"""Structured edit diagnosis using the fast planning model."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass
from typing import Any, Literal

from bs4 import BeautifulSoup
from langchain_core.messages import HumanMessage, SystemMessage
from langsmith import traceable
from langsmith.run_helpers import get_current_run_tree

from aetherviz_service.aetherviz.agents.model_factory import create_chat_model, extract_llm_text, has_primary_llm_config
from aetherviz_service.aetherviz.tools.function_patch import extract_named_functions

logger = logging.getLogger(__name__)

EditStrategy = Literal[
    "css_declaration",
    "text_or_attribute",
    "function_repair",
    "dom_block",
    "full_html_regeneration",
    "clarification_required",
]

EDIT_DIAGNOSIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "intent",
        "scope",
        "strategy",
        "problem",
        "confidence",
        "resolved_instruction",
        "change_requirements",
        "preserve_requirements",
        "impact_areas",
        "acceptance_criteria",
        "ambiguities",
        "targets",
        "operations",
        "assertions",
        "allowed_scope",
        "requires_clarification",
        "clarification_question",
    ],
    "properties": {
        "intent": {"type": "string", "maxLength": 120},
        "scope": {"type": "string", "maxLength": 120},
        "strategy": {
            "type": "string",
            "enum": [
                "full_html_regeneration",
                "clarification_required",
            ],
        },
        "problem": {"type": "string", "maxLength": 800},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "resolved_instruction": {"type": "string", "maxLength": 1600},
        "change_requirements": {
            "type": "array",
            "maxItems": 10,
            "items": {"type": "string", "maxLength": 500},
        },
        "preserve_requirements": {
            "type": "array",
            "maxItems": 10,
            "items": {"type": "string", "maxLength": 500},
        },
        "impact_areas": {
            "type": "array",
            "maxItems": 9,
            "items": {
                "type": "string",
                "enum": ["shell_content", "dom", "css", "svg_canvas", "state", "render", "events", "animation", "runtime"],
            },
        },
        "acceptance_criteria": {
            "type": "array",
            "maxItems": 10,
            "items": {"type": "string", "maxLength": 500},
        },
        "ambiguities": {
            "type": "array",
            "maxItems": 6,
            "items": {"type": "string", "maxLength": 500},
        },
        "targets": {
            "type": "array",
            "maxItems": 5,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["kind", "selector", "function", "source_hash", "evidence", "confidence"],
                "properties": {
                    "kind": {"type": "string", "enum": ["dom", "css", "function", "server_layout", "unknown"]},
                    "selector": {"type": "string", "maxLength": 240},
                    "function": {"type": "string", "maxLength": 120},
                    "source_hash": {"type": "string", "maxLength": 80},
                    "evidence": {"type": "string", "maxLength": 500},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
            },
        },
        "operations": {
            "type": "array",
            "maxItems": 6,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["op", "selector", "property", "value", "old_text", "new_text", "attribute"],
                "properties": {
                    "op": {"type": "string", "enum": ["set_css", "replace_text", "set_attribute", "replace_function"]},
                    "selector": {"type": "string", "maxLength": 240},
                    "property": {"type": "string", "maxLength": 100},
                    "value": {"type": "string", "maxLength": 500},
                    "old_text": {"type": "string", "maxLength": 500},
                    "new_text": {"type": "string", "maxLength": 500},
                    "attribute": {"type": "string", "maxLength": 100},
                },
            },
        },
        "assertions": {
            "type": "array",
            "maxItems": 8,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["type", "selector", "property", "expected"],
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": [
                            "selector_exists",
                            "text_contains",
                            "attribute_equals",
                            "css_declaration",
                            "runtime_error_absent",
                        ],
                    },
                    "selector": {"type": "string", "maxLength": 240},
                    "property": {"type": "string", "maxLength": 100},
                    "expected": {"type": "string", "maxLength": 500},
                },
            },
        },
        "allowed_scope": {"type": "array", "maxItems": 8, "items": {"type": "string", "maxLength": 240}},
        "requires_clarification": {"type": "boolean"},
        "clarification_question": {"type": "string", "maxLength": 500},
    },
}

EDIT_DIAGNOSIS_SYSTEM_PROMPT = """你是 AetherViz HTML 编辑需求编译器，只负责把用户输入整理为可直接驱动完整 HTML 重生成的结构化任务，不生成 HTML、CSS 或 JavaScript 源码。
根据当前 instruction、当前 HTML 的确定性摘要、可选选中元素、运行时错误和最近对话，消除“再快一点”“刚才那个”等指代，形成完整、自包含且可观察验收的编辑任务。
规则：
1. 证据只能引用摘要中真实存在的 selector、函数、样式、错误或服务端所有权信息，不得编造。
2. resolved_instruction 必须是无指代、无歧义、可独立执行的完整中文要求；当前 instruction 优先，recent_messages 和 memory 只用于解释指代，不得恢复已被当前输入否定的旧要求。
3. change_requirements 描述必须产生的可观察变化；preserve_requirements 描述不能意外改变的教学内容和交互；acceptance_criteria 描述结果表现，不限定必须修改某个函数或采用某种实现。
4. impact_areas 必须覆盖实现该要求可能涉及的完整链路。动画变化重点检查 events -> state -> render -> animation -> reset/replay，不得只定位到一个函数。
5. 执行阶段固定为完整 HTML 重生成，通常使用 full_html_regeneration，不再选择 CSS、文本或函数局部补丁策略。operations 和 allowed_scope 保持空数组。
6. 用户通常描述可见现象而不是准确实现位置。即使输入提到“控制面板、外壳、侧栏、布局、挤压”等词，也必须结合当前 HTML、选中目标、运行时错误和对话判断真实意图；不得仅凭这些词拒绝编辑。若真实问题是主视觉尺寸、裁切、标签、业务控件密度或动画内容，应编译为对应业务 HTML 修改任务。
7. 外壳中的标题、学习目标和目标列表属于可编辑内容，使用 shell_content 影响域；控制区、说明区、公式区和教学流程本来就是业务内容。math-shell-v1、.av-*、#aetherviz-app-shell 的具体宽度、分栏、滚动和响应式仍由服务端重建；用户对这些结构提出的诉求，应转换为业务内容优先级、槽位内部自适应、主视觉 viewBox/Canvas 尺寸、控件组织或内容精简等可执行要求，而不是要求模型仿制外壳。
8. 用户明确要求“全部修改、整体重做、重新设计”时，允许重做全部可编辑内容，包括外壳文案、教学文案、主视觉、业务控件、状态、渲染、事件和动画运行时；只保留用户明确要求保留的内容及核心 Widget 运行契约。
9. 只有缺少的信息会导致多个实质不同结果、且无法从当前 HTML、edit_target 或最近对话推断时，才使用 clarification_required；同时列出 ambiguities 并给出一个最小澄清问题。一般性的视觉或动画优化应直接形成合理任务，不要澄清。
只输出符合 JSON Schema 的对象。"""


@dataclass(frozen=True)
class EditDiagnosis:
    intent: str
    scope: str
    strategy: EditStrategy
    problem: str
    confidence: float
    resolved_instruction: str = ""
    change_requirements: tuple[str, ...] = ()
    preserve_requirements: tuple[str, ...] = ()
    impact_areas: tuple[str, ...] = ()
    acceptance_criteria: tuple[str, ...] = ()
    ambiguities: tuple[str, ...] = ()
    targets: tuple[dict[str, Any], ...] = ()
    operations: tuple[dict[str, str], ...] = ()
    assertions: tuple[dict[str, str], ...] = ()
    allowed_scope: tuple[str, ...] = ()
    requires_clarification: bool = False
    clarification_question: str = ""
    degraded: bool = False
    fallback_reason: str = ""

    def public_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["targets"] = list(self.targets)
        value["change_requirements"] = list(self.change_requirements)
        value["preserve_requirements"] = list(self.preserve_requirements)
        value["impact_areas"] = list(self.impact_areas)
        value["acceptance_criteria"] = list(self.acceptance_criteria)
        value["ambiguities"] = list(self.ambiguities)
        value["operations"] = list(self.operations)
        value["assertions"] = list(self.assertions)
        value["allowed_scope"] = list(self.allowed_scope)
        return value


def diagnose_edit(
    *,
    instruction: str,
    business_html: str,
    context_summary: dict[str, Any],
) -> EditDiagnosis:
    runner = _traced_diagnose_edit if get_current_run_tree() is not None else _diagnose_edit_impl
    return runner(instruction=instruction, business_html=business_html, context_summary=context_summary)


@traceable(
    name="aetherviz.edit_diagnosis",
    run_type="chain",
    metadata={"component": "aetherviz", "stage": "edit_diagnosis"},
    process_inputs=lambda inputs: {
        "instruction_chars": len(inputs.get("instruction") or ""),
        "business_chars": len(inputs.get("business_html") or ""),
        "has_runtime_error": bool((inputs.get("context_summary") or {}).get("runtime_error")),
        "has_edit_target": bool((inputs.get("context_summary") or {}).get("edit_target")),
        "dom_target_count": len(((inputs.get("context_summary") or {}).get("document") or {}).get("dom_targets", [])),
        "function_count": len(((inputs.get("context_summary") or {}).get("document") or {}).get("functions", [])),
        "summary_chars": (inputs.get("context_summary") or {}).get("summary_chars", 0),
        "summary_truncated": bool((inputs.get("context_summary") or {}).get("summary_truncated")),
    },
    process_outputs=lambda output: {
        "strategy": output.strategy,
        "scope": output.scope,
        "confidence": output.confidence,
        "target_count": len(output.targets),
        "requirement_count": len(output.change_requirements),
        "acceptance_criteria_count": len(output.acceptance_criteria),
        "resolved_instruction_chars": len(output.resolved_instruction),
        "degraded": output.degraded,
        "fallback_reason": output.fallback_reason,
    },
)
def _traced_diagnose_edit(
    *,
    instruction: str,
    business_html: str,
    context_summary: dict[str, Any],
) -> EditDiagnosis:
    return _diagnose_edit_impl(
        instruction=instruction,
        business_html=business_html,
        context_summary=context_summary,
    )


def _diagnose_edit_impl(
    *,
    instruction: str,
    business_html: str,
    context_summary: dict[str, Any],
) -> EditDiagnosis:
    if not has_primary_llm_config():
        return _fallback_diagnosis(instruction, context_summary, "model_unavailable")
    try:
        messages = [
            SystemMessage(content=EDIT_DIAGNOSIS_SYSTEM_PROMPT),
            HumanMessage(content=json.dumps(context_summary, ensure_ascii=False, separators=(",", ":"))),
        ]
        try:
            response = create_chat_model("edit_analysis", response_schema=EDIT_DIAGNOSIS_SCHEMA).invoke(messages)
            payload = _parse_json_object(extract_llm_text(response))
        except Exception as strict_error:
            logger.info("strict edit diagnosis response failed, retrying JSON object mode: %s", strict_error)
            response = create_chat_model("edit_analysis").invoke(messages)
            payload = _parse_json_object(extract_llm_text(response))
        return _normalize_diagnosis(payload, instruction=instruction, business_html=business_html)
    except Exception as exc:
        logger.warning("edit diagnosis failed, falling back to full regeneration: %s", exc)
        return _fallback_diagnosis(instruction, context_summary, type(exc).__name__)


def _normalize_diagnosis(payload: dict[str, Any], *, instruction: str, business_html: str) -> EditDiagnosis:
    strategies = {"full_html_regeneration", "clarification_required"}
    strategy = str(payload.get("strategy") or "full_html_regeneration")
    if strategy not in strategies:
        strategy = "full_html_regeneration"
    targets = tuple(dict(item) for item in payload.get("targets", [])[:5] if isinstance(item, dict))
    operations = tuple(_string_mapping(item) for item in payload.get("operations", [])[:6] if isinstance(item, dict))
    assertions = tuple(_string_mapping(item) for item in payload.get("assertions", [])[:8] if isinstance(item, dict))
    allowed_scope = tuple(str(item)[:240] for item in payload.get("allowed_scope", [])[:8])
    confidence = _confidence(payload.get("confidence"))
    requires_clarification = bool(payload.get("requires_clarification"))
    question = str(payload.get("clarification_question") or "")[:500]
    resolved_instruction = str(payload.get("resolved_instruction") or instruction).strip()[:1600]
    change_requirements = _string_list(payload.get("change_requirements"), limit=10, chars=500)
    preserve_requirements = _string_list(payload.get("preserve_requirements"), limit=10, chars=500)
    allowed_impact_areas = {
        "shell_content",
        "dom",
        "css",
        "svg_canvas",
        "state",
        "render",
        "events",
        "animation",
        "runtime",
    }
    impact_areas = tuple(
        area for area in _string_list(payload.get("impact_areas"), limit=9, chars=40) if area in allowed_impact_areas
    )
    acceptance_criteria = _string_list(payload.get("acceptance_criteria"), limit=10, chars=500)
    ambiguities = _string_list(payload.get("ambiguities"), limit=6, chars=500)

    soup = BeautifulSoup(business_html or "", "html.parser")
    functions = extract_named_functions(business_html)
    for item in targets:
        selector = str(item.get("selector") or "")
        if selector and not _selector_exists(soup, selector):
            item["selector"] = ""
        function_name = str(item.get("function") or "")
        if function_name:
            item["source_hash"] = (
                functions[function_name][0].source_hash if len(functions.get(function_name, [])) == 1 else ""
            )
    can_block_for_clarification = bool(
        requires_clarification and ambiguities and question and confidence >= 0.85 and not targets
    )
    if can_block_for_clarification:
        strategy = "clarification_required"
    else:
        requires_clarification = False
        if strategy == "clarification_required":
            strategy = "full_html_regeneration"

    return EditDiagnosis(
        intent=str(payload.get("intent") or "edit_html")[:120],
        scope=str(payload.get("scope") or "business_html")[:120],
        strategy=strategy,  # type: ignore[arg-type]
        problem=str(payload.get("problem") or "根据用户意见修改当前 HTML")[:800],
        confidence=confidence,
        resolved_instruction=resolved_instruction,
        change_requirements=change_requirements,
        preserve_requirements=preserve_requirements,
        impact_areas=impact_areas,
        acceptance_criteria=acceptance_criteria,
        ambiguities=ambiguities,
        targets=targets,
        operations=operations,
        assertions=assertions,
        allowed_scope=allowed_scope,
        requires_clarification=requires_clarification,
        clarification_question=question,
    )


def _fallback_diagnosis(
    instruction: str,
    context_summary: dict[str, Any],
    reason: str,
) -> EditDiagnosis:
    runtime_error = context_summary.get("runtime_error") or {}
    return EditDiagnosis(
        intent="fix_runtime_error" if runtime_error else "edit_html",
        scope="business_runtime" if runtime_error else "business_html",
        strategy="full_html_regeneration",
        problem=str(runtime_error.get("message") or "根据用户意见修改当前 HTML")[:800],
        confidence=0.4,
        resolved_instruction=instruction.strip()[:1600],
        change_requirements=(instruction.strip()[:500],) if instruction.strip() else (),
        preserve_requirements=("保持未要求修改的教学内容、核心交互和视觉层级",),
        impact_areas=("runtime", "state", "render") if runtime_error else ("dom", "css", "render"),
        acceptance_criteria=("用户要求的变化在最终页面中可观察且核心交互仍可用",),
        degraded=True,
        fallback_reason=reason,
    )


def _parse_json_object(raw_text: str) -> dict[str, Any]:
    text = (raw_text or "").strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        text = match.group(0)
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("edit diagnosis must be a JSON object")
    return payload


def _selector_exists(soup: BeautifulSoup, selector: str) -> bool:
    if not selector or selector.startswith(".av-") or selector.startswith("#aetherviz-app-shell"):
        return False
    try:
        return bool(soup.select(selector))
    except Exception:
        return False


def _string_mapping(value: dict[str, Any]) -> dict[str, str]:
    return {str(key): str(raw or "") for key, raw in value.items()}


def _string_list(value: Any, *, limit: int, chars: int) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(text for item in value[:limit] if (text := str(item or "").strip()[:chars]))


def _confidence(value: Any) -> float:
    try:
        return min(max(float(value), 0.0), 1.0)
    except (TypeError, ValueError):
        return 0.0
