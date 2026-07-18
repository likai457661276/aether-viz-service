from __future__ import annotations

from copy import deepcopy

from aetherviz_service.aetherviz.contracts.validation.js_checker import check_inline_javascript
from aetherviz_service.aetherviz.ir.registry import DEFAULT_IR_REGISTRY
from aetherviz_service.aetherviz.ir.router.service import resolve_generation_route
from aetherviz_service.aetherviz.ir.symbolic_derivation.contract import (
    SYMBOLIC_DERIVATION_IR_VERSION,
    compile_symbolic_derivation_ir,
    rank_symbolic_derivation_ir_candidates,
    validate_symbolic_derivation_ir,
)
from aetherviz_service.aetherviz.ir.symbolic_derivation.runtime import assemble_symbolic_derivation_business_html
from aetherviz_service.aetherviz.workflow.plan_contract import normalize_plan


def _plan() -> dict:
    return normalize_plan(
        {
            "interactive_type": "simulation",
            "interactive_spec": {
                "type": "simulation",
                "concept": "因式分解推导",
                "description": "逐步展开并验证多项式恒等变形",
                "variables": [{"name": "step", "label": "步骤", "min": 0, "max": 1, "step": 0.1, "default": 0}],
                "presets": [],
                "observations": ["每一步保持等价"],
            },
            "knowledge_profile": {
                "subject": "math",
                "concept_family": "algebra",
                "representation_type": "symbolic_derivation",
                "pedagogy_pattern": "worked_example",
            },
            "representation_spec": {
                "views": [{"id": "proof", "kind": "symbolic_panel", "role": "推导步骤"}],
                "state_variables": [{"id": "step", "semantic_type": "progress"}],
                "correspondences": [],
                "required_invariants": ["equal_value"],
                "interaction_requirements": ["scrub", "play", "pause", "reset"],
            },
        },
        "逐步验证多项式恒等变形",
    )


def _sym(name: str) -> dict:
    return {"symbol": name}


def _rel(left: object, right: object = 0) -> dict:
    return {"left": left, "right": right}


def _ir() -> dict:
    x = _sym("x")
    factored = {"op": "mul", "args": [x, {"op": "add", "args": [x, 2]}]}
    expanded = {"op": "add", "args": [{"op": "pow", "args": [x, 2]}, {"op": "mul", "args": [2, x]}]}
    reordered = {"op": "add", "args": [{"op": "mul", "args": [x, 2]}, {"op": "pow", "args": [x, 2]}]}
    return {
        "version": SYMBOLIC_DERIVATION_IR_VERSION,
        "mode": "expression",
        "variables": ["x"],
        "steps": [
            {
                "id": "expand",
                "before": _rel(factored),
                "after": _rel(expanded),
                "rule": "expand",
                "explanation": "使用分配律展开。",
            },
            {
                "id": "commute",
                "before": _rel(expanded),
                "after": _rel(reordered),
                "rule": "commute",
                "explanation": "交换加法项顺序。",
            },
        ],
        "observation": "每一步的规范多项式保持相同。",
    }


def test_symbolic_derivation_validates_exact_equivalence_and_runtime() -> None:
    plan, ir = _plan(), _ir()
    assert validate_symbolic_derivation_ir(ir, plan)["ok"]
    assert SYMBOLIC_DERIVATION_IR_VERSION in compile_symbolic_derivation_ir(ir, plan)
    business_html = assemble_symbolic_derivation_business_html(ir, plan, "因式分解")
    assert 'id="symbolic-derivation-ir"' in business_html
    assert "window.AetherVizAnimationController.create" in business_html
    assert "requestAnimationFrame" not in business_html
    assert check_inline_javascript(business_html)["ok"]


def test_symbolic_derivation_rejects_non_equivalent_or_disconnected_steps() -> None:
    invalid = deepcopy(_ir())
    invalid["steps"][0]["after"] = _rel({"op": "add", "args": [_sym("x"), 1]})
    report = validate_symbolic_derivation_ir(invalid, _plan())
    assert any(item["type"] == "non_equivalent_derivation_step" for item in report["errors"])
    assert any(item["type"] == "disconnected_derivation_steps" for item in report["errors"])


def test_symbolic_derivation_candidate_ranking_and_routing() -> None:
    invalid = deepcopy(_ir())
    invalid["steps"][0]["rule"] = "invent_rule"
    assert rank_symbolic_derivation_ir_candidates([invalid, _ir()], _plan())["ok"]
    assert resolve_generation_route(_plan()).selected_backend == "symbolic_derivation_scene"
    backend = DEFAULT_IR_REGISTRY.get("symbolic_derivation_scene")
    assert backend is not None and backend.assess is not None and backend.assess(_plan()).eligible
