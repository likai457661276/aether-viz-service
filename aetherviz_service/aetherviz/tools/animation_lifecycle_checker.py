"""Low-cost, topic-independent checks for animation/render lifecycle hazards."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

_FUNCTION_START_RE = re.compile(r"\bfunction\s+([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{")
_FRAME_CALLBACK_RE = re.compile(
    r"(?:onUpdate\s*:\s*(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>\s*\{|"
    r"requestAnimationFrame\s*\(\s*(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>\s*\{)"
)
_STRUCTURAL_MUTATION_RE = re.compile(
    r"\.innerHTML\s*=\s*['\"]{0,2}\s*['\"]{0,2}|\.replaceChildren\s*\(|"
    r"\.createElement(?:NS)?\s*\(|\.appendChild\s*\(|\.removeChild\s*\(",
)
_CALL_RE = re.compile(r"\b([A-Za-z_$][\w$]*)\s*\(")
_IGNORED_CALLS = {"if", "for", "while", "switch", "catch", "function"}


def check_animation_lifecycle(html: str, *, soup: BeautifulSoup | None = None) -> dict:
    parsed = soup or BeautifulSoup(html or "", "html.parser")
    script_text = "\n".join(
        script.get_text("\n", strip=False)
        for script in parsed.find_all("script")
        if not script.get("src") and str(script.get("type", "")).lower() != "application/json"
    )
    errors: list[dict] = []
    warnings: list[dict] = []
    functions = _extract_function_bodies(script_text)

    for callback in _extract_braced_bodies(script_text, _FRAME_CALLBACK_RE):
        risky = []
        if _STRUCTURAL_MUTATION_RE.search(callback):
            risky.append("<inline callback>")
        for name in _CALL_RE.findall(callback):
            if name not in _IGNORED_CALLS and _calls_structural_function(name, functions, set()):
                risky.append(name)
        if risky:
            errors.append(
                _issue(
                    "structural_render_inside_animation_frame",
                    "动画逐帧回调调用了会重建 DOM/SVG 结构的函数："
                    + ", ".join(sorted(set(risky)))
                    + "；应拆分 buildScene 与 applyView，逐帧只更新既有节点属性。",
                )
            )
            break

    registries = set(re.findall(r"\b(?:window\.)?([A-Za-z_$][\w$]*)\.push\s*\(", script_text))
    for registry in sorted(registries):
        reset = re.search(
            rf"(?:window\.)?{re.escape(registry)}\s*=\s*\[\s*\]|"
            rf"(?:window\.)?{re.escape(registry)}\.length\s*=\s*0|"
            rf"(?:window\.)?{re.escape(registry)}\.clear\s*\(",
            script_text,
        )
        if not reset:
            warnings.append(
                _issue(
                    "stale_animation_node_registry",
                    f"动画节点注册表 {registry} 只追加但未在结构重建前清空，可能累积脱离 DOM 的节点。",
                )
            )

    return {
        "ok": not errors,
        "severity": "error" if errors else "warning" if warnings else "info",
        "summary": "动画生命周期检查完成",
        "errors": errors,
        "warnings": warnings,
    }


def _extract_function_bodies(script: str) -> dict[str, str]:
    return {
        match.group(1): body
        for match, body in _matches_with_bodies(script, _FUNCTION_START_RE)
    }


def _extract_braced_bodies(script: str, pattern: re.Pattern[str]) -> list[str]:
    return [body for _, body in _matches_with_bodies(script, pattern)]


def _matches_with_bodies(script: str, pattern: re.Pattern[str]):
    for match in pattern.finditer(script):
        opening = script.find("{", match.start(), match.end())
        if opening < 0:
            continue
        closing = _matching_brace(script, opening)
        if closing is not None:
            yield match, script[opening + 1 : closing]


def _matching_brace(script: str, opening: int) -> int | None:
    depth = 0
    quote = None
    escaped = False
    line_comment = False
    block_comment = False
    index = opening
    while index < len(script):
        char = script[index]
        next_char = script[index + 1] if index + 1 < len(script) else ""
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


def _calls_structural_function(
    name: str,
    functions: dict[str, str],
    visited: set[str],
) -> bool:
    if name in visited or name not in functions:
        return False
    visited.add(name)
    body = functions[name]
    if _STRUCTURAL_MUTATION_RE.search(body):
        return True
    return any(
        called not in _IGNORED_CALLS and _calls_structural_function(called, functions, visited)
        for called in _CALL_RE.findall(body)
    )


def _issue(issue_type: str, message: str) -> dict:
    return {"type": issue_type, "message": message, "line": None}
