from __future__ import annotations

from copy import deepcopy

from aetherviz_service.aetherviz.contracts.validation.js_checker import check_inline_javascript
from aetherviz_service.aetherviz.ir.probability_experiment.contract import (
    PROBABILITY_EXPERIMENT_IR_VERSION,
    compile_probability_experiment_ir,
    event_probabilities,
    rank_probability_experiment_ir_candidates,
    validate_probability_experiment_ir,
)
from aetherviz_service.aetherviz.ir.probability_experiment.runtime import assemble_probability_experiment_business_html
from aetherviz_service.aetherviz.ir.registry import DEFAULT_IR_REGISTRY
from aetherviz_service.aetherviz.ir.router.service import resolve_generation_route
from aetherviz_service.aetherviz.workflow.plan_contract import normalize_plan


def _plan() -> dict:
    return normalize_plan(
        {
            "interactive_type": "simulation",
            "interactive_spec": {
                "type": "simulation",
                "concept": "重复抛硬币随机试验",
                "description": "累计正面频率并与理论概率比较",
                "variables": [{"name": "trials", "label": "试验次数", "min": 1, "max": 200, "step": 1, "default": 20}],
                "presets": [],
                "observations": ["频率逐步接近理论概率"],
            },
            "knowledge_profile": {
                "subject": "math",
                "concept_family": "probability_statistics",
                "representation_type": "probability_experiment",
                "pedagogy_pattern": "parameter_exploration",
            },
            "representation_spec": {
                "views": [
                    {"id": "trial", "kind": "probability_experiment", "role": "随机试验"},
                    {"id": "chart", "kind": "data_chart", "role": "累计频率"},
                ],
                "state_variables": [{"id": "trials", "semantic_type": "count"}],
                "correspondences": [
                    {"type": "derived_value", "source_view": "trial", "target_view": "chart", "parameter": "trials"}
                ],
                "required_invariants": ["probability_mass"],
                "interaction_requirements": ["scrub", "play", "pause", "reset"],
            },
        },
        "重复抛硬币并观察频率收敛",
    )


def _ir() -> dict:
    return {
        "version": PROBABILITY_EXPERIMENT_IR_VERSION,
        "animation": {"variable": "trials", "from": 1, "to": 200, "default": 20, "duration": 7},
        "seed": 20260718,
        "outcomes": [
            {"id": "head", "label": "正面", "weight": 1, "path": ["抛硬币", "正面"]},
            {"id": "tail", "label": "反面", "weight": 1, "path": ["抛硬币", "反面"]},
        ],
        "events": [{"id": "is_head", "label": "出现正面", "outcomes": ["head"]}],
        "views": [
            {"id": "space", "type": "sample_space", "title": "样本空间"},
            {"id": "frequency", "type": "frequency_chart", "title": "累计频率", "event": "is_head"},
            {"id": "tree", "type": "probability_tree", "title": "概率树"},
        ],
        "observation": "试验序列可复现，累计频率随次数增加而变化。",
    }


def test_probability_experiment_validates_derives_and_uses_seeded_runtime() -> None:
    plan, ir = _plan(), _ir()
    assert validate_probability_experiment_ir(ir, plan)["ok"]
    assert event_probabilities(ir) == {"is_head": 0.5}
    compiled = compile_probability_experiment_ir(ir, plan)
    assert '"event_probabilities":{"is_head":0.5}' in compiled
    business_html = assemble_probability_experiment_business_html(ir, plan, "抛硬币")
    assert 'id="probability-experiment-ir"' in business_html
    assert "function rng(seed)" in business_html
    assert "requestAnimationFrame" not in business_html
    assert check_inline_javascript(business_html)["ok"]


def test_probability_experiment_rejects_invalid_events_and_weights() -> None:
    invalid = deepcopy(_ir())
    invalid["outcomes"][0]["weight"] = 0
    invalid["events"][0]["outcomes"] = ["missing"]
    report = validate_probability_experiment_ir(invalid, _plan())
    assert any(item["type"] == "invalid_outcome_weight" for item in report["errors"])
    assert any(item["type"] == "invalid_event_outcomes" for item in report["errors"])


def test_probability_experiment_candidate_ranking_routing_and_continuous_exclusion() -> None:
    invalid = deepcopy(_ir())
    invalid["seed"] = 0
    assert rank_probability_experiment_ir_candidates([invalid, _ir()], _plan())["ok"]
    assert resolve_generation_route(_plan()).selected_backend == "probability_experiment_scene"
    backend = DEFAULT_IR_REGISTRY.get("probability_experiment_scene")
    assert backend is not None and backend.assess is not None
    continuous = deepcopy(_plan())
    continuous["interactive_spec"]["description"] = "观察正态分布概率密度曲线下面积"
    assert not backend.assess(continuous).eligible
