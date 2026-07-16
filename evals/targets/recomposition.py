#!/usr/bin/env python3
"""Evaluation target for geometric recomposition generation."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from aetherviz_service.aetherviz.ir.recomposition.agent import (
    GeometryIRGenerationError,
    _attempt_target_bounds_completion,
    _generate_ranked_scene_source,
    _repair_scene_source,
)
from aetherviz_service.aetherviz.ir.recomposition.assembly import evaluate_target_assembly
from aetherviz_service.aetherviz.ir.recomposition.contract import (
    compile_geometry_ir,
    expand_geometry_ir,
    extract_geometry_ir_from_scene_source,
    sample_geometry_states,
    validate_geometry_ir,
)
from aetherviz_service.aetherviz.ir.recomposition.ranking import (
    public_geometry_ir_ranking,
    rank_geometry_ir_candidates,
)
from aetherviz_service.aetherviz.ir.recomposition.runtime import (
    assemble_recomposition_business_html,
    build_deterministic_scene_module,
)
from aetherviz_service.aetherviz.ir.recomposition.scene_contract import validate_scene_module
from aetherviz_service.aetherviz.ir.recomposition.semantics import (
    evaluate_recomposition_semantics,
)
from aetherviz_service.aetherviz.tools.layout_contract import assemble_layout_contract
from aetherviz_service.aetherviz.tools.validation_report import build_validation_report
from aetherviz_service.aetherviz.workflow.plan_contract import normalize_plan


def load_examples(path: Path) -> list[dict[str, Any]]:
    examples = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    for example in examples:
        if not isinstance(example.get("inputs"), dict) or not isinstance(example.get("outputs"), dict):
            raise ValueError("每个样本必须包含 inputs 和 outputs 对象")
    return examples


def load_completion_cases(path: Path) -> list[dict[str, Any]]:
    cases = [json.loads(case_path.read_text(encoding="utf-8")) for case_path in sorted(path.glob("*.json"))]
    for case in cases:
        if not isinstance(case.get("inputs"), dict) or not isinstance(case.get("outputs"), dict):
            raise ValueError("每个 completion 样本必须包含 inputs 和 outputs 对象")
    return cases


def run_completion_case(example: dict[str, Any]) -> dict[str, Any]:
    """Run one controlled candidate through the target-bounds completion branch."""
    inputs = example["inputs"]
    topic = str(inputs["topic"])
    plan = normalize_plan(deepcopy(inputs["plan_seed"]), topic)
    candidate = deepcopy(inputs["geometry_ir"])
    _apply_completion_mutation(candidate, inputs.get("mutation", {}))
    initial_ranking = rank_geometry_ir_candidates([candidate], plan)
    assembly_before = evaluate_target_assembly(candidate, plan)
    repaired_ranking, repaired_candidates = _attempt_target_bounds_completion(
        [candidate], plan, initial_ranking
    )
    selected_ir = repaired_ranking.get("selected_ir")
    if not isinstance(selected_ir, dict) and repaired_candidates:
        selected_ir = repaired_candidates[0]
    assembly_after = (
        evaluate_target_assembly(selected_ir, plan) if isinstance(selected_ir, dict) else {"ok": False}
    )
    scene_report: dict[str, Any] = {"ok": False, "errors": [{"type": "missing_selected_ir"}]}
    if isinstance(selected_ir, dict):
        geometry_report = validate_geometry_ir(selected_ir, plan)
        scene_report = (
            validate_scene_module(compile_geometry_ir(selected_ir, plan))
            if geometry_report["ok"]
            else geometry_report
        )
    candidate_reports = initial_ranking.get("candidates", [])
    initial_hard_failures = (
        candidate_reports[0].get("hard_failures", [])
        if candidate_reports and isinstance(candidate_reports[0], dict)
        else []
    )
    return {
        "initial_hard_failures": initial_hard_failures,
        "strategy": repaired_ranking.get("strategy"),
        "completion_reports": repaired_ranking.get("target_bounds_completion", []),
        "final_ranking_ok": repaired_ranking.get("ok"),
        "assembly_before": assembly_before,
        "assembly_after": assembly_after,
        "final_assembly_ok": assembly_after.get("ok"),
        "scene_report": scene_report,
    }


def _apply_completion_mutation(ir: dict[str, Any], mutation: object) -> None:
    if not isinstance(mutation, dict) or mutation.get("type") != "translate_target":
        raise ValueError("unsupported_completion_mutation")
    dx = float(mutation.get("x", 0))
    dy = float(mutation.get("y", 0))
    for piece in ir.get("pieces", []):
        if not isinstance(piece, dict):
            continue
        _translate_transform_expression(piece.get("target"), dx, dy)
        keyframes = piece.get("keyframes", [])
        if isinstance(keyframes, list):
            target_frame = next(
                (
                    frame
                    for frame in reversed(keyframes)
                    if isinstance(frame, dict) and float(frame.get("at", -1)) == 1.0
                ),
                None,
            )
            _translate_transform_expression(target_frame, dx, dy)


def _translate_transform_expression(transform: object, dx: float, dy: float) -> None:
    if not isinstance(transform, dict):
        return
    if dx:
        transform["x"] = {"op": "add", "args": [transform.get("x", 0), dx]}
    if dy:
        transform["y"] = {"op": "add", "args": [transform.get("y", 0), dy]}


def run_case(example: dict[str, Any], *, live_model: bool, browser: bool) -> dict[str, Any]:
    topic = str(example["inputs"]["topic"])
    plan = normalize_plan(build_evaluation_plan_seed(example), topic)
    degraded = False
    repaired = False
    fallback = False
    generation_error = ""
    repair_error = ""
    repair_input = ""
    initial_ir_report: dict[str, Any] = {
        "ok": False,
        "errors": [{"type": "geometry_ir_not_generated"}],
    }
    ranking_report: dict[str, Any] = {"ok": False, "candidates": [], "ranking": []}
    if live_model:
        try:
            scene_source, degraded, private_ranking = _generate_ranked_scene_source(topic, plan)
            ranking_report = public_geometry_ir_ranking(private_ranking)
            initial_ir_report = validate_geometry_ir(
                extract_geometry_ir_from_scene_source(scene_source),
                plan,
            )
        except GeometryIRGenerationError as exc:
            scene_source = ""
            repair_input = exc.raw_text
            initial_ir_report = exc.report
            ranking_report = exc.report.get("ranking", ranking_report)
            degraded = True
            generation_error = str(exc)
        except Exception as exc:
            scene_source = ""
            degraded = True
            generation_error = str(exc)
    else:
        scene_source = build_deterministic_scene_module(plan)
        initial_ir_report = validate_geometry_ir(
            extract_geometry_ir_from_scene_source(scene_source),
            plan,
        )
    initial_scene_report = validate_scene_module(scene_source)
    scene_report = initial_scene_report
    if live_model and not scene_report["ok"] and (scene_source or repair_input):
        try:
            repaired_source = _repair_scene_source(
                topic,
                plan,
                repair_input or scene_source,
                initial_ir_report if repair_input else scene_report,
            )
            repaired_report = validate_scene_module(repaired_source)
            if repaired_report["ok"]:
                scene_source = repaired_source
                scene_report = repaired_report
                repaired = True
                degraded = True
        except Exception as exc:
            repair_error = str(exc)
    if live_model and not scene_report["ok"]:
        scene_source = build_deterministic_scene_module(plan)
        scene_report = validate_scene_module(scene_source)
        fallback = True
        degraded = True
    business_html = ""
    assembled_html = ""
    html_report: dict[str, Any] = {"ok": False, "errors": [{"type": "scene_module_invalid"}]}
    browser_report: dict[str, Any] = {"skipped": True}
    semantic_report: dict[str, Any] = {"ok": False, "errors": [{"type": "scene_module_invalid"}]}
    if scene_report["ok"]:
        geometry_ir = extract_geometry_ir_from_scene_source(scene_source)
        semantic_report = evaluate_recomposition_semantics(geometry_ir, plan)
        geometry_ir_facts = _geometry_ir_facts(geometry_ir, plan)
        business_html = assemble_recomposition_business_html(scene_source, plan, topic)
        assembled_html = assemble_layout_contract(business_html, plan)
        html_report = build_validation_report(assembled_html, plan=plan, model_html=business_html)
        if browser and html_report["ok"]:
            browser_report = _evaluate_browser(assembled_html)
    else:
        geometry_ir_facts = {"piece_counts": [], "stage_count": 0, "tags": [], "transforms": []}
    return {
        "topic": topic,
        "split": example.get("metadata", {}).get("split"),
        "profile": plan.get("knowledge_profile", {}),
        "recomposition_spec": plan.get("recomposition_spec", {}),
        "scene_report": scene_report,
        "initial_scene_report": initial_scene_report,
        "initial_geometry_ir_report": initial_ir_report,
        "candidate_ranking_report": ranking_report,
        "html_report": html_report,
        "browser_report": browser_report,
        "semantic_report": semantic_report,
        "geometry_ir_facts": geometry_ir_facts,
        "scene_chars": len(scene_source),
        "business_chars": len(business_html),
        "assembled_chars": len(assembled_html),
        "degraded": degraded,
        "repaired": repaired,
        "fallback": fallback,
        "generation_error": generation_error,
        "repair_error": repair_error,
    }


def build_evaluation_plan_seed(example: dict[str, Any]) -> dict[str, Any]:
    dimensions = example.get("metadata", {}).get("dimensions", {})
    constraints = example.get("outputs", {}).get("expected_constraints", {})
    if not isinstance(constraints, dict):
        constraints = {}
    variables: list[dict[str, Any]] = []
    topology: list[str] = []
    piece_bucket = str(constraints.get("piece_count") or "")
    if piece_bucket:
        piece_ranges = {
            "1": (1, 1, 1),
            "2": (2, 2, 2),
            "3": (3, 3, 3),
            "4+": (4, 16, 8),
        }
        minimum, maximum, default = piece_ranges.get(piece_bucket, (3, 20, 6))
        variables.append(
            {
                "name": "pieceCount",
                "label": "分块数量",
                "min": minimum,
                "max": maximum,
                "default": default,
                "step": 1,
            }
        )
        topology.append("pieceCount")
    elif dimensions.get("dynamic_piece_count"):
        variables.append(
            {"name": "pieceCount", "label": "分块数量", "min": 4, "max": 24, "default": 8, "step": 2}
        )
        topology.append("pieceCount")
    parameter_form = str(constraints.get("parameter_form") or "variable")
    parameter_ranges = {
        "fixed": (4, 4, 4, 1),
        "variable": (1, 8, 4, 0.5),
        "boundary": (0.25, 12, 4, 0.25),
    }
    scale_min, scale_max, scale_default, scale_step = parameter_ranges.get(
        parameter_form, parameter_ranges["variable"]
    )
    variables.append(
        {
            "name": "scale",
            "label": "几何尺度",
            "min": scale_min,
            "max": scale_max,
            "default": scale_default,
            "step": scale_step,
        }
    )
    stage_count = int(constraints.get("stage_count") or 3)
    transform = str(constraints.get("primary_transform") or "translation")
    transform_labels = {
        "translation": "平移并对齐图元",
        "rotation": "旋转并对齐图元",
        "reflection": "翻转并对齐图元",
        "combined": "依次平移、旋转并翻转图元",
    }
    stage_requirements = [{"id": "source", "intent": "展示源图元集合"}]
    for index in range(1, max(2, min(5, stage_count)) - 1):
        stage_requirements.append(
            {
                "id": f"transform-{index}",
                "intent": f"第 {index} 个中间阶段：{transform_labels.get(transform, '重排图元')}",
                "min_piece_ratio": 0.5,
            }
        )
    stage_requirements.append({"id": "target", "intent": "展示目标图元集合并归纳关系"})
    math_relation = str(constraints.get("math_relation") or "area")
    measure_invariants = {
        "area": ["area_preserved", "piece_congruence"],
        "length": ["length_preserved"],
        "angle": ["angle_preserved"],
        "congruence": ["piece_congruence"],
    }.get(math_relation, ["area_preserved", "piece_congruence"])
    return {
        "interactive_spec": {"variables": variables},
        "recomposition_spec": {
            "topology_variables": topology,
            "geometry_variables": ["scale"],
            "proof_constraints": {
                "measure_invariants": measure_invariants,
                "stage_requirements": stage_requirements,
            },
        },
    }


def _geometry_ir_facts(ir: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    piece_counts: list[int] = []
    tags: set[str] = set()
    transforms: set[str] = set()
    for _, state in sample_geometry_states(plan):
        pieces = expand_geometry_ir(ir, state)
        piece_counts.append(len(pieces))
        for piece in pieces:
            tags.add(str(piece.get("tag") or ""))
            source = piece.get("source", {})
            target = piece.get("target", {})
            if abs(float(target.get("x", 0)) - float(source.get("x", 0))) > 1e-6 or abs(
                float(target.get("y", 0)) - float(source.get("y", 0))
            ) > 1e-6:
                transforms.add("translation")
            if abs(float(target.get("rotation", 0)) - float(source.get("rotation", 0))) > 1e-6:
                transforms.add("rotation")
            if float(target.get("scale", 1)) * float(source.get("scale", 1)) < 0:
                transforms.add("reflection")
    return {
        "piece_counts": piece_counts,
        "stage_count": len(ir.get("frames", [])),
        "tags": sorted(tags),
        "transforms": sorted(transforms),
    }


def _evaluate_browser(html_text: str) -> dict[str, Any]:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        page_errors: list[str] = []
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.route("**/*", lambda route: route.abort() if route.request.url.startswith("http") else route.continue_())
        page.set_content(html_text, wait_until="load")
        try:
            page.wait_for_function(
                "() => Boolean(window.AetherVizRuntime || window.__AETHERVIZ_RUNTIME_ERROR__)",
                timeout=2_000,
            )
        except Exception:
            pass
        runtime_present = page.evaluate("() => Boolean(window.AetherVizRuntime)")
        if not runtime_present:
            snapshot = page.evaluate(
                "() => ({runtime_ready:false,runtime_error:String(window.__AETHERVIZ_RUNTIME_ERROR__||'')})"
            )
            browser.close()
            return {"ok": False, "page_errors": page_errors, **snapshot}
        initial_visual = page.evaluate(
            "() => [...document.querySelectorAll('[data-piece-id]')].map((node)=>[node.getAttribute('transform'),node.getAttribute('opacity'),node.getAttribute('fill'),node.getAttribute('stroke')].join(':')).join('|')"
        )
        page.evaluate("() => window.AetherVizRuntime.play()")
        page.wait_for_timeout(120)
        page.evaluate("() => window.AetherVizRuntime.pause()")
        animated_visual = page.evaluate(
            "() => [...document.querySelectorAll('[data-piece-id]')].map((node)=>[node.getAttribute('transform'),node.getAttribute('opacity'),node.getAttribute('fill'),node.getAttribute('stroke')].join(':')).join('|')"
        )
        snapshot = page.evaluate(
            """() => {
              const runtime=window.AetherVizRuntime;
              const initial=runtime.getState();
              runtime.update({progress:.5});
              const middle=runtime.getState();
              const inputs=[...document.querySelectorAll('[data-var]')];
              for(const input of inputs){input.value=input.max;input.dispatchEvent(new Event('input',{bubbles:true}));input.value=input.min;input.dispatchEvent(new Event('input',{bubbles:true}));}
              const afterBoundaries=runtime.getState();
              const topologyInput=inputs.find((input)=>input.getAttribute('data-var')==='pieceCount');
              if(topologyInput){for(let index=0;index<2;index+=1){topologyInput.value=topologyInput.max;topologyInput.dispatchEvent(new Event('input',{bubbles:true}));topologyInput.value=topologyInput.min;topologyInput.dispatchEvent(new Event('input',{bubbles:true}));}}
              runtime.reset();
              const reset=runtime.getState();
              const attrs=[...document.querySelectorAll('[data-piece-id]')].flatMap((node)=>
                [...node.attributes].map((attr)=>attr.value));
              return {
                runtime_ready:window.__AETHERVIZ_RUNTIME_READY__===true,
                runtime_error:String(window.__AETHERVIZ_RUNTIME_ERROR__||''),
                initial,middle,afterBoundaries,reset,
                piece_ids:[...document.querySelectorAll('[data-piece-id]')].map((node)=>node.getAttribute('data-piece-id')),
                finite_attrs:!attrs.some((value)=>/NaN|Infinity/.test(value))
              };
            }"""
        )
        browser.close()
    ids = snapshot.get("piece_ids", [])
    ok = (
        snapshot.get("runtime_ready")
        and not snapshot.get("runtime_error")
        and not page_errors
        and snapshot.get("finite_attrs")
        and len(ids) == len(set(ids)) > 0
        and initial_visual != animated_visual
        and snapshot.get("middle", {}).get("progress") == 0.5
        and snapshot.get("reset", {}).get("progress") == 0
        and snapshot.get("reset", {}).get("pieceCount") == snapshot.get("initial", {}).get("pieceCount")
    )
    return {
        "ok": bool(ok),
        "page_errors": page_errors,
        "animation_visible_change": initial_visual != animated_visual,
        **snapshot,
    }
