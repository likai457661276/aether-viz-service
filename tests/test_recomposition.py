from __future__ import annotations

import json
from copy import deepcopy

import pytest

from aetherviz_service.aetherviz.contracts.html_stream import HtmlGenerationError
from aetherviz_service.aetherviz.contracts.layout import assemble_layout_contract
from aetherviz_service.aetherviz.contracts.pipeline import (
    _accept_hard_repair_candidate,
    _hard_error_only_report,
)
from aetherviz_service.aetherviz.contracts.validation.animation_lifecycle_checker import check_animation_lifecycle
from aetherviz_service.aetherviz.contracts.validation.report import build_validation_report
from aetherviz_service.aetherviz.generate.workflow import run_generate_workflow
from aetherviz_service.aetherviz.ir.recomposition.assembly import (
    analyze_footprint_scale,
    evaluate_target_assembly,
    piece_local_polygon,
    scale_scene_footprints_into_canvas,
    translate_target_assembly_into_canvas,
)
from aetherviz_service.aetherviz.ir.recomposition.construction import (
    materialize_target_construction,
)
from aetherviz_service.aetherviz.ir.recomposition.contract import (
    GEOMETRY_IR_VERSION,
    build_deterministic_geometry_ir,
    compile_geometry_ir,
    expand_geometry_ir,
    geometry_ir_candidates_response_schema,
    geometry_ir_response_schema,
    normalize_geometry_ir,
    parse_geometry_ir,
    parse_geometry_ir_candidates,
    sample_geometry_states,
    validate_geometry_ir,
)
from aetherviz_service.aetherviz.ir.recomposition.feasibility import (
    evaluate_recomposition_plan_feasibility,
)
from aetherviz_service.aetherviz.ir.recomposition.math import (
    evaluate_mathematical_invariants,
)
from aetherviz_service.aetherviz.ir.recomposition.ranking import rank_geometry_ir_candidates
from aetherviz_service.aetherviz.ir.recomposition.runtime import (
    assemble_recomposition_business_html,
    build_deterministic_scene_module,
)
from aetherviz_service.aetherviz.ir.recomposition.scene_contract import validate_scene_module
from aetherviz_service.aetherviz.ir.recomposition.semantics import (
    INTERMEDIATE_EVIDENCE_THRESHOLDS,
    evaluate_intermediate_transform_evidence,
    evaluate_recomposition_semantics,
)
from aetherviz_service.aetherviz.ir.recomposition.waypoints import (
    complete_intermediate_waypoints,
)
from aetherviz_service.aetherviz.ir.router.service import resolve_generation_route
from aetherviz_service.aetherviz.tools.function_patch import (
    apply_function_replacements,
    describe_target_functions,
    repair_function_targets,
    target_functions_from_report,
)
from aetherviz_service.aetherviz.workflow.knowledge_profile import build_knowledge_profile
from aetherviz_service.aetherviz.workflow.plan_contract import normalize_plan
from aetherviz_service.config import settings
from evals.evaluators.deterministic import html_hard_validation_pass


@pytest.mark.parametrize(
    "topic",
    [
        "圆的面积推导",
        "平行四边形面积割补推导",
        "三角形面积复制拼合推导",
        "梯形面积复制重排推导",
        "菱形面积按对角线切分重排推导",
        "勾股定理拼图重排证明",
        "扇形面积等分重排推导",
        "椭圆面积分割重排推导",
        "正六边形面积拆分拼合推导",
        "弓形面积割补推导",
        "组合图形面积切割重排证明",
    ],
)
def test_recomposition_profile_generalizes_across_topics(topic: str) -> None:
    profile = build_knowledge_profile(topic)
    assert profile["representation_type"] == "geometric_recomposition"
    assert profile["pedagogy_pattern"] == "decompose_recompose_proof"


@pytest.mark.parametrize("topic", ["用尺规作三角形", "测量圆周角", "动态构造理解几何定理证明"])
def test_recomposition_profile_does_not_capture_plain_construction(topic: str) -> None:
    assert build_knowledge_profile(topic)["representation_type"] != "geometric_recomposition"


def test_normalized_plan_overrides_stale_profile_and_classifies_state_variables() -> None:
    plan = normalize_plan(
        {
            "knowledge_profile": {
                "representation_type": "geometric_construction",
                "pedagogy_pattern": "proof_animation",
            },
            "interactive_spec": {
                "variables": [
                    {"name": "pieceCount", "label": "分块数", "min": 4, "max": 20, "default": 8},
                    {"name": "radius", "label": "半径", "min": 1, "max": 8, "default": 4},
                ]
            },
        },
        "圆的面积推导",
    )
    assert plan["knowledge_profile"]["representation_type"] == "geometric_recomposition"
    assert plan["recomposition_spec"]["topology_variables"] == ["pieceCount"]
    assert plan["recomposition_spec"]["geometry_variables"] == ["radius"]
    assert plan["recomposition_spec"]["proof_constraints"]["measure_invariants"] == [
        "area_preserved",
        "piece_congruence",
    ]


def test_fractional_length_controls_cannot_be_requested_as_topology_variables() -> None:
    plan = normalize_plan(
        {
            "knowledge_profile": {"representation_type": "geometric_recomposition"},
            "interactive_spec": {
                "variables": [
                    {"name": "a", "label": "长度 a", "min": 2, "max": 8, "default": 3, "step": 0.5},
                    {"name": "b", "label": "长度 b", "min": 2, "max": 15, "default": 4, "step": 0.5},
                ]
            },
            "recomposition_spec": {
                "topology_variables": ["a", "b"],
                "geometry_variables": [],
            },
        },
        "通用几何面积拼图验证",
    )

    assert plan["recomposition_spec"]["topology_variables"] == []
    assert plan["recomposition_spec"]["geometry_variables"] == ["a", "b"]


def test_deterministic_fallback_uses_a_readable_visual_footprint() -> None:
    plan = normalize_plan(
        {
            "knowledge_profile": {"representation_type": "geometric_recomposition"},
            "interactive_spec": {
                "variables": [
                    {"name": "a", "label": "长度 a", "min": 2, "max": 8, "default": 3, "step": 0.5},
                    {"name": "b", "label": "长度 b", "min": 2, "max": 15, "default": 4, "step": 0.5},
                ]
            },
            "recomposition_spec": {
                "topology_variables": ["a", "b"],
                "proof_constraints": {
                    "target_assembly": [
                        {
                            "id": "target-rectangle",
                            "type": "approximate_rectangle",
                            "max_components": 1,
                            "max_overlap_ratio": 0.1,
                            "min_rectangularity": 0.62,
                        }
                    ]
                },
            },
        },
        "通用几何面积拼图验证",
    )

    report = rank_geometry_ir_candidates([build_deterministic_geometry_ir(plan)], plan)

    assert report["ok"]
    safety = report["candidates"][0]["details"]["motion_safety"]
    assert safety["footprint_score"] >= 0.55
    assert "safety:undersized_visual_footprint" not in report["candidates"][0]["hard_failures"]


def test_candidate_ranking_rejects_an_undersized_visible_union() -> None:
    plan = normalize_plan({}, "组合图形面积切割重排证明")
    candidate = build_deterministic_geometry_ir(plan)
    candidate["pieces"][0]["attrs"]["points"] = "0,0 12,0 0,12"
    candidate["pieces"][0]["target"]["x"] = 420
    candidate["pieces"][0]["target"]["y"] = 260
    candidate["pieces"][0]["keyframes"][-1] = {"at": 1, **candidate["pieces"][0]["target"]}

    report = rank_geometry_ir_candidates([candidate], plan)

    assert not report["ok"]
    assert "safety:undersized_visual_footprint" in report["candidates"][0]["hard_failures"]
    assert "safety:visual_scale_range_conflict" in report["candidates"][0]["hard_failures"]


def test_footprint_scale_analysis_reports_infeasible_parameter_range() -> None:
    report = {
        "endpoints": {
            "source": [
                {"state": "minimum", "bbox": [440, 240, 520, 320]},
                {"state": "maximum", "bbox": [280, 80, 680, 480]},
            ],
            "target": [
                {"state": "minimum", "bbox": [400, 250, 541.42, 301.716]},
                {"state": "maximum", "bbox": [80, 40, 880, 520]},
            ],
        }
    }

    analysis = analyze_footprint_scale(report)

    assert analysis["ok"]
    assert not analysis["feasible"]
    assert analysis["reason"] == "visual_scale_range_conflict"
    assert analysis["required_scale"] == pytest.approx(1.6)
    assert analysis["maximum_scale"] == pytest.approx(1.166667, abs=1e-6)


def test_deterministic_footprint_scale_completion_repairs_feasible_candidate() -> None:
    from aetherviz_service.aetherviz.ir.recomposition import agent as recomposition_agent

    plan = normalize_plan({}, "组合图形面积切割重排证明")
    candidate = build_deterministic_geometry_ir(plan)
    candidate["pieces"][0]["attrs"]["points"] = "0,0 12,0 0,12"
    candidate["pieces"][0]["target"]["x"] = 420
    candidate["pieces"][0]["target"]["y"] = 260
    candidate["pieces"][0]["keyframes"][-1] = {"at": 1, **candidate["pieces"][0]["target"]}
    initial = rank_geometry_ir_candidates([candidate], plan)
    assert "safety:undersized_visual_footprint" in initial["candidates"][0]["hard_failures"]

    repaired_ranking, repaired_candidates = recomposition_agent._attempt_footprint_scale_completion(
        [candidate], plan, initial
    )

    assert repaired_ranking["ok"], repaired_ranking["candidates"][0]["hard_failures"]
    assert repaired_ranking["strategy"] == "deterministic_footprint_scale_completion"
    completion = repaired_ranking["footprint_scale_completion"][0]
    assert completion["accepted"]
    assert completion.get("changed") or completion.get("scale", 0) >= 1
    repaired = scale_scene_footprints_into_canvas(
        candidate,
        initial["candidates"][0]["details"]["visual_footprints"],
        plan,
    )
    assert repaired["ok"] and repaired["changed"]
    assert repaired_candidates[0] == repaired["ir"]


def test_deterministic_footprint_scale_completion_partial_scales_conflict() -> None:
    from aetherviz_service.aetherviz.ir.recomposition import agent as recomposition_agent
    from aetherviz_service.aetherviz.ir.recomposition.contract import GEOMETRY_IR_VERSION

    plan = normalize_plan(
        {
            "interactive_spec": {
                "variables": [
                    {"name": "scale", "label": "尺度", "min": 1, "max": 12, "default": 4, "step": 1}
                ]
            },
            "recomposition_spec": {
                "geometry_variables": ["scale"],
                "topology_variables": [],
                "proof_constraints": {
                    "measure_invariants": ["piece_congruence"],
                    "stage_requirements": [
                        {"id": "source", "intent": "源"},
                        {"id": "transform-1", "intent": "中间", "min_piece_ratio": 0.5},
                        {"id": "target", "intent": "目标"},
                    ],
                },
            },
        },
        "尺度冲突重排",
    )
    candidate = {
        "version": GEOMETRY_IR_VERSION,
        "definitions": {"size": {"op": "mul", "args": [{"state": "scale"}, 10]}},
        "pieces": [
            {
                "repeat": None,
                "id": "piece-0",
                "tag": "polygon",
                "attrs": {
                    "points": {
                        "op": "points",
                        "args": [[0, 0], [{"var": "size"}, 0], [0, {"var": "size"}]],
                    },
                    "fill": "#34d399",
                },
                "source": {"x": 80, "y": 80, "rotation": 0, "scale": 1, "opacity": 1},
                "target": {"x": 700, "y": 350, "rotation": 0, "scale": 1, "opacity": 1},
                "keyframes": [
                    {"at": 0, "x": 80, "y": 80, "rotation": 0, "scale": 1, "opacity": 1},
                    {"at": 0.5, "x": 390, "y": 120, "rotation": 0, "scale": 1, "opacity": 1},
                    {"at": 1, "x": 700, "y": 350, "rotation": 0, "scale": 1, "opacity": 1},
                ],
            }
        ],
        "frames": [
            {"stage_id": "source", "at": 0, "caption": "源", "formula": "保持", "step": 0},
            {"stage_id": "transform-1", "at": 0.5, "caption": "中间", "formula": "保持", "step": 1},
            {"stage_id": "target", "at": 1, "caption": "目标", "formula": "保持", "step": 2},
        ],
    }
    initial = rank_geometry_ir_candidates([candidate], plan)
    assert "safety:undersized_visual_footprint" in initial["candidates"][0]["hard_failures"]

    repaired_ranking, _ = recomposition_agent._attempt_footprint_scale_completion(
        [candidate], plan, initial
    )
    report = repaired_ranking["footprint_scale_completion"][0]

    assert report["attempted"] and report["accepted"], report
    assert report["reason"] in {
        "scene_footprints_boosted_then_scaled",
        "scene_footprints_boosted_and_centered",
        "scene_footprints_boosted_and_fitted",
        "scene_footprints_partial_scaled_to_canvas_limit",
        "scene_footprints_scaled_into_canvas",
    }
    assert "safety:undersized_visual_footprint" not in repaired_ranking["candidates"][0]["hard_failures"]
    assert "safety:visual_scale_range_conflict" not in repaired_ranking["candidates"][0]["hard_failures"]


def test_failed_construction_strips_block_so_ranking_can_continue() -> None:
    plan = normalize_plan({}, "组合图形面积切割重排证明")
    candidate = build_deterministic_geometry_ir(plan)
    candidate["construction"] = {
        "target_boundary": None,
        "constraints": [
            {
                "type": "attach_edge",
                "piece_id": "missing",
                "edge": 0,
                "to_piece_id": "also-missing",
                "to_edge": 0,
            }
        ],
    }

    materialized = materialize_target_construction(candidate, plan)

    assert not materialized["ok"]
    assert materialized["changed"]
    assert materialized.get("fallback") == "stripped_unsolved_construction"
    assert "construction" not in materialized["ir"]
    assert "unmaterialized_target_construction" not in {
        item["type"] for item in validate_geometry_ir(materialized["ir"], plan)["errors"]
    }


def test_null_construction_is_not_treated_as_unmaterialized() -> None:
    plan = normalize_plan({}, "组合图形面积切割重排证明")
    candidate = build_deterministic_geometry_ir(plan)
    candidate["construction"] = None

    report = validate_geometry_ir(candidate, plan)

    assert "unmaterialized_target_construction" not in {item["type"] for item in report["errors"]}


def test_normalized_recomposition_plan_always_preserves_piece_shape() -> None:
    plan = normalize_plan(
        {"recomposition_spec": {"proof_constraints": {"measure_invariants": ["area_preserved", "length_preserved"]}}},
        "组合图形切割重排证明",
    )

    assert plan["recomposition_spec"]["proof_constraints"]["measure_invariants"] == [
        "area_preserved",
        "length_preserved",
        "piece_congruence",
    ]


def test_structured_piece_invariants_recover_omitted_recomposition_contract() -> None:
    """Regression for a plan trace that described an exact puzzle proof but omitted its IR contract."""

    plan = normalize_plan(
        {
            "knowledge_profile": {
                "subject": "math",
                "concept_family": "geometry",
                "representation_type": "dynamic_model",
                "pedagogy_pattern": "proof_animation",
                "confidence": 0.61,
            },
            "interactive_spec": {
                "type": "simulation",
                "concept": "几何面积关系",
                "variables": [
                    {"name": "a", "label": "长度 a", "min": 2, "max": 8, "step": 0.5, "default": 3},
                    {"name": "b", "label": "长度 b", "min": 2, "max": 12, "step": 0.5, "default": 4},
                ],
            },
            "discipline_spec": {
                "invariants": ["拼片形状不变", "面积守恒"],
            },
            "representation_spec": {
                "version": "1.0",
                "views": [
                    {"id": "main-geometry", "kind": "geometric_scene", "role": "几何主舞台"},
                    {"id": "formula-panel", "kind": "symbolic_panel", "role": "度量关系"},
                ],
                "state_variables": [
                    {"id": "a", "semantic_type": "length"},
                    {"id": "b", "semantic_type": "length"},
                ],
                "correspondences": [
                    {
                        "type": "shared_parameter",
                        "source_view": "main-geometry",
                        "target_view": "formula-panel",
                        "parameter": "a",
                    }
                ],
                "required_invariants": ["equal_value", "piece_congruence", "area_preserved"],
                "interaction_requirements": ["drag", "reveal"],
            },
        },
        "通用几何面积验证",
    )

    assert plan["knowledge_profile"]["representation_type"] == "geometric_recomposition"
    assert len(plan["recomposition_spec"]["proof_constraints"]["stage_requirements"]) == 3
    assert any(
        item["type"] == "decompose_recompose"
        for item in plan["representation_spec"]["correspondences"]
    )
    route = resolve_generation_route(plan)
    assert route.selected_backend == "recomposition_scene"
    assert route.source == "deterministic"
    assert route.llm_invoked is False


def test_scene_module_contract_rejects_dom_and_animation_ownership() -> None:
    source = """const sceneModule={
      structureKey(state){return 'x';},
      buildGeometry(state){document.createElement('div');return {pieces:[]};},
      deriveFrame(geometry,state,progress){requestAnimationFrame(()=>{});return {pieces:[]};},
      deriveDisplay(state,progress){return {caption:'',formula:'',step:0};}
    }; // sourceTransform targetTransform"""
    report = validate_scene_module(source)
    assert not report["ok"]
    apis = {error.get("api") for error in report["errors"]}
    assert {"document", "dom_creation", "animation_loop"} <= apis


def test_geometry_ir_rejects_executable_content_and_trailing_prose() -> None:
    with pytest.raises(ValueError, match="trailing_content"):
        parse_geometry_ir('{"version":"aetherviz.geometry-ir.v1"}; alert(1)')
    with pytest.raises(ValueError, match="missing_geometry_ir_object"):
        parse_geometry_ir("const sceneBlueprint = buildGeometry();")


def test_geometry_ir_candidate_envelope_requires_two_or_three_items() -> None:
    plan = normalize_plan({}, "组合图形面积切割重排证明")
    candidate = build_deterministic_geometry_ir(plan)
    raw = json.dumps({"candidates": [candidate, candidate]}, ensure_ascii=False)
    assert len(parse_geometry_ir_candidates(raw)) == 2
    with pytest.raises(ValueError, match="2_to_3"):
        parse_geometry_ir_candidates(json.dumps({"candidates": [candidate]}, ensure_ascii=False))
    schema = geometry_ir_candidates_response_schema()
    assert schema["properties"]["candidates"]["minItems"] == 2
    assert schema["properties"]["candidates"]["maxItems"] == 3


def test_ir_candidate_ranking_rejects_hard_failures_and_is_repeatable() -> None:
    plan = normalize_plan({}, "组合图形面积切割重排证明")
    first = build_deterministic_geometry_ir(plan)
    second = deepcopy(first)
    second["pieces"][0]["target"]["x"] = 520
    invalid = deepcopy(first)
    invalid["pieces"][0]["target"]["scale"] = 0

    report = rank_geometry_ir_candidates([first, second, invalid], plan)
    repeated = rank_geometry_ir_candidates([first, second, invalid], plan)

    assert report["ok"]
    assert report["selected_index"] == repeated["selected_index"]
    assert report["ranking"] == repeated["ranking"]
    assert report["candidates"][2]["eligible"] is False
    assert any("schema:geometry_ir_semantics" == item for item in report["candidates"][2]["hard_failures"])
    assert sum(report["candidates"][report["selected_index"]]["components"].values()) == report["selected_score"]


def test_ir_candidate_ranking_is_order_independent_by_fingerprint() -> None:
    plan = normalize_plan({}, "组合图形面积切割重排证明")
    first = build_deterministic_geometry_ir(plan)
    second = deepcopy(first)
    second["frames"][-1]["caption"] = "拼合并解释目标关系"
    forward = rank_geometry_ir_candidates([first, second], plan)
    reverse = rank_geometry_ir_candidates([second, first], plan)
    forward_fingerprint = forward["candidates"][forward["selected_index"]]["fingerprint"]
    reverse_fingerprint = reverse["candidates"][reverse["selected_index"]]["fingerprint"]
    assert forward_fingerprint == reverse_fingerprint


def test_ir_candidate_ranking_rejects_gross_out_of_bounds_motion() -> None:
    plan = normalize_plan({}, "组合图形面积切割重排证明")
    candidate = build_deterministic_geometry_ir(plan)
    candidate["pieces"][0]["target"]["x"] = 4_000
    candidate["pieces"][0]["keyframes"][-1]["x"] = 4_000
    report = rank_geometry_ir_candidates([candidate], plan)
    assert not report["ok"]
    assert "safety:gross_transform_out_of_bounds" in report["candidates"][0]["hard_failures"]


def test_target_assembly_rejects_scattered_candidate_and_selects_rectangle() -> None:
    plan = normalize_plan(
        {
            "recomposition_spec": {
                "proof_constraints": {
                    "target_assembly": [
                        {
                            "id": "target-rectangle",
                            "type": "approximate_rectangle",
                            "max_components": 1,
                            "max_overlap_ratio": 0.1,
                            "min_rectangularity": 0.8,
                        }
                    ]
                }
            }
        },
        "组合图形切割重排证明",
    )
    rectangle = _rectangular_assembly_ir(plan)
    scattered = deepcopy(rectangle)
    scattered["pieces"][0]["target"]["x"] = {
        "op": "add",
        "args": [420, {"op": "mul", "args": [{"local": "i"}, 100]}],
    }
    scattered["pieces"][0]["keyframes"][-1]["x"] = deepcopy(scattered["pieces"][0]["target"]["x"])

    report = rank_geometry_ir_candidates([scattered, rectangle], plan)

    assert report["ok"]
    assert report["selected_index"] == 1
    assert report["candidates"][0]["eligible"] is False
    assert "assembly:target_assembly_failed" in report["candidates"][0]["hard_failures"]
    assert report["candidates"][1]["details"]["target_assembly"]["states"][0]["rectangularity"] >= 0.95


def test_sector_rectangle_guidance_describes_measurable_interlocking_assembly() -> None:
    from aetherviz_service.aetherviz.ir.recomposition.agent import SCENE_SYSTEM_PROMPT

    plan = normalize_plan(
        {
            "interactive_spec": {
                "variables": [
                    {
                        "name": "sectorCount",
                        "label": "等分数",
                        "min": 4,
                        "max": 32,
                        "default": 8,
                    }
                ]
            },
            "recomposition_spec": {
                "topology_variables": ["sectorCount"],
                "proof_constraints": {
                    "target_assembly": [
                        {
                            "id": "target-rectangle",
                            "type": "approximate_rectangle",
                            "max_components": 1,
                            "max_overlap_ratio": 0.1,
                            "min_rectangularity": 0.62,
                            "monotonic": True,
                            "trend_tolerance": 0.08,
                        }
                    ]
                },
            },
        },
        "圆形切分重排推导",
    )

    report = evaluate_target_assembly(_interlocking_sector_assembly_ir(), plan)
    source = compile_geometry_ir(_interlocking_sector_assembly_ir(), plan)

    assert report["ok"], report
    assert validate_scene_module(source)["ok"]
    assert all(state["component_count"] == 1 for state in report["states"])
    assert all(state["rectangularity"] >= 0.62 for state in report["states"])
    assert "stepX=r*sin(halfAngle)" in SCENE_SYSTEM_PROMPT
    assert "不得用 arcLen 作为逐片中心间距" in SCENE_SYSTEM_PROMPT


def test_target_assembly_is_inactive_without_structured_plan_constraint() -> None:
    plan = normalize_plan({}, "组合图形切割重排证明")
    report = evaluate_target_assembly(_rectangular_assembly_ir(plan), plan)
    assert report == {"ok": True, "errors": [], "warnings": [], "checks": [], "states": []}


def test_ranking_does_not_award_assembly_points_without_structured_constraint() -> None:
    plan = normalize_plan({}, "组合图形切割重排证明")
    report = rank_geometry_ir_candidates([build_deterministic_geometry_ir(plan)], plan)
    assert report["candidates"][0]["components"]["target_assembly"] == 0.0


def test_target_assembly_rejects_overlapping_source_and_canvas_overflow() -> None:
    plan = normalize_plan(
        {
            "recomposition_spec": {
                "proof_constraints": {
                    "target_assembly": [
                        {
                            "id": "target-rectangle",
                            "type": "approximate_rectangle",
                            "max_components": 1,
                            "max_overlap_ratio": 0.1,
                            "min_rectangularity": 0.62,
                        }
                    ]
                }
            }
        },
        "组合图形切割重排证明",
    )
    geometry_ir = _rectangular_assembly_ir(plan)
    geometry_ir["pieces"][0]["source"]["x"] = 180
    geometry_ir["pieces"][0]["keyframes"][0]["x"] = 180
    geometry_ir["pieces"][0]["target"]["x"] = 950
    geometry_ir["pieces"][0]["keyframes"][-1]["x"] = 950

    report = evaluate_target_assembly(geometry_ir, plan)
    error_types = {item["type"] for item in report["errors"]}
    assert "source_assembly_overlap_failed" in error_types
    assert "target_assembly_out_of_bounds" in error_types


def test_target_assembly_can_translate_an_otherwise_valid_target_into_canvas() -> None:
    plan = normalize_plan(
        {
            "interactive_spec": {"variables": [{"name": "sectorCount", "min": 4, "max": 32, "default": 8}]},
            "recomposition_spec": {
                "topology_variables": ["sectorCount"],
                "proof_constraints": {
                    "target_assembly": [
                        {
                            "id": "target-rectangle",
                            "type": "approximate_rectangle",
                            "max_components": 1,
                            "max_overlap_ratio": 0.1,
                            "min_rectangularity": 0.62,
                            "monotonic": True,
                            "trend_tolerance": 0.08,
                        }
                    ],
                    "stage_requirements": [
                        {
                            "id": "source",
                            "role": "source",
                            "at": 0,
                            "geometry_requirement": "source_snapshot",
                            "min_piece_ratio": 1,
                            "required_relations": [],
                        },
                        {
                            "id": "move",
                            "role": "intermediate",
                            "at": 0.5,
                            "geometry_requirement": "transform_keyframe",
                            "min_piece_ratio": 0.5,
                            "required_relations": [],
                        },
                        {
                            "id": "target",
                            "role": "target",
                            "at": 1,
                            "geometry_requirement": "target_snapshot",
                            "min_piece_ratio": 1,
                            "required_relations": [],
                        },
                    ],
                },
            },
        },
        "圆形切分重排推导",
    )
    geometry_ir = _interlocking_sector_assembly_ir()
    geometry_ir["frames"][-1]["formula"] = "S = πr²"
    target = geometry_ir["pieces"][0]["target"]
    target["x"] = {"op": "add", "args": [target["x"], 700]}
    geometry_ir["pieces"][0]["keyframes"][-1]["x"] = deepcopy(target["x"])

    before = evaluate_target_assembly(geometry_ir, plan)
    repair = translate_target_assembly_into_canvas(geometry_ir, before)
    after = evaluate_target_assembly(repair["ir"], plan)

    assert {item["type"] for item in before["errors"]} == {"target_assembly_out_of_bounds"}
    assert repair["ok"] and repair["changed"]
    assert repair["translation"]["x"] < 0
    assert after["ok"], after
    assert [item["rectangularity"] for item in after["states"]] == [item["rectangularity"] for item in before["states"]]
    assert [item["overlap_ratio"] for item in after["states"]] == [item["overlap_ratio"] for item in before["states"]]

    from aetherviz_service.aetherviz.ir.recomposition import agent as recomposition_agent

    initial_ranking = rank_geometry_ir_candidates([geometry_ir], plan)
    repaired_ranking, _ = recomposition_agent._attempt_target_bounds_completion([geometry_ir], plan, initial_ranking)
    assert repaired_ranking["ok"]
    assert repaired_ranking["strategy"] == "deterministic_target_bounds_completion"
    assert repaired_ranking["target_bounds_completion"][0]["attempted"]


def test_deterministic_fallback_satisfies_explicit_rectangle_assembly() -> None:
    plan = normalize_plan(
        {
            "recomposition_spec": {
                "proof_constraints": {
                    "target_assembly": [
                        {
                            "id": "target-rectangle",
                            "type": "approximate_rectangle",
                            "max_components": 1,
                            "max_overlap_ratio": 0.1,
                            "min_rectangularity": 0.62,
                        }
                    ]
                }
            }
        },
        "组合图形切割重排证明",
    )
    report = rank_geometry_ir_candidates([build_deterministic_geometry_ir(plan)], plan)
    assert report["ok"], report["candidates"][0]["details"]["target_assembly"]


def test_explicit_target_assembly_stops_after_failed_repair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aetherviz_service.aetherviz.ir.recomposition import agent as recomposition_agent

    plan = normalize_plan(
        {
            "recomposition_spec": {
                "proof_constraints": {
                    "target_assembly": [
                        {
                            "id": "target-rectangle",
                            "type": "approximate_rectangle",
                            "max_components": 1,
                            "max_overlap_ratio": 0.1,
                            "min_rectangularity": 0.62,
                        }
                    ]
                }
            }
        },
        "组合图形切割重排证明",
    )
    failure_report = {
        "ok": False,
        "errors": [{"type": "geometry_ir_candidate_rejected"}],
        "warnings": [],
    }
    monkeypatch.setattr(recomposition_agent, "has_primary_llm_config", lambda: True)
    monkeypatch.setattr(
        recomposition_agent,
        "_generate_scene_source",
        lambda *_args: (_ for _ in ()).throw(recomposition_agent.GeometryIRGenerationError("{}", failure_report)),
    )
    monkeypatch.setattr(
        recomposition_agent,
        "_repair_scene_source",
        lambda *_args: (_ for _ in ()).throw(ValueError("repair failed")),
    )

    with pytest.raises(HtmlGenerationError) as exc_info:
        list(recomposition_agent._stream_generate_recomposition_html_impl("topic", plan))
    assert exc_info.value.code == "ir_generation_failed"
    assert exc_info.value.detail == "initial=geometry_ir_candidate_rejected;repair=repair failed"


def test_failed_repair_never_uses_deterministic_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aetherviz_service.aetherviz.ir.recomposition import agent as recomposition_agent

    plan = normalize_plan({}, "组合图形切割重排证明")
    failure_report = {
        "ok": False,
        "errors": [{"type": "geometry_ir_candidate_rejected"}],
        "warnings": [],
    }
    monkeypatch.setattr(recomposition_agent, "has_primary_llm_config", lambda: True)
    monkeypatch.setattr(
        recomposition_agent,
        "_generate_scene_source",
        lambda *_args: (_ for _ in ()).throw(recomposition_agent.GeometryIRGenerationError("{}", failure_report)),
    )
    monkeypatch.setattr(
        recomposition_agent,
        "_repair_scene_source",
        lambda *_args: (_ for _ in ()).throw(ValueError("repair failed")),
    )
    with pytest.raises(HtmlGenerationError) as exc_info:
        list(recomposition_agent._stream_generate_recomposition_html_impl("topic", plan))
    assert exc_info.value.code == "ir_generation_failed"


def test_geometry_ir_failure_reports_unique_actionable_reasons() -> None:
    from aetherviz_service.aetherviz.ir.recomposition.agent import (
        GeometryIRGenerationError,
        _compact_assembly_diagnostics,
        _compact_teaching_diagnostics,
    )

    error = GeometryIRGenerationError(
        "{}",
        {
            "errors": [
                {
                    "type": "geometry_ir_candidate_rejected",
                    "hard_failures": [
                        "assembly:target_assembly_failed",
                        "teaching:missing_intermediate_geometry_stage",
                    ],
                },
                {
                    "type": "geometry_ir_candidate_rejected",
                    "hard_failures": ["assembly:target_assembly_failed"],
                },
            ]
        },
    )
    assembly = _compact_assembly_diagnostics(
        {
            "states": [
                {
                    "state": "default",
                    "piece_count": 8,
                    "component_count": 5,
                    "rectangularity": 0.2,
                    "overlap_ratio": 0.06,
                    "bbox": [100, 100, 700, 400],
                    "grid": [88, 44],
                }
            ],
            "errors": [
                {
                    "type": "target_assembly_failed",
                    "state": "default",
                    "minimum_rectangularity": 0.62,
                    "message": "verbose",
                }
            ],
            "checks": [{"verbose": "omitted"}],
        }
    )
    teaching = _compact_teaching_diagnostics(
        {
            "errors": [{"type": "missing_intermediate_geometry_stage"}],
            "checks": [
                {
                    "kind": "intermediate_geometry",
                    "name": "stage-split",
                    "state": "default",
                    "at": 0.333333,
                    "ratio": 0,
                    "required_ratio": 0.5,
                    "reason_counts": {"insufficient_source_separation": 8},
                    "piece_evidence": [{"piece_id": f"piece-{index}"} for index in range(32)],
                }
            ],
        }
    )

    assert str(error) == ("assembly:target_assembly_failed,teaching:missing_intermediate_geometry_stage")
    assert assembly == {
        "errors": [
            {
                "type": "target_assembly_failed",
                "state": "default",
                "minimum_rectangularity": 0.62,
            }
        ],
        "states": [
            {
                "state": "default",
                "piece_count": 8,
                "component_count": 5,
                "rectangularity": 0.2,
                "overlap_ratio": 0.06,
                "bbox": [100, 100, 700, 400],
            }
        ],
    }
    assert "piece_evidence" not in json.dumps(teaching)


def test_scene_generation_selects_one_ir_from_single_three_candidate_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aetherviz_service.aetherviz.ir.recomposition import agent as recomposition_agent

    plan = normalize_plan({}, "组合图形面积切割重排证明")
    candidates = [build_deterministic_geometry_ir(plan) for _ in range(3)]
    candidates[1]["frames"][-1]["caption"] = "拼合并解释目标关系"
    captured: dict[str, object] = {}

    def fake_stream(_messages: object, *, response_schema: dict[str, object] | None = None):
        captured["schema"] = response_schema
        yield {"content": json.dumps({"candidates": candidates}, ensure_ascii=False)}

    monkeypatch.setattr(recomposition_agent, "_stream_scene_response", fake_stream)
    source, timed_out, ranking = recomposition_agent._generate_ranked_scene_source("组合图形面积切割重排证明", plan)
    assert not timed_out
    assert ranking["ok"]
    assert len(ranking["candidates"]) == 3
    assert validate_scene_module(source)["ok"]
    assert captured["schema"]["properties"]["candidates"]["maxItems"] == 3


def test_geometry_ir_rejects_unknown_operator_attribute_and_state() -> None:
    plan = normalize_plan({}, "组合图形面积切割重排证明")
    geometry_ir = build_deterministic_geometry_ir(plan)
    piece = geometry_ir["pieces"][0]
    piece["attrs"]["onclick"] = "alert(1)"
    piece["target"]["x"] = {"op": "execute", "args": [{"state": "secret"}]}
    report = validate_geometry_ir(geometry_ir, plan)
    issue_types = {item["type"] for item in report["errors"]}
    assert "forbidden_piece_attr" in issue_types
    assert "forbidden_expression_operator" in issue_types


def test_geometry_ir_checks_minimum_default_and_maximum_semantics() -> None:
    plan = normalize_plan(
        {
            "interactive_spec": {
                "variables": [{"name": "radius", "label": "半径", "min": 0, "max": 8, "default": 4, "step": 1}]
            }
        },
        "弓形面积割补推导",
    )
    geometry_ir = {
        "version": GEOMETRY_IR_VERSION,
        "definitions": {},
        "pieces": [
            {
                "id": "piece-0",
                "tag": "circle",
                "attrs": {"cx": 0, "cy": 0, "r": {"state": "radius"}, "fill": "#34d399"},
                "source": {"x": 100, "y": 100, "rotation": 0, "scale": 1, "opacity": 1},
                "target": {"x": 300, "y": 100, "rotation": 0, "scale": 1, "opacity": 1},
            }
        ],
        "frames": [
            {"stage_id": "source", "at": 0, "caption": "源状态", "formula": "A", "step": 0},
            {"stage_id": "transform-1", "at": 0.5, "caption": "重排", "formula": "A=B", "step": 1},
            {"stage_id": "target", "at": 1, "caption": "目标状态", "formula": "B", "step": 2},
        ],
    }
    report = validate_geometry_ir(geometry_ir, plan)
    assert not report["ok"]
    assert any(item.get("state") == "minimum" for item in report["errors"])


def test_geometry_ir_compiles_to_server_owned_scene_module() -> None:
    plan = normalize_plan({}, "正六边形面积拆分拼合推导")
    geometry_ir = build_deterministic_geometry_ir(plan)
    source = compile_geometry_ir(geometry_ir, plan)
    assert "const sceneIR=" in source
    assert "sceneIRRuntime" in source
    assert "buildGeometry(state){return sceneIRRuntime.build" in source
    assert validate_scene_module(source)["ok"]


def test_geometry_ir_normalizes_only_unambiguous_dsl_aliases() -> None:
    plan = normalize_plan(
        {
            "interactive_spec": {
                "variables": [{"name": "scale", "label": "尺度", "min": 1, "max": 8, "default": 4, "step": 1}]
            }
        },
        "组合图形面积切割重排证明",
    )
    geometry_ir = build_deterministic_geometry_ir(plan)
    geometry_ir["definitions"]["angle"] = {"op": "rad2deg", "args": [{"var": "scale"}]}
    normalized = normalize_geometry_ir(geometry_ir, plan)
    assert normalized["definitions"]["angle"] == {
        "op": "rad_to_deg",
        "args": [{"state": "scale"}],
    }
    assert validate_geometry_ir(normalized, plan)["ok"]


def test_geometry_ir_normalizes_strict_transport_and_expression_shorthand() -> None:
    plan = normalize_plan({}, "组合图形面积切割重排证明")
    geometry_ir = build_deterministic_geometry_ir(plan)
    transport = {
        **geometry_ir,
        "definitions": [
            *[{"name": name, "value": value} for name, value in geometry_ir["definitions"].items()],
            {"name": "negative", "value": {"neg": 12}},
        ],
        "pieces": [
            {
                **geometry_ir["pieces"][0],
                "repeat": geometry_ir["pieces"][0]["repeat"],
                "attrs": [{"name": name, "value": value} for name, value in geometry_ir["pieces"][0]["attrs"].items()],
                "keyframes": [],
            }
        ],
    }
    normalized = normalize_geometry_ir(transport, plan)
    assert normalized["definitions"]["negative"] == {"op": "neg", "args": [12]}
    assert isinstance(normalized["pieces"][0]["attrs"], dict)
    assert normalized["pieces"][0]["repeat"]["index"] == "i"
    assert validate_geometry_ir(normalized, plan)["ok"]
    schema = geometry_ir_response_schema()
    assert schema["additionalProperties"] is False
    assert schema["properties"]["definitions"]["type"] == "array"
    construction_object = schema["properties"]["construction"]["anyOf"][1]
    assert construction_object["properties"]["constraints"]["maxItems"] == 24
    assert "construction" in schema["required"]
    assert len(schema["$defs"]["construction_constraint"]["anyOf"]) == 6
    operator_variants = [
        item
        for item in schema["$defs"]["expression"]["anyOf"]
        if isinstance(item, dict) and "op" in item.get("properties", {})
    ]
    unary = next(item for item in operator_variants if "sqrt" in item["properties"]["op"]["enum"])
    fold = next(item for item in operator_variants if "div" in item["properties"]["op"]["enum"])
    assert unary["properties"]["args"]["minItems"] == unary["properties"]["args"]["maxItems"] == 1
    assert fold["properties"]["args"]["minItems"] == 2


def test_geometry_ir_supports_generic_angle_distance_operators() -> None:
    plan = normalize_plan({}, "勾股定理拼图重排证明")
    geometry_ir = build_deterministic_geometry_ir(plan)
    geometry_ir["definitions"]["angle"] = {"op": "atan2", "args": [3, 4]}
    geometry_ir["definitions"]["distance"] = {"op": "hypot", "args": [3, 4]}
    geometry_ir["pieces"][0]["target"]["rotation"] = {
        "op": "rad_to_deg",
        "args": [{"var": "angle"}],
    }
    assert validate_geometry_ir(geometry_ir, plan)["ok"]
    assert validate_scene_module(compile_geometry_ir(geometry_ir, plan))["ok"]


def test_geometry_ir_supports_multistage_transform_keyframes() -> None:
    plan = normalize_plan({}, "组合图形面积切割重排证明")
    geometry_ir = build_deterministic_geometry_ir(plan)
    piece = geometry_ir["pieces"][0]
    piece["keyframes"] = [
        {"at": 0, **piece["source"]},
        {
            "at": 0.5,
            "x": 320,
            "y": 110,
            "rotation": 45,
            "scale": piece["source"]["scale"],
            "opacity": 1,
        },
        {"at": 1, **piece["target"]},
    ]
    assert validate_geometry_ir(geometry_ir, plan)["ok"]
    source = compile_geometry_ir(geometry_ir, plan)
    assert "transformKeyframes" in source
    assert validate_scene_module(source)["ok"]
    assert not evaluate_recomposition_semantics(geometry_ir, plan)["errors"]


def test_plan_normalizes_hard_intermediate_teaching_stage_contract() -> None:
    plan = normalize_plan(
        {
            "recomposition_spec": {
                "proof_constraints": {
                    "stage_requirements": [
                        {"id": "observe", "intent": "观察源状态"},
                        {"id": "separate", "intent": "分离图元", "min_piece_ratio": 0.4},
                        {"id": "align", "intent": "对齐图元", "min_piece_ratio": 2},
                        {"id": "conclude", "intent": "得到结论"},
                    ]
                }
            }
        },
        "组合图形面积切割重排证明",
    )
    stages = plan["recomposition_spec"]["proof_constraints"]["stage_requirements"]
    assert [stage["role"] for stage in stages] == ["source", "intermediate", "intermediate", "target"]
    assert [stage["at"] for stage in stages] == [0.0, 0.333333, 0.666667, 1.0]
    assert [stage["geometry_requirement"] for stage in stages] == [
        "source_snapshot",
        "transform_keyframe",
        "transform_keyframe",
        "target_snapshot",
    ]
    assert stages[1]["min_piece_ratio"] == 0.4
    assert stages[2]["min_piece_ratio"] == 1.0


def test_semantic_evaluator_requires_independent_intermediate_geometry() -> None:
    plan = normalize_plan({}, "组合图形面积切割重排证明")
    geometry_ir = build_deterministic_geometry_ir(plan)
    accepted = evaluate_recomposition_semantics(geometry_ir, plan)
    assert accepted["ok"]
    assert {check["state"] for check in accepted["checks"] if check.get("kind") == "intermediate_geometry"} == {
        "minimum",
        "default",
        "maximum",
    }

    geometry_ir["pieces"][0].pop("keyframes")
    rejected = evaluate_recomposition_semantics(geometry_ir, plan)
    assert not rejected["ok"]
    assert "missing_intermediate_geometry_stage" in {item["type"] for item in rejected["errors"]}


def test_semantic_evaluator_rejects_text_stage_with_only_linear_geometry() -> None:
    plan = normalize_plan({}, "组合图形面积切割重排证明")
    geometry_ir = build_deterministic_geometry_ir(plan)
    piece = geometry_ir["pieces"][0]
    middle = piece["keyframes"][1]
    middle.update({key: piece["source"][key] for key in ("x", "y", "rotation", "scale", "opacity")})
    report = evaluate_recomposition_semantics(geometry_ir, plan)
    assert not report["ok"]
    assert "missing_intermediate_geometry_stage" in {item["type"] for item in report["errors"]}


def test_intermediate_transform_evidence_reports_explainable_metrics() -> None:
    piece = {
        "id": "piece-0",
        "source": {"x": 100, "y": 100, "rotation": 0, "scale": 1, "opacity": 1},
        "target": {"x": 300, "y": 100, "rotation": 90, "scale": 1, "opacity": 1},
        "keyframes": [{"at": 0.5, "x": 200, "y": 100, "rotation": 45, "scale": 1, "opacity": 1}],
    }
    evidence = evaluate_intermediate_transform_evidence(piece, 0.5)
    assert evidence["evidenced"] is False
    assert evidence["reason"] == "insufficient_direct_path_deviation"
    assert evidence["endpoint_score"] > 1
    assert evidence["independence_score"] == 0
    assert evidence["thresholds"] == INTERMEDIATE_EVIDENCE_THRESHOLDS
    assert evidence["metrics"]["from_direct_interpolation"]["translation_px"] == 0

    piece["keyframes"][0]["rotation"] = 45 + INTERMEDIATE_EVIDENCE_THRESHOLDS["rotation_deg"]
    accepted = evaluate_intermediate_transform_evidence(piece, 0.5)
    assert accepted["evidenced"] is True
    assert accepted["reason"] == "independent_transform_evidence"
    assert accepted["independence_score"] == 1


def test_waypoint_completion_repairs_only_generic_intermediate_transform_evidence() -> None:
    plan = normalize_plan(
        {
            "recomposition_spec": {
                "proof_constraints": {
                    "stage_requirements": [
                        {"id": "source", "intent": "观察"},
                        {"id": "separate", "intent": "分离"},
                        {"id": "rotate", "intent": "旋转"},
                        {"id": "align", "intent": "对齐"},
                        {"id": "target", "intent": "结论"},
                    ]
                }
            }
        },
        "单块多边形旋转割补面积守恒推导",
    )
    geometry_ir = build_deterministic_geometry_ir(plan)
    source = deepcopy(geometry_ir["pieces"][0]["source"])
    target = deepcopy(geometry_ir["pieces"][0]["target"])
    for keyframe in geometry_ir["pieces"][0]["keyframes"][1:-1]:
        at = keyframe["at"]
        keyframe.update(
            {name: _test_lerp(source[name], target[name], at) for name in ("x", "y", "rotation", "scale", "opacity")}
        )
    before = evaluate_recomposition_semantics(geometry_ir, plan)
    assert not before["ok"]

    completion = complete_intermediate_waypoints(geometry_ir, plan)
    assert completion["ok"]
    assert completion["changed"]
    assert completion["completed_stage_ids"] == ["separate", "rotate", "align"]
    assert completion["ir"]["pieces"][0]["source"] == source
    assert completion["ir"]["pieces"][0]["target"] == target
    assert len(completion["ir"]["pieces"][0]["keyframes"]) == 5
    assert evaluate_recomposition_semantics(completion["ir"], plan)["ok"]


def test_scene_generation_uses_waypoint_completion_before_model_repair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aetherviz_service.aetherviz.ir.recomposition import agent as recomposition_agent

    plan = normalize_plan({}, "单块多边形旋转割补面积守恒推导")
    candidates = [build_deterministic_geometry_ir(plan) for _ in range(2)]
    for candidate in candidates:
        piece = candidate["pieces"][0]
        middle = piece["keyframes"][1]
        middle.update(
            {
                name: _test_lerp(piece["source"][name], piece["target"][name], middle["at"])
                for name in ("x", "y", "rotation", "scale", "opacity")
            }
        )

    def fake_stream(_messages: object, *, response_schema: dict[str, object] | None = None):
        yield {"content": json.dumps({"candidates": candidates}, ensure_ascii=False)}

    monkeypatch.setattr(recomposition_agent, "_stream_scene_response", fake_stream)
    source, _, ranking = recomposition_agent._generate_ranked_scene_source("topic", plan)
    assert validate_scene_module(source)["ok"]
    assert ranking["strategy"] == "deterministic_waypoint_completion"
    assert ranking["ok"]
    assert all(item["attempted"] for item in ranking["waypoint_completion"])
    assert ranking["initial_ranking"]["ok"] is False


def test_composite_completion_repairs_waypoint_with_unrelated_assembly_failure() -> None:
    from aetherviz_service.aetherviz.ir.recomposition import agent as recomposition_agent

    plan = normalize_plan(
        {
            "recomposition_spec": {
                "proof_constraints": {
                    "target_assembly": [
                        {
                            "id": "target-rectangle",
                            "type": "approximate_rectangle",
                            "max_components": 1,
                            "max_overlap_ratio": 0.1,
                            "min_rectangularity": 0.8,
                        }
                    ]
                }
            }
        },
        "组合图形切割重排证明",
    )
    candidate = _rectangular_assembly_ir(plan)
    piece = candidate["pieces"][0]
    piece["target"]["x"] = {
        "op": "add",
        "args": [420, {"op": "mul", "args": [{"local": "i"}, 100]}],
    }
    piece["keyframes"][-1]["x"] = deepcopy(piece["target"]["x"])
    middle = piece["keyframes"][1]
    middle.update(
        {
            name: _test_lerp(piece["source"][name], piece["target"][name], middle["at"])
            for name in ("x", "y", "rotation", "scale", "opacity")
        }
    )
    initial = rank_geometry_ir_candidates([candidate], plan)
    assert set(initial["candidates"][0]["hard_failures"]) == {
        "assembly:target_assembly_failed",
        "teaching:missing_intermediate_geometry_stage",
    }

    completed, completed_candidates = recomposition_agent._complete_candidates_deterministically(
        [candidate], plan, initial
    )

    assert not completed["ok"]
    assert completed["candidates"][0]["hard_failures"] == ["assembly:target_assembly_failed"]
    assert completed["strategy"] == "deterministic_waypoint_completion"
    waypoint_report = completed["waypoint_completion"][0]
    assert waypoint_report["accepted"] is True
    assert waypoint_report["introduced_hard_failures"] == []
    assert waypoint_report["removed_hard_failures"] == ["teaching:missing_intermediate_geometry_stage"]
    assert completed_candidates[0]["pieces"][0]["source"] == candidate["pieces"][0]["source"]
    assert completed_candidates[0]["pieces"][0]["target"] == candidate["pieces"][0]["target"]

    repeated, repeated_candidates = recomposition_agent._complete_candidates_deterministically(
        completed_candidates, plan, completed
    )
    assert repeated_candidates == completed_candidates
    assert repeated["candidates"][0]["fingerprint"] == completed["candidates"][0]["fingerprint"]
    assert not any(item["accepted"] for item in repeated["completion_history"])


def test_target_construction_materializes_exact_edge_attachment() -> None:
    plan = normalize_plan(
        {
            "interactive_spec": {
                "variables": [
                    {"name": "size", "label": "边长", "min": 80, "max": 140, "default": 100, "step": 10}
                ]
            },
            "recomposition_spec": {
                "geometry_variables": ["size"],
                "proof_constraints": {
                    "target_assembly": [
                        {
                            "id": "target-rectangle",
                            "type": "approximate_rectangle",
                            "max_components": 1,
                            "max_overlap_ratio": 0.1,
                            "min_rectangularity": 0.9,
                        }
                    ]
                }
            }
        },
        "组合图形切割重排证明",
    )
    stages = plan["recomposition_spec"]["proof_constraints"]["stage_requirements"]

    def piece(piece_id: str, source_x: float, target_x: float, rotation: float) -> dict[str, object]:
        source = {"x": source_x, "y": 150, "rotation": 0, "scale": 1, "opacity": 1}
        target = {"x": target_x, "y": 200, "rotation": 0, "scale": 1, "opacity": 1}
        return {
            "id": piece_id,
            "tag": "rect",
            "attrs": {
                "x": 0,
                "y": 0,
                "width": {"state": "size"},
                "height": 100,
                "fill": "#34d399",
            },
            "source": source,
            "target": target,
            "keyframes": [
                {"at": 0, **source},
                {
                    "at": 0.5,
                    "x": (source_x + 400) / 2,
                    "y": 90,
                    "rotation": rotation,
                    "scale": 1,
                    "opacity": 1,
                },
                {"at": 1, **target},
            ],
        }

    geometry_ir = {
        "version": GEOMETRY_IR_VERSION,
        "definitions": {},
        "pieces": [piece("left", 200, 400, 20), piece("right", 400, 50, -20)],
        "frames": [
            {
                "stage_id": stage["id"],
                "at": stage["at"],
                "caption": stage["intent"],
                "formula": "面积保持不变",
                "step": index,
            }
            for index, stage in enumerate(stages)
        ],
        "construction": {
            "target_boundary": {"x": 400, "y": 200, "width": {"state": "size"}, "height": 200},
            "constraints": [
                {
                    "type": "attach_edge",
                    "piece_id": "right",
                    "edge": 0,
                    "to_piece_id": "left",
                    "to_edge": 2,
                    "reverse": True,
                },
                {"type": "inside_target", "piece_id": "left"},
                {"type": "inside_target", "piece_id": "right"},
                {
                    "type": "cover_target",
                    "piece_ids": ["left", "right"],
                    "min_coverage_ratio": 0.98,
                },
            ]
        },
    }
    assert "unmaterialized_target_construction" in {
        item["type"] for item in validate_geometry_ir(geometry_ir, plan)["errors"]
    }

    materialized = materialize_target_construction(geometry_ir, plan)

    assert materialized["ok"], materialized["errors"]
    assert materialized["changed"]
    assert "construction" not in materialized["ir"]
    right = materialized["ir"]["pieces"][1]
    assert right["target"]["x"] == pytest.approx(400)
    assert right["target"]["y"] == pytest.approx(300)
    for _, state in sample_geometry_states(plan):
        expanded = {item["id"]: item for item in expand_geometry_ir(materialized["ir"], state)}
        size = state["size"]
        assert float(expanded["right"]["target"]["rotation"]) % 360 == pytest.approx(0)
        left_points = piece_local_polygon(expanded["left"])
        right_points = piece_local_polygon(expanded["right"])
        assert left_points[2][0] == pytest.approx(size)
        assert right_points[1][0] == pytest.approx(size)
    ranking = rank_geometry_ir_candidates([materialized["ir"]], plan)
    assert ranking["ok"], ranking["candidates"][0]["hard_failures"]
    assert ranking["candidates"][0]["details"]["target_assembly"]["ok"]


def test_recomposition_preflight_rejects_unbounded_piece_budget_before_model_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aetherviz_service.aetherviz.ir.recomposition import agent as recomposition_agent
    from aetherviz_service.aetherviz.ir.recomposition.routing import assess

    plan = normalize_plan(
        {
            "interactive_spec": {
                "variables": [
                    {
                        "name": "pieceCount",
                        "label": "拼片数",
                        "min": 1,
                        "max": 120,
                        "default": 8,
                        "step": 1,
                    }
                ]
            },
            "recomposition_spec": {"topology_variables": ["pieceCount"]},
        },
        "组合图形切割重排证明",
    )
    feasibility = evaluate_recomposition_plan_feasibility(plan)
    assert not feasibility["ok"]
    assert feasibility["errors"][0]["type"] == "expanded_piece_budget_exceeded"
    assessment = assess(plan)
    assert not assessment.eligible
    assert any("超过 IR 上限" in reason for reason in assessment.exclusion_reasons)

    invoked = False

    def fail_if_invoked(*_args: object, **_kwargs: object):
        nonlocal invoked
        invoked = True
        yield {"content": ""}

    monkeypatch.setattr(recomposition_agent, "_stream_scene_response", fail_if_invoked)
    monkeypatch.setattr(recomposition_agent, "has_primary_llm_config", lambda: True)
    with pytest.raises(HtmlGenerationError) as exc_info:
        list(recomposition_agent._stream_generate_recomposition_html_impl("topic", plan))
    assert exc_info.value.code == "unsupported_ir_capability"
    assert "120" in str(exc_info.value.detail)
    assert invoked is False


def test_model_repair_output_reuses_deterministic_completion_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aetherviz_service.aetherviz.ir.recomposition import agent as recomposition_agent

    plan = normalize_plan({}, "组合图形切割重排证明")
    candidate = build_deterministic_geometry_ir(plan)
    piece = candidate["pieces"][0]
    middle = piece["keyframes"][1]
    middle.update(
        {
            name: _test_lerp(piece["source"][name], piece["target"][name], middle["at"])
            for name in ("x", "y", "rotation", "scale", "opacity")
        }
    )
    assert not rank_geometry_ir_candidates([candidate], plan)["ok"]

    def fake_stream(_messages: object, *, response_schema: dict[str, object] | None = None):
        yield {"content": json.dumps(candidate, ensure_ascii=False)}

    monkeypatch.setattr(recomposition_agent, "_stream_scene_response", fake_stream)
    source = recomposition_agent._repair_scene_source(
        "topic",
        plan,
        json.dumps(candidate, ensure_ascii=False),
        {"errors": [{"type": "missing_intermediate_geometry_stage"}]},
    )

    assert validate_scene_module(source)["ok"]


def test_geometry_ir_normalizer_completes_keyframe_endpoints_from_source_target() -> None:
    plan = normalize_plan({}, "组合图形面积切割重排证明")
    geometry_ir = build_deterministic_geometry_ir(plan)
    piece = geometry_ir["pieces"][0]
    piece["keyframes"] = [
        {
            "at": 0.6,
            "x": 310,
            "y": 180,
            "rotation": 45,
            "scale": piece["source"]["scale"],
            "opacity": 1,
        }
    ]
    normalized = normalize_geometry_ir(geometry_ir, plan)
    keyframes = normalized["pieces"][0]["keyframes"]
    assert [frame["at"] for frame in keyframes] == [0, 0.6, 1]
    assert keyframes[0]["x"] == normalized["pieces"][0]["source"]["x"]
    assert keyframes[-1]["x"] == normalized["pieces"][0]["target"]["x"]
    assert validate_geometry_ir(normalized, plan)["ok"]


def test_semantic_evaluator_rejects_area_changing_scale() -> None:
    plan = normalize_plan({}, "组合图形面积切割重排证明")
    geometry_ir = build_deterministic_geometry_ir(plan)
    geometry_ir["pieces"][0]["target"]["scale"] = 1.2
    report = evaluate_recomposition_semantics(geometry_ir, plan)
    assert not report["ok"]
    assert "mathematical_invariant_failed" in {item["type"] for item in report["errors"]}


def test_plan_normalizes_structured_geometry_relations() -> None:
    plan = normalize_plan(
        {
            "recomposition_spec": {
                "proof_constraints": {
                    "target_relations": [
                        {
                            "id": "Source area = Target area",
                            "type": "equal_area",
                            "left": {"stage": "source"},
                            "right": {"stage": "target"},
                            "tolerance": 1e-7,
                            "ignored": "not part of the relation DSL",
                        },
                        {"id": "unsupported", "type": "topic_specific_relation"},
                    ]
                }
            }
        },
        "组合图形面积切割重排证明",
    )
    relations = plan["recomposition_spec"]["proof_constraints"]["target_relations"]
    assert relations == [
        {
            "id": "source-area-target-area",
            "type": "equal_area",
            "left": {"stage": "source"},
            "right": {"stage": "target"},
            "tolerance": 1e-7,
        }
    ]


def test_plan_normalizes_structured_target_assembly_constraints() -> None:
    plan = normalize_plan(
        {
            "recomposition_spec": {
                "proof_constraints": {
                    "target_assembly": [
                        {
                            "id": "Target rectangle",
                            "type": "approximate_rectangle",
                            "max_components": 0,
                            "max_overlap_ratio": 0.08,
                            "min_rectangularity": 0.7,
                            "monotonic": True,
                            "trend_tolerance": 0.05,
                            "ignored": "not part of the assembly DSL",
                        },
                        {"id": "unsupported", "type": "circle_area_specific"},
                    ]
                }
            }
        },
        "组合图形面积切割重排证明",
    )
    assert plan["recomposition_spec"]["proof_constraints"]["target_assembly"] == [
        {
            "id": "target-rectangle",
            "type": "approximate_rectangle",
            "max_components": 1,
            "max_overlap_ratio": 0.08,
            "min_rectangularity": 0.7,
            "monotonic": True,
            "trend_tolerance": 0.05,
        }
    ]


def test_mathematical_evaluator_computes_generic_relations() -> None:
    plan = {
        "interactive_spec": {"variables": []},
        "recomposition_spec": {
            "proof_constraints": {
                "measure_invariants": [
                    "area_preserved",
                    "length_preserved",
                    "angle_preserved",
                    "piece_congruence",
                ],
                "target_relations": [
                    {
                        "id": "area",
                        "type": "equal_area",
                        "left": {"piece_ids": ["rect-a"], "stage": "source"},
                        "right": {"piece_ids": ["rect-b"], "stage": "target"},
                    },
                    {
                        "id": "length",
                        "type": "equal_length",
                        "left": _segment("line-h", 0, 1),
                        "right": _segment("line-v", 0, 1),
                    },
                    {
                        "id": "angle",
                        "type": "equal_angle",
                        "left": {"points": [_point("tri-a", 1), _point("tri-a", 0), _point("tri-a", 2)]},
                        "right": {"points": [_point("tri-b", 1), _point("tri-b", 0), _point("tri-b", 2)]},
                    },
                    {
                        "id": "parallel",
                        "type": "parallel",
                        "left": _segment("line-h", 0, 1),
                        "right": _segment("line-h2", 0, 1),
                    },
                    {
                        "id": "perpendicular",
                        "type": "perpendicular",
                        "left": _segment("line-h", 0, 1),
                        "right": _segment("line-v", 0, 1),
                    },
                    {
                        "id": "coincident",
                        "type": "coincident",
                        "left": _point("line-h", 1),
                        "right": _point("line-h2", 0),
                    },
                    {
                        "id": "collinear",
                        "type": "collinear",
                        "points": [_point("line-h", 0), _point("line-h", 1), _point("line-h2", 1)],
                    },
                    {
                        "id": "congruent",
                        "type": "congruent",
                        "left": {"piece_id": "tri-a", "stage": "source"},
                        "right": {"piece_id": "tri-b", "stage": "target"},
                    },
                ],
            }
        },
    }
    report = evaluate_mathematical_invariants(_mathematical_geometry_ir(), plan)
    assert report["ok"]
    assert not report["warnings"]
    assert {check["name"] for check in report["checks"] if check["kind"] == "relation"} == {
        "area",
        "length",
        "angle",
        "parallel",
        "perpendicular",
        "coincident",
        "collinear",
        "congruent",
    }


def test_mathematical_evaluator_rejects_false_relation_and_warns_when_unavailable() -> None:
    geometry_ir = _mathematical_geometry_ir()
    plan = {
        "interactive_spec": {"variables": []},
        "recomposition_spec": {
            "proof_constraints": {
                "measure_invariants": [],
                "target_relations": [
                    {
                        "id": "false-parallel",
                        "type": "parallel",
                        "left": _segment("line-h", 0, 1),
                        "right": _segment("line-v", 0, 1),
                    },
                    {
                        "id": "missing-piece",
                        "type": "coincident",
                        "left": _point("line-h", 0),
                        "right": _point("does-not-exist", 0),
                    },
                ],
            }
        },
    }
    report = evaluate_mathematical_invariants(geometry_ir, plan)
    assert not report["ok"]
    assert {item["type"] for item in report["errors"]} == {"mathematical_relation_failed"}
    assert {item["type"] for item in report["warnings"]} == {"target_relation_unavailable"}


def test_ranking_does_not_award_math_points_when_all_relations_are_unavailable() -> None:
    plan = normalize_plan({}, "组合图形面积切割重排证明")
    geometry_ir = build_deterministic_geometry_ir(plan)
    geometry_ir["pieces"][0]["tag"] = "path"
    geometry_ir["pieces"][0]["attrs"] = {"d": "M 0 0 L 20 0 L 10 20 Z", "fill": "#34d399"}
    report = rank_geometry_ir_candidates([geometry_ir], plan)
    candidate = report["candidates"][0]
    assert candidate["eligible"] is True
    assert candidate["details"]["mathematics"]["relation_coverage"] == 0.0
    assert candidate["components"]["mathematical_invariants"] == 0.0


def _point(piece_id: str, index: int, stage: str = "source") -> dict[str, object]:
    return {"piece_id": piece_id, "stage": stage, "anchor": "vertex", "index": index}


def _test_lerp(source: object, target: object, at: float) -> object:
    if source == target:
        return deepcopy(source)
    return {
        "op": "add",
        "args": [
            deepcopy(source),
            {
                "op": "mul",
                "args": [
                    {"op": "sub", "args": [deepcopy(target), deepcopy(source)]},
                    at,
                ],
            },
        ],
    }


def _segment(piece_id: str, start: int, end: int, stage: str = "source") -> dict[str, object]:
    return {"start": _point(piece_id, start, stage), "end": _point(piece_id, end, stage)}


def _interlocking_sector_assembly_ir() -> dict[str, object]:
    source = {
        "x": 220,
        "y": 280,
        "rotation": {
            "op": "rad_to_deg",
            "args": [
                {
                    "op": "mul",
                    "args": [{"local": "i"}, {"var": "angleStep"}],
                }
            ],
        },
        "scale": 1,
        "opacity": 1,
    }
    is_even = {
        "op": "eq",
        "args": [{"op": "mod", "args": [{"local": "i"}, 2]}, 0],
    }
    target = {
        "x": {
            "op": "add",
            "args": [380, {"op": "mul", "args": [{"local": "i"}, {"var": "stepX"}]}],
        },
        "y": {
            "op": "if",
            "args": [
                is_even,
                220,
                {"op": "add", "args": [220, {"var": "stepY"}]},
            ],
        },
        "rotation": {"op": "if", "args": [is_even, 90, -90]},
        "scale": 1,
        "opacity": 1,
    }
    return {
        "version": GEOMETRY_IR_VERSION,
        "definitions": {
            "r": 80,
            "pi": 3.141592653589793,
            "N": {"state": "sectorCount"},
            "angleStep": {
                "op": "div",
                "args": [{"op": "mul", "args": [2, {"var": "pi"}]}, {"var": "N"}],
            },
            "halfAngle": {"op": "div", "args": [{"var": "angleStep"}, 2]},
            "stepX": {
                "op": "mul",
                "args": [
                    {"var": "r"},
                    {"op": "sin", "args": [{"var": "halfAngle"}]},
                ],
            },
            "stepY": {
                "op": "mul",
                "args": [
                    {"var": "r"},
                    {"op": "cos", "args": [{"var": "halfAngle"}]},
                ],
            },
        },
        "pieces": [
            {
                "repeat": {"count": {"var": "N"}, "index": "i"},
                "id": {"op": "concat", "args": ["sector-", {"local": "i"}]},
                "tag": "path",
                "attrs": {
                    "d": {
                        "op": "sector_path",
                        "args": [
                            0,
                            0,
                            {"var": "r"},
                            {"op": "neg", "args": [{"var": "halfAngle"}]},
                            {"var": "halfAngle"},
                        ],
                    },
                    "fill": "#34d399",
                },
                "source": source,
                "target": target,
                "keyframes": [
                    {"at": 0, **source},
                    {"at": 0.5, **source, "x": 300},
                    {"at": 1, **target},
                ],
            }
        ],
        "frames": [
            {"stage_id": "source", "at": 0, "caption": "source", "formula": "", "step": 0},
            {"stage_id": "move", "at": 0.5, "caption": "move", "formula": "", "step": 1},
            {"stage_id": "target", "at": 1, "caption": "target", "formula": "", "step": 2},
        ],
    }


def _rectangular_assembly_ir(plan: dict[str, object]) -> dict[str, object]:
    geometry_ir = build_deterministic_geometry_ir(plan)
    source = {
        "x": {"op": "add", "args": [180, {"op": "mul", "args": [{"local": "i"}, 110]}]},
        "y": 120,
        "rotation": 0,
        "scale": 1,
        "opacity": 1,
    }
    target = {
        "x": {
            "op": "add",
            "args": [420, {"op": "mul", "args": [{"op": "mod", "args": [{"local": "i"}, 2]}, 80]}],
        },
        "y": {
            "op": "add",
            "args": [
                260,
                {"op": "mul", "args": [{"op": "floor", "args": [{"op": "div", "args": [{"local": "i"}, 2]}]}, 60]},
            ],
        },
        "rotation": 0,
        "scale": 1,
        "opacity": 1,
    }
    geometry_ir["definitions"] = {}
    geometry_ir["pieces"] = [
        {
            "repeat": {"count": 4, "index": "i"},
            "id": {"op": "concat", "args": ["tile-", {"local": "i"}]},
            "tag": "rect",
            "attrs": {"x": 0, "y": 0, "width": 80, "height": 60, "fill": "#34d399"},
            "source": source,
            "target": target,
            "keyframes": [
                {"at": 0, **source},
                {
                    "at": 0.5,
                    "x": {"op": "add", "args": [300, {"op": "mul", "args": [{"local": "i"}, 15]}]},
                    "y": {
                        "op": "add",
                        "args": [170, {"op": "mul", "args": [{"op": "mod", "args": [{"local": "i"}, 2]}, 50]}],
                    },
                    "rotation": 20,
                    "scale": 1,
                    "opacity": 1,
                },
                {"at": 1, **target},
            ],
        }
    ]
    return geometry_ir


def _mathematical_geometry_ir() -> dict[str, object]:
    transform = {"x": 0, "y": 0, "rotation": 0, "scale": 1, "opacity": 1}

    def piece(piece_id: str, tag: str, attrs: dict[str, object]) -> dict[str, object]:
        return {
            "id": piece_id,
            "tag": tag,
            "attrs": attrs,
            "source": dict(transform),
            "target": dict(transform),
        }

    return {
        "version": GEOMETRY_IR_VERSION,
        "definitions": {},
        "pieces": [
            piece("rect-a", "rect", {"x": 0, "y": 0, "width": 10, "height": 10}),
            piece("rect-b", "rect", {"x": 20, "y": 0, "width": 10, "height": 10}),
            piece("line-h", "line", {"x1": 0, "y1": 20, "x2": 10, "y2": 20}),
            piece("line-h2", "line", {"x1": 10, "y1": 20, "x2": 20, "y2": 20}),
            piece("line-v", "line", {"x1": 0, "y1": 20, "x2": 0, "y2": 30}),
            piece("tri-a", "polygon", {"points": "0,40 10,40 0,50"}),
            piece("tri-b", "polygon", {"points": "20,40 30,40 20,50"}),
        ],
        "frames": [],
    }


def test_geometry_ir_supports_repeat_scoped_definitions_and_fold_arithmetic() -> None:
    plan = normalize_plan({}, "扇形面积等分重排推导")
    geometry_ir = build_deterministic_geometry_ir(plan)
    geometry_ir["definitions"]["offset"] = {
        "op": "sub",
        "args": [320, {"op": "mul", "args": [{"local": "i"}, 12]}, 5],
    }
    geometry_ir["pieces"][0]["source"]["x"] = {"var": "offset"}
    report = validate_geometry_ir(geometry_ir, plan)
    assert report["ok"]
    assert validate_scene_module(compile_geometry_ir(geometry_ir, plan))["ok"]


def test_geometry_ir_rejects_repeat_index_in_congruent_local_geometry() -> None:
    plan = normalize_plan({}, "扇形面积等分重排推导")
    geometry_ir = build_deterministic_geometry_ir(plan)
    geometry_ir["definitions"]["startAngle"] = {
        "op": "mul",
        "args": [{"local": "i"}, 0.5],
    }
    geometry_ir["pieces"][0]["tag"] = "path"
    geometry_ir["pieces"][0]["attrs"] = {
        "d": {
            "op": "sector_path",
            "args": [0, 0, 54, {"var": "startAngle"}, 0.5],
        },
        "fill": "#34d399",
    }

    report = validate_geometry_ir(geometry_ir, plan)

    assert "repeat_geometry_depends_on_index" in {item["type"] for item in report["errors"]}


def test_geometry_ir_supports_sector_sweep_and_opacity_only_transition() -> None:
    plan = normalize_plan({}, "弓形面积割补推导")
    geometry_ir = {
        "version": GEOMETRY_IR_VERSION,
        "definitions": {},
        "pieces": [
            {
                "id": "arc-piece",
                "tag": "path",
                "attrs": {
                    "d": {"op": "sector_path", "args": [0, 0, 80, 0, 3.14, 0]},
                    "fill": "#34d399",
                },
                "source": {"x": 240, "y": 220, "rotation": 0, "scale": 1, "opacity": 1},
                "target": {"x": 240, "y": 220, "rotation": 0, "scale": 1, "opacity": 0},
            }
        ],
        "frames": [
            {"stage_id": "source", "at": 0, "caption": "源状态", "formula": "A", "step": 0},
            {"stage_id": "transform-1", "at": 0.5, "caption": "比较", "formula": "A=B", "step": 1},
            {"stage_id": "target", "at": 1, "caption": "目标状态", "formula": "B", "step": 2},
        ],
    }
    assert validate_geometry_ir(geometry_ir, plan)["ok"]
    assert validate_scene_module(compile_geometry_ir(geometry_ir, plan))["ok"]


def test_mathematical_evaluator_computes_sector_path_area() -> None:
    plan = normalize_plan({}, "弓形面积割补推导")
    geometry_ir = build_deterministic_geometry_ir(plan)
    geometry_ir["pieces"][0]["tag"] = "path"
    geometry_ir["pieces"][0]["attrs"] = {
        "d": {"op": "sector_path", "args": [0, 0, 80, 0, 1.2]},
        "fill": "#34d399",
    }
    report = evaluate_mathematical_invariants(geometry_ir, plan)
    assert report["ok"]
    assert report["relation_coverage"] == 1.0
    assert not any(item["type"] == "target_relation_unavailable" for item in report["warnings"])


def test_server_scaffold_assembles_valid_bounded_html() -> None:
    plan = normalize_plan({}, "圆的面积推导")
    source = build_deterministic_scene_module(plan)
    assert validate_scene_module(source)["ok"]
    business = assemble_recomposition_business_html(source, plan, "圆的面积推导")
    assembled = assemble_layout_contract(business, plan)
    report = build_validation_report(assembled, plan=plan, model_html=business)
    assert report["ok"]
    assert len(source) <= 12_000
    assert len(business) <= 30_000
    assert not any(error["type"] == "structural_render_inside_animation_frame" for error in report["errors"])


def test_recomposition_runtime_owns_drag_snap_and_presets() -> None:
    plan = normalize_plan(
        {
            "interactive_spec": {
                "type": "simulation",
                "concept": "面积重排",
                "variables": [
                    {"name": "scale", "label": "尺度", "min": 1, "max": 3, "default": 2, "step": 1}
                ],
                "presets": [{"id": "large", "label": "大尺寸", "values": {"scale": 3}}],
            },
            "representation_spec": {
                "views": [{"id": "main", "kind": "geometric_scene"}],
                "state_variables": [{"id": "scale", "semantic_type": "length"}],
                "correspondences": [{"type": "decompose_recompose"}],
                "required_invariants": ["piece_congruence", "area_preserved"],
                "interaction_requirements": ["drag", "preset", "reveal"],
            },
        },
        "面积重排",
    )
    source = build_deterministic_scene_module(plan)
    business = assemble_recomposition_business_html(source, plan, "面积重排")

    assert 'id="recomposition-targets"' in business
    assert 'data-preset-id="large"' in business
    assert "node.addEventListener('pointerdown',beginDrag)" in business
    assert "INTERACTION_CONFIG.snap_distance" in business
    assert "placedPieceCount:placedIds.size" in business


def test_recomposition_regression_uses_project_html_hard_limit() -> None:
    assert html_hard_validation_pass({"html_report": {"ok": True}, "business_chars": 24_469}, {})


def test_lifecycle_error_reports_full_call_chain_and_operation() -> None:
    html = """<script>
    function updateFormulaPanel(){ panel.innerHTML='x'; }
    function updateLabels(){ updateFormulaPanel(); }
    function applyView(){ updateLabels(); }
    window.gsap.to(proxy,{onUpdate:()=>{applyView();}});
    </script>"""
    report = check_animation_lifecycle(html)
    error = report["errors"][0]
    assert error["call_chain"] == ["applyView", "updateLabels", "updateFormulaPanel"]
    assert error["operation"] == "innerHTML"


def test_function_patch_requires_named_target_and_exact_hash() -> None:
    html = """<script>
    function updateLabels(){ panel.innerHTML='x'; }
    function applyView(){ updateLabels(); }
    window.gsap.to(proxy,{onUpdate:()=>{applyView();}});
    </script>"""
    report = check_animation_lifecycle(html)
    targets = target_functions_from_report(report)
    descriptions = describe_target_functions(html, targets)
    target = next(item for item in descriptions if item["function"] == "updateLabels")
    replacement = "function updateLabels(){ panel.textContent='x'; }"
    result = apply_function_replacements(
        html,
        [{"function": "updateLabels", "source_hash": target["source_hash"], "replacement": replacement}],
        allowed_functions=targets,
    )
    assert result.applied == ("updateLabels",)
    assert check_animation_lifecycle(result.html)["ok"]
    stale = apply_function_replacements(
        html,
        [{"function": "updateLabels", "source_hash": "stale", "replacement": replacement}],
        allowed_functions=targets,
    )
    assert stale.html == html
    assert "source_hash_mismatch:updateLabels" in stale.errors


def test_function_patch_supports_arrow_and_object_methods() -> None:
    html = """<script>
    const loop = (now) => { state.progress = now; };
    const runtime = { setSpeed(value) { speed = value; } };
    </script>"""
    descriptions = {item["function"]: item for item in describe_target_functions(html, ("loop", "setSpeed"))}
    result = apply_function_replacements(
        html,
        [
            {
                "function": "loop",
                "source_hash": descriptions["loop"]["source_hash"],
                "replacement": "const loop = (now) => { elapsed = now; state.progress = elapsed; }",
            },
            {
                "function": "setSpeed",
                "source_hash": descriptions["setSpeed"]["source_hash"],
                "replacement": "setSpeed(value) { speed = Math.max(Number(value) || 1, .01); }",
            },
        ],
        allowed_functions=("loop", "setSpeed"),
    )

    assert result.applied == ("loop", "setSpeed")
    assert "elapsed = now" in result.html
    assert "Math.max" in result.html


def test_function_repair_includes_scene_builder_for_variable_topology() -> None:
    from aetherviz_service.aetherviz.tools.function_patch import extract_named_functions

    regex_html = "<script>function render(value){const brace=/\\}/;return brace.test(value);}</script>"
    functions = extract_named_functions(regex_html)
    assert functions["render"][0].source == "function render(value){const brace=/\\}/;return brace.test(value);}"

    html = """<script>
    function buildScene(){ dots.length=0; for(let i=0;i<96;i++){const dot=createDot();stage.appendChild(dot);dots.push(dot);} }
    function updateView(){ while(dots.length<state.sides){const dot=createDot();stage.appendChild(dot);dots.push(dot);} }
    window.gsap.to(proxy,{onUpdate:()=>{updateView();}});
    </script>"""
    report = check_animation_lifecycle(html)

    assert target_functions_from_report(report) == ("updateView",)
    assert repair_function_targets(html, report) == ("updateView", "buildScene")
    assert [item["function"] for item in describe_target_functions(html, repair_function_targets(html, report))] == [
        "updateView",
        "buildScene",
    ]


def test_hard_repair_gate_rejects_truncation_and_new_fatal_errors() -> None:
    baseline = {"ok": False, "errors": [{"type": "structural_render_inside_animation_frame"}]}
    fixed = {"ok": True, "errors": []}
    assert _accept_hard_repair_candidate(
        baseline_report=baseline, candidate_report=fixed, candidate_truncated=False
    ) == (True, None)
    assert _accept_hard_repair_candidate(
        baseline_report=baseline, candidate_report=fixed, candidate_truncated=True
    ) == (False, "truncated_candidate")
    broken = {"ok": False, "errors": [{"type": "js_syntax"}]}
    accepted, reason = _accept_hard_repair_candidate(
        baseline_report=baseline, candidate_report=broken, candidate_truncated=False
    )
    assert not accepted
    assert reason == "new_fatal_errors:js_syntax"


def test_hard_repair_gate_accepts_nonfatal_error_signature_progression() -> None:
    baseline = {"ok": False, "errors": [{"type": "animation_controller_bypass"}]}
    candidate = {"ok": False, "errors": [{"type": "animation_controller_missing_update"}]}

    assert _accept_hard_repair_candidate(
        baseline_report=baseline,
        candidate_report=candidate,
        candidate_truncated=False,
    ) == (True, None)


def test_hard_repair_gate_rejects_same_error_signature_without_reduction() -> None:
    baseline = {"ok": False, "errors": [{"type": "animation_controller_bypass"}]}
    candidate = {"ok": False, "errors": [{"type": "animation_controller_bypass"}]}

    assert _accept_hard_repair_candidate(
        baseline_report=baseline,
        candidate_report=candidate,
        candidate_truncated=False,
    ) == (False, "no_hard_error_reduction")


def test_hard_repair_report_excludes_quality_warnings() -> None:
    report = {
        "ok": False,
        "errors": [{"type": "js_syntax"}],
        "warnings": [{"type": "unformatted_dynamic_value"}],
        "checks": {"js": {"errors": [{"type": "js_syntax"}], "warnings": [{"type": "quality"}]}},
    }
    compact = _hard_error_only_report(report)
    assert compact["warnings"] == []
    assert compact["checks"]["js"]["warnings"] == []


def test_generate_workflow_routes_recomposition_to_scene_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    from aetherviz_service.aetherviz.ir.recomposition import agent as recomposition_agent

    plan = normalize_plan({}, "圆的面积推导")
    monkeypatch.setattr(recomposition_agent, "has_primary_llm_config", lambda: False)
    monkeypatch.setattr(settings, "langsmith_tracing", False)
    monkeypatch.setattr(settings, "aetherviz_max_repair_attempts", 0)
    events = list(run_generate_workflow(run_id="scene-test", topic="圆的面积推导", approved_plan=plan))
    error = next(event for event in events if event.startswith("event: error"))
    payload = json.loads(next(line[6:] for line in error.splitlines() if line.startswith("data: ")))
    assert payload["data"]["code"] == "model_unavailable"
    assert payload["metadata"]["generation_backend"] == "recomposition_scene"
    assert payload["metadata"]["generation_route_source"] == "deterministic"
