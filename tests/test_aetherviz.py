"""AetherViz Deep Agents workflow tests."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from aetherviz_service.config import settings
from aetherviz_service.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def disable_real_llm_calls(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", None)
    monkeypatch.setattr(settings, "planning_openai_api_key", None)


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


def sample_plan(topic: str = "熵增演示") -> dict:
    return {
        "page_type": "interactive",
        "interactive_type": "simulation",
        "widget_type": "simulation",
        "scene_outline": {
            "id": "scene-main",
            "type": "interactive",
            "title": topic,
            "description": "课堂观察参数变化",
            "keyPoints": ["观察", "比较", "归纳"],
            "order": 1,
            "widgetType": "simulation",
            "widgetOutline": {},
        },
        "subject": "physics",
        "title": f"{topic}互动课件",
        "goal": f"理解{topic}的变化规律。",
        "learner_level": "初中/高中",
        "stage_layout": "顶部目标，中间主舞台，底部控制与结论。",
        "key_points": ["初始状态", "参数变化", "结论归纳"],
        "design_brief": {"main_stage": "中心曲线和运动点"},
        "interactive_spec": {
            "type": "simulation",
            "concept": topic,
            "description": "调节参数观察变化",
            "variables": [{"name": "parameter", "label": "参数", "min": 0, "max": 100, "default": 50}],
            "presets": [{"id": "default", "label": "默认", "values": {"parameter": 50}}],
            "observations": ["观察图形随参数变化"],
        },
        "widget_outline": {"state": "parameter"},
        "widget_actions": [{"type": "SET_WIDGET_STATE", "state": {"parameter": 50}}],
        "teaching_flow": [
            {"id": "observe", "label": "观察", "focus": "初始状态", "caption": "先观察。"},
            {"id": "compare", "label": "比较", "focus": "参数变化", "caption": "再比较。"},
            {"id": "conclude", "label": "归纳", "focus": "结论", "caption": "后归纳。"},
        ],
        "controls": [{"id": "parameter", "label": "参数", "type": "slider", "bind": "parameter"}],
        "formulas": [],
        "runtime": {
            "render_stack": "dom_svg",
            "animation_runtime": "gsap",
            "external_libraries": ["https://cdn.jsdelivr.net/npm/gsap@3/dist/gsap.min.js"],
        },
        "primary_color": "#22D3EE",
    }


def sample_html() -> str:
    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>熵增演示</title>
<style>body{margin:0}#aetherviz-stage{display:grid;place-items:center;min-height:240px}</style>
</head>
<body>
<main id="aetherviz-stage"><svg viewBox="0 0 100 100"><circle id="dot" cx="20" cy="50" r="8"></circle></svg></main>
<p id="animation-caption">当前步骤：观察。</p>
<button id="play-animation">播放</button>
<script>
const state = { progress: 0 };
const dot = document.getElementById('dot');
const caption = document.getElementById('animation-caption');
function updateVisualization(){
  state.progress = (state.progress + 1) % 100;
  dot.setAttribute('cx', String(20 + state.progress / 2));
  caption.textContent = state.progress > 50 ? '当前步骤：归纳。' : '当前步骤：观察。';
}
document.getElementById('play-animation').addEventListener('click', updateVisualization);
window.AetherVizRuntime = { update: updateVisualization, getState: () => state };
window.__AETHERVIZ_RUNTIME_READY__ = true;
</script>
</body>
</html>"""


def test_generate_aetherviz_spec_returns_400_when_topic_empty() -> None:
    response = client.post("/generate-aetherviz-spec", json={"topic": "   "})

    assert response.status_code == 400
    assert response.json()["detail"] == "topic 不能为空"


def test_static_page_routes_are_removed() -> None:
    assert client.get("/aetherviz-static-knowledge-points").status_code == 404
    assert client.get("/aetherviz-static-html", params={"knowledge_point_id": "physics/newton_second_law"}).status_code == 404
    assert client.get("/static-html/physics/newton-second-law.html").status_code == 404


def test_plan_phase_streams_new_plan_events() -> None:
    response = client.post("/generate-aetherviz-spec", json={"topic": "初中物理 电路串并联", "phase": "plan"})

    assert response.status_code == 200
    events = parse_sse_events(response)
    names = [event for event, _ in events]
    assert names[:2] == ["plan.started", "plan.delta"]
    assert names[-1] in {"plan.ready", "context.compressed"}
    ready = next(data for event, data in events if event == "plan.ready")
    plan = ready["data"]["plan"]
    assert plan["page_type"] == "interactive"
    assert plan["status"] == "draft"
    assert plan["interactive_type"] in {"simulation", "diagram", "game"}
    assert ready["metadata"]["context_status"]["status"] in {"normal", "compressed"}


def test_revise_plan_requires_current_plan_and_message() -> None:
    response = client.post(
        "/generate-aetherviz-spec",
        json={"topic": "熵增演示", "phase": "revise_plan", "current_plan": sample_plan()},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "message 不能为空"


def test_revise_plan_streams_complete_revised_plan() -> None:
    response = client.post(
        "/generate-aetherviz-spec",
        json={
            "topic": "熵增演示",
            "phase": "revise_plan",
            "current_plan": sample_plan(),
            "message": "改成闯关式并增加学生预测环节",
        },
    )

    events = parse_sse_events(response)
    assert [event for event, _ in events][:2] == ["plan.revise_started", "plan.delta"]
    revised = next(data for event, data in events if event == "plan.revised")
    assert revised["data"]["plan"]["status"] == "revised"
    assert "改成闯关式" in revised["data"]["plan"]["revision_summary"]


def test_approve_plan_marks_plan_approved() -> None:
    response = client.post("/generate-aetherviz-spec", json={"phase": "approve_plan", "plan": sample_plan()})

    events = parse_sse_events(response)
    assert events[-1][0] == "plan.approved"
    assert events[-1][1]["data"]["plan"]["status"] == "approved"


def test_generate_phase_requires_approved_plan() -> None:
    response = client.post("/generate-aetherviz-spec", json={"phase": "generate"})

    assert response.status_code == 400
    assert response.json()["detail"] == "approved_plan 不能为空"


def test_generate_phase_runs_sandbox_validation_and_done() -> None:
    response = client.post(
        "/generate-aetherviz-spec",
        json={"topic": "熵增演示", "phase": "generate", "approved_plan": sample_plan()},
    )

    events = parse_sse_events(response)
    names = [event for event, _ in events]
    assert "html.generation_started" in names
    assert "sandbox.written" in names
    assert "validation.report" in names
    assert "html.done" in names
    done = next(data for event, data in events if event == "html.done")
    assert done["data"]["html"].startswith("<!DOCTYPE html>")
    assert done["data"]["metadata"]["attempts"] >= 1
    assert done["data"]["metadata"]["artifacts"]["report_path"].endswith("validation-report.json")


def test_edit_html_generates_new_branch_events() -> None:
    response = client.post(
        "/generate-aetherviz-spec",
        json={"phase": "edit_html", "current_html": sample_html(), "message": "把按钮改大", "context": {"topic": "熵增演示"}},
    )

    events = parse_sse_events(response)
    names = [event for event, _ in events]
    assert "html.edit_started" in names
    assert "validation.report" in names
    assert "html.done" in names


def test_validation_report_rejects_dangerous_external_resource() -> None:
    from aetherviz_service.aetherviz.tools.validation_report import build_validation_report

    bad_html = sample_html().replace(
        "</head>",
        '<script src="https://example.com/evil.js"></script></head>',
    )

    report = build_validation_report(bad_html)

    assert report["ok"] is False
    assert any(error["type"] == "external_resource" for error in report["errors"])


def test_validation_report_rejects_inline_script_syntax_error() -> None:
    from aetherviz_service.aetherviz.tools.validation_report import build_validation_report

    bad_html = sample_html().replace("const state = { progress: 0 };", "const state = ;")

    report = build_validation_report(bad_html)

    assert report["ok"] is False
    assert any(error["type"] == "js_syntax" for error in report["errors"])
