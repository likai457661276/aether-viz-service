from __future__ import annotations

from copy import deepcopy

from aetherviz_service.aetherviz.contracts.validation.js_checker import check_inline_javascript
from aetherviz_service.aetherviz.ir.constraint_geometry.contract import (
    CONSTRAINT_GEOMETRY_IR_VERSION,
    compile_constraint_geometry_ir,
    rank_constraint_geometry_ir_candidates,
    repair_constraint_geometry_ir,
    validate_constraint_geometry_ir,
)
from aetherviz_service.aetherviz.ir.constraint_geometry.runtime import (
    assemble_constraint_geometry_business_html,
)
from aetherviz_service.aetherviz.ir.registry import DEFAULT_IR_REGISTRY
from aetherviz_service.aetherviz.ir.router.service import resolve_generation_route
from aetherviz_service.aetherviz.workflow.plan_contract import normalize_plan


def _plan() -> dict:
    return normalize_plan(
        {
            "interactive_type": "simulation",
            "interactive_spec": {
                "type": "simulation",
                "concept": "三角形的中线与高",
                "description": "改变顶点高度并观察中点、等长和垂直关系",
                "variables": [
                    {"name": "height", "label": "顶点高度", "min": 1, "max": 4, "step": 0.1, "default": 2, "unit": ""}
                ],
                "presets": [],
                "observations": ["底边中点和垂直关系保持不变"],
            },
            "knowledge_profile": {
                "subject": "math",
                "concept_family": "geometry",
                "representation_type": "geometric_construction",
                "pedagogy_pattern": "construct_and_measure",
            },
            "representation_spec": {
                "views": [{"id": "geometry", "kind": "geometric_scene", "role": "三角形约束构造"}],
                "state_variables": [{"id": "height", "semantic_type": "length"}],
                "correspondences": [],
                "required_invariants": ["midpoint", "equal_length", "perpendicular"],
                "interaction_requirements": ["scrub", "play", "pause", "reset"],
            },
        },
        "改变三角形顶点，观察中点和高的约束关系",
    )


def _ir() -> dict:
    return {
        "version": CONSTRAINT_GEOMETRY_IR_VERSION,
        "viewport": {"x_min": -4, "x_max": 4, "y_min": -1, "y_max": 5},
        "animation": {"variable": "height", "from": 1, "to": 4, "default": 2, "duration": 6},
        "points": [
            {"id": "A", "label": "A", "x": -3, "y": 0},
            {"id": "B", "label": "B", "x": 3, "y": 0},
            {"id": "C", "label": "C", "x": 0, "y": {"state": "height"}},
            {"id": "M", "label": "M", "x": 0, "y": 0},
        ],
        "lines": [
            {"id": "AB", "from": "A", "to": "B", "kind": "segment", "label": "底边"},
            {"id": "AM", "from": "A", "to": "M", "kind": "segment", "label": "左半底边"},
            {"id": "MB", "from": "M", "to": "B", "kind": "segment", "label": "右半底边"},
            {"id": "CM", "from": "C", "to": "M", "kind": "segment", "label": "高"},
            {"id": "AC", "from": "A", "to": "C", "kind": "segment", "label": "左边"},
            {"id": "BC", "from": "B", "to": "C", "kind": "segment", "label": "右边"},
        ],
        "circles": [],
        "angles": [],
        "loci": [],
        "constraints": [
            {"type": "horizontal", "refs": ["A", "B"], "tolerance": 0.000001},
            {"type": "midpoint", "refs": ["M", "A", "B"], "tolerance": 0.000001},
            {"type": "equal_length", "refs": ["AM", "MB"], "tolerance": 0.000001},
            {"type": "perpendicular", "refs": ["AB", "CM"], "tolerance": 0.000001},
        ],
        "observation": "改变顶点高度时，M 始终是 AB 的中点，CM 始终垂直于 AB。",
    }


def _tangent_plan() -> dict:
    seed = deepcopy(_plan())
    seed["interactive_spec"]["concept"] = "圆的切线与轨迹"
    seed["interactive_spec"]["description"] = "拖动圆外点并观察切点、直角与切点轨迹"
    seed["interactive_spec"]["variables"] = [
        {"name": "external_x", "label": "圆外点横坐标", "min": 3, "max": 6, "step": 0.05, "default": 4}
    ]
    seed["representation_spec"]["state_variables"] = [{"id": "external_x", "semantic_type": "scalar"}]
    seed["representation_spec"]["required_invariants"] = ["point_on_circle", "perpendicular", "tangent"]
    seed["representation_spec"]["interaction_requirements"] = ["drag", "trace", "play", "pause", "reset"]
    return normalize_plan(seed, "拖动圆外点构造切线并记录切点轨迹")


def _tangent_ir() -> dict:
    d = {"state": "external_x"}
    tangent_x = {"op": "div", "args": [4, d]}
    tangent_y = {
        "op": "div",
        "args": [
            {
                "op": "mul",
                "args": [2, {"op": "sqrt", "args": [{"op": "sub", "args": [{"op": "pow", "args": [d, 2]}, 4]}]}],
            },
            d,
        ],
    }
    return {
        "version": CONSTRAINT_GEOMETRY_IR_VERSION,
        "viewport": {"x_min": -3, "x_max": 7, "y_min": -1, "y_max": 5},
        "animation": {"variable": "external_x", "from": 3, "to": 6, "default": 4, "duration": 6},
        "points": [
            {"id": "O", "label": "O", "x": 0, "y": 0},
            {
                "id": "E",
                "label": "E",
                "x": d,
                "y": 0,
                "drag": {"state": "external_x", "mode": "x", "unit": "scalar"},
            },
            {"id": "T", "label": "T", "x": tangent_x, "y": tangent_y},
        ],
        "lines": [
            {"id": "OT", "from": "O", "to": "T", "kind": "segment", "label": "半径"},
            {"id": "ET", "from": "E", "to": "T", "kind": "segment", "label": "切线"},
        ],
        "circles": [{"id": "circle", "center": "O", "radius": 2, "label": "圆 O"}],
        "angles": [{"id": "right-angle", "from": "O", "vertex": "T", "to": "E", "label": "切线角", "precision": 1}],
        "loci": [{"id": "tangent-locus", "point": "T", "label": "切点轨迹", "max_samples": 240, "min_distance": 0.01}],
        "constraints": [
            {"type": "point_on_circle", "refs": ["T", "circle"], "tolerance": 0.000001},
            {"type": "perpendicular", "refs": ["OT", "ET"], "tolerance": 0.000001},
            {"type": "tangent", "refs": ["ET", "circle", "T"], "tolerance": 0.000001},
        ],
        "observation": "移动圆外点时，切点始终在圆上，半径始终垂直于切线。",
    }


def test_constraint_geometry_ir_validates_compiles_and_uses_server_runtime() -> None:
    plan, ir = _plan(), _ir()

    assert validate_constraint_geometry_ir(ir, plan)["ok"]
    assert CONSTRAINT_GEOMETRY_IR_VERSION in compile_constraint_geometry_ir(ir, plan)
    business_html = assemble_constraint_geometry_business_html(ir, plan, "三角形约束")

    assert 'id="constraint-geometry-ir"' in business_html
    assert "window.AetherVizAnimationController.create" in business_html
    assert "window.AetherVizRuntime" in business_html
    assert "requestAnimationFrame" not in business_html
    assert check_inline_javascript(business_html)["ok"]


def test_constraint_geometry_ir_rejects_constraint_that_fails_at_sampled_states() -> None:
    invalid = deepcopy(_ir())
    invalid["points"][3]["x"] = 0.25

    report = validate_constraint_geometry_ir(invalid, _plan())

    assert not report["ok"]
    assert any(item["type"] == "geometry_invariant_failed" for item in report["errors"])


def test_constraint_geometry_candidate_ranking_prefers_valid_candidate() -> None:
    invalid = deepcopy(_ir())
    invalid["points"][3]["x"] = 0.25

    ranking = rank_constraint_geometry_ir_candidates([invalid, _ir()], _plan())

    assert ranking["ok"]
    assert ranking["selected_ir"]["points"][3]["x"] == 0


def test_constraint_geometry_plan_routes_without_stealing_discrete_parametric_geometry() -> None:
    route = resolve_generation_route(_plan())

    assert route.selected_backend == "constraint_geometry_scene"
    backend = DEFAULT_IR_REGISTRY.get("constraint_geometry_scene")
    assert backend is not None
    assert backend.assess is not None and backend.assess(_plan()).eligible


def test_constraint_geometry_routes_plan_level_point_on_curve_alias() -> None:
    plan = normalize_plan(
        {
            "interactive_type": "simulation",
            "interactive_spec": {
                "type": "simulation",
                "concept": "圆的切线",
                "description": "移动外点后切点、半径和切线约束保持成立",
                "variables": [
                    {"name": "external_x", "label": "圆外点位置", "min": 3, "max": 8, "step": 0.1, "default": 5}
                ],
            },
            "knowledge_profile": {
                "subject": "math",
                "concept_family": "geometry",
                "representation_type": "geometric_construction",
                "pedagogy_pattern": "construct_and_measure",
            },
            "representation_spec": {
                "views": [{"id": "geometry", "kind": "geometric_scene", "role": "圆、切点、半径和切线"}],
                "state_variables": [{"id": "external_x", "semantic_type": "scalar"}],
                "correspondences": [
                    {
                        "type": "point_on_curve",
                        "source_view": "geometry",
                        "target_view": "geometry",
                        "parameter": "external_x",
                    }
                ],
                "required_invariants": ["point_on_curve", "angle_preserved"],
                "interaction_requirements": ["drag", "reset"],
            },
        },
        "移动圆外点，构造切线并验证半径垂直于切线",
    )

    assert resolve_generation_route(plan).selected_backend == "constraint_geometry_scene"


def test_constraint_geometry_does_not_route_generic_point_on_curve_without_geometry_prior() -> None:
    plan = normalize_plan(
        {
            "interactive_type": "simulation",
            "interactive_spec": {
                "type": "simulation",
                "concept": "任意曲线运动",
                "description": "动点沿贝塞尔曲线运动",
                "variables": [{"name": "t", "label": "曲线参数", "min": 0, "max": 1, "step": 0.01, "default": 0.5}],
            },
            "knowledge_profile": {"representation_type": "object_scene"},
            "representation_spec": {
                "views": [{"id": "geometry", "kind": "geometric_scene", "role": "贝塞尔曲线与动点"}],
                "state_variables": [{"id": "t", "semantic_type": "scalar"}],
                "correspondences": [
                    {"type": "point_on_curve", "source_view": "geometry", "target_view": "geometry", "parameter": "t"}
                ],
                "required_invariants": ["point_on_curve"],
                "interaction_requirements": ["scrub"],
            },
        },
        "动点沿任意贝塞尔曲线运动",
    )

    backend = DEFAULT_IR_REGISTRY.get("constraint_geometry_scene")
    assert backend is not None and backend.assess is not None
    assert not backend.assess(plan).eligible
    assert resolve_generation_route(plan).selected_backend != "constraint_geometry_scene"


def test_constraint_geometry_deterministic_repair_strips_inactive_drag_and_bad_refs() -> None:
    noisy = deepcopy(_ir())
    noisy["points"][0]["drag"] = {"state": "height", "mode": "x"}  # A.x is constant
    noisy["points"][2]["drag"] = {"state": "height", "mode": "y"}  # C.y uses height
    noisy["points"][3]["x"] = 1
    noisy["points"][3]["y"] = 1  # wrong midpoint; repair should rewrite from A/B
    noisy["angles"] = [{"id": "bad", "from": "M", "vertex": "M", "to": "C", "label": "坏角", "precision": 1}]
    noisy["constraints"].append({"type": "equal_length", "refs": ["BM", "MC"], "tolerance": 0.000001})
    noisy["constraints"].append({"type": "coincident", "refs": ["M", "AB"], "tolerance": 0.000001})

    repaired = repair_constraint_geometry_ir(noisy, _plan())
    ranking = rank_constraint_geometry_ir_candidates([noisy], _plan())

    assert isinstance(repaired, dict)
    assert "drag" not in repaired["points"][0]
    assert repaired["points"][2].get("drag", {}).get("mode") == "y"
    assert repaired["points"][3]["x"] == 0
    assert repaired["points"][3]["y"] == 0
    assert repaired["angles"] == []
    assert all(item["type"] != "equal_length" or item["refs"] != ["BM", "MC"] for item in repaired["constraints"])
    assert all(not (item["type"] == "coincident" and item["refs"] == ["M", "AB"]) for item in repaired["constraints"])
    assert ranking["ok"]


def test_constraint_geometry_repair_does_not_accept_empty_constraint_result() -> None:
    invalid = deepcopy(_ir())
    invalid["constraints"] = [{"type": "coincident", "refs": ["M", "AB"], "tolerance": 0.000001}]

    repaired = repair_constraint_geometry_ir(invalid, _plan())
    ranking = rank_constraint_geometry_ir_candidates([invalid], _plan())

    assert isinstance(repaired, dict)
    assert repaired["constraints"] == invalid["constraints"]
    assert not ranking["ok"]
    assert any(item["type"] == "geometry_invariant_failed" for item in ranking["repair_report"]["errors"])


def test_constraint_geometry_repair_handles_malformed_collection_fields() -> None:
    for field in ("points", "lines", "circles", "angles", "loci", "constraints"):
        malformed = deepcopy(_ir())
        malformed[field] = None

        ranking = rank_constraint_geometry_ir_candidates([malformed], _plan())

        assert isinstance(ranking, dict)
        if field in {"points", "constraints"}:
            assert not ranking["ok"]


def test_constraint_geometry_deterministic_repair_rewrites_aliases_and_expression_midpoint() -> None:
    alias = deepcopy(_ir())
    alias["points"][3]["x"] = {"op": "div", "args": [{"op": "add", "args": [{"state": "A.x"}, {"state": "B.x"}]}, 2]}
    alias["points"][3]["y"] = {"state": "A.y"}
    expression = deepcopy(_ir())
    expression["viewport"] = {"x_min": -5, "x_max": 5, "y_min": -1, "y_max": 5}
    expression["points"][0]["x"] = {"op": "neg", "args": [{"state": "height"}]}
    expression["points"][1]["x"] = {"state": "height"}
    expression["points"][3]["x"] = 1
    expression["points"][3]["y"] = 1

    repaired_alias = repair_constraint_geometry_ir(alias, _plan())
    repaired_expression = repair_constraint_geometry_ir(expression, _plan())

    assert isinstance(repaired_alias, dict)
    assert repaired_alias["points"][3]["x"] == 0.0
    assert repaired_alias["points"][3]["y"] == 0.0
    assert validate_constraint_geometry_ir(repaired_alias, _plan())["ok"]
    assert isinstance(repaired_expression, dict)
    assert isinstance(repaired_expression["points"][3]["x"], dict)
    assert repaired_expression["points"][3]["x"]["op"] == "div"
    assert repaired_expression["points"][3]["y"] == 0.0
    assert validate_constraint_geometry_ir(repaired_expression, _plan())["ok"]


def test_constraint_geometry_v11_supports_tangent_angle_drag_and_bounded_locus() -> None:
    plan, ir = _tangent_plan(), _tangent_ir()

    assert validate_constraint_geometry_ir(ir, plan)["ok"]
    business_html = assemble_constraint_geometry_business_html(ir, plan, "圆的切线")

    assert "setPointerCapture" in business_html
    assert "angleNodes" in business_html
    assert "locusSamples" in business_html
    assert "samples.length>item.max_samples" in business_html
    assert check_inline_javascript(business_html)["ok"]
    assert resolve_generation_route(plan).selected_backend == "constraint_geometry_scene"


def test_constraint_geometry_v11_rejects_false_tangent_and_unbounded_locus() -> None:
    invalid_tangent = deepcopy(_tangent_ir())
    invalid_tangent["points"][2]["y"] = 1
    tangent_report = validate_constraint_geometry_ir(invalid_tangent, _tangent_plan())

    invalid_locus = deepcopy(_tangent_ir())
    invalid_locus["loci"][0]["max_samples"] = 5000
    locus_report = validate_constraint_geometry_ir(invalid_locus, _tangent_plan())

    assert any(item["type"] == "geometry_invariant_failed" for item in tangent_report["errors"])
    assert any(item["type"] == "invalid_geometry_locus_bounds" for item in locus_report["errors"])


def test_constraint_geometry_v11_validates_equal_and_supplementary_angles() -> None:
    ir = deepcopy(_ir())
    ir["angles"] = [
        {"id": "left-right", "from": "A", "vertex": "M", "to": "C", "label": "左直角", "precision": 1},
        {"id": "right-right", "from": "C", "vertex": "M", "to": "B", "label": "右直角", "precision": 1},
    ]
    ir["constraints"].extend(
        [
            {"type": "equal_angle", "refs": ["left-right", "right-right"], "tolerance": 0.000001},
            {"type": "supplementary", "refs": ["left-right", "right-right"], "tolerance": 0.000001},
        ]
    )

    assert validate_constraint_geometry_ir(ir, _plan())["ok"]


def test_constraint_geometry_v11_accepts_circle_and_segment_projection_drag_bindings() -> None:
    circle_plan = deepcopy(_tangent_plan())
    circle_plan["interactive_spec"]["variables"] = [
        {"name": "theta", "label": "圆周角", "min": 0, "max": 360, "step": 1, "default": 45, "unit": "°"}
    ]
    circle_plan["representation_spec"]["state_variables"] = [
        {"id": "theta", "semantic_type": "angle", "unit": "degree"}
    ]
    circle_plan["representation_spec"]["required_invariants"] = ["point_on_circle"]
    circle_plan = normalize_plan(circle_plan, "拖动圆周点并记录轨迹")
    radians = {"op": "deg_to_rad", "args": [{"state": "theta"}]}
    circle_ir = {
        "version": CONSTRAINT_GEOMETRY_IR_VERSION,
        "viewport": {"x_min": -3, "x_max": 3, "y_min": -3, "y_max": 3},
        "animation": {"variable": "theta", "from": 0, "to": 360, "default": 45, "duration": 8},
        "points": [
            {"id": "O", "label": "O", "x": 0, "y": 0},
            {
                "id": "P",
                "label": "P",
                "x": {"op": "mul", "args": [2, {"op": "cos", "args": [radians]}]},
                "y": {"op": "mul", "args": [2, {"op": "sin", "args": [radians]}]},
                "drag": {"state": "theta", "mode": "angle_on_circle", "ref": "circle", "unit": "degree"},
            },
        ],
        "lines": [],
        "circles": [{"id": "circle", "center": "O", "radius": 2, "label": "圆 O"}],
        "angles": [],
        "loci": [{"id": "circle-locus", "point": "P", "label": "圆周轨迹", "max_samples": 360, "min_distance": 0.01}],
        "constraints": [{"type": "point_on_circle", "refs": ["P", "circle"], "tolerance": 0.000001}],
        "observation": "拖动 P 时，P 始终位于圆上。",
    }

    segment_plan = deepcopy(_plan())
    segment_plan["interactive_spec"]["variables"] = [
        {"name": "ratio", "label": "线段位置", "min": 0, "max": 1, "step": 0.01, "default": 0.5}
    ]
    segment_plan["representation_spec"]["state_variables"] = [{"id": "ratio", "semantic_type": "ratio"}]
    segment_plan["representation_spec"]["required_invariants"] = ["collinear"]
    segment_plan["representation_spec"]["interaction_requirements"] = ["drag", "reset"]
    segment_plan = normalize_plan(segment_plan, "在线段上拖动分点")
    segment_ir = {
        "version": CONSTRAINT_GEOMETRY_IR_VERSION,
        "viewport": {"x_min": -3, "x_max": 3, "y_min": -2, "y_max": 2},
        "animation": {"variable": "ratio", "from": 0, "to": 1, "default": 0.5, "duration": 5},
        "points": [
            {"id": "A", "label": "A", "x": -2, "y": 0},
            {"id": "B", "label": "B", "x": 2, "y": 0},
            {
                "id": "P",
                "label": "P",
                "x": {"op": "add", "args": [-2, {"op": "mul", "args": [4, {"state": "ratio"}]}]},
                "y": 0,
                "drag": {"state": "ratio", "mode": "segment_parameter", "ref": "AB", "unit": "scalar"},
            },
        ],
        "lines": [{"id": "AB", "from": "A", "to": "B", "kind": "segment", "label": "线段 AB"}],
        "circles": [],
        "angles": [],
        "loci": [],
        "constraints": [{"type": "collinear", "refs": ["A", "P", "B"], "tolerance": 0.000001}],
        "observation": "P 始终在线段 AB 上。",
    }

    assert validate_constraint_geometry_ir(circle_ir, circle_plan)["ok"]
    assert validate_constraint_geometry_ir(segment_ir, segment_plan)["ok"]
    html = assemble_constraint_geometry_business_html(circle_ir, circle_plan, "圆周拖拽")
    assert "drag.mode==='angle_on_circle'" in html
    assert "drag.mode==='segment_parameter'" in html
