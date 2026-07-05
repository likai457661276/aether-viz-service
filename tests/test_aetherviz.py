"""AI互动实验 static-hit and interactive HTML fallback tests."""

import base64
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import aetherviz_service.aetherviz.react as react_module
import aetherviz_service.aetherviz.static_html as static_html_module
from aetherviz_service.aetherviz.knowledge_points import KNOWLEDGE_POINTS, KnowledgePoint
from aetherviz_service.aetherviz.static_html import (
    DEFAULT_PRIMARY_COLOR,
    static_html_path_for_point,
)
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
window.AetherVizRuntime = {{ play, pause, reset, setSpeed, update, getState }};
window.__AETHERVIZ_RUNTIME_READY__ = true;
window.__AETHERVIZ_RUNTIME_ERROR__ = null;
animationLoop();
console.log("{marker}");
</script>
</body>
</html>"""


def sample_gsap_html(topic: str = "勾股定理") -> str:
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{topic}</title>
<style>
body {{ margin: 0; font-family: sans-serif; }}
#aetherviz-stage {{ width: min(960px, 94vw); min-height: 320px; margin: 0 auto; display: grid; place-items: center; }}
#aetherviz-stage svg {{ display: block; margin: auto; max-width: 100%; max-height: 100%; }}
.square {{ opacity: 0; transform-origin: center; }}
</style>
</head>
<body>
<h1>{topic}</h1>
<section class="learning-objectives">
  <h2>学习目标</h2>
  <ul>
    <li>认识直角三角形三边关系</li>
    <li>观察三个正方形面积变化</li>
    <li>验证 a² + b² = c²</li>
  </ul>
</section>
<section>
  <h2>核心公式</h2>
  <p>a² + b² = c²</p>
</section>
<main id="aetherviz-stage">
  <p id="animation-caption" class="animation-caption">当前步骤：观察 3-4-5 直角三角形。</p>
  <svg viewBox="0 0 360 220" preserveAspectRatio="xMidYMid meet" role="img" aria-label="{topic}互动图形">
    <g id="main-visual-group">
      <polygon id="main-shape" points="80,170 80,50 240,170" fill="#dbeafe" stroke="#2563eb"></polygon>
      <rect id="square-a" class="square" x="20" y="50" width="60" height="120" fill="#22D3EE"></rect>
      <rect id="square-b" class="square" x="80" y="170" width="160" height="30" fill="#FBBF24"></rect>
      <rect id="square-c" class="square" x="235" y="65" width="95" height="95" fill="#A78BFA"></rect>
      <text id="formula-a" x="130" y="30">3² + 4² = 5²</text>
    </g>
  </svg>
</main>
<div class="control-panel">
  <button id="play-animation">播放</button>
  <button id="pause-animation">暂停</button>
  <button id="reset-animation">重置</button>
  <label>速度 <input type="range" id="speed-control" min="0.5" max="2" step="0.5" value="1"></label>
  <label>进度 <input type="range" id="progress-slider" min="0" max="1" step="0.01" value="0"></label>
</div>
<script src="https://cdn.jsdelivr.net/npm/gsap@3.15.0/dist/gsap.min.js"></script>
<script>
const caption = document.getElementById('animation-caption');
const speed = document.getElementById('speed-control');
const progress = document.getElementById('progress-slider');
function syncRuntimeState() {{
  progress.value = String(tl.progress());
  if (tl.time() < 1) caption.textContent = '当前步骤：先观察 3-4-5 直角三角形。';
  else if (tl.time() < 2) caption.textContent = '当前步骤：两条直角边的正方形面积相加。';
  else caption.textContent = '当前步骤：斜边正方形面积与前两者相等。';
}}
const tl = gsap.timeline({{ paused: true, defaults: {{ ease: 'power2.inOut' }}, onUpdate: syncRuntimeState }});
tl.addLabel('scene_intro', 0)
  .to('#main-shape', {{ scale: 1.04, duration: 0.6 }}, 'scene_intro')
  .to('#square-a', {{ autoAlpha: 1, duration: 0.6 }}, 'scene_intro+=0.2')
  .addLabel('scene_legs', '>')
  .to('#square-b', {{ autoAlpha: 1, duration: 0.6 }}, 'scene_legs')
  .to('#formula-a', {{ fill: '#0EA5E9', duration: 0.4 }}, 'scene_legs')
  .addLabel('scene_hypotenuse', '>')
  .to('#square-c', {{ autoAlpha: 1, duration: 0.6 }}, 'scene_hypotenuse');
document.getElementById('play-animation').addEventListener('click', () => tl.restart());
document.getElementById('pause-animation').addEventListener('click', () => tl.pause());
document.getElementById('reset-animation').addEventListener('click', () => {{ tl.pause(0); syncRuntimeState(); }});
speed.addEventListener('input', () => tl.timeScale(Number(speed.value) || 1));
progress.addEventListener('input', () => tl.progress(Number(progress.value) || 0));
function play() {{ tl.play(); }}
function pause() {{ tl.pause(); }}
function reset() {{ tl.pause(0); syncRuntimeState(); }}
function setSpeed(value) {{ tl.timeScale(Number(value) || 1); }}
function update(value) {{ tl.progress(Number(value) || 0); syncRuntimeState(); }}
function getState() {{ return {{ progress: tl.progress(), time: tl.time(), duration: tl.duration(), speed: tl.timeScale() }}; }}
window.AetherVizRuntime = {{ play, pause, reset, setSpeed, update, getState }};
window.__AETHERVIZ_RUNTIME_READY__ = true;
window.__AETHERVIZ_RUNTIME_ERROR__ = null;
syncRuntimeState();
</script>
</body>
</html>"""


def test_generate_aetherviz_spec_returns_400_when_topic_empty() -> None:
    response = client.post("/generate-aetherviz-spec", json={"topic": "   "})

    assert response.status_code == 400
    assert response.json()["detail"] == "topic 不能为空"


def test_list_static_aetherviz_knowledge_points() -> None:
    response = client.get("/aetherviz-static-knowledge-points")

    assert response.status_code == 200
    data = response.json()
    static_points = [
        point
        for point in KNOWLEDGE_POINTS.values()
        if point.render_mode == "static-html" and point.static_html_slug
    ]
    assert data["success"] is True
    assert data["total"] == len(static_points)
    assert len(data["knowledge_points"]) == len(static_points)
    assert data["knowledge_points"] == sorted(
        data["knowledge_points"],
        key=lambda item: (item["subject"], item["knowledge_point_id"]),
    )

    newton = next(
        item
        for item in data["knowledge_points"]
        if item["knowledge_point_id"] == "physics/newton_second_law"
    )
    assert newton["title"] == "牛顿第二定律"
    assert newton["subject"] == "physics"
    assert newton["knowledge_domain"] == "mechanics"
    assert newton["grade"] == "高一"
    assert newton["render_mode"] == "static-html"
    assert newton["static_html_slug"] == "newton-second-law"
    assert newton["static_html_path"] == "physics/newton-second-law.html"
    assert "F=ma" in newton["keywords"]
    cover_bytes = base64.b64decode(newton["cover_image_base64"])
    assert cover_bytes.startswith(b"\xff\xd8\xff")


def test_get_static_aetherviz_html_by_knowledge_point_id() -> None:
    response = client.get(
        "/aetherviz-static-html",
        params={"knowledge_point_id": "physics/newton_second_law"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["knowledge_point_id"] == "physics/newton_second_law"
    assert data["title"] == "牛顿第二定律"
    assert data["subject"] == "physics"
    assert data["knowledge_domain"] == "mechanics"
    assert data["grade"] == "高一"
    assert data["render_mode"] == "static-html"
    assert data["static_html_slug"] == "newton-second-law"
    assert data["static_html_path"] == "physics/newton-second-law.html"
    assert data["primary_color"] == DEFAULT_PRIMARY_COLOR
    assert data["html"].startswith("<!DOCTYPE html>")
    assert "牛顿第二定律" in data["html"]
    assert "AI互动实验 runtime theme override" in data["html"]


def test_get_static_aetherviz_html_by_relative_path_returns_raw_html() -> None:
    response = client.get("/static-html/physics/newton-second-law.html")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.text.startswith("<!DOCTYPE html>")
    assert "牛顿第二定律" in response.text
    assert "AI互动实验 runtime theme override" in response.text


def test_get_static_aetherviz_html_by_relative_path_rejects_unsafe_path() -> None:
    response = client.get("/static-html/../README.md")

    assert response.status_code == 404


def test_static_html_relative_path_rejects_traversal() -> None:
    with pytest.raises(static_html_module.StaticAetherVizHtmlError):
        static_html_module.static_html_path_for_relative_path("../README.md")


def test_get_static_aetherviz_html_returns_404_when_unknown() -> None:
    response = client.get(
        "/aetherviz-static-html",
        params={"knowledge_point_id": "physics/unknown"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "静态知识点不存在"


def test_get_static_aetherviz_html_returns_500_when_file_missing(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(static_html_module, "HTML_ROOT", tmp_path)

    response = client.get(
        "/aetherviz-static-html",
        params={"knowledge_point_id": "physics/newton_second_law"},
    )

    assert response.status_code == 500
    assert "静态 HTML 文件不存在" in response.json()["detail"]


def test_all_registered_knowledge_points_have_cover_image() -> None:
    missing = [
        point.knowledge_point_id
        for point in KNOWLEDGE_POINTS.values()
        if point.render_mode == "static-html" and not point.cover_image_base64
    ]

    assert missing == []


def test_static_match_returns_html_without_llm(monkeypatch) -> None:
    def fail_llm(*args, **kwargs):
        raise AssertionError("static hit must not call LLM")

    monkeypatch.setattr(react_module, "call_llm_stream", fail_llm)

    response = client.post("/generate-aetherviz-spec", json={"topic": "牛顿第二定律"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = parse_sse_events(response)
    assert [event for event, _ in events] == ["start", "progress", "done"]
    assert events[1][1]["stage"] == "static_match"

    done_data = events[-1][1]
    html = done_data["html"]
    assert html.startswith("<!DOCTYPE html>")
    assert "牛顿第二定律" in html
    assert "AI互动实验 runtime theme override" in html
    assert done_data["metadata"]["source"] == "static_html"
    assert done_data["metadata"]["attempts"] == 0
    assert done_data["metadata"]["degraded"] is False
    assert done_data["metadata"]["knowledge_point_id"] == "physics/newton_second_law"
    assert done_data["metadata"]["grade"] == "高一"


def test_static_match_uses_default_theme_color() -> None:
    response = client.post(
        "/generate-aetherviz-spec",
        json={"topic": "牛顿第二定律"},
    )

    assert response.status_code == 200
    html = parse_sse_events(response)[-1][1]["html"]
    assert "AI互动实验 runtime theme override" in html
    assert f"--primary-gradient: linear-gradient(135deg, {DEFAULT_PRIMARY_COLOR}" in html


def test_static_match_supports_registered_non_physics_subject(monkeypatch, tmp_path: Path) -> None:
    def fail_llm(*args, **kwargs):
        raise AssertionError("registered static hit must not call LLM")

    chemistry_html_dir = tmp_path / "chemistry"
    chemistry_html_dir.mkdir()
    (chemistry_html_dir / "reaction-rate.html").write_text(
        """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>反应速率</title>
<style>:root { --theme-subject: #14B8A6; }</style>
</head>
<body><main>反应速率互动演示</main><script>window.ready=true;</script></body>
</html>""",
        encoding="utf-8",
    )
    point = KnowledgePoint(
        subject="chemistry",
        knowledge_domain="kinetics",
        knowledge_point_id="chemistry/reaction_rate",
        title="化学反应速率测试",
        keywords=("反应速率测试", "化学反应速率测试"),
        render_mode="static-html",
        static_html_slug="reaction-rate",
    )

    monkeypatch.setitem(KNOWLEDGE_POINTS, point.knowledge_point_id, point)
    monkeypatch.setattr(static_html_module, "HTML_ROOT", tmp_path)
    monkeypatch.setattr(react_module, "call_llm_stream", fail_llm)

    response = client.post("/generate-aetherviz-spec", json={"topic": "化学反应速率测试"})

    assert response.status_code == 200
    events = parse_sse_events(response)
    assert events[-1][0] == "done"
    done_data = events[-1][1]
    assert done_data["metadata"]["subject"] == "chemistry"
    assert done_data["metadata"]["knowledge_domain"] == "kinetics"
    assert done_data["metadata"]["knowledge_point_id"] == "chemistry/reaction_rate"
    assert "反应速率互动演示" in done_data["html"]
    assert "AI互动实验 runtime theme override" in done_data["html"]


def test_all_registered_knowledge_points_have_static_html() -> None:
    missing = [
        point.knowledge_point_id
        for point in KNOWLEDGE_POINTS.values()
        if not static_html_path_for_point(point).is_file()
    ]

    assert missing == []


def test_all_registered_knowledge_points_have_grade() -> None:
    missing = [
        point.knowledge_point_id
        for point in KNOWLEDGE_POINTS.values()
        if not point.grade
    ]

    assert missing == []


def test_all_static_html_files_are_registered() -> None:
    registered_files = {
        static_html_path_for_point(point).relative_to(static_html_module.HTML_ROOT)
        for point in KNOWLEDGE_POINTS.values()
    }
    html_files = {
        path.relative_to(static_html_module.HTML_ROOT)
        for path in static_html_module.HTML_ROOT.rglob("*.html")
    }

    assert sorted(html_files - registered_files) == []


def test_static_match_supports_builtin_math_and_chemistry_without_llm(monkeypatch) -> None:
    def fail_llm(*args, **kwargs):
        raise AssertionError("registered static hit must not call LLM")

    monkeypatch.setattr(react_module, "call_llm_stream", fail_llm)

    chemistry_response = client.post("/generate-aetherviz-spec", json={"topic": "酸碱中和反应"})

    assert chemistry_response.status_code == 200
    chemistry_done = parse_sse_events(chemistry_response)[-1][1]
    assert chemistry_done["metadata"]["subject"] == "chemistry"
    assert chemistry_done["metadata"]["knowledge_point_id"] == "chemistry/acid_base_neutralization"
    assert "酸碱中和反应" in chemistry_done["html"]

    chemistry_response2 = client.post("/generate-aetherviz-spec", json={"topic": "氧化还原反应"})
    assert chemistry_response2.status_code == 200
    chemistry_done2 = parse_sse_events(chemistry_response2)[-1][1]
    assert chemistry_done2["metadata"]["subject"] == "chemistry"
    assert chemistry_done2["metadata"]["knowledge_point_id"] == "chemistry/redox_reaction"
    assert "氧化还原反应" in chemistry_done2["html"]

    rate_response = client.post("/generate-aetherviz-spec", json={"topic": "化学反应速率"})
    assert rate_response.status_code == 200
    rate_done = parse_sse_events(rate_response)[-1][1]
    assert rate_done["metadata"]["subject"] == "chemistry"
    assert rate_done["metadata"]["knowledge_point_id"] == "chemistry/chemical_reaction_rate"
    assert "化学反应速率" in rate_done["html"]

    polygon_response = client.post("/generate-aetherviz-spec", json={"topic": "多边形的面积"})
    assert polygon_response.status_code == 200
    polygon_done = parse_sse_events(polygon_response)[-1][1]
    assert polygon_done["metadata"]["subject"] == "math"
    assert polygon_done["metadata"]["knowledge_point_id"] == "math/polygon_area"
    assert "多边形的面积" in polygon_done["html"]

    quadratic_function_response = client.post("/generate-aetherviz-spec", json={"topic": "高一二次函数"})
    assert quadratic_function_response.status_code == 200
    quadratic_function_done = parse_sse_events(quadratic_function_response)[-1][1]
    assert quadratic_function_done["metadata"]["subject"] == "math"
    assert quadratic_function_done["metadata"]["knowledge_point_id"] == "math/quadratic_function"
    assert quadratic_function_done["metadata"]["grade"] == "高一"
    assert "二次函数" in quadratic_function_done["html"]

    spatial_geom_response = client.post("/generate-aetherviz-spec", json={"topic": "空间几何"})
    assert spatial_geom_response.status_code == 200
    spatial_geom_done = parse_sse_events(spatial_geom_response)[-1][1]
    assert spatial_geom_done["metadata"]["subject"] == "math"
    assert spatial_geom_done["metadata"]["knowledge_point_id"] == "math/spatial_geometry"
    assert spatial_geom_done["metadata"]["grade"] == "高二"
    assert "空间几何" in spatial_geom_done["html"]

    protein_response = client.post("/generate-aetherviz-spec", json={"topic": "蛋白质的结构与功能"})
    assert protein_response.status_code == 200
    protein_done = parse_sse_events(protein_response)[-1][1]
    assert protein_done["metadata"]["subject"] == "biology"
    assert protein_done["metadata"]["knowledge_point_id"] == "biology/protein_structure_function"
    assert protein_done["metadata"]["grade"] == "高一"
    assert "蛋白质" in protein_done["html"]

    dna_response = client.post("/generate-aetherviz-spec", json={"topic": "DNA的分子结构"})
    assert dna_response.status_code == 200
    dna_done = parse_sse_events(dna_response)[-1][1]
    assert dna_done["metadata"]["subject"] == "biology"
    assert dna_done["metadata"]["knowledge_point_id"] == "biology/dna_structure"
    assert dna_done["metadata"]["grade"] == "高二"
    assert "DNA" in dna_done["html"]


def test_static_match_supports_builtin_chinese_without_llm(monkeypatch) -> None:
    def fail_llm(*args, **kwargs):
        raise AssertionError("registered static hit must not call LLM")

    monkeypatch.setattr(react_module, "call_llm_stream", fail_llm)

    response = client.post("/generate-aetherviz-spec", json={"topic": "灰雀"})

    assert response.status_code == 200
    events = parse_sse_events(response)
    assert events[-1][0] == "done"
    done_data = events[-1][1]
    assert done_data["metadata"]["subject"] == "chinese"
    assert done_data["metadata"]["knowledge_point_id"] == "chinese/huique"
    assert "灰雀" in done_data["html"]
    assert "AI互动实验 runtime theme override" in done_data["html"]


def test_static_html_missing_returns_sse_error(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(static_html_module, "HTML_ROOT", tmp_path)

    response = client.post("/generate-aetherviz-spec", json={"topic": "牛顿第二定律"})

    events = parse_sse_events(response)
    assert events[-1][0] == "error"
    assert events[-1][1]["stage"] == "static_html_missing"


def test_static_html_load_strips_ai_attribution(tmp_path: Path) -> None:
    html_path = tmp_path / "demo.html"
    html_path.write_text(
        "<!DOCTYPE html><html><head><style>body{}</style></head><body><footer>— 由 宾果AI 为你生成❤️</footer></body></html>",
        encoding="utf-8",
    )

    html = static_html_module.load_static_html_file(html_path, "#22D3EE")

    assert "由 宾果AI 为你生成" not in html
    assert "AI互动实验 runtime theme override" in html


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

    monkeypatch.setattr(react_module, "call_llm_stream", fake_llm_stream)

    response = client.post("/generate-aetherviz-spec", json={"topic": "熵增演示"})

    assert response.status_code == 200
    events = parse_sse_events(response)
    assert [event for event, _ in events][-1] == "plan_ready"
    assert "plan_delta" in [event for event, _ in events]
    plan = events[-1][1]["plan"]
    assert len(stream_calls) == 1
    assert stream_calls[0][2] == react_module.PLANNING_MAX_TOKENS
    assert stream_calls[0][4] is False
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
            "title": "勾股定理互动动画",
            "goal": "通过拖动直角三角形边长观察面积关系。",
            "stage_layout": "顶部目标导航，中间大几何舞台，底部控制条和公式结论。",
            "interactive_spec": {
                "concept": "勾股定理",
                "variables": [{"name": "leg", "label": "直角边", "min": 1, "max": 10, "default": 3, "step": 1}],
                "observations": ["观察边长变化和面积关系。"],
            },
            "teaching_flow": [{"id": "observe", "label": "显示直角三角形", "focus": "直角三角形居中", "caption": "观察三边。"}],
            "controls": [{"id": "leg-slider", "label": "直角边", "type": "slider"}],
            "formulas": ["a^2+b^2=c^2"],
            "runtime": {"render_stack": "svg", "animation_runtime": "native", "external_libraries": []},
            "primary_color": "#22D3EE",
        })
        yield LLMStreamChunk(kind="content", delta=raw)

    monkeypatch.setattr(react_module, "call_llm_stream", fake_llm_stream)

    response = client.post("/generate-aetherviz-spec", json={"topic": "勾股定理"})

    events = parse_sse_events(response)
    assert "thinking_delta" not in [event for event, _ in events]
    assert events[-1][0] == "plan_ready"
    assert events[-1][1]["plan"]["interactive_type"] == "simulation"
    assert len(calls) == 1
    assert calls[0][2] == react_module.PLANNING_MAX_TOKENS
    assert calls[0][4] is False


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
    assert done_data["metadata"]["degraded"] is True
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


def test_validation_accepts_gsap_timeline_contract() -> None:
    from aetherviz_service.aetherviz.validator import validate_aetherviz_html

    warnings = validate_aetherviz_html(
        sample_gsap_html(),
        topic="勾股定理",
        strict=True,
    )

    assert isinstance(warnings, list)


def test_validation_rejects_gsap_without_fixed_cdn() -> None:
    from aetherviz_service.aetherviz.validator import (
        AetherVizHtmlValidationError,
        validate_aetherviz_html,
    )

    bad_html = sample_gsap_html().replace(
        "https://cdn.jsdelivr.net/npm/gsap@3.15.0/dist/gsap.min.js",
        "https://cdn.jsdelivr.net/npm/gsap/dist/gsap.min.js",
    )

    with pytest.raises(AetherVizHtmlValidationError) as exc_info:
        validate_aetherviz_html(bad_html, topic="勾股定理", strict=True)

    assert "非白名单外部资源" in str(exc_info.value)


def test_validation_rejects_empty_gsap_timeline() -> None:
    from aetherviz_service.aetherviz.validator import (
        AetherVizHtmlValidationError,
        validate_aetherviz_html,
    )

    bad_html = sample_gsap_html().replace(".addLabel('scene_legs', '>')", ".addLabelRemoved('scene_legs', '>')")
    bad_html = bad_html.replace(".addLabel('scene_hypotenuse', '>')", ".addLabelRemoved('scene_hypotenuse', '>')")
    bad_html = bad_html.replace(".to('#square-b', { autoAlpha: 1, duration: 0.6 }, 'scene_legs')", ".call(() => syncRuntimeState())")
    bad_html = bad_html.replace(".to('#formula-a', { fill: '#0EA5E9', duration: 0.4 }, 'scene_legs')", ".call(() => syncRuntimeState())")

    with pytest.raises(AetherVizHtmlValidationError) as exc_info:
        validate_aetherviz_html(bad_html, topic="勾股定理", strict=True)

    message = str(exc_info.value)
    assert "GSAP timeline 至少需要 3 个 addLabel" in message or "GSAP timeline 至少需要 3 个真实" in message


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
    assert "missing_caption_state_update" in message
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


def test_generate_phase_rejects_three_output_in_svg_mode(monkeypatch) -> None:
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
    assert events[-1][1]["stage"] == "validation_failed"
    assert "非白名单外部资源" in events[-1][1]["detail"]
    assert "three.js" in events[-1][1]["detail"]


def test_default_primary_color_is_22d3ee() -> None:
    assert DEFAULT_PRIMARY_COLOR == "#22D3EE"


def test_extract_color_from_topic_hex() -> None:
    color = static_html_module.extract_color_from_topic("带#FF5500颜色的主题")
    assert color == "#FF5500"


def test_extract_color_from_topic_chinese_name() -> None:
    color = static_html_module.extract_color_from_topic("蓝色主题下的力学")
    assert color == "#3B82F6"


def test_extract_color_from_topic_no_color() -> None:
    color = static_html_module.extract_color_from_topic("光的折射")
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
    assert "推荐动画运行时：native" in user_prompt
    assert "stage_layout" in user_prompt
    assert "interactive_spec" in sys_prompt
    assert "teaching_flow" in sys_prompt
    assert "#22D3EE" in user_prompt
    assert "输出 JSON 示例" not in sys_prompt
    assert "平行四边形面积互动动画" not in sys_prompt
    assert "剪拼动画" not in sys_prompt


def test_generation_prompt_requires_visible_scene_list() -> None:
    from aetherviz_service.aetherviz.prompts import INTERACTIVE_HTML_SYSTEM_PROMPT, build_interactive_generation_prompt

    plan = sample_approved_plan("勾股定理")
    prompt = build_interactive_generation_prompt("勾股定理", plan)

    assert "single-page interactive" in INTERACTIVE_HTML_SYSTEM_PROMPT
    assert "active" in INTERACTIVE_HTML_SYSTEM_PROMPT
    assert "aria-current=\"step\"" in INTERACTIVE_HTML_SYSTEM_PROMPT
    assert "覆盖 teaching_flow 条目" in prompt
    assert "当前步骤用 active/current 状态同步标注" in prompt


def test_default_math_simulation_spec_is_not_pythagorean_hardcoded() -> None:
    from aetherviz_service.aetherviz.fallback_planner import normalize_plan

    plan = normalize_plan({}, "勾股定理")

    assert plan["interactive_type"] == "simulation"
    spec = plan["interactive_spec"]
    assert spec["concept"] == "勾股定理"
    assert "3-4-5" not in json.dumps(spec, ensure_ascii=False)


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
    assert plan["runtime"]["animation_runtime"] in ("native", "gsap_timeline")
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
    assert res["runtime"]["animation_runtime"] in ("native", "gsap_timeline")
    assert "测试主题" in res["title"]
    assert res["interactive_type"] in ("simulation", "diagram", "game")


def test_fallback_planning_failure_returns_default_plan(monkeypatch) -> None:
    calls = []

    def fake_llm_stream(prompt: str, system_prompt: str, max_tokens: int = 0, temperature: float = 0.3, enable_thinking: bool = False):
        calls.append((prompt, system_prompt, max_tokens, temperature, enable_thinking))
        raise RuntimeError("planning failed")

    monkeypatch.setattr(react_module, "call_llm_stream", fake_llm_stream)

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


def test_generate_phase_returns_error_for_invalid_svg_output(monkeypatch) -> None:
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
    assert events[-1][1]["stage"] == "fallback_failed"
    assert len(calls) == 2
    assert all(call[2] == react_module.HTML_OUTPUT_MAX_TOKENS for call in calls)
    assert all(call[4] is True for call in calls)
    assert "首次失败" in events[-1][1]["detail"]
    assert "修复失败" in events[-1][1]["detail"]


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


def test_revise_phase_returns_new_plan_without_current_html(monkeypatch) -> None:
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

    monkeypatch.setattr(react_module, "call_llm_stream", fake_llm_stream)

    response = client.post(
        "/generate-aetherviz-spec",
        json={
            "topic": "熵增演示",
            "phase": "revise",
            "current_html": sample_svg_html(marker="before-revise"),
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
    assert enable_thinking is False
    assert events[-1][1]["phase"] == "revise"
    assert events[-1][1]["plan"]["title"] == "慢速熵增互动课件"
    assert "html" not in events[-1][1]


def test_revise_phase_falls_back_to_default_plan_when_planning_fails(monkeypatch) -> None:
    calls = []

    def fake_llm_stream(prompt: str, system_prompt: str, max_tokens: int = 0, temperature: float = 0.3, enable_thinking: bool = False):
        calls.append((prompt, system_prompt, max_tokens, temperature, enable_thinking))
        raise RuntimeError("planner down")

    monkeypatch.setattr(react_module, "call_llm_stream", fake_llm_stream)

    response = client.post(
        "/generate-aetherviz-spec",
        json={
            "topic": "熵增演示",
            "phase": "revise",
            "current_html": sample_svg_html(marker="before-revise"),
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


def test_generate_phase_returns_error_for_inline_script_syntax_error(monkeypatch) -> None:
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
    error_data = events[-1][1]
    assert error_data["stage"] == "validation_failed"
    assert "内联脚本语法错误" in error_data["detail"]
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
