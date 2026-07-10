"""HTML repair agent."""

from __future__ import annotations

import html as html_lib
import json
import logging
import re
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

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


def repair_html(
    *,
    topic: str,
    plan: dict[str, Any],
    raw_html: str,
    report: dict[str, Any],
) -> tuple[str, bool]:
    result: RepairStreamResult | None = None
    for item in stream_repair_html(
        topic=topic,
        plan=plan,
        raw_html=raw_html,
        report=report,
    ):
        if isinstance(item, RepairStreamResult):
            result = item
    if result is None:
        return deterministic_repair_html(raw_html, report), True
    return result.html, result.degraded


def stream_repair_html(
    *,
    topic: str,
    plan: dict[str, Any],
    raw_html: str,
    report: dict[str, Any],
) -> Iterator[dict[str, Any] | RepairStreamResult]:
    if not has_primary_llm_config():
        yield RepairStreamResult(html=deterministic_repair_html(raw_html, report, plan=plan), degraded=True)
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
        yield RepairStreamResult(html=repaired_html, degraded=timed_out)
    except (Exception, GeneratorExit) as exc:
        # 同 html_agent/edit_html_workflow：显式捕获 GeneratorExit，避免模型
        # 流被外部中断时已产出的部分内容被静默丢弃。
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
                )
                return
            except Exception:
                logger.warning("repair model partial output failed parsing")
        yield RepairStreamResult(html=deterministic_repair_html(raw_html, report, plan=plan), degraded=True)


def deterministic_repair_html(
    html: str,
    report: dict[str, Any] | None = None,
    *,
    plan: dict[str, Any] | None = None,
) -> str:
    repaired = html.strip()
    if not repaired.lower().startswith("<!doctype html>"):
        repaired = "<!DOCTYPE html>\n" + repaired
    if "</body>" not in repaired.lower():
        if "</html>" in repaired.lower():
            close_index = repaired.lower().rfind("</html>")
            repaired = repaired[:close_index] + "\n</body>\n" + repaired[close_index:]
        else:
            repaired += "\n</body>"
    if "</html>" not in repaired.lower():
        repaired += "\n</html>"
    error_types = {
        str(error.get("type"))
        for error in ((report or {}).get("errors") or [])
        if isinstance(error, dict)
    }
    if plan is not None or "missing_widget_config" in error_types:
        repaired = _insert_widget_config(repaired, plan)
    if plan is not None or "missing_control" in error_types:
        repaired = _insert_runtime_controls(repaired)
    if "inline_event" in error_types:
        repaired = _move_inline_events_to_listeners(repaired)
    if "html_length_hard_limit" in error_types:
        repaired = re.sub(r"<!--(?!\[if)[\s\S]*?-->", "", repaired, flags=re.IGNORECASE)
        repaired = re.sub(r">\s+<", "><", repaired)
    return repaired


def _move_inline_events_to_listeners(html: str) -> str:
    """Move inline onXxx handlers into equivalent addEventListener bindings.

    这是纯代码搬移，不改变原元素、事件顺序或 handler 内容。若生成出的
    handler 本身存在语法/安全问题，后续确定性校验仍会阻止其通过。
    """
    handlers: list[tuple[str, str, str]] = []
    tag_index = 0
    event_attr = re.compile(r"\s+(on[a-zA-Z]+)\s*=\s*(['\"])(.*?)\2", re.DOTALL)

    def rewrite_tag(match: re.Match[str]) -> str:
        nonlocal tag_index
        tag = match.group(0)
        found = list(event_attr.finditer(tag))
        if not found:
            return tag
        marker = f"aetherviz-event-{tag_index}"
        tag_index += 1
        for attr in found:
            handlers.append(
                (
                    marker,
                    attr.group(1)[2:].lower(),
                    html_lib.unescape(attr.group(3)).strip(),
                )
            )
        tag = event_attr.sub("", tag)
        insert_at = tag.rfind("/>")
        if insert_at < 0:
            insert_at = tag.rfind(">")
        return tag[:insert_at] + f' data-aetherviz-event="{marker}"' + tag[insert_at:]

    repaired = re.sub(r"<[A-Za-z][^<>]*>", rewrite_tag, html)
    if not handlers:
        return html
    bindings = "".join(
        "var el=document.querySelector(" + json.dumps(f'[data-aetherviz-event="{marker}"]') + ");"
        + f"if(el)el.addEventListener({json.dumps(event_name)},function(event){{{source}}});"
        for marker, event_name, source in handlers
    )
    script = f"<script>(function(){{{bindings}}})();</script>\n"
    body_close = re.search(r"</body\s*>", repaired, re.IGNORECASE)
    insert_at = body_close.start() if body_close else len(repaired)
    return repaired[:insert_at] + script + repaired[insert_at:]


def _insert_widget_config(html: str, plan: dict[str, Any] | None) -> str:
    source = plan if isinstance(plan, dict) else {}
    interactive_type = str(source.get("interactive_type") or "diagram")
    if interactive_type not in {"simulation", "diagram", "game"}:
        interactive_type = "diagram"
    spec = source.get("interactive_spec")
    payload = dict(spec) if isinstance(spec, dict) else {}
    payload["type"] = interactive_type
    config_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    markup = f'<script type="application/json" id="widget-config">{config_json}</script>\n'
    existing = re.search(
        r"<script\b(?=[^>]*\bid\s*=\s*(['\"])widget-config\1)[^>]*>[\s\S]*?</script\s*>",
        html,
        re.IGNORECASE,
    )
    if existing:
        return html[: existing.start()] + markup.rstrip() + html[existing.end() :]
    head_close = re.search(r"</head\s*>", html, re.IGNORECASE)
    if head_close:
        return html[: head_close.start()] + markup + html[head_close.start() :]
    html_open = re.search(r"<html\b[^>]*>", html, re.IGNORECASE)
    insert_at = html_open.end() if html_open else 0
    return html[:insert_at] + "\n<head>\n" + markup + "</head>\n" + html[insert_at:]


def _insert_runtime_controls(html: str) -> str:
    controls = (
        ("play-animation", "播放", "play"),
        ("pause-animation", "暂停", "pause"),
        ("reset-animation", "重置", "reset"),
    )
    missing = [
        item
        for item in controls
        if not re.search(rf"\bid\s*=\s*(['\"]){item[0]}\1", html, re.IGNORECASE)
    ]
    if not missing:
        return html
    buttons = "".join(
        f'<button id="{control_id}" type="button" data-action="{action}">{label}</button>'
        for control_id, label, action in missing
    )
    repaired = _insert_into_control_panel(html, buttons)
    if repaired == html:
        body_close = re.search(r"</body\s*>", html, re.IGNORECASE)
        insert_at = body_close.start() if body_close else len(html)
        repaired = (
            html[:insert_at]
            + f'<div class="control-panel" data-region="controls">{buttons}</div>\n'
            + html[insert_at:]
        )

    bindings = json.dumps({control_id: action for control_id, _, action in missing}, ensure_ascii=True)
    script = (
        "<script>(function(){var bindings="
        + bindings
        + ";Object.keys(bindings).forEach(function(id){var el=document.getElementById(id);"
        "if(!el)return;el.addEventListener('click',function(){var runtime=window.AetherVizRuntime;"
        "var method=bindings[id];if(runtime&&typeof runtime[method]==='function')runtime[method]();});});})();</script>\n"
    )
    body_close = re.search(r"</body\s*>", repaired, re.IGNORECASE)
    insert_at = body_close.start() if body_close else len(repaired)
    return repaired[:insert_at] + script + repaired[insert_at:]


def _insert_into_control_panel(html: str, markup: str) -> str:
    opening = re.search(
        r"<div\b[^>]*\bclass\s*=\s*(['\"])[^'\"]*\bcontrol-panel\b[^'\"]*\1[^>]*>",
        html,
        re.IGNORECASE,
    )
    if not opening:
        return html
    depth = 0
    for token in re.finditer(r"<div\b[^>]*>|</div\s*>", html[opening.start() :], re.IGNORECASE):
        if token.group(0).lower().startswith("</div"):
            depth -= 1
            if depth == 0:
                insert_at = opening.start() + token.start()
                return html[:insert_at] + markup + html[insert_at:]
        else:
            depth += 1
    return html


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
