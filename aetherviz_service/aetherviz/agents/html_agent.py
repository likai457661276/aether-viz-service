"""HTML generation agent."""

from __future__ import annotations

import html
import json
import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from aetherviz_service.aetherviz.agents.instructions import (
    build_interactive_generation_prompt,
    system_prompt_for_interactive_type,
)
from aetherviz_service.aetherviz.agents.model_factory import (
    agent_invoke_config,
    create_agent_app,
    extract_agent_text,
    has_primary_llm_config,
)
from aetherviz_service.aetherviz.tools.html_output import parse_interactive_html, sanitize_aetherviz_html
from aetherviz_service.config import settings

logger = logging.getLogger(__name__)

HTML_AGENT_WORKFLOW_PROMPT = """你是 html_agent，负责生成完整互动 HTML。

工作方式（必须遵守）：
1. 只用 write_file 将完整 HTML 写入 /widget.html（只允许 1 次 write_file）。
2. write_file 成功后，立即在最终回复直接输出完整 <!DOCTYPE html>...</html> 并结束任务。
3. 禁止使用 read_file、edit_file、write_todos、execute、task 子代理或其它工具。
4. 禁止分步审查、回读文件或循环打磨；写完即输出。
5. 最终回复必须是完整 HTML 文档，禁止 Markdown 包装。"""

DEFAULT_HTML_PROGRESS_STEPS: list[dict[str, str]] = [
    {"content": "写入完整 HTML 初稿", "status": "pending"},
    {"content": "输出最终 HTML 文档", "status": "pending"},
]

HTML_OUTPUT_FILE = "/widget.html"
_MIN_READY_HTML_CHARS = 500


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


def stream_generate_html(topic: str, plan: dict[str, Any]) -> Iterator[dict[str, Any] | HtmlStreamResult]:
    if not has_primary_llm_config():
        yield from _iter_deterministic_html_progress()
        yield HtmlStreamResult(html=_deterministic_html(topic, plan), degraded=True)
        return

    prompt = build_interactive_generation_prompt(topic, plan)
    combined_system_prompt = f"{HTML_AGENT_WORKFLOW_PROMPT}\n\n{system_prompt_for_interactive_type(plan)}"
    final_state: dict[str, Any] | None = None
    timed_out = False
    degraded = False
    deadline = time.monotonic() + max(settings.aetherviz_html_timeout_seconds, 1)
    progress_emitted = False

    try:
        yield from _iter_initial_html_progress()
        progress_emitted = True
        agent = create_agent_app("html", system_prompt=combined_system_prompt)
        for mode, chunk in agent.stream(
            {"messages": [{"role": "user", "content": prompt}]},
            stream_mode=["updates", "values"],
            config=agent_invoke_config("html"),
        ):
            if time.monotonic() > deadline:
                timed_out = True
                degraded = True
                logger.warning(
                    "html_agent timed out after %ss; using best available Deep Agents output",
                    settings.aetherviz_html_timeout_seconds,
                )
                break
            if mode == "values" and isinstance(chunk, dict):
                final_state = chunk
                ready_html = _extract_ready_html_from_agent_state(chunk)
                if ready_html:
                    parsed_html = sanitize_aetherviz_html(parse_interactive_html(ready_html))
                    yield _completed_html_progress_payload()
                    yield HtmlStreamResult(html=parsed_html, degraded=degraded or timed_out)
                    return
            elif mode == "updates" and isinstance(chunk, dict):
                files = _extract_files_from_stream_chunk(chunk)
                if files:
                    ready_html = _extract_ready_html_from_files(files)
                    if ready_html:
                        final_state = {"files": files, **(final_state or {})}
                        parsed_html = sanitize_aetherviz_html(parse_interactive_html(ready_html))
                        yield _completed_html_progress_payload()
                        yield HtmlStreamResult(html=parsed_html, degraded=degraded)
                        return

        raw_html = _extract_html_from_agent_state(final_state or {})
        if not raw_html.strip():
            raise HtmlGenerationError(
                "HTML 生成失败，Deep Agents 未产出可用页面",
                detail="html_agent did not produce HTML output",
            )
        parsed_html = sanitize_aetherviz_html(parse_interactive_html(raw_html))
        if not progress_emitted:
            yield _completed_html_progress_payload()
        yield HtmlStreamResult(html=parsed_html, degraded=timed_out or degraded)
    except HtmlGenerationError:
        raise
    except Exception as exc:
        logger.warning("html_agent failed: %s", exc)
        partial_html = _extract_html_from_agent_state(final_state or {})
        if partial_html.strip():
            try:
                parsed_html = sanitize_aetherviz_html(parse_interactive_html(partial_html))
                yield _completed_html_progress_payload()
                yield HtmlStreamResult(html=parsed_html, degraded=True)
                return
            except Exception:
                logger.warning("html_agent partial Deep Agents output failed validation")
        if _is_recursion_limit_error(exc):
            raise HtmlGenerationError(
                "HTML 生成失败，Agent 步骤过多未正常结束",
                code="generation_failed",
                detail=str(exc),
            ) from exc
        raise HtmlGenerationError(
            "HTML 生成失败，未获得可用页面",
            detail=str(exc),
        ) from exc


def generate_html(topic: str, plan: dict[str, Any]) -> tuple[str, bool]:
    if not has_primary_llm_config():
        return _deterministic_html(topic, plan), True
    result: HtmlStreamResult | None = None
    for item in stream_generate_html(topic, plan):
        if isinstance(item, HtmlStreamResult):
            result = item
    if result is None:
        raise HtmlGenerationError("HTML 生成未返回结果")
    return result.html, result.degraded


def build_html_progress_payload(steps: list[dict[str, str]]) -> dict[str, Any]:
    active_index = next((index for index, step in enumerate(steps) if step["status"] == "in_progress"), None)
    return {
        "delta": _format_html_progress_delta(steps),
        "html_steps": steps,
        "active_step_index": active_index,
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


def _completed_html_progress_payload() -> dict[str, Any]:
    return build_html_progress_payload([{**step, "status": "completed"} for step in DEFAULT_HTML_PROGRESS_STEPS])


def _extract_files_from_stream_chunk(chunk: dict[str, Any]) -> dict[str, Any] | None:
    files = chunk.get("files")
    if isinstance(files, dict):
        return files
    for node_update in chunk.values():
        if isinstance(node_update, dict) and isinstance(node_update.get("files"), dict):
            return node_update["files"]
    return None


def _extract_ready_html_from_agent_state(state: dict[str, Any]) -> str:
    return _extract_ready_html_from_files(state.get("files")) or _extract_ready_html_from_text(
        extract_agent_text(state)
    )


def _extract_ready_html_from_files(files: Any) -> str:
    if not isinstance(files, dict):
        return ""
    content = files.get(HTML_OUTPUT_FILE)
    if content is None:
        for path, value in files.items():
            if str(path).endswith(".html"):
                content = value
                break
    text = str(content or "").strip()
    return text if _is_ready_html_document(text) else ""


def _extract_ready_html_from_text(text: str) -> str:
    candidate = text.strip()
    return candidate if _is_ready_html_document(candidate) else ""


def _is_ready_html_document(text: str) -> bool:
    if not _looks_like_html(text):
        return False
    if len(text) < _MIN_READY_HTML_CHARS:
        return False
    return "</html>" in text.lower()


def _extract_html_from_agent_state(state: dict[str, Any]) -> str:
    files = state.get("files")
    if isinstance(files, dict):
        preferred = [str(path) for path in files if str(path).endswith(".html")]
        for path in [HTML_OUTPUT_FILE, *preferred, *files.keys()]:
            content = files.get(path)
            text = str(content or "").strip()
            if _looks_like_html(text):
                return text
    text = extract_agent_text(state).strip()
    if _looks_like_html(text):
        return text
    return text


def _looks_like_html(text: str) -> bool:
    lowered = text.lower()
    return lowered.startswith("<!doctype html") or "<html" in lowered


def _is_recursion_limit_error(exc: BaseException) -> bool:
    name = type(exc).__name__
    if name == "GraphRecursionError":
        return True
    message = str(exc)
    return "Recursion limit" in message or "GRAPH_RECURSION_LIMIT" in message


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
function handleWidgetAction(event){{const msg=event.data||{{}};if(msg.type==='SET_WIDGET_STATE'&&msg.state){{Object.assign(state,msg.state);updateVisualization();}}if(msg.type==='ANNOTATE_ELEMENT'&&msg.content)caption.textContent=String(msg.content);}}
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
