"""Capability routing for ordered one-dimensional number-line scenes."""

from __future__ import annotations

from typing import Any

from aetherviz_service.aetherviz.ir.router.contracts import IRRouteAssessment, IRRoutingProfile

PROFILE = IRRoutingProfile(
    description="一维有序数轴上的点、端点、区间、射线、距离和有向位移，由服务端统一编译刻度与动画。",
    capabilities=frozenset(
        {"number_line", "interval", "dynamic_point", "inequality_ray", "distance", "directed_displacement"}
    ),
    required_capabilities=frozenset({"number_line", "ordered_scale", "state_parameter"}),
    supported_view_kinds=frozenset({"number_line", "symbolic_panel"}),
    exclusions=("二维坐标图或函数曲线", "连续几何约束", "没有数轴视图或可调状态"),
)


def assess(plan: dict[str, Any]) -> IRRouteAssessment:
    spec = plan.get("representation_spec") if isinstance(plan.get("representation_spec"), dict) else {}
    views = [item for item in spec.get("views", []) if isinstance(item, dict)]
    kinds = {str(item.get("kind") or "") for item in views}
    states = [item for item in spec.get("state_variables", []) if isinstance(item, dict)]
    relations = {str(item.get("type") or "") for item in spec.get("correspondences", []) if isinstance(item, dict)}
    prior = (
        isinstance(plan.get("knowledge_profile"), dict)
        and plan["knowledge_profile"].get("representation_type") == "number_line"
    )
    number_line = "number_line" in kinds
    supported_views = bool(kinds) and kinds <= PROFILE.supported_view_kinds
    checks = {
        "number_line": number_line,
        "ordered_scale": number_line and supported_views,
        "state_parameter": bool(states),
        "symbolic_sync": "symbolic_panel" in kinds and bool(relations & {"equal_value", "derived_value"}),
        "multi_track": sum(1 for item in views if item.get("kind") == "number_line") > 1,
        "profile_prior": prior,
    }
    weights = {
        "number_line": 0.30,
        "ordered_scale": 0.25,
        "state_parameter": 0.20,
        "symbolic_sync": 0.08,
        "multi_track": 0.07,
        "profile_prior": 0.10,
    }
    required = {"number_line", "ordered_scale", "state_parameter"}
    missing = tuple(sorted(key for key in required if not checks[key]))
    exclusions = tuple(
        reason
        for condition, reason in (
            (bool(kinds - PROFILE.supported_view_kinds), "计划包含数轴 IR 不支持的视图"),
            ("coordinate_plane" in kinds, "二维坐标平面应使用坐标图 IR"),
            ("geometric_scene" in kinds, "几何场景不属于数轴 IR"),
        )
        if condition
    )
    return IRRouteAssessment(
        backend_key="number_line_scene",
        eligible=not missing and not exclusions,
        score=round(sum(weights[key] for key, matched in checks.items() if matched), 3),
        matched_capabilities=tuple(sorted(key for key, matched in checks.items() if matched)),
        missing_capabilities=missing,
        exclusion_reasons=exclusions,
        reasons=tuple(key for key, matched in checks.items() if matched),
    )
