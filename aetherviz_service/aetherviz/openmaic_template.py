"""Deterministic OpenMAIC interactive HTML builder."""

from __future__ import annotations

import json
from html import escape
from typing import Any


def build_openmaic_template_html(topic: str, plan: dict[str, Any]) -> str:
    """Build a validated OpenMAIC HTML page when model HTML is unusable."""
    title = _safe_text(plan.get("title") or f"{topic}互动课件", fallback=f"{topic}互动课件", limit=48)
    goal = _safe_text(plan.get("goal") or f"通过互动操作理解{topic}。", fallback=f"通过互动操作理解{topic}。", limit=160)
    primary_color = _safe_color(plan.get("primary_color"))
    interactive_type = str(plan.get("interactive_type") or "simulation")
    if interactive_type not in {"simulation", "diagram", "game"}:
        interactive_type = "simulation"

    teaching_flow = _normalize_teaching_flow(plan.get("teaching_flow"), topic)
    controls = _normalize_controls(plan.get("controls"), interactive_type)
    formulas = _normalize_text_list(plan.get("formulas"), fallback=[topic], max_items=3)
    widget_config = _widget_config(plan.get("interactive_spec"), interactive_type, topic, controls)
    variable = _primary_variable(widget_config)

    flow_item_parts = []
    for index, step in enumerate(teaching_flow):
        class_name = "flow-step active" if index == 0 else "flow-step"
        current_attr = ' aria-current="step"' if index == 0 else ""
        flow_item_parts.append(
            f'        <li id="flow-{escape(step["id"])}" data-step-index="{index}" class="{class_name}"{current_attr}>'
            f'<strong>第{index + 1}步：{escape(step["label"])}</strong>'
            f'<span>{escape(step["caption"])}</span></li>'
        )
    flow_items = "\n".join(flow_item_parts)
    learning_items = "\n".join(
        f"        <li>{escape(item)}</li>"
        for item in (
            f"明确{topic}的核心对象和观察目标",
            "通过播放、暂停和重置观察状态变化",
            "调节参数后比较画面、读数和结论的同步变化",
        )
    )
    control_items = "\n".join(_control_markup(control, variable) for control in controls)
    formula_items = "\n".join(f"        <li>{escape(item)}</li>" for item in formulas)
    widget_config_json = json.dumps(widget_config, ensure_ascii=False, indent=2)
    flow_json = json.dumps(teaching_flow, ensure_ascii=False)
    visual_markup = _visual_markup(interactive_type, topic, primary_color, widget_config)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <style>
    :root {{
      --primary: {primary_color};
      --bg: #07111f;
      --panel: #101b2d;
      --panel-strong: #14233a;
      --text: #eef6ff;
      --muted: #a8b8cc;
      --line: rgba(255, 255, 255, 0.12);
    }}
    * {{ box-sizing: border-box; }}
    html, body {{ width: 100%; height: 100%; margin: 0; overflow: hidden; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif;
      background: var(--bg);
      color: var(--text);
    }}
    [data-region="app-shell"] {{
      height: 100%;
      min-height: 540px;
      display: grid;
      grid-template-rows: auto 1fr auto;
      gap: 10px;
      padding: 14px;
    }}
    .topbar, .bottom-grid {{
      display: grid;
      grid-template-columns: 1.25fr 1fr;
      gap: 10px;
      min-height: 0;
    }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      min-width: 0;
    }}
    h1, h2, p, ul {{ margin-top: 0; }}
    h1 {{ margin-bottom: 6px; font-size: 22px; line-height: 1.2; }}
    h2 {{ margin-bottom: 8px; font-size: 15px; }}
    p, li {{ font-size: 13px; line-height: 1.55; }}
    .learning-objectives ul, .flow-list, .formula-list {{ margin: 0; padding-left: 18px; }}
    .stage-wrap {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) 280px;
      gap: 10px;
      min-height: 0;
    }}
    #aetherviz-stage {{
      position: relative;
      min-height: 0;
      display: grid;
      place-items: center;
      overflow: hidden;
      background:
        linear-gradient(rgba(255,255,255,.045) 1px, transparent 1px),
        linear-gradient(90deg, rgba(255,255,255,.045) 1px, transparent 1px),
        #091426;
      background-size: 36px 36px;
    }}
    #aetherviz-stage svg {{
      display: block;
      width: min(100%, 760px);
      height: min(100%, 390px);
      margin: auto;
    }}
    .side-panel {{
      display: grid;
      grid-template-rows: auto auto 1fr;
      gap: 10px;
      min-height: 0;
    }}
    .caption-box {{
      min-height: 72px;
      border-left: 3px solid var(--primary);
      background: var(--panel-strong);
    }}
    .animation-caption {{ margin: 0; color: var(--text); }}
    .control-panel {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
      align-items: center;
    }}
    .control-panel button, .control-panel input, .control-panel select {{
      min-height: 44px;
      border-radius: 8px;
      border: 1px solid rgba(255,255,255,.16);
      background: #17263d;
      color: var(--text);
      font: inherit;
    }}
    .control-panel button {{
      cursor: pointer;
      font-weight: 700;
    }}
    #play-animation {{ background: var(--primary); color: #04111f; }}
    .slider-field {{
      grid-column: span 3;
      display: grid;
      grid-template-columns: auto 1fr auto;
      gap: 8px;
      align-items: center;
      min-width: 0;
    }}
    .slider-field input {{ width: 100%; accent-color: var(--primary); }}
    .readout-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
    }}
    .metric {{
      background: var(--panel-strong);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 8px;
    }}
    .metric span {{ display: block; color: var(--muted); font-size: 12px; }}
    .metric strong {{ display: block; font-size: 18px; color: var(--primary); }}
    .flow-list {{ list-style: none; padding-left: 0; display: grid; gap: 8px; }}
    .flow-step {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 8px;
      background: rgba(255,255,255,.03);
    }}
    .flow-step.active {{
      border-color: var(--primary);
      background: rgba(34, 211, 238, .12);
    }}
    .flow-step strong, .flow-step span {{ display: block; }}
    .flow-step span {{ color: var(--muted); margin-top: 3px; }}
    .main-shape {{ transition: transform .35s ease, opacity .35s ease; }}
    .motion-dot {{ transition: transform .2s linear; }}
    .trace-line {{ transition: stroke-dashoffset .2s linear, opacity .3s ease; }}
    .stage-label {{ font-size: 13px; fill: #dbeafe; font-weight: 700; }}
    .error-banner {{ display: none; color: #fecaca; background: #7f1d1d; padding: 8px; border-radius: 8px; }}
    @media (max-width: 760px) {{
      [data-region="app-shell"] {{ min-height: 100%; padding: 8px; overflow: hidden; }}
      .topbar, .bottom-grid, .stage-wrap {{ grid-template-columns: 1fr; }}
      .stage-wrap {{ grid-template-rows: minmax(220px, 1fr) auto; }}
      .side-panel {{ grid-template-rows: auto auto auto; }}
      h1 {{ font-size: 18px; }}
      p, li {{ font-size: 12px; }}
    }}
  </style>
  <script type="application/json" id="widget-config">
{_json_for_script(widget_config_json)}
  </script>
</head>
<body>
  <div data-region="app-shell">
    <header class="topbar">
      <section class="panel">
        <h1>{escape(title)}</h1>
        <p>{escape(goal)}</p>
      </section>
      <section class="panel learning-objectives" data-region="learning-goal">
        <h2>学习目标</h2>
        <ul>
{learning_items}
        </ul>
      </section>
    </header>

    <main class="stage-wrap">
      <section id="aetherviz-stage" class="panel" data-region="stage" aria-label="{escape(topic)}互动主舞台">
{visual_markup}
      </section>

      <aside class="side-panel">
        <section class="panel caption-box" data-region="caption">
          <h2>当前观察</h2>
          <p id="animation-caption" class="animation-caption">{escape(teaching_flow[0]["caption"])}</p>
        </section>
        <section class="panel" data-region="formula">
          <h2>核心公式或概念</h2>
          <ul class="formula-list">
{formula_items}
          </ul>
          <div class="readout-grid">
            <div class="metric"><span>当前步骤</span><strong id="step-readout">1</strong></div>
            <div class="metric"><span>参数</span><strong id="param-readout">{escape(str(variable["default"]))}</strong></div>
            <div class="metric"><span>变化量</span><strong id="change-readout">0%</strong></div>
          </div>
        </section>
        <section class="panel" data-region="teaching-flow">
          <h2>教学流程</h2>
          <ol class="flow-list">
{flow_items}
          </ol>
        </section>
      </aside>
    </main>

    <footer class="bottom-grid">
      <section class="panel control-panel" data-region="controls" aria-label="控制面板">
{control_items}
      </section>
      <section id="runtime-error" class="error-banner" role="alert"></section>
    </footer>
  </div>

  <script>
    (function () {{
      const teachingFlow = {flow_json};
      const state = {{
        running: false,
        progress: 0,
        speed: 1,
        parameter: {json.dumps(variable["default"], ensure_ascii=False)},
        currentStep: 0
      }};
      const caption = document.getElementById('animation-caption');
      const motionDot = document.getElementById('motion-dot');
      const traceLine = document.getElementById('trace-line');
      const conceptRing = document.getElementById('concept-ring');
      const comparisonBar = document.getElementById('comparison-bar');
      const paramReadout = document.getElementById('param-readout');
      const changeReadout = document.getElementById('change-readout');
      const stepReadout = document.getElementById('step-readout');
      const errorBanner = document.getElementById('runtime-error');
      const parameterInput = document.getElementById('{escape(variable["id"])}');
      let rafId = 0;
      let lastTime = 0;

      function clamp(value, min, max) {{
        return Math.min(max, Math.max(min, value));
      }}

      function setActiveStep(index) {{
        state.currentStep = clamp(index, 0, teachingFlow.length - 1);
        document.querySelectorAll('.flow-step').forEach((item, itemIndex) => {{
          const active = itemIndex === state.currentStep;
          item.classList.toggle('active', active);
          if (active) {{
            item.setAttribute('aria-current', 'step');
          }} else {{
            item.removeAttribute('aria-current');
          }}
        }});
        const step = teachingFlow[state.currentStep] || teachingFlow[0];
        caption.textContent = step.caption;
        stepReadout.textContent = String(state.currentStep + 1);
      }}

      function updateVisualization() {{
        const parameter = Number(state.parameter) || 0;
        const progress = clamp(state.progress, 0, 1);
        const stepIndex = Math.min(teachingFlow.length - 1, Math.floor(progress * teachingFlow.length));
        setActiveStep(stepIndex);
        const x = -180 + 360 * progress;
        const y = 72 - Math.sin(progress * Math.PI) * (80 + parameter * 3);
        motionDot.setAttribute('cx', String(x));
        motionDot.setAttribute('cy', String(y));
        traceLine.style.strokeDashoffset = String(420 - progress * 420);
        conceptRing.setAttribute('r', String(78 + parameter * 3 + Math.sin(progress * Math.PI) * 16));
        comparisonBar.setAttribute('width', String(180 + parameter * 18));
        comparisonBar.setAttribute('x', String(-(180 + parameter * 18) / 2));
        document.querySelectorAll('[data-reveal-index]').forEach((item) => {{
          const revealIndex = Number(item.getAttribute('data-reveal-index')) || 0;
          item.classList.toggle('active', revealIndex <= stepIndex);
          item.style.opacity = revealIndex <= stepIndex ? '1' : '0.28';
        }});
        document.querySelectorAll('[data-game-index]').forEach((item) => {{
          const gameIndex = Number(item.getAttribute('data-game-index')) || 0;
          const lift = gameIndex === stepIndex ? -16 : 0;
          item.setAttribute('transform', 'translate(0 ' + lift + ')');
        }});
        paramReadout.textContent = String(parameter);
        changeReadout.textContent = Math.round(progress * 100) + '%';
      }}

      function tick(time) {{
        if (!lastTime) lastTime = time;
        const delta = Math.min(80, time - lastTime) / 1000;
        lastTime = time;
        if (state.running) {{
          state.progress += delta * 0.18 * state.speed;
          if (state.progress >= 1) {{
            state.progress = 1;
            state.running = false;
          }}
          updateVisualization();
        }}
        rafId = requestAnimationFrame(tick);
      }}

      function play() {{
        if (state.progress >= 1) state.progress = 0;
        state.running = true;
        updateVisualization();
      }}

      function pause() {{
        state.running = false;
        updateVisualization();
      }}

      function reset() {{
        state.running = false;
        state.progress = 0;
        state.speed = 1;
        state.parameter = Number({json.dumps(variable["default"], ensure_ascii=False)}) || 1;
        if (parameterInput) parameterInput.value = String(state.parameter);
        updateVisualization();
      }}

      function setSpeed(value) {{
        state.speed = clamp(Number(value) || 1, 0.25, 3);
      }}

      function update(value) {{
        state.progress = clamp(Number(value) || 0, 0, 1);
        updateVisualization();
      }}

      function getState() {{
        return {{ ...state }};
      }}

      function handleWidgetAction(event) {{
        const data = event.data || {{}};
        if (data.type === 'SET_WIDGET_STATE' && data.state) {{
          Object.entries(data.state).forEach(([key, value]) => {{
            const input = document.getElementById(key + '-slider') || document.querySelector('[data-var="' + key + '"]') || document.getElementById(key);
            if (input) {{
              input.value = String(value);
              input.dispatchEvent(new Event('input', {{ bubbles: true }}));
              input.dispatchEvent(new Event('change', {{ bubbles: true }}));
            }}
          }});
        }}
        if (data.type === 'HIGHLIGHT_ELEMENT' && data.target) {{
          const el = document.querySelector(data.target);
          if (el) el.classList.add('active');
        }}
        if (data.type === 'ANNOTATE_ELEMENT' && data.content) {{
          caption.textContent = String(data.content);
        }}
        if (data.type === 'REVEAL_ELEMENT' && data.target) {{
          const el = document.querySelector(data.target);
          if (el) el.style.opacity = '1';
        }}
      }}

      try {{
        document.getElementById('play-animation').addEventListener('click', () => play());
        document.getElementById('pause-animation').addEventListener('click', () => pause());
        document.getElementById('reset-animation').addEventListener('click', () => reset());
        if (parameterInput) {{
          parameterInput.addEventListener('input', (event) => {{
            state.parameter = Number(event.target.value) || 0;
            updateVisualization();
          }});
        }}
        document.querySelectorAll('[data-speed]').forEach((button) => {{
          button.addEventListener('click', () => setSpeed(button.getAttribute('data-speed')));
        }});
        window.addEventListener('message', handleWidgetAction);
        window.AetherVizRuntime = {{ play, pause, reset, setSpeed, update, getState }};
        window.__AETHERVIZ_RUNTIME_ERROR__ = null;
        window.__AETHERVIZ_RUNTIME_READY__ = true;
        updateVisualization();
        rafId = requestAnimationFrame(tick);
      }} catch (error) {{
        window.__AETHERVIZ_RUNTIME_READY__ = false;
        window.__AETHERVIZ_RUNTIME_ERROR__ = error instanceof Error ? error.message : String(error);
        errorBanner.style.display = 'block';
        errorBanner.textContent = '页面初始化失败：' + window.__AETHERVIZ_RUNTIME_ERROR__;
        if (rafId) cancelAnimationFrame(rafId);
      }}
    }})();
  </script>
</body>
</html>"""


def _visual_markup(interactive_type: str, topic: str, primary_color: str, widget_config: dict[str, Any]) -> str:
    if interactive_type == "diagram":
        return _diagram_visual_markup(topic, primary_color, widget_config)
    if interactive_type == "game":
        return _game_visual_markup(topic, primary_color, widget_config)
    return _simulation_visual_markup(topic, primary_color)


def _svg_defs() -> str:
    return """          <defs>
            <filter id="soft-shadow" x="-20%" y="-20%" width="140%" height="140%">
              <feDropShadow dx="0" dy="8" stdDeviation="8" flood-color="#000000" flood-opacity="0.25"></feDropShadow>
            </filter>
            <marker id="arrow-head" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto">
              <path d="M0,0 L0,6 L9,3 z" fill="#fbbf24"></path>
            </marker>
          </defs>"""


def _simulation_visual_markup(topic: str, primary_color: str) -> str:
    return f"""        <svg viewBox="0 0 640 360" preserveAspectRatio="xMidYMid meet" role="img" aria-label="{escape(topic)}仿真主视觉">
{_svg_defs()}
          <g id="main-visual-group" data-role="main-visual" transform="translate(320 180)">
            <circle id="concept-ring" class="main-shape" data-role="animated-shape" cx="0" cy="0" r="92" fill="rgba(34,211,238,.16)" stroke="{primary_color}" stroke-width="6" filter="url(#soft-shadow)"></circle>
            <path id="trace-line" class="trace-line" data-role="motion-path" d="M-180 72 C-90 -96 80 -96 180 72" fill="none" stroke="#fbbf24" stroke-width="8" stroke-linecap="round" stroke-dasharray="420" stroke-dashoffset="260"></path>
            <circle id="motion-dot" class="motion-dot" data-role="animated-object" cx="-180" cy="72" r="16" fill="#f97316"></circle>
            <rect id="comparison-bar" class="main-shape" data-role="comparison-bar" x="-150" y="120" width="300" height="18" rx="9" fill="{primary_color}" opacity=".68"></rect>
            <text x="0" y="-6" text-anchor="middle" class="stage-label">{escape(topic[:18])}</text>
            <text x="0" y="24" text-anchor="middle" class="stage-label">参数驱动变化</text>
          </g>
        </svg>"""


def _diagram_visual_markup(topic: str, primary_color: str, widget_config: dict[str, Any]) -> str:
    raw_nodes = widget_config.get("nodes") if isinstance(widget_config.get("nodes"), list) else []
    nodes = [node for node in raw_nodes if isinstance(node, dict)][:4]
    while len(nodes) < 4:
        defaults = [
            {"id": "core", "label": topic},
            {"id": "cause", "label": "关键原因"},
            {"id": "process", "label": "变化过程"},
            {"id": "result", "label": "结果结论"},
        ]
        nodes.append(defaults[len(nodes)])
    positions = [(-170, -70), (0, -102), (170, -70), (0, 84)]
    node_parts = []
    for index, node in enumerate(nodes):
        x, y = positions[index]
        label = _safe_text(node.get("label") or node.get("id"), fallback=f"节点{index + 1}", limit=10)
        node_parts.append(
            f'            <g id="diagram-node-{index + 1}" data-role="diagram-node" data-reveal-index="{index}" transform="translate({x} {y})">'
            f'<circle r="42" fill="rgba(34,211,238,.14)" stroke="{primary_color}" stroke-width="4"></circle>'
            f'<text text-anchor="middle" y="5" class="stage-label">{escape(label)}</text></g>'
        )
    return f"""        <svg viewBox="0 0 640 360" preserveAspectRatio="xMidYMid meet" role="img" aria-label="{escape(topic)}图解主视觉">
{_svg_defs()}
          <g id="main-visual-group" data-role="main-visual" transform="translate(320 180)">
            <path id="trace-line" class="trace-line" data-role="relationship-path" d="M-132 -70 C-70 -120 70 -120 132 -70 M132 -42 C96 16 58 54 28 76 M-132 -42 C-96 16 -58 54 -28 76" fill="none" stroke="#fbbf24" stroke-width="5" stroke-linecap="round" stroke-dasharray="420" stroke-dashoffset="260" marker-end="url(#arrow-head)"></path>
            <circle id="concept-ring" class="main-shape" data-role="focus-halo" cx="0" cy="-102" r="54" fill="none" stroke="{primary_color}" stroke-width="5" filter="url(#soft-shadow)"></circle>
{chr(10).join(node_parts)}
            <circle id="motion-dot" class="motion-dot" data-role="reveal-pointer" cx="-180" cy="72" r="12" fill="#f97316"></circle>
            <rect id="comparison-bar" class="main-shape" data-role="reveal-meter" x="-150" y="138" width="300" height="14" rx="7" fill="{primary_color}" opacity=".68"></rect>
            <text x="0" y="150" text-anchor="middle" class="stage-label">{escape(topic[:18])} 关系逐步揭示</text>
          </g>
        </svg>"""


def _game_visual_markup(topic: str, primary_color: str, widget_config: dict[str, Any]) -> str:
    challenge = _safe_text(widget_config.get("challenge") or widget_config.get("description"), fallback=f"完成{topic}挑战", limit=18)
    return f"""        <svg viewBox="0 0 640 360" preserveAspectRatio="xMidYMid meet" role="img" aria-label="{escape(topic)}游戏主视觉">
{_svg_defs()}
          <g id="main-visual-group" data-role="main-visual" transform="translate(320 180)">
            <path id="trace-line" class="trace-line" data-role="strategy-path" d="M-190 80 C-120 -60 120 -60 190 80" fill="none" stroke="#fbbf24" stroke-width="6" stroke-linecap="round" stroke-dasharray="420" stroke-dashoffset="260"></path>
            <circle id="concept-ring" class="main-shape" data-role="target-zone" cx="0" cy="-16" r="74" fill="rgba(34,211,238,.12)" stroke="{primary_color}" stroke-width="5" filter="url(#soft-shadow)"></circle>
            <g id="game-piece-1" data-role="game-piece" data-game-index="0" transform="translate(0 0)"><rect x="-210" y="102" width="118" height="44" rx="10" fill="#17263d" stroke="{primary_color}" stroke-width="3"></rect><text x="-151" y="130" text-anchor="middle" class="stage-label">观察</text></g>
            <g id="game-piece-2" data-role="game-piece" data-game-index="1" transform="translate(0 0)"><rect x="-59" y="102" width="118" height="44" rx="10" fill="#17263d" stroke="#fbbf24" stroke-width="3"></rect><text x="0" y="130" text-anchor="middle" class="stage-label">操作</text></g>
            <g id="game-piece-3" data-role="game-piece" data-game-index="2" transform="translate(0 0)"><rect x="92" y="102" width="118" height="44" rx="10" fill="#17263d" stroke="#f97316" stroke-width="3"></rect><text x="151" y="130" text-anchor="middle" class="stage-label">反馈</text></g>
            <circle id="motion-dot" class="motion-dot" data-role="player-token" cx="-180" cy="72" r="16" fill="#f97316"></circle>
            <rect id="comparison-bar" class="main-shape" data-role="success-meter" x="-150" y="162" width="300" height="16" rx="8" fill="{primary_color}" opacity=".68"></rect>
            <text x="0" y="-20" text-anchor="middle" class="stage-label">{escape(challenge)}</text>
            <text x="0" y="12" text-anchor="middle" class="stage-label">达成条件后获得即时反馈</text>
          </g>
        </svg>"""


def _safe_text(value: Any, *, fallback: str, limit: int) -> str:
    text = str(value or "").strip() or fallback
    return text[:limit]


def _safe_color(value: Any) -> str:
    text = str(value or "").strip()
    if len(text) == 7 and text.startswith("#"):
        return text
    return "#22D3EE"


def _json_for_script(value: str) -> str:
    return value.replace("</", "<\\/")


def _normalize_text_list(value: Any, *, fallback: list[str], max_items: int) -> list[str]:
    items = [str(item).strip() for item in value or [] if str(item).strip()] if isinstance(value, list) else []
    items = items[:max_items] or fallback
    return [item[:80] for item in items]


def _normalize_teaching_flow(value: Any, topic: str) -> list[dict[str, str]]:
    defaults = [
        {"id": "observe", "label": "观察初始状态", "focus": "核心对象清晰出现", "caption": f"先观察{topic}的核心对象和初始状态。"},
        {"id": "interact", "label": "操作互动控件", "focus": "参数变化驱动画面", "caption": "拖动参数或点击播放，比较画面中的变化。"},
        {"id": "conclude", "label": "归纳结论", "focus": "读数与结论同步", "caption": "把观察到的变化与核心结论对应起来。"},
    ]
    if not isinstance(value, list):
        return defaults
    steps: list[dict[str, str]] = []
    for index, item in enumerate(value[:5]):
        if not isinstance(item, dict):
            continue
        steps.append(
            {
                "id": _dom_id(item.get("id") or f"step-{index + 1}"),
                "label": _safe_text(item.get("label"), fallback=defaults[min(index, 2)]["label"], limit=28),
                "focus": _safe_text(item.get("focus"), fallback=defaults[min(index, 2)]["focus"], limit=60),
                "caption": _safe_text(item.get("caption"), fallback=defaults[min(index, 2)]["caption"], limit=90),
            }
        )
    while len(steps) < 3:
        steps.append(defaults[len(steps)])
    return steps


def _normalize_controls(value: Any, interactive_type: str) -> list[dict[str, str]]:
    defaults = [
        {"id": "play-animation", "label": "播放", "type": "button", "action": "play"},
        {"id": "pause-animation", "label": "暂停", "type": "button", "action": "pause"},
        {"id": "reset-animation", "label": "重置", "type": "button", "action": "reset"},
        {"id": "parameter-slider", "label": "关键参数", "type": "slider", "bind": "parameter"},
    ]
    if interactive_type == "diagram":
        defaults[-1]["label"] = "揭示强度"
    if interactive_type == "game":
        defaults[-1]["label"] = "挑战难度"

    controls = []
    if isinstance(value, list):
        for item in value[:5]:
            if not isinstance(item, dict):
                continue
            control_type = str(item.get("type") or "button")
            if control_type not in {"slider", "button", "speed", "toggle", "select"}:
                control_type = "button"
            controls.append(
                {
                    "id": _dom_id(item.get("id") or item.get("bind") or item.get("action") or f"control-{len(controls) + 1}"),
                    "label": _safe_text(item.get("label"), fallback="互动控件", limit=24),
                    "type": control_type,
                    "bind": _dom_id(item.get("bind") or "parameter"),
                    "action": _dom_id(item.get("action") or ""),
                }
            )
    merged = defaults + [control for control in controls if control["id"] not in {item["id"] for item in defaults}]
    return merged


def _widget_config(value: Any, interactive_type: str, topic: str, controls: list[dict[str, str]]) -> dict[str, Any]:
    config = dict(value) if isinstance(value, dict) else {}
    config["type"] = interactive_type
    config.setdefault("concept", topic)
    config.setdefault("description", f"通过互动控件观察{topic}的关键变化。")
    if interactive_type == "simulation":
        variables = config.get("variables")
        if not isinstance(variables, list) or not variables:
            variables = [
                {"name": "parameter", "label": "关键参数", "min": 1, "max": 10, "default": 5, "step": 1, "unit": ""},
            ]
        config["variables"] = variables
        config.setdefault("presets", [{"id": "default", "label": "默认", "values": {"parameter": 5}}])
        config.setdefault("observations", ["观察参数改变后主舞台、读数和结论如何同步变化。"])
    elif interactive_type == "diagram":
        config.setdefault("nodes", [{"id": "core", "label": topic, "details": "核心概念", "explanation": "核心概念"}])
        config.setdefault("edges", [])
        config.setdefault("revealOrder", config.get("reveal_order") or ["core"])
    else:
        config.setdefault("gameType", config.get("game_type") or "manipulation")
        config.setdefault("gameConfig", config.get("game_config") or {"controls": [control["id"] for control in controls]})
        config.setdefault("successCondition", config.get("success_condition") or "完成操作并解释关键变化。")
        config.setdefault("feedbackRules", config.get("feedback_rules") or ["操作后给出即时反馈。"])
    return config


def _primary_variable(widget_config: dict[str, Any]) -> dict[str, Any]:
    variables = widget_config.get("variables")
    first = variables[0] if isinstance(variables, list) and variables and isinstance(variables[0], dict) else {}
    name = _dom_id(first.get("name") or "parameter")
    return {
        "id": f"{name}-slider",
        "name": name,
        "label": str(first.get("label") or "关键参数"),
        "min": first.get("min", 1),
        "max": first.get("max", 10),
        "step": first.get("step", 1),
        "default": first.get("default", 5),
    }


def _control_markup(control: dict[str, str], variable: dict[str, Any]) -> str:
    control_id = control["id"]
    label = escape(control["label"])
    action = control.get("action")
    if control_id in {"play-animation", "pause-animation", "reset-animation"}:
        return f'        <button id="{control_id}" type="button">{label}</button>'
    if control["type"] in {"slider", "speed"}:
        return (
            f'        <label class="slider-field" for="{escape(variable["id"])}">'
            f'<span>{label}</span>'
            f'<input id="{escape(variable["id"])}" data-var="{escape(variable["name"])}" type="range"'
            f' min="{escape(str(variable["min"]))}" max="{escape(str(variable["max"]))}"'
            f' step="{escape(str(variable["step"]))}" value="{escape(str(variable["default"]))}">'
            f'<span id="{escape(variable["name"])}-value">{escape(str(variable["default"]))}</span></label>'
        )
    if action == "pause":
        return f'        <button id="pause-animation" type="button">{label}</button>'
    if action == "reset":
        return f'        <button id="reset-animation" type="button">{label}</button>'
    if action == "play":
        return f'        <button id="play-animation" type="button">{label}</button>'
    return f'        <button id="{escape(control_id)}" type="button" data-speed="1">{label}</button>'


def _dom_id(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = "".join(char if char.isalnum() else "-" for char in text)
    text = "-".join(part for part in text.split("-") if part)
    return text or "item"
