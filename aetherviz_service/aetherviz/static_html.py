"""Static AetherViz HTML lookup and theme adaptation."""

from __future__ import annotations

import colorsys
import re
from pathlib import Path

from aetherviz_service.aetherviz.knowledge_points import KnowledgePoint


DEFAULT_PRIMARY_COLOR = "#22D3EE"
HTML_ROOT = Path(__file__).resolve().parent / "html"
HEX_COLOR_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")
AI_ATTRIBUTION_PATTERN = re.compile(
    r"(?:[—\-·•]\s*)?由\s*宾果AI\s*(?:为你)?生成\s*(?:❤️|❤|\ufe0f)?",
    re.IGNORECASE,
)


def extract_color_from_topic(topic: str) -> str:
    """从教学主题字符串中提取主色调。
    
    提取逻辑按优先级：
    1. 首先查找 #RRGGBB 格式的十六进制颜色值（如 #3B82F6）
    2. 如果没有找到，查找中文颜色词（如"红色"、"蓝色"）
    3. 如果都没有找到，返回默认主题色 #22D3EE（青色）
    
    参数:
        topic: 教学主题字符串
        
    返回:
        十六进制颜色值字符串（大写），如 "#3B82F6"
    """
    if not topic:
        return DEFAULT_PRIMARY_COLOR
    match = re.search(r"#[0-9A-Fa-f]{6}", topic)
    if match:
        return match.group(0).upper()
    
    chinese_colors = [
        ("红色", "#EF4444"), ("橙色", "#F97316"), ("黄色", "#EAB308"), ("绿色", "#22C55E"),
        ("蓝色", "#3B82F6"), ("紫色", "#A855F7"), ("粉色", "#EC4899"), ("青色", "#06B6D4"),
        ("白色", "#F8FAFC"), ("黑色", "#1E293B"),
        ("红", "#EF4444"), ("橙", "#F97316"), ("黄", "#EAB308"), ("绿", "#22C55E"),
        ("蓝", "#3B82F6"), ("紫", "#A855F7"), ("粉", "#EC4899"), ("青", "#06B6D4"),
        ("白", "#F8FAFC"), ("黑", "#1E293B"),
    ]
    for name, hex_val in chinese_colors:
        if name in topic:
            return hex_val
            
    return DEFAULT_PRIMARY_COLOR


class StaticAetherVizHtmlError(ValueError):
    pass


def static_html_path_for_point(point: KnowledgePoint, html_root: Path | None = None) -> Path:
    root = html_root or HTML_ROOT
    return root / point.subject / f"{point.static_html_slug}.html"


def load_static_html_for_point(point: KnowledgePoint, primary_color: str) -> str:
    """加载静态知识点的 HTML 文件并注入主题色。
    
    该函数负责：
    1. 根据知识点的 subject 和 static_html_slug 定位 HTML 文件路径
    2. 读取 HTML 文件（支持 utf-8-sig 编码，处理 BOM）
    3. 校验文件必须以 <!DOCTYPE html> 开头
    4. 注入主题色 CSS 覆盖层
    
    参数:
        point: 知识点对象，包含 subject 和 static_html_slug 属性
        primary_color: 主题色，如 "#3B82F6"
        
    返回:
        注入主题色后的完整 HTML 字符串
        
    异常:
        StaticAetherVizHtmlError: 当 HTML 文件不存在或格式不正确时抛出
    """
    path = static_html_path_for_point(point)
    return load_static_html_file(path, primary_color)


def static_html_path_for_relative_path(relative_path: str, html_root: Path | None = None) -> Path:
    normalized = Path(relative_path.strip().lstrip("/"))
    if normalized.is_absolute() or ".." in normalized.parts or normalized.suffix.lower() != ".html":
        raise StaticAetherVizHtmlError("静态 HTML 路径不合法")

    root = (html_root or HTML_ROOT).resolve()
    path = (root / normalized).resolve()
    if not path.is_relative_to(root):
        raise StaticAetherVizHtmlError("静态 HTML 路径不合法")
    return path


def load_static_html_for_relative_path(relative_path: str, primary_color: str) -> str:
    path = static_html_path_for_relative_path(relative_path)
    return load_static_html_file(path, primary_color)


def load_static_html_file(path: Path, primary_color: str) -> str:
    if not path.is_file():
        raise StaticAetherVizHtmlError(f"静态 HTML 文件不存在：{path}")
    html = path.read_text(encoding="utf-8-sig").strip()
    if not html.lower().startswith("<!doctype html>"):
        raise StaticAetherVizHtmlError(f"静态 HTML 必须以 <!DOCTYPE html> 开始：{path}")
    return inject_theme_override(strip_ai_attribution(html), primary_color)


def strip_ai_attribution(html: str) -> str:
    return AI_ATTRIBUTION_PATTERN.sub("", html or "")


def normalize_primary_color(primary_color: str) -> str:
    color = (primary_color or "").strip()
    if not HEX_COLOR_PATTERN.fullmatch(color):
        return DEFAULT_PRIMARY_COLOR
    return color.upper()


def inject_theme_override(html: str, primary_color: str) -> str:
    """向 HTML 中注入主题色 CSS 覆盖层。
    
    该函数根据主色调生成一套完整的 CSS 变量覆盖，包括：
    - 主渐变、浅色渐变、深色渐变
    - 背景卡片渐变
    - 强调色、边框色、悬浮效果等
    
    注入方式是在最后一个 </style> 标签前插入 :root 级别的 CSS 变量覆盖。
    这种方式可以批量覆盖预定义的 CSS 变量，而不需要逐个替换 HTML 中的颜色值。
    
    参数:
        html: 原始 HTML 字符串
        primary_color: 主题色，如 "#3B82F6"
        
    返回:
        注入主题色覆盖后的 HTML 字符串
    """
    color = normalize_primary_color(primary_color)
    palette = _build_palette(color)
    override = f"""

/* AI互动实验 runtime theme override */
:root {{
  --primary-gradient: linear-gradient(135deg, {palette["primary"]} 0%, {palette["cool"]} 50%, {palette["highlight"]} 100%);
  --primary-gradient-light: linear-gradient(135deg, {palette["light"]} 0%, {palette["lighter"]} 50%, {palette["highlight_light"]} 100%);
  --primary-gradient-dark: linear-gradient(135deg, {palette["dark"]} 0%, {palette["cool_dark"]} 50%, {palette["highlight_dark"]} 100%);
  --bg-gradient-card: linear-gradient(145deg, rgba({palette["rgb"]},0.15) 0%, rgba({palette["cool_rgb"]},0.1) 100%);
  --accent-cyan: {palette["highlight"]};
  --theme-physics: linear-gradient(135deg, {palette["primary"]} 0%, {palette["cool"]} 100%);
  --nav-border: rgba({palette["rgb"]},0.3);
  --sidebar-item-hover: rgba({palette["rgb"]},0.2);
  --sidebar-item-active: rgba({palette["cool_rgb"]},0.4);
  --panel-border: rgba({palette["rgb"]},0.25);
  --btn-primary: linear-gradient(135deg, {palette["primary"]} 0%, {palette["cool"]} 100%);
  --btn-primary-hover: linear-gradient(135deg, {palette["light"]} 0%, {palette["highlight"]} 100%);
  --slider-thumb: linear-gradient(135deg, {palette["light"]} 0%, {palette["lighter"]} 100%);
}}
""".rstrip()
    if "</style>" not in html.lower():
        return html
    return re.sub(r"</style>", f"{override}\n</style>", html, count=1, flags=re.IGNORECASE)


def _build_palette(primary: str) -> dict[str, str]:
    r, g, b = _hex_to_rgb(primary)
    h, lightness, saturation = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    cool_h = (h + 0.08) % 1.0
    highlight_h = (h + 0.14) % 1.0
    dark_h = (h - 0.02) % 1.0
    return {
        "primary": primary,
        "rgb": f"{r},{g},{b}",
        "light": _hls_to_hex(h, min(0.72, lightness + 0.14), saturation),
        "lighter": _hls_to_hex(h, min(0.82, lightness + 0.24), max(0.35, saturation * 0.85)),
        "dark": _hls_to_hex(dark_h, max(0.28, lightness - 0.16), saturation),
        "cool": _hls_to_hex(cool_h, lightness, saturation),
        "cool_rgb": _hex_rgb_string(_hls_to_hex(cool_h, lightness, saturation)),
        "cool_dark": _hls_to_hex(cool_h, max(0.3, lightness - 0.14), saturation),
        "highlight": _hls_to_hex(highlight_h, min(0.66, lightness + 0.08), saturation),
        "highlight_light": _hls_to_hex(highlight_h, min(0.78, lightness + 0.18), saturation),
        "highlight_dark": _hls_to_hex(highlight_h, max(0.32, lightness - 0.12), saturation),
    }


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


def _hex_rgb_string(color: str) -> str:
    return ",".join(str(part) for part in _hex_to_rgb(color))


def _hls_to_hex(hue: float, lightness: float, saturation: float) -> str:
    red, green, blue = colorsys.hls_to_rgb(hue, lightness, saturation)
    return f"#{round(red * 255):02X}{round(green * 255):02X}{round(blue * 255):02X}"
