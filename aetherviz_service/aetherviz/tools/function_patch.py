"""Bounded, hash-guarded replacement of named JavaScript functions in HTML."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from aetherviz_service.aetherviz.limits import MAX_FUNCTION_REPLACEMENT_CHARS, MAX_FUNCTION_REPLACEMENTS
from aetherviz_service.aetherviz.tools.javascript_object import matching_brace
from aetherviz_service.aetherviz.tools.javascript_syntax import check_javascript_syntax

_FUNCTION_START_RE = re.compile(r"\bfunction\s+([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{")
_VARIABLE_ARROW_START_RE = re.compile(
    r"\b(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*"
    r"(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>\s*\{"
)
_VARIABLE_FUNCTION_START_RE = re.compile(
    r"\b(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*"
    r"(?:async\s+)?function(?:\s+[A-Za-z_$][\w$]*)?\s*\([^)]*\)\s*\{"
)
_OBJECT_ARROW_START_RE = re.compile(
    r"(?P<name>[A-Za-z_$][\w$]*)\s*:\s*"
    r"(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>\s*\{"
)
_OBJECT_FUNCTION_START_RE = re.compile(
    r"(?P<name>[A-Za-z_$][\w$]*)\s*:\s*"
    r"(?:async\s+)?function(?:\s+[A-Za-z_$][\w$]*)?\s*\([^)]*\)\s*\{"
)
_OBJECT_METHOD_START_RE = re.compile(r"(?:(?<=\{)|(?<=,))\s*(?:async\s+)?(?P<name>[A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{")
_STANDALONE_METHOD_START_RE = re.compile(
    r"^(?!\s*(?:if|for|while|switch|catch)\b)\s*(?:async\s+)?"
    r"(?P<name>[A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{",
    re.MULTILINE,
)
_FUNCTION_PATTERNS = (
    _FUNCTION_START_RE,
    _VARIABLE_ARROW_START_RE,
    _VARIABLE_FUNCTION_START_RE,
    _OBJECT_ARROW_START_RE,
    _OBJECT_FUNCTION_START_RE,
    _OBJECT_METHOD_START_RE,
    _STANDALONE_METHOD_START_RE,
)
_SCENE_BUILDER_NAMES = ("buildScene", "rebuildScene", "createScene", "initScene", "initializeScene")

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


def repair_function_targets(html: str, report: dict[str, Any]) -> tuple[str, ...]:
    """Select the failing call-chain tail plus one scene builder when available.

    A frame updater cannot move structural work out of the animation callback by
    itself. Supplying the unique scene builder lets the bounded model patch
    preallocate nodes there and leave the updater with attribute-only changes.
    """
    targets = list(target_functions_from_report(report))
    functions = extract_named_functions(html)
    builder = next(
        (name for name in _SCENE_BUILDER_NAMES if name not in targets and len(functions.get(name, [])) == 1),
        None,
    )
    if builder is None:
        return tuple(targets[-MAX_FUNCTION_REPLACEMENTS:])
    return tuple([*targets[-(MAX_FUNCTION_REPLACEMENTS - 1) :], builder])


def describe_target_functions(html: str, targets: tuple[str, ...]) -> list[dict[str, str]]:
    functions = extract_named_functions(html)
    descriptions: list[dict[str, str]] = []
    for name in targets:
        matches = functions.get(name, [])
        if len(matches) != 1:
            continue
        function = matches[0]
        descriptions.append({"function": name, "source_hash": function.source_hash, "source": function.source})
    return descriptions


def extract_named_functions(html: str) -> dict[str, list[FunctionSource]]:
    functions: dict[str, list[FunctionSource]] = {}
    seen_spans: set[tuple[int, int]] = set()
    source_html = html or ""
    for pattern in _FUNCTION_PATTERNS:
        for match in pattern.finditer(source_html):
            opening = source_html.find("{", match.start(), match.end())
            closing = matching_brace(source_html, opening)
            if closing is None:
                continue
            start = match.start()
            if pattern in {_OBJECT_METHOD_START_RE, _STANDALONE_METHOD_START_RE}:
                while start < match.end() and source_html[start].isspace():
                    start += 1
            end = closing + 1
            if (start, end) in seen_spans:
                continue
            seen_spans.add((start, end))
            name = match.groupdict().get("name") or match.group(1)
            source = source_html[start:end]
            item = FunctionSource(
                name=name,
                source=source,
                source_hash=hashlib.sha256(source.encode("utf-8")).hexdigest(),
                start=start,
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
                "target_id": str(item.get("target_id") or ""),
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
    allowed_targets: tuple[tuple[str, str], ...] = (),
    allowed_target_ids: tuple[str, ...] = (),
) -> FunctionPatchResult:
    if not replacements:
        return FunctionPatchResult(html=html, applied=(), errors=("empty_replacements",))
    if len(replacements) > MAX_FUNCTION_REPLACEMENTS:
        return FunctionPatchResult(html=html, applied=(), errors=("too_many_replacements",))
    total_chars = sum(len(item.get("replacement", "")) for item in replacements)
    if total_chars > MAX_FUNCTION_REPLACEMENT_CHARS:
        return FunctionPatchResult(html=html, applied=(), errors=("replacement_too_long",))
    functions = extract_named_functions(html)
    functions_by_target_id = {
        f"{function.name}:{function.start}:{function.source_hash[:12]}": function
        for matches in functions.values()
        for function in matches
    }
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
        source_hash = item.get("source_hash") or ""
        target_id = item.get("target_id") or ""
        if allowed_target_ids:
            if target_id not in allowed_target_ids:
                errors.append(f"function_target_id_not_allowed:{name}")
                continue
            original = functions_by_target_id.get(target_id)
            if original is None or original.name != name:
                errors.append(f"function_target_id_mismatch:{name}")
                continue
            if original.source_hash != source_hash:
                errors.append(f"source_hash_mismatch:{name}")
                continue
        else:
            original = None
        if allowed_targets and (name, source_hash) not in allowed_targets:
            errors.append(f"function_target_not_allowed:{name}")
            continue
        if original is None:
            hash_matches = [match for match in matches if match.source_hash == source_hash]
            if not hash_matches:
                errors.append(f"source_hash_mismatch:{name}")
                continue
            if len(hash_matches) != 1:
                errors.append(f"function_not_unique:{name}")
                continue
            original = hash_matches[0]
        replacement_functions = extract_named_functions(replacement)
        replacement_matches = replacement_functions.get(name, [])
        if len(replacement_matches) != 1 or replacement_matches[0].source.strip() != replacement:
            errors.append(f"replacement_name_mismatch:{name}")
            continue
        if "</script" in replacement.lower():
            errors.append(f"script_escape:{name}")
            continue
        syntax_source = replacement
        if not re.match(r"^(?:async\s+)?function\b|^(?:const|let|var)\b", replacement):
            syntax_source = f"const __aetherviz_patch__={{ {replacement} }};"
        syntax_error = check_javascript_syntax(syntax_source)
        if syntax_error:
            errors.append(f"replacement_js_syntax:{name}:{syntax_error}")
            continue
        if replacement == original.source.strip():
            errors.append(f"unchanged_replacement:{name}")
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
