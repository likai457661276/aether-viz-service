"""Routing capability declaration for linked mathematical views."""

from __future__ import annotations

from typing import Any

from aetherviz_service.aetherviz.ir.router.contracts import IRRouteAssessment, IRRoutingProfile

PROFILE = IRRoutingProfile(
    description="共享连续参数驱动两个或更多数学视图，并保持曲线、动态点、投影或数值对应不变量。",
    capabilities=frozenset(
        {"multi_view", "shared_parameter", "dynamic_point", "curve", "cross_view_correspondence"}
    ),
    required_capabilities=frozenset({"multi_view", "shared_parameter", "cross_view_correspondence"}),
    supported_view_kinds=frozenset({"coordinate_plane", "geometric_scene", "symbolic_panel"}),
    exclusions=("单一静态函数图像", "没有共享状态参数", "没有跨视图动态关系"),
)


def assess(plan: dict[str, Any]) -> IRRouteAssessment:
    spec = plan.get("representation_spec") if isinstance(plan.get("representation_spec"), dict) else {}
    views = [item for item in spec.get("views", []) if isinstance(item, dict)]
    correspondences = [item for item in spec.get("correspondences", []) if isinstance(item, dict)]
    invariants = {str(item) for item in spec.get("required_invariants", [])}
    kinds = {str(item.get("kind") or "") for item in views}
    relation_types = {str(item.get("type") or "") for item in correspondences}
    multi_view = len({str(item.get("id") or "") for item in views}) >= 2
    shared_parameter = "shared_parameter" in relation_types and any(
        str(item.get("parameter") or "") for item in correspondences if item.get("type") == "shared_parameter"
    )
    cross_view = bool(relation_types & {"projection", "equal_value", "point_on_curve", "coincident"})
    coordinate_view = "coordinate_plane" in kinds
    prior = (
        ((plan.get("knowledge_profile") or {}).get("representation_type") == "linked_coordinate_scene")
        if isinstance(plan.get("knowledge_profile"), dict)
        else False
    )
    checks = {
        "multi_view": multi_view,
        "shared_parameter": shared_parameter,
        "cross_view_correspondence": cross_view,
        "coordinate_view": coordinate_view,
        "computable_invariant": bool(invariants & {"point_on_curve", "equal_value", "coincident"}),
        "profile_prior": prior,
    }
    weights = {
        "multi_view": 0.24,
        "shared_parameter": 0.26,
        "cross_view_correspondence": 0.24,
        "coordinate_view": 0.12,
        "computable_invariant": 0.10,
        "profile_prior": 0.04,
    }
    score = round(sum(weights[key] for key, matched in checks.items() if matched), 3)
    required = {"multi_view", "shared_parameter", "cross_view_correspondence", "coordinate_view"}
    missing = tuple(sorted(key for key in required if not checks[key]))
    exclusions = tuple(
        reason
        for condition, reason in (
            (len(views) == 1 and not correspondences, "单一视图且没有跨视图关系"),
            (not shared_parameter and not cross_view, "没有共享参数或跨视图关系"),
        )
        if condition
    )
    return IRRouteAssessment(
        backend_key="linked_coordinate_scene",
        eligible=not missing and not exclusions,
        score=score,
        matched_capabilities=tuple(sorted(key for key, matched in checks.items() if matched)),
        missing_capabilities=missing,
        exclusion_reasons=exclusions,
        reasons=tuple(key for key, matched in checks.items() if matched),
    )
