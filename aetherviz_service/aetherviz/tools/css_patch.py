"""Standards-based CSS targeting and transactional declaration edits."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

import tinycss2

CssParseStatus = Literal["exact", "unsupported", "malformed"]

_GROUPING_AT_RULES = {"container", "document", "layer", "media", "scope", "starting-style", "supports"}
_DECLARATION_AT_RULES = {
    "counter-style",
    "font-face",
    "page",
    "property",
}
_KEYFRAME_AT_RULES = {"keyframes", "-webkit-keyframes"}
_PROPERTY_RE = re.compile(r"(?:--[A-Za-z0-9_-]+|-?[A-Za-z_][A-Za-z0-9_-]*)\Z")
_EXTERNAL_URL_RE = re.compile(r"url\s*\(\s*['\"]?https?://", re.IGNORECASE)


@dataclass(frozen=True)
class CssRuleSpan:
    start: int
    end: int
    selector: str
    at_rule_path: tuple[str, ...]
    occurrence: int


@dataclass(frozen=True)
class CssParseResult:
    status: CssParseStatus
    rules: tuple[CssRuleSpan, ...]
    errors: tuple[str, ...] = ()


def parse_css_rules(css: str) -> CssParseResult:
    """Parse DOM-addressable qualified rules while preserving exact source spans."""
    lexical_error = _css_lexical_error(css)
    if lexical_error:
        return CssParseResult(status="malformed", rules=(), errors=(lexical_error,))

    nodes = tinycss2.parse_stylesheet(css, skip_comments=False, skip_whitespace=False)
    rules: list[CssRuleSpan] = []
    errors: list[str] = []
    unsupported = False
    occurrences: dict[tuple[tuple[str, ...], str], int] = {}

    def walk(items: list[Any], path: tuple[str, ...]) -> None:
        nonlocal unsupported
        for node in items:
            if node.type in {"comment", "whitespace"}:
                continue
            if node.type == "error":
                errors.append(f"{node.source_line}:{node.source_column}:{node.message}")
                continue
            if node.type == "qualified-rule":
                selector = tinycss2.serialize(node.prelude).strip()
                span = _qualified_rule_span(css, node)
                if not selector or span is None:
                    errors.append(f"{node.source_line}:{node.source_column}:rule_span_unavailable")
                    continue
                nested = tinycss2.parse_blocks_contents(node.content, skip_comments=False, skip_whitespace=False)
                errors.extend(_parse_errors(nested))
                key = (path, _normalize_selector(selector))
                occurrence = occurrences.get(key, 0)
                occurrences[key] = occurrence + 1
                rules.append(
                    CssRuleSpan(
                        start=span[0],
                        end=span[1],
                        selector=selector,
                        at_rule_path=path,
                        occurrence=occurrence,
                    )
                )
                continue
            if node.type != "at-rule":
                unsupported = True
                continue
            keyword = node.lower_at_keyword
            if node.content is None:
                if keyword not in {"charset", "import", "layer", "namespace"}:
                    unsupported = True
                continue
            if keyword in _GROUPING_AT_RULES:
                label = f"@{keyword} {tinycss2.serialize(node.prelude).strip()}".strip()
                children = tinycss2.parse_rule_list(node.content, skip_comments=False, skip_whitespace=False)
                walk(children, (*path, label))
            elif keyword in _DECLARATION_AT_RULES:
                declarations = tinycss2.parse_declaration_list(
                    node.content,
                    skip_comments=False,
                    skip_whitespace=False,
                )
                errors.extend(_parse_errors(declarations))
            elif keyword in _KEYFRAME_AT_RULES:
                keyframes = tinycss2.parse_rule_list(node.content, skip_comments=False, skip_whitespace=False)
                errors.extend(_parse_errors(keyframes))
            else:
                unsupported = True

    walk(nodes, ())
    if errors:
        return CssParseResult(status="malformed", rules=(), errors=tuple(dict.fromkeys(errors)))
    return CssParseResult(status="unsupported" if unsupported else "exact", rules=tuple(rules))


def apply_declaration_edit(
    rule_source: str,
    *,
    set_values: dict[str, str],
    remove: list[str],
) -> tuple[str | None, str | None]:
    """Apply bounded declaration mutations without allowing selector or rule-structure drift."""
    parsed = parse_css_rules(rule_source)
    if parsed.status != "exact" or len(parsed.rules) != 1:
        return None, f"css_declaration_rule_{parsed.status}"
    rule = parsed.rules[0]
    if rule.start != 0 or rule.end != len(rule_source):
        return None, "css_declaration_rule_not_single"
    if len(set_values) > 12 or len(remove) > 12:
        return None, "css_declaration_too_many_properties"

    normalized_set: dict[str, str] = {}
    normalized_remove: set[str] = set()
    for raw_name, raw_value in set_values.items():
        name = str(raw_name).strip()
        value = str(raw_value).strip()
        validation_error = _declaration_input_error(name, value)
        if validation_error:
            return None, validation_error
        normalized_set[name.lower()] = f"{name}:{value};"
    for raw_name in remove:
        name = str(raw_name).strip()
        if not _PROPERTY_RE.fullmatch(name):
            return None, f"css_declaration_invalid_property:{name}"
        normalized_remove.add(name.lower())
    if normalized_set.keys() & normalized_remove:
        return None, "css_declaration_set_remove_conflict"

    node = tinycss2.parse_one_rule(rule_source, skip_comments=False)
    if node is None or node.type != "qualified-rule":
        return None, "css_declaration_rule_invalid"
    block_items = tinycss2.parse_blocks_contents(node.content, skip_comments=False, skip_whitespace=False)
    if _parse_errors(block_items):
        return None, "css_declaration_block_invalid"

    patches: list[tuple[int, int, str]] = []
    found: set[str] = set()
    first_nested_start: int | None = None
    for item in block_items:
        if item.type in {"qualified-rule", "at-rule"} and first_nested_start is None:
            first_nested_start = _line_column_offset(rule_source, item.source_line, item.source_column)
        if item.type != "declaration":
            continue
        start = _line_column_offset(rule_source, item.source_line, item.source_column)
        end = _css_statement_end(rule_source, start)
        if start is None or end is None:
            return None, "css_declaration_span_unavailable"
        name = item.lower_name
        if name in normalized_remove:
            patches.append((start, end, ""))
            found.add(name)
        elif name in normalized_set:
            patches.append((start, end, normalized_set[name]))
            found.add(name)

    additions = [value for name, value in normalized_set.items() if name not in found]
    if additions:
        opening = _find_css_token(rule_source, "{", 0)
        closing = _matching_css_brace(rule_source, opening) if opening is not None else None
        if closing is None:
            return None, "css_declaration_rule_unbalanced"
        insertion = first_nested_start if first_nested_start is not None else closing
        prefix = " " if insertion > 0 and not rule_source[insertion - 1].isspace() else ""
        patches.append((insertion, insertion, f"{prefix}{' '.join(additions)}"))

    if not patches:
        return None, "css_declaration_unchanged"
    updated = rule_source
    for start, end, replacement in sorted(patches, reverse=True):
        updated = updated[:start] + replacement + updated[end:]
    validation = parse_css_rules(updated)
    if validation.status != "exact" or len(validation.rules) != 1:
        return None, "css_declaration_result_invalid"
    if _normalize_selector(validation.rules[0].selector) != _normalize_selector(rule.selector):
        return None, "css_declaration_selector_changed"
    if updated == rule_source:
        return None, "css_declaration_unchanged"
    return updated, None


def stylesheet_validation_error(css: str) -> str | None:
    parsed = parse_css_rules(css)
    if parsed.status == "malformed":
        return "css_stylesheet_malformed"
    if "@import" in css.lower() or _EXTERNAL_URL_RE.search(css):
        return "css_stylesheet_external_resource"
    return None


def _qualified_rule_span(css: str, node: Any) -> tuple[int, int] | None:
    start = _line_column_offset(css, node.source_line, node.source_column)
    if start is None:
        return None
    opening = _find_css_token(css, "{", start)
    closing = _matching_css_brace(css, opening) if opening is not None else None
    return (start, closing + 1) if closing is not None else None


def _line_column_offset(text: str, line: int, column: int) -> int | None:
    if line < 1 or column < 1:
        return None
    lines = text.splitlines(keepends=True)
    if line > len(lines):
        return None
    offset = sum(len(item) for item in lines[: line - 1]) + column - 1
    return offset if offset <= len(text) else None


def _parse_errors(nodes: list[Any]) -> list[str]:
    return [
        f"{node.source_line}:{node.source_column}:{node.message}"
        for node in nodes
        if node.type == "error"
    ]


def _declaration_input_error(name: str, value: str) -> str | None:
    if not _PROPERTY_RE.fullmatch(name):
        return f"css_declaration_invalid_property:{name}"
    if not value or len(value) > 1_000:
        return f"css_declaration_invalid_value:{name}"
    lowered = value.lower()
    if "@import" in lowered or _EXTERNAL_URL_RE.search(value) or "expression(" in lowered:
        return f"css_declaration_unsafe_value:{name}"
    declarations = tinycss2.parse_declaration_list(f"{name}:{value};", skip_comments=True, skip_whitespace=True)
    if len(declarations) != 1 or declarations[0].type != "declaration":
        return f"css_declaration_invalid_value:{name}"
    return None


def _css_statement_end(text: str, start: int | None) -> int | None:
    if start is None:
        return None
    quote: str | None = None
    escaped = False
    comment = False
    depth = 0
    index = start
    while index < len(text):
        char = text[index]
        next_char = text[index + 1] if index + 1 < len(text) else ""
        if comment:
            if char == "*" and next_char == "/":
                comment = False
                index += 2
            else:
                index += 1
            continue
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            index += 1
            continue
        if char == "/" and next_char == "*":
            comment = True
            index += 2
            continue
        if char in {"'", '"'}:
            quote = char
        elif char in "([":
            depth += 1
        elif char in ")]":
            depth = max(0, depth - 1)
        elif char == ";" and depth == 0:
            return index + 1
        elif char == "}" and depth == 0:
            return index
        index += 1
    return None


def _css_lexical_error(text: str) -> str | None:
    quote: str | None = None
    escaped = False
    comment = False
    braces = 0
    index = 0
    while index < len(text):
        char = text[index]
        next_char = text[index + 1] if index + 1 < len(text) else ""
        if comment:
            if char == "*" and next_char == "/":
                comment = False
                index += 2
            else:
                index += 1
            continue
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            index += 1
            continue
        if char == "/" and next_char == "*":
            comment = True
            index += 2
            continue
        if char in {"'", '"'}:
            quote = char
        elif char == "{":
            braces += 1
        elif char == "}":
            braces -= 1
            if braces < 0:
                return "unexpected_closing_brace"
        index += 1
    if comment:
        return "unclosed_comment"
    if quote:
        return "unclosed_string"
    if braces:
        return "unbalanced_braces"
    return None


def _find_css_token(text: str, token: str, start: int) -> int | None:
    quote: str | None = None
    escaped = False
    comment = False
    index = start
    while index < len(text):
        char = text[index]
        next_char = text[index + 1] if index + 1 < len(text) else ""
        if comment:
            if char == "*" and next_char == "/":
                comment = False
                index += 2
            else:
                index += 1
            continue
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            index += 1
            continue
        if char == "/" and next_char == "*":
            comment = True
            index += 2
            continue
        if char in {"'", '"'}:
            quote = char
        elif char == token:
            return index
        index += 1
    return None


def _matching_css_brace(text: str, opening: int | None) -> int | None:
    if opening is None:
        return None
    depth = 0
    cursor = opening
    while cursor < len(text):
        next_opening = _find_css_token(text, "{", cursor)
        next_closing = _find_css_token(text, "}", cursor)
        if next_closing is None:
            return None
        if next_opening is not None and next_opening < next_closing:
            depth += 1
            cursor = next_opening + 1
            continue
        depth -= 1
        if depth == 0:
            return next_closing
        cursor = next_closing + 1
    return None


def _normalize_selector(selector: str) -> str:
    return re.sub(r"\s+", " ", selector.strip())
