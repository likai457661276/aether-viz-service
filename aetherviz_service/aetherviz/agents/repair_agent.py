"""HTML repair agent."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from aetherviz_service.aetherviz.agents.html_agent import (
    HTML_OUTPUT_FILE,
    _extract_files_from_stream_chunk,
    _extract_ready_html_from_agent_state,
    _extract_ready_html_from_files,
    _is_recursion_limit_error,
    build_html_progress_payload,
)
from aetherviz_service.aetherviz.agents.instructions import REPAIR_SYSTEM_PROMPT, build_repair_prompt
from aetherviz_service.aetherviz.agents.model_factory import (
    agent_invoke_config,
    create_agent_app,
    extract_agent_text,
    has_primary_llm_config,
)
from aetherviz_service.aetherviz.constants import HTML_OUTPUT_HARD_LIMIT_CHARS
from aetherviz_service.aetherviz.tools.html_output import parse_interactive_html, sanitize_aetherviz_html
from aetherviz_service.config import settings

logger = logging.getLogger(__name__)

DEFAULT_REPAIR_PROGRESS_STEPS: list[dict[str, str]] = [
    {"content": "分析校验错误并修复 HTML", "status": "pending"},
    {"content": "输出修复后的完整 HTML", "status": "pending"},
]

REPAIR_AGENT_WORKFLOW_PROMPT = """你是 repair_agent，负责修复 HTML。

工作方式（必须遵守）：
1. 基于校验错误直接 write_file 或 edit_file 修复 /widget.html（edit_file 最多 3 次）。
2. 修复完成后，立即在最终回复直接输出完整 <!DOCTYPE html>...</html> 并结束任务。
3. 禁止使用 write_todos、execute、task 子代理；禁止 read_file 分页回读后循环打磨。
4. 最终回复必须是完整 HTML 文档，禁止 Markdown 包装。"""


@dataclass(frozen=True)
class RepairStreamResult:
    html: str
    degraded: bool


def repair_html(
    *,
    topic: str,
    plan: dict[str, Any],
    raw_html: str,
    report: dict[str, Any],
    original_prompt: str = "",
) -> tuple[str, bool]:
    result: RepairStreamResult | None = None
    for item in stream_repair_html(
        topic=topic,
        plan=plan,
        raw_html=raw_html,
        report=report,
        original_prompt=original_prompt,
    ):
        if isinstance(item, RepairStreamResult):
            result = item
    if result is None:
        return _deterministic_repair(raw_html), True
    return result.html, result.degraded


def stream_repair_html(
    *,
    topic: str,
    plan: dict[str, Any],
    raw_html: str,
    report: dict[str, Any],
    original_prompt: str = "",
) -> Iterator[dict[str, Any] | RepairStreamResult]:
    if not has_primary_llm_config():
        yield RepairStreamResult(html=_deterministic_repair(raw_html), degraded=True)
        return
    prompt = build_repair_prompt(
        topic=topic,
        plan=plan,
        original_prompt=original_prompt,
        raw_html=raw_html[:HTML_OUTPUT_HARD_LIMIT_CHARS],
        error_detail=json.dumps(_compact_report(report), ensure_ascii=False),
        source_label="Deep Agents 检查",
    )
    combined_system_prompt = f"{REPAIR_AGENT_WORKFLOW_PROMPT}\n\n{REPAIR_SYSTEM_PROMPT}"
    final_state: dict[str, Any] | None = None
    timed_out = False
    deadline = time.monotonic() + max(settings.aetherviz_repair_timeout_seconds, 1)
    yield build_html_progress_payload(
        [
            {"content": DEFAULT_REPAIR_PROGRESS_STEPS[0]["content"], "status": "in_progress"},
            {"content": DEFAULT_REPAIR_PROGRESS_STEPS[1]["content"], "status": "pending"},
        ]
    )
    try:
        agent = create_agent_app("repair", system_prompt=combined_system_prompt)
        for mode, chunk in agent.stream(
            {"messages": [{"role": "user", "content": prompt}]},
            stream_mode=["updates", "values"],
            config=agent_invoke_config("repair"),
        ):
            if time.monotonic() > deadline:
                timed_out = True
                logger.warning(
                    "repair_agent timed out after %ss; using best available Deep Agents output",
                    settings.aetherviz_repair_timeout_seconds,
                )
                break
            if mode == "values" and isinstance(chunk, dict):
                final_state = chunk
                ready_html = _extract_ready_html_from_agent_state(chunk)
                if ready_html:
                    yield build_html_progress_payload(
                        [{**step, "status": "completed"} for step in DEFAULT_REPAIR_PROGRESS_STEPS]
                    )
                    yield RepairStreamResult(
                        html=sanitize_aetherviz_html(parse_interactive_html(ready_html)),
                        degraded=timed_out,
                    )
                    return
            elif mode == "updates" and isinstance(chunk, dict):
                files = _extract_files_from_stream_chunk(chunk)
                if files:
                    ready_html = _extract_ready_html_from_files(files)
                    if ready_html:
                        final_state = {"files": files, **(final_state or {})}
                        yield build_html_progress_payload(
                            [{**step, "status": "completed"} for step in DEFAULT_REPAIR_PROGRESS_STEPS]
                        )
                        yield RepairStreamResult(
                            html=sanitize_aetherviz_html(parse_interactive_html(ready_html)),
                            degraded=timed_out,
                        )
                        return
        raw_text = _extract_repair_html_from_state(final_state or {}) or extract_agent_text(final_state or {})
        yield build_html_progress_payload([{**step, "status": "completed"} for step in DEFAULT_REPAIR_PROGRESS_STEPS])
        yield RepairStreamResult(html=sanitize_aetherviz_html(parse_interactive_html(raw_text)), degraded=timed_out)
    except Exception as exc:
        logger.warning("repair_agent failed, using deterministic repair: %s", exc)
        partial_html = _extract_repair_html_from_state(final_state or {})
        if partial_html.strip():
            yield RepairStreamResult(html=sanitize_aetherviz_html(parse_interactive_html(partial_html)), degraded=True)
            return
        if _is_recursion_limit_error(exc):
            logger.warning("repair_agent hit recursion limit; falling back to deterministic repair")
        yield RepairStreamResult(html=_deterministic_repair(raw_html), degraded=True)


def _extract_repair_html_from_state(state: dict[str, Any]) -> str:
    ready = _extract_ready_html_from_agent_state(state)
    if ready:
        return ready
    files = state.get("files")
    if isinstance(files, dict):
        for path in (HTML_OUTPUT_FILE, *files.keys()):
            text = str(files.get(path) or "").strip()
            if text:
                return text
    return extract_agent_text(state).strip()


def _deterministic_repair(html: str) -> str:
    repaired = html.strip()
    if not repaired.lower().startswith("<!doctype html>"):
        repaired = "<!DOCTYPE html>\n" + repaired
    if "</html>" not in repaired.lower():
        repaired += "\n</html>"
    return repaired


def _compact_report(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": report.get("ok"),
        "summary": report.get("summary"),
        "errors": report.get("errors", [])[:8],
        "warnings": report.get("warnings", [])[:8],
        "checks": {
            check_name: {
                "ok": check_data.get("ok"),
                "summary": check_data.get("summary"),
                "errors": check_data.get("errors", [])[:3],
            }
            for check_name, check_data in (report.get("checks") or {}).items()
            if isinstance(check_data, dict)
        },
    }
