"""Capability routing for exact symbolic derivations."""

from __future__ import annotations

from typing import Any

from aetherviz_service.aetherviz.ir.router.contracts import IRRouteAssessment, IRRoutingProfile

PROFILE = IRRoutingProfile(
    description="表达式 AST、方程与受限等价变换步骤，由服务端逐步验证多项式恒等性或方程等价性。",
    capabilities=frozenset(
        {"symbolic_derivation", "equation_solving", "factorization", "identity_transform", "formula_derivation"}
    ),
    required_capabilities=frozenset({"symbolic_panel", "ordered_steps"}),
    supported_view_kinds=frozenset({"symbolic_panel"}),
    exclusions=("超越方程", "不等式解集", "数值近似证明", "几何或数据图联动"),
)


def assess(plan: dict[str, Any]) -> IRRouteAssessment:
    spec = plan.get("representation_spec") if isinstance(plan.get("representation_spec"), dict) else {}
    views = [item for item in spec.get("views", []) if isinstance(item, dict)]
    kinds = {str(item.get("kind") or "") for item in views}
    profile = plan.get("knowledge_profile") if isinstance(plan.get("knowledge_profile"), dict) else {}
    text = " ".join(
        str(value or "")
        for value in (
            plan.get("source_topic"),
            (plan.get("interactive_spec") or {}).get("concept"),
            (plan.get("interactive_spec") or {}).get("description"),
        )
    )
    symbolic = bool(kinds) and kinds <= PROFILE.supported_view_kinds and "symbolic_panel" in kinds
    ordered = any(token in text for token in ("推导", "求解", "因式分解", "恒等", "化简", "公式"))
    prior = profile.get("representation_type") in {"symbolic_derivation", "equation_derivation"}
    unsupported = any(token in text for token in ("三角方程", "指数方程", "对数方程", "不等式", "近似解", "数值解"))
    foreign = bool(kinds & {"geometric_scene", "coordinate_plane", "number_line", "data_chart", "object_scene"})
    checks = {"symbolic_panel": symbolic, "ordered_steps": ordered, "profile_prior": prior}
    missing = tuple(sorted(key for key in ("symbolic_panel", "ordered_steps") if not checks[key]))
    exclusions = tuple(
        reason
        for condition, reason in ((unsupported, "计划超出受限多项式等价变换"), (foreign, "计划包含非符号视图"))
        if condition
    )
    return IRRouteAssessment(
        backend_key="symbolic_derivation_scene",
        eligible=not missing and not exclusions,
        score=round((0.45 if symbolic else 0) + (0.35 if ordered else 0) + (0.2 if prior else 0), 3),
        matched_capabilities=tuple(sorted(key for key, value in checks.items() if value)),
        missing_capabilities=missing,
        exclusion_reasons=exclusions,
        reasons=tuple(key for key, value in checks.items() if value),
    )
