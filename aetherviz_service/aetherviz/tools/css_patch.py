"""Bounded, hash-guarded replacement of CSS qualified rules in HTML."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

import tinycss2

from aetherviz_service.aetherviz.limits import MAX_CSS_RULE_REPLACEMENT_CHARS, MAX_CSS_RULE_REPLACEMENTS


@dataclass(frozen=True)
class CssRuleSource:
    selector: str
    source: str
    source_hash: str
    start: int
    end: int
    style_index: int


@dataclass(frozen=True)
class CssPatchResult:
    html: str
    applied: tuple[str, ...]
    errors: tuple[str, ...] = ()


def extract_named_css_rules(html: str) -> dict[str, list[CssRuleSource]]:
    """Extract qualified CSS rules keyed by serialized selector text."""

    soup_html = html or ""
    rules: dict[str, list[CssRuleSource]] = {}
    style_pattern = re.compile(r"<style\b[^>]*>(.*?)</style>", re.IGNORECASE | re.DOTALL)
    for style_index, style_match in enumerate(style_pattern.finditer(soup_html)):
        css_text = style_match.group(1)
        css_offset = style_match.start(1)
        parsed = tinycss2.parse_stylesheet(css_text, skip_comments=True, skip_whitespace=False)
        for rule in parsed:
            if getattr(rule, "type", "") != "qualified-rule":
                continue
            if rule.source_line is None or rule.source_column is None:
                continue
            selector = tinycss2.serialize(rule.prelude).strip()
            if not selector:
                continue
            start = css_offset + _line_column_offset(css_text, rule.source_line, rule.source_column)
            # tinycss2 end positions are exclusive of the closing brace in some versions;
            # recover the full rule text by scanning from start to the matching '}'.
            end = _rule_end_offset(soup_html, start)
            if end is None or end <= start:
                continue
            source = soup_html[start:end]
            item = CssRuleSource(
                selector=selector,
                source=source,
                source_hash=hashlib.sha256(source.encode("utf-8")).hexdigest(),
                start=start,
                end=end,
                style_index=style_index,
            )
            rules.setdefault(selector, []).append(item)
    return rules


def describe_target_css_rules(html: str, selectors: tuple[str, ...]) -> list[dict[str, str]]:
    rules = extract_named_css_rules(html)
    descriptions: list[dict[str, str]] = []
    for selector in selectors:
        matches = rules.get(selector, [])
        if len(matches) != 1:
            continue
        rule = matches[0]
        descriptions.append(
            {
                "selector": selector,
                "source_hash": rule.source_hash,
                "source": rule.source,
            }
        )
    return descriptions


def parse_css_rule_replacements(raw_text: str) -> list[dict[str, str]]:
    text = (raw_text or "").strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        text = match.group(0)
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        return []
    raw_replacements = payload.get("css_rule_replacements") if isinstance(payload, dict) else None
    if raw_replacements is None and isinstance(payload, dict):
        raw_replacements = payload.get("replacements")
    if not isinstance(raw_replacements, list):
        return []
    replacements: list[dict[str, str]] = []
    for item in raw_replacements[:MAX_CSS_RULE_REPLACEMENTS]:
        if not isinstance(item, dict):
            continue
        replacements.append(
            {
                "selector": str(item.get("selector") or ""),
                "source_hash": str(item.get("source_hash") or ""),
                "replacement": str(item.get("replacement") or ""),
            }
        )
    return replacements


def apply_css_rule_replacements(
    html: str,
    replacements: list[dict[str, str]],
    *,
    allowed_selectors: tuple[str, ...],
    allowed_targets: tuple[tuple[str, str], ...] = (),
) -> CssPatchResult:
    if not replacements:
        return CssPatchResult(html=html, applied=(), errors=("empty_replacements",))
    if len(replacements) > MAX_CSS_RULE_REPLACEMENTS:
        return CssPatchResult(html=html, applied=(), errors=("too_many_replacements",))
    total_chars = sum(len(item.get("replacement", "")) for item in replacements)
    if total_chars > MAX_CSS_RULE_REPLACEMENT_CHARS:
        return CssPatchResult(html=html, applied=(), errors=("replacement_too_long",))

    rules = extract_named_css_rules(html)
    patches: list[tuple[int, int, str, str]] = []
    errors: list[str] = []
    seen: set[str] = set()
    for item in replacements:
        selector = item.get("selector", "")
        replacement = item.get("replacement", "").strip()
        if selector in seen:
            errors.append(f"duplicate_replacement:{selector}")
            continue
        seen.add(selector)
        if selector not in allowed_selectors:
            errors.append(f"selector_not_allowed:{selector}")
            continue
        matches = rules.get(selector, [])
        source_hash = item.get("source_hash") or ""
        if allowed_targets and (selector, source_hash) not in allowed_targets:
            errors.append(f"css_target_not_allowed:{selector}")
            continue
        hash_matches = [match for match in matches if match.source_hash == source_hash]
        if not hash_matches:
            errors.append(f"source_hash_mismatch:{selector}")
            continue
        if len(hash_matches) != 1:
            errors.append(f"selector_not_unique:{selector}")
            continue
        original = hash_matches[0]
        if "</style" in replacement.lower() or "<script" in replacement.lower():
            errors.append(f"style_escape:{selector}")
            continue
        if not _is_valid_css_rule(replacement, expected_selector=selector):
            errors.append(f"replacement_css_invalid:{selector}")
            continue
        if replacement == original.source.strip():
            errors.append(f"unchanged_replacement:{selector}")
            continue
        patches.append((original.start, original.end, replacement, selector))
    if errors or not patches:
        return CssPatchResult(html=html, applied=(), errors=tuple(errors or ["no_valid_replacements"]))
    updated = html
    for start, end, replacement, _selector in sorted(patches, reverse=True):
        updated = updated[:start] + replacement + updated[end:]
    return CssPatchResult(
        html=updated,
        applied=tuple(selector for _start, _end, _replacement, selector in patches),
    )


def _line_column_offset(text: str, line: int, column: int) -> int:
    """Convert 1-based tinycss2 line/column to a 0-based string offset."""

    if line <= 1:
        return max(column - 1, 0)
    offset = 0
    current_line = 1
    for char in text:
        if current_line == line:
            return offset + max(column - 1, 0)
        offset += 1
        if char == "\n":
            current_line += 1
    return offset + max(column - 1, 0)


def _rule_end_offset(html: str, start: int) -> int | None:
    depth = 0
    in_string: str | None = None
    i = start
    while i < len(html):
        char = html[i]
        if in_string:
            if char == "\\" and i + 1 < len(html):
                i += 2
                continue
            if char == in_string:
                in_string = None
            i += 1
            continue
        if char in {'"', "'"}:
            in_string = char
            i += 1
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return None


def _is_valid_css_rule(replacement: str, *, expected_selector: str) -> bool:
    parsed = tinycss2.parse_stylesheet(replacement, skip_comments=True, skip_whitespace=True)
    qualified = [rule for rule in parsed if getattr(rule, "type", "") == "qualified-rule"]
    if len(qualified) != 1:
        return False
    selector = tinycss2.serialize(qualified[0].prelude).strip()
    return selector == expected_selector


def css_rule_inventory(html: str) -> list[dict[str, Any]]:
    """Compact inventory for edit context / diagnosis evidence."""

    result: list[dict[str, Any]] = []
    for selector, matches in extract_named_css_rules(html).items():
        for rule in matches[:2]:
            result.append(
                {
                    "selector": selector,
                    "source_hash": rule.source_hash,
                    "chars": len(rule.source),
                    "unique": len(matches) == 1,
                }
            )
    return result
