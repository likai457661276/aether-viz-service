from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from playwright.sync_api import sync_playwright

from aetherviz_service.aetherviz.contracts.html_stream import HtmlStreamResult
from aetherviz_service.aetherviz.contracts.layout import assemble_layout_contract
from aetherviz_service.aetherviz.contracts.validation.report import build_validation_report
from aetherviz_service.aetherviz.ir.number_line.contract import (
    NUMBER_LINE_IR_VERSION,
    compile_number_line_ir,
    number_line_ir_candidates_response_schema,
    rank_number_line_ir_candidates,
    repair_number_line_ir,
    validate_number_line_ir,
)
from aetherviz_service.aetherviz.ir.number_line.runtime import assemble_number_line_business_html
from aetherviz_service.aetherviz.ir.registry import DEFAULT_IR_REGISTRY
from aetherviz_service.aetherviz.ir.router.service import resolve_generation_route
from aetherviz_service.aetherviz.workflow.plan_contract import normalize_plan
from evals.targets.visual import evaluate_playback_progress


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
        "distances": [{"id": "distance", "track": "main", "label": "|x-a|", "color": "#7C3AED", "start": x, "end": a}],
        "movements": [{"id": "movement", "track": "main", "label": "a+x", "color": "#DC2626", "start": a, "delta": x}],
        "derived_sets": [],
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


def test_number_line_ir_rejects_invariant_target_of_wrong_object_type() -> None:
    broken = deepcopy(_ir())
    broken["invariants"][0]["refs"] = ["point-x"]

    report = validate_number_line_ir(broken, _plan())

    assert not report["ok"]
    assert any(item["type"] == "invalid_number_line_invariant_target" for item in report["errors"])


def test_number_line_ir_accepts_ray_boundary_invariant() -> None:
    candidate = _ir()
    candidate["invariants"] = [{"id": "ray-boundary", "type": "ray_boundary_consistent", "refs": ["solution-ray"]}]

    report = validate_number_line_ir(candidate, _plan())

    assert report["ok"], report["errors"]


def test_number_line_ir_validates_derived_set_references() -> None:
    candidate = deepcopy(_ir())
    candidate["intervals"] = [
        {
            "id": "left-set",
            "track": "main",
            "label": "A",
            "color": "#0F766E",
            "start": -4,
            "end": 2,
            "left_endpoint": "closed",
            "right_endpoint": "closed",
        },
        {
            "id": "right-set",
            "track": "main",
            "label": "B",
            "color": "#2563EB",
            "start": 0,
            "end": 5,
            "left_endpoint": "closed",
            "right_endpoint": "closed",
        },
    ]
    candidate["derived_sets"] = [
        {
            "id": "intersection",
            "track": "main",
            "label": "A∩B",
            "color": "#7C3AED",
            "operation": "intersection",
            "inputs": ["left-set", "right-set"],
        }
    ]
    candidate["invariants"] = [{"id": "ordered", "type": "ordered_interval", "refs": ["left-set", "right-set"]}]

    valid = validate_number_line_ir(candidate, _plan())
    candidate["derived_sets"][0]["inputs"][1] = "missing"
    invalid = validate_number_line_ir(candidate, _plan())

    assert valid["ok"], valid
    assert not invalid["ok"]
    assert any(item["type"] == "invalid_number_line_derived_set_ref" for item in invalid["errors"])


def test_number_line_candidate_ranking_prefers_valid_ir() -> None:
    broken = deepcopy(_ir())
    broken["intervals"][0]["track"] = "missing"

    ranking = rank_number_line_ir_candidates([broken, _ir()], _plan())

    assert ranking["ok"]
    assert ranking["selected_ir"] == _ir()


def test_number_line_normalizes_missing_multi_variable_keyframes() -> None:
    candidate = _ir()
    candidate["animation"]["keyframes"] = []

    ranking = rank_number_line_ir_candidates([candidate], _plan())

    assert ranking["ok"]
    assert ranking["selected_ir"]["animation"]["keyframes"] == [
        {"progress": 0, "state": {"x": -8.0, "a": -8.0}},
        {"progress": 1, "state": {"x": 8.0, "a": 8.0}},
    ]


def test_number_line_movement_delta_is_not_treated_as_absolute_coordinate() -> None:
    candidate = _ir()
    candidate["domain"] = [-8, 8]
    candidate["movements"] = [
        {
            "id": "long-delta",
            "track": "main",
            "label": "跨越原点",
            "color": "#DC2626",
            "start": -8,
            "delta": 16,
        }
    ]
    candidate["invariants"] = [{"id": "movement-sum", "type": "movement_equals_sum", "refs": ["long-delta"]}]

    report = validate_number_line_ir(candidate, _plan())

    assert report["ok"], report


def test_number_line_validation_samples_combined_variable_extremes() -> None:
    plan = _plan()
    for variable in plan["interactive_spec"]["variables"]:
        variable["default"] = 0
    candidate = _ir()
    candidate["domain"] = [-8, 8]
    candidate["points"] = [
        {
            "id": "sum",
            "track": "main",
            "label": "x+a",
            "color": "#0F766E",
            "value": {"op": "add", "args": [{"state": "x"}, {"state": "a"}]},
            "endpoint": "closed",
        }
    ]
    candidate["intervals"] = []
    candidate["rays"] = []
    candidate["distances"] = []
    candidate["movements"] = []
    candidate["invariants"] = [{"id": "sum-on-line", "type": "point_on_number_line", "refs": ["sum"]}]

    report = validate_number_line_ir(candidate, plan)

    assert not report["ok"]
    assert any("combination:" in item["message"] for item in report["errors"])


def test_number_line_repair_orders_crossing_interval_endpoints() -> None:
    candidate = _ir()
    candidate["intervals"][0]["start"] = {"state": "x"}
    candidate["intervals"][0]["end"] = {"state": "a"}

    repaired = repair_number_line_ir(candidate, _plan())

    assert validate_number_line_ir(repaired, _plan())["ok"]
    assert repaired["intervals"][0]["start"]["op"] == "min"
    assert repaired["intervals"][0]["end"]["op"] == "max"


def test_number_line_repair_retargets_invariant_to_matching_object_type() -> None:
    candidate = _ir()
    candidate["invariants"] = [{"id": "wrong-target", "type": "ordered_interval", "refs": ["point-x"]}]

    repaired = repair_number_line_ir(candidate, _plan())

    assert validate_number_line_ir(repaired, _plan())["ok"]
    assert repaired["invariants"][0]["refs"] == ["between"]


def test_number_line_agent_repairs_each_candidate_before_model_retry(monkeypatch) -> None:
    from aetherviz_service.aetherviz.ir.number_line import agent

    unrepairable = _ir()
    unrepairable["points"][0]["value"] = {"state": "missing"}
    repairable = _ir()
    repairable["intervals"][0]["start"] = {"state": "x"}
    repairable["intervals"][0]["end"] = {"state": "a"}
    raw = json.dumps({"candidates": [unrepairable, repairable]}, ensure_ascii=False)
    calls = 0

    def fake_invoke(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return raw

    monkeypatch.setattr(agent, "has_primary_llm_config", lambda: True)
    monkeypatch.setattr(agent, "_invoke", fake_invoke)

    result = next(
        item
        for item in agent.stream_generate_number_line_html("动态区间", _plan())
        if isinstance(item, HtmlStreamResult)
    )

    assert result.strategy == "number_line_ir"
    assert result.degraded is True
    assert calls == 1


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


def test_number_line_runtime_derives_dynamic_set_topology(tmp_path: Path) -> None:
    plan = normalize_plan(
        {
            "interactive_type": "simulation",
            "interactive_spec": {
                "type": "simulation",
                "concept": "动态集合运算",
                "description": "移动区间边界并观察并集与交集",
                "variables": [{"name": "boundary", "label": "边界", "min": -2, "max": 2, "step": 1, "default": -2}],
            },
            "knowledge_profile": {"subject": "math", "representation_type": "number_line"},
        },
        "动态区间并集与交集",
    )
    boundary = {"state": "boundary"}
    intervals = [
        {
            "id": "open-a",
            "track": "input",
            "label": "A",
            "color": "#2563EB",
            "start": -4,
            "end": 1,
            "left_endpoint": "closed",
            "right_endpoint": "open",
        },
        {
            "id": "open-b",
            "track": "input",
            "label": "B",
            "color": "#10B981",
            "start": boundary,
            "end": 4,
            "left_endpoint": "open",
            "right_endpoint": "closed",
        },
        {
            "id": "closed-a",
            "track": "input",
            "label": "C",
            "color": "#0F766E",
            "start": -4,
            "end": 1,
            "left_endpoint": "closed",
            "right_endpoint": "closed",
        },
        {
            "id": "closed-b",
            "track": "input",
            "label": "D",
            "color": "#F97316",
            "start": boundary,
            "end": 4,
            "left_endpoint": "closed",
            "right_endpoint": "closed",
        },
    ]
    ir = {
        "version": NUMBER_LINE_IR_VERSION,
        "domain": [-5, 5],
        "animation": {"variable": "boundary", "from": -2, "to": 2, "duration": 2, "keyframes": []},
        "tracks": [
            {"id": "input", "label": "输入区间"},
            {"id": "union", "label": "并集"},
            {"id": "intersection", "label": "交集"},
        ],
        "points": [],
        "intervals": intervals,
        "rays": [],
        "distances": [],
        "movements": [],
        "derived_sets": [
            {
                "id": "open-union",
                "track": "union",
                "label": "A∪B",
                "color": "#8B5CF6",
                "operation": "union",
                "inputs": ["open-a", "open-b"],
            },
            {
                "id": "open-intersection",
                "track": "intersection",
                "label": "A∩B",
                "color": "#EF4444",
                "operation": "intersection",
                "inputs": ["open-a", "open-b"],
            },
            {
                "id": "closed-union",
                "track": "union",
                "label": "C∪D",
                "color": "#0891B2",
                "operation": "union",
                "inputs": ["closed-a", "closed-b"],
            },
            {
                "id": "closed-intersection",
                "track": "intersection",
                "label": "C∩D",
                "color": "#DB2777",
                "operation": "intersection",
                "inputs": ["closed-a", "closed-b"],
            },
        ],
        "invariants": [{"id": "ordered", "type": "ordered_interval", "refs": [item["id"] for item in intervals]}],
    }
    assert validate_number_line_ir(ir, plan)["ok"]
    html_path = tmp_path / "number-line-derived-sets.html"
    html_path.write_text(
        assemble_layout_contract(assemble_number_line_business_html(ir, plan, "动态集合运算"), plan),
        encoding="utf-8",
    )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(html_path.resolve().as_uri(), wait_until="load")
        page.wait_for_function("window.__AETHERVIZ_RUNTIME_READY__ === true")
        page.evaluate("() => window.AetherVizRuntime.update({boundary: 1})")
        counts_at_touch = page.eval_on_selector_all(
            '[data-kind="derived_set"]',
            "nodes => Object.fromEntries(nodes.map(node => [node.dataset.object, Number(node.dataset.segmentCount)]))",
        )
        page.evaluate("() => window.AetherVizRuntime.update({boundary: 2})")
        counts_disjoint = page.eval_on_selector_all(
            '[data-kind="derived_set"]',
            "nodes => Object.fromEntries(nodes.map(node => [node.dataset.object, Number(node.dataset.segmentCount)]))",
        )
        browser.close()

    assert counts_at_touch == {
        "open-union": 2,
        "open-intersection": 0,
        "closed-union": 1,
        "closed-intersection": 1,
    }
    assert counts_disjoint == {
        "open-union": 2,
        "open-intersection": 0,
        "closed-union": 2,
        "closed-intersection": 0,
    }


def test_number_line_runtime_advances_in_offline_browser(tmp_path: Path) -> None:
    plan = normalize_plan(
        {
            "interactive_type": "simulation",
            "interactive_spec": {
                "type": "simulation",
                "concept": "不等式射线",
                "description": "移动边界点",
                "variables": [{"name": "boundary", "label": "边界", "min": -8, "max": 8, "step": 1, "default": -8}],
            },
            "knowledge_profile": {"subject": "math", "representation_type": "number_line"},
            "representation_spec": {
                "views": [{"id": "line", "kind": "number_line", "role": "解集"}],
                "state_variables": [{"id": "boundary", "semantic_type": "scalar"}],
            },
        },
        "数轴不等式射线",
    )
    ir = {
        "version": NUMBER_LINE_IR_VERSION,
        "domain": [-10, 10],
        "animation": {"variable": "boundary", "from": -8, "to": 8, "duration": 2, "keyframes": []},
        "tracks": [{"id": "main", "label": "解集"}],
        "points": [
            {
                "id": "boundary-point",
                "track": "main",
                "label": "边界",
                "color": "#0F766E",
                "value": {"state": "boundary"},
                "endpoint": "closed",
            }
        ],
        "intervals": [],
        "rays": [
            {
                "id": "ray",
                "track": "main",
                "label": "解集射线",
                "color": "#0F766E",
                "boundary": {"state": "boundary"},
                "direction": "right",
                "endpoint": "closed",
            }
        ],
        "distances": [],
        "movements": [],
        "derived_sets": [],
        "invariants": [{"id": "point-on-line", "type": "point_on_number_line", "refs": ["boundary-point"]}],
    }
    business_html = assemble_number_line_business_html(ir, plan, "数轴不等式射线")
    html_path = tmp_path / "number-line-runtime.html"
    html_path.write_text(assemble_layout_contract(business_html, plan), encoding="utf-8")

    report = evaluate_playback_progress(html_path, wait_ms=350)

    assert report["passed"], report
