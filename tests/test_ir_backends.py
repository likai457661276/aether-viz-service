from __future__ import annotations

import json
from copy import deepcopy

import pytest

from aetherviz_service.aetherviz.contracts.html_stream import HtmlGenerationError
from aetherviz_service.aetherviz.contracts.layout import assemble_layout_contract
from aetherviz_service.aetherviz.contracts.validation.report import build_validation_report
from aetherviz_service.aetherviz.ir.coordinate_graph import agent as coordinate_graph_agent
from aetherviz_service.aetherviz.ir.coordinate_graph.contract import (
    COORDINATE_GRAPH_IR_VERSION,
    compile_coordinate_graph_ir,
    coordinate_graph_ir_response_schema,
    validate_coordinate_graph_ir,
)
from aetherviz_service.aetherviz.ir.coordinate_graph.runtime import (
    assemble_coordinate_graph_business_html,
)
from aetherviz_service.aetherviz.ir.linked_coordinate.contract import (
    LINKED_COORDINATE_INVARIANT_MAX_TOLERANCE,
    LINKED_COORDINATE_IR_VERSION,
    compile_linked_coordinate_ir,
    linked_coordinate_ir_candidates_response_schema,
    linked_coordinate_ir_response_schema,
    normalize_linked_coordinate_ir,
    rank_linked_coordinate_ir_candidates,
    validate_linked_coordinate_ir,
)
from aetherviz_service.aetherviz.ir.linked_coordinate.runtime import (
    assemble_linked_coordinate_business_html,
)
from aetherviz_service.aetherviz.ir.parametric_geometry.contract import (
    PARAMETRIC_GEOMETRY_IR_VERSION,
    compile_parametric_geometry_ir,
    validate_parametric_geometry_ir,
)
from aetherviz_service.aetherviz.ir.parametric_geometry.runtime import (
    assemble_parametric_geometry_business_html,
)
from aetherviz_service.aetherviz.ir.registry import (
    DEFAULT_IR_REGISTRY,
    IRBackend,
    IRBackendRegistry,
)
from aetherviz_service.aetherviz.workflow.knowledge_profile import build_knowledge_profile
from aetherviz_service.aetherviz.workflow.plan_contract import normalize_plan


def _plan() -> dict:
    return normalize_plan(
        {
            "interactive_type": "simulation",
            "interactive_spec": {
                "type": "simulation",
                "concept": "多坐标表征",
                "description": "观察同一参数在两个坐标系中的对应关系",
                "variables": [
                    {
                        "name": "theta",
                        "label": "参数",
                        "min": 0,
                        "max": 6.283185307179586,
                        "step": 0.01,
                        "default": 1,
                        "unit": "rad",
                    }
                ],
                "presets": [],
                "observations": ["两个动态点共享相同纵坐标"],
            },
        },
        "函数曲线与坐标轨迹参数联动",
    )


def _operand(kind: str, ref: str = "", *, at: object = 0, axis: str = "both", value: object = 0) -> dict:
    return {"kind": kind, "ref": ref, "at": at, "axis": axis, "value": value}


def _ir() -> dict:
    theta = {"state": "theta"}
    local_t = {"local": "t"}
    sine_theta = {"op": "sin", "args": [theta]}
    return {
        "version": LINKED_COORDINATE_IR_VERSION,
        "definitions": [{"name": "tau", "value": 6.283185307179586}],
        "animation": {"variable": "theta", "from": 0, "to": {"var": "tau"}, "duration": 4},
        "coordinate_systems": [
            {
                "id": "phase-space",
                "x": 40,
                "y": 110,
                "width": 360,
                "height": 360,
                "x_domain": [-1.4, 1.4],
                "y_domain": [-1.4, 1.4],
                "label": "参数轨迹",
            },
            {
                "id": "function-space",
                "x": 470,
                "y": 110,
                "width": 450,
                "height": 360,
                "x_domain": [0, {"var": "tau"}],
                "y_domain": [-1.4, 1.4],
                "label": "函数图像",
            },
        ],
        "curves": [
            {
                "id": "trajectory",
                "system": "phase-space",
                "parameter": "t",
                "parameter_unit": "radian",
                "domain": [0, {"var": "tau"}],
                "samples": 120,
                "x": {"op": "cos", "args": [local_t]},
                "y": {"op": "sin", "args": [local_t]},
                "stroke": "#2563eb",
            },
            {
                "id": "function-curve",
                "system": "function-space",
                "parameter": "t",
                "parameter_unit": "radian",
                "domain": [0, {"var": "tau"}],
                "samples": 120,
                "x": local_t,
                "y": {"op": "sin", "args": [local_t]},
                "stroke": "#10b981",
            },
        ],
        "points": [
            {
                "id": "trajectory-point",
                "system": "phase-space",
                "x": {"op": "cos", "args": [theta]},
                "y": sine_theta,
                "radius": 7,
                "fill": "#ef4444",
                "label": "P",
            },
            {
                "id": "function-point",
                "system": "function-space",
                "x": theta,
                "y": sine_theta,
                "radius": 7,
                "fill": "#ef4444",
                "label": "Q",
            },
        ],
        "links": [
            {
                "id": "value-projection",
                "from": "trajectory-point",
                "to": "function-point",
                "stroke": "#94a3b8",
                "dash": "6 5",
            }
        ],
        "invariants": [
            {
                "id": "trajectory-membership",
                "type": "point_on_curve",
                "left": _operand("point", "trajectory-point"),
                "right": _operand("curve_sample", "trajectory", at=theta),
                "tolerance": 0.000001,
            },
            {
                "id": "function-membership",
                "type": "point_on_curve",
                "left": _operand("point", "function-point"),
                "right": _operand("curve_sample", "function-curve", at=theta),
                "tolerance": 0.000001,
            },
            {
                "id": "shared-value",
                "type": "equal_value",
                "left": _operand("point", "trajectory-point", axis="y"),
                "right": _operand("point", "function-point", axis="y"),
                "tolerance": 0.000001,
            },
        ],
    }


def _coordinate_plan() -> dict:
    return normalize_plan(
        {
            "interactive_type": "simulation",
            "interactive_spec": {
                "type": "simulation",
                "concept": "一次函数图像",
                "description": "调节参数并观察单一坐标平面中的曲线变化",
                "variables": [
                    {
                        "name": "theta",
                        "label": "参数",
                        "min": 0,
                        "max": 6.283185307179586,
                        "step": 0.01,
                        "default": 1,
                        "unit": "rad",
                    }
                ],
                "presets": [],
                "observations": ["动态点始终位于曲线上"],
            },
            "representation_spec": {
                "views": [{"id": "graph", "kind": "coordinate_plane", "role": "函数图像"}],
                "state_variables": [{"id": "theta", "semantic_type": "scalar"}],
                "correspondences": [],
                "required_invariants": ["point_on_curve"],
            },
        },
        "一次函数图像",
    )


def _coordinate_ir() -> dict:
    candidate = deepcopy(_ir())
    candidate["version"] = COORDINATE_GRAPH_IR_VERSION
    candidate["coordinate_systems"] = [candidate["coordinate_systems"][0]]
    candidate["curves"] = [candidate["curves"][0]]
    candidate["points"] = [candidate["points"][0]]
    candidate["links"] = []
    candidate["invariants"] = [candidate["invariants"][0]]
    return candidate


def test_default_ir_registry_routes_all_independent_ir_families() -> None:
    recomposition = DEFAULT_IR_REGISTRY.resolve(
        {"knowledge_profile": {"representation_type": "geometric_recomposition"}}
    )
    linked = DEFAULT_IR_REGISTRY.resolve({"knowledge_profile": {"representation_type": "linked_coordinate_scene"}})
    assert recomposition and recomposition.key == "recomposition_scene"
    assert linked and linked.key == "linked_coordinate_scene"
    coordinate = DEFAULT_IR_REGISTRY.resolve({"knowledge_profile": {"representation_type": "coordinate_graph"}})
    assert coordinate and coordinate.key == "coordinate_graph_scene"
    parametric = DEFAULT_IR_REGISTRY.resolve({"knowledge_profile": {"representation_type": "geometric_construction"}})
    assert parametric and parametric.key == "parametric_geometry_scene"
    number_line = DEFAULT_IR_REGISTRY.resolve({"knowledge_profile": {"representation_type": "number_line"}})
    assert number_line and number_line.key == "number_line_scene"


def _parametric_plan() -> dict:
    return normalize_plan(
        {
            "interactive_type": "simulation",
            "interactive_spec": {
                "type": "simulation",
                "concept": "离散正多边形逼近圆",
                "description": "调节边数并观察周长误差",
                "variables": [
                    {"name": "sides", "label": "边数", "min": 3, "max": 100, "step": 1, "default": 6, "unit": "边"}
                ],
                "presets": [],
                "observations": ["边数增加时误差收敛"],
            },
            "knowledge_profile": {
                "subject": "math",
                "concept_family": "geometry",
                "representation_type": "geometric_construction",
                "pedagogy_pattern": "parameter_exploration",
            },
            "representation_spec": {
                "views": [
                    {"id": "geometry", "kind": "geometric_scene", "role": "圆与正多边形"},
                    {"id": "measure", "kind": "data_chart", "role": "误差变化"},
                ],
                "state_variables": [{"id": "sides", "semantic_type": "discrete"}],
                "correspondences": [
                    {"type": "derived_value", "source_view": "geometry", "target_view": "measure", "parameter": "sides"}
                ],
                "required_invariants": ["length_preserved"],
                "interaction_requirements": ["scrub", "play", "pause", "reset"],
            },
        },
        "离散正多边形逼近圆",
    )


def _parametric_ir() -> dict:
    return {
        "version": PARAMETRIC_GEOMETRY_IR_VERSION,
        "state": {
            "variable": "sides",
            "label": "边数",
            "minimum": 3,
            "maximum": 100,
            "default": 6,
            "step": 1,
            "unit": "边",
        },
        "circle": {"radius": 1, "label": "目标圆"},
        "polygons": [
            {"id": "inner", "mode": "inscribed", "label": "内接正多边形", "color": "#2563EB"},
            {"id": "outer", "mode": "circumscribed", "label": "外切正多边形", "color": "#F97316"},
        ],
        "measures": [
            {"id": "inner-p", "type": "polygon_perimeter", "polygon": "inner", "label": "内接周长", "precision": 5},
            {"id": "outer-p", "type": "polygon_perimeter", "polygon": "outer", "label": "外切周长", "precision": 5},
            {"id": "inner-error", "type": "absolute_error", "polygon": "inner", "label": "内接误差", "precision": 6},
        ],
        "animation": {"duration": 6},
        "invariants": ["regular_polygon", "vertex_on_circle", "bounded_by_circle", "monotonic_convergence"],
    }


def test_parametric_geometry_ir_compiles_and_runtime_is_server_owned() -> None:
    plan = _parametric_plan()
    ir = _parametric_ir()

    assert validate_parametric_geometry_ir(ir, plan)["ok"]
    assert PARAMETRIC_GEOMETRY_IR_VERSION in compile_parametric_geometry_ir(ir, plan)
    business_html = assemble_parametric_geometry_business_html(ir, plan, "正多边形逼近")
    assert "requestAnimationFrame" not in business_html
    assert "AetherVizAnimationController.create" in business_html
    assert "for(let i=0;i<IR.state.maximum;i++)" in business_html
    assembled = assemble_layout_contract(business_html, plan)
    report = build_validation_report(assembled, plan=plan, model_html=business_html)
    assert report["ok"], report["errors"]


def test_parametric_geometry_ir_rejects_convergence_without_error_measure() -> None:
    ir = _parametric_ir()
    ir["measures"] = [ir["measures"][0]]

    report = validate_parametric_geometry_ir(ir, _parametric_plan())

    assert not report["ok"]
    assert any(item["type"] == "missing_convergence_measure" for item in report["errors"])


def test_registry_select_for_route_prefers_ir_then_explicit_unsupported_failure() -> None:
    from aetherviz_service.aetherviz.ir.registry import UNSUPPORTED_GENERATION_BACKEND
    from aetherviz_service.aetherviz.ir.router.contracts import IRRouteDecision

    calls: list[str] = []

    def ir_stream(topic: str, plan: dict):
        calls.append(f"ir:{topic}")
        yield {"delta": "y"}

    registry = IRBackendRegistry((IRBackend("demo_scene", frozenset({"demo_repr"}), ir_stream),))
    ir_route = IRRouteDecision(
        selected_backend="demo_scene",
        source="deterministic",
        confidence=0.9,
        plan_fingerprint="fp",
        candidates=(),
    )
    selection = registry.select_for_route(ir_route, topic="主题", plan={})
    assert selection.generation_backend == "demo_scene"
    assert selection.ir_backend is not None
    list(selection.stream_factory())
    assert calls == ["ir:主题"]

    unsupported_route = IRRouteDecision(
        selected_backend=None,
        source="fallback",
        confidence=0.0,
        plan_fingerprint="fp",
        candidates=(),
    )
    unsupported = registry.select_for_route(unsupported_route, topic="主题", plan={})
    assert unsupported.generation_backend == UNSUPPORTED_GENERATION_BACKEND
    assert unsupported.ir_backend is None
    with pytest.raises(HtmlGenerationError) as exc_info:
        list(unsupported.stream_factory())
    assert exc_info.value.code == "unsupported_ir_capability"
    assert calls == ["ir:主题"]

    unknown = registry.select_for_route(
        IRRouteDecision(
            selected_backend="missing_backend",
            source="llm",
            confidence=0.5,
            plan_fingerprint="fp",
            candidates=(),
        ),
        topic="主题",
        plan={},
    )
    assert unknown.generation_backend == UNSUPPORTED_GENERATION_BACKEND


def test_ir_registry_rejects_backend_and_representation_collisions() -> None:
    def stream(_topic: str, _plan: dict):
        yield from ()

    registry = IRBackendRegistry((IRBackend("one", frozenset({"shared"}), stream),))
    with pytest.raises(ValueError, match="duplicate_ir_backend"):
        registry.register(IRBackend("one", frozenset({"other"}), stream))
    with pytest.raises(ValueError, match="duplicate_ir_representation"):
        registry.register(IRBackend("two", frozenset({"shared"}), stream))


def test_coordinate_graph_contract_requires_one_coordinate_system() -> None:
    schema = coordinate_graph_ir_response_schema()
    assert schema["properties"]["coordinate_systems"]["maxItems"] == 1
    report = validate_coordinate_graph_ir(_coordinate_ir(), _coordinate_plan())
    assert report["ok"], report

    broken = _coordinate_ir()
    broken["coordinate_systems"].append({**broken["coordinate_systems"][0], "id": "second"})
    broken_report = validate_coordinate_graph_ir(broken, _coordinate_plan())
    assert not broken_report["ok"]
    assert any(error["type"] == "coordinate_graph_requires_single_system" for error in broken_report["errors"])


def test_coordinate_graph_multivariable_animation_requires_complete_keyframes() -> None:
    plan = _coordinate_plan()
    plan["interactive_spec"]["variables"].append(
        {"name": "h", "label": "水平平移", "min": -4, "max": 4, "default": 0, "step": 0.1, "unit": ""}
    )
    plan["representation_spec"]["state_variables"].append(
        {
            "id": "h",
            "semantic_type": "scalar",
            "minimum": -4,
            "maximum": 4,
            "default": 0,
            "unit": "",
            "display_unit": "",
        }
    )
    candidate = _coordinate_ir()
    missing = validate_coordinate_graph_ir(candidate, plan)
    assert any(error["type"] == "missing_multi_state_keyframes" for error in missing["errors"])

    candidate["animation"]["keyframes"] = [
        {"progress": 0, "state": {"theta": 0, "h": -4}},
        {"progress": 0.5, "state": {"theta": 3.141592653589793, "h": 0}},
        {"progress": 1, "state": {"theta": 6.283185307179586, "h": 4}},
    ]
    report = validate_coordinate_graph_ir(candidate, plan)
    assert report["ok"], report


def test_coordinate_graph_runtime_owns_svg_units_and_family_metadata() -> None:
    plan = _coordinate_plan()
    compiled = json.loads(compile_coordinate_graph_ir(_coordinate_ir(), plan))
    html = assemble_coordinate_graph_business_html(compiled, plan, "一次函数图像")
    assembled = assemble_layout_contract(html, plan)
    report = build_validation_report(assembled, plan=plan, model_html=html)

    assert compiled["version"] == COORDINATE_GRAPH_IR_VERSION
    assert 'viewBox="0 0 960 560"' in html
    assert "vector-effect:non-scaling-stroke" in html
    assert '"family":"coordinate_graph"' in html
    assert "irFamily:'linked_coordinate'" not in html
    assert report["ok"], report


def test_coordinate_graph_ir_failure_stops_without_direct_html(monkeypatch) -> None:
    responses = iter(['{"candidates":[{},{}]}', "{}"])
    monkeypatch.setattr(coordinate_graph_agent, "has_primary_llm_config", lambda: True)
    monkeypatch.setattr(coordinate_graph_agent, "_stream_ir", lambda *_args: next(responses))
    with pytest.raises(HtmlGenerationError) as exc_info:
        list(coordinate_graph_agent.stream_generate_coordinate_graph_html("一次函数图像", _coordinate_plan()))

    assert exc_info.value.code == "ir_generation_failed"
    assert exc_info.value.detail == "coordinate_graph_ir_invalid"


def test_linked_coordinate_profile_uses_generic_multi_representation_evidence() -> None:
    assert build_knowledge_profile("函数曲线与坐标轨迹参数联动")["representation_type"] == "linked_coordinate_scene"
    assert build_knowledge_profile("三角函数单位圆与正弦波")["representation_type"] == "linked_coordinate_scene"
    assert build_knowledge_profile("一次函数图像")["representation_type"] == "coordinate_graph"


def test_linked_coordinate_ir_schema_is_strict_and_contract_accepts_shared_model() -> None:
    schema = linked_coordinate_ir_response_schema()
    assert schema["additionalProperties"] is False
    assert schema["properties"]["invariants"]["minItems"] == 1
    report = validate_linked_coordinate_ir(_ir(), _plan())
    assert report["ok"], report
    assert compile_linked_coordinate_ir(_ir(), _plan()).startswith("{")


def test_linked_coordinate_compiler_normalizes_schema_shaped_ir() -> None:
    candidate = deepcopy(_ir())
    for system in candidate["coordinate_systems"]:
        for key in ("x", "y", "width", "height"):
            system.pop(key)
    for curve in candidate["curves"]:
        curve.pop("parameter_unit")

    compiled = json.loads(compile_linked_coordinate_ir(candidate, _plan()))

    assert all({"x", "y", "width", "height"} <= set(system) for system in compiled["coordinate_systems"])
    assert all(curve["parameter_unit"] == "radian" for curve in compiled["curves"])


def test_linked_coordinate_schema_separates_state_and_curve_expression_scopes() -> None:
    schema = linked_coordinate_ir_response_schema()
    state_variants = schema["$defs"]["state_expression"]["anyOf"]
    curve_variants = schema["$defs"]["curve_expression"]["anyOf"]

    assert not any("local" in item.get("properties", {}) for item in state_variants)
    assert any("local" in item.get("properties", {}) for item in curve_variants)
    curve_schema = schema["properties"]["curves"]["items"]
    system_schema = schema["properties"]["coordinate_systems"]["items"]
    reveal = curve_schema["properties"]["reveal"]
    assert "parameter_unit" in curve_schema["required"]
    assert curve_schema["properties"]["parameter_unit"]["enum"] == [
        "degree",
        "radian",
        "scalar",
    ]
    assert not {"x", "y", "width", "height"} & set(system_schema["properties"])
    assert "reveal" in curve_schema["required"]
    assert set(reveal["anyOf"][0]["required"]) == {"value", "from", "to"}
    assert reveal["anyOf"][1] == {"type": "null"}


def test_linked_coordinate_ir_rejects_degree_state_without_explicit_conversion() -> None:
    plan = _plan()
    plan["interactive_spec"]["variables"][0].update({"min": 0, "max": 360, "default": 90, "unit": "°"})
    broken = deepcopy(_ir())
    broken["animation"]["to"] = 360
    report = validate_linked_coordinate_ir(broken, plan)

    assert not report["ok"]
    assert any(error["type"] == "degree_trig_requires_conversion" for error in report["errors"])


def test_linked_coordinate_ir_accepts_explicit_degree_to_radian_conversion() -> None:
    plan = _plan()
    plan["interactive_spec"]["variables"][0].update({"min": 0, "max": 360, "default": 90, "unit": "degree"})
    converted = deepcopy(_ir())
    converted["animation"]["to"] = 360
    state_angle = {"op": "deg_to_rad", "args": [{"state": "theta"}]}
    converted["points"][0]["x"] = {"op": "cos", "args": [state_angle]}
    converted["points"][0]["y"] = {"op": "sin", "args": [state_angle]}
    converted["points"][1]["x"] = {"state": "theta"}
    converted["points"][1]["y"] = {"op": "sin", "args": [state_angle]}
    for invariant in converted["invariants"][:2]:
        invariant["right"]["at"] = {"state": "theta"}
    for curve in converted["curves"]:
        curve["parameter_unit"] = "degree"
        local = {"op": "deg_to_rad", "args": [{"local": "t"}]}
        curve["domain"] = [0, 360]
        if curve["id"] == "trajectory":
            curve["x"] = {"op": "cos", "args": [local]}
            curve["y"] = {"op": "sin", "args": [local]}
        else:
            curve["x"] = {"local": "t"}
            curve["y"] = {"op": "sin", "args": [local]}

    report = validate_linked_coordinate_ir(converted, plan)
    assert report["ok"], report


def test_linked_coordinate_candidate_schema_and_ranking_select_valid_ir() -> None:
    schema = linked_coordinate_ir_candidates_response_schema()
    assert schema["properties"]["candidates"]["minItems"] == 2
    assert schema["properties"]["candidates"]["maxItems"] == 2
    broken = deepcopy(_ir())
    broken["points"][1]["y"] = 0
    ranking = rank_linked_coordinate_ir_candidates([broken, _ir()], _plan())
    assert ranking["ok"]
    assert ranking["selected_index"] == 1
    assert ranking["candidates"][0]["eligible"] is False


def test_linked_coordinate_ranking_repairs_trace_layout_and_mixed_curve_units() -> None:
    plan = _plan()
    plan["interactive_spec"]["variables"][0].update({"min": 0, "max": 360, "default": 90, "unit": "degree"})
    plan["representation_spec"]["state_variables"][0].update(
        {"minimum": 0, "maximum": 360, "default": 90, "unit": "degree"}
    )
    candidate = deepcopy(_ir())
    candidate["definitions"].append(
        {
            "name": "theta_rad",
            "value": {"op": "deg_to_rad", "args": [{"state": "theta"}]},
        }
    )
    candidate["animation"]["to"] = 360
    candidate["coordinate_systems"][0].update({"x": 240, "y": 280, "width": 400, "height": 400})
    candidate["coordinate_systems"][1].update({"x": 720, "y": 280, "width": 400, "height": 400})
    radian_curve, degree_curve = candidate["curves"]
    radian_curve.pop("parameter_unit")
    degree_curve.pop("parameter_unit")
    degree_local = {"op": "deg_to_rad", "args": [{"local": "t"}]}
    degree_curve.update(
        {
            "domain": [0, 360],
            "x": {"local": "t"},
            "y": {"op": "sin", "args": [degree_local]},
        }
    )
    theta_rad = {"var": "theta_rad"}
    candidate["points"][0]["x"] = {"op": "cos", "args": [theta_rad]}
    candidate["points"][0]["y"] = {"op": "sin", "args": [theta_rad]}
    candidate["points"][1]["x"] = {"state": "theta"}
    candidate["points"][1]["y"] = {"op": "sin", "args": [theta_rad]}
    candidate["invariants"][0]["right"]["at"] = theta_rad
    candidate["invariants"][1]["right"]["at"] = {"state": "theta"}

    ranking = rank_linked_coordinate_ir_candidates([candidate], plan)

    assert ranking["ok"], ranking
    selected = ranking["selected_ir"]
    assert [curve["parameter_unit"] for curve in selected["curves"]] == ["radian", "degree"]
    assert all(
        system["x"] >= 0
        and system["y"] >= 0
        and system["x"] + system["width"] <= 960
        and system["y"] + system["height"] <= 560
        for system in selected["coordinate_systems"]
    )


@pytest.mark.parametrize("system_count", [1, 2, 3, 4])
def test_linked_coordinate_layout_normalization_fits_supported_system_counts(
    system_count: int,
) -> None:
    candidate = deepcopy(_ir())
    template = candidate["coordinate_systems"][0]
    candidate["coordinate_systems"] = [{**deepcopy(template), "id": f"system-{index}"} for index in range(system_count)]

    normalized = normalize_linked_coordinate_ir(candidate, _plan())

    assert isinstance(normalized, dict)
    assert all(
        system["width"] >= 120
        and system["height"] >= 120
        and system["x"] + system["width"] <= 960
        and system["y"] + system["height"] <= 560
        for system in normalized["coordinate_systems"]
    )


def test_linked_coordinate_ir_rejects_unknown_curve_parameter_unit() -> None:
    broken = deepcopy(_ir())
    broken["curves"][0]["parameter_unit"] = "angle"

    report = validate_linked_coordinate_ir(broken, _plan())

    assert not report["ok"]
    assert any(error["type"] == "invalid_curve_parameter_unit" for error in report["errors"])


def test_linked_coordinate_ir_warns_for_english_prose_system_labels_without_blocking() -> None:
    candidate = deepcopy(_ir())
    candidate["coordinate_systems"][0]["label"] = "Unit Circle"

    report = validate_linked_coordinate_ir(candidate, _plan())

    assert report["ok"], report
    assert any(warning["type"] == "non_chinese_visible_label" for warning in report["warnings"])


def test_linked_coordinate_ranking_prefers_chinese_label_but_keeps_english_fallback() -> None:
    english = deepcopy(_ir())
    english["coordinate_systems"][0]["label"] = "Unit Circle"
    chinese = deepcopy(_ir())

    preferred = rank_linked_coordinate_ir_candidates([english, chinese], _plan())
    fallback = rank_linked_coordinate_ir_candidates([english], _plan())

    assert preferred["ok"]
    assert preferred["selected_index"] == 1
    assert fallback["ok"]
    assert fallback["selected_index"] == 0


def test_linked_coordinate_ir_keeps_mathematical_point_symbols() -> None:
    candidate = deepcopy(_ir())
    candidate["points"][0]["label"] = "P"
    candidate["points"][1]["label"] = "θ"

    report = validate_linked_coordinate_ir(candidate, _plan())

    assert report["ok"], report


def test_linked_coordinate_ir_keeps_formula_only_system_label() -> None:
    candidate = deepcopy(_ir())
    candidate["coordinate_systems"][0]["label"] = "y=sin(x)"

    report = validate_linked_coordinate_ir(candidate, _plan())

    assert report["ok"], report


def test_linked_coordinate_ranking_scopes_repair_report_to_one_candidate() -> None:
    first = deepcopy(_ir())
    second = deepcopy(_ir())
    first["points"][1]["y"] = 0
    second["points"][0]["x"] = 0
    second["points"][1]["y"] = 0

    ranking = rank_linked_coordinate_ir_candidates([first, second], _plan())

    assert not ranking["ok"]
    repair_index = ranking["repair_index"]
    repair_candidate = next(item for item in ranking["candidates"] if item["index"] == repair_index)
    assert ranking["repair_report"] == repair_candidate["report"]
    assert len(ranking["repair_report"]["errors"]) == len(repair_candidate["report"]["errors"])


def test_linked_coordinate_ranking_normalizes_progress_domain_and_tolerance() -> None:
    plan = _plan()
    plan["interactive_spec"]["variables"][0]["default"] = 0
    plan["representation_spec"]["state_variables"][0]["default"] = 0
    candidate = deepcopy(_ir())
    candidate["curves"].append(
        {
            "id": "progressive-trace",
            "system": "function-space",
            "parameter": "t",
            "parameter_unit": "radian",
            "domain": [0, {"state": "theta"}],
            "samples": 60,
            "x": {"local": "t"},
            "y": {"op": "sin", "args": [{"local": "t"}]},
            "stroke": "#ef4444",
        }
    )
    for invariant in candidate["invariants"]:
        invariant["tolerance"] = 0.1

    ranking = rank_linked_coordinate_ir_candidates([candidate], plan)

    assert ranking["ok"], ranking
    assert ranking["candidates"][0]["normalized"] is True
    selected = ranking["selected_ir"]
    trace = next(curve for curve in selected["curves"] if curve["id"] == "progressive-trace")
    maximum = plan["interactive_spec"]["variables"][0]["max"]
    assert trace["domain"] == [0.0, maximum]
    assert trace["reveal"] == {
        "value": {"state": "theta"},
        "from": 0.0,
        "to": maximum,
    }
    assert all(
        invariant["tolerance"] == LINKED_COORDINATE_INVARIANT_MAX_TOLERANCE for invariant in selected["invariants"]
    )


def test_linked_coordinate_ir_rejects_degenerate_reveal_range() -> None:
    broken = deepcopy(_ir())
    broken["curves"][1]["reveal"] = {
        "value": {"state": "theta"},
        "from": 0,
        "to": 0,
    }

    report = validate_linked_coordinate_ir(broken, _plan())

    assert not report["ok"]
    assert any("invalid_curve_reveal" in error["message"] for error in report["errors"])


def test_linked_coordinate_ir_rejects_point_with_duplicated_wrong_sign() -> None:
    broken = deepcopy(_ir())
    broken["points"][1]["y"] = {
        "op": "neg",
        "args": [{"op": "sin", "args": [{"state": "theta"}]}],
    }
    report = validate_linked_coordinate_ir(broken, _plan())
    assert not report["ok"]
    assert any(error["type"] == "linked_coordinate_ir_semantics" for error in report["errors"])
    assert any("function-membership" in error["message"] for error in report["errors"])


def test_linked_coordinate_ir_checks_interior_states_when_endpoints_are_degenerate() -> None:
    plan = _plan()
    plan["interactive_spec"]["variables"][0]["default"] = 0
    plan["representation_spec"]["state_variables"][0]["default"] = 0
    broken = deepcopy(_ir())
    broken["points"][1]["y"] = 0

    report = validate_linked_coordinate_ir(broken, plan)

    assert not report["ok"]
    assert any(
        error["type"] == "linked_coordinate_ir_semantics" and error.get("state") == "theta:quarter"
        for error in report["errors"]
    )


def test_linked_coordinate_ir_requires_plan_invariant_coverage() -> None:
    broken = deepcopy(_ir())
    broken["invariants"] = [item for item in broken["invariants"] if item["type"] != "equal_value"]

    report = validate_linked_coordinate_ir(broken, _plan())

    assert not report["ok"]
    assert any(
        error["type"] == "missing_required_invariant" and error.get("invariant") == "equal_value"
        for error in report["errors"]
    )


def test_linked_coordinate_ir_rejects_overly_permissive_tolerance() -> None:
    broken = deepcopy(_ir())
    broken["invariants"][0]["tolerance"] = 0.1

    report = validate_linked_coordinate_ir(broken, _plan())

    assert not report["ok"]
    assert any(error["type"] == "invalid_invariant_tolerance" for error in report["errors"])


def test_linked_coordinate_runtime_is_server_owned_and_passes_html_contract() -> None:
    plan = _plan()
    ir = _ir()
    ir["curves"][1]["reveal"] = {
        "value": {"state": "theta"},
        "from": 0,
        "to": {"var": "tau"},
    }
    business_html = assemble_linked_coordinate_business_html(ir, plan, "参数联动")
    assert "requestAnimationFrame" not in business_html
    assert "AetherVizAnimationController.create" in business_html
    assert "aetherviz.linked-coordinate-ir.v1" in business_html
    assert "pathLength:1" in business_html
    assert "curve.reveal" in business_html
    html = assemble_layout_contract(business_html, plan)
    report = build_validation_report(html, plan=plan, model_html=business_html)
    assert report["ok"], report["errors"]
