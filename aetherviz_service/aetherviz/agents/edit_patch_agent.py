"""Model-assisted, service-applied patches for focused HTML runtime edits."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langsmith import traceable
from langsmith.run_helpers import get_current_run_tree

from aetherviz_service.aetherviz.agents.html_agent import build_html_progress_payload
from aetherviz_service.aetherviz.agents.model_factory import (
    create_chat_model,
    extract_llm_text,
    extract_llm_usage,
)
from aetherviz_service.aetherviz.tools.content_patch import (
    MAX_CONTENT_REPLACEMENT_CHARS,
    apply_content_replacements,
    content_patch_causal_error,
    parse_content_replacements,
    parse_css_declaration_edits,
    select_content_descriptions,
)
from aetherviz_service.aetherviz.tools.edit_targeting import (
    compact_report_context,
    extract_edit_evidence,
)
from aetherviz_service.aetherviz.tools.function_patch import (
    MAX_FUNCTION_REPLACEMENT_CHARS,
    FunctionPatchResult,
    apply_function_replacements,
    parse_function_replacements,
    patch_causal_error,
    select_edit_function_descriptions,
)
from aetherviz_service.config import settings

logger = logging.getLogger(__name__)

EDIT_PATCH_SYSTEM_PROMPT = """你是互动 HTML 的最小结构化补丁工程师。
只输出 JSON：{"replacements":[{"function":"名称","target_id":"原目标 ID","source_hash":"原哈希","replacement":"完整函数源码"}],"css_edits":[{"target_id":"CSS规则目标ID","source_hash":"原哈希","set":{"属性":"值"},"remove":["属性"]}],"blocks":[{"kind":"css_rule|style|visual|semantic","target_id":"原目标 ID","source_hash":"原哈希","replacement":"完整目标块"}]}。
只能替换输入列出的目标并原样返回 kind/function、target_id 与 source_hash；不需要修改的数组输出空数组。不得输出完整 HTML、Markdown 或解释。
函数同名时以 target_id 和 source_hash 区分；HTML 块 replacement 必须保留根标签及原有 id、data-role、data-region，不得加入 script；css_rule 必须保留原 selector，只修改声明。
修改已有 CSS 属性或增删少量属性时必须优先使用 css_edits，由服务端安全序列化；只有新增嵌套规则、伪类、关键帧或其他结构性变化时才输出 css_rule/style 块原文替换。同一 target_id 不得同时出现在 css_edits 和 blocks。
根据用户反馈修复运行时行为，保留函数声明形式、签名、页面结构、教学语义和未点名行为。
错误信息包含具体失败表达式时，必须修改包含该表达式的目标并消除原失败调用，不能只调整播放、暂停、重置等旁支函数。
函数目标的 evidence 描述其位于事件绑定、Runtime 动作、前向调用或共享状态依赖中的原因；运行时故障必须修改该调用切片，不能只修改未被主链调用的 fallback。
动画必须使用独立连续 progress/elapsed/accumulator 推进；离散显示值只能由连续量派生，禁止把 Math.floor/round 后的业务状态作为下一帧累加起点。
优先复用 window.AetherVizAnimationController；原生 requestAnimationFrame 路径必须支持 play/pause/reset/replay/setSpeed，且 setSpeed 必须实际改变时间推进速度。
不得引用未在现有脚本或 replacement 内声明的变量；需要新增跨函数共享声明而目标列表不包含声明时，返回空 replacements 以触发完整 HTML 编辑。
不得引入网络、eval、新框架或第二套并行动画循环。函数替换总长度不得超过 6000 字符，全部 replacement 合计不得超过 12000 字符。"""


@dataclass(frozen=True)
class EditPatchResult:
    html: str
    attempted: bool
    applied: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    finish_reason: str | None = None
    selected_targets: tuple[str, ...] = ()
    content_changed: bool = False
    fallback_reason: str | None = None
    causal_check: str = "not_applicable"
    strategy: str = "function_patch"
    applied_functions: tuple[str, ...] = ()
    applied_blocks: tuple[str, ...] = ()
    output_chars: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    issue_types: tuple[str, ...] = ()
    selection_details: tuple[dict[str, Any], ...] = ()
    applied_operations: tuple[str, ...] = ()
    css_parse_statuses: tuple[str, ...] = ()
    css_stylesheet_statuses: tuple[str, ...] = ()
    allow_full_html_fallback: bool = True


def stream_edit_patch(
    *,
    raw_html: str,
    instruction: str,
    topic: str,
    context: dict[str, Any] | None = None,
) -> Iterator[dict[str, Any] | EditPatchResult]:
    runner = (
        _traced_stream_edit_patch
        if settings.langsmith_tracing and get_current_run_tree() is not None
        else _stream_edit_patch_impl
    )
    yield from runner(raw_html=raw_html, instruction=instruction, topic=topic, context=context)


@traceable(
    name="aetherviz.html_edit_patch",
    run_type="chain",
    metadata={"component": "aetherviz", "stage": "edit_patch"},
    process_inputs=lambda inputs: _trace_targeting_inputs(inputs),
    reduce_fn=lambda items: _summarize(items),
)
def _traced_stream_edit_patch(
    *,
    raw_html: str,
    instruction: str,
    topic: str,
    context: dict[str, Any] | None = None,
) -> Iterator[dict[str, Any] | EditPatchResult]:
    yield from _stream_edit_patch_impl(
        raw_html=raw_html,
        instruction=instruction,
        topic=topic,
        context=context,
    )


def _stream_edit_patch_impl(
    *,
    raw_html: str,
    instruction: str,
    topic: str,
    context: dict[str, Any] | None = None,
) -> Iterator[dict[str, Any] | EditPatchResult]:
    edit_evidence = extract_edit_evidence(instruction, context)
    block_descriptions = select_content_descriptions(raw_html, instruction, context)
    target_selectors = tuple(
        dict.fromkeys(
            selector
            for item in block_descriptions
            for selector in (
                str(item.get("selector") or ""),
                *(str(value) for value in item.get("dependencies", [])),
            )
            if selector
        )
    )
    descriptions = [
        item
        for item in select_edit_function_descriptions(
            raw_html,
            instruction,
            target_selectors=target_selectors,
        )
        if len(item["source"]) <= MAX_FUNCTION_REPLACEMENT_CHARS
    ]
    selected_target_ids = tuple(str(item["target_id"]) for item in descriptions)
    selected_block_ids = tuple(str(item["target_id"]) for item in block_descriptions)
    css_parse_statuses = tuple(
        dict.fromkeys(
            str(item.get("parse_status") or "not_applicable")
            for item in block_descriptions
            if item.get("kind") in {"css_rule", "style"}
        )
    )
    css_stylesheet_statuses = tuple(
        dict.fromkeys(
            str(item.get("stylesheet_parse_status") or "not_applicable")
            for item in block_descriptions
            if item.get("kind") in {"css_rule", "style"}
        )
    )
    allow_full_html_fallback = _allow_full_html_fallback(
        descriptions,
        block_descriptions,
        edit_evidence.issue_types,
    )
    if not descriptions and not block_descriptions:
        yield EditPatchResult(
            html=raw_html,
            attempted=False,
            errors=("no_patch_targets",),
            fallback_reason="no_patch_targets",
            issue_types=edit_evidence.issue_types,
            css_parse_statuses=css_parse_statuses,
            css_stylesheet_statuses=css_stylesheet_statuses,
            allow_full_html_fallback=allow_full_html_fallback,
        )
        return

    yield build_html_progress_payload([{"content": "定位并补丁修复相关运行时函数", "status": "in_progress"}])
    payload = {
        "topic": topic,
        "instruction": instruction,
        "functions": descriptions,
        "blocks": block_descriptions,
        "allowed_functions": [item["function"] for item in descriptions],
        "edit_intent": edit_evidence.as_prompt_payload(),
        "quality_report": compact_report_context(context),
    }
    raw_text = ""
    finish_reason: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    try:
        model = create_chat_model("edit_patch")
        for chunk in model.stream(
            [
                SystemMessage(content=EDIT_PATCH_SYSTEM_PROMPT),
                HumanMessage(content=json.dumps(payload, ensure_ascii=False, separators=(",", ":"))),
            ]
        ):
            raw_text += extract_llm_text(chunk)
            metadata = getattr(chunk, "response_metadata", None)
            if isinstance(metadata, dict) and metadata.get("finish_reason"):
                finish_reason = str(metadata["finish_reason"])
            chunk_input_tokens, chunk_output_tokens = extract_llm_usage(chunk)
            input_tokens = chunk_input_tokens or input_tokens
            output_tokens = chunk_output_tokens or output_tokens
            if len(raw_text) > MAX_CONTENT_REPLACEMENT_CHARS + 2_000:
                finish_reason = finish_reason or "local_length_guard"
                break
        function_replacements = parse_function_replacements(raw_text)
        content_replacements = parse_content_replacements(raw_text)
        css_declaration_edits = parse_css_declaration_edits(raw_text)
        combined_replacement_chars = sum(
            len(item.get("replacement", "")) for item in (*function_replacements, *content_replacements)
        ) + len(json.dumps(css_declaration_edits, ensure_ascii=False, separators=(",", ":")))
        if combined_replacement_chars > MAX_CONTENT_REPLACEMENT_CHARS:
            yield EditPatchResult(
                html=raw_html,
                attempted=True,
                errors=("structured_replacement_too_long",),
                finish_reason=finish_reason,
                selected_targets=(*selected_target_ids, *selected_block_ids),
                fallback_reason="structured_replacement_too_long",
                output_chars=len(raw_text),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                issue_types=edit_evidence.issue_types,
                selection_details=_selection_details(descriptions, block_descriptions),
                css_parse_statuses=css_parse_statuses,
                css_stylesheet_statuses=css_stylesheet_statuses,
                allow_full_html_fallback=allow_full_html_fallback,
            )
            return
        content_patch = apply_content_replacements(
            raw_html,
            content_replacements,
            allowed_descriptions=block_descriptions,
            declaration_edits=css_declaration_edits,
        )
        if function_replacements and not content_patch.errors:
            function_patch = apply_function_replacements(
                content_patch.html,
                function_replacements,
                allowed_functions=tuple(item["function"] for item in descriptions),
                allowed_targets=tuple((str(item["function"]), str(item["source_hash"])) for item in descriptions),
                allowed_target_ids=tuple(str(item["target_id"]) for item in descriptions),
            )
        else:
            function_patch = FunctionPatchResult(html=content_patch.html, applied=())
        patch_errors = (*function_patch.errors, *content_patch.errors)
        applied_functions = function_patch.applied
        applied_blocks = content_patch.applied
        applied = (*applied_functions, *applied_blocks)
        patched_html = function_patch.html
        if patch_errors:
            applied = ()
            applied_functions = ()
            applied_blocks = ()
            patched_html = raw_html
        causal_error = patch_causal_error(raw_html, patched_html, instruction) if function_patch.applied else None
        if not causal_error and applied_blocks:
            applied_block_descriptions = [item for item in block_descriptions if item["target_id"] in applied_blocks]
            causal_error = content_patch_causal_error(
                raw_html,
                patched_html,
                instruction,
                context=context,
                applied_descriptions=applied_block_descriptions,
                function_changed=bool(applied_functions),
            )
        if causal_error:
            patch_errors = (*patch_errors, causal_error)
            applied = ()
            applied_functions = ()
            applied_blocks = ()
            patched_html = raw_html
        content_changed = patched_html != raw_html
        fallback_reason = None
        if not applied:
            fallback_reason = causal_error or (patch_errors[0] if patch_errors else "patch_not_applied")
        yield build_html_progress_payload([{"content": "定位并补丁修复相关运行时函数", "status": "completed"}])
        yield EditPatchResult(
            html=patched_html,
            attempted=True,
            applied=tuple(applied),
            errors=tuple(patch_errors),
            finish_reason=finish_reason,
            selected_targets=(*selected_target_ids, *selected_block_ids),
            content_changed=content_changed,
            fallback_reason=fallback_reason,
            causal_check="failed" if causal_error else "passed" if applied else "not_applicable",
            strategy="structured_patch" if applied_blocks else "function_patch",
            applied_functions=applied_functions,
            applied_blocks=applied_blocks,
            output_chars=len(raw_text),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            issue_types=edit_evidence.issue_types,
            selection_details=_selection_details(descriptions, block_descriptions),
            applied_operations=content_patch.operations,
            css_parse_statuses=css_parse_statuses,
            css_stylesheet_statuses=css_stylesheet_statuses,
            allow_full_html_fallback=allow_full_html_fallback,
        )
    except GeneratorExit:
        raise
    except Exception as exc:
        logger.warning("edit patch failed: %s", exc)
        yield EditPatchResult(
            html=raw_html,
            attempted=True,
            errors=(str(exc),),
            finish_reason=finish_reason,
            selected_targets=(*selected_target_ids, *selected_block_ids),
            fallback_reason="patch_exception",
            output_chars=len(raw_text),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            issue_types=edit_evidence.issue_types,
            selection_details=_selection_details(descriptions, block_descriptions),
            css_parse_statuses=css_parse_statuses,
            css_stylesheet_statuses=css_stylesheet_statuses,
            allow_full_html_fallback=allow_full_html_fallback,
        )


def _summarize(items: list[dict[str, Any] | EditPatchResult]) -> dict[str, Any]:
    result = next((item for item in reversed(items) if isinstance(item, EditPatchResult)), None)
    if result is None:
        return {"completed": False}
    return {
        "completed": True,
        "attempted": result.attempted,
        "accepted": bool(result.applied),
        "rolled_back": result.attempted and not result.applied,
        "applied": list(result.applied),
        "errors": list(result.errors),
        "finish_reason": result.finish_reason,
        "selected_targets": list(result.selected_targets),
        "content_changed": result.content_changed,
        "fallback_reason": result.fallback_reason,
        "causal_check": result.causal_check,
        "strategy": result.strategy,
        "applied_functions": list(result.applied_functions),
        "applied_blocks": list(result.applied_blocks),
        "output_chars": result.output_chars,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "chars_per_output_token": (
            round(result.output_chars / result.output_tokens, 3) if result.output_tokens else None
        ),
        "issue_types": list(result.issue_types),
        "selection_details": list(result.selection_details),
        "selected_by_kind": _count_by_field(result.selection_details, "kind"),
        "selected_by_evidence": _count_selection_evidence(result.selection_details),
        "applied_by_kind": _count_applied_by_kind(result),
        "applied_operations": list(result.applied_operations),
        "css_parse_statuses": list(result.css_parse_statuses),
        "css_stylesheet_statuses": list(result.css_stylesheet_statuses),
        "allow_full_html_fallback": result.allow_full_html_fallback,
    }


def _trace_targeting_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    raw_html = inputs.get("raw_html") or ""
    instruction = inputs.get("instruction") or ""
    context = inputs.get("context") if isinstance(inputs.get("context"), dict) else None
    blocks = select_content_descriptions(raw_html, instruction, context)
    selectors = tuple(str(item.get("selector") or "") for item in blocks if item.get("selector"))
    functions = select_edit_function_descriptions(
        raw_html,
        instruction,
        target_selectors=selectors,
    )
    evidence = extract_edit_evidence(instruction, context)
    return {
        "source_chars": len(raw_html),
        "instruction_chars": len(instruction),
        "issue_types": list(evidence.issue_types),
        "report_context": compact_report_context(context),
        "targets": [
            {
                "function": item["function"],
                "target_id": item["target_id"],
                "line": item["line"],
            }
            for item in functions
        ],
        "block_targets": _selection_details([], blocks),
    }


def _selection_details(functions: list[dict[str, Any]], blocks: list[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    function_details = tuple(
        {
            "kind": "function",
            "target_id": str(item["target_id"]),
            "line": int(item["line"]),
            "score": None,
            "evidence": list(item.get("evidence") or []),
            "region": "runtime",
        }
        for item in functions
    )
    block_details = tuple(
        {
            "kind": str(item["kind"]),
            "target_id": str(item["target_id"]),
            "line": int(item["line"]),
            "score": int(item.get("score") or 0),
            "evidence": list(item.get("evidence") or []),
            "region": str(item.get("region") or ""),
            "selector": str(item.get("selector") or ""),
            "parse_status": str(item.get("parse_status") or "not_applicable"),
            "stylesheet_parse_status": str(
                item.get("stylesheet_parse_status") or "not_applicable"
            ),
            "at_rule_path": list(item.get("at_rule_path") or []),
            "unsupported_at_rules": list(item.get("unsupported_at_rules") or []),
        }
        for item in blocks
    )
    return (*function_details, *block_details)


def _count_by_field(items: tuple[dict[str, Any], ...], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        key = str(item.get(field) or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return counts


def _count_selection_evidence(items: tuple[dict[str, Any], ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        for evidence in item.get("evidence") or []:
            key = str(evidence).split(":", 1)[0]
            counts[key] = counts.get(key, 0) + 1
    return counts


def _count_applied_by_kind(result: EditPatchResult) -> dict[str, int]:
    applied_ids = set(result.applied)
    return _count_by_field(
        tuple(item for item in result.selection_details if item.get("target_id") in applied_ids),
        "kind",
    )


def _allow_full_html_fallback(
    functions: list[dict[str, Any]],
    blocks: list[dict[str, Any]],
    issue_types: tuple[str, ...],
) -> bool:
    css_targets = [item for item in blocks if item.get("kind") in {"css_rule", "style"}]
    if not css_targets:
        return True
    cross_runtime = bool(functions) and any(
        issue in issue_types for issue in ("runtime_error", "control_issue", "visual_not_visible")
    )
    return cross_runtime
