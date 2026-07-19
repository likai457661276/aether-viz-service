"""Small comment-aware helpers for inspecting JavaScript object literals."""

from __future__ import annotations

import re
from dataclasses import dataclass

_IDENTIFIER_RE = re.compile(r"[A-Za-z_$][\w$]*")


@dataclass(frozen=True)
class ObjectProperty:
    """A top-level object-literal property and its source key span."""

    name: str
    start: int
    end: int
    syntax: str
    value_start: int | None
    segment_end: int


def matching_brace(source: str, opening: int) -> int | None:
    """Return the matching closing brace while ignoring JS literals/comments."""
    if opening < 0 or opening >= len(source) or source[opening] != "{":
        return None

    depth = 0
    quote: str | None = None
    escaped = False
    line_comment = False
    block_comment = False
    regex_literal = False
    regex_char_class = False
    index = opening
    while index < len(source):
        char = source[index]
        next_char = source[index + 1] if index + 1 < len(source) else ""
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
        if regex_literal:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == "[":
                regex_char_class = True
            elif char == "]":
                regex_char_class = False
            elif char == "/" and not regex_char_class:
                regex_literal = False
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
        elif char == "/" and _can_start_regex(source, index):
            regex_literal = True
            regex_char_class = False
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return None


def top_level_object_properties(
    source: str,
    opening: int,
    closing: int | None = None,
) -> tuple[ObjectProperty, ...] | None:
    """Read top-level property keys without treating nested commas as separators."""
    closing = matching_brace(source, opening) if closing is None else closing
    if closing is None or closing <= opening:
        return None

    segments: list[tuple[int, int]] = []
    segment_start = opening + 1
    brace_depth = 0
    bracket_depth = 0
    paren_depth = 0
    quote: str | None = None
    escaped = False
    line_comment = False
    block_comment = False
    regex_literal = False
    regex_char_class = False
    index = segment_start
    while index < closing:
        char = source[index]
        next_char = source[index + 1] if index + 1 < closing else ""
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
        if regex_literal:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == "[":
                regex_char_class = True
            elif char == "]":
                regex_char_class = False
            elif char == "/" and not regex_char_class:
                regex_literal = False
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
        elif char == "/" and _can_start_regex(source, index):
            regex_literal = True
            regex_char_class = False
        elif char == "{":
            brace_depth += 1
        elif char == "}":
            brace_depth = max(0, brace_depth - 1)
        elif char == "[":
            bracket_depth += 1
        elif char == "]":
            bracket_depth = max(0, bracket_depth - 1)
        elif char == "(":
            paren_depth += 1
        elif char == ")":
            paren_depth = max(0, paren_depth - 1)
        elif char == "," and brace_depth == bracket_depth == paren_depth == 0:
            segments.append((segment_start, index))
            segment_start = index + 1
        index += 1
    segments.append((segment_start, closing))

    properties = [prop for start, end in segments if (prop := _parse_property(source, start, end)) is not None]
    return tuple(properties)


def _parse_property(source: str, start: int, end: int) -> ObjectProperty | None:
    index = _skip_trivia(source, start, end)
    if index >= end or source.startswith("...", index):
        return None

    key_start = index
    name: str | None = None
    if source[index] in {"'", '"'}:
        quote = source[index]
        key_end = _quoted_end(source, index, end, quote)
        if key_end is None:
            return None
        raw_name = source[index + 1 : key_end - 1]
        if "\\" not in raw_name:
            name = raw_name
        index = key_end
    elif source[index] == "[":
        computed = re.match(r"\[\s*(['\"])([A-Za-z_$][\w$]*)\1\s*\]", source[index:end])
        if not computed:
            return None
        name = computed.group(2)
        index += computed.end()
    else:
        match = _IDENTIFIER_RE.match(source, index, end)
        if not match:
            return None
        name = match.group(0)
        index = match.end()
        if name == "async":
            method_index = _skip_trivia(source, index, end)
            method = _IDENTIFIER_RE.match(source, method_index, end)
            if method:
                name = method.group(0)
                key_start = method.start()
                index = method.end()

    if name is None:
        return None
    key_end = index
    index = _skip_trivia(source, index, end)
    if index >= end:
        syntax = "shorthand"
        value_start = None
    elif source[index] == ":":
        syntax = "property"
        value_start = index + 1
    elif source[index] == "(":
        syntax = "method"
        value_start = index
    else:
        return None
    return ObjectProperty(
        name=name,
        start=key_start,
        end=key_end,
        syntax=syntax,
        value_start=value_start,
        segment_end=end,
    )


def _skip_trivia(source: str, start: int, end: int) -> int:
    index = start
    while index < end:
        if source[index].isspace():
            index += 1
            continue
        if source.startswith("//", index):
            newline = source.find("\n", index + 2, end)
            index = end if newline < 0 else newline + 1
            continue
        if source.startswith("/*", index):
            close = source.find("*/", index + 2, end)
            index = end if close < 0 else close + 2
            continue
        break
    return index


def _quoted_end(source: str, start: int, end: int, quote: str) -> int | None:
    escaped = False
    index = start + 1
    while index < end:
        char = source[index]
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == quote:
            return index + 1
        index += 1
    return None


def _can_start_regex(source: str, index: int) -> bool:
    prefix = source[:index].rstrip()
    if not prefix:
        return True
    if prefix[-1] in "([{=,:;!?&|+-*%^~<>":
        return True
    word = re.search(r"([A-Za-z_$][\w$]*)$", prefix)
    return bool(
        word
        and word.group(1)
        in {"await", "case", "delete", "in", "new", "of", "return", "throw", "typeof", "void", "yield"}
    )
