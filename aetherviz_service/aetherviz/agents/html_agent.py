"""HTML generation agent."""

from __future__ import annotations

import logging
from typing import Any

from aetherviz_service.aetherviz.agents.model_factory import create_agent_app, extract_agent_text, has_primary_llm_config
from aetherviz_service.aetherviz.fallback_validator import parse_interactive_html
from aetherviz_service.aetherviz.prompts import build_interactive_generation_prompt, system_prompt_for_interactive_type
from aetherviz_service.aetherviz.validator import sanitize_aetherviz_html

logger = logging.getLogger(__name__)


def generate_html(topic: str, plan: dict[str, Any]) -> tuple[str, bool]:
    prompt = build_interactive_generation_prompt(topic, plan)
    system_prompt = system_prompt_for_interactive_type(plan)
    if not has_primary_llm_config():
        return _fallback_html(topic, plan), True
    try:
        agent = create_agent_app("html", system_prompt=system_prompt)
        result = agent.invoke({"messages": [{"role": "user", "content": prompt}]})
        html = sanitize_aetherviz_html(parse_interactive_html(extract_agent_text(result)))
        return html, False
    except Exception as exc:
        logger.warning("html_agent failed, using fallback html: %s", exc)
        return _fallback_html(topic, plan), True


def _fallback_html(topic: str, plan: dict[str, Any]) -> str:
    title = str(plan.get("title") or topic or "AI互动实验")
    goal = str(plan.get("goal") or f"理解{topic}的核心概念")
    color = str(plan.get("primary_color") or "#22D3EE")
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
<script type="application/json" id="widget-config">{{"type":"{plan.get("interactive_type","diagram")}","concept":"{topic}"}}</script>
</head>
<body>
<main class="wrap">
<header><h1>{title}</h1><p>{goal}</p></header>
<section id="aetherviz-stage" aria-label="{topic}互动舞台">
<svg viewBox="0 0 640 320" role="img" aria-label="{topic}">
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
