"""Security, request-contract, and degradation regression tests."""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from aetherviz_service.aetherviz.agents import planner_agent, repair_agent
from aetherviz_service.aetherviz.agents.planner_agent import PlanningStreamResult, stream_create_plan
from aetherviz_service.aetherviz.tools.animation_lifecycle_checker import check_animation_lifecycle
from aetherviz_service.aetherviz.tools.deterministic_repair import deterministic_repair_html
from aetherviz_service.aetherviz.tools.layout_contract import assemble_layout_contract
from aetherviz_service.aetherviz.tools.security_checker import check_security
from aetherviz_service.aetherviz.tools.widget_contract_checker import check_widget_runtime_contract
from aetherviz_service.aetherviz.workflow.generate_workflow import _validate
from aetherviz_service.aetherviz.workflow.plan_contract import normalize_plan
from aetherviz_service.config import settings
from aetherviz_service.main import app
from tests.test_aetherviz import AETHERVIZ_ENDPOINT, sample_html, sample_plan

client = TestClient(app)


def test_generate_rejects_incomplete_approved_plan() -> None:
    response = client.post(AETHERVIZ_ENDPOINT, json={"phase": "generate", "approved_plan": {}})

    assert response.status_code == 400
    assert "approved_plan 缺少必要字段" in response.json()["detail"]


def test_plan_normalization_rejects_invalid_primary_color() -> None:
    plan = sample_plan()
    plan["primary_color"] = "red;body{display:none}"

    normalized = normalize_plan(plan, "熵增演示")

    assert normalized["primary_color"] == "#22D3EE"


def test_plan_loads_katex_only_when_formulas_are_present(monkeypatch) -> None:
    monkeypatch.setattr(settings, "aetherviz_katex_enabled", True)
    with_formula = sample_plan("勾股定理")
    with_formula["formulas"] = ["a^2+b^2=c^2"]

    formula_libraries = normalize_plan(with_formula, "勾股定理")["runtime"]["external_libraries"]
    plain_libraries = normalize_plan(sample_plan(), "熵增演示")["runtime"]["external_libraries"]

    assert settings.aetherviz_katex_css_url in formula_libraries
    assert settings.aetherviz_katex_js_url in formula_libraries
    assert all("katex" not in url.lower() for url in plain_libraries)


def test_security_rejects_tailwind_d3_and_unconfigured_katex() -> None:
    urls = (
        "https://cdn.tailwindcss.com",
        "https://d3js.org/d3.v7.min.js",
        "https://cdn.jsdelivr.net/npm/katex@9.9.9/dist/katex.min.js",
    )

    for url in urls:
        report = check_security(f'<!DOCTYPE html><html><head><script src="{url}"></script></head></html>')
        assert report["ok"] is False
        assert any(error["type"] == "external_resource" for error in report["errors"])


def test_security_rejects_allowlisted_url_with_query_and_network_apis() -> None:
    query_url = f"{settings.aetherviz_gsap_cdn_url}?unexpected=1"
    query_report = check_security(
        f'<!DOCTYPE html><html><head><script src="{query_url}"></script></head></html>'
    )
    fetch_report = check_security(
        "<!DOCTYPE html><html><body><script>fetch('https://example.com/data')</script></body></html>"
    )
    css_report = check_security(
        "<!DOCTYPE html><html><head><style>.x{background:url(https://example.com/x.png)}</style></head></html>"
    )

    assert query_report["ok"] is False
    assert fetch_report["ok"] is False
    assert css_report["ok"] is False


def test_widget_contract_warns_when_katex_has_no_fallback(monkeypatch) -> None:
    monkeypatch.setattr(settings, "aetherviz_katex_enabled", True)
    html = sample_html().replace(
        "</head>",
        f'<link rel="stylesheet" href="{settings.aetherviz_katex_css_url}">'
        f'<script src="{settings.aetherviz_katex_js_url}"></script></head>',
    ).replace(
        '<p id="animation-caption">',
        '<div data-region="formula">a^2+b^2=c^2</div><p id="animation-caption">',
    )

    report = check_widget_runtime_contract(html)

    assert any(warning["type"] == "missing_katex_fallback_guard" for warning in report["warnings"])


def test_widget_contract_rejects_non_node_append_child() -> None:
    html = sample_html().replace(
        "window.__AETHERVIZ_RUNTIME_READY__ = true;",
        'document.getElementById("aetherviz-stage").appendChild(caption.textContent = "x");\n'
        "window.__AETHERVIZ_RUNTIME_READY__ = true;",
    )

    report = check_widget_runtime_contract(html)

    assert any(error["type"] == "non_node_append_child" for error in report["errors"])


def test_widget_contract_accepts_node_append_child() -> None:
    html = sample_html().replace(
        "window.__AETHERVIZ_RUNTIME_READY__ = true;",
        "const wrap = document.createElement('div');\n"
        "wrap.appendChild(dot);\n"
        "wrap.appendChild(el = document.createElement('span'));\n"
        "window.__AETHERVIZ_RUNTIME_READY__ = true;",
    )

    report = check_widget_runtime_contract(html)

    assert not any(error["type"] == "non_node_append_child" for error in report["errors"])


def test_deterministic_repair_injects_missing_runtime_methods() -> None:
    html = sample_html().replace(
        "window.AetherVizRuntime = { play, pause, reset, update: updateVisualization, getState: () => state };",
        "window.AetherVizRuntime = { play, pause, reset };",
    )
    report = check_widget_runtime_contract(html)
    assert any(error["type"] == "missing_runtime_method" for error in report["errors"])

    repaired = deterministic_repair_html(html, {"errors": report["errors"]}, plan=sample_plan())
    repaired_report = check_widget_runtime_contract(repaired)

    assert not any(
        error["type"] in {"missing_runtime", "missing_runtime_method"}
        for error in repaired_report["errors"]
    )
    assert 'if(typeof r.getState!=="function")' in repaired


def test_deterministic_repair_rewrites_assignment_append_child() -> None:
    html = sample_html().replace(
        "window.__AETHERVIZ_RUNTIME_READY__ = true;",
        'document.getElementById("aetherviz-stage").appendChild(caption.textContent = "x");\n'
        "window.__AETHERVIZ_RUNTIME_READY__ = true;",
    )
    report = check_widget_runtime_contract(html)
    assert any(error["type"] == "non_node_append_child" for error in report["errors"])

    repaired = deterministic_repair_html(html, {"errors": report["errors"]}, plan=sample_plan())
    repaired_report = check_widget_runtime_contract(repaired)

    assert 'appendChild(Object.assign(caption,{textContent:"x"}))' in repaired
    assert not any(error["type"] == "non_node_append_child" for error in repaired_report["errors"])


def test_planning_context_is_included_and_reports_compression(monkeypatch) -> None:
    captured_messages = []
    plan_json = (
        '{"interactive_type":"simulation","title":"测试","goal":"目标","subject":"math",'
        '"teaching_flow":[],"controls":[],"formulas":[]}'
    )

    class FakeModel:
        def stream(self, messages):
            captured_messages.extend(messages)
            yield MagicMock(content=plan_json, additional_kwargs={})

    monkeypatch.setattr(planner_agent, "has_planning_llm_config", lambda: True)
    monkeypatch.setattr(planner_agent, "create_chat_model", lambda kind: FakeModel())

    result = next(
        item
        for item in stream_create_plan("勾股定理", context={"memory": "偏好探究式教学" * 1000})
        if isinstance(item, PlanningStreamResult)
    )

    assert "偏好探究式教学" in str(captured_messages[-1].content)
    assert result.plan["context_status"]["status"] == "compressed"


def test_truncated_model_output_is_a_hard_validation_error() -> None:
    report = _validate(sample_html(), truncated=True)

    assert report["ok"] is False
    assert any(error["type"] == "truncated_model_output" for error in report["errors"])


def test_deterministic_repair_does_not_hide_truncated_output_error() -> None:
    report = _validate(sample_html(), truncated=True)

    repaired = deterministic_repair_html(sample_html(), report, plan=sample_plan())
    repaired_report = _validate(repaired, truncated=True)

    assert repaired_report["ok"] is False
    assert any(error["type"] == "truncated_model_output" for error in repaired_report["errors"])


def test_model_free_repair_preserves_truncation_marker(monkeypatch) -> None:
    report = _validate(sample_html(), truncated=True)
    monkeypatch.setattr(repair_agent, "has_primary_llm_config", lambda: False)

    result = next(
        item
        for item in repair_agent.stream_repair_html(
            topic="熵增演示",
            plan=sample_plan(),
            raw_html=sample_html(),
            report=report,
        )
        if isinstance(item, repair_agent.RepairStreamResult)
    )

    assert result.truncated is True


def test_model_length_ignores_server_assembly_overhead() -> None:
    business_html = sample_html().replace("</style>", f"/*{'x' * 36000}*/</style>")
    assembled_html = assemble_layout_contract(business_html, sample_plan())

    report = _validate(assembled_html, plan=sample_plan(), model_html=business_html)

    assert len(business_html) < 40000
    assert len(assembled_html) > 40000
    assert report["ok"] is True
    assert not any(error["type"] == "html_length_hard_limit" for error in report["errors"])


def test_animation_lifecycle_rejects_structural_render_from_timeline_update() -> None:
    html = sample_html().replace(
        "function updateVisualization(){",
        "function render(){ stage.innerHTML=''; const node=document.createElementNS('svg','path'); stage.appendChild(node); }\n"
        "const timeline=gsap.timeline({onUpdate:()=>{ render(); }});\n"
        "function updateVisualization(){",
    )

    report = check_animation_lifecycle(html)

    assert report["ok"] is False
    assert any(error["type"] == "structural_render_inside_animation_frame" for error in report["errors"])


def test_animation_lifecycle_allows_attribute_only_frame_updates() -> None:
    html = sample_html().replace(
        "function updateVisualization(){",
        "function applyView(){ dot.setAttribute('cx', String(state.progress)); }\n"
        "const timeline=gsap.timeline({onUpdate:()=>{ applyView(); }});\n"
        "function updateVisualization(){",
    )

    report = check_animation_lifecycle(html)

    assert report["ok"] is True


def test_widget_contract_detects_direct_gsap_without_business_fallback_after_assembly() -> None:
    html = sample_html().replace(
        "</head>",
        '<script src="https://cdn.jsdelivr.net/npm/gsap@3/dist/gsap.min.js"></script></head>',
    ).replace(
        "function updateVisualization(){",
        "const timeline=gsap.timeline({paused:true}); timeline.to('#dot',{x:20,duration:1});\n"
        "function updateVisualization(){",
    )

    report = check_widget_runtime_contract(assemble_layout_contract(html, sample_plan()))

    assert any(
        warning["type"] == "missing_animation_controller_fallback"
        for warning in report["warnings"]
    )


def test_widget_contract_accepts_shared_animation_controller_fallback() -> None:
    html = sample_html().replace(
        "</head>",
        '<script src="https://cdn.jsdelivr.net/npm/gsap@3/dist/gsap.min.js"></script></head>',
    ).replace(
        "function updateVisualization(){",
        "const controller=window.AetherVizAnimationController.create({duration:1,update:()=>applyView()});\n"
        "function applyView(){}\nfunction updateVisualization(){",
    )

    report = check_widget_runtime_contract(assemble_layout_contract(html, sample_plan()))

    assert not any(
        warning["type"] == "missing_animation_controller_fallback"
        for warning in report["warnings"]
    )
