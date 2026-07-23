"""Tests for TeachingPlan / GenerationSpec field ownership and composition."""

from __future__ import annotations

from aetherviz_service.aetherviz.schemas.aetherviz import (
    GENERATION_SPEC_FIELDS as SCHEMA_GENERATION_SPEC_FIELDS,
)
from aetherviz_service.aetherviz.schemas.aetherviz import (
    TEACHING_PLAN_FIELDS as SCHEMA_TEACHING_PLAN_FIELDS,
)
from aetherviz_service.aetherviz.schemas.aetherviz import (
    AetherVizGenerationSpec,
    AetherVizTeachingPlan,
)
from aetherviz_service.aetherviz.workflow.plan_contract import (
    normalize_plan,
    normalize_plan_with_diagnostics,
)
from aetherviz_service.aetherviz.workflow.plan_layers import (
    GENERATION_SPEC_FIELD_SET,
    GENERATION_SPEC_FIELDS,
    LIFECYCLE_FIELD_SET,
    TEACHING_PLAN_FIELD_SET,
    TEACHING_PLAN_FIELDS,
    extract_generation_spec,
    extract_teaching_plan,
    merge_plan_layers,
    split_plan_layers,
)


def test_schema_and_workflow_field_ownership_stay_in_sync() -> None:
    assert tuple(SCHEMA_TEACHING_PLAN_FIELDS) == TEACHING_PLAN_FIELDS
    assert tuple(SCHEMA_GENERATION_SPEC_FIELDS) == GENERATION_SPEC_FIELDS
    assert TEACHING_PLAN_FIELD_SET.isdisjoint(GENERATION_SPEC_FIELD_SET)
    assert TEACHING_PLAN_FIELD_SET.isdisjoint(LIFECYCLE_FIELD_SET)
    assert GENERATION_SPEC_FIELD_SET.isdisjoint(LIFECYCLE_FIELD_SET)


def test_normalize_plan_still_returns_flat_union_of_layers() -> None:
    plan = normalize_plan({}, "勾股定理拼图重排证明")
    teaching = extract_teaching_plan(plan)
    generation = extract_generation_spec(plan)

    assert set(teaching) <= TEACHING_PLAN_FIELD_SET
    assert set(generation) <= GENERATION_SPEC_FIELD_SET
    assert teaching["title"]
    assert teaching["goal"]
    assert teaching["interactive_type"] in {"simulation", "diagram", "game"}
    assert generation["page_type"] == "interactive"
    assert generation["representation_spec"]["version"] == "1.0"
    assert "play-animation" not in {item["id"] for item in teaching["controls"]}
    assert "play-animation" in {item["id"] for item in plan["controls"]}
    assert "play-animation" in {item["id"] for item in generation["runtime_controls"]}

    rebuilt = merge_plan_layers(teaching, generation)
    for field in TEACHING_PLAN_FIELDS:
        assert rebuilt[field] == plan[field]
    for field in GENERATION_SPEC_FIELDS:
        if field == "recomposition_spec" and field not in plan:
            continue
        assert rebuilt.get(field) == plan.get(field)


def test_split_and_merge_round_trip_preserves_lifecycle() -> None:
    plan = normalize_plan({}, "一次函数图像")
    plan["status"] = "draft"
    plan["plan_id"] = "plan-test"
    teaching, generation, lifecycle = split_plan_layers(plan)
    merged = merge_plan_layers(teaching, generation, lifecycle=lifecycle)
    assert merged["status"] == "draft"
    assert merged["plan_id"] == "plan-test"
    assert merged["title"] == plan["title"]
    assert merged["representation_spec"] == plan["representation_spec"]


def test_teaching_and_generation_pydantic_models_accept_extracted_layers() -> None:
    plan = normalize_plan({}, "单位圆与正弦")
    teaching = extract_teaching_plan(plan)
    generation = extract_generation_spec(plan)
    parsed_teaching = AetherVizTeachingPlan.model_validate(teaching)
    parsed_generation = AetherVizGenerationSpec.model_validate(generation)
    assert parsed_teaching.title == teaching["title"]
    assert parsed_generation.subject == generation["subject"]
    assert parsed_generation.runtime.render_stack


def test_normalize_plan_with_diagnostics_still_emits_consistency_checks() -> None:
    result = normalize_plan_with_diagnostics({}, "勾股定理")
    assert result.plan["title"]
    assert isinstance(result.diagnostics, tuple)
