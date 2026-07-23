"""Deterministic plan-stage route preview (LLM refine moved to plan_compile)."""

from __future__ import annotations

from aetherviz_service.aetherviz.ir.router.capability_catalog import build_ir_capability_catalog
from aetherviz_service.aetherviz.workflow import plan_compile, plan_route_preview
from aetherviz_service.aetherviz.workflow.plan_contract import compact_plan_for_revision, normalize_plan
from aetherviz_service.aetherviz.workflow.plan_detection import build_planning_prompt
from aetherviz_service.aetherviz.workflow.plan_layers import TEACHING_PLAN_FIELD_SET, extract_teaching_plan


def test_capability_catalog_is_for_compile_not_planner() -> None:
    catalog = build_ir_capability_catalog()
    system_prompt, _ = build_planning_prompt("勾股定理", "#22D3EE")

    assert "已验证可视化能力族" in catalog
    assert "number_line_scene" not in catalog
    assert catalog not in system_prompt
    assert "不要输出这些字段" in system_prompt
    assert "机器 IR 规格" in system_prompt
    assert "discipline_spec：只含" not in system_prompt
    assert "{capability_catalog}" not in system_prompt


def test_compact_plan_for_revision_is_teaching_only() -> None:
    plan = normalize_plan({}, "二次函数图像")
    compact = compact_plan_for_revision(plan)
    assert set(compact) <= TEACHING_PLAN_FIELD_SET
    assert "representation_spec" not in compact
    assert "discipline_spec" not in compact


def test_route_preview_is_deterministic_only(monkeypatch) -> None:
    plan = normalize_plan({}, "二次函数图像的平移与形变")
    calls = {"llm": 0}

    def _unexpected_llm(*_args, **_kwargs):
        calls["llm"] += 1
        raise AssertionError("plan-stage preview must not call LLM compile")

    monkeypatch.setattr(plan_compile, "_llm_compile_representation_fields", _unexpected_llm)

    refined, metrics = plan_route_preview.preview_route_for_plan(plan, topic="二次函数图像的平移与形变")

    assert refined["representation_spec"]["views"]
    assert metrics["route_preview_attempted"] is True
    assert metrics["route_preview_refined"] is False
    assert metrics["route_preview_refine_attempted"] is False
    assert metrics["route_preview_selected_backend"] == "coordinate_graph_scene"
    assert "teaching_plan" in metrics
    assert set(metrics["teaching_plan"]) <= TEACHING_PLAN_FIELD_SET
    assert calls["llm"] == 0


def test_plan_ready_exposes_teaching_plan_layer() -> None:
    from fastapi.testclient import TestClient

    from aetherviz_service.main import app
    from tests.test_aetherviz import parse_sse_events

    client = TestClient(app)
    response = client.post("/bingo-ai/generate-aetherviz-spec", json={"topic": "一次函数", "phase": "plan"})
    events = parse_sse_events(response)
    ready = next(data for event, data in events if event == "plan.ready")
    assert "teaching_plan" in ready["data"]
    assert ready["data"]["teaching_plan"]["title"]
    assert "representation_spec" not in ready["data"]["teaching_plan"]
    # Legacy flat plan still present for compatibility.
    assert ready["data"]["plan"]["page_type"] == "interactive"
    assert ready["metadata"]["route_preview_refine_attempted"] is False


def test_approve_returns_dual_layers(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from aetherviz_service.main import app
    from tests.test_aetherviz import parse_sse_events, sample_plan

    client = TestClient(app)
    plan = sample_plan("旋转向量在纵轴的投影与正弦曲线联动")
    response = client.post("/bingo-ai/generate-aetherviz-spec", json={"phase": "approve_plan", "plan": plan})
    events = parse_sse_events(response)
    assert events[-1][0] == "plan.approved"
    payload = events[-1][1]["data"]
    assert payload["teaching_plan"]["title"]
    assert payload["generation_spec"]["representation_spec"]["version"] == "1.0"
    assert payload["plan"]["status"] == "approved"
    assert extract_teaching_plan(payload["plan"])["title"] == payload["teaching_plan"]["title"]


def test_approve_accepts_teaching_plan_only() -> None:
    from fastapi.testclient import TestClient

    from aetherviz_service.main import app
    from tests.test_aetherviz import parse_sse_events, sample_plan

    client = TestClient(app)
    flat = sample_plan("旋转向量在纵轴的投影与正弦曲线联动")
    teaching = extract_teaching_plan(normalize_plan(flat, flat["title"]))
    response = client.post(
        "/bingo-ai/generate-aetherviz-spec",
        json={"phase": "approve_plan", "teaching_plan": teaching},
    )
    events = parse_sse_events(response)
    assert events[-1][0] == "plan.approved"
    assert events[-1][1]["data"]["generation_spec"]["subject"]
