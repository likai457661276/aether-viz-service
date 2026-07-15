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
from aetherviz_service.aetherviz.agents.model_factory import create_chat_model, extract_llm_text
from aetherviz_service.aetherviz.tools.function_patch import (
    MAX_FUNCTION_REPLACEMENT_CHARS,
    apply_function_replacements,
    describe_target_functions,
    parse_function_replacements,
    select_edit_function_targets,
)
from aetherviz_service.config import settings

logger = logging.getLogger(__name__)

EDIT_PATCH_SYSTEM_PROMPT = """你是互动 HTML 的 JavaScript 最小补丁工程师。
只输出 JSON：{"replacements":[{"function":"名称","source_hash":"原哈希","replacement":"完整函数/方法/箭头函数源码"}]}。
只能替换输入列出的函数并原样返回 source_hash；不得输出完整 HTML、CSS、Markdown 或解释。
根据用户反馈修复运行时行为，保留函数声明形式、签名、页面结构、教学语义和未点名行为。
动画必须使用独立连续 progress/elapsed/accumulator 推进；离散显示值只能由连续量派生，禁止把 Math.floor/round 后的业务状态作为下一帧累加起点。
优先复用 window.AetherVizAnimationController；原生 requestAnimationFrame 路径必须支持 play/pause/reset/replay/setSpeed，且 setSpeed 必须实际改变时间推进速度。
不得引入网络、eval、新框架或第二套并行动画循环。替换总长度不得超过 6000 字符。"""


@dataclass(frozen=True)
class EditPatchResult:
    html: str
    attempted: bool
    applied: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    finish_reason: str | None = None


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
        "targets": list(
            select_edit_function_targets(
                inputs.get("raw_html") or "", inputs.get("instruction") or ""
            )
        ),
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
    targets = select_edit_function_targets(raw_html, instruction)
    descriptions = [
        item
        for item in describe_target_functions(raw_html, targets)
        if len(item["source"]) <= MAX_FUNCTION_REPLACEMENT_CHARS
    ]
    if not descriptions:
        yield EditPatchResult(html=raw_html, attempted=False, errors=("no_patch_targets",))
        return

    yield build_html_progress_payload(
        [{"content": "定位并补丁修复相关运行时函数", "status": "in_progress"}]
    )
    payload = {
        "topic": topic,
        "instruction": instruction,
        "functions": descriptions,
        "allowed_functions": [item["function"] for item in descriptions],
    }
    raw_text = ""
    finish_reason: str | None = None
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
            if len(raw_text) > MAX_FUNCTION_REPLACEMENT_CHARS + 2_000:
                finish_reason = finish_reason or "local_length_guard"
                break
        patch = apply_function_replacements(
            raw_html,
            parse_function_replacements(raw_text),
            allowed_functions=tuple(item["function"] for item in descriptions),
        )
        yield build_html_progress_payload(
            [{"content": "定位并补丁修复相关运行时函数", "status": "completed"}]
        )
        yield EditPatchResult(
            html=patch.html,
            attempted=True,
            applied=patch.applied,
            errors=patch.errors,
            finish_reason=finish_reason,
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
    }
