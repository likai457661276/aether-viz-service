from __future__ import annotations

from aetherviz_service.aetherviz.workflow.plan_contract import normalize_plan_with_diagnostics
from aetherviz_service.aetherviz.workflow.plan_diagnostics import check_plan_consistency


def test_normalization_reports_dropped_cross_field_references() -> None:
    result = normalize_plan_with_diagnostics(
        {
            "interactive_type": "simulation",
            "interactive_spec": {
                "type": "simulation",
                "concept": "函数联动",
                "description": "参数驱动函数图像",
                "variables": [{"name": "theta", "min": 0, "max": 6.28, "default": 0}],
            },
            "representation_spec": {
                "views": [{"id": "graph", "kind": "coordinate_plane"}],
                "state_variables": [{"id": "angle", "semantic_type": "angle"}],
                "correspondences": [
                    {
                        "type": "shared_parameter",
                        "source_view": "missing",
                        "target_view": "graph",
                        "parameter": "angle",
                    }
                ],
            },
        },
        "函数图像联动",
    )

    codes = {item.code for item in result.diagnostics}
    assert "state_variable_reference_missing" in codes
    assert "correspondence_view_reference_missing" in codes
    assert "correspondence_parameter_reference_missing" in codes
    assert check_plan_consistency(result.plan) == ()


def test_normalization_reports_inferred_representation_fields() -> None:
    result = normalize_plan_with_diagnostics({}, "旋转向量与正弦图像联动")

    inferred_fields = {
        item.field
        for item in result.diagnostics
        if item.code == "representation_field_inferred"
    }
    assert "representation_spec.views" in inferred_fields
    assert "representation_spec.correspondences" in inferred_fields


def test_consistency_check_rejects_single_view_shared_parameter() -> None:
    diagnostics = check_plan_consistency(
        {
            "interactive_spec": {"variables": [{"name": "x"}]},
            "representation_spec": {
                "views": [{"id": "graph", "kind": "coordinate_plane"}],
                "state_variables": [{"id": "x"}],
                "correspondences": [
                    {
                        "type": "shared_parameter",
                        "source_view": "graph",
                        "target_view": "graph",
                        "parameter": "x",
                    }
                ],
            },
        }
    )

    assert [item.code for item in diagnostics] == ["cross_view_relation_uses_single_view"]
