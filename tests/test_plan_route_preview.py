"""Plan-stage route preview and representation_spec self-correction."""

from __future__ import annotations

from aetherviz_service.aetherviz.ir.router.capability_catalog import build_ir_capability_catalog
from aetherviz_service.aetherviz.ir.router.contracts import IRRouteAssessment, IRRouteDecision
from aetherviz_service.aetherviz.workflow import plan_route_preview
from aetherviz_service.aetherviz.workflow.plan_contract import normalize_plan
from aetherviz_service.aetherviz.workflow.plan_detection import build_planning_prompt


def test_capability_catalog_uses_capability_language_without_backend_keys() -> None:
    catalog = build_ir_capability_catalog()
    system_prompt, _ = build_planning_prompt("勾股定理", "#22D3EE")

    assert "已验证可视化能力族" in catalog
    assert "number_line_scene" not in catalog
    assert "linked_coordinate_scene" not in catalog
    assert "会被拒的组合" in catalog
    assert catalog in system_prompt
    assert "number_line_scene" not in system_prompt


def test_route_preview_skips_refine_when_confidence_is_high(monkeypatch) -> None:
    plan = normalize_plan({}, "二次函数图像的平移与形变")
    calls = {"refine": 0}

    def _unexpected_refine(*_args, **_kwargs):
        calls["refine"] += 1
        raise AssertionError("should not refine a high-confidence route")

    monkeypatch.setattr(plan_route_preview, "_refine_representation_fields", _unexpected_refine)

    refined, metrics = plan_route_preview.maybe_refine_plan_for_route(plan, topic="二次函数图像的平移与形变")

    assert refined["representation_spec"]["views"]
    assert metrics["route_preview_attempted"] is True
    assert metrics["route_preview_refined"] is False
    assert metrics["route_preview_selected_backend"] == "coordinate_graph_scene"
    assert calls["refine"] == 0


def test_route_preview_refines_once_when_unroutable(monkeypatch) -> None:
    topic = "无法路由的草稿"
    plan = {
        "title": "草稿",
        "goal": "目标",
        "interactive_type": "simulation",
        "representation_spec": {
            "version": "1.0",
            "views": [],
            "state_variables": [],
            "correspondences": [],
            "required_invariants": [],
            "interaction_requirements": [],
        },
    }
    monkeypatch.setattr(plan_route_preview, "has_planning_llm_config", lambda: True)
    route_calls = 0

    def resolve_route(*_args, **_kwargs):
        nonlocal route_calls
        route_calls += 1
        routable = route_calls == 2
        return IRRouteDecision(
            selected_backend="coordinate_graph_scene" if routable else None,
            source="deterministic",
            confidence=0.9 if routable else 1.0,
            plan_fingerprint="fp",
            candidates=(
                IRRouteAssessment(
                    backend_key="coordinate_graph_scene",
                    eligible=routable,
                    score=0.9 if routable else 0.1,
                    missing_capabilities=() if routable else ("curve",),
                    exclusion_reasons=() if routable else ("没有坐标平面或函数曲线",),
                ),
            ),
            reasons=("路由成功",) if routable else ("没有 IR 后端满足计划所需能力，停止生成",),
        )

    monkeypatch.setattr(plan_route_preview, "resolve_generation_route", resolve_route)
    monkeypatch.setattr(
        plan_route_preview,
        "_refine_representation_fields",
        lambda *_args, **_kwargs: {
            "representation_spec": {
                "version": "1.0",
                "views": [{"id": "graph", "kind": "coordinate_plane", "role": "函数图像"}],
                "state_variables": [{"id": "a", "semantic_type": "scalar"}],
                "correspondences": [],
                "required_invariants": [],
                "interaction_requirements": ["scrub"],
            }
        },
    )

    refined, metrics = plan_route_preview.maybe_refine_plan_for_route(plan, topic=topic)

    assert metrics["route_preview_refined"] is True
    assert metrics["route_preview_refine_accepted"] is True
    assert any(view.get("kind") == "coordinate_plane" for view in refined["representation_spec"]["views"])


def test_route_preview_rejects_refinement_that_remains_unroutable(monkeypatch) -> None:
    plan = {"title": "草稿", "goal": "目标", "interactive_type": "simulation"}
    monkeypatch.setattr(plan_route_preview, "has_planning_llm_config", lambda: True)
    monkeypatch.setattr(
        plan_route_preview,
        "resolve_generation_route",
        lambda *_args, **_kwargs: IRRouteDecision(
            selected_backend=None,
            source="deterministic",
            confidence=1.0,
            plan_fingerprint="fp",
            candidates=(),
            reasons=("没有合格后端",),
        ),
    )
    monkeypatch.setattr(
        plan_route_preview,
        "_refine_representation_fields",
        lambda *_args, **_kwargs: {"representation_spec": {"views": []}},
    )

    _refined, metrics = plan_route_preview.maybe_refine_plan_for_route(plan, topic="无法路由")

    assert metrics["route_preview_refined"] is False
    assert metrics["route_preview_refine_accepted"] is False
    assert metrics["route_preview_refine_rejected_reason"] == "post_refine_still_unroutable"
