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
from aetherviz_service.aetherviz.tools.edit_context import is_server_layout_request
from aetherviz_service.aetherviz.tools.function_patch import extract_named_functions

logger = logging.getLogger(__name__)

EditStrategy = Literal[
    "css_declaration",
    "text_or_attribute",
    "function_repair",
    "dom_block",
    "full_html_regeneration",
    "server_owned_rejected",
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
                "css_declaration",
                "text_or_attribute",
                "function_repair",
                "dom_block",
                "full_html_regeneration",
                "server_owned_rejected",
                "clarification_required",
            ],
        },
        "problem": {"type": "string", "maxLength": 800},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
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
                        "enum": ["selector_exists", "text_contains", "attribute_equals", "css_declaration", "runtime_error_absent"],
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

EDIT_DIAGNOSIS_SYSTEM_PROMPT = """你是 AetherViz HTML 编辑诊断器，只负责定位和规划，不生成 HTML、CSS 或 JavaScript 源码。
根据用户本次意见与服务端提供的确定性摘要，判断问题目标、所有权、最小编辑策略和可验证断言。
规则：
1. 证据只能引用摘要中真实存在的 selector、函数、样式、错误或服务端所有权信息，不得编造。
2. 单个明确 CSS 属性使用 css_declaration；精确文案/属性使用 text_or_attribute；运行时报错且能定位唯一函数时使用 function_repair；局部结构变化使用 dom_block；真正的大改才使用 full_html_regeneration。
3. math-shell-v1、.av-*、#aetherviz-app-shell 的宽度、分栏、滚动和响应式属于服务端，使用 server_owned_rejected。
4. 目标不唯一且无法安全选择时使用 clarification_required，并给出一个最小澄清问题。
5. operations 只描述小型确定性操作；function_repair 不输出函数源码，operations 可为空。
6. recent_messages 和 memory 仅用于消歧，当前 instruction 与当前 HTML 摘要始终优先。
只输出符合 JSON Schema 的对象。"""


@dataclass(frozen=True)
class EditDiagnosis:
    intent: str
    scope: str
    strategy: EditStrategy
    problem: str
    confidence: float
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
        "operation_count": len(output.operations),
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
    if is_server_layout_request(instruction):
        return EditDiagnosis(
            intent="server_layout_change",
            scope="server_layout",
            strategy="server_owned_rejected",
            problem="修改目标属于服务端统一页面外壳",
            confidence=1.0,
            targets=({"kind": "server_layout", "evidence": "deterministic ownership match", "confidence": 1.0},),
        )
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
    strategies = {
        "css_declaration",
        "text_or_attribute",
        "function_repair",
        "dom_block",
        "full_html_regeneration",
        "server_owned_rejected",
        "clarification_required",
    }
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

    soup = BeautifulSoup(business_html or "", "html.parser")
    functions = extract_named_functions(business_html)
    if strategy in {"css_declaration", "text_or_attribute", "dom_block"}:
        selectors = [str(item.get("selector") or "") for item in targets if item.get("selector")]
        if not selectors or not all(_selector_exists(soup, selector) for selector in selectors):
            strategy = "clarification_required" if confidence < 0.75 else "full_html_regeneration"
            requires_clarification = strategy == "clarification_required"
            question = question or "请指出需要修改的具体元素、文字或页面区域。"
    if strategy == "function_repair":
        function_targets = [str(item.get("function") or "") for item in targets if item.get("function")]
        if not function_targets or not all(len(functions.get(name, [])) == 1 for name in function_targets):
            strategy = "full_html_regeneration"
        else:
            for item in targets:
                function_name = str(item.get("function") or "")
                if function_name:
                    item["source_hash"] = functions[function_name][0].source_hash
    if strategy == "server_owned_rejected" and not is_server_layout_request(instruction):
        has_server_evidence = any(item.get("kind") == "server_layout" for item in targets)
        if not has_server_evidence:
            strategy = "full_html_regeneration"
    if requires_clarification:
        strategy = "clarification_required"

    return EditDiagnosis(
        intent=str(payload.get("intent") or "edit_html")[:120],
        scope=str(payload.get("scope") or "business_html")[:120],
        strategy=strategy,  # type: ignore[arg-type]
        problem=str(payload.get("problem") or "根据用户意见修改当前 HTML")[:800],
        confidence=confidence,
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


def _confidence(value: Any) -> float:
    try:
        return min(max(float(value), 0.0), 1.0)
    except (TypeError, ValueError):
        return 0.0
