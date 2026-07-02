"""AI互动实验 static-hit and interactive HTML fallback tests."""

import base64
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import aetherviz_service.aetherviz.react as react_module
import aetherviz_service.aetherviz.static_html as static_html_module
from aetherviz_service.aetherviz.knowledge_points import KNOWLEDGE_POINTS, KnowledgePoint
from aetherviz_service.aetherviz.matcher import match_topic_to_knowledge_point
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
        "subject": "general",
        "mode": "generic_svg",
        "title": f"{topic}互动动画",
        "goal": f"用稳定 SVG 动画解释“{topic}”的核心过程。",
        "visual_steps": ["生活类比", "观察现象", "播放过程", "交互验证"],
        "controls": [
            {"id": "progress-slider", "label": "过程进度", "type": "slider"},
            {"id": "speed-control", "label": "速度", "type": "speed"},
            {"id": "reset-button", "label": "重置", "type": "button"},
        ],
        "formulas": [],
        "validation_points": ["使用 HTML + CSS + SVG", "控制按钮均绑定事件", "移动端不溢出"],
        "primary_color": "#22D3EE",
    }


def sample_svg_html(topic: str = "熵增演示", marker: str = "ready") -> str:
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{topic}</title>
<link rel="stylesheet" href="https://cdn.staticfile.net/KaTeX/0.16.9/katex.min.css">
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
  <svg viewBox="0 0 320 180" role="img" aria-label="{topic}互动图形">
    <path d="M20 140 C90 40 190 40 300 140" stroke="#22D3EE" fill="none"></path>
    <circle cx="160" cy="80" r="10" fill="#FBBF24"></circle>
  </svg>
</main>
<div class="control-panel">
  <button id="play-animation">播放</button>
  <input type="range" id="param">
</div>
<script src="https://cdn.staticfile.net/KaTeX/0.16.9/katex.min.js"></script>
<script>
const state = {{ mode: 'playing', progress: 0 }};
function updateVisualization() {{ state.progress = (state.progress + 1) % 100; }}
function animationLoop() {{
  requestAnimationFrame(animationLoop);
  updateVisualization();
}}
window.addEventListener('resize', () => updateVisualization());
document.getElementById('play-animation').addEventListener('click', () => updateVisualization());
animationLoop();
console.log("{marker}");
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


def test_pythagorean_is_not_registered_static_knowledge_point() -> None:
    assert "math/pythagorean" not in KNOWLEDGE_POINTS
    assert match_topic_to_knowledge_point("勾股定理") is None


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


def test_unmatched_topic_plan_phase_streams_plan_without_html_generation(monkeypatch) -> None:
    stream_calls = []

    def fake_llm_stream(prompt: str, system_prompt: str, max_tokens: int = 0, temperature: float = 0.3):
        stream_calls.append((prompt, system_prompt, max_tokens, temperature))
        raw = json.dumps({
            "subject": "general",
            "mode": "generic_svg",
            "title": "熵增演示互动动画",
            "goal": "用稳定 SVG 动画解释熵增演示。",
            "visual_steps": ["生活类比", "观察现象", "播放过程"],
            "controls": [{"id": "progress-slider", "label": "进度", "type": "slider"}],
            "formulas": [],
            "validation_points": ["使用 HTML + CSS + SVG"],
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
    assert plan["subject"] == "general"
    assert plan["mode"] == "generic_svg"
    assert plan["controls"][0]["type"] == "slider"
    assert "html" not in events[-1][1]


def test_plan_phase_streams_reasoning_delta_and_math_css_mode(monkeypatch) -> None:
    def fake_llm_stream(prompt: str, system_prompt: str, max_tokens: int = 0, temperature: float = 0.3):
        yield LLMStreamChunk(kind="reasoning", delta="先判断这是数学几何主题。")
        raw = json.dumps({
            "subject": "math",
            "mode": "math_svg_katex_css",
            "title": "勾股定理互动动画",
            "goal": "通过拖动直角三角形边长观察面积关系。",
            "visual_steps": ["显示直角三角形", "展示三边平方", "拖动边长验证"],
            "controls": [{"id": "leg-slider", "label": "直角边", "type": "slider"}],
            "formulas": ["a^2+b^2=c^2"],
            "validation_points": ["使用 CSS 动画", "使用 KaTeX 渲染公式"],
            "primary_color": "#22D3EE",
        })
        yield LLMStreamChunk(kind="content", delta=raw)

    monkeypatch.setattr(react_module, "call_llm_stream", fake_llm_stream)

    response = client.post("/generate-aetherviz-spec", json={"topic": "勾股定理"})

    events = parse_sse_events(response)
    assert "thinking_delta" in [event for event, _ in events]
    assert events[-1][0] == "plan_ready"
    assert events[-1][1]["plan"]["mode"] == "math_svg_katex_css"
    thinking = next(data for event, data in events if event == "thinking_delta")
    assert "数学几何主题" in thinking["delta"]


def test_generate_phase_requires_approved_plan() -> None:
    response = client.post(
        "/generate-aetherviz-spec",
        json={"topic": "熵增演示", "phase": "generate"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "approved_plan 不能为空"


def test_generate_phase_uses_approved_plan_for_html(monkeypatch) -> None:
    calls = []

    def fake_llm_stream(prompt: str, system_prompt: str, max_tokens: int = 0, temperature: float = 0.3):
        calls.append((prompt, system_prompt, max_tokens, temperature))
        html = sample_svg_html(marker="ready")
        yield html[:120]
        yield html[120:]

    monkeypatch.setattr(react_module, "call_llm_stream", fake_llm_stream)

    response = client.post(
        "/generate-aetherviz-spec",
        json={"topic": "熵增演示", "phase": "generate", "approved_plan": sample_approved_plan()},
    )

    events = parse_sse_events(response)
    assert events[-1][0] == "done"
    assert "generation_delta" in [event for event, _ in events]
    done_data = events[-1][1]
    html = done_data["html"]
    assert len(calls) == 1
    assert '<title>熵增演示</title>' in html
    assert "学习目标1" in html
    assert "核心概念A" in html
    assert done_data["metadata"]["source"] == "llm_svg"
    assert done_data["metadata"]["attempts"] == 1
    assert done_data["metadata"]["degraded"] is True
    assert done_data["metadata"]["render_mode"] == "generic_svg"
    assert done_data["metadata"]["plan"]["controls"][0]["id"] == "progress-slider"
    assert done_data["output_tokens_total"] > 0


def test_generate_phase_stops_stream_after_complete_html(monkeypatch) -> None:
    yielded = []

    def fake_llm_stream(prompt: str, system_prompt: str, max_tokens: int = 0, temperature: float = 0.3):
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
        strict=False,
    )

    assert isinstance(warnings, list)


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

    def fake_llm_stream(prompt: str, system_prompt: str, max_tokens: int = 0, temperature: float = 0.3):
        calls.append((prompt, system_prompt, max_tokens, temperature))
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
    assert "数学主题固定使用" in sys_prompt
    assert "二次函数" in user_prompt
    assert "#22D3EE" in user_prompt


def test_fallback_planner_selects_generation_modes() -> None:
    from aetherviz_service.aetherviz.fallback_planner import select_generation_mode

    assert select_generation_mode("牛顿第二定律") == "generic_svg"
    assert select_generation_mode("电场线分布") == "generic_svg"
    assert select_generation_mode("化学反应速率") == "generic_svg"
    assert select_generation_mode("分子结构") == "generic_svg"
    assert select_generation_mode("平行四边形面积") == "math_svg_katex_css"


def test_planning_normalization_keeps_new_plan_shape() -> None:
    from aetherviz_service.aetherviz.fallback_planner import normalize_plan

    plan = normalize_plan(
        {
            "subject": "physics",
            "mode": "generic_svg",
            "title": "力学过程互动动画",
            "goal": "观察力学过程的关键变化。",
            "visual_steps": ["展示结构", "播放过程", "拖动变量"],
            "controls": [{"id": "force-slider", "label": "作用力", "type": "slider"}],
            "formulas": ["F=ma"],
            "validation_points": ["使用 SVG"],
        },
        "物理轻量化力学演示",
    )

    assert plan["mode"] == "generic_svg"
    assert plan["subject"] == "physics"
    assert plan["title"] == "力学过程互动动画"
    assert plan["controls"][0]["id"] == "force-slider"
    assert plan["formulas"] == ["F=ma"]


def test_planning_parse_valid() -> None:
    from aetherviz_service.aetherviz.fallback_planner import parse_planning_result
    raw = json.dumps({
        "title": "测试动画",
        "goal": "通过按钮点击切换步骤",
        "visual_steps": ["目标一"],
        "controls": [{"id": "step-button", "label": "步骤", "type": "button"}],
        "formulas": ["公式1"],
    })
    res = parse_planning_result(raw, "测试")
    assert res["title"] == "测试动画"
    assert res["goal"] == "通过按钮点击切换步骤"
    assert res["visual_steps"] == ["目标一"]
    assert res["controls"][0]["id"] == "step-button"
    assert res["formulas"] == ["公式1"]


def test_planning_parse_plain_code_fence() -> None:
    from aetherviz_service.aetherviz.fallback_planner import parse_planning_result
    raw = """```
{
  "title": "测试动画",
  "goal": "通过选择题即时反馈",
  "visual_steps": ["目标一"],
  "controls": [{"id": "quiz-button", "label": "反馈", "type": "button"}],
  "formulas": ["公式1"]
}
```"""
    res = parse_planning_result(raw, "测试")
    assert res["title"] == "测试动画"
    assert res["goal"] == "通过选择题即时反馈"
    assert res["visual_steps"] == ["目标一"]
    assert res["controls"][0]["id"] == "quiz-button"
    assert res["formulas"] == ["公式1"]


def test_planning_parse_invalid_returns_default() -> None:
    from aetherviz_service.aetherviz.fallback_planner import parse_planning_result
    res = parse_planning_result("bad json data", "测试主题")
    assert len(res["visual_steps"]) >= 3
    assert "测试主题" in res["title"]
    assert res["mode"] == "generic_svg"


def test_fallback_planning_failure_returns_default_plan(monkeypatch) -> None:
    calls = []

    def fake_llm_stream(prompt: str, system_prompt: str, max_tokens: int = 0, temperature: float = 0.3):
        calls.append((prompt, system_prompt, max_tokens, temperature))
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

    def fake_llm_stream(prompt: str, system_prompt: str, max_tokens: int = 0, temperature: float = 0.3):
        calls.append((prompt, system_prompt, max_tokens, temperature))
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
    assert "首次失败" in events[-1][1]["detail"]
    assert "修复失败" in events[-1][1]["detail"]


def test_generate_phase_repairs_invalid_first_output(monkeypatch) -> None:
    calls = []

    def fake_llm_stream(prompt: str, system_prompt: str, max_tokens: int = 0, temperature: float = 0.3):
        calls.append((prompt, system_prompt, max_tokens, temperature))
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
    assert events[-1][1]["metadata"]["attempts"] == 2
    assert events[-1][1]["metadata"]["repaired"] is True
    assert "repaired" in events[-1][1]["html"]


def test_revise_phase_updates_current_html(monkeypatch) -> None:
    calls = []

    def fake_llm_stream(prompt: str, system_prompt: str, max_tokens: int = 0, temperature: float = 0.3):
        calls.append((prompt, system_prompt, max_tokens, temperature))
        yield sample_svg_html(marker="revised")

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
    assert events[-1][0] == "done"
    assert len(calls) == 1
    prompt, system_prompt, max_tokens, temperature = calls[0]
    assert "把动画速度调慢" in prompt
    assert "before-revise" in prompt
    assert "HTML 修订工程师" in system_prompt
    assert max_tokens == 9000
    assert temperature == 0.16
    assert events[-1][1]["metadata"]["source"] == "llm_svg_revision"
    assert "revised" in events[-1][1]["html"]


def test_revise_phase_repairs_invalid_first_output(monkeypatch) -> None:
    calls = []

    def fake_llm_stream(prompt: str, system_prompt: str, max_tokens: int = 0, temperature: float = 0.3):
        calls.append((prompt, system_prompt, max_tokens, temperature))
        if len(calls) == 1:
            yield "<html><body>修订破损</body></html>"
            return
        yield sample_svg_html(marker="revise-repaired")

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
    assert any(data.get("stage") == "repairing" for event, data in events if event == "progress")
    assert events[-1][0] == "done"
    assert len(calls) == 2
    assert events[-1][1]["metadata"]["attempts"] == 2
    assert events[-1][1]["metadata"]["repaired"] is True
    assert "revise-repaired" in events[-1][1]["html"]


def test_revise_phase_requires_current_html_and_instruction() -> None:
    missing_html = client.post(
        "/generate-aetherviz-spec",
        json={"topic": "熵增演示", "phase": "revise", "instruction": "改慢一点"},
    )
    assert missing_html.status_code == 400
    assert missing_html.json()["detail"] == "current_html 不能为空"

    missing_instruction = client.post(
        "/generate-aetherviz-spec",
        json={"topic": "熵增演示", "phase": "revise", "current_html": sample_svg_html()},
    )
    assert missing_instruction.status_code == 400
    assert missing_instruction.json()["detail"] == "instruction 不能为空"


def test_generate_phase_returns_error_for_inline_script_syntax_error(monkeypatch) -> None:
    calls = []

    def fake_llm_stream(prompt: str, system_prompt: str, max_tokens: int = 0, temperature: float = 0.3):
        calls.append((prompt, system_prompt, max_tokens, temperature))
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
