"""Tests for approve-time TeachingPlan → GenerationSpec compilation."""

from __future__ import annotations

from aetherviz_service.aetherviz.ir.router.contracts import IRRouteAssessment, IRRouteDecision
from aetherviz_service.aetherviz.workflow import plan_compile
from aetherviz_service.aetherviz.workflow.plan_compile import compile_plan_layers
from aetherviz_service.aetherviz.workflow.plan_contract import normalize_plan
from aetherviz_service.aetherviz.workflow.plan_layers import (
    TEACHING_PLAN_FIELD_SET,
    extract_teaching_plan,
)


def test_compile_plan_layers_deterministic_path_preserves_teaching_semantics() -> None:
    flat = normalize_plan({}, "勾股定理拼图重排证明")
    teaching = extract_teaching_plan(flat)
    title_before = teaching["title"]
    goal_before = teaching["goal"]

    result = compile_plan_layers(topic="勾股定理拼图重排证明", teaching_plan=teaching, allow_llm=False)

    assert result.teaching_plan["title"] == title_before
    assert result.teaching_plan["goal"] == goal_before
    assert set(result.teaching_plan) <= TEACHING_PLAN_FIELD_SET
    assert result.generation_spec["representation_spec"]["version"] == "1.0"
    assert result.plan["page_type"] == "interactive"
    assert result.metrics["plan_compile_attempted"] is True
    assert result.metrics["plan_compile_llm_attempted"] is False


def test_compile_does_not_rewrite_teaching_labels_when_narrowing_spans() -> None:
    flat = normalize_plan(
        {
            "interactive_type": "simulation",
            "title": "几何割补",
            "goal": "理解等积变换",
            "interactive_spec": {
                "type": "simulation",
                "concept": "割补",
                "description": "切割重排",
                "variables": [
                    {
                        "name": "side",
                        "label": "边长教学标签",
                        "min": 1,
                        "max": 100,
                        "default": 10,
                        "step": 0.5,
                        "unit": "",
                    }
                ],
                "presets": [{"id": "default", "label": "默认", "values": {"side": 10}}],
                "observations": ["观察等积"],
            },
            "recomposition_spec": {
                "geometry_variables": ["side"],
                "proof_constraints": {"measure_invariants": ["area_preserved", "piece_congruence"]},
            },
        },
        "组合图形面积切割重排证明",
    )
    teaching = extract_teaching_plan(flat)
    result = compile_plan_layers(
        topic="组合图形面积切割重排证明",
        teaching_plan=teaching,
        generation_spec={"recomposition_spec": flat.get("recomposition_spec")},
        flat_plan=flat,
        allow_llm=False,
    )
    variables = result.teaching_plan["interactive_spec"]["variables"]
    side = next(item for item in variables if item["name"] == "side")
    assert side["label"] == "边长教学标签"
    assert float(side["max"]) / float(side["min"]) <= 6.0 + 1e-9


def test_compile_llm_enhancement_accepted_when_routable(monkeypatch) -> None:
    teaching = extract_teaching_plan(normalize_plan({}, "无法路由草稿主题xyz"))
    route_calls = 0

    def resolve_route(plan, **_kwargs):
        nonlocal route_calls
        route_calls += 1
        routable = route_calls >= 2
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
            reasons=("路由成功",) if routable else ("没有合格后端",),
        )

    monkeypatch.setattr(plan_compile, "has_planning_llm_config", lambda: True)
    monkeypatch.setattr(plan_compile, "resolve_generation_route", resolve_route)
    monkeypatch.setattr(
        plan_compile,
        "_llm_compile_representation_fields",
        lambda *_args, **_kwargs: {
            "representation_spec": {
                "version": "1.0",
                "views": [{"id": "graph", "kind": "coordinate_plane", "role": "函数图像"}],
                "state_variables": [{"id": "parameter", "semantic_type": "scalar"}],
                "correspondences": [],
                "required_invariants": [],
                "interaction_requirements": ["scrub"],
            }
        },
    )

    result = compile_plan_layers(topic="无法路由草稿主题xyz", teaching_plan=teaching, allow_llm=True)
    assert result.metrics["plan_compile_llm_attempted"] is True
    assert result.metrics["plan_compile_llm_accepted"] is True
    assert any(
        view.get("kind") == "coordinate_plane"
        for view in result.generation_spec["representation_spec"]["views"]
    )


def test_compile_rejects_llm_enhancement_that_stays_unroutable(monkeypatch) -> None:
    teaching = extract_teaching_plan(normalize_plan({}, "无法路由"))
    monkeypatch.setattr(plan_compile, "has_planning_llm_config", lambda: True)
    monkeypatch.setattr(
        plan_compile,
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
        plan_compile,
        "_llm_compile_representation_fields",
        lambda *_args, **_kwargs: {"representation_spec": {"views": []}},
    )

    result = compile_plan_layers(topic="无法路由", teaching_plan=teaching, allow_llm=True)
    assert result.metrics["plan_compile_llm_attempted"] is True
    assert result.metrics["plan_compile_llm_accepted"] is False
    assert result.metrics["plan_compile_llm_rejected_reason"] == "post_compile_still_unroutable"
