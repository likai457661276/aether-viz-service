from __future__ import annotations

from copy import deepcopy

from aetherviz_service.aetherviz.contracts.validation.js_checker import check_inline_javascript
from aetherviz_service.aetherviz.ir.discrete_structure.contract import (
    DISCRETE_STRUCTURE_IR_VERSION,
    compile_discrete_structure_ir,
    rank_discrete_structure_ir_candidates,
    validate_discrete_structure_ir,
)
from aetherviz_service.aetherviz.ir.discrete_structure.runtime import assemble_discrete_structure_business_html
from aetherviz_service.aetherviz.ir.registry import DEFAULT_IR_REGISTRY
from aetherviz_service.aetherviz.ir.router.service import resolve_generation_route
from aetherviz_service.aetherviz.workflow.plan_contract import normalize_plan


def _plan() -> dict:
    return normalize_plan(
        {
            "interactive_type": "simulation",
            "interactive_spec": {
                "type": "simulation",
                "concept": "树、集合与递推序列",
                "description": "保持节点身份，分阶段观察树拓扑、集合成员和递推序列",
                "variables": [{"name": "stage", "label": "阶段", "min": 0, "max": 4, "step": 1, "default": 0}],
                "presets": [],
                "observations": ["节点身份在视图切换时保持不变"],
            },
            "knowledge_profile": {
                "subject": "math",
                "concept_family": "discrete_math",
                "representation_type": "discrete_structure",
                "pedagogy_pattern": "structure_exploration",
            },
            "representation_spec": {
                "views": [
                    {"id": "tree", "kind": "tree", "role": "树结构"},
                    {"id": "set", "kind": "set_diagram", "role": "集合成员"},
                    {"id": "sequence", "kind": "sequence", "role": "递推序列"},
                ],
                "state_variables": [{"id": "stage", "semantic_type": "discrete"}],
                "correspondences": [
                    {"type": "transform", "source_view": "tree", "target_view": "set", "parameter": "stage"}
                ],
                "required_invariants": ["stable_identity"],
                "interaction_requirements": ["scrub", "play", "pause", "reset"],
            },
        },
        "观察离散结构的拓扑与顺序",
    )


def _ir() -> dict:
    return {
        "version": DISCRETE_STRUCTURE_IR_VERSION,
        "animation": {"variable": "stage", "from": 0, "to": 4, "default": 0, "duration": 6},
        "nodes": [
            {"id": "root", "label": "根", "order": 0},
            {"id": "left", "label": "左", "order": 1, "group": "leaf"},
            {"id": "right", "label": "右", "order": 2, "group": "leaf", "visible_from": 0.25},
        ],
        "edges": [
            {"id": "e1", "source": "root", "target": "left", "directed": True, "label": ""},
            {"id": "e2", "source": "root", "target": "right", "directed": True, "label": "", "visible_from": 0.25},
        ],
        "sets": [{"id": "leaves", "label": "叶节点", "members": ["left", "right"]}],
        "sequences": [
            {
                "id": "fib",
                "label": "递推序列",
                "terms": [1, 1, 2, 3, 5, 8],
                "recurrence": "从第三项起，每项等于前两项之和。",
            }
        ],
        "views": [
            {"id": "tree", "type": "tree", "title": "有根树", "root": "root"},
            {"id": "set", "type": "set", "title": "叶节点集合", "ref": "leaves"},
            {"id": "sequence", "type": "sequence", "title": "递推序列", "ref": "fib"},
            {"id": "permutation", "type": "permutation", "title": "节点排列"},
        ],
        "observation": "节点 id 不随阶段和视图切换而改变。",
    }


def test_discrete_structure_validates_topology_and_runtime() -> None:
    plan, ir = _plan(), _ir()
    assert validate_discrete_structure_ir(ir, plan)["ok"]
    assert DISCRETE_STRUCTURE_IR_VERSION in compile_discrete_structure_ir(ir, plan)
    business_html = assemble_discrete_structure_business_html(ir, plan, "离散结构")
    assert 'id="discrete-structure-ir"' in business_html
    assert "visibleNodeIds" in business_html
    assert "requestAnimationFrame" not in business_html
    assert check_inline_javascript(business_html)["ok"]


def test_discrete_structure_rejects_cycles_unknown_members_and_visibility() -> None:
    invalid = deepcopy(_ir())
    invalid["edges"].append({"id": "e3", "source": "left", "target": "root", "directed": True, "label": ""})
    invalid["sets"][0]["members"].append("missing")
    invalid["nodes"][0]["visible_from"] = 0.9
    invalid["nodes"][0]["visible_to"] = 0.1
    report = validate_discrete_structure_ir(invalid, _plan())
    assert any(item["type"] == "invalid_tree_topology" for item in report["errors"])
    assert any(item["type"] == "invalid_set_members" for item in report["errors"])
    assert any(item["type"] == "invalid_discrete_visibility" for item in report["errors"])


def test_discrete_structure_candidate_ranking_and_routing() -> None:
    invalid = deepcopy(_ir())
    invalid["nodes"][1]["order"] = 0
    assert rank_discrete_structure_ir_candidates([invalid, _ir()], _plan())["ok"]
    assert resolve_generation_route(_plan()).selected_backend == "discrete_structure_scene"
    backend = DEFAULT_IR_REGISTRY.get("discrete_structure_scene")
    assert backend is not None and backend.assess is not None and backend.assess(_plan()).eligible
