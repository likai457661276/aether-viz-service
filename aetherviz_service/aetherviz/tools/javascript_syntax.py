"""Inline JavaScript syntax validation helpers."""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from bs4 import BeautifulSoup, Tag

_JS_KEYWORDS = {
    "async", "await", "break", "case", "catch", "class", "const", "continue", "debugger",
    "default", "delete", "do", "else", "export", "extends", "false", "finally", "for", "from",
    "function", "get", "if", "import", "in", "instanceof", "let", "new", "null", "of", "return",
    "set", "static", "super", "switch", "this", "throw", "true", "try", "typeof", "undefined",
    "var", "void", "while", "with", "yield",
}
_KNOWN_GLOBALS = {
    "Array", "BigInt", "Boolean", "CSS", "CustomEvent", "Date", "Error", "Event", "Infinity",
    "JSON", "Map", "Math", "MutationObserver", "NaN", "Number", "Object", "Promise", "Proxy",
    "RangeError", "RegExp", "ResizeObserver", "Set", "String", "Symbol", "TypeError", "URL",
    "WeakMap", "WeakSet", "cancelAnimationFrame", "clearInterval", "clearTimeout", "console",
    "decodeURIComponent", "document", "encodeURIComponent", "fetch", "isFinite", "isNaN",
    "parseFloat", "parseInt", "performance", "requestAnimationFrame", "setInterval", "setTimeout",
    "structuredClone", "window",
}


def check_javascript_syntax(script: str) -> str | None:
    node = shutil.which("node")
    if node:
        node_error = _check_javascript_syntax_with_node(node, script)
        if node_error:
            return node_error
        return None
    return _check_javascript_balance(script)


def new_unresolved_identifiers(before_html: str, after_html: str) -> tuple[str, ...]:
    """Return identifiers newly referenced without a declaration after a patch.

    This deliberately compares deltas: legacy model HTML can contain browser-provided
    globals that are unknowable statically, while a patch must not introduce new
    implicit state such as ``lastFrameTime`` without declaring it.
    """
    before = _unresolved_identifiers(_inline_scripts(before_html))
    after = _unresolved_identifiers(_inline_scripts(after_html))
    return tuple(sorted(after - before))


def _inline_scripts(html: str) -> str:
    parsed = BeautifulSoup(html or "", "html.parser")
    scripts = [
        node.get_text("\n", strip=False)
        for node in parsed.find_all("script")
        if isinstance(node, Tag) and not node.get("src")
        and str(node.get("type", "")).lower() != "application/json"
    ]
    return "\n;\n".join(scripts)


def _unresolved_identifiers(script: str) -> set[str]:
    source = _strip_js_literals_and_comments(script)
    declared = set(
        re.findall(r"\b(?:const|let|var|class)\s+([A-Za-z_$][\w$]*)", source)
    )
    declared.update(re.findall(r"\bfunction\s+([A-Za-z_$][\w$]*)\s*\(", source))
    for params in re.findall(r"\bfunction(?:\s+[A-Za-z_$][\w$]*)?\s*\(([^)]*)\)", source):
        declared.update(re.findall(r"[A-Za-z_$][\w$]*", params))
    for params in re.findall(
        r"(?<![.\w$])(?:async\s+)?[A-Za-z_$][\w$]*\s*\(([^)]*)\)\s*\{", source
    ):
        declared.update(re.findall(r"[A-Za-z_$][\w$]*", params))
    for params in re.findall(r"(?:\(([^)]*)\)|\b([A-Za-z_$][\w$]*))\s*=>", source):
        declared.update(re.findall(r"[A-Za-z_$][\w$]*", " ".join(params)))
    for params in re.findall(r"\bcatch\s*\(([^)]*)\)", source):
        declared.update(re.findall(r"[A-Za-z_$][\w$]*", params))

    unresolved: set[str] = set()
    for match in re.finditer(r"[A-Za-z_$][\w$]*", source):
        name = match.group(0)
        if name in declared or name in _JS_KEYWORDS or name in _KNOWN_GLOBALS:
            continue
        prefix = source[: match.start()].rstrip()
        suffix = source[match.end() :].lstrip()
        if prefix.endswith(".") or suffix.startswith(":"):
            continue
        unresolved.add(name)
    return unresolved


def _strip_js_literals_and_comments(script: str) -> str:
    """Blank strings/comments while preserving offsets and template expression safety."""
    result = list(script)
    quote: str | None = None
    escaped = False
    line_comment = False
    block_comment = False
    index = 0
    while index < len(script):
        char = script[index]
        next_char = script[index + 1] if index + 1 < len(script) else ""
        if line_comment:
            if char in "\r\n":
                line_comment = False
            else:
                result[index] = " "
            index += 1
            continue
        if block_comment:
            result[index] = " "
            if char == "*" and next_char == "/":
                result[index + 1] = " "
                block_comment = False
                index += 2
            else:
                index += 1
            continue
        if quote:
            result[index] = " "
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            index += 1
            continue
        if char == "/" and next_char == "/":
            result[index] = result[index + 1] = " "
            line_comment = True
            index += 2
            continue
        if char == "/" and next_char == "*":
            result[index] = result[index + 1] = " "
            block_comment = True
            index += 2
            continue
        if char in {"'", '"', "`"}:
            result[index] = " "
            quote = char
        index += 1
    return "".join(result)


def _check_javascript_syntax_with_node(node: str, script: str) -> str | None:
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as temp_file:
            temp_file.write(script)
            temp_path = Path(temp_file.name)
        result = subprocess.run(
            [node, "--check", str(temp_path)],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception:
        return _check_javascript_balance(script)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)

    if result.returncode == 0:
        return None

    output = "\n".join(part.strip() for part in (result.stderr, result.stdout) if part.strip())
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    for line in lines:
        if "SyntaxError" in line:
            return line
    return lines[-1] if lines else "node --check 解析失败"


def _check_javascript_balance(script: str) -> str | None:
    stack: list[tuple[str, int]] = []
    pairs = {"}": "{", ")": "(", "]": "["}
    in_single_quote = False
    in_double_quote = False
    in_template_literal = False
    in_line_comment = False
    in_block_comment = False

    i = 0
    n = len(script)
    while i < n:
        char = script[i]

        if char == "\n":
            in_line_comment = False

        if char == "\\" and (in_single_quote or in_double_quote or in_template_literal):
            i += 2
            continue

        if in_line_comment:
            i += 1
            continue

        if in_block_comment:
            if char == "*" and i + 1 < n and script[i + 1] == "/":
                in_block_comment = False
                i += 2
            else:
                i += 1
            continue

        if in_single_quote:
            if char == "'":
                in_single_quote = False
            i += 1
            continue

        if in_double_quote:
            if char == '"':
                in_double_quote = False
            i += 1
            continue

        if in_template_literal:
            if char == "`":
                in_template_literal = False
            i += 1
            continue

        if char == "/" and i + 1 < n:
            if script[i + 1] == "/":
                in_line_comment = True
                i += 2
                continue
            if script[i + 1] == "*":
                in_block_comment = True
                i += 2
                continue

        if char == "'":
            in_single_quote = True
        elif char == '"':
            in_double_quote = True
        elif char == "`":
            in_template_literal = True
        elif char in "{([":
            stack.append((char, i))
        elif char in pairs:
            if not stack or stack[-1][0] != pairs[char]:
                return f"Unexpected token '{char}' at character {i}"
            stack.pop()

        i += 1

    if in_block_comment:
        return "未闭合的多行注释"
    if in_single_quote or in_double_quote or in_template_literal:
        return "未闭合的字符串或模板字符串"
    if stack:
        opener, position = stack[-1]
        return f"未闭合的 '{opener}' at character {position}"
    return None
