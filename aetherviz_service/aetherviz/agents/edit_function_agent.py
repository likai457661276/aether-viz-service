"""Hash-guarded function editing driven by structured edit diagnosis."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langsmith import traceable
from langsmith.run_helpers import get_current_run_tree

from aetherviz_service.aetherviz.agents.edit_diagnosis_agent import EditDiagnosis
from aetherviz_service.aetherviz.agents.html_agent import HtmlStreamResult, build_html_progress_payload
from aetherviz_service.aetherviz.agents.model_factory import create_chat_model, extract_llm_text, has_primary_llm_config
from aetherviz_service.aetherviz.limits import MAX_FUNCTION_REPLACEMENT_CHARS
from aetherviz_service.aetherviz.tools.function_patch import (
    apply_function_replacements,
    describe_target_functions,
    parse_function_replacements,
)

logger = logging.getLogger(__name__)

EDIT_FUNCTION_SYSTEM_PROMPT = f"""你是 JavaScript 函数级定向编辑器。
只输出 JSON：{{"replacements":[{{"function":"函数名","source_hash":"原哈希","replacement":"完整函数源码"}}]}}。
只能修改输入列出的函数并原样返回 source_hash，不输出完整 HTML、CSS、Markdown 或解释。
根据用户意见、运行时错误和诊断结论修复根因；保留函数签名、教学含义、状态模型与未要求修改的行为。
不得增加吞错 try/catch、空值 early-return、eval、网络请求、新动画循环或外部依赖。
若涉及动画，继续复用 window.AetherVizAnimationController，确保播放、暂停、重置和重复播放保持一致。
替换总长度不得超过 {MAX_FUNCTION_REPLACEMENT_CHARS} 字符。"""


def stream_edit_functions(
    *,
    raw_html: str,
    instruction: str,
    diagnosis: EditDiagnosis,
    runtime_error: dict[str, Any] | None,
) -> Iterator[dict[str, Any] | HtmlStreamResult]:
    runner = _traced_stream_edit_functions if get_current_run_tree() is not None else _stream_edit_functions_impl
    yield from runner(
        raw_html=raw_html,
        instruction=instruction,
        diagnosis=diagnosis,
        runtime_error=runtime_error,
    )


@traceable(
    name="aetherviz.edit_function_patch",
    run_type="chain",
    metadata={"component": "aetherviz", "stage": "edit_function_patch"},
    process_inputs=lambda inputs: {
        "source_chars": len(inputs.get("raw_html") or ""),
        "instruction_chars": len(inputs.get("instruction") or ""),
        "target_functions": [
            item.get("function")
            for item in getattr(inputs.get("diagnosis"), "targets", ())
            if item.get("function")
        ],
        "has_runtime_error": bool(inputs.get("runtime_error")),
    },
    reduce_fn=lambda items: _summarize(items),
)
def _traced_stream_edit_functions(**kwargs: Any) -> Iterator[dict[str, Any] | HtmlStreamResult]:
    yield from _stream_edit_functions_impl(**kwargs)


def _stream_edit_functions_impl(
    *,
    raw_html: str,
    instruction: str,
    diagnosis: EditDiagnosis,
    runtime_error: dict[str, Any] | None,
) -> Iterator[dict[str, Any] | HtmlStreamResult]:
    targets = tuple(
        dict.fromkeys(
            str(item.get("function") or "")
            for item in diagnosis.targets
            if str(item.get("function") or "")
        )
    )[:3]
    descriptions = describe_target_functions(raw_html, targets)
    if not descriptions or not has_primary_llm_config():
        return
    yield build_html_progress_payload([{"content": "按诊断结果修复目标函数", "status": "in_progress"}])
    prompt = json.dumps(
        {
            "instruction": instruction,
            "diagnosis": {
                "problem": diagnosis.problem,
                "scope": diagnosis.scope,
                "allowed_scope": list(diagnosis.allowed_scope),
            },
            "runtime_error": runtime_error or {},
            "functions": descriptions,
            "allowed_functions": [item["function"] for item in descriptions],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    raw_text = ""
    try:
        model = create_chat_model("repair")
        for chunk in model.stream(
            [SystemMessage(content=EDIT_FUNCTION_SYSTEM_PROMPT), HumanMessage(content=prompt)]
        ):
            raw_text += extract_llm_text(chunk)
            if len(raw_text) > MAX_FUNCTION_REPLACEMENT_CHARS + 2000:
                break
        replacements = parse_function_replacements(raw_text)
        patch = apply_function_replacements(
            raw_html,
            replacements,
            allowed_functions=tuple(item["function"] for item in descriptions),
            allowed_targets=tuple((item["function"], item["source_hash"]) for item in descriptions),
        )
        if not patch.applied:
            logger.warning("diagnosed function edit did not apply: %s", patch.errors)
            return
        yield build_html_progress_payload([{"content": "按诊断结果修复目标函数", "status": "completed"}])
        yield HtmlStreamResult(
            html=patch.html,
            degraded=False,
            strategy="function_patch",
            source_chars=len(raw_html),
            patch_functions=patch.applied,
            output_chars=len(raw_text),
        )
    except GeneratorExit:
        raise
    except Exception as exc:
        logger.warning("diagnosed function edit failed: %s", exc)


def _summarize(items: list[dict[str, Any] | HtmlStreamResult]) -> dict[str, Any]:
    result = next((item for item in reversed(items) if isinstance(item, HtmlStreamResult)), None)
    return {
        "completed": result is not None,
        "strategy": result.strategy if result else None,
        "functions": list(result.patch_functions) if result else [],
    }
