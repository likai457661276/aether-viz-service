"""Low-cost runtime contract checks for generated interactive HTML."""

from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup

REQUIRED_CONTROL_IDS = ("play-animation", "pause-animation", "reset-animation")
REQUIRED_RUNTIME_METHODS = ("play", "pause", "reset", "update", "getState")
REQUIRED_WIDGET_ACTIONS = (
    "SET_WIDGET_STATE",
    "HIGHLIGHT_ELEMENT",
    "ANNOTATE_ELEMENT",
    "REVEAL_ELEMENT",
)
ALLOWED_WIDGET_TYPES = {"simulation", "diagram", "game"}

_SET_ATTR_COORD_RE = re.compile(
    r"([A-Za-z_$][\w.$]*)\.setAttribute\(\s*['\"](x|y)['\"]\s*,\s*([^)]+?)\s*\)"
)


def check_widget_runtime_contract(html: str, *, soup: BeautifulSoup | None = None) -> dict:
    parsed = soup or BeautifulSoup(html or "", "html.parser")
    errors: list[dict] = []
    warnings: list[dict] = []

    _check_widget_config(parsed, errors)
    _check_stage(parsed, errors)
    _check_controls(parsed, errors)

    script_text = "\n".join(
        script.get_text("\n", strip=False)
        for script in parsed.find_all("script")
        if not script.get("src") and str(script.get("type", "")).lower() != "application/json"
    )
    if not re.search(r"\bAetherVizRuntime\s*=", script_text):
        errors.append(_error("missing_runtime", "缺少 window.AetherVizRuntime 运行时对象"))
    else:
        for method in REQUIRED_RUNTIME_METHODS:
            if not re.search(rf"\b{re.escape(method)}\b", script_text):
                errors.append(_error("missing_runtime_method", f"AetherVizRuntime 缺少 {method} 方法"))

    if not re.search(r"__AETHERVIZ_RUNTIME_READY__\s*=\s*true", script_text):
        errors.append(_error("missing_runtime_ready", "缺少运行时就绪标记"))
    if not re.search(r"addEventListener\s*\(\s*['\"]message['\"]", script_text):
        errors.append(_error("missing_message_listener", "缺少 iframe widget action 消息监听器"))

    for action in REQUIRED_WIDGET_ACTIONS:
        if action not in script_text:
            warnings.append(_warning("missing_widget_action", f"未显式处理 widget action：{action}"))

    _check_duplicate_label_positions(parsed, script_text, warnings)
    _check_layout_risks(parsed, script_text, warnings)

    external_gsap = any("gsap" in str(script.get("src") or "").lower() for script in parsed.find_all("script"))
    if external_gsap and not re.search(r"window\.gsap|typeof\s+gsap|typeof\s+window\.gsap", script_text):
        warnings.append(_warning("missing_gsap_fallback_guard", "使用 GSAP CDN，但未检测到 native fallback 判断"))
    if external_gsap and _has_call_only_gsap_timeline(script_text):
        warnings.append(
            _warning(
                "call_only_gsap_timeline",
                "GSAP timeline 仅检测到零时长 call，分镜可能在同一时刻瞬间执行",
            )
        )

    return {
        "ok": not errors,
        "severity": "error" if errors else "warning" if warnings else "info",
        "summary": "Widget 最小运行契约检查完成",
        "errors": errors,
        "warnings": warnings,
    }


def _check_layout_risks(parsed: BeautifulSoup, script_text: str, warnings: list[dict]) -> None:
    """Detect common responsive-layout risks without rendering the page.

    These checks deliberately remain warnings: they are cheap production signals
    and must not trigger the model repair loop or reject otherwise usable HTML.
    """
    style_text = "\n".join(style.get_text("\n", strip=False) for style in parsed.find_all("style"))

    for match in re.finditer(r"grid-template-columns\s*:\s*([^;}]+)", style_text, re.IGNORECASE):
        columns = match.group(1)
        fixed_px_columns = re.findall(r"(?:^|\s)\d+(?:\.\d+)?px(?=\s|$)", columns)
        if len(fixed_px_columns) >= 2 and re.search(r"\b(?:\d+(?:\.\d+)?fr|minmax\s*\()", columns):
            warnings.append(
                _warning(
                    "fixed_sidebar_layout",
                    "检测到两个以上固定像素列夹住弹性列，窄 iframe 中可能挤压主舞台；应使用自适应列或在空间不足时堆叠辅助区。",
                )
            )
            break

    uses_grid_shell = bool(re.search(r"grid-template-(?:columns|rows)\s*:", style_text, re.IGNORECASE))
    stage_blocks = re.findall(r"[^{}]*#aetherviz-stage[^{}]*\{([^{}]*)\}", style_text, re.IGNORECASE)
    stage_css = "\n".join(stage_blocks)
    if uses_grid_shell and stage_css:
        has_min_width_guard = bool(re.search(r"min-width\s*:\s*0(?:px|rem|em|%)?\b", stage_css, re.IGNORECASE))
        has_min_height_guard = bool(re.search(r"min-height\s*:\s*0(?:px|rem|em|%)?\b", stage_css, re.IGNORECASE))
        if not (has_min_width_guard and has_min_height_guard):
            warnings.append(
                _warning(
                    "missing_stage_shrink_guard",
                    "Grid/Flex 主舞台未同时声明 min-width:0 和 min-height:0，内容可能撑开网格并造成裁切。",
                )
            )

    stage = parsed.find(id="aetherviz-stage")
    svg = stage.find("svg") if stage is not None else None
    has_variable_control = parsed.find("input", attrs={"type": re.compile(r"^range$", re.IGNORECASE)}) is not None
    redraws_svg = bool(
        re.search(r"\.innerHTML\s*=|setAttribute\s*\(\s*['\"](?:d|points|x|y|cx|cy|r)['\"]", script_text)
    )
    updates_viewbox = bool(
        re.search(r"getBBox\s*\(|ResizeObserver\b|setAttribute\s*\(\s*['\"]viewBox['\"]", script_text)
    )
    if svg is not None and svg.get("viewbox") and has_variable_control and redraws_svg and not updates_viewbox:
        warnings.append(
            _warning(
                "static_viewbox_for_variable_svg",
                "可调参数会改变 SVG 图形，但未检测到基于内容包围盒或容器尺寸更新 viewBox 的逻辑，极值状态可能偏心或裁切。",
            )
        )


def _has_call_only_gsap_timeline(script_text: str) -> bool:
    has_timeline = bool(re.search(r"(?:window\.)?gsap\.timeline\s*\(", script_text))
    has_call = bool(re.search(r"\.call\s*\(", script_text))
    has_duration_tween = bool(re.search(r"\.(?:to|from|fromTo)\s*\(", script_text))
    has_positioned_call = bool(
        re.search(
            r"\.call\s*\([^;]*?,\s*(?:null|\[[^\]]*\])\s*,\s*(?:['\"]|[0-9])",
            script_text,
        )
    )
    return has_timeline and has_call and not has_duration_tween and not has_positioned_call


def _check_duplicate_label_positions(
    parsed: BeautifulSoup, script_text: str, warnings: list[dict]
) -> None:
    """Warn when two different text labels resolve to the exact same coordinates.

    覆盖两种常见情况：模板里直接写死的静态 x/y 属性，以及运行时通过
    `element.setAttribute('x'/'y', expr)` 用相同表达式驱动多个元素坐标
    （典型场景：变量标签与其面积/数值标签被复制成同一组坐标，导致文字互相
    覆盖）。只作为 warning，不阻断生成/修复/编辑流程。
    """
    coords_by_ref: dict[str, dict[str, str]] = {}
    for ref, axis, expr in _SET_ATTR_COORD_RE.findall(script_text):
        coords_by_ref.setdefault(ref, {})[axis] = re.sub(r"\s+", "", expr)

    dynamic_groups: dict[tuple[str, str], set[str]] = {}
    for ref, axes in coords_by_ref.items():
        x_expr, y_expr = axes.get("x"), axes.get("y")
        if x_expr is None or y_expr is None:
            continue
        dynamic_groups.setdefault((x_expr, y_expr), set()).add(ref)

    for (x_expr, y_expr), refs in dynamic_groups.items():
        if len(refs) > 1:
            warnings.append(
                _warning(
                    "duplicate_label_position",
                    "检测到多个元素通过相同坐标表达式设置位置（x="
                    f"{x_expr}, y={y_expr}），可能导致文本标签互相重叠："
                    f"{', '.join(sorted(refs))}",
                )
            )

    static_groups: dict[tuple[str, str], set[str]] = {}
    for text_el in parsed.find_all(["text", "tspan"]):
        x, y = text_el.get("x"), text_el.get("y")
        if x is None or y is None:
            continue
        label = text_el.get("id") or text_el.get("class") or text_el.get_text(strip=True)[:12] or "text"
        static_groups.setdefault((str(x).strip(), str(y).strip()), set()).add(str(label))

    for (x, y), labels in static_groups.items():
        if len(labels) > 1:
            warnings.append(
                _warning(
                    "duplicate_label_position",
                    f"检测到多个静态文本标签使用完全相同坐标 (x={x}, y={y})，可能互相重叠："
                    f"{', '.join(sorted(labels))}",
                )
            )


def _check_widget_config(parsed: BeautifulSoup, errors: list[dict]) -> None:
    config = parsed.find("script", id="widget-config")
    if config is None or str(config.get("type") or "").lower() != "application/json":
        errors.append(_error("missing_widget_config", "缺少 script#widget-config[type=application/json]"))
        return
    try:
        payload = json.loads(config.get_text(strip=False))
    except (TypeError, ValueError):
        errors.append(_error("invalid_widget_config", "widget-config 不是有效 JSON"))
        return
    if not isinstance(payload, dict) or payload.get("type") not in ALLOWED_WIDGET_TYPES:
        errors.append(_error("invalid_widget_type", "widget-config.type 必须是 simulation、diagram 或 game"))


def _check_stage(parsed: BeautifulSoup, errors: list[dict]) -> None:
    stage = parsed.find(id="aetherviz-stage")
    if stage is None:
        errors.append(_error("missing_stage", "缺少 #aetherviz-stage 主舞台"))
        return
    if stage.find(["svg", "canvas"]) is None and stage.select_one("[data-role='main-visual']") is None:
        errors.append(_error("missing_stage_visual", "主舞台缺少 SVG、Canvas 或 main-visual 主体"))


def _check_controls(parsed: BeautifulSoup, errors: list[dict]) -> None:
    for control_id in REQUIRED_CONTROL_IDS:
        if parsed.find(id=control_id) is None:
            errors.append(_error("missing_control", f"缺少核心控件 #{control_id}"))


def _error(error_type: str, message: str) -> dict:
    return {"type": error_type, "message": message, "line": None}


def _warning(warning_type: str, message: str) -> dict:
    return {"type": warning_type, "message": message, "line": None}
