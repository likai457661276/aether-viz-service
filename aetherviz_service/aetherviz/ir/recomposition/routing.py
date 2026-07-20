"""Routing capability declaration for geometric decomposition/recomposition."""

from __future__ import annotations

from typing import Any

from aetherviz_service.aetherviz.ir.recomposition.feasibility import (
    evaluate_recomposition_plan_feasibility,
    format_recomposition_feasibility_errors,
)
from aetherviz_service.aetherviz.ir.router.contracts import IRRouteAssessment, IRRoutingProfile

PROFILE = IRRoutingProfile(
    description="几何对象切分为稳定图元，经独立变换、拖拽吸附和中间状态重排后形成目标拼合并证明度量关系。",
    capabilities=frozenset(
        {
            "piece_decomposition",
            "piece_transform",
            "target_assembly",
            "geometry_invariant",
            "piece_drag",
            "snap_target",
            "preset",
            "progressive_reveal",
        }
    ),
    required_capabilities=frozenset({"piece_decomposition", "piece_transform"}),
    supported_view_kinds=frozenset({"geometric_scene"}),
    exclusions=("仅作图或拖动控制点", "没有切分重排", "没有稳定拼片集合"),
)


def assess(plan: dict[str, Any]) -> IRRouteAssessment:
    spec = plan.get("representation_spec") if isinstance(plan.get("representation_spec"), dict) else {}
    relations = {str(item.get("type") or "") for item in spec.get("correspondences", []) if isinstance(item, dict)}
    invariants = {str(item) for item in spec.get("required_invariants", [])}
    interactions = {str(item) for item in spec.get("interaction_requirements", []) if str(item)}
    supported_interactions = {"drag", "preset", "reveal", "trace", "scrub", "play", "pause", "reset"}
    recomposition = plan.get("recomposition_spec") if isinstance(plan.get("recomposition_spec"), dict) else {}
    stages = ((recomposition.get("proof_constraints") or {}).get("stage_requirements") or []) if recomposition else []
    feasibility = evaluate_recomposition_plan_feasibility(plan)
    checks = {
        "piece_decomposition": "decompose_recompose" in relations or bool(recomposition),
        "piece_transform": len(stages) >= 3,
        "geometry_invariant": bool(invariants & {"piece_identity_preserved", "piece_congruence", "area_preserved"}),
        "target_assembly": bool((recomposition.get("proof_constraints") or {}).get("target_assembly"))
        if recomposition
        else False,
        "profile_prior": ((plan.get("knowledge_profile") or {}).get("representation_type") == "geometric_recomposition")
        if isinstance(plan.get("knowledge_profile"), dict)
        else False,
        "supported_interactions": interactions <= supported_interactions,
    }
    weights = {
        "piece_decomposition": 0.30,
        "piece_transform": 0.30,
        "geometry_invariant": 0.20,
        "target_assembly": 0.15,
        "profile_prior": 0.05,
        "supported_interactions": 0.0,
    }
    score = round(sum(weights[key] for key, matched in checks.items() if matched), 3)
    required = {"piece_decomposition", "piece_transform", "geometry_invariant"}
    missing = tuple(sorted(key for key in required if not checks[key]))
    exclusions = tuple(
        reason
        for condition, reason in (
            (not checks["piece_decomposition"], "计划没有可验证的切分重排阶段"),
            (
                not checks["supported_interactions"],
                "计划包含几何重排运行时不支持的交互类型",
            ),
            (
                not feasibility["ok"],
                format_recomposition_feasibility_errors(feasibility),
            ),
        )
        if condition
    )
    return IRRouteAssessment(
        backend_key="recomposition_scene",
        eligible=not missing and not exclusions,
        score=score,
        matched_capabilities=tuple(sorted(key for key, matched in checks.items() if matched)),
        missing_capabilities=missing,
        exclusion_reasons=exclusions,
        reasons=tuple(key for key, matched in checks.items() if matched),
    )
