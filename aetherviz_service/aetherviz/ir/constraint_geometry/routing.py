"""Capability routing for parameter-driven Euclidean constraint scenes."""

from __future__ import annotations

from typing import Any

from aetherviz_service.aetherviz.ir.router.contracts import IRRouteAssessment, IRRoutingProfile

PROFILE = IRRoutingProfile(
    description="连续参数驱动的点、线、圆、角、切线和轨迹构造，服务端验证欧氏不变量并提供有界受约束拖拽。",
    capabilities=frozenset(
        {
            "geometric_scene",
            "continuous_parameter",
            "point_line_circle",
            "euclidean_constraint",
            "derived_construction",
            "constrained_drag",
            "angle_measurement",
            "tangent",
            "bounded_locus",
        }
    ),
    required_capabilities=frozenset({"geometric_scene", "state_parameter", "euclidean_constraint"}),
    supported_view_kinds=frozenset({"geometric_scene", "symbolic_panel"}),
    exclusions=("离散正多边形收敛", "割补重排", "跨坐标系函数联动"),
)


def assess(plan: dict[str, Any]) -> IRRouteAssessment:
    spec = plan.get("representation_spec") if isinstance(plan.get("representation_spec"), dict) else {}
    views = [item for item in spec.get("views", []) if isinstance(item, dict)]
    kinds = {str(item.get("kind") or "") for item in views}
    states = [item for item in spec.get("state_variables", []) if isinstance(item, dict)]
    relations = {str(item.get("type") or "") for item in spec.get("correspondences", []) if isinstance(item, dict)}
    invariants = {str(item) for item in spec.get("required_invariants", [])}
    geometry = "geometric_scene" in kinds
    supported_views = bool(kinds) and kinds <= PROFILE.supported_view_kinds
    continuous = any(item.get("semantic_type") != "discrete" for item in states)
    constraint_signal = bool(
        invariants
        & {
            "coincident",
            "collinear",
            "parallel",
            "perpendicular",
            "equal_length",
            "midpoint",
            "point_on_circle",
            "tangent",
            "equal_angle",
            "supplementary",
        }
    )
    prior = isinstance(plan.get("knowledge_profile"), dict) and plan["knowledge_profile"].get(
        "representation_type"
    ) in {"geometric_construction", "constraint_geometry"}
    recomposition = "decompose_recompose" in relations or bool(
        invariants & {"piece_identity_preserved", "piece_count_constant", "piece_congruence", "area_preserved"}
    )
    parametric = any(item.get("semantic_type") == "discrete" for item in states) and (
        "derived_value" in relations or "data_chart" in kinds
    )
    cross_coordinate = "coordinate_plane" in kinds or len(views) > 2
    checks = {
        "geometric_scene": geometry,
        "state_parameter": bool(states),
        "continuous_parameter": continuous,
        "euclidean_constraint": constraint_signal,
        "supported_views": supported_views,
        "profile_prior": prior,
    }
    weights = {
        "geometric_scene": 0.28,
        "state_parameter": 0.18,
        "continuous_parameter": 0.16,
        "euclidean_constraint": 0.22,
        "supported_views": 0.10,
        "profile_prior": 0.06,
    }
    required = {"geometric_scene", "state_parameter", "euclidean_constraint", "supported_views"}
    missing = tuple(sorted(key for key in required if not checks[key]))
    exclusions = tuple(
        reason
        for condition, reason in (
            (recomposition, "计划要求割补重排"),
            (parametric, "离散派生测量应使用参数几何 IR"),
            (cross_coordinate, "计划包含坐标平面或过多跨视图关系"),
        )
        if condition
    )
    return IRRouteAssessment(
        backend_key="constraint_geometry_scene",
        eligible=not missing and not exclusions,
        score=round(sum(weights[key] for key, matched in checks.items() if matched), 3),
        matched_capabilities=tuple(sorted(key for key, matched in checks.items() if matched)),
        missing_capabilities=missing,
        exclusion_reasons=exclusions,
        reasons=tuple(key for key, matched in checks.items() if matched),
    )
