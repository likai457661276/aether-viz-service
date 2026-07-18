"""Capability routing for finite discrete structures."""

from __future__ import annotations

from typing import Any

from aetherviz_service.aetherviz.ir.router.contracts import IRRouteAssessment, IRRoutingProfile

PROFILE = IRRoutingProfile(
    description="有限节点身份、边拓扑、集合成员、排列顺序和显式递推项，由服务端管理布局与阶段变化。",
    capabilities=frozenset(
        {
            "finite_graph",
            "rooted_tree",
            "set_membership",
            "permutation",
            "combination",
            "finite_sequence",
            "topology_reveal",
        }
    ),
    required_capabilities=frozenset({"discrete_view", "state_parameter", "stable_identity"}),
    supported_view_kinds=frozenset(
        {"discrete_structure", "graph", "tree", "set_diagram", "sequence", "symbolic_panel"}
    ),
    exclusions=("连续几何", "加权最短路算法执行", "无限递归", "动态图编辑器"),
)


def assess(plan: dict[str, Any]) -> IRRouteAssessment:
    spec = plan.get("representation_spec") if isinstance(plan.get("representation_spec"), dict) else {}
    views = [item for item in spec.get("views", []) if isinstance(item, dict)]
    kinds = {str(item.get("kind") or "") for item in views}
    states = [item for item in spec.get("state_variables", []) if isinstance(item, dict)]
    profile = plan.get("knowledge_profile") if isinstance(plan.get("knowledge_profile"), dict) else {}
    text = " ".join(
        str(value or "")
        for value in (
            plan.get("source_topic"),
            (plan.get("interactive_spec") or {}).get("concept"),
            (plan.get("interactive_spec") or {}).get("description"),
        )
    )
    discrete = bool(kinds & {"discrete_structure", "graph", "tree", "set_diagram", "sequence"})
    identity = any(token in text for token in ("排列", "组合", "树", "图", "集合", "递推", "序列", "节点", "拓扑"))
    supported = bool(kinds) and kinds <= PROFILE.supported_view_kinds
    prior = profile.get("representation_type") in {"discrete_structure", "graph_structure", "combinatorial_structure"}
    foreign = bool(
        kinds & {"geometric_scene", "coordinate_plane", "number_line", "data_chart", "probability_experiment"}
    )
    advanced = any(token in text for token in ("最短路动画", "最大流", "无限递归", "自由编辑图"))
    checks = {
        "discrete_view": discrete,
        "state_parameter": bool(states),
        "stable_identity": identity,
        "supported_views": supported,
        "profile_prior": prior,
    }
    required = {"discrete_view", "state_parameter", "stable_identity", "supported_views"}
    missing = tuple(sorted(key for key in required if not checks[key]))
    exclusions = tuple(
        reason
        for condition, reason in (
            (foreign, "计划包含连续或统计视图"),
            (advanced, "计划要求首版不支持的图算法或编辑能力"),
        )
        if condition
    )
    weights = {
        "discrete_view": 0.28,
        "state_parameter": 0.15,
        "stable_identity": 0.24,
        "supported_views": 0.15,
        "profile_prior": 0.18,
    }
    return IRRouteAssessment(
        backend_key="discrete_structure_scene",
        eligible=not missing and not exclusions,
        score=round(sum(weights[key] for key, value in checks.items() if value), 3),
        matched_capabilities=tuple(sorted(key for key, value in checks.items() if value)),
        missing_capabilities=missing,
        exclusion_reasons=exclusions,
        reasons=tuple(key for key, value in checks.items() if value),
    )
