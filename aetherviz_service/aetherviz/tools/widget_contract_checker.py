"""Low-cost runtime contract checks for generated interactive HTML."""

from __future__ import annotations

import json
import math
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
SVG_GEOMETRY_TAGS = {"circle", "ellipse", "line", "polygon", "polyline", "rect"}

_SET_ATTR_COORD_RE = re.compile(
    r"([A-Za-z_$][\w.$]*)\.setAttribute\(\s*['\"](x|y)['\"]\s*,\s*([^)]+?)\s*\)"
)
_VISIBLE_TEMPLATE_ASSIGNMENT_RE = re.compile(
    r"\.(?:textContent|innerText|innerHTML)\s*=\s*`([^`]*)`"
)
_VISIBLE_TEXT_NAME_RE = re.compile(
    r"\b(?:latex|formula|caption|label|readout|display(?:Value|Text)?|hud(?:Value|Text)?)\b\s*=\s*`([^`]*)`",
    re.IGNORECASE,
)
_RAW_TEMPLATE_VALUE_RE = re.compile(
    r"\$\{\s*(?!formatValue\s*\(|formatDisplayValue\s*\(|display\b)"
    r"((?:state|STATE|proxy|model|vars?)\.[A-Za-z_$][\w$]*)\s*\}"
)
_RAW_VISIBLE_ASSIGNMENT_RE = re.compile(
    r"\.(?:textContent|innerText|innerHTML)\s*=\s*"
    r"((?:state|STATE|proxy|model|vars?)\.[A-Za-z_$][\w$]*)\s*;"
)
_STAGE_LOOKUP_RE = re.compile(
    r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*document\."
    r"(?:getElementById\(\s*['\"]aetherviz-stage['\"]\s*\)|"
    r"querySelector\(\s*['\"]#aetherviz-stage['\"]\s*\))"
)
_JS_IDENTIFIER = r"[A-Za-z_$][\w$]*"
_JS_MEMBER = rf"{_JS_IDENTIFIER}(?:\s*\.\s*{_JS_IDENTIFIER}|\s*\[\s*['\"]{_JS_IDENTIFIER}['\"]\s*\])*"
_MAIN_VISUAL_QUERY = (
    r"(?:document|" + _JS_MEMBER + r")\.querySelector\(\s*"
    r"['\"]\[data-role=(?:\\?['\"])?main-visual(?:\\?['\"])?\]['\"]\s*\)"
)
_MAIN_VISUAL_ASSIGNMENT_RE = re.compile(
    rf"(?:const|let|var)?\s*(?P<target>{_JS_MEMBER})\s*=\s*{_MAIN_VISUAL_QUERY}"
)
_OBJECT_DECLARATION_RE = re.compile(
    rf"(?:const|let|var)\s+(?P<base>{_JS_IDENTIFIER})\s*=\s*\{{(?P<body>[\s\S]{{0,5000}}?)\}}\s*;"
)
_MAIN_VISUAL_OBJECT_PROPERTY_RE = re.compile(
    rf"(?P<property>{_JS_IDENTIFIER}|['\"]{_JS_IDENTIFIER}['\"])\s*:\s*{_MAIN_VISUAL_QUERY}"
)
_VISUAL_CREATION_RE = re.compile(
    rf"(?:const|let|var)?\s*(?P<target>{_JS_MEMBER})\s*=\s*document\.createElement(?:NS)?\("
    r"(?:\s*[^,]+,)?\s*['\"](svg|canvas)['\"]\s*\)",
    re.IGNORECASE,
)


def check_widget_runtime_contract(html: str, *, soup: BeautifulSoup | None = None) -> dict:
    parsed = soup or BeautifulSoup(html or "", "html.parser")
    errors: list[dict] = []
    warnings: list[dict] = []

    script_text = "\n".join(
        script.get_text("\n", strip=False)
        for script in parsed.find_all("script")
        if not script.get("src") and str(script.get("type", "")).lower() != "application/json"
    )
    _check_widget_config(parsed, errors)
    _check_stage(parsed, script_text, errors, warnings)
    _check_controls(parsed, errors)
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

    _check_append_child_arguments(script_text, errors)
    _check_duplicate_label_positions(parsed, script_text, warnings)
    _check_layout_risks(parsed, script_text, warnings)
    _check_svg_unit_system(parsed, script_text, warnings)
    _check_unformatted_dynamic_numbers(script_text, warnings)

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

    external_katex = any(
        "katex" in str(tag.get("src") or tag.get("href") or "").lower()
        for tag in parsed.find_all(["script", "link"])
    )
    if external_katex and not re.search(r"window\.katex|typeof\s+katex|typeof\s+window\.katex", script_text):
        warnings.append(_warning("missing_katex_fallback_guard", "加载 KaTeX，但未检测到 window.katex 守卫和纯文本 fallback"))
    has_formula_region = parsed.select_one('[data-region="formula"], .formula, .katex-target') is not None
    if external_katex and not has_formula_region:
        warnings.append(_warning("unused_katex_runtime", "页面未检测到公式区域，不应加载 KaTeX"))

    return {
        "ok": not errors,
        "severity": "error" if errors else "warning" if warnings else "info",
        "summary": "Widget 最小运行契约检查完成",
        "errors": errors,
        "warnings": warnings,
    }


_NUMERIC_CONST_RE = re.compile(
    r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(-?\d+(?:\.\d+)?)\s*;"
)
_VIEWBOX_LITERAL_RE = re.compile(
    r"(?:viewBox\s*=\s*['\"]|setAttribute\(\s*['\"]viewBox['\"]\s*,\s*['\"])([^'\"]+)"
)


def _viewbox_short_sides(parsed: BeautifulSoup, script_text: str) -> list[float]:
    """Return statically provable SVG viewBox short sides.

    Besides literal markup/JS values, support the common generic form
    ```${-SIZE/2} ${-SIZE/2} ${SIZE} ${SIZE}```. This is deliberately a small
    expression recognizer rather than a JavaScript evaluator.
    """
    values: list[float] = []
    for svg in parsed.find_all("svg"):
        raw = str(svg.get("viewbox") or "")
        numbers = re.findall(r"-?\d+(?:\.\d+)?", raw)
        if len(numbers) == 4:
            width, height = abs(float(numbers[2])), abs(float(numbers[3]))
            if width and height:
                values.append(min(width, height))
    for raw in _VIEWBOX_LITERAL_RE.findall(script_text):
        numbers = re.findall(r"-?\d+(?:\.\d+)?", raw)
        if len(numbers) == 4:
            width, height = abs(float(numbers[2])), abs(float(numbers[3]))
            if width and height:
                values.append(min(width, height))
    constants = {name: abs(float(value)) for name, value in _NUMERIC_CONST_RE.findall(script_text)}
    for template in re.findall(
        r"setAttribute\(\s*['\"]viewBox['\"]\s*,\s*`([^`]+)`\s*\)", script_text
    ):
        expressions = re.findall(r"\$\{\s*([^}]+)\s*\}", template)
        if len(expressions) != 4:
            continue
        resolved: list[float] = []
        for expression in expressions:
            match = re.fullmatch(r"(-)?([A-Za-z_$][\w$]*)(?:\s*/\s*(\d+(?:\.\d+)?))?", expression.strip())
            if not match or match.group(2) not in constants:
                break
            value = constants[match.group(2)] / float(match.group(3) or 1)
            resolved.append(-value if match.group(1) else value)
        if len(resolved) == 4 and resolved[2] and resolved[3]:
            values.append(min(abs(resolved[2]), abs(resolved[3])))
    return values


def _check_svg_unit_system(parsed: BeautifulSoup, script_text: str, warnings: list[dict]) -> None:
    """Detect mixed screen-pixel and abstract SVG user-unit styling.

    The check is topic-independent and remains non-blocking because static CSS
    cannot prove the final browser geometry in every generated document.
    """
    if parsed.select_one('script[data-aetherviz-scale-guard="true"]') is not None:
        return
    short_sides = _viewbox_short_sides(parsed, script_text)
    if not short_sides or min(short_sides) > 100:
        return
    style_text = "\n".join(style.get_text("\n", strip=False) for style in parsed.find_all("style"))
    svg_rules = [
        (selector, declarations)
        for selector, declarations in re.findall(r"([^{}]+)\{([^{}]*)\}", style_text)
        if re.search(r"(?:svg|text|axis|grid|curve|line|path|vertex|label|tick)", selector, re.IGNORECASE)
    ]
    text_px = any(
        re.search(r"(?:text|label|tick)", selector, re.IGNORECASE)
        and re.search(r"font-size\s*:\s*(?:[1-9]\d*(?:\.\d+)?)px", declarations, re.IGNORECASE)
        for selector, declarations in svg_rules
    )
    scaling_stroke = any(
        re.search(r"stroke-width\s*:\s*(\d+(?:\.\d+)?)\s*(?:;|$)", declarations, re.IGNORECASE)
        and not re.search(r"vector-effect\s*:\s*non-scaling-stroke", declarations, re.IGNORECASE)
        for _, declarations in svg_rules
    )
    if text_px:
        warnings.append(
            _warning(
                "abstract_svg_text_scale_risk",
                "检测到小范围抽象 viewBox 与 SVG px 字号混用；文字会随坐标系缩放而异常放大。"
                "应使用 getScreenCTM() 反算用户单位字号，或改用 CSS 像素对齐 viewBox。",
            )
        )
    if scaling_stroke:
        warnings.append(
            _warning(
                "abstract_svg_stroke_scale_risk",
                "检测到小范围抽象 viewBox 中存在未使用 non-scaling-stroke 的描边；轴线、网格或轮廓可能异常粗大。",
            )
        )
    if text_px and scaling_stroke:
        warnings.append(
            _warning(
                "mixed_svg_unit_system",
                "SVG 同时混用屏幕像素排版与抽象用户单位描边，视觉尺度在不同 iframe 尺寸下不稳定。",
            )
        )


_APPEND_CHILD_OPEN_RE = re.compile(r"\.appendChild\s*\(")
_LITERAL_START_RE = re.compile(r"^['\"`\d]")
_TOP_LEVEL_ASSIGN_RE = re.compile(r"(?<![=!<>+\-*/%&|^])=(?![=>])")


def _check_append_child_arguments(script_text: str, errors: list[dict]) -> None:
    """Reject appendChild calls whose argument cannot evaluate to a Node.

    Assignment expressions evaluate to the assigned value; when that value is a
    string/number/template literal (e.g. `parent.appendChild(el.textContent = "x")`)
    the call throws `parameter 1 is not of type 'Node'` at runtime. Static
    validators cannot execute JS, but this expression shape is deterministically
    broken regardless of topic, so it is treated as a hard error.
    """
    for match in _APPEND_CHILD_OPEN_RE.finditer(script_text):
        argument = _extract_balanced_argument(script_text, match.end())
        if argument is None:
            continue
        stripped = argument.strip()
        if not stripped:
            continue
        broken = False
        if _LITERAL_START_RE.match(stripped):
            broken = True
        else:
            assign = _find_top_level_assignment(stripped)
            if assign is not None:
                rhs = stripped[assign + 1 :].strip()
                if _LITERAL_START_RE.match(rhs):
                    broken = True
        if broken:
            snippet = re.sub(r"\s+", " ", stripped)[:120]
            errors.append(
                _error(
                    "non_node_append_child",
                    f"appendChild 参数表达式求值结果不是 Node，运行时必然抛错：appendChild({snippet})",
                )
            )


def _extract_balanced_argument(text: str, start: int) -> str | None:
    depth = 1
    quote: str | None = None
    index = start
    while index < len(text):
        char = text[index]
        if quote is not None:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                quote = None
        elif char in "'\"`":
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return text[start:index]
        index += 1
    return None


def _find_top_level_assignment(argument: str) -> int | None:
    depth = 0
    quote: str | None = None
    index = 0
    while index < len(argument):
        char = argument[index]
        if quote is not None:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                quote = None
        elif char in "'\"`":
            quote = char
        elif char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif char == "=" and depth == 0:
            prev_char = argument[index - 1] if index else ""
            next_char = argument[index + 1] if index + 1 < len(argument) else ""
            if prev_char not in "=!<>+-*/%&|^" and next_char not in "=>":
                return index
        index += 1
    return None


def _check_unformatted_dynamic_numbers(script_text: str, warnings: list[dict]) -> None:
    """Warn when a bare runtime value is interpolated into visible text.

    Animation libraries commonly produce long binary floating-point intermediates.
    Bare template interpolation leaks those values into labels, while an explicit
    formatter (toFixed/Intl.NumberFormat/project helper) keeps rendering stable.
    This remains a warning because a bare identifier can also hold non-numeric text.
    """
    visible_templates = [
        *_VISIBLE_TEMPLATE_ASSIGNMENT_RE.findall(script_text),
        *_VISIBLE_TEXT_NAME_RE.findall(script_text),
    ]
    raw_template_values = sorted(
        {
            value
            for template in visible_templates
            for value in _RAW_TEMPLATE_VALUE_RE.findall(template)
        }
    )
    raw_assignments = _RAW_VISIBLE_ASSIGNMENT_RE.findall(script_text)
    all_bare_values = sorted(set(raw_template_values) | set(raw_assignments))
    if all_bare_values:
        warnings.append(
            _warning(
                "unformatted_dynamic_value",
                "检测到可见文本或公式直接插入未格式化的运行时值，动画插值可能显示过长小数；"
                "请统一通过描述符驱动的 display state 输出："
                + ", ".join(all_bare_values[:8]),
            )
        )

    formatter = re.search(
        r"function\s+(?:formatValue|formatDisplayValue)\s*\(\s*[^,)]*\s*(?:,\s*([^)=,]+))?",
        script_text,
    )
    if formatter and not formatter.group(1):
        warnings.append(
            _warning(
                "missing_numeric_descriptor",
                "数值格式化函数没有 descriptor 参数，无法按不同变量步长、单位和派生量精度稳定展示。",
            )
        )
    elif formatter:
        descriptor_name = formatter.group(1).strip()
        if not re.search(r"(?:descriptor|desc|meta|options?|config)", descriptor_name, re.IGNORECASE):
            warnings.append(
                _warning(
                    "missing_numeric_descriptor",
                    "数值格式化函数的第二参数不是描述符对象，可能把所有变量错误套用同一精度。",
                )
            )

    formatter_body = re.search(
        r"function\s+(?:formatValue|formatDisplayValue)\s*\([^)]*\)\s*\{([\s\S]{0,1200}?)\n?\}",
        script_text,
    )
    if formatter_body and re.search(
        r"\b(?:const|let|var)\s+step\s*=\s*\d+(?:\.\d+)?\s*;", formatter_body.group(1)
    ):
        warnings.append(
            _warning(
                "hardcoded_numeric_step",
                "数值格式化函数内部写死统一 step，输入变量和派生量会被错误量化；应从 descriptor 读取。",
            )
        )

    if re.search(r"function\s+(?:formatValue|formatDisplayValue)\b", script_text):
        visible_precision_re = re.compile(
            r"(?:textContent|innerText|innerHTML|createLabel|katex\.render|formula|latex|hud|caption|label|readout)"
            r"[^;\n]{0,300}\.toFixed\s*\(",
            re.IGNORECASE,
        )
        scattered_precision = len(visible_precision_re.findall(script_text))
        if scattered_precision >= 2:
            warnings.append(
                _warning(
                    "scattered_visible_precision",
                    "已定义统一格式化函数，但仍检测到多处散落的 toFixed；公式、HUD 和标签可能绕过统一 display state。",
                )
            )


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
    if svg is not None:
        _check_static_svg_viewbox_alignment(svg, warnings)
    has_variable_control = parsed.find("input", attrs={"type": re.compile(r"^range$", re.IGNORECASE)}) is not None
    # Structural mutation means the content envelope cannot be known from the
    # authored markup, so a fixed viewBox may crop unseen content. Attribute-only
    # redraws of pre-declared elements stay within a designable worst-case
    # envelope and a static viewBox is the *preferred* stable solution there.
    mutates_svg_structure = bool(
        re.search(
            r"createElementNS\s*\([^,]+,\s*['\"](?:circle|ellipse|line|path|polygon|polyline|rect|use)['\"]\s*\)|"
            r"(?:svg|stage|visual|root|group|layer|chart|scene)[\w.$]*\.innerHTML\s*=|"
            r"insertAdjacentHTML\s*\(",
            script_text,
            re.IGNORECASE,
        )
    )
    measures_content_bounds = bool(re.search(r"getBBox\s*\(", script_text))
    updates_viewbox = bool(re.search(r"setAttribute\s*\(\s*['\"]viewBox['\"]", script_text))
    has_dynamic_fit = measures_content_bounds and updates_viewbox
    if svg is not None and svg.get("viewbox") and has_variable_control and mutates_svg_structure and not has_dynamic_fit:
        warnings.append(
            _warning(
                "static_viewbox_for_variable_svg",
                "脚本会向 SVG 动态增删图形节点，内容包络无法在编写时确定；固定 viewBox 可能裁切内容。"
                "应在结构变化后按 getBBox（或几何模型）重算 viewBox；若图形只更新既有元素属性，"
                "则应改为按变量 min/max 与动画关键帧预留 worst-case 包络的静态 viewBox，不做运行时重拟合。",
            )
        )

    _check_dynamic_viewbox_stability(script_text, warnings)


def _check_static_svg_viewbox_alignment(svg, warnings: list[dict]) -> None:
    """Warn when statically visible geometry is mostly outside or far off the SVG viewBox.

    This intentionally uses only cheap, theme-independent geometry. Dynamic paths
    cannot be evaluated safely here, but authored primitives are enough to catch
    the common failure where content is centered around the origin while the
    viewBox starts at ``0 0``.
    """
    viewbox = _parse_number_list(str(svg.get("viewbox") or ""))
    if len(viewbox) != 4 or viewbox[2] <= 0 or viewbox[3] <= 0:
        return

    visual_root = svg.find(id="visual-root") or svg.select_one('[data-role="visual-root"]')
    scope = visual_root or svg
    bounds = [_static_svg_element_bounds(element) for element in scope.find_all(SVG_GEOMETRY_TAGS)]
    bounds = [bound for bound in bounds if bound is not None]
    if not bounds:
        return

    min_x = min(bound[0] for bound in bounds)
    min_y = min(bound[1] for bound in bounds)
    max_x = max(bound[2] for bound in bounds)
    max_y = max(bound[3] for bound in bounds)
    content_width, content_height = max_x - min_x, max_y - min_y
    if content_width <= 0 or content_height <= 0:
        return

    view_x, view_y, view_width, view_height = viewbox
    overlap_width = max(0.0, min(max_x, view_x + view_width) - max(min_x, view_x))
    overlap_height = max(0.0, min(max_y, view_y + view_height) - max(min_y, view_y))
    visible_ratio = overlap_width * overlap_height / (content_width * content_height)
    center_dx = abs((min_x + max_x) / 2 - (view_x + view_width / 2)) / view_width
    center_dy = abs((min_y + max_y) / 2 - (view_y + view_height / 2)) / view_height

    if visible_ratio < 0.5 or (center_dx > 0.4 and center_dy > 0.4):
        warnings.append(
            _warning(
                "svg_visual_center_mismatch",
                "主视觉静态几何大部分位于 SVG viewBox 之外或与其中心明显偏离；"
                "应按全部状态的内容包络中心和相对安全边距设置固定 viewBox，"
                "包络不可预知时才在结构变化后执行受控的动态拟合。",
            )
        )


def _parse_number_list(value: str) -> list[float]:
    try:
        return [float(item) for item in re.findall(r"-?(?:\d+(?:\.\d*)?|\.\d+)", value)]
    except ValueError:
        return []


def _static_svg_element_bounds(element) -> tuple[float, float, float, float] | None:
    def number(name: str, default: float = 0.0) -> float | None:
        raw = element.get(name)
        if raw is None:
            return default
        if not re.fullmatch(r"\s*-?(?:\d+(?:\.\d*)?|\.\d+)\s*", str(raw)):
            return None
        value = float(raw)
        return value if math.isfinite(value) else None

    tag = str(element.name).lower()
    if tag == "circle":
        cx, cy, radius = number("cx"), number("cy"), number("r")
        if None not in (cx, cy, radius) and radius > 0:
            return cx - radius, cy - radius, cx + radius, cy + radius
    elif tag == "ellipse":
        cx, cy, rx, ry = number("cx"), number("cy"), number("rx"), number("ry")
        if None not in (cx, cy, rx, ry) and rx > 0 and ry > 0:
            return cx - rx, cy - ry, cx + rx, cy + ry
    elif tag == "line":
        values = number("x1"), number("y1"), number("x2"), number("y2")
        if None not in values:
            x1, y1, x2, y2 = values
            return min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)
    elif tag == "rect":
        x, y, width, height = number("x"), number("y"), number("width"), number("height")
        if None not in (x, y, width, height) and width > 0 and height > 0:
            return x, y, x + width, y + height
    elif tag in {"polygon", "polyline"}:
        points = _parse_number_list(str(element.get("points") or ""))
        if len(points) >= 4 and len(points) % 2 == 0:
            xs, ys = points[::2], points[1::2]
            return min(xs), min(ys), max(xs), max(ys)
    return None


def _check_dynamic_viewbox_stability(script_text: str, warnings: list[dict]) -> None:
    """Warn about dynamic-viewBox patterns that cause visible jitter.

    Refitting the viewBox per animation frame, or writing it synchronously
    inside a ResizeObserver callback without a change guard, produces scale
    jumps and the benign-but-noisy "ResizeObserver loop" browser warning.
    These stay warnings: the output remains usable, but repair guidance should
    steer toward a static worst-case envelope or a guarded refit path.
    """
    updates_viewbox = bool(re.search(r"setAttribute\s*\(\s*['\"]viewBox['\"]", script_text))
    if not updates_viewbox:
        return

    fit_fn_names = set(
        re.findall(
            r"(?:function\s+([A-Za-z_$][\w$]*)\s*\([^)]*\)|"
            r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:function\s*\([^)]*\)|\([^)]*\)\s*=>))"
            r"\s*\{[^{}]*(?:\{[^{}]*\}[^{}]*)*?setAttribute\s*\(\s*['\"]viewBox['\"]",
            script_text,
        )
    )
    fit_fn_names = {name for pair in fit_fn_names for name in pair if name}

    for match in re.finditer(r"onUpdate\s*[:=]\s*(?:function\s*\([^)]*\)|\([^)]*\)\s*=>)\s*\{", script_text):
        body = _extract_balanced_block(script_text, match.end() - 1)
        if body is None:
            continue
        writes_directly = "viewBox" in body
        calls_fit = any(re.search(rf"\b{re.escape(name)}\s*\(", body) for name in fit_fn_names)
        if writes_directly or calls_fit:
            warnings.append(
                _warning(
                    "per_frame_viewbox_refit",
                    "动画 onUpdate 回调内每帧重写 viewBox，内容包络随状态微变会导致画面缩放抖动；"
                    "viewBox 应只在初始化、结构变化或容器 resize 时更新，动画帧内只更新图形属性。",
                )
            )
            break

    observes_stage_size = bool(re.search(r"ResizeObserver\b", script_text))
    if observes_stage_size:
        has_raf_guard = bool(re.search(r"requestAnimationFrame\s*\(", script_text))
        has_change_guard = bool(
            re.search(
                r"getAttribute\s*\(\s*['\"]viewBox['\"]|"
                r"\b(?:last|prev|previous|current)[\w$]*[Vv]iew[Bb]ox\b",
                script_text,
            )
        )
        if not (has_raf_guard and has_change_guard):
            warnings.append(
                _warning(
                    "unguarded_resize_viewbox_write",
                    "ResizeObserver 回调路径会写 viewBox，但缺少 requestAnimationFrame 调度或新旧值比较守卫，"
                    "可能触发 ResizeObserver loop 警告并造成宽度/缩放跳动；值未变化时应跳过写入。",
                )
            )


def _extract_balanced_block(text: str, open_brace_index: int) -> str | None:
    if open_brace_index >= len(text) or text[open_brace_index] != "{":
        return None
    depth = 0
    quote: str | None = None
    index = open_brace_index
    while index < len(text):
        char = text[index]
        if quote is not None:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                quote = None
        elif char in "'\"`":
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[open_brace_index + 1 : index]
        index += 1
    return None


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


def _check_stage(
    parsed: BeautifulSoup,
    script_text: str,
    errors: list[dict],
    warnings: list[dict],
) -> None:
    stage = parsed.find(id="aetherviz-stage")
    if stage is None:
        errors.append(
            _error(
                "missing_stage",
                "缺少 #aetherviz-stage 主舞台",
                expected={"selector": "#aetherviz-stage", "phase": "static_dom"},
            )
        )
        return
    if stage.find(["svg", "canvas"]) is not None:
        return
    mount = stage.select_one("[data-role='main-visual']")
    if mount is not None:
        if mount.find() is not None or mount.get_text(strip=True):
            return
        mount_names = _find_main_visual_references(script_text)
        if _has_created_visual_appended_to(script_text, mount_names):
            return
        errors.append(
            _error(
                "empty_main_visual_mount",
                "main-visual 挂载节点为空，且未检测到脚本向该节点挂载可视化",
                expected={
                    "scope": "#aetherviz-stage [data-role='main-visual']",
                    "phase": "static_dom_or_provable_runtime_mount",
                    "content": "non-empty DOM visual or appended svg/canvas",
                },
            )
        )
        return
    if _has_provable_dynamic_stage_visual(script_text):
        warnings.append(
            _warning(
                "dynamic_stage_visual_legacy",
                "主视觉由脚本直接挂载到舞台；建议保留静态 [data-role='main-visual'] 挂载节点以统一生成和校验契约。",
            )
        )
        return
    errors.append(
        _error(
            "missing_stage_visual",
            "主舞台缺少可验证的 SVG、Canvas 或 main-visual 主体",
            expected={
                "scope": "#aetherviz-stage",
                "selector": "svg, canvas, [data-role='main-visual']",
                "phase": "static_dom",
                "dynamic_fallback": "create svg/canvas and append it to #aetherviz-stage",
            },
        )
    )


def _has_provable_dynamic_stage_visual(script_text: str) -> bool:
    """Recognize a small, topic-agnostic create-and-mount visual data flow."""

    stage_names = set(_STAGE_LOOKUP_RE.findall(script_text))
    return _has_created_visual_appended_to(script_text, stage_names)


def _has_created_visual_appended_to(script_text: str, target_names: set[str]) -> bool:
    visual_names = {
        _normalize_reference(match.group("target"))
        for match in _VISUAL_CREATION_RE.finditer(script_text)
    }
    for target_name in target_names:
        for visual_name in visual_names:
            if re.search(
                rf"(?<![\w$]){_reference_pattern(target_name)}\s*\.\s*"
                rf"(?:appendChild|append|replaceChildren)\(\s*{_reference_pattern(visual_name)}(?![\w$])",
                script_text,
            ):
                return True
    return False


def _find_main_visual_references(script_text: str) -> set[str]:
    """Return simple JS references that resolve to the static main-visual mount.

    Besides direct variables, generated pages frequently cache DOM nodes inside a
    plain object (for example ``const elements = { stage: querySelector(...) }``).
    Recognizing that generic member path keeps this check data-flow based without
    depending on a topic, identifier spelling, or visual coordinates.
    """

    references = {
        _normalize_reference(match.group("target"))
        for match in _MAIN_VISUAL_ASSIGNMENT_RE.finditer(script_text)
    }
    for declaration in _OBJECT_DECLARATION_RE.finditer(script_text):
        base = declaration.group("base")
        for prop_match in _MAIN_VISUAL_OBJECT_PROPERTY_RE.finditer(declaration.group("body")):
            prop = prop_match.group("property").strip("'\"")
            references.add(f"{base}.{prop}")
    return references


def _normalize_reference(reference: str) -> str:
    normalized = re.sub(r"\s+", "", reference)
    return re.sub(r"\[['\"]([A-Za-z_$][\w$]*)['\"]\]", r".\1", normalized)


def _reference_pattern(reference: str) -> str:
    return r"\s*\.\s*".join(re.escape(part) for part in reference.split("."))


def _check_controls(parsed: BeautifulSoup, errors: list[dict]) -> None:
    for control_id in REQUIRED_CONTROL_IDS:
        if parsed.find(id=control_id) is None:
            errors.append(_error("missing_control", f"缺少核心控件 #{control_id}"))


def _error(error_type: str, message: str, **details: object) -> dict:
    return {"type": error_type, "message": message, "line": None, **details}


def _warning(warning_type: str, message: str) -> dict:
    return {"type": warning_type, "message": message, "line": None}
