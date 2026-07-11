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
    assert ready["metadata"]["planning_elapsed_ms"] >= 0
    assert ready["metadata"]["first_chunk_elapsed_ms"] >= 0
    assert ready["metadata"]["total_tokens"] >= 0


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
    assert done["data"]["metadata"]["first_chunk_elapsed_ms"] >= 0
    assert done["data"]["metadata"]["generation_elapsed_ms"] >= 0
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


def test_plan_normalization_enforces_runtime_control_ids() -> None:
    from aetherviz_service.aetherviz.workflow.plan_contract import normalize_plan

    raw_plan = sample_plan()
    raw_plan["controls"] = [
        {"id": "slider-a", "label": "直角边 a", "type": "slider", "bind": "a"},
        {"id": "slider-b", "label": "直角边 b", "type": "slider", "bind": "b"},
        {"id": "preset-selector", "label": "预设", "type": "select"},
        {"id": "reset-btn", "label": "重置", "type": "button", "action": "reset"},
    ]

    normalized = normalize_plan(raw_plan, "勾股定理")
    control_ids = [control["id"] for control in normalized["controls"]]

    assert control_ids == ["slider-a", "slider-b", "play-animation", "pause-animation", "reset-animation"]


def test_plan_normalization_migrates_fields_and_expands_bounds_for_presets() -> None:
    from aetherviz_service.aetherviz.workflow.plan_contract import normalize_plan

    raw_plan = {
        "interactive_type": "simulation",
        "title": "勾股定理探索",
        "stage_layout": {"description": "主舞台居中，控制区和公式区位于舞台外。"},
        "design_brief": {
            "main_stage_objects": ["直角三角形", "三个边长正方形"],
            "layout_coordinates": "三角形位于舞台中心",
            "color_semantics": "三边使用不同颜色",
            "dynamic_update_rules": "变量变化时同步更新图形和公式",
            "default_preset": "a=3,b=4",
            "acceptance_criteria": "公式与图形同步",
        },
        "interactive_spec": {
            "type": "simulation",
            "concept": "勾股定理",
            "description": "调节两条直角边",
            "variables": [
                {"name": "a", "label": "直角边 a", "min": 1, "max": 12, "step": 1, "default": 3},
                {"name": "b", "label": "直角边 b", "min": 1, "max": 12, "step": 1, "default": 4},
            ],
            "presets": [{"label": "越界预设", "a": 8, "b": 15}],
            "observations": ["观察平方关系"],
        },
        "teaching_flow": [{"step": 1, "instruction": "拖动滑块观察三边变化"}],
        "controls": [{"id": "a-slider", "label": "直角边 a", "type": "slider", "target_var": "a"}],
        "widget_actions": [
            {"action": "widget_setState", "params": {"a": 5, "b": 12}},
            {"action": "widget_highlight", "params": {"elementId": "side-c"}},
            {"action": "widget_annotation", "params": {"elementId": "square-c", "text": "斜边平方"}},
            {"action": "widget_reveal", "params": {"elementId": "formula"}},
        ],
    }

    normalized = normalize_plan(raw_plan, "勾股定理")

    assert normalized["stage_layout"] == "主舞台居中，控制区和公式区位于舞台外。"
    assert normalized["teaching_flow"][0]["caption"] == "拖动滑块观察三边变化"
    assert normalized["controls"][0]["bind"] == "a"
    assert normalized["interactive_spec"]["presets"][0]["values"] == {"a": 8, "b": 15}
    variables = {item["name"]: item for item in normalized["interactive_spec"]["variables"]}
    assert variables["b"]["max"] == 15
    assert normalized["widget_actions"][1]["target"] == "#side-c"
    assert set(normalized["design_brief"]) == {
        "layout",
        "stage_objects",
        "visual_rules",
        "state_updates",
        "default_preset",
        "acceptance",
    }


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


def test_widget_contract_warns_when_animation_value_is_rendered_without_formatting() -> None:
    from aetherviz_service.aetherviz.tools.widget_contract_checker import check_widget_runtime_contract

    risky_html = sample_html().replace(
        "const state = { progress: 0 };",
        "const state = { progress: 0 }; label.textContent = `value=${state.progress}`;",
    )

    report = check_widget_runtime_contract(risky_html)

    assert any(warning["type"] == "unformatted_dynamic_value" for warning in report["warnings"])


def test_widget_contract_accepts_explicitly_formatted_animation_value() -> None:
    from aetherviz_service.aetherviz.tools.widget_contract_checker import check_widget_runtime_contract

    safe_html = sample_html().replace(
        "const state = { progress: 0 };",
        "const state = { progress: 0 }; label.textContent = `value=${formatValue(state.progress)}`;",
    )

    report = check_widget_runtime_contract(safe_html)

    assert not any(warning["type"] == "unformatted_dynamic_value" for warning in report["warnings"])


def test_widget_contract_warns_about_hardcoded_formatter_step_and_raw_formula_state() -> None:
    from aetherviz_service.aetherviz.tools.widget_contract_checker import check_widget_runtime_contract

    risky_html = sample_html().replace(
        "const state = { progress: 0 };",
        "const state = { progress: 0 };\n"
        "function formatValue(value, unit=''){ const step = 0.5; return (Math.round(value / step) * step).toFixed(1) + unit; }\n"
        "function updateFormula(){ const latex = `x=${state.progress}`; caption.textContent = latex; }\n"
        "hudA.textContent = state.progress.toFixed(1); hudB.textContent = state.progress.toFixed(1);",
    )

    report = check_widget_runtime_contract(risky_html)
    warning_types = {warning["type"] for warning in report["warnings"]}

    assert "unformatted_dynamic_value" in warning_types
    assert "missing_numeric_descriptor" in warning_types
    assert "hardcoded_numeric_step" in warning_types
    assert "scattered_visible_precision" in warning_types


def test_validation_report_accepts_minimum_widget_runtime_contract() -> None:
    from aetherviz_service.aetherviz.tools.validation_report import build_validation_report

    report = build_validation_report(sample_html())

    assert report["ok"] is True
    assert report["checks"]["widget_contract_checker"]["ok"] is True


def test_widget_contract_warns_about_call_only_gsap_timeline() -> None:
    from aetherviz_service.aetherviz.tools.widget_contract_checker import check_widget_runtime_contract

    html = sample_html().replace(
        "</head>",
        '<script src="https://cdn.jsdelivr.net/npm/gsap@3/dist/gsap.min.js"></script></head>',
    ).replace(
        "const state = { progress: 0 };",
        "const state = { progress: 0 }; const tl = gsap.timeline({paused:true}); "
        "tl.call(() => updateVisualization()); tl.call(() => updateVisualization()); "
        "if (!window.gsap) updateVisualization();",
    )

    report = check_widget_runtime_contract(html)

    assert any(warning["type"] == "call_only_gsap_timeline" for warning in report["warnings"])


def test_widget_contract_accepts_duration_tween_in_gsap_timeline() -> None:
    from aetherviz_service.aetherviz.tools.widget_contract_checker import check_widget_runtime_contract

    html = sample_html().replace(
        "</head>",
        '<script src="https://cdn.jsdelivr.net/npm/gsap@3/dist/gsap.min.js"></script></head>',
    ).replace(
        "const state = { progress: 0 };",
        "const state = { progress: 0 }; const tl = gsap.timeline({paused:true}); "
        "tl.to('#dot', {x: 20, duration: 0.6}).call(() => updateVisualization()); "
        "if (!window.gsap) updateVisualization();",
    )

    report = check_widget_runtime_contract(html)

    assert not any(warning["type"] == "call_only_gsap_timeline" for warning in report["warnings"])


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


def test_generate_phase_accepts_quality_repair_only_when_warning_is_reduced(monkeypatch) -> None:
    from aetherviz_service.aetherviz.agents.html_agent import HtmlStreamResult
    from aetherviz_service.aetherviz.agents.repair_agent import RepairStreamResult
    from aetherviz_service.aetherviz.workflow import generate_workflow

    risky_html = sample_html().replace(
        "const state = { progress: 0 };",
        "const state = { progress: 0 }; label.textContent = `value=${state.progress}`;",
    )

    def fake_stream(topic, plan):
        yield HtmlStreamResult(html=risky_html, degraded=False)

    def fake_repair_stream(**kwargs):
        yield RepairStreamResult(html=sample_html(), degraded=False)

    monkeypatch.setattr(settings, "aetherviz_max_repair_attempts", 1)
    monkeypatch.setattr(generate_workflow, "stream_generate_html", fake_stream)
    monkeypatch.setattr(generate_workflow, "stream_repair_html", fake_repair_stream)

    response = client.post(
        AETHERVIZ_ENDPOINT,
        json={"topic": "变量变化", "phase": "generate", "approved_plan": sample_plan("变量变化")},
    )

    events = parse_sse_events(response)
    quality_done = next(
        data
        for event, data in events
        if event == "repair.done" and data["data"].get("strategy") == "quality-model"
    )
    done = next(data for event, data in events if event == "html.done")

    assert quality_done["data"]["accepted"] is True
    assert done["data"]["html"] == sample_html()
    assert done["data"]["metadata"]["repaired"] is True


def test_edit_html_stream_propagates_generator_exit(monkeypatch) -> None:
    from unittest.mock import MagicMock

    from aetherviz_service.aetherviz.workflow import edit_html_workflow

    monkeypatch.setattr(settings, "openai_api_key", "test-key")

    class GeneratorExitModel:
        def stream(self, messages):
            yield MagicMock(content=sample_html(), additional_kwargs={})
            raise GeneratorExit()

    monkeypatch.setattr(edit_html_workflow, "create_chat_model", lambda kind: GeneratorExitModel())

    with pytest.raises(GeneratorExit):
        list(
            edit_html_workflow._stream_edit_html(
                topic="熵增演示",
                message="把按钮改大",
                current_html=sample_html(),
                context=None,
            )
        )


def test_repair_stream_propagates_generator_exit(monkeypatch) -> None:
    from unittest.mock import MagicMock

    from aetherviz_service.aetherviz.agents import repair_agent

    monkeypatch.setattr(settings, "openai_api_key", "test-key")

    class GeneratorExitModel:
        def stream(self, messages):
            yield MagicMock(content=sample_html(), additional_kwargs={})
            raise GeneratorExit()

    monkeypatch.setattr(repair_agent, "create_chat_model", lambda kind: GeneratorExitModel())

    with pytest.raises(GeneratorExit):
        list(
            repair_agent.stream_repair_html(
                topic="熵增演示",
                plan=sample_plan("熵增演示"),
                raw_html=sample_html(),
                report={"ok": False, "errors": [], "warnings": []},
            )
        )


def test_widget_contract_warns_about_duplicate_setattribute_label_positions() -> None:
    from aetherviz_service.aetherviz.tools.widget_contract_checker import check_widget_runtime_contract

    html = sample_html().replace(
        "function updateVisualization(){",
        "function updateVisualization(){\n"
        "  primaryLabel.setAttribute('x', state.offset);\n"
        "  primaryLabel.setAttribute('y', state.position);\n"
        "  secondaryLabel.setAttribute('x', state.offset);\n"
        "  secondaryLabel.setAttribute('y', state.position);\n",
    )

    report = check_widget_runtime_contract(html)

    warnings = [warning for warning in report["warnings"] if warning["type"] == "duplicate_label_position"]
    assert warnings
    assert "primaryLabel" in warnings[0]["message"]
    assert "secondaryLabel" in warnings[0]["message"]


def test_widget_contract_accepts_distinct_setattribute_label_positions() -> None:
    from aetherviz_service.aetherviz.tools.widget_contract_checker import check_widget_runtime_contract

    html = sample_html().replace(
        "function updateVisualization(){",
        "function updateVisualization(){\n"
        "  primaryLabel.setAttribute('x', state.offset);\n"
        "  primaryLabel.setAttribute('y', state.position);\n"
        "  secondaryLabel.setAttribute('x', state.offset + labelGap);\n"
        "  secondaryLabel.setAttribute('y', state.position + labelGap);\n",
    )

    report = check_widget_runtime_contract(html)

    assert not any(warning["type"] == "duplicate_label_position" for warning in report["warnings"])


def test_widget_contract_warns_about_duplicate_static_text_positions() -> None:
    from aetherviz_service.aetherviz.tools.widget_contract_checker import check_widget_runtime_contract

    html = sample_html().replace(
        '<circle id="dot" cx="20" cy="50" r="8"></circle>',
        '<circle id="dot" cx="20" cy="50" r="8"></circle>'
        '<text id="primary-label" x="10" y="10">变量</text>'
        '<text id="secondary-label" x="10" y="10">读数</text>',
    )

    report = check_widget_runtime_contract(html)

    assert any(warning["type"] == "duplicate_label_position" for warning in report["warnings"])


def test_generation_and_edit_prompts_include_stage_centering_rules() -> None:
    from aetherviz_service.aetherviz.agents.instructions import (
        ADAPTIVE_LAYOUT_PROMPT,
        DIAGRAM_SYSTEM_PROMPT,
        EDIT_HTML_SYSTEM_PROMPT,
        GAME_SYSTEM_PROMPT,
        GRAPHICS_CRAFT_PROMPT,
        NUMERIC_PRESENTATION_PROMPT,
        SIMULATION_SYSTEM_PROMPT,
        STAGE_CENTERING_AND_LABEL_PROMPT,
        VISUAL_DESIGN_SYSTEM_PROMPT,
    )

    shared_rule_marker = STAGE_CENTERING_AND_LABEL_PROMPT.strip().splitlines()[-1]
    for prompt in (SIMULATION_SYSTEM_PROMPT, EDIT_HTML_SYSTEM_PROMPT):
        assert shared_rule_marker in prompt
        assert "viewBox" in prompt
        assert "页面排版 token" in prompt
        assert "getScreenCTM()" in prompt
        assert "getBoundingClientRect" in prompt
        assert "禁止按具体文本内容、元素 id 或单个初始状态打补丁" in prompt
        assert ADAPTIVE_LAYOUT_PROMPT.strip().splitlines()[-1] in prompt
        assert "ResizeObserver" in prompt
        assert "固定像素侧栏" in prompt
        assert VISUAL_DESIGN_SYSTEM_PROMPT.strip().splitlines()[-1] in prompt
        assert "清爽教学工作台" in prompt
        assert "#2d4f41" in prompt
        assert NUMERIC_PRESENTATION_PROMPT.strip().splitlines()[-1] in prompt
        assert GRAPHICS_CRAFT_PROMPT.strip().splitlines()[-1] in prompt
        assert "连续计算状态与可见展示状态必须分离" in prompt
        assert "共享边、连接点和轮廓" in prompt
        assert "禁止按具体图形、路径 id、坐标或预设写特例" in prompt

    assert "浅色实验舞台" in SIMULATION_SYSTEM_PROMPT
    assert "关系画布" in DIAGRAM_SYSTEM_PROMPT
    assert "街机霓虹风" in GAME_SYSTEM_PROMPT


def test_generation_prompt_has_explicit_svg_text_scale_acceptance() -> None:
    from aetherviz_service.aetherviz.agents.instructions import build_interactive_generation_prompt

    prompt = build_interactive_generation_prompt("参数关系", sample_plan("参数关系"))

    assert "SVG 最终硬验收" in prompt
    assert "数学/抽象 viewBox" in prompt
    assert "getScreenCTM()" in prompt
    assert "初始状态、参数范围边界和动画关键帧" in prompt
    assert "禁止按主题、标签 id、具体坐标或单个预设写特例" in prompt


def test_generation_prompt_uses_descriptor_driven_numbers_and_semantic_strokes() -> None:
    from aetherviz_service.aetherviz.agents.instructions import (
        SIMULATION_SYSTEM_PROMPT,
        build_interactive_generation_prompt,
    )

    prompt = build_interactive_generation_prompt("变量关系", sample_plan("变量关系"))

    assert "描述符驱动的统一格式化入口" in prompt
    assert "语义化描边层级" in prompt
    assert "共享边只绘制一次" in prompt
    assert "默认最多" not in SIMULATION_SYSTEM_PROMPT
    assert "散落的 `toFixed` 常量" in SIMULATION_SYSTEM_PROMPT


def test_default_design_brief_matches_frontend_visual_language() -> None:
    from aetherviz_service.aetherviz.workflow.plan_contract import normalize_plan

    normalized = normalize_plan({}, "勾股定理")
    visual_rules = " ".join(normalized["design_brief"]["visual_rules"])

    assert "浅色教学工作台" in visual_rules
    assert "灰绿背景" in visual_rules
    assert "主题主色只用于" in visual_rules


def test_widget_contract_warns_about_fixed_sidebars_and_missing_stage_guards() -> None:
    from aetherviz_service.aetherviz.tools.widget_contract_checker import check_widget_runtime_contract

    html = sample_html().replace(
        "body{margin:0}",
        ".app-shell{display:grid;grid-template-columns:280px 1fr 280px}body{margin:0}",
    )

    report = check_widget_runtime_contract(html)
    warning_types = {warning["type"] for warning in report["warnings"]}

    assert "fixed_sidebar_layout" in warning_types
    assert "missing_stage_shrink_guard" in warning_types
    assert report["ok"] is True


def test_widget_contract_warns_when_variable_svg_keeps_static_viewbox() -> None:
    from aetherviz_service.aetherviz.tools.widget_contract_checker import check_widget_runtime_contract

    html = sample_html().replace(
        '<button id="play-animation">播放</button>',
        '<input type="range" id="parameter-slider"><button id="play-animation">播放</button>',
    ).replace(
        "function updateVisualization(){",
        "function updateVisualization(){ dot.setAttribute('x', state.progress);",
    )

    report = check_widget_runtime_contract(html)

    assert any(warning["type"] == "static_viewbox_for_variable_svg" for warning in report["warnings"])
    assert report["ok"] is True


def test_widget_contract_accepts_dynamic_variable_svg_viewbox() -> None:
    from aetherviz_service.aetherviz.tools.widget_contract_checker import check_widget_runtime_contract

    html = sample_html().replace(
        '<button id="play-animation">播放</button>',
        '<input type="range" id="parameter-slider"><button id="play-animation">播放</button>',
    ).replace(
        "function updateVisualization(){",
        "function updateVisualization(){ dot.setAttribute('x', state.progress); "
        "const observer = new ResizeObserver(updateVisualization); observer.observe(document.getElementById('aetherviz-stage')); "
        "const box = dot.getBBox(); document.querySelector('svg').setAttribute('viewBox', `${box.x} ${box.y} ${box.width} ${box.height}`);",
    )

    report = check_widget_runtime_contract(html)

    assert not any(warning["type"] == "static_viewbox_for_variable_svg" for warning in report["warnings"])


def test_repair_prompt_is_error_directed_and_does_not_force_unrelated_layout_changes() -> None:
    from aetherviz_service.aetherviz.agents.instructions import REPAIR_SYSTEM_PROMPT, build_repair_prompt

    prompt = build_repair_prompt(
        topic="勾股定理",
        plan=sample_plan("勾股定理"),
        raw_html="<!DOCTYPE html><html><body><button onclick=\"go()\">播放</button></body></html>",
        error_detail='{"errors":[{"type":"inline_event"}]}',
        source_label="确定性检查",
    )

    assert "未被错误点名" in prompt
    assert "舞台居中目标" not in prompt
    assert "硬性错误或明确标记为可修复的通用质量风险" in REPAIR_SYSTEM_PROMPT


def test_edit_html_prompt_has_quantified_convergence_guidance() -> None:
    from aetherviz_service.aetherviz.agents.instructions import EDIT_HTML_SYSTEM_PROMPT

    assert "70%" in EDIT_HTML_SYSTEM_PROMPT


def test_build_edit_html_prompt_trims_plan_summary_to_whitelist() -> None:
    from aetherviz_service.aetherviz.agents.instructions import build_edit_html_prompt

    context = {
        "plan_summary": {
            "title": "勾股定理互动模拟",
            "goal": "理解勾股定理",
            "interactive_type": "simulation",
            "design_brief": {"layout": "单屏"},
            "interactive_spec": {"type": "simulation"},
            "teaching_flow": [{"id": "step-1"}],
            "widget_actions": [{"type": "widget_setState"}],
            "scene_outline": {"id": "scene_1"},
            "formulas": ["a^2+b^2=c^2"],
        },
        "selected_file": {"id": "html-1"},
    }

    prompt = build_edit_html_prompt(
        topic="勾股定理",
        instruction="居中问题",
        current_html="<html></html>",
        context=context,
    )

    assert '"title": "勾股定理互动模拟"' in prompt
    assert '"design_brief"' in prompt
    assert '"interactive_spec"' in prompt
    assert '"teaching_flow"' not in prompt
    assert '"widget_actions"' not in prompt
    assert '"scene_outline"' not in prompt
    assert '"formulas"' not in prompt
