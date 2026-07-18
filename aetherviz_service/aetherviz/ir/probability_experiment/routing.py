"""Capability routing for finite seeded probability experiments."""

from __future__ import annotations

from typing import Any

from aetherviz_service.aetherviz.ir.router.contracts import IRRouteAssessment, IRRoutingProfile

PROFILE = IRRoutingProfile(
    description="有限样本空间、固定种子随机试验、事件频率累计、概率树和大数收敛。",
    capabilities=frozenset(
        {"finite_sample_space", "seeded_random_trial", "cumulative_frequency", "probability_tree", "convergence"}
    ),
    required_capabilities=frozenset({"probability_view", "state_parameter", "finite_sample_space"}),
    supported_view_kinds=frozenset({"probability_experiment", "probability_tree", "data_chart", "symbolic_panel"}),
    exclusions=("连续概率密度", "无限样本空间", "马尔可夫链", "贝叶斯网络"),
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
    probability = bool(kinds & {"probability_experiment", "probability_tree"})
    finite = any(token in text for token in ("随机试验", "样本空间", "频率", "概率树", "掷骰", "抛硬币", "抽取"))
    prior = profile.get("representation_type") in {"probability_experiment", "probability_tree"}
    supported = bool(kinds) and kinds <= PROFILE.supported_view_kinds
    continuous = any(token in text for token in ("概率密度", "正态分布", "连续分布", "曲线下面积"))
    advanced = any(token in text for token in ("马尔可夫", "贝叶斯网络", "无限样本"))
    checks = {
        "probability_view": probability,
        "state_parameter": bool(states),
        "finite_sample_space": finite,
        "supported_views": supported,
        "profile_prior": prior,
    }
    required = {"probability_view", "state_parameter", "finite_sample_space", "supported_views"}
    missing = tuple(sorted(key for key in required if not checks[key]))
    exclusions = tuple(
        reason
        for condition, reason in ((continuous, "计划要求连续概率模型"), (advanced, "计划要求首版不支持的高级随机过程"))
        if condition
    )
    weights = {
        "probability_view": 0.28,
        "state_parameter": 0.16,
        "finite_sample_space": 0.24,
        "supported_views": 0.14,
        "profile_prior": 0.18,
    }
    return IRRouteAssessment(
        backend_key="probability_experiment_scene",
        eligible=not missing and not exclusions,
        score=round(sum(weights[key] for key, value in checks.items() if value), 3),
        matched_capabilities=tuple(sorted(key for key, value in checks.items() if value)),
        missing_capabilities=missing,
        exclusion_reasons=exclusions,
        reasons=tuple(key for key, value in checks.items() if value),
    )
