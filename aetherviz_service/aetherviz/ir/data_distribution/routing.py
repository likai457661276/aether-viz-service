"""Capability routing for deterministic data and statistics scenes."""

from __future__ import annotations

from typing import Any

from aetherviz_service.aetherviz.ir.router.contracts import IRRouteAssessment, IRRoutingProfile

PROFILE = IRRoutingProfile(
    description="共享同一数据源的表格、统计图和确定性派生统计量，由服务端统一分箱、汇总和回归。",
    capabilities=frozenset(
        {
            "data_chart",
            "data_table",
            "bar_chart",
            "line_chart",
            "scatter_plot",
            "histogram",
            "box_plot",
            "descriptive_statistics",
            "linear_regression",
            "deterministic_binning",
        }
    ),
    required_capabilities=frozenset({"data_chart", "state_parameter", "shared_dataset"}),
    supported_view_kinds=frozenset({"data_chart", "symbolic_panel"}),
    exclusions=("随机试验累计", "连续概率密度面积", "包含几何或坐标构造视图"),
)


def assess(plan: dict[str, Any]) -> IRRouteAssessment:
    spec = plan.get("representation_spec") if isinstance(plan.get("representation_spec"), dict) else {}
    views = [item for item in spec.get("views", []) if isinstance(item, dict)]
    kinds = {str(item.get("kind") or "") for item in views}
    states = [item for item in spec.get("state_variables", []) if isinstance(item, dict)]
    relations = {str(item.get("type") or "") for item in spec.get("correspondences", []) if isinstance(item, dict)}
    profile = plan.get("knowledge_profile") if isinstance(plan.get("knowledge_profile"), dict) else {}
    data_chart = "data_chart" in kinds
    supported_views = bool(kinds) and kinds <= PROFILE.supported_view_kinds
    shared_dataset = data_chart and (len(views) == 1 or bool(relations & {"equal_value", "derived_value", "transform"}))
    prior = profile.get("representation_type") in {"data_chart", "data_distribution"}
    concept_family = profile.get("concept_family") == "probability_statistics"
    text = " ".join(
        str(value or "")
        for value in (
            plan.get("source_topic"),
            (plan.get("interactive_spec") or {}).get("concept"),
            (plan.get("interactive_spec") or {}).get("description"),
        )
    )
    stochastic = any(token in text for token in ("随机试验", "重复抽样", "累计频率", "蒙特卡洛", "掷骰"))
    density_area = any(
        token in text for token in ("概率密度", "区间面积", "正态分布曲线", "二项分布", "概率质量", "理论概率")
    )
    foreign_view = bool(kinds & {"geometric_scene", "coordinate_plane", "number_line", "object_scene"})
    checks = {
        "data_chart": data_chart,
        "state_parameter": bool(states),
        "shared_dataset": shared_dataset,
        "supported_views": supported_views,
        "profile_prior": prior,
        "statistics_family": concept_family,
    }
    weights = {
        "data_chart": 0.28,
        "state_parameter": 0.16,
        "shared_dataset": 0.22,
        "supported_views": 0.14,
        "profile_prior": 0.12,
        "statistics_family": 0.08,
    }
    required = {"data_chart", "state_parameter", "shared_dataset", "supported_views"}
    missing = tuple(sorted(key for key in required if not checks[key]))
    exclusions = tuple(
        reason
        for condition, reason in (
            (stochastic, "计划要求随机试验或重复抽样累计"),
            (density_area, "计划要求连续概率密度或区间面积"),
            (foreign_view, "计划包含不受支持的几何或坐标视图"),
        )
        if condition
    )
    return IRRouteAssessment(
        backend_key="data_distribution_scene",
        eligible=not missing and not exclusions,
        score=round(sum(weights[key] for key, matched in checks.items() if matched), 3),
        matched_capabilities=tuple(sorted(key for key, matched in checks.items() if matched)),
        missing_capabilities=missing,
        exclusion_reasons=exclusions,
        reasons=tuple(key for key, matched in checks.items() if matched),
    )
