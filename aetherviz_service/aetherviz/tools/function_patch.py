"""Bounded, hash-guarded replacement of named JavaScript functions in HTML."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from aetherviz_service.aetherviz.tools.animation_lifecycle_checker import check_animation_lifecycle
from aetherviz_service.aetherviz.tools.javascript_syntax import (
    check_javascript_syntax,
    new_unresolved_identifiers,
)

MAX_FUNCTION_REPLACEMENTS = 5
MAX_FUNCTION_REPLACEMENT_CHARS = 6_000
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
_LEGACY_PLAYBACK_FUNCTION_NAMES = (
    "play",
    "loop",
    "animate",
    "nativeFrame",
    "tick",
    "setSpeed",
    "pause",
    "reset",
    "applyView",
    "render",
    "updateView",
)


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


def select_edit_function_descriptions(
    html: str,
    instruction: str,
    *,
    target_selectors: tuple[str, ...] = (),
) -> list[dict[str, str | int]]:
    """Describe runtime-edit targets, including duplicate names selected by source position."""
    selected, evidence = _select_edit_function_sources_with_evidence(
        html, instruction, target_selectors=target_selectors
    )
    return [
        {
            "function": item.name,
            "target_id": f"{item.name}:{item.start}:{item.source_hash[:12]}",
            "source_hash": item.source_hash,
            "source": item.source,
            "start": item.start,
            "end": item.end,
            "line": (html.count("\n", 0, item.start) + 1),
            "evidence": list(evidence.get((item.start, item.end), ())),
        }
        for item in selected
    ]


def extract_named_functions(html: str) -> dict[str, list[FunctionSource]]:
    functions: dict[str, list[FunctionSource]] = {}
    seen_spans: set[tuple[int, int]] = set()
    source_html = html or ""
    for pattern in _FUNCTION_PATTERNS:
        for match in pattern.finditer(source_html):
            opening = source_html.find("{", match.start(), match.end())
            closing = _matching_brace(source_html, opening)
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


def select_edit_function_targets(html: str, instruction: str) -> tuple[str, ...]:
    """Select a bounded set of unique functions for a runtime-focused edit."""
    return tuple(item.name for item in _select_edit_function_sources(html, instruction))


def _select_edit_function_sources(
    html: str,
    instruction: str,
    *,
    target_selectors: tuple[str, ...] = (),
) -> tuple[FunctionSource, ...]:
    selected, _evidence = _select_edit_function_sources_with_evidence(
        html, instruction, target_selectors=target_selectors
    )
    return selected


def _select_edit_function_sources_with_evidence(
    html: str,
    instruction: str,
    *,
    target_selectors: tuple[str, ...] = (),
) -> tuple[tuple[FunctionSource, ...], dict[tuple[int, int], tuple[str, ...]]]:
    functions = extract_named_functions(html)
    text = instruction or ""
    targets: list[FunctionSource] = []
    seen_spans: set[tuple[int, int]] = set()
    selection_evidence: dict[tuple[int, int], list[str]] = {}

    def add(item: FunctionSource, reason: str) -> None:
        span = (item.start, item.end)
        if reason not in selection_evidence.setdefault(span, []):
            selection_evidence[span].append(reason)
        if span not in seen_spans and len(targets) < MAX_FUNCTION_REPLACEMENTS:
            seen_spans.add(span)
            targets.append(item)

    source = html or ""
    all_functions = [item for matches in functions.values() for item in matches]
    for anchor in _runtime_error_anchors(text):
        for match in re.finditer(_dotted_expression_pattern(anchor), source):
            enclosing = [item for item in all_functions if item.start <= match.start() < item.end]
            if enclosing:
                add(min(enclosing, key=lambda item: item.end - item.start), f"runtime_error:{anchor}")

    for name, matches in functions.items():
        if len(matches) == 1 and re.search(rf"(?<![\w$]){re.escape(name)}(?![\w$])", text):
            add(matches[0], "instruction_symbol")
    for selector in target_selectors:
        selector_text = str(selector or "").strip()
        if not selector_text:
            continue
        identifiers = {selector_text}
        if selector_text.startswith("#"):
            identifiers.add(selector_text[1:])
        selector_variables = _top_level_selector_variables(source, selector_text, all_functions)
        for function in all_functions:
            if any(identifier in function.source for identifier in identifiers):
                add(function, f"dom_dependency:{selector_text}")
                continue
            matched_variable = next(
                (
                    variable
                    for variable in selector_variables
                    if re.search(rf"(?<![\w$]){re.escape(variable)}(?![\w$])", function.source)
                ),
                None,
            )
            if matched_variable:
                add(function, f"dom_variable_dependency:{selector_text}:{matched_variable}")

    semantic_slice, semantic_evidence = _runtime_control_slice(source, text, functions)
    for function in semantic_slice:
        add(function, semantic_evidence.get((function.start, function.end), "control_path"))

    if _runtime_actions(text) and not semantic_slice:
        for name in _LEGACY_PLAYBACK_FUNCTION_NAMES:
            matches = functions.get(name, [])
            if len(matches) == 1:
                add(matches[0], "legacy_name_fallback")
    frozen_evidence = {span: tuple(values) for span, values in selection_evidence.items()}
    return tuple(targets[:MAX_FUNCTION_REPLACEMENTS]), frozen_evidence


def _top_level_selector_variables(
    html: str,
    selector: str,
    functions: list[FunctionSource],
) -> tuple[str, ...]:
    """Resolve selector-bound globals and a bounded chain of derived globals.

    Generated widgets commonly bind the main visual once at script scope and
    reference only that variable from build/render functions. Literal-selector
    matching alone cannot connect those functions back to the selected DOM node.
    """
    function_spans = tuple((item.start, item.end) for item in functions)

    def is_top_level(position: int) -> bool:
        return not any(start <= position < end for start, end in function_spans)

    selector_patterns = [
        re.compile(
            r"\b(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*"
            r"document\.querySelector(?:All)?\s*\(\s*(?P<quote>['\"])"
            + re.escape(selector)
            + r"(?P=quote)\s*\)"
        )
    ]
    if selector.startswith("#") and len(selector) > 1:
        selector_patterns.append(
            re.compile(
                r"\b(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*"
                r"document\.getElementById\s*\(\s*(?P<quote>['\"])"
                + re.escape(selector[1:])
                + r"(?P=quote)\s*\)"
            )
        )

    variables: list[str] = []
    for pattern in selector_patterns:
        for match in pattern.finditer(html):
            name = match.group("name")
            if is_top_level(match.start()) and name not in variables:
                variables.append(name)

    declaration_re = re.compile(
        r"\b(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*(?P<value>[^;\n]{1,600})"
    )
    for _depth in range(2):
        added = False
        for match in declaration_re.finditer(html):
            if not is_top_level(match.start()):
                continue
            name = match.group("name")
            value = match.group("value")
            if name in variables or not any(
                re.search(rf"(?<![\w$]){re.escape(variable)}(?![\w$])", value)
                for variable in variables
            ):
                continue
            variables.append(name)
            added = True
        if not added:
            break
    return tuple(variables)


def patch_causal_error(before: str, after: str, instruction: str) -> str | None:
    """Reject a runtime patch when the reported failing call remains unchanged."""
    for anchor in _runtime_error_anchors(instruction):
        pattern = re.compile(_dotted_expression_pattern(anchor) + r"\s*\(")
        before_count = len(pattern.findall(_strip_javascript_comments(before)))
        if before_count and len(pattern.findall(_strip_javascript_comments(after))) >= before_count:
            return f"reported_error_signature_unchanged:{anchor}"
    unresolved = new_unresolved_identifiers(before, after)
    if unresolved:
        return "new_unresolved_identifiers:" + ",".join(unresolved[:8])
    if _runtime_actions(instruction):
        before_functions = extract_named_functions(before)
        control_path, _evidence = _runtime_control_slice(before, instruction, before_functions)
        if control_path:
            after_hashes = {
                item.source_hash
                for matches in extract_named_functions(after).values()
                for item in matches
            }
            if all(item.source_hash in after_hashes for item in control_path):
                return "runtime_control_path_unchanged"
        controller_errors = {
            str(item.get("type") or "")
            for item in check_animation_lifecycle(after).get("errors", [])
            if str(item.get("type") or "").startswith("animation_controller_")
            or item.get("type") == "ephemeral_animation_controller"
        }
        if controller_errors:
            return "controller_contract_errors_remaining:" + ",".join(sorted(controller_errors))
    return None


def _runtime_actions(instruction: str) -> tuple[str, ...]:
    text = instruction or ""
    patterns = {
        "play": r"播放|开始|继续|重播|不动|无响应|没反应|play|start|resume|replay|animation",
        "pause": r"暂停|pause",
        "reset": r"重置|复位|reset|restart",
        "speed": r"速度|倍速|speed|rate",
        "update": r"滑块|拖动|参数|进度|slider|range|input|change|update",
    }
    return tuple(action for action, pattern in patterns.items() if re.search(pattern, text, re.IGNORECASE))


def _runtime_control_slice(
    html: str,
    instruction: str,
    functions: dict[str, list[FunctionSource]],
) -> tuple[tuple[FunctionSource, ...], dict[tuple[int, int], str]]:
    """Build a bounded control-path slice from bindings, runtime actions and calls."""
    actions = set(_runtime_actions(instruction))
    if not actions:
        return (), {}
    unique = {name: matches[0] for name, matches in functions.items() if len(matches) == 1}
    if not unique:
        return (), {}
    dom_vars = _dom_variable_actions(html)
    roots: list[tuple[str, str]] = []

    binding_re = re.compile(
        r"(?P<target>[A-Za-z_$][\w$]*)\s*\.\s*addEventListener\s*\(\s*"
        r"['\"](?P<event>click|input|change)['\"]\s*,\s*(?P<handler>[A-Za-z_$][\w$]*)",
        re.IGNORECASE,
    )
    for match in binding_re.finditer(html):
        target_actions = dom_vars.get(match.group("target"), set())
        event_actions = {"update"} if match.group("event").lower() in {"input", "change"} else target_actions
        if actions & event_actions and match.group("handler") in unique:
            roots.append((match.group("handler"), f"event_binding:{match.group('event').lower()}"))

    property_re = re.compile(
        r"(?P<target>[A-Za-z_$][\w$]*)\s*\.\s*on(?:click|input|change)\s*=\s*(?P<handler>[A-Za-z_$][\w$]*)"
    )
    for match in property_re.finditer(html):
        if actions & dom_vars.get(match.group("target"), set()) and match.group("handler") in unique:
            roots.append((match.group("handler"), "event_property"))

    for action, handler in _runtime_action_handlers(html):
        if action in actions and handler in unique:
            roots.append((handler, f"runtime_action:{action}"))

    for tag in re.finditer(r"<(?P<tag>button|input)\b(?P<attrs>[^>]*)>", html, re.IGNORECASE):
        attrs = tag.group("attrs")
        semantic = _semantic_actions(attrs)
        handler = re.search(r"\bonclick\s*=\s*['\"]\s*([A-Za-z_$][\w$]*)", attrs, re.IGNORECASE)
        if handler and actions & semantic and handler.group(1) in unique:
            roots.append((handler.group(1), "inline_event_binding"))

    if not roots:
        return (), {}

    calls = {
        name: tuple(
            candidate
            for candidate in unique
            if candidate != name
            and re.search(rf"(?<![.\w$]){re.escape(candidate)}\s*\(", item.source)
        )
        for name, item in unique.items()
    }
    ordered: list[FunctionSource] = []
    evidence: dict[tuple[int, int], str] = {}
    queue = list(dict.fromkeys(name for name, _reason in roots))
    root_reasons = {name: reason for name, reason in roots}
    seen: set[str] = set()
    while queue and len(ordered) < MAX_FUNCTION_REPLACEMENTS:
        name = queue.pop(0)
        if name in seen or name not in unique:
            continue
        seen.add(name)
        item = unique[name]
        ordered.append(item)
        evidence[(item.start, item.end)] = root_reasons.get(name, "forward_call_dependency")
        queue.extend(calls.get(name, ()))

    # Include lifecycle siblings that share a selected controller/state helper.
    selected_names = {item.name for item in ordered}
    shared_helpers = {callee for name in selected_names for callee in calls.get(name, ())}
    for helper in shared_helpers:
        for caller, callees in calls.items():
            if len(ordered) >= MAX_FUNCTION_REPLACEMENTS:
                break
            if caller not in selected_names and helper in callees:
                item = unique[caller]
                ordered.append(item)
                selected_names.add(caller)
                evidence[(item.start, item.end)] = f"shared_dependency:{helper}"

    global_state = _top_level_declared_identifiers(html, functions)
    selected_state = {
        state
        for item in ordered
        for state in global_state
        if re.search(rf"(?<![\w$]){re.escape(state)}(?![\w$])", item.source)
    }
    for state in sorted(selected_state):
        for name, item in unique.items():
            if len(ordered) >= MAX_FUNCTION_REPLACEMENTS:
                break
            if name in selected_names:
                continue
            if re.search(rf"(?<![\w$]){re.escape(state)}(?![\w$])", item.source):
                ordered.append(item)
                selected_names.add(name)
                evidence[(item.start, item.end)] = f"shared_state:{state}"
    return tuple(ordered), evidence


def _top_level_declared_identifiers(
    html: str, functions: dict[str, list[FunctionSource]]
) -> set[str]:
    spans = [(item.start, item.end) for matches in functions.values() for item in matches]
    names: set[str] = set()
    for match in re.finditer(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)", html):
        if not any(start <= match.start() < end for start, end in spans):
            names.add(match.group(1))
    return names


def _dom_variable_actions(html: str) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    pattern = re.compile(
        r"\b(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*document\."
        r"(?:getElementById|querySelector)\s*\(\s*['\"](?P<selector>[^'\"]+)['\"]\s*\)"
    )
    for match in pattern.finditer(html):
        selector = match.group("selector")
        actions = _semantic_actions(selector)
        element_id = selector[1:] if selector.startswith("#") else selector
        element = re.search(
            rf"<(?P<tag>button|input|select)\b(?P<attrs>[^>]*\bid\s*=\s*['\"]{re.escape(element_id)}['\"][^>]*)>"
            r"(?P<label>[\s\S]*?)</(?P=tag)>",
            html,
            re.IGNORECASE,
        )
        if element:
            actions.update(_semantic_actions(element.group("attrs") + " " + element.group("label")))
        result[match.group("name")] = actions
    return result


def _semantic_actions(text: str) -> set[str]:
    patterns = {
        "play": r"play|start|resume|replay|播放|开始|继续|重播",
        "pause": r"pause|暂停",
        "reset": r"reset|restart|重置|复位",
        "speed": r"speed|rate|速度|倍速",
        "update": r"slider|range|progress|parameter|input|滑块|进度|参数",
    }
    return {action for action, pattern in patterns.items() if re.search(pattern, text, re.IGNORECASE)}


def _runtime_action_handlers(html: str) -> tuple[tuple[str, str], ...]:
    marker = re.search(r"(?:window\.)?AetherVizRuntime\s*=\s*\{", html)
    if not marker:
        return ()
    opening = html.find("{", marker.start(), marker.end())
    closing = _matching_brace(html, opening)
    if closing is None:
        return ()
    body = html[opening + 1 : closing]
    handlers: list[tuple[str, str]] = []
    for action in ("play", "pause", "reset", "setSpeed", "update"):
        explicit = re.search(rf"\b{re.escape(action)}\s*:\s*([A-Za-z_$][\w$]*)", body)
        shorthand = re.search(rf"(?:^|,)\s*{re.escape(action)}\s*(?=,|$)", body)
        handler = explicit.group(1) if explicit else action if shorthand else None
        if handler:
            handlers.append(("speed" if action == "setSpeed" else action, handler))
    return tuple(handlers)


def _runtime_error_anchors(instruction: str) -> tuple[str, ...]:
    anchors: list[str] = []
    for match in re.finditer(
        r"(?<![\w$])([A-Za-z_$][\w$]*(?:\s*\.\s*[A-Za-z_$][\w$]*)*)\s+is not a function",
        instruction or "",
        re.IGNORECASE,
    ):
        anchor = re.sub(r"\s+", "", match.group(1))
        if anchor not in anchors:
            anchors.append(anchor)
    return tuple(anchors)


def _dotted_expression_pattern(expression: str) -> str:
    return r"\s*\.\s*".join(re.escape(part) for part in expression.split("."))


def _strip_javascript_comments(text: str) -> str:
    """Remove comments while preserving strings well enough for call-signature checks."""
    result: list[str] = []
    quote: str | None = None
    escaped = False
    line_comment = False
    block_comment = False
    index = 0
    while index < len(text):
        char = text[index]
        next_char = text[index + 1] if index + 1 < len(text) else ""
        if line_comment:
            if char in "\r\n":
                line_comment = False
                result.append(char)
            index += 1
            continue
        if block_comment:
            if char == "*" and next_char == "/":
                block_comment = False
                index += 2
            else:
                index += 1
            continue
        if quote:
            result.append(char)
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
        result.append(char)
        if char in {"'", '"', "`"}:
            quote = char
        index += 1
    return "".join(result)


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
