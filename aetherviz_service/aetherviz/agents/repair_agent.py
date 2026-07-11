"""HTML repair agent."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langsmith import traceable
from langsmith.run_helpers import get_current_run_tree

from aetherviz_service.aetherviz.agents.html_agent import (
    HTML_SIZE_EVENT_INTERVAL_BYTES,
    build_html_progress_payload,
    build_html_size_payload,
)
from aetherviz_service.aetherviz.agents.instructions import REPAIR_SYSTEM_PROMPT, build_repair_prompt
from aetherviz_service.aetherviz.agents.model_factory import (
    create_chat_model,
    extract_llm_text,
    has_primary_llm_config,
)
from aetherviz_service.aetherviz.constants import HTML_OUTPUT_HARD_LIMIT_CHARS
from aetherviz_service.aetherviz.tools.deterministic_repair import deterministic_repair_html
from aetherviz_service.aetherviz.tools.html_output import parse_interactive_html, sanitize_aetherviz_html
from aetherviz_service.config import settings

logger = logging.getLogger(__name__)

DEFAULT_REPAIR_PROGRESS_STEPS: list[dict[str, str]] = [
    {"content": "分析校验错误并修复 HTML", "status": "pending"},
    {"content": "输出修复后的完整 HTML", "status": "pending"},
]

@dataclass(frozen=True)
class RepairStreamResult:
    html: str
    degraded: bool
    truncated: bool = False


def stream_repair_html(
    *,
    topic: str,
    plan: dict[str, Any],
    raw_html: str,
    report: dict[str, Any],
) -> Iterator[dict[str, Any] | RepairStreamResult]:
    runner = (
        _traced_stream_repair_html
        if settings.langsmith_tracing and get_current_run_tree() is not None
        else _stream_repair_html_impl
    )
    yield from runner(topic=topic, plan=plan, raw_html=raw_html, report=report)


@traceable(
    name="aetherviz.model_repair",
    run_type="chain",
    metadata={"component": "aetherviz", "stage": "model_repair"},
    process_inputs=lambda inputs: {
        "topic": inputs.get("topic"),
        "interactive_type": (inputs.get("plan") or {}).get("interactive_type"),
        "source_chars": len(inputs.get("raw_html") or ""),
        "error_types": [error.get("type") for error in (inputs.get("report") or {}).get("errors", [])],
        "warning_types": [warning.get("type") for warning in (inputs.get("report") or {}).get("warnings", [])],
    },
    reduce_fn=lambda items: _summarize_repair_stream(items),
)
def _traced_stream_repair_html(
    *,
    topic: str,
    plan: dict[str, Any],
    raw_html: str,
    report: dict[str, Any],
) -> Iterator[dict[str, Any] | RepairStreamResult]:
    yield from _stream_repair_html_impl(topic=topic, plan=plan, raw_html=raw_html, report=report)


def _stream_repair_html_impl(
    *,
    topic: str,
    plan: dict[str, Any],
    raw_html: str,
    report: dict[str, Any],
) -> Iterator[dict[str, Any] | RepairStreamResult]:
    if not has_primary_llm_config():
        yield RepairStreamResult(
            html=deterministic_repair_html(raw_html, report, plan=plan),
            degraded=True,
            truncated=_report_has_truncation(report),
        )
        return
    prompt = build_repair_prompt(
        topic=topic,
        plan=plan,
        raw_html=raw_html[:HTML_OUTPUT_HARD_LIMIT_CHARS],
        error_detail=json.dumps(_compact_report(report), ensure_ascii=False),
        source_label="确定性检查",
    )
    raw_text = ""
    last_size_event_bytes = 0
    timed_out = False
    deadline = time.monotonic() + max(settings.aetherviz_repair_timeout_seconds, 1)
    yield build_html_progress_payload(
        [
            {"content": DEFAULT_REPAIR_PROGRESS_STEPS[0]["content"], "status": "in_progress"},
            {"content": DEFAULT_REPAIR_PROGRESS_STEPS[1]["content"], "status": "pending"},
        ]
    )
    try:
        model = create_chat_model("repair")
        messages = [SystemMessage(content=REPAIR_SYSTEM_PROMPT), HumanMessage(content=prompt)]
        output_started = False
        for chunk in model.stream(messages):
            if time.monotonic() > deadline:
                timed_out = True
                logger.warning(
                    "repair model timed out after %ss; using best available output",
                    settings.aetherviz_repair_timeout_seconds,
                )
                break
            text = extract_llm_text(chunk)
            if text:
                raw_text += text
                current_bytes = len(raw_text.encode("utf-8"))
                if not output_started:
                    output_started = True
                    yield build_html_progress_payload(
                        [
                            {**DEFAULT_REPAIR_PROGRESS_STEPS[0], "status": "completed"},
                            {**DEFAULT_REPAIR_PROGRESS_STEPS[1], "status": "in_progress"},
                        ],
                        html_content=raw_text,
                    )
                    last_size_event_bytes = current_bytes
                elif current_bytes - last_size_event_bytes >= HTML_SIZE_EVENT_INTERVAL_BYTES:
                    yield build_html_size_payload(raw_text)
                    last_size_event_bytes = current_bytes
        if not raw_text.strip():
            raise ValueError("repair model returned empty content")
        repaired_html = deterministic_repair_html(
            sanitize_aetherviz_html(parse_interactive_html(raw_text)),
            report,
            plan=plan,
        )
        yield build_html_progress_payload(
            [{**step, "status": "completed"} for step in DEFAULT_REPAIR_PROGRESS_STEPS],
            html_content=repaired_html,
        )
        yield RepairStreamResult(
            html=repaired_html,
            degraded=timed_out,
            truncated="</html" not in raw_text.lower(),
        )
    except GeneratorExit:
        raise
    except Exception as exc:
        logger.warning("repair model failed, using deterministic repair: %s", exc)
        if raw_text.strip():
            try:
                yield RepairStreamResult(
                    html=deterministic_repair_html(
                        sanitize_aetherviz_html(parse_interactive_html(raw_text)),
                        report,
                        plan=plan,
                    ),
                    degraded=True,
                    truncated="</html" not in raw_text.lower(),
                )
                return
            except Exception:
                logger.warning("repair model partial output failed parsing")
        yield RepairStreamResult(
            html=deterministic_repair_html(raw_html, report, plan=plan),
            degraded=True,
            truncated=_report_has_truncation(report),
        )


def _summarize_repair_stream(items: list[dict[str, Any] | RepairStreamResult]) -> dict[str, Any]:
    result = next((item for item in reversed(items) if isinstance(item, RepairStreamResult)), None)
    if result is None:
        return {"completed": False, "progress_events": sum(isinstance(item, dict) for item in items)}
    return {
        "completed": True,
        "chars": len(result.html),
        "bytes": len(result.html.encode("utf-8")),
        "degraded": result.degraded,
        "truncated": result.truncated,
        "progress_events": sum(isinstance(item, dict) for item in items),
    }


def _report_has_truncation(report: dict[str, Any]) -> bool:
    return any(
        isinstance(error, dict) and error.get("type") == "truncated_model_output"
        for error in report.get("errors", [])
    )


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
