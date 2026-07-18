"""Deterministic edit intent satisfaction checks against structured diagnosis claims."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

import tinycss2
from bs4 import BeautifulSoup

from aetherviz_service.aetherviz.contracts.html_compare import normalize_html_for_compare
from aetherviz_service.aetherviz.contracts.validation.dom_api_contract import (
    find_dom_element_selector_mismatches,
)
from aetherviz_service.aetherviz.tools.function_patch import extract_named_functions

IntentSeverity = Literal["hard", "soft"]
BaselineBinding = Literal["must_differ", "must_match", "absolute"]

CHANGE_KINDS = frozenset(
    {
        "html_must_differ",
        "text_contains",
        "text_absent",
        "text_changed",
        "attribute_equals",
        "attribute_changed",
        "css_declaration",
        "css_changed",
        "function_body_changed",
        "numeric_changed",
        "shell_meta_changed",
        "widget_default_changed",
        "runtime_dom_selector_clean",
    }
)
PRESERVE_KINDS = frozenset(
    {
        "text_unchanged",
        "attribute_unchanged",
        "css_unchanged",
        "function_body_unchanged",
        "widget_type_unchanged",
        "iframe_actions_unchanged",
    }
)
ALL_KINDS = CHANGE_KINDS | PRESERVE_KINDS

_REQUIRED_WIDGET_ACTIONS = (
    "SET_WIDGET_STATE",
    "HIGHLIGHT_ELEMENT",
    "ANNOTATE_ELEMENT",
    "REVEAL_ELEMENT",
)
_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")


@dataclass(frozen=True)
class IntentCheck:
    id: str
    kind: str
    selector: str = ""
    function: str = ""
    property: str = ""
    expected: str = ""
    baseline_binding: BaselineBinding = "absolute"
    severity: IntentSeverity = "hard"
    rationale: str = ""
    group: Literal["change", "preserve"] = "change"

    def public_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "kind": self.kind,
            "selector": self.selector,
            "function": self.function,
            "property": self.property,
            "expected": self.expected,
            "baseline_binding": self.baseline_binding,
            "severity": self.severity,
            "rationale": self.rationale,
            "group": self.group,
        }


@dataclass(frozen=True)
class CheckResult:
    check: IntentCheck
    passed: bool
    message: str

    def public_dict(self) -> dict[str, Any]:
        return {
            **self.check.public_dict(),
            "passed": self.passed,
            "message": self.message,
        }


@dataclass(frozen=True)
class IntentEvaluation:
    ok: bool
    passed: tuple[CheckResult, ...]
    failed: tuple[CheckResult, ...]
    soft_failed: tuple[CheckResult, ...]
    summary: str

    def as_guard_errors(self) -> list[str]:
        return [
            f"intent:{item.check.id}:{item.check.kind}:{item.message}"
            for item in self.failed
            if item.check.severity == "hard"
        ]

    def as_guard(self, baseline_html: str) -> Callable[[str], list[str]]:
        diagnosis_checks = (
            tuple(item.check for item in self.passed)
            + tuple(item.check for item in self.failed)
            + tuple(item.check for item in self.soft_failed)
        )

        def guard(candidate: str) -> list[str]:
            evaluation = evaluate_intent_checks(
                baseline_html=baseline_html,
                candidate_html=candidate,
                change_checks=tuple(check for check in diagnosis_checks if check.group == "change"),
                preserve_checks=tuple(check for check in diagnosis_checks if check.group == "preserve"),
            )
            return evaluation.as_guard_errors()

        return guard

    def retry_evidence(self) -> str:
        lines = ["上一轮完整编辑未通过意图验收："]
        for item in self.failed:
            if item.check.severity != "hard":
                continue
            lines.append(f"- [id={item.check.id} kind={item.check.kind} group={item.check.group}] {item.message}")
        lines.append("请针对失败 hard checks 修正；已通过的 preserve hard checks 必须继续保持。")
        return "\n".join(lines)


def evaluate_edit_intent(
    *,
    baseline_html: str,
    candidate_html: str,
    change_checks: tuple[IntentCheck, ...] | list[IntentCheck],
    preserve_checks: tuple[IntentCheck, ...] | list[IntentCheck] = (),
) -> IntentEvaluation:
    return evaluate_intent_checks(
        baseline_html=baseline_html,
        candidate_html=candidate_html,
        change_checks=tuple(change_checks),
        preserve_checks=tuple(preserve_checks),
    )


def evaluate_intent_checks(
    *,
    baseline_html: str,
    candidate_html: str,
    change_checks: tuple[IntentCheck, ...],
    preserve_checks: tuple[IntentCheck, ...],
) -> IntentEvaluation:
    baseline_soup = BeautifulSoup(baseline_html or "", "html.parser")
    candidate_soup = BeautifulSoup(candidate_html or "", "html.parser")
    baseline_functions = extract_named_functions(baseline_html)
    candidate_functions = extract_named_functions(candidate_html)

    passed: list[CheckResult] = []
    failed: list[CheckResult] = []
    soft_failed: list[CheckResult] = []

    for check in (*change_checks, *preserve_checks):
        ok, message = _evaluate_one(
            check=check,
            baseline_html=baseline_html or "",
            candidate_html=candidate_html or "",
            baseline_soup=baseline_soup,
            candidate_soup=candidate_soup,
            baseline_functions=baseline_functions,
            candidate_functions=candidate_functions,
        )
        result = CheckResult(check=check, passed=ok, message=message)
        if ok:
            passed.append(result)
        elif check.severity == "soft":
            soft_failed.append(result)
        else:
            failed.append(result)

    hard_ok = not failed
    summary_parts = [item.message for item in failed[:8]]
    if soft_failed and hard_ok:
        summary_parts.append(f"soft_failed={len(soft_failed)}")
    summary = "; ".join(summary_parts) if summary_parts else "intent_ok"
    return IntentEvaluation(
        ok=hard_ok,
        passed=tuple(passed),
        failed=tuple(failed),
        soft_failed=tuple(soft_failed),
        summary=summary,
    )


def build_intent_guard(
    *,
    baseline_html: str,
    change_checks: tuple[IntentCheck, ...] | list[IntentCheck],
    preserve_checks: tuple[IntentCheck, ...] | list[IntentCheck] = (),
) -> Callable[[str], list[str]]:
    change = tuple(change_checks)
    preserve = tuple(preserve_checks)

    def guard(candidate: str) -> list[str]:
        return evaluate_intent_checks(
            baseline_html=baseline_html,
            candidate_html=candidate,
            change_checks=change,
            preserve_checks=preserve,
        ).as_guard_errors()

    return guard


def _evaluate_one(
    *,
    check: IntentCheck,
    baseline_html: str,
    candidate_html: str,
    baseline_soup: BeautifulSoup,
    candidate_soup: BeautifulSoup,
    baseline_functions: dict[str, list[Any]],
    candidate_functions: dict[str, list[Any]],
) -> tuple[bool, str]:
    kind = check.kind
    if kind == "html_must_differ":
        changed = normalize_html_for_compare(baseline_html) != normalize_html_for_compare(candidate_html)
        return changed, "html_unchanged" if not changed else "html_changed"
    if kind == "runtime_dom_selector_clean":
        dirty = bool(find_dom_element_selector_mismatches(candidate_html))
        return (not dirty), "dom_element_used_as_selector" if dirty else "runtime_dom_selector_clean"
    if kind == "text_contains":
        return _text_predicate(candidate_soup, check.selector, check.expected, contains=True)
    if kind == "text_absent":
        return _text_predicate(candidate_soup, check.selector, check.expected, contains=False)
    if kind == "text_changed":
        before = _collect_text(baseline_soup, check.selector)
        after = _collect_text(candidate_soup, check.selector)
        changed = before != after
        return changed, "text_unchanged" if not changed else "text_changed"
    if kind == "text_unchanged":
        before = _collect_text(baseline_soup, check.selector)
        after = _collect_text(candidate_soup, check.selector)
        same = before == after
        return same, "text_drifted" if not same else "text_unchanged"
    if kind == "attribute_equals":
        return _attribute_equals(candidate_soup, check.selector, check.property, check.expected)
    if kind == "attribute_changed":
        before = _attribute_values(baseline_soup, check.selector, check.property)
        after = _attribute_values(candidate_soup, check.selector, check.property)
        changed = before != after
        return changed, "attribute_unchanged" if not changed else "attribute_changed"
    if kind == "attribute_unchanged":
        before = _attribute_values(baseline_soup, check.selector, check.property)
        after = _attribute_values(candidate_soup, check.selector, check.property)
        same = before == after
        return same, "attribute_drifted" if not same else "attribute_unchanged"
    if kind == "css_declaration":
        ok = _has_css_declaration(candidate_soup, check.selector, check.property, check.expected)
        return ok, "css_mismatch" if not ok else "css_declaration_ok"
    if kind == "css_changed":
        before = _css_values(baseline_soup, check.selector, check.property)
        after = _css_values(candidate_soup, check.selector, check.property)
        changed = before != after
        return changed, "css_unchanged" if not changed else "css_changed"
    if kind == "css_unchanged":
        before = _css_values(baseline_soup, check.selector, check.property)
        after = _css_values(candidate_soup, check.selector, check.property)
        same = before == after
        return same, "css_drifted" if not same else "css_unchanged"
    if kind == "function_body_changed":
        return _function_hash_changed(baseline_functions, candidate_functions, check.function, expect_changed=True)
    if kind == "function_body_unchanged":
        return _function_hash_changed(baseline_functions, candidate_functions, check.function, expect_changed=False)
    if kind == "numeric_changed":
        before = _numbers_in_scope(baseline_soup, baseline_html, check.selector)
        after = _numbers_in_scope(candidate_soup, candidate_html, check.selector)
        changed = before != after
        return changed, "numeric_unchanged" if not changed else "numeric_changed"
    if kind == "shell_meta_changed":
        before = _shell_meta(baseline_soup)
        after = _shell_meta(candidate_soup)
        changed = before != after
        return changed, "shell_meta_unchanged" if not changed else "shell_meta_changed"
    if kind == "widget_default_changed":
        before = _widget_property(baseline_soup, check.property)
        after = _widget_property(candidate_soup, check.property)
        if check.expected:
            ok = after == check.expected and after != before
            return ok, "widget_default_mismatch" if not ok else "widget_default_changed"
        changed = before != after
        return changed, "widget_default_unchanged" if not changed else "widget_default_changed"
    if kind == "widget_type_unchanged":
        before = _widget_property(baseline_soup, "type")
        after = _widget_property(candidate_soup, "type")
        if not before and not after:
            return True, "widget_type_absent_both"
        same = before == after
        return same, f"widget_type_changed:{before}->{after}" if not same else "widget_type_unchanged"
    if kind == "iframe_actions_unchanged":
        missing = [
            action for action in _REQUIRED_WIDGET_ACTIONS if action in baseline_html and action not in candidate_html
        ]
        return (not missing), (f"widget_actions_missing:{','.join(missing)}" if missing else "iframe_actions_unchanged")
    return False, f"unknown_kind:{kind}"


def _text_predicate(soup: BeautifulSoup, selector: str, expected: str, *, contains: bool) -> tuple[bool, str]:
    texts = _collect_text(soup, selector)
    if contains:
        ok = bool(expected) and any(expected in text for text in texts)
        return ok, "text_missing" if not ok else "text_contains"
    ok = not any(expected in text for text in texts) if expected else True
    return ok, "text_still_present" if not ok else "text_absent"


def _collect_text(soup: BeautifulSoup, selector: str) -> tuple[str, ...]:
    if selector:
        elements = _select(soup, selector)
        return tuple(element.get_text(" ", strip=True) for element in elements)
    return (soup.get_text(" ", strip=True),)


def _attribute_equals(soup: BeautifulSoup, selector: str, attribute: str, expected: str) -> tuple[bool, str]:
    values = _attribute_values(soup, selector, attribute)
    ok = bool(values) and any(value == expected for value in values)
    return ok, "attribute_mismatch" if not ok else "attribute_equals"


def _attribute_values(soup: BeautifulSoup, selector: str, attribute: str) -> tuple[str, ...]:
    if not attribute:
        return ()
    elements = _select(soup, selector) if selector else list(soup.find_all(True))
    return tuple(str(element.get(attribute) or "") for element in elements)


def _function_hash_changed(
    baseline_functions: dict[str, list[Any]],
    candidate_functions: dict[str, list[Any]],
    function_name: str,
    *,
    expect_changed: bool,
) -> tuple[bool, str]:
    if not function_name:
        return False, "function_missing_name"
    baseline = baseline_functions.get(function_name) or []
    candidate = candidate_functions.get(function_name) or []
    if len(baseline) != 1:
        return False, f"function_not_unique:{function_name}"
    if expect_changed:
        if not candidate:
            return True, "function_removed_or_renamed"
        changed = all(item.source_hash != baseline[0].source_hash for item in candidate)
        return changed, "function_unchanged" if not changed else "function_body_changed"
    if len(candidate) != 1:
        return False, f"function_not_unique:{function_name}"
    changed = baseline[0].source_hash != candidate[0].source_hash
    return (not changed), "function_drifted" if changed else "function_body_unchanged"


def _numbers_in_scope(soup: BeautifulSoup, html: str, selector: str) -> tuple[str, ...]:
    if selector:
        elements = _select(soup, selector)
        text = " ".join(str(element) for element in elements)
    else:
        text = html
    return tuple(_NUMBER_RE.findall(text))


def _shell_meta(soup: BeautifulSoup) -> dict[str, Any]:
    region = soup.select_one('[data-shell-content-edit="true"]')
    if region is not None:
        return {
            "title": str(region.get("data-title") or "").strip(),
            "goal": str(region.get("data-goal") or "").strip(),
            "objectives": [item.get_text(" ", strip=True) for item in region.select("li") if item.get_text(strip=True)],
        }
    title_el = soup.select_one(".av-title")
    goal_el = soup.select_one(".av-goal")
    return {
        "title": title_el.get_text(" ", strip=True) if title_el else "",
        "goal": goal_el.get_text(" ", strip=True) if goal_el else "",
        "objectives": [
            item.get_text(" ", strip=True) for item in soup.select(".av-objectives li") if item.get_text(strip=True)
        ],
    }


def _widget_property(soup: BeautifulSoup, property_name: str) -> str:
    script = soup.find("script", id="widget-config")
    if script is None or not property_name:
        return ""
    try:
        payload = json.loads(script.get_text())
    except (TypeError, ValueError):
        return ""
    if not isinstance(payload, dict):
        return ""
    value = payload.get(property_name)
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return str(value) if value is not None else ""


def _select(soup: BeautifulSoup, selector: str) -> list[Any]:
    try:
        return list(soup.select(selector)) if selector else []
    except Exception:
        return []


def _css_values(soup: BeautifulSoup, selector: str, property_name: str) -> tuple[str, ...]:
    values: list[str] = []
    for style in soup.find_all("style"):
        for rule in tinycss2.parse_stylesheet(style.get_text() or "", skip_comments=True, skip_whitespace=True):
            if getattr(rule, "type", "") != "qualified-rule":
                continue
            if selector not in _css_rule_selectors(rule.prelude):
                continue
            for declaration in tinycss2.parse_declaration_list(rule.content, skip_comments=True, skip_whitespace=True):
                if getattr(declaration, "type", "") != "declaration" or declaration.name != property_name:
                    continue
                values.append(tinycss2.serialize(declaration.value).strip())
    for element in _select(soup, selector):
        for declaration in tinycss2.parse_declaration_list(
            str(element.get("style") or ""), skip_comments=True, skip_whitespace=True
        ):
            if getattr(declaration, "type", "") != "declaration" or declaration.name != property_name:
                continue
            values.append(tinycss2.serialize(declaration.value).strip())
    return tuple(values)


def _css_rule_selectors(prelude: list[Any]) -> tuple[str, ...]:
    """Split a qualified-rule prelude on top-level commas only."""

    selectors: list[str] = []
    current: list[Any] = []
    for token in prelude:
        if getattr(token, "type", "") == "literal" and getattr(token, "value", "") == ",":
            rendered = tinycss2.serialize(current).strip()
            if rendered:
                selectors.append(rendered)
            current = []
            continue
        current.append(token)
    rendered = tinycss2.serialize(current).strip()
    if rendered:
        selectors.append(rendered)
    return tuple(selectors)


def _has_css_declaration(soup: BeautifulSoup, selector: str, property_name: str, expected: str) -> bool:
    return expected in _css_values(soup, selector, property_name)
