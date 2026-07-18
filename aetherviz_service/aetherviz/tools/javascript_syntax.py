"""Inline JavaScript syntax validation helpers."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path


def check_javascript_syntax(script: str) -> str | None:
    node = shutil.which("node")
    if node:
        node_error = _check_javascript_syntax_with_node(node, script)
        if node_error:
            return node_error
        return None
    return _check_javascript_balance(script)


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
    except (OSError, subprocess.SubprocessError, TimeoutError):
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
