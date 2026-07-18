"""Capability routing for discrete parametric geometry convergence scenes."""

from __future__ import annotations

from typing import Any

from aetherviz_service.aetherviz.ir.router.contracts import IRRouteAssessment, IRRoutingProfile

PROFILE = IRRoutingProfile(
    description="离散参数驱动圆与正多边形构造、边界测量和误差收敛，节点与动画由服务端统一管理。",
    capabilities=frozenset(
        {"geometric_scene", "regular_polygon", "discrete_parameter", "derived_measure", "convergence"}
    ),
    required_capabilities=frozenset({"geometric_scene", "discrete_parameter", "derived_measure"}),
    supported_view_kinds=frozenset({"geometric_scene", "data_chart"}),
    exclusions=("连续自由拖拽构造", "割补重排", "没有离散几何参数或派生测量"),
)


def assess(plan: dict[str, Any]) -> IRRouteAssessment:
    spec = plan.get("representation_spec") if isinstance(plan.get("representation_spec"), dict) else {}
    views = [item for item in spec.get("views", []) if isinstance(item, dict)]
    kinds = {str(item.get("kind") or "") for item in views}
    states = [item for item in spec.get("state_variables", []) if isinstance(item, dict)]
    relations = {str(item.get("type") or "") for item in spec.get("correspondences", []) if isinstance(item, dict)}
    invariants = {str(item) for item in spec.get("required_invariants", [])}
    prior = (
        isinstance(plan.get("knowledge_profile"), dict)
        and plan["knowledge_profile"].get("representation_type") == "geometric_construction"
    )
    geometric = "geometric_scene" in kinds
    discrete = any(item.get("semantic_type") == "discrete" and float(item.get("maximum", 0)) >= 4 for item in states)
    derived = "derived_value" in relations or "data_chart" in kinds
    recomposition = "decompose_recompose" in relations or bool(
        invariants & {"piece_identity_preserved", "piece_congruence", "area_preserved"}
    )
    checks = {
        "geometric_scene": geometric,
        "discrete_parameter": discrete,
        "derived_measure": derived,
        "profile_prior": prior,
        "convergence": "data_chart" in kinds,
    }
    weights = {
        "geometric_scene": 0.30,
        "discrete_parameter": 0.28,
        "derived_measure": 0.22,
        "profile_prior": 0.12,
        "convergence": 0.08,
    }
    missing = tuple(key for key in ("geometric_scene", "discrete_parameter", "derived_measure") if not checks[key])
    exclusions = ("计划要求割补重排，应使用 recomposition IR",) if recomposition else ()
    return IRRouteAssessment(
        backend_key="parametric_geometry_scene",
        eligible=not missing and not exclusions,
        score=round(sum(weights[key] for key, matched in checks.items() if matched), 3),
        matched_capabilities=tuple(sorted(key for key, matched in checks.items() if matched)),
        missing_capabilities=missing,
        exclusion_reasons=exclusions,
        reasons=tuple(key for key, matched in checks.items() if matched),
    )
