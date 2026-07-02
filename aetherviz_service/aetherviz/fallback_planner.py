"""Fallback planning logic for the narrowed AetherViz HTML/SVG generator."""

from __future__ import annotations

import json
import re

DEFAULT_PRIMARY_COLOR = "#22D3EE"

SUBJECT_KEYWORDS = {
    "math": ["数学", "几何", "证明", "三角", "函数", "代数", "方程", "概率", "统计", "向量", "面积", "体积", "导数", "积分", "勾股", "坐标", "平行四边形"],
    "physics": ["物理", "牛顿", "力", "运动", "碰撞", "弹簧", "速度", "加速度", "动量", "能量", "重力", "摩擦", "浮力", "电阻", "电流", "电压", "惯性"],
    "chemistry": ["化学", "反应", "元素", "分子", "原子", "周期表", "离子", "酸", "碱", "盐", "氧化", "还原", "溶液", "溶解度"],
    "biology": ["生物", "细胞", "基因", "dna", "蛋白质", "光合", "呼吸", "植物", "动物", "生态", "遗传"],
    "programming": ["算法", "排序", "递归", "树", "图", "状态机", "队列", "栈", "复杂度", "编程", "代码"],
    "geography": ["地理", "大气", "地球", "经纬", "板块", "地震", "地形", "气候", "水文", "洋流"],
    "chinese": ["语文", "诗词", "文言", "古文", "修辞", "散文", "小说", "汉字", "阅读"],
    "english": ["英语", "english", "语法", "句型", "词汇", "单词", "时态", "从句", "grammar", "tense"],
}

PLANNING_SYSTEM_PROMPT_TEMPLATE = """你是 AetherViz 互动教学动画规划师。
根据用户教学主题，输出一个用于生成独立 HTML 教学动画的 JSON 对象。

硬性边界：
- 本阶段只做 HTML + CSS + SVG 动画。
- 数学主题固定使用 HTML + SVG + KaTeX + GSAP Timeline。
- 非数学主题使用 HTML + CSS + SVG，不使用 Three.js、Canvas、图片生成或文件上传。
- 单个页面只突出一个核心结论，控制项少而明确。
- 只输出 JSON，不输出 Markdown 或解释。

字段约束：
- subject：math / physics / chemistry / biology / astronomy / programming / geography / chinese / english / general
- mode：generic_svg / math_svg_katex_gsap
- title：页面标题
- goal：一句话教学目标
- visual_steps：3~5 条视觉演示步骤
- controls：2~4 个控件，每个包含 id、label、type，type 只能是 slider / button / speed
- formulas：0~4 条公式或关键表达，数学主题至少 1 条
- validation_points：4~6 条生成 HTML 前的自检点
- primary_color：主色

输出 JSON 示例：
{
  "subject": "math",
  "mode": "math_svg_katex_gsap",
  "title": "平行四边形面积互动动画",
  "goal": "通过拖动底和高，观察平行四边形面积等于底乘高。",
  "visual_steps": ["显示底和高", "拖动顶点形成等底等高图形", "把图形剪拼为长方形", "同步更新面积公式"],
  "controls": [
    {"id": "base-slider", "label": "底", "type": "slider"},
    {"id": "height-slider", "label": "高", "type": "slider"},
    {"id": "speed-control", "label": "速度", "type": "speed"}
  ],
  "formulas": ["S=a\\\\times h"],
  "validation_points": ["包含 #math-svg", "按钮可播放暂停重置", "滑块同步更新 SVG 与公式", "声明 window.AetherVizRuntime"],
  "primary_color": "#22D3EE"
}
"""


def detect_subject(topic: str) -> str:
    if not topic:
        return "general"
    topic_lower = topic.lower()
    for subject in ("math", "chemistry", "biology", "geography", "physics", "programming", "chinese", "english"):
        if any(keyword in topic_lower for keyword in SUBJECT_KEYWORDS[subject]):
            return subject
    return "general"


def select_generation_mode(topic: str) -> str:
    return "math_svg_katex_gsap" if detect_subject(topic) == "math" else "generic_svg"


def build_planning_prompt(topic: str, primary_color: str) -> tuple[str, str]:
    subject = detect_subject(topic)
    mode = select_generation_mode(topic)
    user_prompt = f"""请为教学主题“{topic}”生成 AetherViz 动画方案。
服务端学科识别：{subject}
生成模式：{mode}
主色调：{primary_color}

请严格输出 JSON 对象，字段为 subject、mode、title、goal、visual_steps、controls、formulas、validation_points、primary_color。
"""
    return PLANNING_SYSTEM_PROMPT_TEMPLATE, user_prompt


def parse_planning_result(raw: str, topic: str = "", primary_color: str = DEFAULT_PRIMARY_COLOR) -> dict:
    data: dict = {}
    if raw:
        cleaned = raw.strip()
        if "```" in cleaned:
            fence_match = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL | re.IGNORECASE)
            if fence_match:
                cleaned = fence_match.group(1).strip()
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            cleaned = match.group(0)
        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                data = parsed
        except Exception:
            data = {}
    return normalize_plan(data, topic, primary_color)


def normalize_plan(raw_plan: dict | None, topic: str, primary_color: str = DEFAULT_PRIMARY_COLOR) -> dict:
    raw = raw_plan if isinstance(raw_plan, dict) else {}
    fallback = _default_plan(topic, primary_color)

    subject = _safe_str(raw.get("subject")) or fallback["subject"]
    if subject not in {*SUBJECT_KEYWORDS.keys(), "astronomy", "general"}:
        subject = fallback["subject"]

    mode = _safe_str(raw.get("mode")) or fallback["mode"]
    if mode not in {"generic_svg", "math_svg_katex_gsap"}:
        mode = "math_svg_katex_gsap" if subject == "math" else "generic_svg"
    if subject == "math":
        mode = "math_svg_katex_gsap"

    formulas = _string_list(raw.get("formulas"), fallback["formulas"], max_items=4, max_len=80)
    if mode == "math_svg_katex_gsap" and not formulas:
        formulas = [fallback["formulas"][0]]

    return {
        "subject": subject,
        "mode": mode,
        "title": (_safe_str(raw.get("title")) or fallback["title"])[:48],
        "goal": (_safe_str(raw.get("goal")) or fallback["goal"])[:120],
        "visual_steps": _string_list(raw.get("visual_steps"), fallback["visual_steps"], max_items=5, max_len=80),
        "controls": _normalize_controls(raw.get("controls"), fallback["controls"]),
        "formulas": formulas,
        "validation_points": _string_list(raw.get("validation_points"), fallback["validation_points"], max_items=6, max_len=80),
        "primary_color": _safe_str(raw.get("primary_color")) or primary_color,
    }


def _default_plan(topic: str, primary_color: str = DEFAULT_PRIMARY_COLOR) -> dict:
    subject = detect_subject(topic)
    mode = "math_svg_katex_gsap" if subject == "math" else "generic_svg"
    if mode == "math_svg_katex_gsap":
        return {
            "subject": subject,
            "mode": mode,
            "title": f"{topic}互动动画",
            "goal": f"通过 SVG 图形、公式和时间线动画理解“{topic}”的核心关系。",
            "visual_steps": [
                "展示核心图形和变量标注",
                "播放关键几何或函数变化过程",
                "同步更新公式和当前步骤说明",
                "拖动变量验证结论是否保持成立",
            ],
            "controls": [
                {"id": "variable-slider", "label": "关键变量", "type": "slider"},
                {"id": "speed-control", "label": "速度", "type": "speed"},
                {"id": "reset-button", "label": "重置", "type": "button"},
            ],
            "formulas": [topic],
            "validation_points": [
                "包含 #math-svg",
                "使用 KaTeX 渲染公式",
                "使用 GSAP Timeline 管理动画",
                "提供 play/pause/reset/setSpeed/update/getState",
                "滑块同步更新 SVG 和公式",
            ],
            "primary_color": primary_color,
        }
    return {
        "subject": subject,
        "mode": mode,
        "title": f"{topic}互动动画",
        "goal": f"用稳定的 SVG 动画解释“{topic}”的核心过程。",
        "visual_steps": [
            "用生活类比引入主题",
            "展示关键结构或过程节点",
            "播放状态变化动画",
            "通过滑块或步骤按钮观察结果变化",
        ],
        "controls": [
            {"id": "progress-slider", "label": "过程进度", "type": "slider"},
            {"id": "speed-control", "label": "速度", "type": "speed"},
            {"id": "reset-button", "label": "重置", "type": "button"},
        ],
        "formulas": [],
        "validation_points": [
            "使用 HTML + CSS + SVG",
            "不引入 Three.js 或 Canvas",
            "控制按钮均绑定事件",
            "移动端不溢出",
            "声明 window.AetherVizRuntime",
        ],
        "primary_color": primary_color,
    }


def _normalize_controls(raw_controls: object, default: list[dict]) -> list[dict]:
    source = raw_controls if isinstance(raw_controls, list) and raw_controls else default
    controls: list[dict] = []
    seen: set[str] = set()
    for item in source[:4]:
        if not isinstance(item, dict):
            continue
        control_id = re.sub(r"[^a-zA-Z0-9_-]+", "-", _safe_str(item.get("id")).lower()).strip("-")
        label = _safe_str(item.get("label"))
        control_type = _safe_str(item.get("type")).lower()
        if not control_id or control_id in seen or control_type not in {"slider", "button", "speed"}:
            continue
        seen.add(control_id)
        controls.append({"id": control_id[:40], "label": label[:24] or control_id, "type": control_type})
    return controls or list(default)


def _string_list(value: object, default: list[str], max_items: int, max_len: int = 60) -> list[str]:
    if not isinstance(value, list):
        return list(default[:max_items])
    items = [str(item).strip()[:max_len] for item in value if str(item).strip()]
    return items[:max_items] or list(default[:max_items])


def _safe_str(value: object) -> str:
    return str(value).strip() if value is not None else ""
