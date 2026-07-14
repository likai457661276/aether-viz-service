"""Bounded, hash-guarded replacement of named JavaScript functions in HTML."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from aetherviz_service.aetherviz.tools.javascript_syntax import check_javascript_syntax

MAX_FUNCTION_REPLACEMENTS = 3
MAX_FUNCTION_REPLACEMENT_CHARS = 6_000
_FUNCTION_START_RE = re.compile(r"\bfunction\s+([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{")


@dataclass(frozen=True)
class FunctionSource:
    name: str
    source: str
    source_hash: str
    start: int
    end: int


@dataclass(frozen=True)
class FunctionPatchResult:
    html: str
    applied: tuple[str, ...]
    errors: tuple[str, ...] = ()


def target_functions_from_report(report: dict[str, Any]) -> tuple[str, ...]:
    targets: list[str] = []
    for error in report.get("errors", []):
        if not isinstance(error, dict) or error.get("type") != "structural_render_inside_animation_frame":
            continue
        for name in error.get("call_chain", []):
            normalized = str(name or "")
            if normalized and not normalized.startswith("<") and normalized not in targets:
                targets.append(normalized)
    return tuple(targets)


def describe_target_functions(html: str, targets: tuple[str, ...]) -> list[dict[str, str]]:
    functions = extract_named_functions(html)
    descriptions: list[dict[str, str]] = []
    for name in targets:
        matches = functions.get(name, [])
        if len(matches) != 1:
            continue
        function = matches[0]
        descriptions.append(
            {"function": name, "source_hash": function.source_hash, "source": function.source}
        )
    return descriptions


def extract_named_functions(html: str) -> dict[str, list[FunctionSource]]:
    functions: dict[str, list[FunctionSource]] = {}
    for match in _FUNCTION_START_RE.finditer(html or ""):
        opening = (html or "").find("{", match.start(), match.end())
        closing = _matching_brace(html or "", opening)
        if closing is None:
            continue
        end = closing + 1
        source = (html or "")[match.start() : end]
        item = FunctionSource(
            name=match.group(1),
            source=source,
            source_hash=hashlib.sha256(source.encode("utf-8")).hexdigest(),
            start=match.start(),
            end=end,
        )
        functions.setdefault(item.name, []).append(item)
    return functions


def parse_function_replacements(raw_text: str) -> list[dict[str, str]]:
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
    raw_replacements = payload.get("replacements") if isinstance(payload, dict) else None
    if not isinstance(raw_replacements, list):
        return []
    replacements: list[dict[str, str]] = []
    for item in raw_replacements[:MAX_FUNCTION_REPLACEMENTS]:
        if not isinstance(item, dict):
            continue
        replacements.append(
            {
                "function": str(item.get("function") or ""),
                "source_hash": str(item.get("source_hash") or ""),
                "replacement": str(item.get("replacement") or ""),
            }
        )
    return replacements


def apply_function_replacements(
    html: str,
    replacements: list[dict[str, str]],
    *,
    allowed_functions: tuple[str, ...],
) -> FunctionPatchResult:
    if not replacements:
        return FunctionPatchResult(html=html, applied=(), errors=("empty_replacements",))
    if len(replacements) > MAX_FUNCTION_REPLACEMENTS:
        return FunctionPatchResult(html=html, applied=(), errors=("too_many_replacements",))
    total_chars = sum(len(item.get("replacement", "")) for item in replacements)
    if total_chars > MAX_FUNCTION_REPLACEMENT_CHARS:
        return FunctionPatchResult(html=html, applied=(), errors=("replacement_too_long",))
    functions = extract_named_functions(html)
    patches: list[tuple[int, int, str, str]] = []
    errors: list[str] = []
    seen: set[str] = set()
    for item in replacements:
        name = item.get("function", "")
        replacement = item.get("replacement", "").strip()
        if name in seen:
            errors.append(f"duplicate_replacement:{name}")
            continue
        seen.add(name)
        if name not in allowed_functions:
            errors.append(f"function_not_allowed:{name}")
            continue
        matches = functions.get(name, [])
        if len(matches) != 1:
            errors.append(f"function_not_unique:{name}")
            continue
        original = matches[0]
        if item.get("source_hash") != original.source_hash:
            errors.append(f"source_hash_mismatch:{name}")
            continue
        replacement_match = _FUNCTION_START_RE.match(replacement)
        if not replacement_match or replacement_match.group(1) != name:
            errors.append(f"replacement_name_mismatch:{name}")
            continue
        if "</script" in replacement.lower():
            errors.append(f"script_escape:{name}")
            continue
        syntax_error = check_javascript_syntax(replacement)
        if syntax_error:
            errors.append(f"replacement_js_syntax:{name}:{syntax_error}")
            continue
        patches.append((original.start, original.end, replacement, name))
    if errors or not patches:
        return FunctionPatchResult(html=html, applied=(), errors=tuple(errors or ["no_valid_replacements"]))
    updated = html
    for start, end, replacement, _name in sorted(patches, reverse=True):
        updated = updated[:start] + replacement + updated[end:]
    return FunctionPatchResult(
        html=updated,
        applied=tuple(name for _start, _end, _replacement, name in patches),
    )


def _matching_brace(text: str, opening: int) -> int | None:
    if opening < 0:
        return None
    depth = 0
    quote: str | None = None
    escaped = False
    line_comment = False
    block_comment = False
    index = opening
    while index < len(text):
        char = text[index]
        next_char = text[index + 1] if index + 1 < len(text) else ""
        if line_comment:
            if char in "\r\n":
                line_comment = False
            index += 1
            continue
        if block_comment:
            if char == "*" and next_char == "/":
                block_comment = False
                index += 2
                continue
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
        if char == "/" and next_char == "/":
            line_comment = True
            index += 2
            continue
        if char == "/" and next_char == "*":
            block_comment = True
            index += 2
            continue
        if char in {"'", '"', "`"}:
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return None
