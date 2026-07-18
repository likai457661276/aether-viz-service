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


def test_approve_plan_preserves_recomposition_contract() -> None:
    plan = sample_plan("圆的面积推导")
    plan["subject"] = "mathematics"
    plan["recomposition_spec"] = {
        "topology_variables": ["parameter"],
        "proof_constraints": {
            "measure_invariants": ["area_preserved", "piece_congruence"],
            "target_assembly": [
                {
                    "id": "target-rectangle",
                    "type": "approximate_rectangle",
                    "max_components": 1,
                    "max_overlap_ratio": 0.1,
                    "min_rectangularity": 0.62,
                    "monotonic": True,
                    "trend_tolerance": 0.08,
                }
            ],
            "stage_requirements": [
                {"id": "source", "intent": "源状态"},
                {"id": "align", "intent": "对齐"},
                {"id": "target", "intent": "目标状态"},
            ],
        },
    }

    response = client.post(AETHERVIZ_ENDPOINT, json={"phase": "approve_plan", "plan": plan})

    events = parse_sse_events(response)
    approved = events[-1][1]["data"]["plan"]
    proof = approved["recomposition_spec"]["proof_constraints"]
    assert proof["target_assembly"] == plan["recomposition_spec"]["proof_constraints"]["target_assembly"]
    assert [item["id"] for item in proof["stage_requirements"]] == ["source", "align", "target"]


def test_generate_phase_requires_approved_plan() -> None:
    response = client.post(AETHERVIZ_ENDPOINT, json={"phase": "generate"})

    assert response.status_code == 400
    assert response.json()["detail"] == "approved_plan 不能为空"


def test_generate_phase_without_model_returns_explicit_error() -> None:
    response = client.post(
        AETHERVIZ_ENDPOINT,
        json={"topic": "熵增演示", "phase": "generate", "approved_plan": sample_plan()},
    )

    events = parse_sse_events(response)
    names = [event for event, _ in events]
    assert "html.generation_started" in names
    assert names[-1] == "error"
    assert events[-1][1]["data"]["code"] == "model_unavailable"
    assert "html.done" not in names


def test_generate_phase_returns_error_when_html_agent_fails_completely(monkeypatch) -> None:
    from aetherviz_service.aetherviz.contracts import pipeline as generate_workflow
    from aetherviz_service.aetherviz.generate import html_agent
    from aetherviz_service.aetherviz.generate import workflow as _generate_entry

    monkeypatch.setattr(settings, "openai_api_key", "test-key")

    def failing_stream(topic, plan):
        raise html_agent.HtmlGenerationError("HTML 生成失败，未获得可用页面", detail="boom")

    monkeypatch.setattr(html_agent, "stream_generate_html", failing_stream)
    monkeypatch.setattr(_generate_entry, "stream_generate_html", failing_stream)
    monkeypatch.setattr(generate_workflow, "stream_generate_html", failing_stream, raising=False)

    response = client.post(
        AETHERVIZ_ENDPOINT,
        json={"topic": "熵增演示", "phase": "generate", "approved_plan": sample_plan()},
    )

    events = parse_sse_events(response)
    assert events[-1][0] == "error"
    assert events[-1][1]["data"]["code"] == "generation_failed"
    assert "未获得可用页面" in events[-1][1]["data"]["message"]
    assert all(event != "html.done" for event, _ in events)


def test_generate_phase_does_not_fallback_for_special_topic_without_model() -> None:
    topic = '能量"</script><script>alert(1)</script>'
    response = client.post(
        AETHERVIZ_ENDPOINT,
        json={"topic": topic, "phase": "generate", "approved_plan": sample_plan(topic)},
    )

    events = parse_sse_events(response)
    assert events[-1][0] == "error"
    assert events[-1][1]["data"]["code"] == "model_unavailable"


def test_edit_html_without_model_returns_explicit_error() -> None:
    response = client.post(
        AETHERVIZ_ENDPOINT,
        json={"phase": "edit_html", "current_html": sample_html(), "message": "把按钮改大", "context": {"topic": "熵增演示"}},
    )

    events = parse_sse_events(response)
    names = [event for event, _ in events]
    assert "html.edit_started" in names
    assert names[-1] == "error"
    assert "html.done" not in names
    assert events[-1][1]["data"]["code"] == "model_unavailable"


def test_validation_report_rejects_dangerous_external_resource() -> None:
    from aetherviz_service.aetherviz.contracts.validation.report import build_validation_report

    bad_html = sample_html().replace(
        "</head>",
        '<script src="https://example.com/evil.js"></script></head>',
    )

    report = build_validation_report(bad_html)

    assert report["ok"] is False
    assert any(error["type"] == "external_resource" for error in report["errors"])


def test_security_checker_allows_only_configured_gsap_cdn(monkeypatch) -> None:
    from aetherviz_service.aetherviz.contracts.validation.security_checker import check_security

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
    from aetherviz_service.aetherviz.contracts.validation.report import build_validation_report

    bad_html = sample_html().replace("const state = { progress: 0 };", "const state = ;")

    report = build_validation_report(bad_html)

    assert report["ok"] is False
    assert any(error["type"] == "js_syntax" for error in report["errors"])


def test_validation_report_downgrades_explicit_low_confidence_error() -> None:
    from aetherviz_service.aetherviz.contracts.validation.report import _normalize_check_confidence

    normalized = _normalize_check_confidence(
        {
            "ok": False,
            "severity": "error",
            "summary": "uncertain",
            "errors": [
                {
                    "type": "heuristic_failure",
                    "message": "无法可靠定位",
                    "confidence": "low",
                    "blocking": False,
                }
            ],
            "warnings": [],
        }
    )

    assert normalized["ok"] is True
    assert normalized["errors"] == []
    assert normalized["warnings"][0]["type"] == "validator_uncertain"
    assert normalized["warnings"][0]["original_type"] == "heuristic_failure"


def test_validation_report_rejects_missing_widget_runtime_contract() -> None:
    from aetherviz_service.aetherviz.contracts.validation.report import build_validation_report

    bad_html = "<!DOCTYPE html><html><body><script>const ok = true;</script></body></html>"

    report = build_validation_report(bad_html)

    assert report["ok"] is False
    error_types = {error["type"] for error in report["errors"]}
    assert "missing_widget_config" in error_types
    assert "missing_stage" in error_types
    assert "missing_runtime" in error_types


def test_widget_contract_warns_when_animation_value_is_rendered_without_formatting() -> None:
    from aetherviz_service.aetherviz.contracts.validation.widget_contract_checker import check_widget_runtime_contract

    risky_html = sample_html().replace(
        "const state = { progress: 0 };",
        "const state = { progress: 0 }; label.textContent = `value=${state.progress}`;",
    )

    report = check_widget_runtime_contract(risky_html)

    assert any(warning["type"] == "unformatted_dynamic_value" for warning in report["warnings"])


def test_widget_contract_accepts_explicitly_formatted_animation_value() -> None:
    from aetherviz_service.aetherviz.contracts.validation.widget_contract_checker import check_widget_runtime_contract

    safe_html = sample_html().replace(
        "const state = { progress: 0 };",
        "const state = { progress: 0 }; label.textContent = `value=${formatValue(state.progress)}`;",
    )

    report = check_widget_runtime_contract(safe_html)

    assert not any(warning["type"] == "unformatted_dynamic_value" for warning in report["warnings"])


def test_widget_contract_ignores_text_and_preformatted_template_values() -> None:
    from aetherviz_service.aetherviz.contracts.validation.widget_contract_checker import check_widget_runtime_contract

    safe_html = sample_html().replace(
        "const state = { progress: 0 };",
        "const state = { progress: 0 }; const e = {message: '错误'}; "
        "const step = {caption: '观察'}; const formattedValue = formatValue(state.progress, descriptor); "
        "caption.textContent = `${e.message} ${step.caption} ${formattedValue}`;",
    )

    report = check_widget_runtime_contract(safe_html)

    assert not any(warning["type"] == "unformatted_dynamic_value" for warning in report["warnings"])


def test_widget_contract_accepts_provable_dynamic_stage_visual_as_legacy() -> None:
    from aetherviz_service.aetherviz.contracts.validation.widget_contract_checker import check_widget_runtime_contract

    html = sample_html().replace(
        '<svg viewBox="0 0 100 100"><circle id="dot" cx="20" cy="50" r="8"></circle></svg>',
        "",
    ).replace(
        "const state = { progress: 0 };",
        "const state = { progress: 0 };\n"
        "const stage = document.getElementById('aetherviz-stage');\n"
        "const visual = document.createElementNS('http://www.w3.org/2000/svg', 'svg');\n"
        "stage.appendChild(visual);",
    )

    report = check_widget_runtime_contract(html)

    assert report["ok"] is True
    assert any(warning["type"] == "dynamic_stage_visual_legacy" for warning in report["warnings"])


def test_widget_contract_rejects_unmounted_dynamic_visual_with_acceptance_contract() -> None:
    from aetherviz_service.aetherviz.contracts.validation.widget_contract_checker import check_widget_runtime_contract

    html = sample_html().replace(
        '<svg viewBox="0 0 100 100"><circle id="dot" cx="20" cy="50" r="8"></circle></svg>',
        "",
    ).replace(
        "const state = { progress: 0 };",
        "const state = { progress: 0 };\n"
        "const visual = document.createElementNS('http://www.w3.org/2000/svg', 'svg');",
    )

    report = check_widget_runtime_contract(html)
    error = next(item for item in report["errors"] if item["type"] == "missing_stage_visual")

    assert report["ok"] is False
    assert error["expected"]["phase"] == "static_dom"
    assert "[data-role='main-visual']" in error["expected"]["selector"]


def test_widget_contract_accepts_static_main_visual_mount() -> None:
    from aetherviz_service.aetherviz.contracts.validation.widget_contract_checker import check_widget_runtime_contract

    html = sample_html().replace(
        '<svg viewBox="0 0 100 100"><circle id="dot" cx="20" cy="50" r="8"></circle></svg>',
        '<div data-role="main-visual"><div class="visual-node"></div></div>',
    )

    report = check_widget_runtime_contract(html)

    assert not any(error["type"] == "missing_stage_visual" for error in report["errors"])


def test_widget_contract_accepts_dynamic_visual_mounted_into_static_main_visual() -> None:
    from aetherviz_service.aetherviz.contracts.validation.widget_contract_checker import check_widget_runtime_contract

    html = sample_html().replace(
        '<svg viewBox="0 0 100 100"><circle id="dot" cx="20" cy="50" r="8"></circle></svg>',
        '<div data-role="main-visual"></div>',
    ).replace(
        "const state = { progress: 0 };",
        "const state = { progress: 0 };\n"
        "const mount = document.querySelector('[data-role=\"main-visual\"]');\n"
        "const visual = document.createElementNS('http://www.w3.org/2000/svg', 'svg');\n"
        "mount.appendChild(visual);",
    )

    report = check_widget_runtime_contract(html)

    assert report["ok"] is True
    assert not any(warning["type"] == "dynamic_stage_visual_legacy" for warning in report["warnings"])


def test_widget_contract_accepts_visual_mounted_through_dom_cache_property() -> None:
    from aetherviz_service.aetherviz.contracts.validation.widget_contract_checker import check_widget_runtime_contract

    html = sample_html().replace(
        '<svg viewBox="0 0 100 100"><circle id="dot" cx="20" cy="50" r="8"></circle></svg>',
        '<div data-role="main-visual"></div>',
    ).replace(
        "const state = { progress: 0 };",
        """const elements = {
  stage: document.querySelector('[data-role="main-visual"]')
};
const visual = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
elements.stage.appendChild(visual);
const state = { progress: 0 };""",
    )

    report = check_widget_runtime_contract(html)

    assert report["ok"] is True
    assert not any(error["type"] == "empty_main_visual_mount" for error in report["errors"])


def test_widget_contract_accepts_member_references_for_mount_and_visual() -> None:
    from aetherviz_service.aetherviz.contracts.validation.widget_contract_checker import check_widget_runtime_contract

    html = sample_html().replace(
        '<svg viewBox="0 0 100 100"><circle id="dot" cx="20" cy="50" r="8"></circle></svg>',
        '<div data-role="main-visual"></div>',
    ).replace(
        "const state = { progress: 0 };",
        """const elements = {};
elements['stage'] = document.querySelector('[data-role="main-visual"]');
elements.visual = document.createElement('canvas');
elements.stage.replaceChildren(elements.visual);
const state = { progress: 0 };""",
    )

    report = check_widget_runtime_contract(html)

    assert report["ok"] is True


def test_widget_contract_rejects_visual_appended_to_different_cache_property() -> None:
    from aetherviz_service.aetherviz.contracts.validation.widget_contract_checker import check_widget_runtime_contract

    html = sample_html().replace(
        '<svg viewBox="0 0 100 100"><circle id="dot" cx="20" cy="50" r="8"></circle></svg>',
        '<div data-role="main-visual"></div><div id="other"></div>',
    ).replace(
        "const state = { progress: 0 };",
        """const elements = {
  stage: document.querySelector('[data-role="main-visual"]'),
  other: document.getElementById('other')
};
const visual = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
elements.other.appendChild(visual);
const state = { progress: 0 };""",
    )

    report = check_widget_runtime_contract(html)

    assert report["ok"] is False
    assert any(error["type"] == "empty_main_visual_mount" for error in report["errors"])


def test_widget_contract_accepts_get_element_by_id_mount_lookup() -> None:
    from aetherviz_service.aetherviz.contracts.validation.widget_contract_checker import check_widget_runtime_contract

    html = sample_html().replace(
        '<svg viewBox="0 0 100 100"><circle id="dot" cx="20" cy="50" r="8"></circle></svg>',
        '<div data-role="main-visual" id="main-visual-mount"></div>',
    ).replace(
        "const state = { progress: 0 };",
        "const state = { progress: 0 };\n"
        "const mount = document.getElementById('main-visual-mount');\n"
        "const visual = document.createElementNS('http://www.w3.org/2000/svg', 'svg');\n"
        "mount.appendChild(visual);",
    )

    report = check_widget_runtime_contract(html)

    assert report["ok"] is True
    assert not any(error["type"] == "empty_main_visual_mount" for error in report["errors"])


def test_widget_contract_accepts_mount_id_constant_cache_pattern() -> None:
    """Regression for getElementById + string-constant mount lookups (LangSmith fca017c8)."""
    from aetherviz_service.aetherviz.contracts.validation.widget_contract_checker import check_widget_runtime_contract

    html = sample_html().replace(
        '<svg viewBox="0 0 100 100"><circle id="dot" cx="20" cy="50" r="8"></circle></svg>',
        '<div data-role="main-visual" id="main-visual-mount" style="width:100%;height:100%;"></div>',
    ).replace(
        "const state = { progress: 0 };",
        """const MOUNT_ID = 'main-visual-mount';
const els = {
  mount: document.getElementById(MOUNT_ID),
  caption: document.getElementById('animation-caption'),
  stats: {
    n: document.getElementById('val-n'),
    error: document.getElementById('val-error')
  }
};
let svgRoot;
function initSVG() {
  svgRoot = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  els.mount.appendChild(svgRoot);
}
initSVG();
const state = { progress: 0 };""",
    )

    report = check_widget_runtime_contract(html)

    assert report["ok"] is True
    assert not any(error["type"] == "empty_main_visual_mount" for error in report["errors"])


def test_widget_contract_accepts_mount_selector_constant_cache_pattern() -> None:
    """Regression for the selector-constant mount flow from LangSmith trace 13c07e7d."""
    from aetherviz_service.aetherviz.contracts.validation.widget_contract_checker import check_widget_runtime_contract

    html = sample_html().replace(
        '<svg viewBox="0 0 100 100"><circle id="dot" cx="20" cy="50" r="8"></circle></svg>',
        '<div data-role="main-visual"></div>',
    ).replace(
        "const state = { progress: 0 };",
        """const MOUNT_SELECTOR = "[data-role='main-visual']";
const els = {
  mount: document.querySelector(MOUNT_SELECTOR),
  caption: document.getElementById('animation-caption')
};
let svgRoot;
function initSVG() {
  svgRoot = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  if (els.mount && els.mount instanceof Node) {
    els.mount.appendChild(svgRoot);
  }
}
initSVG();
const state = { progress: 0 };""",
    )

    report = check_widget_runtime_contract(html)

    assert report["ok"] is True
    assert not any(error["type"] == "empty_main_visual_mount" for error in report["errors"])


def test_widget_contract_rejects_unrelated_selector_constant_mount() -> None:
    from aetherviz_service.aetherviz.contracts.validation.widget_contract_checker import check_widget_runtime_contract

    html = sample_html().replace(
        '<svg viewBox="0 0 100 100"><circle id="dot" cx="20" cy="50" r="8"></circle></svg>',
        '<div data-role="main-visual"></div><div id="other"></div>',
    ).replace(
        "const state = { progress: 0 };",
        """const MOUNT_SELECTOR = '#other';
const mount = document.querySelector(MOUNT_SELECTOR);
const visual = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
mount.appendChild(visual);
const state = { progress: 0 };""",
    )

    report = check_widget_runtime_contract(html)

    assert report["ok"] is False
    assert any(error["type"] == "empty_main_visual_mount" for error in report["errors"])


def test_html_contract_dataset_rejects_mount_lookup_false_positive() -> None:
    """Offline dataset sample must not reintroduce empty_main_visual_mount false positives."""
    import json
    from pathlib import Path

    from aetherviz_service.aetherviz.contracts.validation.widget_contract_checker import check_widget_runtime_contract

    sample_path = (
        Path(__file__).resolve().parents[1]
        / "evals"
        / "datasets"
        / "html_contract"
        / "mount_lookup_false_positive.json"
    )
    sample = json.loads(sample_path.read_text(encoding="utf-8"))
    report = check_widget_runtime_contract(sample["html_fragment"])

    forbidden = set(sample["expected"]["must_not_contain_error_types"])
    assert not forbidden.intersection(error["type"] for error in report["errors"])
    assert report["ok"] is True or not any(
        error["type"] == "empty_main_visual_mount" for error in report["errors"]
    )


def test_widget_contract_accepts_query_selector_hash_mount_id() -> None:
    from aetherviz_service.aetherviz.contracts.validation.widget_contract_checker import check_widget_runtime_contract

    html = sample_html().replace(
        '<svg viewBox="0 0 100 100"><circle id="dot" cx="20" cy="50" r="8"></circle></svg>',
        '<div data-role="main-visual" id="main-visual-mount"></div>',
    ).replace(
        "const state = { progress: 0 };",
        "const state = { progress: 0 };\n"
        "const mount = document.querySelector('#main-visual-mount');\n"
        "const visual = document.createElement('canvas');\n"
        "mount.replaceChildren(visual);",
    )

    report = check_widget_runtime_contract(html)

    assert report["ok"] is True


def test_deterministic_can_address_skips_empty_main_visual_only() -> None:
    from aetherviz_service.aetherviz.contracts.repair.deterministic import deterministic_can_address

    assert deterministic_can_address(
        {"errors": [{"type": "empty_main_visual_mount"}], "warnings": []}
    ) is False
    assert deterministic_can_address(
        {"errors": [{"type": "missing_runtime_ready"}], "warnings": []}
    ) is True


def test_widget_contract_warns_about_hardcoded_formatter_step_and_raw_formula_state() -> None:
    from aetherviz_service.aetherviz.contracts.validation.widget_contract_checker import check_widget_runtime_contract

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
    from aetherviz_service.aetherviz.contracts.layout import assemble_layout_contract
    from aetherviz_service.aetherviz.contracts.validation.report import build_validation_report

    report = build_validation_report(assemble_layout_contract(sample_html(), sample_plan()))

    assert report["ok"] is True


def test_server_layout_contract_replaces_model_shell_and_is_idempotent() -> None:
    from bs4 import BeautifulSoup

    from aetherviz_service.aetherviz.contracts.layout import assemble_layout_contract

    raw = sample_html().replace("<body>", '<body><div class="model-grid">').replace(
        "</body>", "</div></body>"
    )
    once = assemble_layout_contract(raw, sample_plan("函数变化"))
    twice = assemble_layout_contract(once, sample_plan("函数变化"))
    parsed = BeautifulSoup(twice, "html.parser")

    assert parsed.select_one(".model-grid") is None
    assert len(parsed.select("#aetherviz-app-shell")) == 1
    assert len(parsed.select('[data-layout-slot="stage"]')) == 1
    assert len(parsed.select('[data-layout-slot="primary-controls"]')) == 1
    assert len(parsed.select('style[data-aetherviz-layout-contract="math-shell-v1"]')) == 1
    assert parsed.body["data-layout-contract"] == "math-shell-v1"


def test_extract_business_html_removes_server_shell_and_round_trips() -> None:
    from aetherviz_service.aetherviz.contracts.layout import (
        assemble_layout_contract,
        extract_business_html,
    )

    assembled = assemble_layout_contract(sample_html(), sample_plan())
    business = extract_business_html(assembled)
    round_tripped = assemble_layout_contract(business, sample_plan())

    assert len(business) < len(assembled)
    assert "data-aetherviz-layout-contract" not in business
    assert "data-aetherviz-animation-contract" not in business
    assert "function updateVisualization" in business
    assert "function updateVisualization" in round_tripped
    assert 'id="aetherviz-app-shell"' in round_tripped


def test_extract_business_html_round_trips_editable_shell_content() -> None:
    from bs4 import BeautifulSoup

    from aetherviz_service.aetherviz.contracts.layout import assemble_layout_contract, extract_business_html

    assembled = assemble_layout_contract(sample_html(), sample_plan("二次函数"))
    business = extract_business_html(assembled)
    parsed_business = BeautifulSoup(business, "html.parser")
    shell_content = parsed_business.select_one('[data-shell-content-edit="true"]')
    assert shell_content is not None
    shell_content["data-title"] = "重新设计的标题"
    shell_content["data-goal"] = "观察新的核心关系"
    first_objective = shell_content.select_one("li")
    assert first_objective is not None
    first_objective.string = "新的学习目标"

    edited = assemble_layout_contract(str(parsed_business), sample_plan("二次函数"))
    parsed_edited = BeautifulSoup(edited, "html.parser")
    assert parsed_edited.select_one(".av-title").get_text(strip=True) == "重新设计的标题"
    assert parsed_edited.select_one(".av-goal").get_text(strip=True) == "观察新的核心关系"
    assert parsed_edited.select_one(".av-objectives li").get_text(strip=True) == "新的学习目标"


def test_server_range_contract_owns_track_progress_and_touch_target() -> None:
    from bs4 import BeautifulSoup

    from aetherviz_service.aetherviz.contracts.layout import assemble_layout_contract

    source = sample_html().replace(
        '<button id="play-animation">播放</button>',
        '<input type="range" id="speed-slider" min="-5" max="5" value="0">'
        '<button id="play-animation">播放</button>',
    )
    assembled = assemble_layout_contract(source, sample_plan())
    parsed = BeautifulSoup(assembled, "html.parser")
    contract_css = parsed.select_one('style[data-aetherviz-layout-contract="math-shell-v1"]')

    assert contract_css is not None
    assert "--av-range-progress" in contract_css.get_text()
    assert "linear-gradient(to right" in contract_css.get_text()
    assert "input:not([type=\"range\"])" in contract_css.get_text()
    assert len(parsed.select('script[data-aetherviz-control-contract="range-v1"]')) == 1


def test_server_control_contract_provides_button_and_select_feedback() -> None:
    from bs4 import BeautifulSoup

    from aetherviz_service.aetherviz.contracts.layout import assemble_layout_contract

    source = sample_html().replace(
        '<button id="play-animation">播放</button>',
        '<button id="play-animation">播放</button>'
        '<label>速度<select id="animation-speed"><option>1×</option></select></label>',
    )
    parsed = BeautifulSoup(assemble_layout_contract(source, sample_plan()), "html.parser")
    contract_css = parsed.select_one('style[data-aetherviz-layout-contract="math-shell-v1"]')
    control_script = parsed.select_one('script[data-aetherviz-control-contract="range-v1"]')
    animation_script = parsed.select_one('script[data-aetherviz-animation-contract="controller-v1"]')

    assert contract_css is not None
    assert control_script is not None
    assert animation_script is not None
    css = contract_css.get_text()
    assert 'button:active' in css
    assert '#play-animation[aria-pressed="true"]' in css
    assert 'button.av-reset-confirm' in css
    assert 'select:focus-visible' in css
    assert 'appearance:none' in css
    assert "clamp(300px,30vw,380px)" in css
    assert "grid-template-rows:auto auto" in css
    assert ".control-label" in css
    assert "grid-template-rows:auto 44px" not in css
    assert "aetherviz:animation-state" in control_script.get_text()
    assert "emit('playing')" in animation_script.get_text()
    assert "emit('paused')" in animation_script.get_text()
    assert "emit('reset')" in animation_script.get_text()


def test_layout_contract_promotes_model_button_rows_and_caps_compact_stage_height() -> None:
    from bs4 import BeautifulSoup

    from aetherviz_service.aetherviz.contracts.layout import assemble_layout_contract

    source = sample_html().replace(
        '<button id="play-animation">播放</button>\n'
        '<button id="pause-animation">暂停</button>\n'
        '<button id="reset-animation">重置</button>',
        '<div data-region="controls"><div class="btn-row"><button id="play-animation">播放</button>'
        '<button id="pause-animation">暂停</button><button id="reset-animation">重置</button></div>'
        '<div class="btn-row"><button>0°</button><button>90°</button><button>180°</button></div></div>',
    )
    parsed = BeautifulSoup(assemble_layout_contract(source, sample_plan()), "html.parser")
    rows = parsed.select('.av-primary-controls [data-region="controls"] > .btn-row')
    contract_css = parsed.select_one('style[data-aetherviz-layout-contract="math-shell-v1"]')

    assert len(rows) == 2
    assert all("action-buttons" in row.get("class", []) for row in rows)
    assert contract_css is not None
    css = contract_css.get_text()
    assert "clamp(300px,56dvh,620px)" in css
    assert "grid-template-columns:minmax(0,1fr)" in css


def test_server_layout_contract_sanitizes_model_owned_layout_and_range_css() -> None:
    from bs4 import BeautifulSoup

    from aetherviz_service.aetherviz.contracts.layout import assemble_layout_contract

    source = sample_html().replace(
        "body{margin:0}",
        ":root{--topic-color:#123456;color:red}body{margin:0}"
        "#aetherviz-stage{min-height:500px}"
        '[data-region="controls"]{display:flex;flex-direction:column;height:500px}'
        'input[type="range"]{height:6px;flex:1}'
        'input[type="range"]::-webkit-slider-thumb{height:20px}'
        ".control-label{color:var(--topic-color)}",
    )
    parsed = BeautifulSoup(assemble_layout_contract(source, sample_plan()), "html.parser")
    business_css = parsed.select_one('style[data-aetherviz-business-style="true"]')
    contract_css = parsed.select_one('style[data-aetherviz-layout-contract="math-shell-v1"]')

    assert business_css is not None
    assert contract_css is not None
    css = business_css.get_text()
    assert "--topic-color:#123456" in css
    assert ".control-label" in css
    assert "body{" not in css
    assert "#aetherviz-stage{" not in css
    assert '[data-region="controls"]' not in css
    assert 'input[type="range"]' not in css
    assert "flex:0 0 44px" in contract_css.get_text()
    assert "minmax(260px,1fr)" in contract_css.get_text()


def test_server_layout_contract_sanitizes_owned_selector_after_css_comment() -> None:
    from bs4 import BeautifulSoup

    from aetherviz_service.aetherviz.contracts.layout import assemble_layout_contract

    source = sample_html().replace(
        "#aetherviz-stage{display:grid;place-items:center;min-height:240px}",
        "/* Main Stage Area */\n#aetherviz-stage{height:500px;display:flex}",
    )
    parsed = BeautifulSoup(assemble_layout_contract(source, sample_plan()), "html.parser")
    business_css = parsed.select_one('style[data-aetherviz-business-style="true"]')

    assert business_css is not None
    assert "#aetherviz-stage" not in business_css.get_text()
    assert "height:500px" not in business_css.get_text()


def test_server_layout_contract_preserves_custom_properties_after_css_comment() -> None:
    from bs4 import BeautifulSoup

    from aetherviz_service.aetherviz.contracts.layout import assemble_layout_contract

    source = sample_html().replace(
        "body{margin:0}",
        "/* Visual tokens */\n"
        ":root{--paper:#ffffff;--shape-fill:#3b82f6;"
        "/* shape outline */--shape-stroke:#1d4ed8;color:red}"
        "body{margin:0}"
        ".main-shape{fill:var(--shape-fill);stroke:var(--shape-stroke)}",
    )
    parsed = BeautifulSoup(assemble_layout_contract(source, sample_plan()), "html.parser")
    business_css = parsed.select_one('style[data-aetherviz-business-style="true"]')

    assert business_css is not None
    css = business_css.get_text()
    assert ":root{--paper:#ffffff;--shape-fill:#3b82f6;--shape-stroke:#1d4ed8;}" in css
    assert "color:red" not in css
    assert ".main-shape{fill:var(--shape-fill);stroke:var(--shape-stroke)}" in css


def test_server_animation_controller_precedes_business_scripts_and_replays() -> None:
    from bs4 import BeautifulSoup

    from aetherviz_service.aetherviz.contracts.layout import assemble_layout_contract

    parsed = BeautifulSoup(assemble_layout_contract(sample_html(), sample_plan()), "html.parser")
    scripts = parsed.body.find_all("script")
    controller_index = next(
        index for index, script in enumerate(scripts) if script.get("data-aetherviz-animation-contract") == "controller-v1"
    )
    business_index = next(index for index, script in enumerate(scripts) if "AetherVizRuntime" in script.get_text())
    controller_source = scripts[controller_index].get_text()

    assert controller_index < business_index
    assert "if(progress>=1)apply(0)" in controller_source
    assert "requestAnimationFrame(nativeFrame)" in controller_source
    assert "tween.timeScale(speed)" in controller_source


def test_layout_contract_checker_rejects_unassembled_model_html() -> None:
    from aetherviz_service.aetherviz.contracts.validation.layout_checker import check_layout_contract

    report = check_layout_contract("<!DOCTYPE html><html><body><div id='aetherviz-stage'></div></body></html>")

    assert report["ok"] is False
    assert {error["type"] for error in report["errors"]} >= {
        "missing_layout_contract",
        "missing_layout_shell",
    }


def test_widget_contract_warns_about_call_only_gsap_timeline() -> None:
    from aetherviz_service.aetherviz.contracts.validation.widget_contract_checker import check_widget_runtime_contract

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
    from aetherviz_service.aetherviz.contracts.validation.widget_contract_checker import check_widget_runtime_contract

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
    from aetherviz_service.aetherviz.contracts.repair import model as repair_agent
    from aetherviz_service.aetherviz.contracts.repair.model import RepairStreamResult
    from aetherviz_service.aetherviz.generate import html_agent
    from aetherviz_service.aetherviz.generate.html_agent import HtmlStreamResult, build_html_progress_payload

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
    from aetherviz_service.aetherviz.contracts import pipeline as generate_workflow
    from aetherviz_service.aetherviz.generate import workflow as _generate_entry

    monkeypatch.setattr(_generate_entry, "stream_generate_html", fake_stream)
    monkeypatch.setattr(generate_workflow, "stream_generate_html", fake_stream, raising=False)
    monkeypatch.setattr(generate_workflow, "stream_repair_html", fake_repair_stream, raising=False)

    response = client.post(
        AETHERVIZ_ENDPOINT,
        json={"topic": "熵增演示", "phase": "generate", "approved_plan": sample_plan()},
    )

    events = parse_sse_events(response)
    names = [event for event, _ in events]
    assert "repair.started" in names
    assert "repair.done" in names
    assert "html.done" in names
    repair_size_events = [
        data["data"]
        for event, data in events
        if event == "html.delta" and data["data"].get("bytes") and data["metadata"].get("stage") == "repair"
    ]
    repair_done = [data for event, data in events if event == "repair.done"][-1]
    done = next(data for event, data in events if event == "html.done")
    assert repair_size_events[-1]["bytes"] == done["data"]["metadata"]["bytes"]
    assert repair_size_events[-1]["chars"] == done["data"]["metadata"]["chars"]
    assert repair_done["data"]["bytes"] == done["data"]["metadata"]["bytes"]
    assert repair_done["data"]["chars"] == done["data"]["metadata"]["chars"]
    assert done["data"]["metadata"]["repaired"] is True
    assert done["data"]["metadata"]["attempts"] >= 2


def test_generate_phase_skips_deterministic_when_only_model_fixable_errors(monkeypatch) -> None:
    """empty_main_visual_mount alone must not burn a deterministic repair attempt."""
    from aetherviz_service.aetherviz.contracts import pipeline as generate_workflow
    from aetherviz_service.aetherviz.contracts.repair.model import RepairStreamResult
    from aetherviz_service.aetherviz.generate import workflow as _generate_entry
    from aetherviz_service.aetherviz.generate.html_agent import HtmlStreamResult

    empty_mount = sample_html().replace(
        '<svg viewBox="0 0 100 100"><circle id="dot" cx="20" cy="50" r="8"></circle></svg>',
        '<div data-role="main-visual" id="main-visual-mount"></div>',
    )
    fixed = sample_html().replace(
        '<svg viewBox="0 0 100 100"><circle id="dot" cx="20" cy="50" r="8"></circle></svg>',
        '<div data-role="main-visual" id="main-visual-mount"></div>',
    ).replace(
        "const state = { progress: 0 };",
        "const MOUNT_ID = 'main-visual-mount';\n"
        "const els = { mount: document.getElementById(MOUNT_ID) };\n"
        "svgRoot = document.createElementNS('http://www.w3.org/2000/svg', 'svg');\n"
        "els.mount.appendChild(svgRoot);\n"
        "const state = { progress: 0 };",
    )
    deterministic_calls = 0

    def fake_stream(topic, plan):
        yield HtmlStreamResult(html=empty_mount, degraded=False)

    def fake_repair_stream(**kwargs):
        yield RepairStreamResult(html=fixed, degraded=False)

    original_run = generate_workflow._run_deterministic_repair

    def counting_run(html, report, plan):
        nonlocal deterministic_calls
        deterministic_calls += 1
        return original_run(html, report, plan)

    monkeypatch.setattr(settings, "aetherviz_max_repair_attempts", 1)
    monkeypatch.setattr(_generate_entry, "stream_generate_html", fake_stream)
    monkeypatch.setattr(generate_workflow, "stream_generate_html", fake_stream, raising=False)
    monkeypatch.setattr(generate_workflow, "stream_repair_html", fake_repair_stream, raising=False)
    monkeypatch.setattr(generate_workflow, "_run_deterministic_repair", counting_run)

    response = client.post(
        AETHERVIZ_ENDPOINT,
        json={"topic": "割圆法", "phase": "generate", "approved_plan": sample_plan("割圆法")},
    )
    events = parse_sse_events(response)
    strategies = [
        data["data"].get("strategy")
        for event, data in events
        if event == "repair.started"
    ]

    assert "deterministic" not in strategies
    assert deterministic_calls == 0
    assert any(event == "html.done" for event, _ in events)


def test_generate_phase_rejects_stalled_model_repair_and_preserves_previous_html(monkeypatch) -> None:
    from aetherviz_service.aetherviz.contracts import pipeline as generate_workflow
    from aetherviz_service.aetherviz.contracts.repair.model import RepairStreamResult
    from aetherviz_service.aetherviz.generate import workflow as _generate_entry
    from aetherviz_service.aetherviz.generate.html_agent import HtmlStreamResult

    missing_visual = sample_html().replace(
        '<svg viewBox="0 0 100 100"><circle id="dot" cx="20" cy="50" r="8"></circle></svg>',
        "",
    )
    unrelated_candidate = missing_visual.replace(
        '<main id="aetherviz-stage">',
        '<main id="aetherviz-stage" data-unrelated="changed">',
    )
    repair_calls = 0
    repair_source = ""

    def fake_stream(topic, plan):
        yield HtmlStreamResult(html=missing_visual, degraded=False)

    def fake_repair_stream(**kwargs):
        nonlocal repair_calls, repair_source
        repair_calls += 1
        repair_source = kwargs["raw_html"]
        yield RepairStreamResult(html=unrelated_candidate, degraded=False)

    monkeypatch.setattr(settings, "aetherviz_max_repair_attempts", 1)
    monkeypatch.setattr(_generate_entry, "stream_generate_html", fake_stream)
    monkeypatch.setattr(generate_workflow, "stream_generate_html", fake_stream, raising=False)
    monkeypatch.setattr(generate_workflow, "stream_repair_html", fake_repair_stream, raising=False)

    response = client.post(
        AETHERVIZ_ENDPOINT,
        json={"topic": "变量变化", "phase": "generate", "approved_plan": sample_plan("变量变化")},
    )

    events = parse_sse_events(response)
    model_done = next(
        data
        for event, data in events
        if event == "repair.done" and data["data"].get("strategy") == "model"
    )
    error = next(data for event, data in events if event == "error")
    repair_source_event = next(data for event, data in events if event == "html.repair_source")

    assert repair_calls == 1
    assert model_done["data"]["accepted"] is False
    assert model_done["data"]["stalled"] is True
    assert model_done["data"]["remaining_error_types"] == ["missing_stage_visual"]
    assert model_done["data"]["model_chars"] == len(repair_source)
    assert model_done["data"]["chars"] > model_done["data"]["model_chars"]
    assert error["data"]["code"] == "validation_failed"
    assert repair_source_event["data"]["renderable"] is False
    assert repair_source_event["data"]["html"].startswith("<!DOCTYPE html>")
    assert repair_source_event["data"]["report"]["ok"] is False
    assert [event for event, _ in events].index("html.repair_source") < [event for event, _ in events].index("error")
    assert not any(event == "html.done" for event, _ in events)


def test_generate_phase_honors_multiple_model_repair_attempts(monkeypatch) -> None:
    from aetherviz_service.aetherviz.contracts import pipeline as generate_workflow
    from aetherviz_service.aetherviz.contracts.repair.model import RepairStreamResult
    from aetherviz_service.aetherviz.generate import workflow as _generate_entry
    from aetherviz_service.aetherviz.generate.html_agent import HtmlStreamResult

    complete = sample_html()
    missing_visual = complete.replace(
        '<svg viewBox="0 0 100 100"><circle id="dot" cx="20" cy="50" r="8"></circle></svg>',
        "",
    )
    baseline = missing_visual.replace("window.__AETHERVIZ_RUNTIME_READY__ = true;", "")
    first_candidate = missing_visual
    repair_calls = 0

    def fake_stream(topic, plan):
        yield HtmlStreamResult(html=baseline, degraded=False)

    def fake_repair_stream(**kwargs):
        nonlocal repair_calls
        repair_calls += 1
        yield RepairStreamResult(html=first_candidate if repair_calls == 1 else complete, degraded=False)

    monkeypatch.setattr(settings, "aetherviz_max_repair_attempts", 2)
    monkeypatch.setattr(_generate_entry, "stream_generate_html", fake_stream)
    monkeypatch.setattr(generate_workflow, "stream_generate_html", fake_stream, raising=False)
    monkeypatch.setattr(generate_workflow, "stream_repair_html", fake_repair_stream, raising=False)
    monkeypatch.setattr(generate_workflow, "deterministic_can_address", lambda report: False)

    response = client.post(
        AETHERVIZ_ENDPOINT,
        json={"topic": "变量变化", "phase": "generate", "approved_plan": sample_plan("变量变化")},
    )
    events = parse_sse_events(response)

    assert repair_calls == 2
    assert any(event == "html.done" for event, _ in events)


def test_generate_phase_marks_unchanged_model_repair(monkeypatch) -> None:
    from aetherviz_service.aetherviz.contracts import pipeline as generate_workflow
    from aetherviz_service.aetherviz.contracts.repair.model import RepairStreamResult
    from aetherviz_service.aetherviz.generate import workflow as _generate_entry
    from aetherviz_service.aetherviz.generate.html_agent import HtmlStreamResult

    missing_visual = sample_html().replace(
        '<svg viewBox="0 0 100 100"><circle id="dot" cx="20" cy="50" r="8"></circle></svg>',
        "",
    )

    def fake_stream(topic, plan):
        yield HtmlStreamResult(html=missing_visual, degraded=False)

    def fake_repair_stream(**kwargs):
        yield RepairStreamResult(html=kwargs["raw_html"], degraded=False)

    monkeypatch.setattr(settings, "aetherviz_max_repair_attempts", 1)
    monkeypatch.setattr(_generate_entry, "stream_generate_html", fake_stream)
    monkeypatch.setattr(generate_workflow, "stream_generate_html", fake_stream, raising=False)
    monkeypatch.setattr(generate_workflow, "stream_repair_html", fake_repair_stream, raising=False)

    response = client.post(
        AETHERVIZ_ENDPOINT,
        json={"topic": "变量变化", "phase": "generate", "approved_plan": sample_plan("变量变化")},
    )

    events = parse_sse_events(response)
    model_done = next(
        data
        for event, data in events
        if event == "repair.done" and data["data"].get("strategy") == "model"
    )

    assert model_done["data"]["accepted"] is False
    assert model_done["data"]["stalled"] is True
    assert model_done["data"]["rejection_reason"] == "unchanged_candidate"


def test_generate_phase_does_not_model_rewrite_quality_warning(monkeypatch) -> None:
    from aetherviz_service.aetherviz.contracts import pipeline as generate_workflow
    from aetherviz_service.aetherviz.generate import workflow as _generate_entry
    from aetherviz_service.aetherviz.generate.html_agent import HtmlStreamResult

    risky_html = sample_html().replace(
        "const state = { progress: 0 };",
        "const state = { progress: 0 }; label.textContent = `value=${state.progress}`;",
    )

    def fake_stream(topic, plan):
        yield HtmlStreamResult(html=risky_html, degraded=False)

    monkeypatch.setattr(settings, "aetherviz_max_repair_attempts", 1)
    monkeypatch.setattr(_generate_entry, "stream_generate_html", fake_stream)
    monkeypatch.setattr(generate_workflow, "stream_generate_html", fake_stream, raising=False)
    monkeypatch.setattr(
        generate_workflow,
        "stream_repair_html",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("warning 不应触发模型重写")),
    )

    response = client.post(
        AETHERVIZ_ENDPOINT,
        json={"topic": "变量变化", "phase": "generate", "approved_plan": sample_plan("变量变化")},
    )

    events = parse_sse_events(response)
    done = next(data for event, data in events if event == "html.done")

    assert 'data-layout-contract="math-shell-v1"' in done["data"]["html"]
    assert "label.textContent = `value=${state.progress}`" in done["data"]["html"]
    assert done["data"]["metadata"]["repaired"] is False
    assert done["data"]["metadata"]["validation_warnings"]


def test_generate_phase_runs_quality_repair_after_hard_error_is_repaired(monkeypatch) -> None:
    from aetherviz_service.aetherviz.contracts import pipeline as generate_workflow
    from aetherviz_service.aetherviz.generate import workflow as _generate_entry
    from aetherviz_service.aetherviz.generate.html_agent import HtmlStreamResult

    risky_html = sample_html().replace(
        "body{margin:0}",
        ".app-shell{display:grid;grid-template-columns:1fr 320px}body{margin:0}"
        ".axis-line{stroke:#333;stroke-width:1.5}.label-text{font-size:12px}",
    ).replace(
        '<svg viewBox="0 0 100 100">',
        '<svg viewBox="-6 -6 12 12"><line class="axis-line"></line><text class="label-text">x</text>',
    ).replace(
        '<button id="play-animation">播放</button>',
        '<button id="play-animation" onclick="window.AetherVizRuntime.play()">播放</button>',
    )

    def fake_stream(topic, plan):
        yield HtmlStreamResult(html=risky_html, degraded=False)

    monkeypatch.setattr(settings, "aetherviz_max_repair_attempts", 1)
    monkeypatch.setattr(_generate_entry, "stream_generate_html", fake_stream)
    monkeypatch.setattr(generate_workflow, "stream_generate_html", fake_stream, raising=False)

    response = client.post(
        AETHERVIZ_ENDPOINT,
        json={"topic": "变量变化", "phase": "generate", "approved_plan": sample_plan("变量变化")},
    )
    events = parse_sse_events(response)
    strategies = [
        data["data"].get("strategy")
        for event, data in events
        if event == "repair.done"
    ]
    done = next(data for event, data in events if event == "html.done")

    assert strategies == ["deterministic"]
    assert 'data-aetherviz-scale-guard="2"' in done["data"]["html"]


def test_edit_phase_applies_deterministic_quality_repair_without_model_rewrite(monkeypatch) -> None:
    from aetherviz_service.aetherviz.contracts import pipeline as generate_workflow
    from aetherviz_service.aetherviz.generate.html_agent import HtmlStreamResult

    risky_html = sample_html().replace(
        "body{margin:0}",
        "body{margin:0}.axis-line{stroke:#333;stroke-width:1.5}.label-text{font-size:12px}",
    ).replace(
        '<svg viewBox="0 0 100 100">',
        '<svg viewBox="-6 -6 12 12"><line class="axis-line"></line>'
        '<text class="label-text">x</text>',
    )

    def fail_model_repair(**kwargs):
        raise AssertionError(f"edit warning 不应触发模型重写: {kwargs}")

    monkeypatch.setattr(settings, "aetherviz_max_repair_attempts", 1)
    monkeypatch.setattr(generate_workflow, "stream_repair_html", fail_model_repair, raising=False)
    raw_events = list(
        generate_workflow.run_html_pipeline(
            run_id="run-edit-quality",
            phase="edit_html",
            start_event="html.edit_started",
            topic="变量变化",
            plan=sample_plan("变量变化"),
            html_stream_factory=lambda: iter([HtmlStreamResult(html=risky_html, degraded=False)]),
        )
    )
    response = type("SseResponse", (), {"text": "".join(raw_events)})()
    events = parse_sse_events(response)
    strategies = [
        data["data"].get("strategy")
        for event, data in events
        if event == "repair.done"
    ]
    done = next(data for event, data in events if event == "html.done")

    assert strategies == ["deterministic"]
    assert 'data-aetherviz-scale-guard="2"' in done["data"]["html"]


def test_edit_html_stream_propagates_generator_exit(monkeypatch) -> None:
    from unittest.mock import MagicMock

    from aetherviz_service.aetherviz.edit import workflow as edit_html_workflow

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
            )
        )


def test_edit_html_always_regenerates_full_html_from_current_page(monkeypatch) -> None:
    from unittest.mock import MagicMock

    from aetherviz_service.aetherviz.edit import workflow as edit_html_workflow
    from aetherviz_service.aetherviz.generate.html_agent import HtmlStreamResult

    source = sample_html()
    regenerated = source.replace("<title>熵增演示</title>", "<title>重新生成的熵增演示</title>")

    class RegenerationModel:
        def stream(self, messages):
            assert source in messages[1].content
            yield MagicMock(content=regenerated, response_metadata={"finish_reason": "stop"})

    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(edit_html_workflow, "create_chat_model", lambda kind: RegenerationModel())

    result = next(
        item
        for item in edit_html_workflow._stream_edit_html(
            topic="动画", message="点击播放没反应", current_html=source
        )
        if isinstance(item, HtmlStreamResult)
    )

    assert result.strategy == "full_html_regeneration"
    assert result.patch_functions == ()
    assert "重新生成的熵增演示" in result.html


def test_edit_workflow_diagnoses_before_passing_current_business_html_to_regeneration(monkeypatch) -> None:
    from aetherviz_service.aetherviz.edit import workflow as edit_html_workflow
    from aetherviz_service.aetherviz.generate.html_agent import HtmlStreamResult

    captured: dict[str, object] = {}

    def fake_stream_edit_html(**kwargs):
        captured.update(kwargs)
        yield HtmlStreamResult(html=kwargs["current_html"], degraded=False)

    def fake_run_html_pipeline(**kwargs):
        list(kwargs["html_stream_factory"]())
        yield "done"

    monkeypatch.setattr(edit_html_workflow, "_stream_edit_html", fake_stream_edit_html)
    monkeypatch.setattr(edit_html_workflow, "run_html_pipeline", fake_run_html_pipeline)

    result = list(
        edit_html_workflow._run_edit_html_workflow_impl(
            run_id="run-edit-targeting",
            current_html=sample_html(),
            message="修复画面",
            context={"topic": "动画"},
        )
    )

    assert result[-1] == "done"
    events = parse_sse_events(type("SseResponse", (), {"text": "".join(result[:-1])})())
    assert [event for event, _data in events] == ["html.edit_started", "html.edit_diagnosed"]
    assert "原始用户输入（用于核对，不得覆盖已编译任务）：修复画面" in str(captured["message"])
    assert "已编译编辑任务（主要执行指令）" in str(captured["message"])
    assert "不要把 selector 或函数名当作修改边界" in str(captured["message"])
    assert "context" not in captured


def test_full_html_edit_retries_intent_failure_with_evidence(monkeypatch) -> None:
    from aetherviz_service.aetherviz.edit import workflow as edit_html_workflow
    from aetherviz_service.aetherviz.generate.html_agent import HtmlGenerationError, HtmlStreamResult

    calls: list[dict[str, object]] = []

    def fake_stream_edit_html(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise HtmlGenerationError(
                "HTML 修改结果未满足本次编辑验收条件，原页面已保留",
                code="edit_intent_not_satisfied",
                detail="上一轮完整编辑未通过意图验收：\n- [id=c1 kind=html_must_differ group=change] html_unchanged",
            )
        yield HtmlStreamResult(
            html=kwargs["current_html"].replace("</body>", "<p>已修改</p></body>"),
            degraded=False,
            strategy="full_html_regeneration",
            intent_passed=True,
            intent_check_count=1,
        )

    monkeypatch.setattr(settings, "aetherviz_edit_max_retries", 1)
    monkeypatch.setattr(edit_html_workflow, "_stream_edit_html", fake_stream_edit_html)

    items = list(
        edit_html_workflow._stream_full_html_edit(
            topic="动画",
            message="改变运动轨迹",
            current_html=sample_html(),
        )
    )

    result = next(item for item in items if isinstance(item, HtmlStreamResult))
    assert len(calls) == 2
    assert calls[0]["current_html"] == calls[1]["current_html"]
    assert "上一轮完整编辑未被接受：edit_intent_not_satisfied" in str(calls[1]["message"])
    assert "id=c1" in str(calls[1]["message"])
    assert "已修改" in result.html


def test_edit_html_rejects_truncated_full_output_without_partial_repair(monkeypatch) -> None:
    from unittest.mock import MagicMock

    from aetherviz_service.aetherviz.edit import workflow as edit_html_workflow
    from aetherviz_service.aetherviz.generate.html_agent import HtmlGenerationError

    class TruncatedModel:
        def stream(self, messages):
            yield MagicMock(
                content="<!DOCTYPE html><html><body><script>function loop(){",
                response_metadata={"finish_reason": "length"},
            )

    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(edit_html_workflow, "create_chat_model", lambda kind: TruncatedModel())

    with pytest.raises(HtmlGenerationError) as exc_info:
        list(
            edit_html_workflow._stream_edit_html(
                topic="动画", message="修改说明文字", current_html=sample_html()
            )
        )

    assert exc_info.value.code == "edit_truncated"
    assert "原页面已保留" in exc_info.value.message


def test_edit_html_reports_full_html_regeneration_strategy(monkeypatch) -> None:
    from unittest.mock import MagicMock

    from aetherviz_service.aetherviz.edit import workflow as edit_html_workflow
    from aetherviz_service.aetherviz.generate.html_agent import HtmlStreamResult

    source = sample_html()
    edited = source.replace("<title>熵增演示</title>", "<title>已完整编辑</title>")

    class FullEditModel:
        def stream(self, messages):
            yield MagicMock(content=edited, response_metadata={"finish_reason": "stop"})

    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(edit_html_workflow, "create_chat_model", lambda kind: FullEditModel())

    items = list(
        edit_html_workflow._stream_edit_html(
            topic="动画",
            message="修改 #stage 的颜色",
            current_html=source,
        )
    )
    result = next(item for item in items if isinstance(item, HtmlStreamResult))

    assert result.strategy == "full_html_regeneration"
    assert "<title>已完整编辑</title>" in result.html
    assert any("重新生成完整 HTML" in str(item) for item in items if isinstance(item, dict))


def test_edit_html_rejects_unchanged_regeneration(monkeypatch) -> None:
    from unittest.mock import MagicMock

    from aetherviz_service.aetherviz.edit import workflow as edit_html_workflow
    from aetherviz_service.aetherviz.generate.html_agent import HtmlGenerationError

    class UnchangedModel:
        def stream(self, messages):
            yield MagicMock(content=sample_html(), response_metadata={"finish_reason": "stop"})

    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(edit_html_workflow, "create_chat_model", lambda kind: UnchangedModel())

    with pytest.raises(HtmlGenerationError) as exc_info:
        list(
            edit_html_workflow._stream_edit_html(
                topic="动画", message="把按钮改大", current_html=sample_html()
            )
        )

    assert exc_info.value.code == "edit_intent_not_satisfied"
    assert "html_must_differ" in exc_info.value.detail or "html_unchanged" in exc_info.value.detail


def test_edit_html_layout_wording_reaches_model_instead_of_keyword_rejection(monkeypatch) -> None:
    from unittest.mock import MagicMock

    from aetherviz_service.aetherviz.edit import workflow as edit_html_workflow
    from aetherviz_service.aetherviz.generate.html_agent import HtmlStreamResult

    source = sample_html()
    edited = source.replace("<title>熵增演示</title>", "<title>布局意图已处理</title>")

    class FullEditModel:
        def stream(self, messages):
            assert "实验控制的动画演示标题被挤压，请优化布局" in messages[1].content
            yield MagicMock(content=edited, response_metadata={"finish_reason": "stop"})

    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(edit_html_workflow, "create_chat_model", lambda kind: FullEditModel())

    items = list(
        edit_html_workflow._stream_edit_html_impl(
            topic="动画",
            message="实验控制的动画演示标题被挤压，请优化布局",
            current_html=source,
        )
    )

    result = next(item for item in items if isinstance(item, HtmlStreamResult))
    assert "布局意图已处理" in result.html


def test_edit_html_requires_model_configuration(monkeypatch) -> None:
    from aetherviz_service.aetherviz.edit import workflow as edit_html_workflow
    from aetherviz_service.aetherviz.generate.html_agent import HtmlGenerationError

    monkeypatch.setattr(settings, "openai_api_key", "")

    with pytest.raises(HtmlGenerationError) as exc_info:
        list(
            edit_html_workflow._stream_edit_html(
                topic="动画", message="把按钮改大", current_html=sample_html()
            )
        )

    assert exc_info.value.code == "model_unavailable"


def test_edit_html_preserves_widget_type_and_actions() -> None:
    from aetherviz_service.aetherviz.edit.workflow import _edit_contract_errors

    source = sample_html().replace(
        "window.addEventListener('message', handleMessage);",
        "window.addEventListener('message', handleMessage); // SET_WIDGET_STATE HIGHLIGHT_ELEMENT",
    )
    candidate = source.replace('"type":"simulation"', '"type":"diagram"').replace(
        "HIGHLIGHT_ELEMENT", ""
    )

    errors = _edit_contract_errors(source, candidate)

    assert "widget_type_changed:simulation->diagram" in errors
    assert "widget_actions_missing:HIGHLIGHT_ELEMENT" in errors


def test_repair_stream_propagates_generator_exit(monkeypatch) -> None:
    from unittest.mock import MagicMock

    from aetherviz_service.aetherviz.contracts.repair import model as repair_agent

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
    from aetherviz_service.aetherviz.contracts.validation.widget_contract_checker import check_widget_runtime_contract

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
    from aetherviz_service.aetherviz.contracts.validation.widget_contract_checker import check_widget_runtime_contract

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
    from aetherviz_service.aetherviz.contracts.validation.widget_contract_checker import check_widget_runtime_contract

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
        DIAGRAM_SYSTEM_PROMPT,
        EDIT_HTML_SYSTEM_PROMPT,
        GAME_SYSTEM_PROMPT,
        GRAPHICS_CRAFT_PROMPT,
        NUMERIC_PRESENTATION_PROMPT,
        SERVER_LAYOUT_CONTRACT_PROMPT,
        SIMULATION_SYSTEM_PROMPT,
        STAGE_CENTERING_AND_LABEL_PROMPT,
        VISUAL_DESIGN_SYSTEM_PROMPT,
    )

    shared_rule_marker = STAGE_CENTERING_AND_LABEL_PROMPT.strip().splitlines()[-1]
    # Generation prompts keep full delivery rules.
    assert shared_rule_marker in SIMULATION_SYSTEM_PROMPT
    assert "viewBox" in SIMULATION_SYSTEM_PROMPT
    assert "页面排版 token" in SIMULATION_SYSTEM_PROMPT
    assert "getScreenCTM()" in SIMULATION_SYSTEM_PROMPT
    assert "getBoundingClientRect" in SIMULATION_SYSTEM_PROMPT
    assert SERVER_LAYOUT_CONTRACT_PROMPT.strip().splitlines()[-1] in SIMULATION_SYSTEM_PROMPT
    assert VISUAL_DESIGN_SYSTEM_PROMPT.strip().splitlines()[-1] in SIMULATION_SYSTEM_PROMPT
    assert "清爽教学工作台" in SIMULATION_SYSTEM_PROMPT
    assert "#2d4f41" in SIMULATION_SYSTEM_PROMPT
    assert NUMERIC_PRESENTATION_PROMPT.strip().splitlines()[-1] in SIMULATION_SYSTEM_PROMPT
    assert GRAPHICS_CRAFT_PROMPT.strip().splitlines()[-1] in SIMULATION_SYSTEM_PROMPT
    assert "连续计算状态与可见展示状态必须分离" in SIMULATION_SYSTEM_PROMPT
    assert "AetherVizAnimationController.create" in SIMULATION_SYSTEM_PROMPT

    # Edit prompts are HTML-baseline only and must not re-inject generation delivery fragments.
    assert shared_rule_marker not in EDIT_HTML_SYSTEM_PROMPT
    assert "清爽教学工作台" not in EDIT_HTML_SYSTEM_PROMPT
    assert "服务端布局契约" not in EDIT_HTML_SYSTEM_PROMPT
    assert "唯一事实基线" in EDIT_HTML_SYSTEM_PROMPT

    assert "浅色实验舞台" in SIMULATION_SYSTEM_PROMPT
    assert "widget-config.variables[].default" in SIMULATION_SYSTEM_PROMPT
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
    from aetherviz_service.aetherviz.contracts.validation.widget_contract_checker import check_widget_runtime_contract

    html = sample_html().replace(
        "body{margin:0}",
        ".app-shell{display:grid;grid-template-columns:280px 1fr 280px}body{margin:0}",
    )

    report = check_widget_runtime_contract(html)
    warning_types = {warning["type"] for warning in report["warnings"]}

    assert "fixed_sidebar_layout" in warning_types
    assert "missing_stage_shrink_guard" in warning_types
    assert report["ok"] is True


def test_widget_contract_warns_about_mixed_abstract_svg_units() -> None:
    from aetherviz_service.aetherviz.contracts.validation.widget_contract_checker import check_widget_runtime_contract

    html = sample_html().replace(
        "body{margin:0}",
        "body{margin:0}.axis-line{stroke:#333;stroke-width:1.5}.label-text{font-size:12px}",
    ).replace(
        '<svg viewBox="0 0 100 100">',
        '<svg viewBox="-6 -6 12 12"><line class="axis-line" x1="-6" y1="0" x2="6" y2="0"></line>'
        '<text class="label-text">x</text>',
    )
    from aetherviz_service.aetherviz.contracts.layout import assemble_layout_contract

    html = assemble_layout_contract(html, sample_plan())

    report = check_widget_runtime_contract(html)
    warning_types = {warning["type"] for warning in report["warnings"]}

    assert {"abstract_svg_text_scale_risk", "abstract_svg_stroke_scale_risk", "mixed_svg_unit_system"} <= warning_types
    assert report["ok"] is False
    assert any(error["type"] == "unsafe_abstract_svg_units" for error in report["errors"])


def test_svg_scale_guard_marker_alone_cannot_bypass_unit_validation() -> None:
    from aetherviz_service.aetherviz.contracts.validation.widget_contract_checker import check_widget_runtime_contract

    html = sample_html().replace(
        "body{margin:0}",
        "body{margin:0}.axis-line{stroke:#333;stroke-width:1.5}.label-text{font-size:12px}",
    ).replace(
        '<svg viewBox="0 0 100 100">',
        '<svg viewBox="-6 -6 12 12"><line class="axis-line"></line><text class="label-text">x</text>',
    ).replace("</body>", '<script data-aetherviz-scale-guard="true"></script></body>')

    report = check_widget_runtime_contract(html)
    warning_types = {warning["type"] for warning in report["warnings"]}

    assert report["ok"] is False
    assert "invalid_svg_scale_guard" in warning_types
    assert any(error["type"] == "unsafe_abstract_svg_units" for error in report["errors"])


def test_deterministic_quality_repair_adds_generic_svg_guard_under_server_layout() -> None:
    from aetherviz_service.aetherviz.contracts.repair.deterministic import deterministic_repair_html
    from aetherviz_service.aetherviz.contracts.validation.report import build_validation_report

    html = sample_html().replace(
        "body{margin:0}",
        ".app-shell{display:grid;grid-template-columns:1fr 320px}body{margin:0}"
        ".axis-line{stroke:#333;stroke-width:1.5}.label-text{font-size:12px}",
    ).replace(
        '<svg viewBox="0 0 100 100">',
        '<svg viewBox="-6 -6 12 12"><line class="axis-line"></line><text class="label-text">x</text>',
    )
    from aetherviz_service.aetherviz.contracts.layout import assemble_layout_contract

    html = assemble_layout_contract(html, sample_plan())
    report = build_validation_report(html)
    repaired = deterministic_repair_html(html, report)
    repaired_report = build_validation_report(repaired)
    warning_types = {warning["type"] for warning in repaired_report["warnings"]}

    assert 'data-aetherviz-scale-guard="2"' in repaired
    assert 'data-aetherviz-layout-contract="math-shell-v1"' in repaired
    assert 'data-aetherviz-layout-guard="true"' not in repaired
    assert "abstract_svg_text_scale_risk" not in warning_types
    assert "abstract_svg_stroke_scale_risk" not in warning_types
    assert "missing_stage_shrink_guard" not in warning_types
    assert "unguarded_resize_viewbox_write" not in warning_types
    assert "target=authoredNumber" in repaired
    assert "target=authored*scale" not in repaired
    assert "setProperty('font-size',(target/scale)+'px','important')" in repaired
    assert "aethervizScreenStroke" in repaired


def test_discipline_checker_accepts_runtime_svg_mounted_in_stage() -> None:
    from aetherviz_service.aetherviz.contracts.validation.discipline_consistency_checker import (
        check_discipline_consistency,
    )

    html = sample_html().replace(
        '<svg viewBox="0 0 100 100"><circle id="dot" cx="20" cy="50" r="8"></circle></svg>',
        '<div data-role="main-visual"></div>',
    ).replace(
        "function updateVisualization(){",
        "const mount=document.querySelector('[data-role=\"main-visual\"]');"
        "const runtimeSvg=document.createElementNS('http://www.w3.org/2000/svg','svg');"
        "mount.appendChild(runtimeSvg);function updateVisualization(){",
    )
    report = check_discipline_consistency(
        html,
        plan={
            "knowledge_profile": {"representation_type": "coordinate_graph"},
            "discipline_spec": {"entities": ["变量"]},
        },
    )

    assert not any(warning["type"] == "representation_mismatch" for warning in report["warnings"])


def test_widget_contract_accepts_static_viewbox_for_attribute_only_redraw() -> None:
    """Attribute-only updates stay within a designable envelope: static viewBox is preferred."""
    from aetherviz_service.aetherviz.contracts.validation.widget_contract_checker import check_widget_runtime_contract

    html = sample_html().replace(
        '<button id="play-animation">播放</button>',
        '<input type="range" id="parameter-slider"><button id="play-animation">播放</button>',
    ).replace(
        "function updateVisualization(){",
        "function updateVisualization(){ dot.setAttribute('x', state.progress);",
    )

    report = check_widget_runtime_contract(html)

    assert not any(warning["type"] == "static_viewbox_for_variable_svg" for warning in report["warnings"])
    assert report["ok"] is True


def test_widget_contract_warns_when_static_geometry_is_mostly_outside_viewbox() -> None:
    from aetherviz_service.aetherviz.contracts.validation.widget_contract_checker import check_widget_runtime_contract

    html = sample_html().replace(
        '<svg viewBox="0 0 100 100"><circle id="dot" cx="20" cy="50" r="8"></circle></svg>',
        '<svg viewBox="0 0 800 450"><g id="visual-root">'
        '<circle id="dot" cx="0" cy="0" r="150"></circle>'
        '<line x1="-150" y1="0" x2="150" y2="0"></line></g></svg>',
    )

    report = check_widget_runtime_contract(html)

    assert any(warning["type"] == "svg_visual_center_mismatch" for warning in report["warnings"])


def test_widget_contract_accepts_centered_static_geometry_viewbox() -> None:
    from aetherviz_service.aetherviz.contracts.validation.widget_contract_checker import check_widget_runtime_contract

    html = sample_html().replace(
        '<svg viewBox="0 0 100 100"><circle id="dot" cx="20" cy="50" r="8"></circle></svg>',
        '<svg viewBox="-200 -200 400 400"><g id="visual-root">'
        '<circle id="dot" cx="0" cy="0" r="150"></circle>'
        '<line x1="-150" y1="0" x2="150" y2="0"></line></g></svg>',
    )

    report = check_widget_runtime_contract(html)

    assert not any(warning["type"] == "svg_visual_center_mismatch" for warning in report["warnings"])


def test_widget_contract_does_not_treat_dynamic_text_labels_as_unknown_geometry() -> None:
    from aetherviz_service.aetherviz.contracts.validation.widget_contract_checker import check_widget_runtime_contract

    html = sample_html().replace(
        '<button id="play-animation">播放</button>',
        '<input type="range" id="parameter-slider"><button id="play-animation">播放</button>',
    ).replace(
        "function updateVisualization(){",
        "function updateVisualization(){ "
        "const label = document.createElementNS('http://www.w3.org/2000/svg', 'text'); "
        "document.querySelector('svg').appendChild(label);",
    )

    report = check_widget_runtime_contract(html)

    assert not any(warning["type"] == "static_viewbox_for_variable_svg" for warning in report["warnings"])


def test_widget_contract_warns_when_structural_svg_mutation_keeps_static_viewbox() -> None:
    from aetherviz_service.aetherviz.contracts.validation.widget_contract_checker import check_widget_runtime_contract

    html = sample_html().replace(
        '<button id="play-animation">播放</button>',
        '<input type="range" id="parameter-slider"><button id="play-animation">播放</button>',
    ).replace(
        "function updateVisualization(){",
        "function updateVisualization(){ "
        "const marker = document.createElementNS('http://www.w3.org/2000/svg', 'circle'); "
        "document.querySelector('svg').appendChild(marker);",
    )

    report = check_widget_runtime_contract(html)

    assert any(warning["type"] == "static_viewbox_for_variable_svg" for warning in report["warnings"])
    assert report["ok"] is True


def test_widget_contract_accepts_dynamic_viewbox_after_structural_mutation() -> None:
    from aetherviz_service.aetherviz.contracts.validation.widget_contract_checker import check_widget_runtime_contract

    html = sample_html().replace(
        '<button id="play-animation">播放</button>',
        '<input type="range" id="parameter-slider"><button id="play-animation">播放</button>',
    ).replace(
        "function updateVisualization(){",
        "function updateVisualization(){ "
        "const marker = document.createElementNS('http://www.w3.org/2000/svg', 'circle'); "
        "document.querySelector('svg').appendChild(marker); "
        "const box = dot.getBBox(); document.querySelector('svg').setAttribute('viewBox', `${box.x} ${box.y} ${box.width} ${box.height}`);",
    )

    report = check_widget_runtime_contract(html)

    assert not any(warning["type"] == "static_viewbox_for_variable_svg" for warning in report["warnings"])


def test_widget_contract_warns_about_per_frame_viewbox_refit() -> None:
    from aetherviz_service.aetherviz.contracts.validation.widget_contract_checker import check_widget_runtime_contract

    html = sample_html().replace(
        "function play(){ updateVisualization(); }",
        "function fitStage(){ const box = dot.getBBox(); "
        "document.querySelector('svg').setAttribute('viewBox', `${box.x} ${box.y} ${box.width} ${box.height}`); }\n"
        "const timeline = gsap.timeline({ onUpdate: () => { updateVisualization(); fitStage(); } });\n"
        "function play(){ updateVisualization(); }",
    )

    report = check_widget_runtime_contract(html)

    assert any(warning["type"] == "per_frame_viewbox_refit" for warning in report["warnings"])
    assert report["ok"] is True


def test_widget_contract_warns_about_unguarded_resizeobserver_viewbox_write() -> None:
    from aetherviz_service.aetherviz.contracts.validation.widget_contract_checker import check_widget_runtime_contract

    html = sample_html().replace(
        "function play(){ updateVisualization(); }",
        "function fitStage(){ const box = dot.getBBox(); "
        "document.querySelector('svg').setAttribute('viewBox', `${box.x} ${box.y} ${box.width} ${box.height}`); }\n"
        "new ResizeObserver(fitStage).observe(document.getElementById('aetherviz-stage'));\n"
        "function play(){ updateVisualization(); }",
    )

    report = check_widget_runtime_contract(html)

    assert any(warning["type"] == "unguarded_resize_viewbox_write" for warning in report["warnings"])
    assert report["ok"] is True


def test_widget_contract_accepts_guarded_resizeobserver_viewbox_write() -> None:
    from aetherviz_service.aetherviz.contracts.validation.widget_contract_checker import check_widget_runtime_contract

    html = sample_html().replace(
        "function play(){ updateVisualization(); }",
        "function fitStage(){ const box = dot.getBBox(); "
        "const next = `${box.x} ${box.y} ${box.width} ${box.height}`; "
        "const svg = document.querySelector('svg'); "
        "if (svg.getAttribute('viewBox') === next) return; "
        "svg.setAttribute('viewBox', next); }\n"
        "new ResizeObserver(() => requestAnimationFrame(fitStage)).observe(document.getElementById('aetherviz-stage'));\n"
        "function play(){ updateVisualization(); }",
    )

    report = check_widget_runtime_contract(html)

    warning_types = {warning["type"] for warning in report["warnings"]}
    assert "unguarded_resize_viewbox_write" not in warning_types
    assert "per_frame_viewbox_refit" not in warning_types


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
    assert "不得仅增加空值 early-return" in EDIT_HTML_SYSTEM_PROMPT
    assert "data-katex" in EDIT_HTML_SYSTEM_PROMPT


def test_build_edit_html_prompt_excludes_plan_and_conversation_context() -> None:
    from aetherviz_service.aetherviz.agents.instructions import build_edit_html_prompt

    prompt = build_edit_html_prompt(
        instruction="居中问题",
        current_html="<html></html>",
    )

    assert "居中问题" in prompt
    assert "<html></html>" in prompt
    assert "可选上下文" not in prompt
    assert "绝对不要原样输出" in prompt


def test_build_repair_prompt_can_exclude_plan_context_for_edit_phase() -> None:
    from aetherviz_service.aetherviz.agents.instructions import build_repair_prompt

    prompt = build_repair_prompt(
        topic="旧主题",
        plan={"goal": "旧目标", "interactive_type": "simulation"},
        raw_html="<html></html>",
        error_detail='{"errors":[]}',
        source_label="确定性检查",
        include_plan_context=False,
    )

    assert "旧主题" not in prompt
    assert "旧目标" not in prompt
    assert "<html></html>" in prompt


def test_knowledge_profile_routes_reusable_math_representations() -> None:
    from aetherviz_service.aetherviz.workflow.knowledge_profile import build_knowledge_profile

    function_profile = build_knowledge_profile("研究导数与函数图像的变化关系")
    geometry_profile = build_knowledge_profile("通过动态构造理解几何定理证明")

    assert function_profile["subject"] == "math"
    assert function_profile["concept_family"] in {"function", "calculus"}
    assert function_profile["representation_type"] == "coordinate_graph"
    assert geometry_profile["concept_family"] == "geometry"
    assert geometry_profile["representation_type"] == "geometric_construction"
    assert geometry_profile["pedagogy_pattern"] == "proof_animation"


def test_normalized_plan_contains_generic_knowledge_contract() -> None:
    from aetherviz_service.aetherviz.workflow.plan_contract import normalize_plan

    plan = normalize_plan({}, "导数的几何意义")

    assert plan["subject"] == "math"
    assert plan["knowledge_profile"]["concept_family"] == "calculus"
    assert set(plan["discipline_spec"]) == {
        "entities",
        "relations",
        "invariants",
        "boundary_cases",
        "representations",
    }


def test_html_prompt_composes_subject_and_representation_modules() -> None:
    from aetherviz_service.aetherviz.agents.instructions import (
        build_interactive_generation_prompt,
        system_prompt_for_interactive_type,
    )
    from aetherviz_service.aetherviz.workflow.plan_contract import normalize_plan

    plan = normalize_plan({}, "函数图像与参数变化")
    system_prompt = system_prompt_for_interactive_type(plan)
    generation_prompt = build_interactive_generation_prompt("函数图像与参数变化", plan)

    assert "数学语义补充" in system_prompt
    assert "坐标图表征" in system_prompt
    assert '"knowledge_profile"' in generation_prompt
    assert '"discipline_spec"' in generation_prompt
    assert '"subject":"math"' in generation_prompt


def test_discipline_consistency_checker_reports_non_blocking_representation_risk() -> None:
    from aetherviz_service.aetherviz.contracts.validation.discipline_consistency_checker import (
        check_discipline_consistency,
    )
    from aetherviz_service.aetherviz.workflow.plan_contract import normalize_plan

    plan = normalize_plan({}, "函数图像与参数变化")
    report = check_discipline_consistency("<!DOCTYPE html><html><body><main></main></body></html>", plan=plan)

    assert report["ok"] is True
    assert any(warning["type"] == "representation_mismatch" for warning in report["warnings"])
