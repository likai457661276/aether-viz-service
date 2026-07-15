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
    business_script_text = "\n".join(
        script.get_text("\n", strip=False)
        for script in parsed.find_all("script")
        if not script.get("src")
        and str(script.get("type", "")).lower() != "application/json"
        and not script.get("data-aetherviz-animation-contract")
        and not script.get("data-aetherviz-control-contract")
    )
    errors: list[dict] = []
    warnings: list[dict] = []
    functions = _extract_function_bodies(script_text)

    for callback in _extract_braced_bodies(script_text, _FRAME_CALLBACK_RE):
        risky: list[tuple[list[str], str]] = []
        inline_mutation = _first_structural_operation(callback)
        if inline_mutation:
            risky.append((["<inline callback>"], inline_mutation))
        for name in _CALL_RE.findall(callback):
            path = _structural_call_path(name, functions, set()) if name not in _IGNORED_CALLS else None
            if path:
                risky.append(path)
        if risky:
            call_chain, operation = min(risky, key=lambda item: (len(item[0]), item[0]))
            errors.append(
                _issue(
                    "structural_render_inside_animation_frame",
                    "动画逐帧回调经调用链 "
                    + " -> ".join(call_chain)
                    + f" 执行结构操作 {operation}；应拆分 buildScene 与 applyView，逐帧只更新既有节点属性。",
                    call_chain=call_chain,
                    operation=operation,
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

    _check_unchecked_node_registries(registries, functions, warnings)
    _check_duplicate_geometry_transform_encoding(script_text, warnings)
    _check_quantized_animation_accumulator(business_script_text, warnings)
    _check_playback_api_effects(business_script_text, warnings)

    return {
        "ok": not errors,
        "severity": "error" if errors else "warning" if warnings else "info",
        "summary": "动画生命周期检查完成",
        "errors": errors,
        "warnings": warnings,
    }


def _check_quantized_animation_accumulator(script_text: str, warnings: list[dict]) -> None:
    """Detect discrete state reused as the next frame's continuous accumulator."""
    quantized_re = re.compile(
        r"(?P<object>[A-Za-z_$][\w$]*)\.(?P<field>[A-Za-z_$][\w$]*)\s*=\s*"
        r"Math\.(?:floor|round|ceil|trunc)\s*\(\s*(?P<next>[A-Za-z_$][\w$]*)\s*\)"
    )
    for match in quantized_re.finditer(script_text):
        source_re = re.compile(
            rf"(?:const|let|var)\s+{re.escape(match.group('next'))}\s*=\s*"
            rf"{re.escape(match.group('object'))}\.{re.escape(match.group('field'))}\s*[+-]"
        )
        if not source_re.search(script_text[: match.start()]):
            continue
        warnings.append(
            _issue(
                "quantized_animation_accumulator",
                f"动画把离散化后的 {match.group('object')}.{match.group('field')} 作为下一帧累加起点；"
                "小于一个整数步长的逐帧增量会被反复丢弃，导致播放循环运行但画面不变化。"
                "应保留独立连续 progress/elapsed/accumulator，仅在渲染时量化显示值。",
                state_field=f"{match.group('object')}.{match.group('field')}",
            )
        )
        return


def _check_playback_api_effects(script_text: str, warnings: list[dict]) -> None:
    functions = _extract_function_bodies(script_text)
    set_speed = functions.get("setSpeed")
    if set_speed is not None:
        meaningful = bool(
            re.search(r"(?:\.setSpeed\s*\(|\.timeScale\s*\(|\bspeed\s*=|\bplaybackRate\s*=)", set_speed)
        )
        if not meaningful:
            warnings.append(
                _issue(
                    "no_op_set_speed",
                    "setSpeed 未改变 controller、timeline、playbackRate 或动画速度状态，速度控件不会生效。",
                )
            )
    if re.search(r"requestAnimationFrame\s*\(", script_text) and "AetherVizAnimationController" not in script_text:
        warnings.append(
            _issue(
                "animation_controller_bypass",
                "业务脚本自行维护 requestAnimationFrame 时间源，未复用 AetherVizAnimationController；"
                "play/pause/reset/replay/setSpeed 语义容易分叉。",
            )
        )


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


def _structural_call_path(
    name: str,
    functions: dict[str, str],
    visited: set[str],
) -> tuple[list[str], str] | None:
    if name in visited or name not in functions:
        return None
    visited = {*visited, name}
    body = functions[name]
    operation = _first_structural_operation(body)
    if operation:
        return [name], operation
    for called in _CALL_RE.findall(body):
        if called in _IGNORED_CALLS:
            continue
        nested = _structural_call_path(called, functions, visited)
        if nested:
            path, operation = nested
            return [name, *path], operation
    return None


def _first_structural_operation(body: str) -> str | None:
    match = _STRUCTURAL_MUTATION_RE.search(body)
    if not match:
        return None
    token = match.group(0)
    for operation in ("innerHTML", "replaceChildren", "createElementNS", "createElement", "appendChild", "removeChild"):
        if operation in token:
            return operation
    return token.strip()


def _check_unchecked_node_registries(
    registries: set[str],
    functions: dict[str, str],
    warnings: list[dict],
) -> None:
    """Detect unchecked DOM-node array indexing after dynamic scene rebuilds.

    Generated animations often rebuild arrays with ``push`` while deriving loop
    bounds from separate state. Directly dereferencing ``nodes[i]`` without a
    guard makes parameter changes and resets fragile when those counts diverge.
    """
    for registry in sorted(registries):
        for function_name, body in functions.items():
            declaration_re = re.compile(
                rf"(?:const|let|var)\s+(?P<ref>[A-Za-z_$][\w$]*)\s*=\s*"
                rf"(?:window\.)?{re.escape(registry)}\s*\[\s*(?P<index>[A-Za-z_$][\w$]*)\s*\]\s*;"
            )
            for match in declaration_re.finditer(body):
                ref = match.group("ref")
                remaining = body[match.end() :]
                dereferenced = re.search(
                    rf"\b{re.escape(ref)}\s*\.\s*(?:setAttribute|remove|appendChild|classList|style)\b",
                    remaining,
                )
                if not dereferenced:
                    continue
                guard_region = remaining[: dereferenced.start()]
                guarded = re.search(
                    rf"if\s*\(\s*(?:!\s*{re.escape(ref)}|{re.escape(ref)}\s*(?:instanceof\s+Node|[!=]==?\s*null)?)\s*\)",
                    guard_region,
                )
                if guarded:
                    continue
                warnings.append(
                    _issue(
                        "unchecked_animation_node_registry",
                        f"动画函数 {function_name} 直接使用动态节点表 {registry}[{match.group('index')}]，"
                        "未校验节点存在或让循环边界来自注册表长度；参数重建后可能访问 undefined。",
                    )
                )
                return


def _check_duplicate_geometry_transform_encoding(
    script_text: str,
    warnings: list[dict],
) -> None:
    """Detect world-angle geometry that is rotated by the same index again.

    A reusable transformable shape should be authored in local coordinates. If
    its points already use an index-derived angle and render later applies a
    rotation derived from the same index/step, the initial layout fans out or
    rotates twice. This data-flow warning is independent of any teaching topic.
    """
    angle_assignment_re = re.compile(
        r"(?:const|let|var)\s+(?P<angle>[A-Za-z_$][\w$]*)\s*=\s*"
        r"(?:\(?\s*(?P<index>[A-Za-z_$][\w$]*)\s*(?:\+\s*1)?\s*\)?)\s*\*\s*"
        r"(?P<step>[A-Za-z_$][\w$]*)\s*;"
    )
    for match in angle_assignment_re.finditer(script_text):
        angle = match.group("angle")
        index = match.group("index")
        step = match.group("step")
        if not re.search(rf"Math\.(?:cos|sin)\s*\(\s*{re.escape(angle)}\s*\)", script_text):
            continue
        rotation_assignments = re.finditer(
            rf"(?:const|let|var)\s+(?P<rotation>[A-Za-z_$][\w$]*)\s*=\s*"
            rf"[^;\n]*\b{re.escape(index)}\b[^;\n]*\b{re.escape(step)}\b[^;\n]*;",
            script_text,
        )
        duplicated = False
        for rotation_assignment in rotation_assignments:
            rotation = rotation_assignment.group("rotation")
            rotation_values = {rotation}
            rotation_values.update(
                alias
                for alias in re.findall(
                    rf"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*"
                    rf"[^;\n]*\b{re.escape(rotation)}\b[^;\n]*;",
                    script_text,
                )
            )
            if any(
                re.search(
                    rf"(?:setAttribute\s*\(\s*['\"]transform['\"]|\.transform\s*=)"
                    rf"[\s\S]{{0,500}}?rotate\s*\([^)]*\$\{{[^}}]*\b{re.escape(value)}\b",
                    script_text,
                    re.IGNORECASE,
                )
                for value in rotation_values
            ):
                duplicated = True
                break
        if not duplicated:
            continue
        warnings.append(
            _issue(
                "duplicate_geometry_transform_encoding",
                f"几何点已使用 {index}×{step} 编码世界方向，transform 又通过 {rotation} 应用同源旋转；"
                "应在统一局部坐标生成一次基础几何，仅由 transform 表达各状态位置和方向。",
            )
        )
        return


def _issue(issue_type: str, message: str, **details: object) -> dict:
    return {"type": issue_type, "message": message, "line": None, **details}
