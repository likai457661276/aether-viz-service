"""AI互动实验 OpenMAIC interactive fallback tests."""

import json

import pytest
from fastapi.testclient import TestClient

import aetherviz_service.aetherviz.react as react_module
from aetherviz_service.aetherviz.theme import DEFAULT_PRIMARY_COLOR, extract_color_from_topic
from aetherviz_service.llm_service import LLMStreamChunk
from aetherviz_service.main import app

client = TestClient(app)


def parse_sse_events(response):
    events = []
    current_event = None
    current_data = None
    for line in response.text.splitlines():
        if line.startswith("event: "):
            current_event = line.removeprefix("event: ")
        elif line.startswith("data: "):
            current_data = json.loads(line.removeprefix("data: "))
        elif line == "" and current_event and current_data is not None:
            events.append((current_event, current_data))
            current_event = None
            current_data = None
    return events


def sample_approved_plan(topic: str = "熵增演示") -> dict:
    return {
        "page_type": "interactive",
        "interactive_type": "simulation",
        "subject": "general",
        "title": f"{topic}互动动画",
        "goal": f"用单页互动仿真解释“{topic}”的核心过程。",
        "learner_level": "初中/高中",
        "stage_layout": "顶部展示学习目标，中间大舞台展示主动画，底部放置播放控制和公式结论。",
        "interactive_spec": {
            "concept": topic,
            "description": "通过调节关键参数观察状态扩散和结论变化。",
            "variables": [
                {"name": "speed", "label": "速度", "min": 0.5, "max": 2, "default": 1, "step": 0.1, "unit": "x"}
            ],
            "presets": [{"id": "default", "label": "默认", "values": {"speed": 1}}],
            "observations": ["观察速度变化后主舞台和 caption 如何同步更新。"],
        },
        "teaching_flow": [
            {"id": "observe", "label": "初始观察", "focus": "初始状态居中出现", "caption": "先观察初始状态。"},
            {"id": "interact", "label": "参数互动", "focus": "核心变化被高亮", "caption": "调节参数观察核心变化。"},
            {"id": "conclude", "label": "结论总结", "focus": "结论区同步总结", "caption": "回顾结论。"},
        ],
        "controls": [
            {"id": "speed-control", "label": "速度", "type": "slider", "bind": "speed"},
            {"id": "play-button", "label": "播放", "type": "button", "action": "play"},
            {"id": "reset-button", "label": "重置", "type": "button", "action": "reset"},
        ],
        "formulas": [],
        "runtime": {"render_stack": "dom_svg", "animation_runtime": "native", "external_libraries": []},
        "primary_color": "#22D3EE",
    }


def sample_svg_html(topic: str = "熵增演示", marker: str = "ready") -> str:
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{topic}</title>
<link rel="stylesheet" href="https://cdn.staticfile.net/KaTeX/0.16.9/katex.min.css">
<style>
body {{ margin: 0; font-family: sans-serif; }}
#aetherviz-stage {{ width: 100%; min-height: 240px; display: grid; place-items: center; }}
#aetherviz-stage svg {{ display: block; margin: auto; max-width: 100%; max-height: 100%; }}
</style>
<script type="application/json" id="widget-config">
{{
  "type": "simulation",
  "concept": "{topic}",
  "description": "通过调节关键参数观察状态扩散和结论变化。",
  "variables": [{{"name": "param", "label": "关键参数", "min": 0, "max": 100, "default": 50, "unit": ""}}],
  "presets": [{{"id": "default", "label": "默认", "variables": {{"param": 50}}}}],
  "observations": ["观察参数改变后主舞台和 caption 如何同步更新。"]
}}
</script>
</head>
<body>
<h1>{topic}</h1>
<section class="learning-objectives">
  <h2>学习目标</h2>
  <ul>
    <li>学习目标1</li>
    <li>学习目标2</li>
    <li>学习目标3</li>
  </ul>
</section>
<section>
  <h2>核心概念</h2>
  <p>核心概念A</p>
</section>
<main id="aetherviz-stage">
  <p id="animation-caption" class="animation-caption">当前步骤：观察核心图形如何随进度变化。</p>
  <svg viewBox="0 0 320 180" preserveAspectRatio="xMidYMid meet" role="img" aria-label="{topic}互动图形">
    <g id="main-visual-group">
      <path id="main-curve" d="M20 140 C90 40 190 40 300 140" stroke="#22D3EE" fill="none" stroke-width="4"></path>
      <circle id="moving-dot" cx="160" cy="80" r="10" fill="#FBBF24"></circle>
    </g>
  </svg>
</main>
<div class="control-panel">
  <button id="play-animation">播放</button>
  <button id="pause-animation">暂停</button>
  <button id="reset-animation">重置</button>
  <input type="range" id="param">
</div>
<script src="https://cdn.staticfile.net/KaTeX/0.16.9/katex.min.js"></script>
<script>
const state = {{ mode: 'playing', progress: 0 }};
const caption = document.getElementById('animation-caption');
const movingDot = document.getElementById('moving-dot');
const mainCurve = document.getElementById('main-curve');
function handleWidgetAction(event) {{
  const {{ type, target, state: widgetState, content }} = event.data || {{}};
  if (type === 'SET_WIDGET_STATE' && widgetState) {{
    Object.entries(widgetState).forEach(([key, value]) => {{
      const input = document.getElementById(key + '-slider') || document.querySelector('[data-var="' + key + '"]') || document.getElementById(key);
      if (input) {{
        input.value = value;
        input.dispatchEvent(new Event('input', {{ bubbles: true }}));
      }}
    }});
  }}
  if (type === 'HIGHLIGHT_ELEMENT' && target) {{
    const el = document.querySelector(target);
    if (el) el.setAttribute('data-highlighted', 'true');
  }}
  if (type === 'ANNOTATE_ELEMENT' && target && content) {{
    caption.textContent = String(content);
  }}
  if (type === 'REVEAL_ELEMENT' && target) {{
    const el = document.querySelector(target);
    if (el) el.style.opacity = '1';
  }}
}}
function updateVisualization() {{
  state.progress = (state.progress + 1) % 100;
  const x = 80 + state.progress * 1.6;
  movingDot.setAttribute('cx', String(x));
  mainCurve.style.strokeDashoffset = String(100 - state.progress);
  caption.textContent = state.progress < 34
    ? '当前步骤：先观察初始状态。'
    : state.progress < 67
      ? '当前步骤：核心对象正在移动并留下变化线索。'
      : '当前步骤：结论区同步回顾核心规律。';
}}
function play() {{ updateVisualization(); }}
function pause() {{ state.mode = 'paused'; }}
function reset() {{ state.progress = 0; updateVisualization(); }}
function setSpeed(value) {{ state.speed = Number(value) || 1; }}
function update(value) {{ state.progress = Number(value) || state.progress; updateVisualization(); }}
function getState() {{ return {{ ...state }}; }}
function animationLoop() {{
  requestAnimationFrame(animationLoop);
  updateVisualization();
}}
window.addEventListener('resize', () => updateVisualization());
document.getElementById('play-animation').addEventListener('click', () => play());
document.getElementById('pause-animation').addEventListener('click', () => pause());
document.getElementById('reset-animation').addEventListener('click', () => reset());
window.addEventListener('message', handleWidgetAction);
window.AetherVizRuntime = {{ play, pause, reset, setSpeed, update, getState }};
window.__AETHERVIZ_RUNTIME_READY__ = true;
window.__AETHERVIZ_RUNTIME_ERROR__ = null;
animationLoop();
console.log("{marker}");
</script>
</body>
</html>"""


def oversized_sample_html(topic: str = "熵增演示", marker: str = "oversized") -> str:
    return sample_svg_html(topic=topic, marker=marker).replace(
        "</main>",
        f"<section data-region=\"caption\">{'超长说明' * 12000}</section></main>",
    )


def test_generate_aetherviz_spec_returns_400_when_topic_empty() -> None:
    response = client.post("/generate-aetherviz-spec", json={"topic": "   "})

    assert response.status_code == 400
    assert response.json()["detail"] == "topic 不能为空"


def test_static_page_routes_are_removed() -> None:
    assert client.get("/aetherviz-static-knowledge-points").status_code == 404
    assert client.get("/aetherviz-static-html", params={"knowledge_point_id": "physics/newton_second_law"}).status_code == 404
    assert client.get("/static-html/physics/newton-second-law.html").status_code == 404


def test_unmatched_topic_plan_phase_streams_plan_without_html_generation(monkeypatch) -> None:
    stream_calls = []

    def fake_llm_stream(prompt: str, system_prompt: str, max_tokens: int = 0, temperature: float = 0.3, enable_thinking: bool = False):
        stream_calls.append((prompt, system_prompt, max_tokens, temperature, enable_thinking))
        raw = json.dumps({
            "page_type": "interactive",
            "interactive_type": "diagram",
            "subject": "general",
            "title": "熵增演示互动动画",
            "goal": "用清晰分镜动画解释熵增演示。",
            "stage_layout": "顶部目标导航，中间大舞台，底部控制条和结论区。",
            "interactive_spec": {"nodes": [{"id": "entropy", "label": "熵增"}], "edges": [], "reveal_order": ["entropy"]},
            "teaching_flow": [{"id": "step", "label": "生活类比", "focus": "粒子初始聚集", "caption": "观察聚集状态。"}],
            "controls": [{"id": "step-button", "label": "下一步", "type": "button"}],
            "formulas": [],
            "runtime": {"render_stack": "dom_svg", "animation_runtime": "native", "external_libraries": []},
            "primary_color": "#22D3EE",
        })
        yield raw[:80]
        yield raw[80:]

    monkeypatch.setattr(react_module, "call_planning_llm_stream", fake_llm_stream)

    response = client.post("/generate-aetherviz-spec", json={"topic": "熵增演示"})

    assert response.status_code == 200
    events = parse_sse_events(response)
    assert [event for event, _ in events][-1] == "plan_ready"
    assert "plan_delta" in [event for event, _ in events]
    plan = events[-1][1]["plan"]
    assert len(stream_calls) == 1
    assert stream_calls[0][2] == react_module.PLANNING_MAX_TOKENS
    assert stream_calls[0][4] is True
    assert plan["subject"] == "general"
    assert plan["page_type"] == "interactive"
    assert plan["interactive_type"] in ("simulation", "diagram", "game")
    assert plan["runtime"]["render_stack"] == "dom_svg"
    assert plan["controls"][0]["type"] == "button"
    assert "html" not in events[-1][1]


def test_plan_phase_disables_reasoning_delta_and_streams_math_css_mode(monkeypatch) -> None:
    calls = []

    def fake_llm_stream(prompt: str, system_prompt: str, max_tokens: int = 0, temperature: float = 0.3, enable_thinking: bool = False):
        calls.append((prompt, system_prompt, max_tokens, temperature, enable_thinking))
        yield LLMStreamChunk(kind="reasoning", delta="先判断这是数学几何主题。")
        raw = json.dumps({
            "page_type": "interactive",
            "interactive_type": "simulation",
            "subject": "math",
            "title": "几何定理互动动画",
            "goal": "通过拖动参数观察几何关系。",
            "stage_layout": "顶部目标导航，中间大几何舞台，底部控制条和公式结论。",
            "interactive_spec": {
                "concept": "几何定理",
                "variables": [{"name": "parameter", "label": "几何参数", "min": 1, "max": 10, "default": 3, "step": 1}],
                "observations": ["观察参数变化和几何关系。"],
            },
            "teaching_flow": [{"id": "observe", "label": "显示几何图形", "focus": "几何图形居中", "caption": "观察关键量。"}],
            "controls": [{"id": "parameter-slider", "label": "几何参数", "type": "slider"}],
            "formulas": ["几何定理"],
            "runtime": {"render_stack": "svg", "animation_runtime": "native", "external_libraries": []},
            "primary_color": "#22D3EE",
        })
        yield LLMStreamChunk(kind="content", delta=raw)

    monkeypatch.setattr(react_module, "call_planning_llm_stream", fake_llm_stream)

    response = client.post("/generate-aetherviz-spec", json={"topic": "几何定理"})

    events = parse_sse_events(response)
    assert "thinking_delta" not in [event for event, _ in events]
    assert events[-1][0] == "plan_ready"
    assert events[-1][1]["plan"]["interactive_type"] == "simulation"
    assert len(calls) == 1
    assert calls[0][2] == react_module.PLANNING_MAX_TOKENS
    assert calls[0][4] is True


def test_generate_phase_requires_approved_plan() -> None:
    response = client.post(
        "/generate-aetherviz-spec",
        json={"topic": "熵增演示", "phase": "generate"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "approved_plan 不能为空"


def test_generate_phase_uses_approved_plan_for_html(monkeypatch) -> None:
    calls = []

    def fake_llm_stream(prompt: str, system_prompt: str, max_tokens: int = 0, temperature: float = 0.3, enable_thinking: bool = False):
        calls.append((prompt, system_prompt, max_tokens, temperature, enable_thinking))
        html = sample_svg_html(marker="ready")
        yield LLMStreamChunk(kind="reasoning", delta="先规划动画叙事、舞台布局和互动控件。")
        yield html[:120]
        yield html[120:]

    monkeypatch.setattr(react_module, "call_llm_stream", fake_llm_stream)

    response = client.post(
        "/generate-aetherviz-spec",
        json={"topic": "熵增演示", "phase": "generate", "approved_plan": sample_approved_plan()},
    )

    events = parse_sse_events(response)
    assert events[-1][0] == "done"
    assert "thinking_delta" in [event for event, _ in events]
    assert "generation_delta" in [event for event, _ in events]
    done_data = events[-1][1]
    html = done_data["html"]
    assert len(calls) == 1
    assert calls[0][2] == react_module.HTML_OUTPUT_MAX_TOKENS
    assert calls[0][4] is True
    prompt, system_prompt = calls[0][0], calls[0][1]
    assert "#aetherviz-stage" in prompt + system_prompt
    assert "中文旁白" in prompt + system_prompt
    assert "不能遮挡主图" in prompt + system_prompt
    assert "禁止页面级滚动条" in prompt + system_prompt
    assert "至少 3 个可观察状态变化" in prompt
    assert "不要生成可见全局进度条" in prompt
    assert "https://cdn.jsdelivr.net/npm/gsap@3/dist/gsap.min.js" in prompt + system_prompt
    assert "gsap.timeline" in prompt + system_prompt
    assert "生成来源文案" in prompt
    assert "caption 必须随动画状态更新" in system_prompt
    assert "高饱和度" not in prompt + system_prompt
    assert "极为精美" not in prompt + system_prompt
    assert "双语字幕" not in prompt + system_prompt
    assert "1920" not in prompt + system_prompt
    assert "2K" not in prompt + system_prompt
    assert "由 宾果AI 为你生成" not in prompt + system_prompt
    assert "progress-slider" not in prompt + system_prompt
    assert "missing_stage_visual_centering" not in html
    assert '<title>熵增演示</title>' in html
    assert "学习目标1" in html
    assert "核心概念A" in html
    assert done_data["metadata"]["source"] == "llm_interactive"
    assert done_data["metadata"]["attempts"] == 1
    assert done_data["metadata"]["degraded"] is False
    assert done_data["metadata"]["render_mode"] in ("simulation", "diagram", "game")
    assert done_data["metadata"]["plan"]["controls"][0]["id"] == "speed-control"
    assert done_data["output_tokens_total"] > 0


def test_generate_phase_converts_english_reasoning_to_chinese_summary(monkeypatch) -> None:
    def fake_llm_stream(prompt: str, system_prompt: str, max_tokens: int = 0, temperature: float = 0.3, enable_thinking: bool = False):
        yield LLMStreamChunk(
            kind="reasoning",
            delta=(
                "I'll structure the teaching flow: observe, compare, "
                "then enable sliders and write the HTML/CSS code carefully."
            ),
        )
        yield sample_svg_html(marker="ready")

    monkeypatch.setattr(react_module, "call_llm_stream", fake_llm_stream)

    response = client.post(
        "/generate-aetherviz-spec",
        json={"topic": "熵增演示", "phase": "generate", "approved_plan": sample_approved_plan()},
    )

    events = parse_sse_events(response)
    thinking_events = [data for event, data in events if event == "thinking_delta"]
    assert thinking_events
    thinking_delta = thinking_events[0]["delta"]
    assert "梳理教学流程" in thinking_delta
    assert "规划播放、暂停、重置、速度和教学参数控件" in thinking_delta
    assert "I'll structure" not in thinking_delta
    assert "observe" not in thinking_delta
    assert events[-1][0] == "done"


def test_generate_phase_stops_stream_after_complete_html(monkeypatch) -> None:
    yielded = []

    def fake_llm_stream(prompt: str, system_prompt: str, max_tokens: int = 0, temperature: float = 0.3, enable_thinking: bool = False):
        html = sample_svg_html(marker="ready")
        yielded.append("html")
        yield html
        yielded.append("after-close")
        yield "不应继续等待或消费的尾部内容"

    monkeypatch.setattr(react_module, "call_llm_stream", fake_llm_stream)

    response = client.post(
        "/generate-aetherviz-spec",
        json={"topic": "熵增演示", "phase": "generate", "approved_plan": sample_approved_plan()},
    )

    events = parse_sse_events(response)
    assert events[-1][0] == "done"
    assert yielded == ["html"]
    assert "不应继续等待" not in events[-1][1]["html"]


def test_svg_validation_rejects_three_dependency() -> None:
    from aetherviz_service.aetherviz.validator import (
        AetherVizHtmlValidationError,
        validate_aetherviz_html,
    )

    bad_html = """<!DOCTYPE html>
<html>
<body>
<h1>熵增演示</h1>
<script src="https://cdn.staticfile.net/three.js/r134/three.min.js"></script>
<script>
const scene = new THREE.Scene();
const renderer = new THREE.WebGLRenderer();
function animationLoop() { requestAnimationFrame(animationLoop); }
animationLoop();
</script>
</body>
</html>"""

    try:
        validate_aetherviz_html(
            bad_html,
            topic="熵增演示",
            strict=False,
        )
    except AetherVizHtmlValidationError as exc:
        message = str(exc)
    else:
        raise AssertionError("动态 SVG 输出引入 Three.js 时必须校验失败")

    assert "非白名单外部资源" in message
    assert "three.js" in message


def test_svg_validation_accepts_minimum_contract() -> None:
    from aetherviz_service.aetherviz.validator import validate_aetherviz_html

    warnings = validate_aetherviz_html(
        sample_svg_html(),
        topic="熵增演示",
        strict=True,
    )

    assert isinstance(warnings, list)


def test_parse_and_validate_html_uses_basic_html_contract_only() -> None:
    from aetherviz_service.aetherviz.html_output import parse_and_validate_html

    bad_html = sample_svg_html().replace(
        "window.AetherVizRuntime = { play, pause, reset, setSpeed, update, getState };",
        "window.LegacyRuntime = { play, pause, reset, setSpeed, update, getState };",
    )

    html, warnings = parse_and_validate_html(bad_html, "熵增演示", sample_approved_plan())

    assert "window.LegacyRuntime" in html
    assert isinstance(warnings, list)


def test_validation_rejects_oversized_stage_formula_and_readout() -> None:
    from aetherviz_service.aetherviz.validator import (
        AetherVizHtmlValidationError,
        validate_aetherviz_html,
    )

    bad_html = sample_svg_html().replace(
        "#aetherviz-stage svg { display: block; margin: auto; max-width: 100%; max-height: 100%; }",
        "#aetherviz-stage svg { display: block; margin: auto; max-width: 100%; max-height: 100%; }\n.stage-number { font-size: clamp(3rem, 14vw, 150px); }",
    ).replace(
        "</g>",
        '<text class="stage-number" transform="scale(1.2)" x="80" y="95">读数=64</text>\n    </g>',
        1,
    )

    with pytest.raises(AetherVizHtmlValidationError) as exc_info:
        validate_aetherviz_html(bad_html, topic="几何定理", strict=True)

    assert "oversized_stage_text" in str(exc_info.value)


def test_validation_rejects_uncentered_stage_visual() -> None:
    from aetherviz_service.aetherviz.validator import (
        AetherVizHtmlValidationError,
        validate_aetherviz_html,
    )

    bad_html = sample_svg_html().replace(
        "#aetherviz-stage { width: 100%; min-height: 240px; display: grid; place-items: center; }",
        "#aetherviz-stage { width: 100%; min-height: 240px; }",
    )
    bad_html = bad_html.replace(
        "#aetherviz-stage svg { display: block; margin: auto; max-width: 100%; max-height: 100%; }\n",
        "",
    )
    bad_html = bad_html.replace(' preserveAspectRatio="xMidYMid meet"', "")
    bad_html = bad_html.replace('<g id="main-visual-group">\n      ', "")
    bad_html = bad_html.replace("\n    </g>", "")

    with pytest.raises(AetherVizHtmlValidationError) as exc_info:
        validate_aetherviz_html(bad_html, topic="熵增演示", strict=False)

    assert "missing_stage_visual_centering" in str(exc_info.value)


def test_validation_allows_gsap_core_dependency() -> None:
    from aetherviz_service.aetherviz.validator import validate_aetherviz_html

    html = sample_svg_html().replace(
        "</head>",
        '<script src="https://cdn.jsdelivr.net/npm/gsap@3/dist/gsap.min.js"></script>\n</head>',
    ).replace(
        "console.log(\"ready\");",
        "gsap.timeline();\nconsole.log(\"ready\");",
    )

    warnings = validate_aetherviz_html(html, topic="熵增演示", strict=True)

    assert warnings == []


def test_validation_rejects_gsap_plugin_dependency() -> None:
    from aetherviz_service.aetherviz.validator import (
        AetherVizHtmlValidationError,
        validate_aetherviz_html,
    )

    bad_html = sample_svg_html().replace(
        "</head>",
        '<script src="https://cdn.jsdelivr.net/npm/gsap@3/dist/ScrollTrigger.min.js"></script>\n</head>',
    )

    with pytest.raises(AetherVizHtmlValidationError) as exc_info:
        validate_aetherviz_html(bad_html, topic="熵增演示", strict=True)

    assert "非白名单外部资源" in str(exc_info.value)


def test_validation_rejects_missing_animation_caption() -> None:
    from aetherviz_service.aetherviz.validator import (
        AetherVizHtmlValidationError,
        validate_aetherviz_html,
    )

    bad_html = sample_svg_html().replace(
        '  <p id="animation-caption" class="animation-caption">当前步骤：观察核心图形如何随进度变化。</p>\n',
        "",
    )

    with pytest.raises(AetherVizHtmlValidationError) as exc_info:
        validate_aetherviz_html(bad_html, topic="熵增演示", strict=True)

    assert "missing_caption_state_update" in str(exc_info.value)


def test_validation_rejects_static_poster_without_stateful_caption_or_visual_update() -> None:
    from aetherviz_service.aetherviz.validator import (
        AetherVizHtmlValidationError,
        validate_aetherviz_html,
    )

    bad_html = sample_svg_html().replace(
        """  const x = 80 + state.progress * 1.6;
  movingDot.setAttribute('cx', String(x));
  mainCurve.style.strokeDashoffset = String(100 - state.progress);
  caption.textContent = state.progress < 34
    ? '当前步骤：先观察初始状态。'
    : state.progress < 67
      ? '当前步骤：核心对象正在移动并留下变化线索。'
      : '当前步骤：结论区同步回顾核心规律。';""",
        "  void state.progress;",
    )

    with pytest.raises(AetherVizHtmlValidationError) as exc_info:
        validate_aetherviz_html(bad_html, topic="熵增演示", strict=True)

    message = str(exc_info.value)
    assert "missing_visual_state_update" in message


def test_validation_rejects_katex_auto_render_without_auto_cdn() -> None:
    from aetherviz_service.aetherviz.validator import (
        AetherVizHtmlValidationError,
        validate_aetherviz_html,
    )

    bad_html = sample_svg_html(topic="二次函数").replace(
        'console.log("ready");',
        'renderMathInElement(document.body);\nconsole.log("ready");',
    )

    with pytest.raises(AetherVizHtmlValidationError) as exc_info:
        validate_aetherviz_html(bad_html, topic="二次函数", strict=True)

    assert "renderMathInElement" in str(exc_info.value)
    assert "auto-render" in str(exc_info.value)


def test_validation_rejects_noop_play_button_binding() -> None:
    from aetherviz_service.aetherviz.validator import (
        AetherVizHtmlValidationError,
        validate_aetherviz_html,
    )

    bad_html = sample_svg_html().replace(
        "document.getElementById('play-animation').addEventListener('click', () => play());",
        "document.getElementById('play-animation').addEventListener('click', () => { console.log('noop'); });",
    )

    with pytest.raises(AetherVizHtmlValidationError) as exc_info:
        validate_aetherviz_html(bad_html, topic="熵增演示", strict=True)

    assert "missing_animation_replay_binding" in str(exc_info.value)


def test_validation_rejects_inline_script_syntax_error() -> None:
    from aetherviz_service.aetherviz.validator import (
        AetherVizHtmlValidationError,
        validate_aetherviz_html,
    )

    bad_html = sample_svg_html(marker="extra-brace").replace(
        "console.log(\"extra-brace\");",
        "console.log(\"extra-brace\");\n}",
    )

    try:
        validate_aetherviz_html(
            bad_html,
            topic="熵增演示",
            strict=False,
        )
    except AetherVizHtmlValidationError as exc:
        message = str(exc)
    else:
        raise AssertionError("内联 JS 语法错误必须被服务端校验拦截")

    assert "内联脚本语法错误" in message
    assert "SyntaxError" in message or "Unexpected token" in message


def test_generate_phase_errors_when_repair_keeps_forbidden_dependency(monkeypatch) -> None:
    calls = []

    def fake_llm_stream(prompt: str, system_prompt: str, max_tokens: int = 0, temperature: float = 0.3, enable_thinking: bool = False):
        calls.append((prompt, system_prompt, max_tokens, temperature, enable_thinking))
        yield """<!DOCTYPE html>
<html>
<body>
<h1>熵增演示</h1>
<script src="https://cdn.staticfile.net/three.js/r134/three.min.js"></script>
<script>
const scene = new THREE.Scene();
const renderer = new THREE.WebGLRenderer();
function animationLoop() { requestAnimationFrame(animationLoop); }
animationLoop();
</script>
</body>
</html>"""

    monkeypatch.setattr(react_module, "call_llm_stream", fake_llm_stream)

    response = client.post(
        "/generate-aetherviz-spec",
        json={"topic": "熵增演示", "phase": "generate", "approved_plan": sample_approved_plan()},
    )

    events = parse_sse_events(response)
    assert events[-1][0] == "error"
    assert len(calls) == 2
    assert all(call[2] == react_module.HTML_OUTPUT_MAX_TOKENS for call in calls)
    assert all(call[4] is True for call in calls)
    assert events[-1][1]["stage"] in {"validation_failed", "html_generation_failed"}
    assert "确定性 HTML" not in events[-1][1]["message"]


def test_default_primary_color_is_22d3ee() -> None:
    assert DEFAULT_PRIMARY_COLOR == "#22D3EE"


def test_extract_color_from_topic_hex() -> None:
    color = extract_color_from_topic("带#FF5500颜色的主题")
    assert color == "#FF5500"


def test_extract_color_from_topic_chinese_name() -> None:
    color = extract_color_from_topic("蓝色主题下的力学")
    assert color == "#3B82F6"


def test_extract_color_from_topic_no_color() -> None:
    color = extract_color_from_topic("光的折射")
    assert color == "#22D3EE"


def test_detect_subject_branches() -> None:
    from aetherviz_service.aetherviz.fallback_planner import detect_subject
    assert detect_subject("二次函数的几何图像") == "math"
    assert detect_subject("简谐运动的受力分析") == "physics"
    assert detect_subject("分子碰撞反应") == "chemistry"
    assert detect_subject("光合作用与呼吸作用") == "biology"
    assert detect_subject("大气压带和风带的运动") == "geography"
    assert detect_subject("古文琵琶行人物关系") == "chinese"
    assert detect_subject("英语语法时态演变") == "english"


def test_detect_subject_general_fallback() -> None:
    from aetherviz_service.aetherviz.fallback_planner import detect_subject
    assert detect_subject("未知的神秘主题") == "general"


def test_build_planning_prompt_contains_subject_guide() -> None:
    from aetherviz_service.aetherviz.fallback_planner import build_planning_prompt
    sys_prompt, user_prompt = build_planning_prompt("二次函数", "#22D3EE")
    assert "资深互动教学课件规划师" in sys_prompt
    assert "AetherViz" not in sys_prompt
    assert "二次函数" in user_prompt
    assert "服务端学科识别：math" in user_prompt
    assert "推荐互动类型：simulation" in user_prompt
    assert "推荐渲染栈：svg" in user_prompt
    assert "推荐动画运行时：gsap" in user_prompt
    assert "stage_layout" in user_prompt
    assert "interactive_spec" in sys_prompt
    assert "teaching_flow" in sys_prompt
    assert "#22D3EE" in user_prompt
    assert "输出 JSON 示例" not in sys_prompt
    assert "平行四边形面积互动动画" not in sys_prompt
    assert "剪拼动画" not in sys_prompt


def test_generation_prompt_requires_visible_scene_list() -> None:
    from aetherviz_service.aetherviz.prompts import (
        EDIT_HTML_SYSTEM_PROMPT,
        INTERACTIVE_HTML_SYSTEM_PROMPT,
        REPAIR_SYSTEM_PROMPT,
        build_interactive_generation_prompt,
    )

    plan = sample_approved_plan("几何定理")
    prompt = build_interactive_generation_prompt("几何定理", plan)

    assert "single-page interactive" in INTERACTIVE_HTML_SYSTEM_PROMPT
    assert "active" in INTERACTIVE_HTML_SYSTEM_PROMPT
    assert "aria-current=\"step\"" in INTERACTIVE_HTML_SYSTEM_PROMPT
    assert "36000 字符以内" in INTERACTIVE_HTML_SYSTEM_PROMPT
    assert "40000 字符" in INTERACTIVE_HTML_SYSTEM_PROMPT
    assert "36000 字符以内" in REPAIR_SYSTEM_PROMPT
    assert "40000 字符" in REPAIR_SYSTEM_PROMPT
    assert "36000 字符以内" in EDIT_HTML_SYSTEM_PROMPT
    assert "40000 字符" in EDIT_HTML_SYSTEM_PROMPT
    assert "覆盖 teaching_flow 条目" in prompt
    assert "当前步骤用 active/current 状态同步标注" in prompt


def test_default_math_plan_uses_generic_fallback_without_topic_specific_overrides() -> None:
    from aetherviz_service.aetherviz.fallback_planner import normalize_plan

    plan = normalize_plan({}, "几何定理")

    assert plan["interactive_type"] == "simulation"
    spec = plan["interactive_spec"]
    assert spec["concept"] == "几何定理"
    assert [item["name"] for item in spec["variables"]] == ["parameter"]
    assert spec["presets"] == [{"id": "default", "label": "默认状态", "values": {"parameter": 5}}]
    assert plan["scene_outline"]["widgetType"] == "simulation"
    assert plan["design_brief"]["stage_objects"]
    assert {action["type"] for action in plan["widget_actions"]} == {
        "widget_setState",
        "widget_highlight",
        "widget_annotation",
        "widget_reveal",
    }


def test_fallback_planner_selects_interactive_types() -> None:
    from aetherviz_service.aetherviz.fallback_planner import detect_subject, select_interactive_type

    assert select_interactive_type("牛顿第二定律运动实验", detect_subject("牛顿第二定律运动实验")) == "simulation"
    assert select_interactive_type("化学反应速率", detect_subject("化学反应速率")) == "simulation"
    assert select_interactive_type("阅读结构分析", detect_subject("阅读结构分析")) == "diagram"
    assert select_interactive_type("排序闯关练习", detect_subject("排序闯关练习")) == "game"


def test_planning_normalization_keeps_new_plan_shape() -> None:
    from aetherviz_service.aetherviz.fallback_planner import normalize_plan

    plan = normalize_plan(
        {
            "subject": "physics",
            "interactive_type": "simulation",
            "runtime": {"render_stack": "svg_canvas", "animation_runtime": "native", "external_libraries": []},
            "title": "力学过程互动动画",
            "goal": "观察力学过程的关键变化。",
            "stage_layout": "顶部目标导航，中间大舞台展示运动轨迹，底部控制速度和作用力。",
            "interactive_spec": {
                "concept": "力学过程",
                "description": "调节作用力观察运动变化。",
                "variables": [{"name": "force", "label": "作用力", "min": 1, "max": 10, "default": 5, "step": 1}],
                "observations": ["观察运动轨迹变化"],
            },
            "teaching_flow": [
                {"id": "observe", "label": "展示结构", "focus": "物体与受力箭头出现", "caption": "先观察受力结构。"},
                {"id": "play", "label": "播放过程", "focus": "运动轨迹连续绘制", "caption": "再观察轨迹。"},
                {"id": "compare", "label": "拖动变量", "focus": "对比不同力的结果", "caption": "最后比较结果。"},
            ],
            "controls": [{"id": "force-slider", "label": "作用力", "type": "slider"}],
            "formulas": ["F=ma"],
        },
        "物理轻量化力学演示",
    )

    assert plan["page_type"] == "interactive"
    assert plan["interactive_type"] == "simulation"
    assert plan["subject"] == "physics"
    assert plan["runtime"]["render_stack"] == "svg_canvas"
    assert plan["runtime"]["animation_runtime"] == "native"
    assert plan["title"] == "力学过程互动动画"
    assert plan["stage_layout"].startswith("顶部目标导航")
    assert plan["interactive_spec"]["variables"][0]["name"] == "force"
    assert len(plan["teaching_flow"]) >= 3
    assert plan["controls"][0]["id"] == "force-slider"
    assert plan["formulas"] == ["F=ma"]


def test_planning_parse_valid() -> None:
    from aetherviz_service.aetherviz.fallback_planner import parse_planning_result
    raw = json.dumps({
        "title": "测试动画",
        "goal": "通过按钮点击切换步骤",
        "interactive_type": "diagram",
        "runtime": {"render_stack": "dom_svg", "animation_runtime": "native"},
        "stage_layout": "顶部目标导航，中间流程舞台，底部按钮控制。",
        "interactive_spec": {"nodes": [{"id": "a", "label": "A"}], "edges": [], "reveal_order": ["a"]},
        "teaching_flow": [{"id": "step", "label": "目标一", "focus": "按钮切换", "caption": "观察切换。"}],
        "controls": [{"id": "step-button", "label": "步骤", "type": "button"}],
        "formulas": ["公式1"],
    })
    res = parse_planning_result(raw, "测试")
    assert res["title"] == "测试动画"
    assert res["goal"] == "通过按钮点击切换步骤"
    assert res["runtime"]["render_stack"] == "dom_svg"
    assert res["stage_layout"].startswith("顶部目标导航")
    assert res["interactive_type"] == "diagram"
    assert res["teaching_flow"][0]["label"] == "目标一"
    assert res["controls"][0]["id"] == "step-button"
    assert res["formulas"] == ["公式1"]


def test_planning_parse_plain_code_fence() -> None:
    from aetherviz_service.aetherviz.fallback_planner import parse_planning_result
    raw = """```
{
  "title": "测试动画",
  "goal": "通过选择题即时反馈",
  "interactive_type": "game",
  "interactive_spec": {"challenge": "完成反馈挑战", "success_condition": "答对", "feedback_rules": ["即时反馈"]},
  "teaching_flow": [{"id": "goal", "label": "目标一", "focus": "选择反馈", "caption": "完成选择。"}],
  "controls": [{"id": "quiz-button", "label": "反馈", "type": "button"}],
  "formulas": ["公式1"]
}
```"""
    res = parse_planning_result(raw, "测试")
    assert res["title"] == "测试动画"
    assert res["goal"] == "通过选择题即时反馈"
    assert res["interactive_type"] == "game"
    assert res["teaching_flow"][0]["label"] == "目标一"
    assert res["controls"][0]["id"] == "quiz-button"
    assert res["formulas"] == ["公式1"]


def test_planning_parse_invalid_returns_default() -> None:
    from aetherviz_service.aetherviz.fallback_planner import parse_planning_result
    res = parse_planning_result("bad json data", "测试主题")
    assert len(res["teaching_flow"]) >= 3
    assert res["interactive_spec"]
    assert res["runtime"]["render_stack"] in ("svg", "svg_canvas", "canvas_svg", "dom_svg")
    assert res["runtime"]["animation_runtime"] == "gsap"
    assert "https://cdn.jsdelivr.net/npm/gsap@3/dist/gsap.min.js" in res["runtime"]["external_libraries"]
    assert "测试主题" in res["title"]
    assert res["interactive_type"] in ("simulation", "diagram", "game")


def test_fallback_planning_failure_returns_default_plan(monkeypatch) -> None:
    calls = []

    def fake_llm_stream(prompt: str, system_prompt: str, max_tokens: int = 0, temperature: float = 0.3, enable_thinking: bool = False):
        calls.append((prompt, system_prompt, max_tokens, temperature, enable_thinking))
        raise RuntimeError("planning failed")

    monkeypatch.setattr(react_module, "call_planning_llm_stream", fake_llm_stream)

    response = client.post("/generate-aetherviz-spec", json={"topic": "熵增演示"})

    events = parse_sse_events(response)
    assert events[-1][0] == "plan_ready"
    plan = events[-1][1]["plan"]
    assert len(calls) == 1
    assert plan["subject"] == "general"
    assert "熵增演示" in plan["title"]


def test_parse_interactive_html_success() -> None:
    from aetherviz_service.aetherviz.fallback_validator import parse_interactive_html
    raw = """```html
<!DOCTYPE html>
<html>
<head><title>test</title></head>
<body>
<p>这是一个测试页面，它的长度要达到至少五百个字符以通过检验，所以我们需要在这里多写一点测试文字。这非常有利于提高测试的覆盖率和确保质量门能够稳定工作。
这段文字虽然没有任何实在意义，但它为我们的解析器提供了一个很好的校验样本。
好的，差不多够长了。
</p>
</body>
</html>
```"""
    res = parse_interactive_html(raw)
    assert res.startswith("<!DOCTYPE html>")
    assert "test" in res


def test_sanitize_aetherviz_html_strips_ai_attribution() -> None:
    from aetherviz_service.aetherviz.validator import sanitize_aetherviz_html

    html = sanitize_aetherviz_html("<!DOCTYPE html><html><body><p>由 宾果AI 为你生成❤️</p></body></html>")

    assert "由 宾果AI 为你生成" not in html
    assert "<p></p>" in html


def test_parse_interactive_html_rejects_truncated_script() -> None:
    from aetherviz_service.aetherviz.fallback_validator import parse_interactive_html
    # 模拟截断在 script 内的破损 HTML
    truncated_raw = """<!DOCTYPE html>
<html>
<head><title>test</title></head>
<body>
  <div>测试截断</div>
  <script>
    function update(val) {
      console.log("hello");
      if (val > 0) {
        console.log(val);
        // 这里被无情截断，没有写完且没有闭合大括号，也缺少了结束的 script 和 body html 标签"""

    try:
        parse_interactive_html(truncated_raw)
    except Exception as exc:
        message = str(exc)
    else:
        raise AssertionError("截断在 <script> 内的 HTML 不应自动补齐 JS")

    assert "script" in message.lower()
    assert "截断" in message


def test_generate_phase_errors_when_repair_output_is_invalid(monkeypatch) -> None:
    calls = []

    def fake_llm_stream(prompt: str, system_prompt: str, max_tokens: int = 0, temperature: float = 0.3, enable_thinking: bool = False):
        calls.append((prompt, system_prompt, max_tokens, temperature, enable_thinking))
        yield """<html>
<head><title>破损HTML</title></head>
<body>缺少DOCTYPE和主体，也不够长。</body>
</html>"""

    monkeypatch.setattr(react_module, "call_llm_stream", fake_llm_stream)

    response = client.post(
        "/generate-aetherviz-spec",
        json={"topic": "熵增演示", "phase": "generate", "approved_plan": sample_approved_plan()},
    )

    events = parse_sse_events(response)
    assert events[-1][0] == "error"
    assert len(calls) == 2
    assert all(call[2] == react_module.HTML_OUTPUT_MAX_TOKENS for call in calls)
    assert all(call[4] is True for call in calls)
    assert events[-1][1]["stage"] in {"validation_failed", "html_generation_failed"}
    assert any(data.get("stage") == "repairing" for event, data in events if event == "progress")


def test_generate_phase_repairs_invalid_first_output(monkeypatch) -> None:
    calls = []

    def fake_llm_stream(prompt: str, system_prompt: str, max_tokens: int = 0, temperature: float = 0.3, enable_thinking: bool = False):
        calls.append((prompt, system_prompt, max_tokens, temperature, enable_thinking))
        if len(calls) == 1:
            yield "<html><body>破损</body></html>"
            return
        yield sample_svg_html(marker="repaired")

    monkeypatch.setattr(react_module, "call_llm_stream", fake_llm_stream)

    response = client.post(
        "/generate-aetherviz-spec",
        json={"topic": "熵增演示", "phase": "generate", "approved_plan": sample_approved_plan()},
    )

    events = parse_sse_events(response)
    assert "progress" in [event for event, _ in events]
    assert any(data.get("stage") == "repairing" for event, data in events if event == "progress")
    assert events[-1][0] == "done"
    assert len(calls) == 2
    assert all(call[2] == react_module.HTML_OUTPUT_MAX_TOKENS for call in calls)
    assert all(call[4] is True for call in calls)
    assert events[-1][1]["metadata"]["attempts"] == 2
    assert events[-1][1]["metadata"]["repaired"] is True
    assert "repaired" in events[-1][1]["html"]


def test_generate_phase_repairs_oversized_html_output(monkeypatch) -> None:
    calls = []

    def fake_llm_stream(prompt: str, system_prompt: str, max_tokens: int = 0, temperature: float = 0.3, enable_thinking: bool = False):
        calls.append((prompt, system_prompt, max_tokens, temperature, enable_thinking))
        if len(calls) == 1:
            yield oversized_sample_html(marker="too-long")
            return
        yield sample_svg_html(marker="compressed")

    monkeypatch.setattr(react_module, "call_llm_stream", fake_llm_stream)

    response = client.post(
        "/generate-aetherviz-spec",
        json={"topic": "熵增演示", "phase": "generate", "approved_plan": sample_approved_plan()},
    )

    events = parse_sse_events(response)
    repair_events = [data for event, data in events if event == "progress" and data.get("stage") == "repairing"]
    assert events[-1][0] == "done"
    assert len(calls) == 2
    assert repair_events
    assert "超过上线限制" in repair_events[0]["detail"]
    assert "40000" in calls[1][0]
    assert events[-1][1]["metadata"]["repaired"] is True
    assert "compressed" in events[-1][1]["html"]


def test_basic_html_validation_rejects_oversized_output() -> None:
    from aetherviz_service.aetherviz.constants import HTML_OUTPUT_HARD_LIMIT_CHARS
    from aetherviz_service.aetherviz.validator import AetherVizHtmlValidationError, validate_basic_aetherviz_html

    html = oversized_sample_html()
    assert len(html) > HTML_OUTPUT_HARD_LIMIT_CHARS

    with pytest.raises(AetherVizHtmlValidationError, match="超过上线限制"):
        validate_basic_aetherviz_html(html, topic="熵增演示")


def test_revise_phase_returns_new_plan(monkeypatch) -> None:
    calls = []

    def fake_llm_stream(prompt: str, system_prompt: str, max_tokens: int = 0, temperature: float = 0.3, enable_thinking: bool = False):
        calls.append((prompt, system_prompt, max_tokens, temperature, enable_thinking))
        yield json.dumps(
            {
                "page_type": "interactive",
                "interactive_type": "simulation",
                "subject": "general",
                "title": "慢速熵增互动课件",
                "goal": "通过更慢的参数变化观察熵增过程。",
                "stage_layout": "顶部目标，中间粒子舞台，底部速度滑块和结论。",
                "interactive_spec": {
                    "concept": "熵增",
                    "description": "调慢速度观察粒子扩散。",
                    "variables": [{"name": "speed", "label": "速度", "min": 0.2, "max": 1, "default": 0.5, "step": 0.1}],
                    "observations": ["观察慢速扩散。"],
                },
                "teaching_flow": [
                    {"id": "observe", "label": "慢速观察", "focus": "粒子扩散速度降低", "caption": "放慢速度观察每一步变化。"}
                ],
                "controls": [{"id": "speed-slider", "label": "速度", "type": "slider", "bind": "speed"}],
                "runtime": {"render_stack": "dom_svg", "animation_runtime": "native", "external_libraries": []},
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(react_module, "call_planning_llm_stream", fake_llm_stream)

    response = client.post(
        "/generate-aetherviz-spec",
        json={
            "topic": "熵增演示",
            "phase": "revise",
            "instruction": "把动画速度调慢",
        },
    )

    events = parse_sse_events(response)
    assert events[-1][0] == "plan_ready"
    assert len(calls) == 1
    prompt, system_prompt, max_tokens, temperature, enable_thinking = calls[0]
    assert "把动画速度调慢" in prompt
    assert "不修改旧 HTML" in prompt
    assert "before-revise" not in prompt
    assert "interactive_spec" in system_prompt
    assert max_tokens == react_module.PLANNING_MAX_TOKENS
    assert temperature == 0.25
    assert enable_thinking is True
    assert events[-1][1]["phase"] == "revise"
    assert events[-1][1]["plan"]["title"] == "慢速熵增互动课件"
    assert "html" not in events[-1][1]


def test_revise_phase_falls_back_to_default_plan_when_planning_fails(monkeypatch) -> None:
    calls = []

    def fake_llm_stream(prompt: str, system_prompt: str, max_tokens: int = 0, temperature: float = 0.3, enable_thinking: bool = False):
        calls.append((prompt, system_prompt, max_tokens, temperature, enable_thinking))
        raise RuntimeError("planner down")

    monkeypatch.setattr(react_module, "call_planning_llm_stream", fake_llm_stream)

    response = client.post(
        "/generate-aetherviz-spec",
        json={
            "topic": "熵增演示",
            "phase": "revise",
            "instruction": "把动画速度调慢",
        },
    )

    events = parse_sse_events(response)
    assert events[-1][0] == "plan_ready"
    assert len(calls) == 1
    assert any("兜底计划" in data.get("message", "") for event, data in events if event == "plan_delta")
    assert events[-1][1]["plan"]["page_type"] == "interactive"
    assert events[-1][1]["plan"]["interactive_type"] in ("simulation", "diagram", "game")


def test_revise_phase_requires_instruction_only() -> None:
    without_html = client.post(
        "/generate-aetherviz-spec",
        json={"topic": "熵增演示", "phase": "revise", "instruction": "改慢一点"},
    )
    assert without_html.status_code == 200

    missing_instruction = client.post(
        "/generate-aetherviz-spec",
        json={"topic": "熵增演示", "phase": "revise"},
    )
    assert missing_instruction.status_code == 400
    assert missing_instruction.json()["detail"] == "instruction 不能为空"


def test_edit_phase_uses_current_html_as_context_and_returns_new_html(monkeypatch) -> None:
    calls = []

    def fake_llm_stream(prompt: str, system_prompt: str, max_tokens: int = 0, temperature: float = 0.3, enable_thinking: bool = False):
        calls.append((prompt, system_prompt, max_tokens, temperature, enable_thinking))
        assert "当前 HTML 文件" in prompt
        assert "把标题改成慢速演示" in prompt
        assert "before-edit" in prompt
        yield sample_svg_html(topic="慢速熵增演示", marker="after-edit")

    monkeypatch.setattr(react_module, "call_llm_stream", fake_llm_stream)

    response = client.post(
        "/generate-aetherviz-spec",
        json={
            "topic": "熵增演示",
            "phase": "edit",
            "instruction": "把标题改成慢速演示",
            "current_html": sample_svg_html(marker="before-edit"),
            "context": {"selected_file": {"id": "html-1", "title": "原始 HTML"}},
        },
    )

    events = parse_sse_events(response)
    assert events[-1][0] == "done"
    assert len(calls) == 1
    assert calls[0][2] == react_module.HTML_OUTPUT_MAX_TOKENS
    assert calls[0][4] is True
    assert events[-1][1]["phase"] == "edit"
    assert events[-1][1]["metadata"]["source"] == "llm_html_edit"
    assert "after-edit" in events[-1][1]["html"]


def test_edit_phase_requires_current_html() -> None:
    response = client.post(
        "/generate-aetherviz-spec",
        json={"topic": "熵增演示", "phase": "edit", "instruction": "改标题"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "current_html 不能为空"


def test_generate_phase_errors_for_inline_script_syntax_error_after_repair(monkeypatch) -> None:
    calls = []

    def fake_llm_stream(prompt: str, system_prompt: str, max_tokens: int = 0, temperature: float = 0.3, enable_thinking: bool = False):
        calls.append((prompt, system_prompt, max_tokens, temperature, enable_thinking))
        yield sample_svg_html(marker="broken-js").replace(
            "console.log(\"broken-js\");",
            "console.log(\"broken-js\");\n}",
        )

    monkeypatch.setattr(react_module, "call_llm_stream", fake_llm_stream)

    response = client.post(
        "/generate-aetherviz-spec",
        json={"topic": "熵增演示", "phase": "generate", "approved_plan": sample_approved_plan()},
    )

    events = parse_sse_events(response)
    assert events[-1][0] == "error"
    assert events[-1][1]["stage"] in {"validation_failed", "html_generation_failed"}
    assert len(calls) == 2
    assert all(call[4] is True for call in calls)


def test_strip_code_fences_does_not_break_internal_template_literals() -> None:
    from aetherviz_service.llm_service import strip_code_fences

    # 有最外围栏，内部含反引号
    text = """```html
    <script>
    const a = `hello ${name}`;
    const b = ```
    code block
    ```;
    </script>
    ```"""
    result = strip_code_fences(text)
    assert result.startswith("<script>")
    assert "const b = ```" in result
    assert result.endswith("</script>")

    # 没有最外围栏，仅开头和结尾有
    text2 = """```html
    const a = `hello`;
    ```"""
    result2 = strip_code_fences(text2)
    assert result2 == "const a = `hello`;"


def test_balance_js_brackets_handles_various_truncations() -> None:
    from aetherviz_service.aetherviz.fallback_validator import _balance_js_brackets

    # Case 1: 截断在普通大括号内
    assert _balance_js_brackets("const a = () => {") == "}"
    
    # Case 2: 截断在反引号模板字符串内，且含有大括号字面量（大括号作为普通文本不需要被闭合）
    assert _balance_js_brackets("const a = `hello {") == "`"
    
    # Case 3: 截断在多行注释内
    assert _balance_js_brackets("/* text") == "*/"
    
    # Case 4: 截断在单引号/双引号内
    assert _balance_js_brackets("const s = 'hello") == "'"
    assert _balance_js_brackets('const s = "hello') == '"'
    
    # Case 5: 截断在模板字符串中的 JS 表达式插值内
    # const a = () => { const b = `hello ${val
    assert _balance_js_brackets("const a = () => { const b = `hello ${val") == "}`}"
    
    # Case 6: 截断在复杂的嵌套中
    # const a = () => { const b = `hello ${() => { return 'world';
    assert _balance_js_brackets("const a = () => { const b = `hello ${() => { return 'world';") == "}}`}"


def test_parse_interactive_html_rejects_smart_closing_inside_script() -> None:
    from aetherviz_service.aetherviz.fallback_validator import parse_interactive_html

    # 模拟一个没有 </html> 闭合标签，且 <script> 截断在大括号和反引号内的 HTML 课件
    raw_html = """<!DOCTYPE html>
<html>
<head>
  <title>截断测试</title>
</head>
<body>
  <script>
    const setup = () => {
      const msg = `hello {
"""
    try:
        parse_interactive_html(raw_html)
    except Exception as exc:
        message = str(exc)
    else:
        raise AssertionError("截断在 <script> 内时不应通过智能闭合返回 HTML")

    assert "script" in message.lower()
    assert "截断" in message
