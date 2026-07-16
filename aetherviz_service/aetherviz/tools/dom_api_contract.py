"""Detect and repair high-confidence DOM value/type contract mismatches."""

from __future__ import annotations

import re
from dataclasses import dataclass

from aetherviz_service.aetherviz.tools.javascript_object import matching_brace

_IDENTIFIER = r"[A-Za-z_$][\w$]*"
_FUNCTION_RE = re.compile(rf"\bfunction\s+(?P<name>{_IDENTIFIER})\s*\((?P<params>[^)]*)\)\s*\{{")


@dataclass(frozen=True)
class DomSelectorMismatch:
    """A helper treats a proven DOM element argument as a selector string."""

    function_name: str
    parameter_name: str


def find_dom_element_selector_mismatches(script_text: str) -> tuple[DomSelectorMismatch, ...]:
    """Find helpers whose ``querySelector(param)`` receives a DOM element.

    The check deliberately requires both sides of the mismatch: the helper must
    pass one of its parameters to ``document.querySelector`` and at least one
    call site must provably supply a DOM element (a DOM iteration item, a DOM
    lookup result, or a direct DOM lookup expression).
    """

    source = script_text or ""
    mismatches: list[DomSelectorMismatch] = []
    for match in _FUNCTION_RE.finditer(source):
        opening = source.find("{", match.start(), match.end())
        closing = matching_brace(source, opening)
        if closing is None:
            continue
        function_name = match.group("name")
        parameters = [item.strip() for item in match.group("params").split(",")]
        body = source[opening + 1 : closing]
        for parameter in parameters:
            if not re.fullmatch(_IDENTIFIER, parameter):
                continue
            if not re.search(
                rf"\bdocument\s*\.\s*querySelector\s*\(\s*{re.escape(parameter)}\s*\)",
                body,
            ):
                continue
            if re.search(
                rf"typeof\s+{re.escape(parameter)}\s*===?\s*['\"]string['\"]"
                rf"[\s\S]{{0,160}}?document\s*\.\s*querySelector\s*\(\s*"
                rf"{re.escape(parameter)}\s*\)[\s\S]{{0,80}}?:\s*{re.escape(parameter)}\b",
                body,
            ):
                continue
            if _has_proven_element_call(source, function_name, parameter):
                mismatches.append(DomSelectorMismatch(function_name, parameter))
    return tuple(dict.fromkeys(mismatches))


def repair_dom_element_selector_mismatches(script_text: str) -> tuple[str, tuple[str, ...]]:
    """Make affected helper parameters accept either a selector or an element."""

    source = script_text or ""
    mismatches = find_dom_element_selector_mismatches(source)
    repaired = source
    applied: list[str] = []
    for mismatch in mismatches:
        function = _find_named_function(repaired, mismatch.function_name)
        if function is None:
            continue
        start, end = function
        function_source = repaired[start:end]
        parameter = mismatch.parameter_name
        pattern = re.compile(rf"\bdocument\s*\.\s*querySelector\s*\(\s*{re.escape(parameter)}\s*\)")
        replacement = f'(typeof {parameter} === "string" ? document.querySelector({parameter}) : {parameter})'
        updated, count = pattern.subn(replacement, function_source)
        if not count:
            continue
        repaired = repaired[:start] + updated + repaired[end:]
        applied.append(mismatch.function_name)
    return repaired, tuple(applied)


def _has_proven_element_call(source: str, function_name: str, parameter_name: str) -> bool:
    escaped_function = re.escape(function_name)
    direct_lookup = re.search(
        rf"\b{escaped_function}\s*\(\s*document\s*\.\s*"
        rf"(?:querySelector|getElementById)\s*\(",
        source,
    )
    if direct_lookup:
        return True

    assignments = set(
        re.findall(
            rf"\b(?:const|let|var)\s+({_IDENTIFIER})\s*=\s*document\s*\.\s*"
            rf"(?:querySelector|getElementById)\s*\(",
            source,
        )
    )
    if any(re.search(rf"\b{escaped_function}\s*\(\s*{re.escape(name)}\b", source) for name in assignments):
        return True

    arrow_iteration = re.search(
        rf"\.(?:forEach|map|filter)\s*\(\s*\(?\s*(?P<item>{_IDENTIFIER})"
        rf"(?:\s*,\s*{_IDENTIFIER})?\s*\)?\s*=>[\s\S]{{0,1000}}?"
        rf"\b{escaped_function}\s*\(\s*(?P=item)\b",
        source,
    )
    if arrow_iteration:
        return True
    function_iteration = re.search(
        rf"\.(?:forEach|map|filter)\s*\(\s*function\s*\(\s*(?P<item>{_IDENTIFIER})"
        rf"[^)]*\)\s*\{{[\s\S]{{0,1000}}?\b{escaped_function}\s*\(\s*(?P=item)\b",
        source,
    )
    return function_iteration is not None


def _find_named_function(source: str, function_name: str) -> tuple[int, int] | None:
    pattern = re.compile(rf"\bfunction\s+{re.escape(function_name)}\s*\([^)]*\)\s*\{{")
    matches = list(pattern.finditer(source))
    if len(matches) != 1:
        return None
    match = matches[0]
    opening = source.find("{", match.start(), match.end())
    closing = matching_brace(source, opening)
    return (match.start(), closing + 1) if closing is not None else None
