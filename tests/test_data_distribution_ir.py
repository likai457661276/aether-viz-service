from __future__ import annotations

from copy import deepcopy

from aetherviz_service.aetherviz.contracts.validation.js_checker import check_inline_javascript
from aetherviz_service.aetherviz.ir.data_distribution.contract import (
    DATA_DISTRIBUTION_IR_VERSION,
    compile_data_distribution_ir,
    derive_statistics,
    rank_data_distribution_ir_candidates,
    validate_data_distribution_ir,
)
from aetherviz_service.aetherviz.ir.data_distribution.runtime import assemble_data_distribution_business_html
from aetherviz_service.aetherviz.ir.registry import DEFAULT_IR_REGISTRY
from aetherviz_service.aetherviz.ir.router.service import resolve_generation_route
from aetherviz_service.aetherviz.workflow.plan_contract import normalize_plan


def _plan() -> dict:
    return normalize_plan(
        {
            "interactive_type": "simulation",
            "interactive_spec": {
                "type": "simulation",
                "concept": "数据分布与分箱",
                "description": "保持样本身份，改变数据缩放并比较多种统计图",
                "variables": [{"name": "scale", "label": "数据缩放", "min": 0.5, "max": 2, "step": 0.1, "default": 1}],
                "presets": [],
                "observations": ["图表与统计量来自同一数据源"],
            },
            "knowledge_profile": {
                "subject": "math",
                "concept_family": "probability_statistics",
                "representation_type": "data_chart",
                "pedagogy_pattern": "parameter_exploration",
            },
            "representation_spec": {
                "views": [
                    {"id": "chart", "kind": "data_chart", "role": "多种统计图"},
                    {"id": "measure", "kind": "symbolic_panel", "role": "派生统计量"},
                ],
                "state_variables": [{"id": "scale", "semantic_type": "ratio"}],
                "correspondences": [
                    {"type": "derived_value", "source_view": "chart", "target_view": "measure", "parameter": "scale"}
                ],
                "required_invariants": ["equal_value"],
                "interaction_requirements": ["scrub", "play", "pause", "reset"],
            },
        },
        "改变数据缩放，比较表格、统计图和派生统计量",
    )


def _value(base: float) -> dict:
    return {"op": "mul", "args": [base, {"state": "scale"}]}


def _ir() -> dict:
    values = [("甲", 1, 2), ("乙", 2, 3), ("丙", 3, 5), ("丁", 4, 4), ("戊", 5, 7)]
    return {
        "version": DATA_DISTRIBUTION_IR_VERSION,
        "animation": {"variable": "scale", "from": 0.5, "to": 2, "default": 1, "duration": 6},
        "fields": [
            {"id": "name", "label": "样本", "type": "category"},
            {"id": "x", "label": "序号", "type": "number"},
            {"id": "value", "label": "数值", "type": "number", "unit": "分"},
        ],
        "rows": [
            {
                "id": f"row-{index}",
                "cells": [
                    {"field": "name", "value": name},
                    {"field": "x", "value": x},
                    {"field": "value", "value": _value(value)},
                ],
            }
            for index, (name, x, value) in enumerate(values)
        ],
        "charts": [
            {"id": "table", "type": "table", "title": "原始数据表"},
            {"id": "bar", "type": "bar", "title": "柱状图", "category_field": "name", "value_field": "value"},
            {"id": "line", "type": "line", "title": "折线图", "x_field": "x", "y_field": "value"},
            {"id": "hist", "type": "histogram", "title": "直方图", "value_field": "value", "bin_width": 2},
        ],
        "metrics": [
            {"id": "mean", "type": "mean", "label": "均值", "field": "value", "precision": 2},
            {"id": "median", "type": "median", "label": "中位数", "field": "value", "precision": 2},
            {"id": "variance", "type": "variance", "label": "总体方差", "field": "value", "precision": 2},
            {
                "id": "regression",
                "type": "linear_regression",
                "label": "回归",
                "x_field": "x",
                "y_field": "value",
                "precision": 2,
            },
        ],
        "observation": "缩放数据时，样本身份不变，均值和离散程度与图形同步更新。",
    }


def test_data_distribution_ir_validates_compiles_derives_and_uses_server_runtime() -> None:
    plan, ir = _plan(), _ir()

    assert validate_data_distribution_ir(ir, plan)["ok"]
    assert DATA_DISTRIBUTION_IR_VERSION in compile_data_distribution_ir(ir, plan)
    derived = derive_statistics(ir, {"scale": 1})
    assert derived["mean"] == 4.2
    assert round(derived["variance"], 2) == 2.96
    assert round(derived["regression"]["slope"], 2) == 1.1

    business_html = assemble_data_distribution_business_html(ir, plan, "数据分布")
    assert 'id="data-distribution-ir"' in business_html
    assert "window.AetherVizAnimationController.create" in business_html
    assert "window.AetherVizRuntime" in business_html
    assert "requestAnimationFrame" not in business_html
    assert check_inline_javascript(business_html)["ok"]


def test_data_distribution_ir_rejects_incomplete_rows_and_excessive_bins() -> None:
    incomplete = deepcopy(_ir())
    incomplete["rows"][0]["cells"].pop()
    report = validate_data_distribution_ir(incomplete, _plan())
    assert any(item["type"] == "invalid_distribution_row_cells" for item in report["errors"])

    excessive = deepcopy(_ir())
    excessive["charts"][3]["bin_width"] = 0.01
    report = validate_data_distribution_ir(excessive, _plan())
    assert any(item["type"] == "distribution_derivation_failed" for item in report["errors"])


def test_data_distribution_candidate_ranking_prefers_valid_candidate() -> None:
    invalid = deepcopy(_ir())
    invalid["metrics"][0]["field"] = "missing"

    ranking = rank_data_distribution_ir_candidates([invalid, _ir()], _plan())

    assert ranking["ok"]
    assert ranking["selected_ir"]["metrics"][0]["field"] == "value"


def test_data_distribution_supports_scatter_and_grouped_box_views() -> None:
    ir = deepcopy(_ir())
    ir["charts"] = [
        {"id": "scatter", "type": "scatter", "title": "散点图", "x_field": "x", "y_field": "value"},
        {"id": "box", "type": "box", "title": "箱线图", "value_field": "value", "group_field": "name"},
    ]

    assert validate_data_distribution_ir(ir, _plan())["ok"]
    business_html = assemble_data_distribution_business_html(ir, _plan(), "散点图与箱线图")
    assert "renderXY" in business_html
    assert "renderBox" in business_html
    assert check_inline_javascript(business_html)["ok"]


def test_data_distribution_routes_supported_plan_but_excludes_random_sampling() -> None:
    route = resolve_generation_route(_plan())
    assert route.selected_backend == "data_distribution_scene"
    backend = DEFAULT_IR_REGISTRY.get("data_distribution_scene")
    assert backend is not None and backend.assess is not None and backend.assess(_plan()).eligible

    random_plan = deepcopy(_plan())
    random_plan["interactive_spec"]["concept"] = "重复抽样"
    random_plan["interactive_spec"]["description"] = "重复抽样并累计样本均值"
    assert not backend.assess(random_plan).eligible
