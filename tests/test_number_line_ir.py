from __future__ import annotations

from copy import deepcopy

from aetherviz_service.aetherviz.contracts.layout import assemble_layout_contract
from aetherviz_service.aetherviz.contracts.validation.report import build_validation_report
from aetherviz_service.aetherviz.ir.number_line.contract import (
    NUMBER_LINE_IR_VERSION,
    compile_number_line_ir,
    number_line_ir_candidates_response_schema,
    rank_number_line_ir_candidates,
    validate_number_line_ir,
)
from aetherviz_service.aetherviz.ir.number_line.runtime import assemble_number_line_business_html
from aetherviz_service.aetherviz.ir.registry import DEFAULT_IR_REGISTRY
from aetherviz_service.aetherviz.ir.router.service import resolve_generation_route
from aetherviz_service.aetherviz.workflow.plan_contract import normalize_plan


def _plan() -> dict:
    return normalize_plan(
        {
            "subject": "math",
            "interactive_type": "simulation",
            "interactive_spec": {
                "type": "simulation",
                "concept": "绝对值、区间与数轴位移",
                "description": "调节两个数并观察区间、距离和位移",
                "variables": [
                    {"name": "x", "label": "点 x", "min": -8, "max": 8, "step": 0.5, "default": 3},
                    {"name": "a", "label": "点 a", "min": -8, "max": 8, "step": 0.5, "default": -1},
                ],
            },
            "knowledge_profile": {
                "subject": "math",
                "concept_family": "number",
                "representation_type": "number_line",
                "pedagogy_pattern": "parameter_exploration",
            },
            "representation_spec": {
                "views": [
                    {"id": "line", "kind": "number_line", "role": "数轴对象"},
                    {"id": "formula", "kind": "symbolic_panel", "role": "数值关系"},
                ],
                "state_variables": [
                    {"id": "x", "semantic_type": "scalar"},
                    {"id": "a", "semantic_type": "scalar"},
                ],
                "correspondences": [
                    {"type": "derived_value", "source_view": "line", "target_view": "formula", "parameter": "x"}
                ],
                "required_invariants": ["equal_value"],
                "interaction_requirements": ["scrub", "play", "pause", "reset"],
            },
        },
        "绝对值、区间与数轴位移",
    )


def _ir() -> dict:
    x = {"state": "x"}
    a = {"state": "a"}
    return {
        "version": NUMBER_LINE_IR_VERSION,
        "domain": [-20, 20],
        "animation": {
            "variable": "x",
            "from": -8,
            "to": 8,
            "duration": 6,
            "keyframes": [
                {"progress": 0, "state": {"x": -8, "a": -8}},
                {"progress": 1, "state": {"x": 8, "a": 8}},
            ],
        },
        "tracks": [{"id": "main", "label": "数轴关系"}],
        "points": [
            {"id": "point-x", "track": "main", "label": "x", "color": "#0F766E", "value": x, "endpoint": "closed"},
            {"id": "point-a", "track": "main", "label": "a", "color": "#2563EB", "value": a, "endpoint": "open"},
        ],
        "intervals": [
            {
                "id": "between",
                "track": "main",
                "label": "两点之间",
                "color": "#14B8A6",
                "start": {"op": "min", "args": [x, a]},
                "end": {"op": "max", "args": [x, a]},
                "left_endpoint": "closed",
                "right_endpoint": "closed",
            }
        ],
        "rays": [
            {
                "id": "solution-ray",
                "track": "main",
                "label": "x 以上",
                "color": "#F97316",
                "boundary": x,
                "direction": "right",
                "endpoint": "closed",
            }
        ],
        "distances": [
            {"id": "distance", "track": "main", "label": "|x-a|", "color": "#7C3AED", "start": x, "end": a}
        ],
        "movements": [
            {"id": "movement", "track": "main", "label": "a+x", "color": "#DC2626", "start": a, "delta": x}
        ],
        "invariants": [
            {"id": "interval-order", "type": "ordered_interval", "refs": ["between"]},
            {"id": "distance-value", "type": "distance_equals_absolute_difference", "refs": ["distance"]},
            {"id": "movement-sum", "type": "movement_equals_sum", "refs": ["movement"]},
        ],
    }


def test_number_line_ir_schema_contract_and_runtime() -> None:
    plan = _plan()
    ir = _ir()

    schema = number_line_ir_candidates_response_schema()
    assert schema["properties"]["candidates"]["minItems"] == 2
    assert validate_number_line_ir(ir, plan)["ok"]
    assert NUMBER_LINE_IR_VERSION in compile_number_line_ir(ir, plan)
    business_html = assemble_number_line_business_html(ir, plan, "绝对值与数轴")
    assert "requestAnimationFrame" not in business_html
    assert "AetherVizAnimationController.create" in business_html
    assert 'id="number-line-ir"' in business_html
    assert "window.AetherVizRuntime" in business_html
    assembled = assemble_layout_contract(business_html, plan)
    report = build_validation_report(assembled, plan=plan, model_html=business_html)
    assert report["ok"], report["errors"]


def test_number_line_ir_rejects_crossing_interval() -> None:
    broken = deepcopy(_ir())
    broken["intervals"][0]["start"] = {"state": "x"}
    broken["intervals"][0]["end"] = {"state": "a"}

    report = validate_number_line_ir(broken, _plan())

    assert not report["ok"]
    assert any(item["type"] == "number_line_ir_semantics" for item in report["errors"])


def test_number_line_ir_rejects_unknown_track_and_out_of_domain_movement() -> None:
    unknown_track = deepcopy(_ir())
    unknown_track["points"][0]["track"] = "missing"
    narrow_domain = deepcopy(_ir())
    narrow_domain["domain"] = [-10, 10]

    track_report = validate_number_line_ir(unknown_track, _plan())
    domain_report = validate_number_line_ir(narrow_domain, _plan())

    assert any(item["type"] == "unknown_number_line_track" for item in track_report["errors"])
    assert any(item["type"] == "number_line_ir_semantics" for item in domain_report["errors"])


def test_number_line_candidate_ranking_prefers_valid_ir() -> None:
    broken = deepcopy(_ir())
    broken["intervals"][0]["track"] = "missing"

    ranking = rank_number_line_ir_candidates([broken, _ir()], _plan())

    assert ranking["ok"]
    assert ranking["selected_ir"] == _ir()


def test_number_line_backend_is_registered_and_selected_by_capabilities() -> None:
    plan = _plan()
    backend = DEFAULT_IR_REGISTRY.resolve(plan)
    route = resolve_generation_route(plan)

    assert backend and backend.key == "number_line_scene"
    assert route.selected_backend == "number_line_scene"
    assessment = next(item for item in route.candidates if item.backend_key == "number_line_scene")
    assert assessment.eligible
    assert {"number_line", "ordered_scale", "state_parameter"} <= set(assessment.matched_capabilities)


def test_number_line_backend_does_not_capture_coordinate_graph() -> None:
    plan = normalize_plan({}, "绘制正弦函数图像并调节振幅")
    route = resolve_generation_route(plan)

    assert route.selected_backend == "coordinate_graph_scene"
    assessment = next(item for item in route.candidates if item.backend_key == "number_line_scene")
    assert not assessment.eligible


def test_number_line_topic_gets_deterministic_representation_fallback() -> None:
    plan = normalize_plan({}, "拖动数轴端点观察绝对值与不等式区间")

    assert plan["knowledge_profile"]["representation_type"] == "number_line"
    assert plan["representation_spec"]["views"] == [
        {"id": "number-line-view", "kind": "number_line", "role": "数、区间与一维关系"}
    ]
    assert resolve_generation_route(plan).selected_backend == "number_line_scene"
