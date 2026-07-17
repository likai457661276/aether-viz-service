from __future__ import annotations

from aetherviz_service.aetherviz.ir.router import service
from aetherviz_service.aetherviz.workflow.plan_contract import normalize_plan
from aetherviz_service.config import settings


def test_plan_aware_routing_fixes_known_false_negative_and_false_positive(monkeypatch) -> None:
    monkeypatch.setattr(settings, "aetherviz_ir_router_enabled", False)
    linked = service.resolve_generation_route(
        normalize_plan({}, "旋转向量在纵轴的投影与正弦曲线联动")
    )
    direct = service.resolve_generation_route(normalize_plan({}, "圆的标准方程与图像"))

    assert linked.selected_backend == "linked_coordinate_scene"
    assert direct.selected_backend is None


def test_router_uses_llm_only_for_prior_conflict_and_accepts_registered_candidate(monkeypatch) -> None:
    plan = normalize_plan({}, "旋转向量在纵轴的投影与正弦曲线联动")
    monkeypatch.setattr(settings, "aetherviz_ir_router_enabled", True)
    monkeypatch.setattr(settings, "aetherviz_ir_router_shadow_mode", False)
    monkeypatch.setattr(service, "has_primary_llm_config", lambda: True)
    monkeypatch.setattr(
        service,
        "judge_ir_route",
        lambda *_args: {
            "selected_backend": "linked_coordinate_scene",
            "confidence": 0.92,
            "required_capabilities": ["multi_view", "shared_parameter"],
            "evidence": ["两个视图共享参数并保持投影关系"],
        },
    )

    route = service.resolve_generation_route(plan)

    assert route.selected_backend == "linked_coordinate_scene"
    assert route.source == "llm_judge"
    assert route.llm_invoked is True
    assert route.llm_accepted is True


def test_router_rejects_unknown_llm_backend_and_falls_back(monkeypatch) -> None:
    plan = normalize_plan({}, "旋转向量在纵轴的投影与正弦曲线联动")
    monkeypatch.setattr(settings, "aetherviz_ir_router_enabled", True)
    monkeypatch.setattr(settings, "aetherviz_ir_router_shadow_mode", False)
    monkeypatch.setattr(service, "has_primary_llm_config", lambda: True)
    monkeypatch.setattr(
        service,
        "judge_ir_route",
        lambda *_args: {
            "selected_backend": "unknown_backend",
            "confidence": 0.99,
            "required_capabilities": [],
            "evidence": [],
        },
    )

    route = service.resolve_generation_route(plan)

    assert route.selected_backend == "linked_coordinate_scene"
    assert route.source == "deterministic"
    assert route.llm_accepted is False
    assert route.fallback == "llm_selection_rejected"


def test_normalized_plan_contains_generic_representation_spec() -> None:
    plan = normalize_plan({}, "函数曲线与坐标轨迹参数联动")

    assert plan["representation_spec"]["version"] == "1.0"
    assert len(plan["representation_spec"]["views"]) == 2
    assert {item["type"] for item in plan["representation_spec"]["correspondences"]} >= {
        "shared_parameter",
        "equal_value",
    }


def test_partial_linked_spec_is_augmented_with_cross_view_relation() -> None:
    plan = normalize_plan(
        {
            "interactive_type": "simulation",
            "interactive_spec": {
                "type": "simulation",
                "concept": "单位圆运动与正弦曲线联动",
                "description": "同一角度参数驱动圆周动点与坐标曲线",
                "variables": [{"name": "theta", "min": 0, "max": 6.28, "default": 0}],
                "presets": [],
                "observations": [],
            },
            "representation_spec": {
                "views": [
                    {"id": "circle", "kind": "geometric_scene", "role": "圆周运动"},
                    {"id": "graph", "kind": "coordinate_plane", "role": "函数曲线"},
                ],
                "state_variables": [{"id": "theta", "semantic_type": "angle"}],
                "correspondences": [
                    {
                        "type": "shared_parameter",
                        "source_view": "circle",
                        "target_view": "graph",
                        "parameter": "theta",
                    }
                ],
                "required_invariants": ["point_on_curve", "equal_value"],
            },
        },
        "单位圆运动与正弦曲线联动",
    )

    relation_types = {item["type"] for item in plan["representation_spec"]["correspondences"]}
    assert relation_types >= {"shared_parameter", "point_on_curve"}
    assert service.resolve_generation_route(plan).selected_backend == "linked_coordinate_scene"


def test_unrelated_recomposition_payload_is_dropped_from_linked_plan() -> None:
    plan = normalize_plan(
        {
            "recomposition_spec": {
                "topology_variables": ["theta"],
                "invariants": ["piece_identity_preserved"],
            }
        },
        "单位圆投影与正弦曲线联动",
    )

    assert "recomposition_spec" not in plan


def test_representation_state_range_is_bound_to_interactive_variable_contract() -> None:
    plan = normalize_plan(
        {
            "interactive_type": "simulation",
            "interactive_spec": {
                "type": "simulation",
                "concept": "参数联动",
                "description": "共享参数",
                "variables": [
                    {
                        "name": "theta",
                        "label": "角度",
                        "min": 0,
                        "max": 6.28,
                        "step": 0.01,
                        "default": 1,
                        "unit": "rad",
                    }
                ],
                "presets": [],
                "observations": [],
            },
            "representation_spec": {
                "views": [],
                "state_variables": [
                    {
                        "id": "theta",
                        "semantic_type": "angle",
                        "minimum": -999,
                        "maximum": 999,
                        "default": 999,
                        "unit": "degree",
                        "display_unit": "degree",
                    },
                    {"id": "phantom", "semantic_type": "scalar"},
                ],
            },
        },
        "参数联动",
    )

    assert plan["representation_spec"]["state_variables"] == [
        {
            "id": "theta",
            "semantic_type": "angle",
            "minimum": 0.0,
            "maximum": 6.28,
            "default": 1.0,
            "unit": "rad",
            "display_unit": "degree",
        }
    ]
