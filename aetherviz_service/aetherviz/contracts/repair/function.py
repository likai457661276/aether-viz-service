"""Model-assisted, service-applied JavaScript function repair."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langsmith import traceable
from langsmith.run_helpers import get_current_run_tree

from aetherviz_service.aetherviz.contracts.html_stream import build_html_progress_payload
from aetherviz_service.aetherviz.agents.model_factory import create_chat_model, extract_llm_text, has_primary_llm_config
from aetherviz_service.aetherviz.tools.function_patch import (
    MAX_FUNCTION_REPLACEMENT_CHARS,
    apply_function_replacements,
    describe_target_functions,
    parse_function_replacements,
    repair_function_targets,
)
from aetherviz_service.config import settings

logger = logging.getLogger(__name__)

FUNCTION_REPAIR_SYSTEM_PROMPT = f"""你是 JavaScript 函数级最小变更修复器。
只输出一个 JSON 对象：{{"replacements":[{{"function":"函数名","source_hash":"原哈希","replacement":"完整函数声明"}}]}}。
只能替换输入中列出的函数，必须原样返回 source_hash；不得输出完整 HTML、CSS、Markdown 或解释。
只修复检查报告点名的逐帧结构修改：动画帧内只能更新已有节点属性，结构创建/清空必须留在初始化或显式重建阶段。
输入可能包含一个伴随的场景构建函数。若逐帧函数处理可变节点数量，必须同时修改场景构建函数，按已有变量上界预分配有界节点池，再在逐帧函数中仅更新属性并用 hidden/display 控制启用数量。
禁止在逐帧函数中通过 while/for + createElement/appendChild/removeChild、innerHTML、replaceChildren 或“仅首次执行”的条件分支增删节点；这仍属于逐帧结构修改。
保留函数签名、业务状态、教学含义和未点名行为；不要引入新框架、网络、eval、timer 或新的动画循环。
替换总长度不得超过 {MAX_FUNCTION_REPLACEMENT_CHARS} 字符。"""


@dataclass(frozen=True)
class FunctionRepairResult:
    html: str
    applied: tuple[str, ...]
    degraded: bool = False
    errors: tuple[str, ...] = ()


def stream_repair_functions(
    *,
    raw_html: str,
    report: dict[str, Any],
) -> Iterator[dict[str, Any] | FunctionRepairResult]:
    runner = (
        _traced_stream_repair_functions
        if settings.langsmith_tracing and get_current_run_tree() is not None
        else _stream_repair_functions_impl
    )
    yield from runner(raw_html=raw_html, report=report)


@traceable(
    name="aetherviz.function_repair",
    run_type="chain",
    metadata={"component": "aetherviz", "stage": "function_repair"},
    process_inputs=lambda inputs: {
        "source_chars": len(inputs.get("raw_html") or ""),
        "target_functions": list(
            repair_function_targets(inputs.get("raw_html") or "", inputs.get("report") or {})
        ),
    },
    reduce_fn=lambda items: _summarize(items),
)
def _traced_stream_repair_functions(
    *,
    raw_html: str,
    report: dict[str, Any],
) -> Iterator[dict[str, Any] | FunctionRepairResult]:
    yield from _stream_repair_functions_impl(raw_html=raw_html, report=report)


def _stream_repair_functions_impl(
    *,
    raw_html: str,
    report: dict[str, Any],
) -> Iterator[dict[str, Any] | FunctionRepairResult]:
    targets = repair_function_targets(raw_html, report)
    descriptions = describe_target_functions(raw_html, targets)
    descriptions = [
        item for item in descriptions if len(item["source"]) <= MAX_FUNCTION_REPLACEMENT_CHARS
    ][:3]
    if not descriptions:
        yield FunctionRepairResult(raw_html, (), degraded=True, errors=("no_unique_target_functions",))
        return
    yield build_html_progress_payload(
        [{"content": "按校验调用链修复点名函数", "status": "in_progress"}]
    )
    if not has_primary_llm_config():
        yield FunctionRepairResult(raw_html, (), degraded=True, errors=("model_unavailable",))
        return
    prompt = json.dumps(
        {
            "errors": report.get("errors", []),
            "functions": descriptions,
            "allowed_functions": [item["function"] for item in descriptions],
            "repair_constraints": [
                "frame callbacks may only update existing node attributes",
                "variable topology must be preallocated in the scene builder",
                "do not append, remove, create, clear, or replace nodes in frame functions",
            ],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    raw_text = ""
    try:
        model = create_chat_model("repair")
        for chunk in model.stream(
            [SystemMessage(content=FUNCTION_REPAIR_SYSTEM_PROMPT), HumanMessage(content=prompt)]
        ):
            raw_text += extract_llm_text(chunk)
            if len(raw_text) > MAX_FUNCTION_REPLACEMENT_CHARS + 2_000:
                break
        replacements = parse_function_replacements(raw_text)
        patch = apply_function_replacements(
            raw_html,
            replacements,
            allowed_functions=tuple(item["function"] for item in descriptions),
            allowed_targets=tuple(
                (str(item["function"]), str(item["source_hash"])) for item in descriptions
            ),
        )
        yield build_html_progress_payload(
            [{"content": "按校验调用链修复点名函数", "status": "completed"}]
        )
        yield FunctionRepairResult(
            html=patch.html,
            applied=patch.applied,
            errors=patch.errors,
        )
    except GeneratorExit:
        raise
    except Exception as exc:
        logger.warning("function repair failed: %s", exc)
        yield FunctionRepairResult(raw_html, (), degraded=True, errors=(str(exc),))


def _summarize(items: list[dict[str, Any] | FunctionRepairResult]) -> dict[str, Any]:
    result = next((item for item in reversed(items) if isinstance(item, FunctionRepairResult)), None)
    if result is None:
        return {"completed": False}
    return {
        "completed": True,
        "applied": list(result.applied),
        "degraded": result.degraded,
        "errors": list(result.errors),
    }
