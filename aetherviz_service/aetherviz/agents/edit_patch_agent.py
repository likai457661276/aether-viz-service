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
    parse_content_replacements,
    select_content_descriptions,
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
只输出 JSON：{"replacements":[{"function":"名称","target_id":"原目标 ID","source_hash":"原哈希","replacement":"完整函数源码"}],"blocks":[{"kind":"style|visual|semantic","target_id":"原目标 ID","source_hash":"原哈希","replacement":"完整目标块"}]}。
只能替换输入列出的目标并原样返回 kind/function、target_id 与 source_hash；不需要修改的数组输出空数组。不得输出完整 HTML、Markdown 或解释。
函数同名时以 target_id 和 source_hash 区分；块 replacement 必须保留根标签及原有 id、data-role、data-region，不得加入 script。
根据用户反馈修复运行时行为，保留函数声明形式、签名、页面结构、教学语义和未点名行为。
错误信息包含具体失败表达式时，必须修改包含该表达式的目标并消除原失败调用，不能只调整播放、暂停、重置等旁支函数。
动画必须使用独立连续 progress/elapsed/accumulator 推进；离散显示值只能由连续量派生，禁止把 Math.floor/round 后的业务状态作为下一帧累加起点。
优先复用 window.AetherVizAnimationController；原生 requestAnimationFrame 路径必须支持 play/pause/reset/replay/setSpeed，且 setSpeed 必须实际改变时间推进速度。
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


def stream_edit_patch(
    *, raw_html: str, instruction: str, topic: str
) -> Iterator[dict[str, Any] | EditPatchResult]:
    runner = (
        _traced_stream_edit_patch
        if settings.langsmith_tracing and get_current_run_tree() is not None
        else _stream_edit_patch_impl
    )
    yield from runner(raw_html=raw_html, instruction=instruction, topic=topic)


@traceable(
    name="aetherviz.html_edit_patch",
    run_type="chain",
    metadata={"component": "aetherviz", "stage": "edit_patch"},
    process_inputs=lambda inputs: {
        "source_chars": len(inputs.get("raw_html") or ""),
        "instruction_chars": len(inputs.get("instruction") or ""),
        "targets": [
            {
                "function": item["function"],
                "target_id": item["target_id"],
                "line": item["line"],
            }
            for item in select_edit_function_descriptions(
                inputs.get("raw_html") or "", inputs.get("instruction") or ""
            )
        ],
        "block_targets": [
            {
                "kind": item["kind"],
                "target_id": item["target_id"],
                "line": item["line"],
            }
            for item in select_content_descriptions(
                inputs.get("raw_html") or "", inputs.get("instruction") or ""
            )
        ],
    },
    reduce_fn=lambda items: _summarize(items),
)
def _traced_stream_edit_patch(
    *, raw_html: str, instruction: str, topic: str
) -> Iterator[dict[str, Any] | EditPatchResult]:
    yield from _stream_edit_patch_impl(raw_html=raw_html, instruction=instruction, topic=topic)


def _stream_edit_patch_impl(
    *, raw_html: str, instruction: str, topic: str
) -> Iterator[dict[str, Any] | EditPatchResult]:
    descriptions = [
        item
        for item in select_edit_function_descriptions(raw_html, instruction)
        if len(item["source"]) <= MAX_FUNCTION_REPLACEMENT_CHARS
    ]
    block_descriptions = select_content_descriptions(raw_html, instruction)
    selected_target_ids = tuple(str(item["target_id"]) for item in descriptions)
    selected_block_ids = tuple(str(item["target_id"]) for item in block_descriptions)
    if not descriptions and not block_descriptions:
        yield EditPatchResult(
            html=raw_html,
            attempted=False,
            errors=("no_patch_targets",),
            fallback_reason="no_patch_targets",
        )
        return

    yield build_html_progress_payload(
        [{"content": "定位并补丁修复相关运行时函数", "status": "in_progress"}]
    )
    payload = {
        "topic": topic,
        "instruction": instruction,
        "functions": descriptions,
        "blocks": block_descriptions,
        "allowed_functions": [item["function"] for item in descriptions],
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
        combined_replacement_chars = sum(
            len(item.get("replacement", ""))
            for item in (*function_replacements, *content_replacements)
        )
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
            )
            return
        if function_replacements:
            function_patch = apply_function_replacements(
                raw_html,
                function_replacements,
                allowed_functions=tuple(item["function"] for item in descriptions),
                allowed_targets=tuple(
                    (str(item["function"]), str(item["source_hash"])) for item in descriptions
                ),
                allowed_target_ids=tuple(str(item["target_id"]) for item in descriptions),
            )
        else:
            function_patch = FunctionPatchResult(html=raw_html, applied=())
        content_patch = apply_content_replacements(
            function_patch.html,
            content_replacements,
            allowed_descriptions=block_descriptions,
        )
        patch_errors = (*function_patch.errors, *content_patch.errors)
        applied_functions = function_patch.applied
        applied_blocks = content_patch.applied
        applied = (*applied_functions, *applied_blocks)
        patched_html = content_patch.html
        if patch_errors:
            applied = ()
            applied_functions = ()
            applied_blocks = ()
            patched_html = raw_html
        causal_error = (
            patch_causal_error(raw_html, patched_html, instruction) if function_patch.applied else None
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
        yield build_html_progress_payload(
            [{"content": "定位并补丁修复相关运行时函数", "status": "completed"}]
        )
        yield EditPatchResult(
            html=patched_html,
            attempted=True,
            applied=tuple(applied),
            errors=tuple(patch_errors),
            finish_reason=finish_reason,
            selected_targets=(*selected_target_ids, *selected_block_ids),
            content_changed=content_changed,
            fallback_reason=fallback_reason,
            causal_check="failed" if causal_error else "passed" if function_patch.applied else "not_applicable",
            strategy="structured_patch" if applied_blocks else "function_patch",
            applied_functions=applied_functions,
            applied_blocks=applied_blocks,
            output_chars=len(raw_text),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
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
    }
