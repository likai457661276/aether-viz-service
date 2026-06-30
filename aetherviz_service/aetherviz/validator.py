import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup, Doctype, Tag


class AetherVizHtmlValidationError(ValueError):
    pass


FORBIDDEN_HTML_TAGS = {"iframe", "object", "embed", "form"}
FORBIDDEN_HTML_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?<!@)\bimport\s+[\w*{]", re.IGNORECASE), "ES Module import 语句"),
    (re.compile(r"\brequire\s*\(", re.IGNORECASE), "CommonJS require()调用"),
    (re.compile(r"\beval\s*\(", re.IGNORECASE), "eval()危险调用"),
    (re.compile(r"\bnew\s+Function\b", re.IGNORECASE), "new Function()构造器"),
    (re.compile(r"\bdocument\.write\s*\(", re.IGNORECASE), "document.write()调用"),
    (re.compile(r"OrbitControls\.js", re.IGNORECASE), "OrbitControls.js CDN引用"),
]

ALLOWED_EXTERNAL_URLS = {
    "https://cdn.tailwindcss.com",
    "https://cdnjs.cloudflare.com/ajax/libs/three.js/r134/three.min.js",
    "https://cdn.staticfile.net/three.js/r134/three.min.js",
    "https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css",
    "https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js",
    "https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/contrib/auto-render.min.js",
    "https://cdn.staticfile.net/KaTeX/0.16.9/katex.min.css",
    "https://cdn.staticfile.net/KaTeX/0.16.9/katex.min.js",
    "https://cdn.staticfile.net/KaTeX/0.16.9/contrib/auto-render.min.js",
    "https://d3js.org/d3.v7.min.js",
    "https://cdn.staticfile.net/d3/7.9.0/d3.min.js",
}

THREEJS_URL = "https://cdnjs.cloudflare.com/ajax/libs/three.js/r134/three.min.js"
REQUIRED_EXTERNAL_URLS = ALLOWED_EXTERNAL_URLS - {
    "https://d3js.org/d3.v7.min.js",
    "https://cdn.staticfile.net/d3/7.9.0/d3.min.js",
}

PLACEHOLDER_HTML_PATTERNS = [
    "暂未添加",
    "暂无内容",
    "待补充",
    "待添加",
    "请补充",
    "请添加",
    "todo",
    "tbd",
]

TOPIC_CONNECTOR_PATTERN = re.compile(
    r"(和|与|及|跟|同|以及|并且|然后|通过|关于|生成|形成|反应|变化|过程|"
    r"\b(?:and|or|with|to|of|the|a|an|in|on|for|about|into|from)\b)",
    re.IGNORECASE,
)


KATEX_URL_PATTERN = re.compile(
    r"^https://(?:cdn\.jsdelivr\.net/npm/katex@[^/]+/dist|cdn\.staticfile\.net/KaTeX/[^/]+)/(katex\.min\.css|katex\.min\.js|contrib/auto-render\.min\.js)$"
)


def _is_allowed_katex_url(url: str) -> bool:
    return bool(KATEX_URL_PATTERN.match(url))


def validate_aetherviz_html(html: str, topic: str | None = None, strict: bool = True) -> list[str]:
    """校验 AetherViz 生成的 HTML，返回警告列表。
    
    该函数执行多维度的 HTML 质量检查：
    1. 文档结构检查：DOCTYPE、html/head/body/title/style/script 标签完整性
    2. 安全检查：禁止标签（iframe/object/embed/form）、内联事件、非白名单外部资源
    3. 依赖检查：必需的 CDN（Tailwind CSS、Three.js、KaTeX）是否完整引入
    4. 运行时契约检查：Three.js 初始化代码、OrbitControls 实现、动画循环等
    5. 内容质量检查：占位符检测、学习目标数量、控制面板组件数量
    
    参数:
        html: 待校验的 HTML 字符串
        topic: 教学主题，用于检查内容是否体现主题（可选）
        strict: 是否启用严格模式（默认 True），非严格模式下某些检查降级为警告
        
    返回:
        警告列表，仅包含软性警告（不影响生成结果）
        
    异常:
        AetherVizHtmlValidationError: 当存在硬性错误时抛出，错误信息包含所有错误的分号分隔描述
    """
    stripped = (html or "").strip()
    if not stripped:
        raise AetherVizHtmlValidationError("HTML 不能为空")

    soup = BeautifulSoup(stripped, "html.parser")
    errors: list[str] = []
    warnings: list[str] = []
    _collect_document_structure_errors(stripped, soup, topic, errors, strict=strict)
    _collect_html_security_errors(stripped, soup, errors)
    fallback_mode = _is_fallback_svg_mode(soup)
    _collect_dependency_errors(soup, errors, fallback_mode=fallback_mode, strict=strict)
    _collect_runtime_contract_errors(stripped, soup, errors, warnings, strict=strict)
    _collect_html_substance_errors(stripped, soup, errors, warnings, strict=strict)
    if errors:
        raise AetherVizHtmlValidationError("；".join(errors))
    return warnings


def sanitize_aetherviz_html(html: str) -> str:
    """对 HTML 进行边界清理，仅去除首尾空白字符。
    
    该函数设计为最小化干预，不删除或改写模型生成的任何 HTML 内容，
    只做最基础的边界清理（strip）。
    
    参数:
        html: 原始 HTML 字符串
        
    返回:
        清理后的 HTML 字符串
    """
    return (html or "").strip()


def _collect_document_structure_errors(
    html: str,
    soup: BeautifulSoup,
    topic: str | None,
    errors: list[str],
    strict: bool = True,
) -> None:
    if not html.lower().startswith("<!doctype html>"):
        errors.append("HTML 必须以 <!DOCTYPE html> 开始")
    if not html.lower().endswith("</html>"):
        errors.append("HTML 必须以 </html> 结束")
    if not any(isinstance(item, Doctype) for item in soup.contents):
        errors.append("HTML 缺少 DOCTYPE")
    
    required_tags = ("html", "head", "body", "title", "style", "script") if strict else ("html", "body", "script")
    for tag_name in required_tags:
        if soup.find(tag_name) is None:
            errors.append(f"HTML 缺少 <{tag_name}>")
    if topic and topic.strip():
        title_text = soup.title.get_text(" ", strip=True) if soup.title else ""
        body_text = soup.get_text(" ", strip=True)
        if not _topic_is_represented(topic, f"{title_text} {body_text}"):
            errors.append("页面内容需要体现教学主题（missing_topic_signal）")


def _collect_html_security_errors(html: str, soup: BeautifulSoup, errors: list[str]) -> None:
    forbidden = [tag.name for tag in soup.find_all(FORBIDDEN_HTML_TAGS)]
    if forbidden:
        found = ", ".join(sorted(set(forbidden)))
        errors.append(f"HTML 包含禁止标签：{found}")

    for tag in soup.find_all(True):
        for attr_name, attr_value in tag.attrs.items():
            lower_name = attr_name.lower()
            value = " ".join(attr_value) if isinstance(attr_value, list) else str(attr_value)
            lower_value = value.lower()
            if lower_name.startswith("on"):
                errors.append(f"HTML 包含禁止内联事件属性：{attr_name}")
            if "javascript:" in lower_value:
                errors.append("HTML 包含禁止的 javascript: URL")
            if lower_name in {"src", "href"} and re.search(r"https?://", lower_value):
                normalized_url = _normalize_external_url(value)
                if normalized_url not in ALLOWED_EXTERNAL_URLS and not _is_allowed_katex_url(normalized_url):
                    errors.append(
                        f"HTML 包含非白名单外部资源（<{tag.name} {lower_name}=\"{value[:100]}\"）"
                    )

    for pattern, description in FORBIDDEN_HTML_PATTERNS:
        match = pattern.search(html)
        if match:
            snippet = match.group()[:80]
            errors.append(f"HTML 包含禁止内容：{description}（发现「{snippet}」）")


def _collect_dependency_errors(soup: BeautifulSoup, errors: list[str], fallback_mode: bool = False, strict: bool = True) -> None:
    if not strict:
        return
    urls = {
        _normalize_external_url(str(tag.get(attr_name)))
        for tag in soup.find_all(True)
        for attr_name in ("src", "href")
        if tag.get(attr_name) and re.search(r"https?://", str(tag.get(attr_name)))
    }
    
    # 校验各项必需依赖是否在 urls 中以合适形式存在（支持任意版本的 KaTeX）
    has_tailwind = any(url.startswith("https://cdn.tailwindcss.com") for url in urls)
    has_three = any(url in {THREEJS_URL, "https://cdn.staticfile.net/three.js/r134/three.min.js"} for url in urls)
    
    has_katex_css = any(
        re.match(r"^https://(?:cdn\.jsdelivr\.net/npm/katex@[^/]+/dist|cdn\.staticfile\.net/KaTeX/[^/]+)/katex\.min\.css$", url)
        for url in urls
    )
    has_katex_js = any(
        re.match(r"^https://(?:cdn\.jsdelivr\.net/npm/katex@[^/]+/dist|cdn\.staticfile\.net/KaTeX/[^/]+)/katex\.min\.js$", url)
        for url in urls
    )
    has_katex_auto = any(
        re.match(r"^https://(?:cdn\.jsdelivr\.net/npm/katex@[^/]+/dist|cdn\.staticfile\.net/KaTeX/[^/]+)/contrib/auto-render\.min\.js$", url)
        for url in urls
    )
    
    if not has_tailwind:
        errors.append("HTML 缺少必需 CDN：https://cdn.tailwindcss.com")
    if not fallback_mode and not has_three:
        errors.append(f"HTML 缺少必需 CDN：{THREEJS_URL}")
    if not has_katex_css:
        errors.append("HTML 缺少必需 CDN：https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css (允许任意版本)")
    if not has_katex_js:
        errors.append("HTML 缺少必需 CDN：https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js (允许任意版本)")
    if not has_katex_auto:
        errors.append("HTML 缺少必需 CDN：https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/contrib/auto-render.min.js (允许任意版本)")


def _collect_runtime_contract_errors(
    html: str,
    soup: BeautifulSoup,
    errors: list[str],
    warnings: list[str],
    strict: bool = True,
) -> None:
    if not strict:
        return
    scripts = "\n".join(script.get_text("\n", strip=False) for script in soup.find_all("script"))
    if not scripts.strip():
        errors.append("HTML 必须包含初始化脚本")
        return

    if _is_fallback_svg_mode(soup):
        stage = soup.find(id="aetherviz-stage")
        if stage is None or stage.find("svg") is None:
            errors.append("SVG 降级模式必须包含 #aetherviz-stage 内联 SVG")
        if not re.search(r"window\.updateVisualization\s*=", scripts):
            errors.append("SVG 降级模式必须声明 window.updateVisualization")
        for required_text in ("__AETHERVIZ_RUNTIME_READY__", "__AETHERVIZ_RUNTIME_ERROR__"):
            if required_text not in scripts:
                errors.append(f"HTML 缺少运行时自检标记 {required_text}")
        if "new window.THREE.WebGLRenderer" in scripts or "new THREE.WebGLRenderer" in scripts:
            errors.append("SVG 降级模式不应初始化 Three.js WebGLRenderer")
        return

    three_ref = r"(?:window\.)?THREE"

    # ── 硬性检查：核心 Three.js 对象必须存在 ──
    required_script_patterns = [
        (rf"new\s+{three_ref}\.Scene\s*\(", "Three.js 场景初始化"),
        (rf"new\s+{three_ref}\.PerspectiveCamera\s*\(", "PerspectiveCamera 相机初始化"),
        (rf"new\s+{three_ref}\.WebGLRenderer\s*\(", "WebGLRenderer 渲染器初始化"),
        (r"requestAnimationFrame\s*\(", "requestAnimationFrame 动画循环"),
        (r"addEventListener\s*\(\s*['\"]resize['\"]", "resize 响应式处理"),
    ]
    for pattern, label in required_script_patterns:
        if not re.search(pattern, scripts, re.IGNORECASE | re.DOTALL):
            errors.append(f"HTML 缺少{label}")

    # ── 硬性检查：OrbitControls 核心 ──
    if not re.search(r"(class|function)\s+(?:AetherViz)?OrbitControls\b", scripts):
        errors.append("HTML 必须内联 OrbitControls 简化实现")
    if "AetherVizOrbitControls" not in scripts:
        errors.append("OrbitControls 必须挂载或使用 window.AetherVizOrbitControls")
    for required_text in ("enableDamping", "dampingFactor", "update"):
        if required_text not in scripts:
            errors.append(f"内联 OrbitControls 缺少 {required_text}")
    for required_text in ("__AETHERVIZ_RUNTIME_READY__", "__AETHERVIZ_RUNTIME_ERROR__"):
        if required_text not in scripts:
            errors.append(f"HTML 缺少运行时自检标记 {required_text}")

    # ── 软性警告：质量细节 ──
    warn_patterns = [
        (rf"\.shadowMap\.enabled\s*=\s*true", "renderer.shadowMap.enabled=true"),
        (rf"new\s+{three_ref}\.HemisphereLight\s*\(", "HemisphereLight 环境光"),
        (rf"new\s+{three_ref}\.DirectionalLight\s*\(", "DirectionalLight 主光源"),
        (r"\.castShadow\s*=\s*true", "DirectionalLight castShadow=true"),
        (r"renderMathInElement\s*\(", "KaTeX renderMathInElement 调用"),
    ]
    for pattern, label in warn_patterns:
        if not re.search(pattern, scripts, re.IGNORECASE | re.DOTALL):
            warnings.append(f"HTML 缺少{label}")

    if not re.search(r"\b(touch|pointer)\w*", scripts, re.IGNORECASE):
        warnings.append("内联 OrbitControls 建议支持触控或 pointer 操作")
    if not re.search(r"\b(minDistance|maxDistance|zoom)\b", scripts, re.IGNORECASE):
        warnings.append("内联 OrbitControls 建议包含缩放限制")


def _collect_html_substance_errors(
    html: str,
    soup: BeautifulSoup,
    errors: list[str],
    warnings: list[str],
    strict: bool = True,
) -> None:
    normalized = soup.get_text(" ", strip=True).lower()
    raw_lower = html.lower()
    for pattern in PLACEHOLDER_HTML_PATTERNS:
        if pattern in normalized or pattern in raw_lower:
            errors.append(f"HTML 包含占位式内容：{pattern}")

    required_groups = {
        "主可视化区域": ["aetherviz-stage", "visualization", "visualizer", "canvas-container", "<canvas", "svg-container", "<svg"],
        "学习目标": ["学习目标", "learning-objectives", "learning objectives", "目标", "objectives"],
        "核心公式或概念": ["核心公式", "核心概念", "formula", "concept", "知识点"],
        "控制面板": ["控制面板", "control-panel", "controls", "buttons", "tab", "slider", "interactive"],
    }
    for label, candidates in required_groups.items():
        if not any(candidate in raw_lower or candidate in normalized for candidate in candidates):
            if strict:
                errors.append(f"HTML 缺少{label}")
            else:
                warnings.append(f"HTML 建议包含{label}")

    learning_items = _find_learning_objective_items(soup)
    if len(learning_items) < 3:
        if strict:
            errors.append("学习目标至少需要 3 条（missing_learning_objectives）")
        else:
            warnings.append("学习目标建议至少 3 条")

    if strict:
        controls = _find_control_items(soup)
        if len(controls) < 2:
            errors.append("控制面板至少需要 2 个可交互控件（missing_controls）")
        if not _has_animation_replay_control(soup):
            errors.append("控制面板必须包含动画播放/重新播放按钮（missing_animation_replay_control）")
        if not _has_animation_replay_binding(soup):
            errors.append("动画播放/重新播放按钮必须绑定进度动画逻辑（missing_animation_replay_binding）")


def _is_fallback_svg_mode(soup: BeautifulSoup) -> bool:
    return bool(soup.select_one('[data-aetherviz-render-mode="fallback-svg"]'))

def _normalize_external_url(url: str) -> str:
    parts = urlsplit(url.strip())
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


def _topic_is_represented(topic: str, text: str) -> bool:
    normalized_topic = _normalize_topic_signal(topic)
    normalized_text = _normalize_topic_signal(text)
    if not normalized_topic:
        return True
    if normalized_topic in normalized_text:
        return True

    topic_tokens = _topic_tokens(topic)
    text_tokens = set(_topic_tokens(text))
    if topic_tokens:
        matched = sum(1 for token in topic_tokens if token in text_tokens or token in normalized_text)
        required = max(1, (len(topic_tokens) + 1) // 2)
        return matched >= required

    topic_chars = {char for char in normalized_topic if "\u4e00" <= char <= "\u9fff"}
    if topic_chars:
        matched_chars = {char for char in topic_chars if char in normalized_text}
        return len(matched_chars) / len(topic_chars) >= 0.6
    return False


def _normalize_topic_signal(value: str) -> str:
    without_connectors = TOPIC_CONNECTOR_PATTERN.sub("", value.lower())
    return re.sub(r"[\W_]+", "", without_connectors, flags=re.UNICODE)


def _topic_tokens(value: str) -> list[str]:
    cleaned = TOPIC_CONNECTOR_PATTERN.sub(" ", value.lower())
    tokens = re.findall(r"[a-z0-9][a-z0-9'-]{1,}|[\u4e00-\u9fff]{2,}", cleaned)
    return [token for token in tokens if len(token) >= 2]


def _find_learning_objective_items(soup: BeautifulSoup) -> list[Tag]:
    selectors = (
        ".learning-objectives li, #learning-objectives li, "
        "[data-section='learning-objectives'] li, [data-section='objectives'] li, "
        "[data-section='goals'] li, [aria-label*='学习目标'] li, [aria-label*='Learning'] li"
    )
    items = list(soup.select(selectors))
    if items:
        return items

    section = _find_section_by_heading(soup, ("学习目标", "learning objectives", "objectives", "目标"))
    return list(section.select("li")) if section else []


def _find_control_items(soup: BeautifulSoup) -> list[Tag]:
    control_tag_names = ("input", "button", "select", "textarea", "details", "summary")
    control_tags = ", ".join(control_tag_names)
    roots = (
        ".control-panel",
        ".controls",
        "#control-panel",
        "[data-section='controls']",
        "[data-section='control-panel']",
        "[aria-label*='控制']",
        "[aria-label*='Control']",
    )
    selectors = [", ".join(f"{root} {tag_name}" for tag_name in control_tag_names) for root in roots]
    controls: list[Tag] = []
    seen: set[int] = set()
    for selector in selectors:
        for item in soup.select(selector):
            marker = id(item)
            if marker not in seen:
                seen.add(marker)
                controls.append(item)

    if controls:
        return controls

    section = _find_section_by_heading(soup, ("控制面板", "controls", "control panel", "参数"))
    return list(section.select(control_tags)) if section else []


def _has_animation_replay_control(soup: BeautifulSoup) -> bool:
    roots = [
        soup.select_one(".control-panel"),
        soup.select_one(".controls"),
        soup.select_one("#control-panel"),
        soup.select_one("[data-section='controls']"),
        soup.select_one("[data-section='control-panel']"),
        _find_section_by_heading(soup, ("控制面板", "controls", "control panel", "参数")),
    ]
    replay_patterns = (
        "重新播放",
        "播放动画",
        "重播",
        "replay",
        "play-animation",
        "replay-animation",
        "restart-animation",
        "animation-play",
    )
    for root in roots:
        if not isinstance(root, Tag):
            continue
        for button in root.select("button, [role='button']"):
            haystack = " ".join(
                str(value)
                for value in (
                    button.get_text(" ", strip=True),
                    button.get("id", ""),
                    button.get("class", ""),
                    button.get("aria-label", ""),
                    button.get("title", ""),
                    button.get("data-action", ""),
                )
            ).lower()
            if any(pattern.lower() in haystack for pattern in replay_patterns):
                return True
    return False


def _has_animation_replay_binding(soup: BeautifulSoup) -> bool:
    scripts = "\n".join(script.get_text("\n", strip=False) for script in soup.find_all("script"))
    if "play-animation" not in scripts:
        return False
    if not re.search(r"addEventListener\s*\(\s*['\"]click['\"]", scripts, re.IGNORECASE):
        return False
    required_patterns = (
        r"requestAnimationFrame\s*\(",
        r"\bsetProgress\s*\(",
        r"\bupdate(?:Reaction|Animation|Visualization|Scene)\s*\(",
        r"重新播放|replay",
    )
    return all(re.search(pattern, scripts, re.IGNORECASE) for pattern in required_patterns)


def _find_section_by_heading(soup: BeautifulSoup, keywords: tuple[str, ...]) -> Tag | None:
    normalized_keywords = tuple(keyword.lower() for keyword in keywords)
    for heading in soup.find_all(re.compile(r"^h[1-6]$")):
        heading_text = heading.get_text(" ", strip=True).lower()
        if not any(keyword in heading_text for keyword in normalized_keywords):
            continue
        parent = heading.parent
        if isinstance(parent, Tag) and parent.name not in {"body", "html"}:
            return parent
        next_sibling = heading.find_next_sibling()
        if isinstance(next_sibling, Tag):
            return next_sibling
    return None
