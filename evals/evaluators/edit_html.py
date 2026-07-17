"""One-metric, local-only evaluators for Edit HTML diagnosis and delivery."""

from __future__ import annotations

from typing import Any

from bs4 import BeautifulSoup

from aetherviz_service.aetherviz.contracts.validation.report import build_validation_report
from aetherviz_service.aetherviz.edit.intent import IntentCheck, evaluate_edit_intent
from aetherviz_service.aetherviz.tools.function_patch import extract_named_functions


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _outputs(run: Any) -> dict[str, Any]:
    return _mapping(run.outputs if hasattr(run, "outputs") else _mapping(run).get("outputs"))


def _expected(example: Any) -> dict[str, Any]:
    return _mapping(example.outputs if hasattr(example, "outputs") else _mapping(example).get("outputs"))


def _checks(values: Any, group: str) -> tuple[IntentCheck, ...]:
    if not isinstance(values, list):
        return ()
    return tuple(
        IntentCheck(
            id=str(item.get("id") or f"{group}_{index}"),
            kind=str(item.get("kind") or ""),
            selector=str(item.get("selector") or ""),
            function=str(item.get("function") or ""),
            property=str(item.get("property") or ""),
            expected=str(item.get("expected") or ""),
            baseline_binding=str(item.get("baseline_binding") or "absolute"),  # type: ignore[arg-type]
            severity=str(item.get("severity") or "hard"),  # type: ignore[arg-type]
            rationale=str(item.get("rationale") or ""),
            group=group,  # type: ignore[arg-type]
        )
        for index, item in enumerate(values)
        if isinstance(item, dict) and item.get("kind")
    )


def diagnosis_strategy_evaluator(run: Any, example: Any) -> dict[str, Any]:
    actual = str(_outputs(run).get("diagnosis", {}).get("strategy") or "")
    expected = str(_expected(example).get("strategy") or "full_html_regeneration")
    passed = actual == expected
    return {"score": int(passed), "comment": f"expected={expected}; actual={actual}"}


def diagnosis_impact_coverage_evaluator(run: Any, example: Any) -> dict[str, Any]:
    actual = set(_outputs(run).get("diagnosis", {}).get("impact_areas") or [])
    required = set(_expected(example).get("required_impact_areas") or [])
    missing = sorted(required - actual)
    return {"score": int(not missing), "comment": f"missing={missing}"}


def diagnosis_hard_change_coverage_evaluator(run: Any, example: Any) -> dict[str, Any]:
    checks = _outputs(run).get("diagnosis", {}).get("change_checks") or []
    hard_kinds = {str(item.get("kind")) for item in checks if isinstance(item, dict) and item.get("severity") == "hard"}
    required = set(_expected(example).get("required_hard_change_kinds") or [])
    missing = sorted(required - hard_kinds)
    return {"score": int(not missing), "comment": f"missing={missing}; hard={sorted(hard_kinds)}"}


def diagnosis_claim_bindability_evaluator(run: Any, example: Any) -> dict[str, Any]:
    output = _outputs(run)
    diagnosis = _mapping(output.get("diagnosis"))
    html = str(output.get("baseline_html") or "")
    soup = BeautifulSoup(html, "html.parser")
    functions = extract_named_functions(html)
    unbound: list[str] = []
    selector_kinds = {
        "text_contains",
        "text_absent",
        "text_changed",
        "text_unchanged",
        "attribute_equals",
        "attribute_changed",
        "attribute_unchanged",
        "css_declaration",
        "css_changed",
        "css_unchanged",
    }
    function_kinds = {"function_body_changed", "function_body_unchanged"}
    for item in [*(diagnosis.get("change_checks") or []), *(diagnosis.get("preserve_checks") or [])]:
        if not isinstance(item, dict) or item.get("severity") != "hard":
            continue
        check_id = str(item.get("id") or item.get("kind") or "unknown")
        kind = str(item.get("kind") or "")
        if kind in selector_kinds:
            selector = str(item.get("selector") or "")
            try:
                bound = bool(selector and soup.select(selector))
            except Exception:
                bound = False
            if not bound:
                unbound.append(check_id)
        elif kind in function_kinds:
            if len(functions.get(str(item.get("function") or ""), [])) != 1:
                unbound.append(check_id)
    return {"score": int(not unbound), "comment": f"unbound={unbound}"}


def change_intent_satisfaction_evaluator(run: Any, example: Any) -> dict[str, Any]:
    output = _outputs(run)
    result = evaluate_edit_intent(
        baseline_html=str(output.get("baseline_html") or ""),
        candidate_html=str(output.get("candidate_html") or ""),
        change_checks=_checks(_expected(example).get("change_checks"), "change"),
        preserve_checks=(),
    )
    return {"score": int(result.ok), "comment": result.summary}


def preserve_satisfaction_evaluator(run: Any, example: Any) -> dict[str, Any]:
    output = _outputs(run)
    result = evaluate_edit_intent(
        baseline_html=str(output.get("baseline_html") or ""),
        candidate_html=str(output.get("candidate_html") or ""),
        change_checks=(),
        preserve_checks=_checks(_expected(example).get("preserve_checks"), "preserve"),
    )
    return {"score": int(result.ok), "comment": result.summary}


def html_validation_evaluator(run: Any, example: Any) -> dict[str, Any]:
    output = _outputs(run)
    report = _mapping(output.get("validation"))
    if not report:
        report = build_validation_report(str(output.get("candidate_html") or ""))
    passed = bool(report.get("ok"))
    return {"score": int(passed), "comment": str(report.get("summary") or "validation_missing")}


def browser_runtime_evaluator(run: Any, example: Any) -> dict[str, Any]:
    browser = _mapping(_outputs(run).get("browser"))
    passed = bool(browser.get("passed"))
    return {"score": int(passed), "comment": "browser_ok" if passed else "browser_failed_or_skipped"}


def post_repair_intent_evaluator(run: Any, example: Any) -> dict[str, Any]:
    output = _outputs(run)
    metadata = _mapping(output.get("metadata"))
    passed = metadata.get("intent_passed") is True and int(metadata.get("intent_check_count") or 0) > 0
    return {
        "score": int(passed),
        "comment": f"intent_passed={metadata.get('intent_passed')}; checks={metadata.get('intent_check_count')}",
    }


def teaching_semantics_judge_evaluator(run: Any, example: Any) -> dict[str, Any]:
    return _judge_metric(run, "teaching_semantics")


def visual_quality_judge_evaluator(run: Any, example: Any) -> dict[str, Any]:
    return _judge_metric(run, "visual_quality")


def edit_relevance_judge_evaluator(run: Any, example: Any) -> dict[str, Any]:
    return _judge_metric(run, "edit_relevance")


def _judge_metric(run: Any, name: str) -> dict[str, Any]:
    grade = _mapping(_outputs(run).get("judge"))
    score = grade.get(name)
    passed = isinstance(score, (int, float)) and float(score) >= 0.8
    return {"score": int(passed), "comment": f"{name}={score}; {grade.get('reasoning', '')}"}
