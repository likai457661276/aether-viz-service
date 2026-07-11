"""HTML generation agent."""

from __future__ import annotations

import html
import json
import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langsmith import traceable
from langsmith.run_helpers import get_current_run_tree

from aetherviz_service.aetherviz.agents.instructions import (
    build_interactive_generation_prompt,
    system_prompt_for_interactive_type,
)
from aetherviz_service.aetherviz.agents.model_factory import (
    create_chat_model,
    extract_llm_reasoning,
    extract_llm_text,
    has_primary_llm_config,
)
from aetherviz_service.aetherviz.tools.html_output import parse_interactive_html, sanitize_aetherviz_html
from aetherviz_service.config import settings

logger = logging.getLogger(__name__)

DEFAULT_HTML_PROGRESS_STEPS: list[dict[str, str]] = [
    {"content": "生成完整 HTML 文档", "status": "pending"},
    {"content": "提取并整理 HTML 输出", "status": "pending"},
]
HTML_SIZE_EVENT_INTERVAL_BYTES = 512
HTML_REASONING_EVENT_INTERVAL_MS = 250


class HtmlGenerationError(Exception):
    """Raised when html_agent cannot produce usable HTML with a configured LLM."""

    def __init__(self, message: str, *, code: str = "generation_failed", detail: str = "") -> None:
        self.code = code
        self.message = message
        self.detail = detail
        super().__init__(message)


@dataclass(frozen=True)
class HtmlStreamResult:
    html: str
    degraded: bool
    truncated: bool = False
    reasoning_elapsed_ms: int = 0
    first_chunk_elapsed_ms: int = 0
    generation_elapsed_ms: int = 0


def stream_generate_html(topic: str, plan: dict[str, Any]) -> Iterator[dict[str, Any] | HtmlStreamResult]:
    runner = (
        _traced_stream_generate_html
        if settings.langsmith_tracing and get_current_run_tree() is not None
        else _stream_generate_html_impl
    )
    yield from runner(topic, plan)


@traceable(
    name="aetherviz.html_generation",
    run_type="chain",
    metadata={"component": "aetherviz", "stage": "html_generation"},
    process_inputs=lambda inputs: {
        "topic": inputs.get("topic"),
        "interactive_type": (inputs.get("plan") or {}).get("interactive_type"),
        "subject": (inputs.get("plan") or {}).get("subject"),
    },
    reduce_fn=lambda items: _summarize_html_stream(items),
)
def _traced_stream_generate_html(
    topic: str,
    plan: dict[str, Any],
) -> Iterator[dict[str, Any] | HtmlStreamResult]:
    yield from _stream_generate_html_impl(topic, plan)


def _stream_generate_html_impl(topic: str, plan: dict[str, Any]) -> Iterator[dict[str, Any] | HtmlStreamResult]:
    if not has_primary_llm_config():
        yield from _iter_deterministic_html_progress()
        yield HtmlStreamResult(html=_deterministic_html(topic, plan), degraded=True)
        return

    prompt = build_interactive_generation_prompt(topic, plan)
    system_prompt = system_prompt_for_interactive_type(plan)
    raw_html = ""
    last_size_event_bytes = 0
    timed_out = False
    degraded = False
    reasoning_started_at = time.monotonic()
    reasoning_elapsed_ms = 0
    first_chunk_elapsed_ms = 0
    generation_elapsed_ms = 0
    last_reasoning_event_ms = -HTML_REASONING_EVENT_INTERVAL_MS
    deadline = time.monotonic() + max(settings.aetherviz_html_timeout_seconds, 1)
    try:
        yield from _iter_initial_html_progress()
        model = create_chat_model("html")
        messages = [SystemMessage(content=system_prompt), HumanMessage(content=prompt)]
        reasoning_started_at = time.monotonic()
        stream_started_at = reasoning_started_at
        extraction_progress_emitted = False
        for chunk in model.stream(messages):
            if first_chunk_elapsed_ms == 0:
                first_chunk_elapsed_ms = max(int((time.monotonic() - stream_started_at) * 1000), 1)
            if time.monotonic() > deadline:
                timed_out = True
                degraded = True
                logger.warning(
                    "html model timed out after %ss; using best available output",
                    settings.aetherviz_html_timeout_seconds,
                )
                break
            reasoning = extract_llm_reasoning(chunk)
            if settings.aetherviz_html_enable_thinking and reasoning:
                reasoning_elapsed_ms = int((time.monotonic() - reasoning_started_at) * 1000)
                if reasoning_elapsed_ms - last_reasoning_event_ms >= HTML_REASONING_EVENT_INTERVAL_MS:
                    yield build_html_reasoning_payload(reasoning_elapsed_ms, active=True)
                    last_reasoning_event_ms = reasoning_elapsed_ms
            text = extract_llm_text(chunk)
            if text:
                if settings.aetherviz_html_enable_thinking:
                    reasoning_elapsed_ms = max(
                        reasoning_elapsed_ms,
                        int((time.monotonic() - reasoning_started_at) * 1000),
                    )
                    if not extraction_progress_emitted:
                        yield build_html_reasoning_payload(reasoning_elapsed_ms, active=False)
                raw_html += text
                current_bytes = len(raw_html.encode("utf-8"))
                if not extraction_progress_emitted:
                    extraction_progress_emitted = True
                    first_content_payload = build_html_progress_payload(
                        [
                            {**DEFAULT_HTML_PROGRESS_STEPS[0], "status": "completed"},
                            {**DEFAULT_HTML_PROGRESS_STEPS[1], "status": "in_progress"},
                        ],
                        html_content=raw_html,
                    )
                    first_content_payload["first_chunk_elapsed_ms"] = first_chunk_elapsed_ms
                    yield first_content_payload
                    last_size_event_bytes = current_bytes
                elif current_bytes - last_size_event_bytes >= HTML_SIZE_EVENT_INTERVAL_BYTES:
                    yield build_html_size_payload(raw_html)
                    last_size_event_bytes = current_bytes

        if not raw_html.strip():
            raise HtmlGenerationError(
                "HTML 生成失败，模型未产出可用页面",
                detail="html model did not produce HTML output",
            )
        generation_elapsed_ms = int((time.monotonic() - stream_started_at) * 1000)
        truncated = "</html" not in raw_html.lower()
        parsed_html = sanitize_aetherviz_html(parse_interactive_html(raw_html))
        yield _completed_html_progress_payload(parsed_html)
        yield HtmlStreamResult(
            html=parsed_html,
            degraded=timed_out or degraded,
            truncated=truncated,
            reasoning_elapsed_ms=reasoning_elapsed_ms,
            first_chunk_elapsed_ms=first_chunk_elapsed_ms,
            generation_elapsed_ms=generation_elapsed_ms,
        )
    except HtmlGenerationError:
        raise
    except GeneratorExit:
        raise
    except Exception as exc:
        logger.warning("html_agent failed: %s", exc)
        if raw_html.strip():
            try:
                parsed_html = sanitize_aetherviz_html(parse_interactive_html(raw_html))
                yield _completed_html_progress_payload(parsed_html)
                yield HtmlStreamResult(
                    html=parsed_html,
                    degraded=True,
                    truncated="</html" not in raw_html.lower(),
                    reasoning_elapsed_ms=reasoning_elapsed_ms,
                    first_chunk_elapsed_ms=first_chunk_elapsed_ms,
                    generation_elapsed_ms=int((time.monotonic() - reasoning_started_at) * 1000),
                )
                return
            except Exception:
                logger.warning("html model partial output failed parsing")
        raise HtmlGenerationError(
            "HTML 生成失败，未获得可用页面",
            detail=str(exc),
        ) from exc


def _summarize_html_stream(items: list[dict[str, Any] | HtmlStreamResult]) -> dict[str, Any]:
    result = next((item for item in reversed(items) if isinstance(item, HtmlStreamResult)), None)
    if result is None:
        return {"completed": False, "progress_events": sum(isinstance(item, dict) for item in items)}
    return {
        "completed": True,
        "chars": len(result.html),
        "bytes": len(result.html.encode("utf-8")),
        "degraded": result.degraded,
        "truncated": result.truncated,
        "reasoning_elapsed_ms": result.reasoning_elapsed_ms,
        "first_chunk_elapsed_ms": result.first_chunk_elapsed_ms,
        "generation_elapsed_ms": result.generation_elapsed_ms,
        "progress_events": sum(isinstance(item, dict) for item in items),
    }


def build_html_progress_payload(
    steps: list[dict[str, str]],
    *,
    html_content: str | None = None,
) -> dict[str, Any]:
    active_index = next((index for index, step in enumerate(steps) if step["status"] == "in_progress"), None)
    payload = {
        "delta": _format_html_progress_delta(steps),
        "html_steps": steps,
        "active_step_index": active_index,
    }
    if html_content is not None:
        payload.update(build_html_size_payload(html_content))
    return payload


def build_html_size_payload(html_content: str) -> dict[str, Any]:
    """Return the actual accumulated HTML size without returning partial HTML."""

    return {
        "delta": "",
        "bytes": len(html_content.encode("utf-8")),
        "chars": len(html_content),
    }


def build_html_reasoning_payload(elapsed_ms: int, *, active: bool) -> dict[str, Any]:
    """Expose reasoning duration without forwarding private chain-of-thought text."""

    return {
        "delta": "",
        "reasoning_active": active,
        "reasoning_elapsed_ms": max(elapsed_ms, 0),
    }


def _format_html_progress_delta(steps: list[dict[str, str]]) -> str:
    active = next((step for step in steps if step["status"] == "in_progress"), None)
    if active:
        return f"正在{active['content']}"
    if steps and all(step["status"] == "completed" for step in steps):
        return "HTML 生成步骤已完成"
    return "正在准备 HTML 生成"


def _iter_initial_html_progress() -> Iterator[dict[str, Any]]:
    steps = [dict(step) for step in DEFAULT_HTML_PROGRESS_STEPS]
    steps[0]["status"] = "in_progress"
    yield build_html_progress_payload(steps)


def _completed_html_progress_payload(html_content: str | None = None) -> dict[str, Any]:
    return build_html_progress_payload(
        [{**step, "status": "completed"} for step in DEFAULT_HTML_PROGRESS_STEPS],
        html_content=html_content,
    )


def _iter_deterministic_html_progress() -> Iterator[dict[str, Any]]:
    steps = [dict(step) for step in DEFAULT_HTML_PROGRESS_STEPS]
    for index in range(len(steps)):
        for step_index, step in enumerate(steps):
            if step_index < index:
                step["status"] = "completed"
            elif step_index == index:
                step["status"] = "in_progress"
            else:
                step["status"] = "pending"
        yield build_html_progress_payload([dict(step) for step in steps])
    yield _completed_html_progress_payload()


def _deterministic_html(topic: str, plan: dict[str, Any]) -> str:
    raw_title = str(plan.get("title") or topic or "AI互动实验")
    raw_goal = str(plan.get("goal") or f"理解{topic}的核心概念")
    title = html.escape(raw_title)
    goal = html.escape(raw_goal)
    topic_text = html.escape(topic)
    color = str(plan.get("primary_color") or "#22D3EE")
    widget_config = json.dumps(
        {"type": plan.get("interactive_type", "diagram"), "concept": topic},
        ensure_ascii=False,
    ).replace("</", "<\\/")
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
body{{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#f7faf9;color:#17231f}}
.wrap{{min-height:100vh;display:grid;grid-template-rows:auto 1fr auto;gap:16px;padding:24px;box-sizing:border-box}}
header,footer{{max-width:980px;width:100%;margin:0 auto}}
h1{{font-size:28px;margin:0 0 8px}}p{{line-height:1.7}}
#aetherviz-stage{{max-width:980px;width:100%;min-height:360px;margin:0 auto;display:grid;place-items:center;background:white;border:1px solid #d9e6e1;border-radius:8px}}
svg{{max-width:92%;height:auto}}.controls{{display:flex;gap:10px;flex-wrap:wrap}}button,input{{font:inherit}}
button{{border:0;border-radius:6px;background:{color};color:white;padding:10px 14px;cursor:pointer}}
.caption{{font-weight:600;color:#365248}}
</style>
<script type="application/json" id="widget-config">{widget_config}</script>
</head>
<body>
<main class="wrap">
<header><h1>{title}</h1><p>{goal}</p></header>
<section id="aetherviz-stage" aria-label="{topic_text}互动舞台">
<svg viewBox="0 0 640 320" role="img" aria-label="{topic_text}">
<rect x="70" y="70" width="500" height="180" rx="20" fill="{color}" opacity=".14"></rect>
<path id="curve" d="M90 220 C180 80 300 80 410 190 S540 230 570 110" fill="none" stroke="{color}" stroke-width="10" stroke-linecap="round"></path>
<circle id="dot" cx="90" cy="220" r="16" fill="#F59E0B"></circle>
<text x="320" y="286" text-anchor="middle" fill="#365248">拖动参数观察状态变化</text>
</svg>
</section>
<footer>
<p id="animation-caption" class="caption">当前步骤：观察初始状态。</p>
<div class="controls"><button id="play-animation">播放</button><button id="pause-animation">暂停</button><button id="reset-animation">重置</button><input id="parameter" type="range" min="0" max="100" value="0"></div>
</footer>
</main>
<script>
const state={{progress:0,playing:false}};
const dot=document.getElementById('dot');
const caption=document.getElementById('animation-caption');
function updateVisualization(){{
  const p=Number(state.progress)||0;
  dot.setAttribute('cx',String(90+p*4.8));
  dot.setAttribute('cy',String(220-Math.sin(p/100*Math.PI)*120));
  caption.textContent=p<34?'当前步骤：观察初始状态。':p<67?'当前步骤：比较参数变化后的图形位置。':'当前步骤：归纳图形变化和核心结论。';
}}
function tick(){{if(state.playing){{state.progress=(state.progress+1)%101;document.getElementById('parameter').value=String(state.progress);updateVisualization();}}requestAnimationFrame(tick);}}
function play(){{state.playing=true;}}function pause(){{state.playing=false;}}function reset(){{state.progress=0;state.playing=false;document.getElementById('parameter').value='0';updateVisualization();}}
function handleWidgetAction(event){{const msg=event.data||{{}};if(msg.type==='SET_WIDGET_STATE'&&msg.state){{Object.assign(state,msg.state);updateVisualization();}}if(msg.type==='HIGHLIGHT_ELEMENT'&&msg.target){{const el=document.querySelector(msg.target);if(el)el.style.filter='drop-shadow(0 0 8px #f59e0b)';}}if(msg.type==='ANNOTATE_ELEMENT'&&msg.content)caption.textContent=String(msg.content);if(msg.type==='REVEAL_ELEMENT'&&msg.target){{const el=document.querySelector(msg.target);if(el)el.hidden=false;}}}}
document.getElementById('play-animation').addEventListener('click',()=>play());
document.getElementById('pause-animation').addEventListener('click',()=>pause());
document.getElementById('reset-animation').addEventListener('click',()=>reset());
document.getElementById('parameter').addEventListener('input',e=>{{state.progress=Number(e.target.value)||0;updateVisualization();}});
window.addEventListener('message',handleWidgetAction);
window.AetherVizRuntime={{play,pause,reset,update:updateVisualization,getState:()=>state}};
window.__AETHERVIZ_RUNTIME_READY__=true;
updateVisualization();tick();
</script>
</body>
</html>"""
