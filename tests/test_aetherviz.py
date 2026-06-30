"""AI互动实验 static-hit and interactive HTML fallback tests."""

import base64
import json
from pathlib import Path

from fastapi.testclient import TestClient

import aetherviz_service.aetherviz.react as react_module
import aetherviz_service.aetherviz.static_html as static_html_module
from aetherviz_service.aetherviz.knowledge_points import KNOWLEDGE_POINTS, KnowledgePoint
from aetherviz_service.aetherviz.static_html import (
    DEFAULT_PRIMARY_COLOR,
    static_html_path_for_point,
)
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

    monkeypatch.setattr(react_module, "call_llm", fail_llm)

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
    monkeypatch.setattr(react_module, "call_llm", fail_llm)

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

    monkeypatch.setattr(react_module, "call_llm", fail_llm)

    math_response = client.post("/generate-aetherviz-spec", json={"topic": "勾股定理"})
    chemistry_response = client.post("/generate-aetherviz-spec", json={"topic": "酸碱中和反应"})

    assert math_response.status_code == 200
    math_done = parse_sse_events(math_response)[-1][1]
    assert math_done["metadata"]["subject"] == "math"
    assert math_done["metadata"]["knowledge_point_id"] == "math/pythagorean"
    assert "勾股定理" in math_done["html"]

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

    monkeypatch.setattr(react_module, "call_llm", fail_llm)

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


def test_unmatched_topic_uses_llm_interactive_fallback(monkeypatch) -> None:
    calls = []

    def fake_llm(prompt: str, system_prompt: str, max_tokens: int = 0, temperature: float = 0.3) -> str:
        calls.append((prompt, system_prompt, max_tokens, temperature))
        if len(calls) == 1:
            return json.dumps({
                "learning_objectives": ["学习目标1", "学习目标2", "学习目标3"],
                "core_concepts": ["核心概念A"],
                "interaction_type": "param_explorer",
                "interaction_hint": "提供滑块"
            })
        return """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>熵增演示</title>
</head>
<body>
<h1>熵增演示</h1>
<div>
  <h2>学习目标</h2>
  <ul>
    <li>学习目标1</li>
    <li>学习目标2</li>
    <li>学习目标3</li>
  </ul>
</div>
<div>
  <h2>核心概念</h2>
  <p>核心概念A</p>
</div>
<div class="control-panel">
  <input type="range" id="param">
</div>
<script>
console.log("ready");
</script>
</body>
</html>"""

    monkeypatch.setattr(react_module, "call_llm", fake_llm)

    response = client.post("/generate-aetherviz-spec", json={"topic": "熵增演示"})

    events = parse_sse_events(response)
    assert events[-1][0] == "done"
    done_data = events[-1][1]
    html = done_data["html"]
    assert len(calls) == 2
    assert '<title>熵增演示</title>' in html
    assert "学习目标1" in html
    assert "核心概念A" in html
    assert done_data["metadata"]["source"] == "llm_interactive_fallback"
    assert done_data["metadata"]["attempts"] == 1
    assert done_data["metadata"]["degraded"] is True
    assert done_data["metadata"]["render_mode"] == "interactive-html"


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
    assert "数学分支" in sys_prompt
    assert "二次函数" in user_prompt
    assert "#22D3EE" in user_prompt


def test_planning_parse_valid() -> None:
    from aetherviz_service.aetherviz.fallback_planner import parse_planning_result
    raw = json.dumps({
        "learning_objectives": ["目标一"],
        "core_concepts": ["公式1"],
        "interaction_type": "step_reveal",
        "interaction_hint": "通过按钮点击切换步骤"
    })
    res = parse_planning_result(raw, "测试")
    assert res["learning_objectives"] == ["目标一"]
    assert res["core_concepts"] == ["公式1"]
    assert res["interaction_type"] == "step_reveal"
    assert res["interaction_hint"] == "通过按钮点击切换步骤"


def test_planning_parse_plain_code_fence() -> None:
    from aetherviz_service.aetherviz.fallback_planner import parse_planning_result
    raw = """```
{
  "learning_objectives": ["目标一"],
  "core_concepts": ["公式1"],
  "interaction_type": "quiz",
  "interaction_hint": "通过选择题即时反馈"
}
```"""
    res = parse_planning_result(raw, "测试")
    assert res["learning_objectives"] == ["目标一"]
    assert res["core_concepts"] == ["公式1"]
    assert res["interaction_type"] == "quiz"
    assert res["interaction_hint"] == "通过选择题即时反馈"


def test_planning_parse_invalid_returns_default() -> None:
    from aetherviz_service.aetherviz.fallback_planner import parse_planning_result
    res = parse_planning_result("bad json data", "测试主题")
    assert len(res["learning_objectives"]) >= 2
    assert "测试主题" in res["core_concepts"]
    assert res["interaction_type"] == "general"


def test_fallback_planning_failure_continues(monkeypatch) -> None:
    calls = []

    def fake_llm(prompt: str, system_prompt: str, max_tokens: int = 0, temperature: float = 0.3) -> str:
        calls.append((prompt, system_prompt, max_tokens, temperature))
        if len(calls) == 1:
            return "invalid raw string"  # 规划阶段调用失败
        return """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>熵增演示</title>
</head>
<body>
<h1>熵增演示</h1>
<div>
  <h2>学习目标</h2>
  <ul>
    <li>学习目标1</li>
    <li>学习目标2</li>
    <li>学习目标3</li>
  </ul>
</div>
<div>
  <h2>核心概念</h2>
  <p>核心概念A</p>
</div>
<div class="control-panel">
  <input type="range" id="param">
</div>
<script>
console.log("ready");
</script>
</body>
</html>"""

    monkeypatch.setattr(react_module, "call_llm", fake_llm)

    response = client.post("/generate-aetherviz-spec", json={"topic": "熵增演示"})

    events = parse_sse_events(response)
    assert events[-1][0] == "done"
    done_data = events[-1][1]
    # 即使规划失败，最后依然成功返回，因为进行了兜底
    assert len(calls) == 2
    assert done_data["metadata"]["source"] == "llm_interactive_fallback"
    assert "熵增演示" in done_data["html"]


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


def test_parse_interactive_html_auto_heal_when_truncated() -> None:
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
    
    res = parse_interactive_html(truncated_raw)
    assert "</html>" in res.lower()
    assert "</body>" in res.lower()
    assert "</script>" in res.lower()
    # 验证是否自动补全了缺失的两个大括号以闭合 function 和 if 语句
    assert "}}" in res


def test_fallback_llm_repairs_invalid_first_output_successfully(monkeypatch) -> None:
    calls = []

    def fake_llm(prompt: str, system_prompt: str, max_tokens: int = 0, temperature: float = 0.3) -> str:
        calls.append((prompt, system_prompt, max_tokens, temperature))
        if len(calls) == 1:
            # 1. 规划阶段
            return json.dumps({
                "learning_objectives": ["学习目标1", "学习目标2", "学习目标3"],
                "core_concepts": ["核心概念A"],
                "interaction_type": "param_explorer",
                "interaction_hint": "提供滑块"
            })
        elif len(calls) == 2:
            # 2. 第一次 HTML 生成：故意返回没有 DOCTYPE 的破损 HTML 触发校验失败
            return """<html>
<head><title>破损HTML</title></head>
<body>缺少DOCTYPE和主体，也不够长。</body>
</html>"""
        else:
            # 3. 自动修复：返回完好 HTML
            return """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>熵增演示</title>
</head>
<body>
<h1>熵增演示</h1>
<div>
  <h2>学习目标</h2>
  <ul>
    <li>学习目标1</li>
    <li>学习目标2</li>
    <li>学习目标3</li>
  </ul>
</div>
<div>
  <h2>核心概念</h2>
  <p>核心概念A</p>
</div>
<div class="control-panel">
  <input type="range" id="param">
</div>
<script>
console.log("repaired");
</script>
</body>
</html>"""

    monkeypatch.setattr(react_module, "call_llm", fake_llm)

    response = client.post("/generate-aetherviz-spec", json={"topic": "熵增演示"})

    events = parse_sse_events(response)
    assert events[-1][0] == "done"
    done_data = events[-1][1]
    html = done_data["html"]
    
    # 确认大模型一共被调用了 3 次（规划、第1次生成HTML、第1次自动修复）
    assert len(calls) == 3
    assert "repaired" in html
    assert done_data["metadata"]["source"] == "llm_interactive_fallback"
    assert done_data["metadata"]["attempts"] == 2
    assert done_data["metadata"]["repaired"] is True
    assert done_data["metadata"]["degraded"] is True


def test_fallback_llm_fails_after_failed_repair(monkeypatch) -> None:
    calls = []

    def fake_llm(prompt: str, system_prompt: str, max_tokens: int = 0, temperature: float = 0.3) -> str:
        calls.append((prompt, system_prompt, max_tokens, temperature))
        if len(calls) == 1:
            # 规划阶段
            return json.dumps({
                "learning_objectives": ["学习目标1", "学习目标2", "学习目标3"],
                "core_concepts": ["核心概念A"],
                "interaction_type": "param_explorer",
                "interaction_hint": "提供滑块"
            })
        # 无论是第一次生成还是自动修复生成，都顽固返回长度超过 500 的 HTML 但缺少 DOCTYPE
        return """<html>
<head>
<title>破损HTML但长度超标</title>
</head>
<body>
  <h1>破损 HTML 页面内容</h1>
  <p>这是一个故意填充得非常长的 HTML 页面，用来通过 parse_interactive_html 的 500 字符以上基本长度检查。</p>
  <p>由于大模型在生成过程中可能会犯错，我们需要有一套极其稳健的错误拦截与自愈修复机制。当前测试的用例就是为了验证“自动修复最多只尝试 1 次”。如果在这个流程中，我们收到了多次重试且依然失败，说明重试限制并没有生效。现在这个 HTML 包含了足够多的内容，但没有以 DOCTYPE 开头，因此会触发 AetherVizHtmlValidationError 错误，而不会因为过短被 AetherVizInteractiveHtmlError 拦截。</p>
</body>
</html>"""

    monkeypatch.setattr(react_module, "call_llm", fake_llm)

    response = client.post("/generate-aetherviz-spec", json={"topic": "熵增演示"})

    events = parse_sse_events(response)
    assert events[-1][0] == "error"
    error_data = events[-1][1]
    
    # 证明在进行了 1 次自动修复重试并且依然失败后，直接向前端抛出 validation_failed
    assert error_data["stage"] == "validation_failed"
    assert "缺少 DOCTYPE" in error_data["detail"]
    
    # 确认虽然顽固报错，但最多尝试了 1 次修复（共 3 次 LLM 调用：规划、生成、修复），没有触发第 4 次调用
    assert len(calls) == 3


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


def test_parse_interactive_html_smart_closing_with_brackets() -> None:
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
    result = parse_interactive_html(raw_html)
    assert "</html>" in result
    assert "</script>" in result
    assert "hello {`}" in result
