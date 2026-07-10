"""AetherViz workflow tests."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from aetherviz_service.config import settings
from aetherviz_service.main import app

client = TestClient(app)
AETHERVIZ_ENDPOINT = "/bingo-ai/generate-aetherviz-spec"


@pytest.fixture(autouse=True)
def disable_real_llm_calls(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", None)
    monkeypatch.setattr(settings, "planning_openai_api_key", None)
    monkeypatch.setattr(settings, "langsmith_tracing", False)


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
<script type="application/json" id="widget-config">{"type":"simulation","concept":"熵增"}</script>
</head>
<body>
<main id="aetherviz-stage"><svg viewBox="0 0 100 100"><circle id="dot" cx="20" cy="50" r="8"></circle></svg></main>
<p id="animation-caption">当前步骤：观察。</p>
<button id="play-animation">播放</button>
<button id="pause-animation">暂停</button>
<button id="reset-animation">重置</button>
<script>
const state = { progress: 0 };
const dot = document.getElementById('dot');
const caption = document.getElementById('animation-caption');
function updateVisualization(){
  state.progress = (state.progress + 1) % 100;
  dot.setAttribute('cx', String(20 + state.progress / 2));
  caption.textContent = state.progress > 50 ? '当前步骤：归纳。' : '当前步骤：观察。';
}
function play(){ updateVisualization(); }
function pause(){ state.paused = true; }
function reset(){ state.progress = 0; updateVisualization(); }
document.getElementById('play-animation').addEventListener('click', updateVisualization);
document.getElementById('pause-animation').addEventListener('click', pause);
document.getElementById('reset-animation').addEventListener('click', reset);
window.addEventListener('message', function(event) {
  const type = event.data && event.data.type;
  if (type === 'SET_WIDGET_STATE') Object.assign(state, event.data.state || {});
  if (type === 'HIGHLIGHT_ELEMENT') dot.dataset.highlighted = 'true';
  if (type === 'ANNOTATE_ELEMENT') caption.textContent = event.data.content || '';
  if (type === 'REVEAL_ELEMENT') dot.hidden = false;
});
window.AetherVizRuntime = { play, pause, reset, update: updateVisualization, getState: () => state };
window.__AETHERVIZ_RUNTIME_READY__ = true;
</script>
</body>
</html>"""


def test_generate_aetherviz_spec_returns_400_when_topic_empty() -> None:
    response = client.post(AETHERVIZ_ENDPOINT, json={"topic": "   "})

    assert response.status_code == 400
    assert response.json()["detail"] == "topic 不能为空"


def test_static_page_routes_are_removed() -> None:
    assert client.get("/aetherviz-static-knowledge-points").status_code == 404
    assert client.get("/aetherviz-static-html", params={"knowledge_point_id": "physics/newton_second_law"}).status_code == 404
    assert client.get("/static-html/physics/newton-second-law.html").status_code == 404


def test_aetherviz_route_requires_bingo_ai_prefix() -> None:
    assert client.post("/generate-aetherviz-spec", json={"topic": "熵增演示"}).status_code == 404


def test_plan_phase_streams_new_plan_events() -> None:
    response = client.post(AETHERVIZ_ENDPOINT, json={"topic": "初中物理 电路串并联", "phase": "plan"})

    assert response.status_code == 200
    events = parse_sse_events(response)
    names = [event for event, _ in events]
    assert names[0] == "plan.started"
    assert "plan.delta" in names
    assert names[-1] in {"plan.ready", "context.compressed"}
    deltas = [data for event, data in events if event == "plan.delta"]
    assert deltas
    assert deltas[0]["data"]["planning_steps"]
    ready = next(data for event, data in events if event == "plan.ready")
    plan = ready["data"]["plan"]
    assert plan["page_type"] == "interactive"
    assert plan["status"] == "draft"
    assert plan["interactive_type"] in {"simulation", "diagram", "game"}
    assert ready["metadata"]["context_status"]["status"] in {"normal", "compressed"}


def test_revise_plan_streams_complete_revised_plan() -> None:
    response = client.post(
        AETHERVIZ_ENDPOINT,
        json={
            "topic": "熵增演示",
            "phase": "revise_plan",
            "current_plan": sample_plan(),
            "message": "改成闯关式并增加学生预测环节",
        },
    )

    events = parse_sse_events(response)
    assert events[0][0] == "plan.revise_started"
    assert any(event == "plan.delta" for event, _ in events)
    revised = next(data for event, data in events if event == "plan.revised")
    assert revised["data"]["plan"]["status"] == "revised"
    assert "改成闯关式" in revised["data"]["plan"]["revision_summary"]


def test_revise_plan_requires_current_plan_and_message() -> None:
    response = client.post(
        AETHERVIZ_ENDPOINT,
        json={"topic": "熵增演示", "phase": "revise_plan", "current_plan": sample_plan()},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "message 不能为空"


def test_approve_plan_marks_plan_approved() -> None:
    response = client.post(AETHERVIZ_ENDPOINT, json={"phase": "approve_plan", "plan": sample_plan()})

    events = parse_sse_events(response)
    assert events[-1][0] == "plan.approved"
    assert events[-1][1]["data"]["plan"]["status"] == "approved"


def test_generate_phase_requires_approved_plan() -> None:
    response = client.post(AETHERVIZ_ENDPOINT, json={"phase": "generate"})

    assert response.status_code == 400
    assert response.json()["detail"] == "approved_plan 不能为空"


def test_generate_phase_streams_html_size_validates_in_memory_and_returns_html() -> None:
    response = client.post(
        AETHERVIZ_ENDPOINT,
        json={"topic": "熵增演示", "phase": "generate", "approved_plan": sample_plan()},
    )

    events = parse_sse_events(response)
    names = [event for event, _ in events]
    assert "html.generation_started" in names
    assert "html.delta" in names
    assert "sandbox.written" not in names
    assert "validation.check" in names
    assert "validation.report" in names
    assert "html.done" in names
    done = next(data for event, data in events if event == "html.done")
    assert done["data"]["html"].startswith("<!DOCTYPE html>")
    assert done["data"]["metadata"]["attempts"] >= 1
    assert done["data"]["metadata"]["generation_backend"] == "direct"
    assert done["data"]["metadata"]["reasoning_elapsed_ms"] >= 0
    assert done["data"]["metadata"]["bytes"] == len(done["data"]["html"].encode("utf-8"))
    assert done["data"]["metadata"]["chars"] == len(done["data"]["html"])
    assert done["metadata"]["stage"] == "done"
    assert "plan" not in done["data"]["metadata"]
    assert "artifacts" not in done["data"]["metadata"]
    size_events = [data["data"] for event, data in events if event == "html.delta" and data["data"].get("bytes")]
    assert size_events
    assert size_events[-1]["bytes"] == len(done["data"]["html"].encode("utf-8"))
    assert size_events[-1]["chars"] == len(done["data"]["html"])


def test_generate_phase_returns_error_when_html_agent_fails_completely(monkeypatch) -> None:
    from aetherviz_service.aetherviz.agents import html_agent

    monkeypatch.setattr(settings, "openai_api_key", "test-key")

    def failing_stream(topic, plan):
        raise html_agent.HtmlGenerationError("HTML 生成失败，未获得可用页面", detail="boom")

    monkeypatch.setattr(html_agent, "stream_generate_html", failing_stream)

    response = client.post(
        AETHERVIZ_ENDPOINT,
        json={"topic": "熵增演示", "phase": "generate", "approved_plan": sample_plan()},
    )

    events = parse_sse_events(response)
    assert events[-1][0] == "error"
    assert events[-1][1]["data"]["code"] == "generation_failed"
    assert "未获得可用页面" in events[-1][1]["data"]["message"]
    assert all(event != "html.done" for event, _ in events)


def test_generate_phase_escapes_special_topic_in_deterministic_html() -> None:
    topic = '能量"</script><script>alert(1)</script>'
    response = client.post(
        AETHERVIZ_ENDPOINT,
        json={"topic": topic, "phase": "generate", "approved_plan": sample_plan(topic)},
    )

    events = parse_sse_events(response)
    done = next(data for event, data in events if event == "html.done")
    generated_html = done["data"]["html"]
    assert "<script>alert(1)</script>" not in generated_html
    assert "<\\/script>" in generated_html


def test_edit_html_generates_new_branch_events() -> None:
    response = client.post(
        AETHERVIZ_ENDPOINT,
        json={"phase": "edit_html", "current_html": sample_html(), "message": "把按钮改大", "context": {"topic": "熵增演示"}},
    )

    events = parse_sse_events(response)
    names = [event for event, _ in events]
    assert "html.edit_started" in names
    assert "html.delta" in names
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


def test_security_checker_allows_only_configured_gsap_cdn(monkeypatch) -> None:
    from aetherviz_service.aetherviz.tools.security_checker import check_security

    custom_url = "https://assets.example.edu/vendor/gsap.min.js"
    monkeypatch.setattr(settings, "aetherviz_gsap_cdn_url", custom_url)

    allowed = check_security(f'<!DOCTYPE html><html><head><script src="{custom_url}"></script></head></html>')
    old_default = check_security(
        '<!DOCTYPE html><html><head><script src="https://cdn.jsdelivr.net/npm/gsap@3/dist/gsap.min.js"></script></head></html>'
    )

    assert allowed["ok"] is True
    assert old_default["ok"] is False
    assert any(error["type"] == "external_resource" for error in old_default["errors"])


def test_plan_normalization_uses_configured_gsap_cdn(monkeypatch) -> None:
    from aetherviz_service.aetherviz.workflow.plan_contract import normalize_plan

    custom_url = "https://assets.example.edu/vendor/gsap.min.js"
    monkeypatch.setattr(settings, "aetherviz_gsap_cdn_url", custom_url)
    raw_plan = sample_plan()
    raw_plan["runtime"]["external_libraries"] = ["https://cdn.jsdelivr.net/npm/gsap@3/dist/gsap.min.js"]

    normalized = normalize_plan(raw_plan, "熵增演示")

    assert normalized["runtime"]["external_libraries"] == [custom_url]


def test_validation_report_rejects_inline_script_syntax_error() -> None:
    from aetherviz_service.aetherviz.tools.validation_report import build_validation_report

    bad_html = sample_html().replace("const state = { progress: 0 };", "const state = ;")

    report = build_validation_report(bad_html)

    assert report["ok"] is False
    assert any(error["type"] == "js_syntax" for error in report["errors"])


def test_validation_report_rejects_missing_widget_runtime_contract() -> None:
    from aetherviz_service.aetherviz.tools.validation_report import build_validation_report

    bad_html = "<!DOCTYPE html><html><body><script>const ok = true;</script></body></html>"

    report = build_validation_report(bad_html)

    assert report["ok"] is False
    error_types = {error["type"] for error in report["errors"]}
    assert "missing_widget_config" in error_types
    assert "missing_stage" in error_types
    assert "missing_runtime" in error_types


def test_validation_report_accepts_minimum_widget_runtime_contract() -> None:
    from aetherviz_service.aetherviz.tools.validation_report import build_validation_report

    report = build_validation_report(sample_html())

    assert report["ok"] is True
    assert report["checks"]["widget_contract_checker"]["ok"] is True


def test_generate_phase_triggers_repair_when_validation_fails(monkeypatch) -> None:
    from aetherviz_service.aetherviz.agents import html_agent, repair_agent
    from aetherviz_service.aetherviz.agents.html_agent import HtmlStreamResult, build_html_progress_payload
    from aetherviz_service.aetherviz.agents.repair_agent import RepairStreamResult

    monkeypatch.setattr(settings, "openai_api_key", "test-key")

    bad_html = sample_html().replace("const state = { progress: 0 };", "const state = ;")

    def fake_stream(topic, plan):
        yield build_html_progress_payload(
            [
                {"content": "写入完整 HTML 初稿", "status": "completed"},
                {"content": "输出最终 HTML 文档", "status": "completed"},
            ]
        )
        yield HtmlStreamResult(html=bad_html, degraded=False)

    def fake_repair_stream(**kwargs):
        yield build_html_progress_payload(
            [
                {"content": "分析校验错误并修复 HTML", "status": "completed"},
                {"content": "输出修复后的完整 HTML", "status": "completed"},
            ]
        )
        yield RepairStreamResult(html=sample_html(), degraded=False)

    monkeypatch.setattr(html_agent, "stream_generate_html", fake_stream)
    monkeypatch.setattr(repair_agent, "stream_repair_html", fake_repair_stream)
    from aetherviz_service.aetherviz.workflow import generate_workflow

    monkeypatch.setattr(generate_workflow, "stream_generate_html", fake_stream)
    monkeypatch.setattr(generate_workflow, "stream_repair_html", fake_repair_stream)

    response = client.post(
        AETHERVIZ_ENDPOINT,
        json={"topic": "熵增演示", "phase": "generate", "approved_plan": sample_plan()},
    )

    events = parse_sse_events(response)
    names = [event for event, _ in events]
    assert "repair.started" in names
    assert "repair.done" in names
    assert "html.done" in names
    done = next(data for event, data in events if event == "html.done")
    assert done["data"]["metadata"]["repaired"] is True
    assert done["data"]["metadata"]["attempts"] >= 2
