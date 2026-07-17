"""Capability routing for a single interactive mathematical coordinate plane."""

from __future__ import annotations

from typing import Any

from aetherviz_service.aetherviz.ir.router.contracts import IRRouteAssessment, IRRoutingProfile

PROFILE = IRRoutingProfile(
    description="单一坐标平面中的函数、曲线、动态点和辅助关系，由服务端统一编译坐标映射与 SVG 尺度。",
    capabilities=frozenset({"single_view", "coordinate_plane", "curve", "dynamic_point", "shared_parameter"}),
    required_capabilities=frozenset({"single_view", "coordinate_plane", "curve"}),
    supported_view_kinds=frozenset({"coordinate_plane"}),
    exclusions=("两个或更多需要跨视图联动的表征", "没有坐标平面或函数曲线"),
)


def assess(plan: dict[str, Any]) -> IRRouteAssessment:
    spec = plan.get("representation_spec") if isinstance(plan.get("representation_spec"), dict) else {}
    views = [item for item in spec.get("views", []) if isinstance(item, dict)]
    kinds = {str(item.get("kind") or "") for item in views}
    relations = {str(item.get("type") or "") for item in spec.get("correspondences", []) if isinstance(item, dict)}
    variables = [item for item in spec.get("state_variables", []) if isinstance(item, dict)]
    single_view = len(views) == 1
    coordinate_plane = single_view and kinds == {"coordinate_plane"}
    cross_view = len(views) > 1 or any(
        relation in {"projection", "equal_value", "coincident", "transform", "decompose_recompose"}
        for relation in relations
    )
    prior = (
        (plan.get("knowledge_profile") or {}).get("representation_type") == "coordinate_graph"
        if isinstance(plan.get("knowledge_profile"), dict)
        else False
    )
    math_subject = str(plan.get("subject") or (plan.get("knowledge_profile") or {}).get("subject") or "") == "math"
    checks = {
        "single_view": single_view,
        "coordinate_plane": coordinate_plane,
        "curve": coordinate_plane and math_subject,
        "state_parameter": bool(variables),
        "profile_prior": prior,
    }
    weights = {
        "single_view": 0.20,
        "coordinate_plane": 0.32,
        "curve": 0.24,
        "state_parameter": 0.14,
        "profile_prior": 0.10,
    }
    score = round(sum(weights[key] for key, matched in checks.items() if matched), 3)
    missing = tuple(sorted(key for key in ("single_view", "coordinate_plane", "curve") if not checks[key]))
    exclusions = tuple(
        reason
        for condition, reason in (
            (cross_view, "计划包含跨视图关系"),
            (not variables, "计划没有可调状态变量"),
        )
        if condition
    )
    return IRRouteAssessment(
        backend_key="coordinate_graph_scene",
        eligible=not missing and not exclusions,
        score=score,
        matched_capabilities=tuple(sorted(key for key, matched in checks.items() if matched)),
        missing_capabilities=missing,
        exclusion_reasons=exclusions,
        reasons=tuple(key for key, matched in checks.items() if matched),
    )
