"""Fallback planning for single-page OpenMAIC-style interactive content."""

from __future__ import annotations

import json
import re
from typing import Any

DEFAULT_PRIMARY_COLOR = "#22D3EE"

SUBJECT_KEYWORDS = {
    "math": ["数学", "几何", "函数", "方程", "概率", "统计", "面积", "体积", "坐标", "圆", "抛物线", "勾股"],
    "physics": ["物理", "运动", "速度", "加速度", "力", "能量", "电流", "电压", "波", "光", "抛体"],
    "chemistry": ["化学", "反应", "分子", "原子", "离子", "酸", "碱", "盐", "溶液", "反应速率"],
    "biology": ["生物", "细胞", "基因", "dna", "蛋白质", "光合", "呼吸", "生态", "遗传"],
    "programming": ["算法", "排序", "递归", "树", "图", "状态机", "队列", "栈", "复杂度"],
    "geography": ["地理", "大气", "地球", "经纬", "板块", "地震", "地形", "气候", "水文"],
    "chinese": ["语文", "诗词", "文言", "古文", "修辞", "散文", "小说", "阅读结构"],
    "english": ["英语", "english", "语法", "句型", "词汇", "时态", "从句", "grammar"],
}

VALID_INTERACTIVE_TYPES = {"simulation", "diagram", "game"}
VALID_RENDER_STACKS = {"svg", "svg_canvas", "canvas_svg", "dom_svg"}
VALID_ANIMATION_RUNTIMES = {"native", "gsap_timeline"}

SIMULATION_KEYWORDS = ["运动", "参数", "实验", "函数", "概率", "反应速率", "电路", "轨迹", "速度", "采样"]
DIAGRAM_KEYWORDS = ["流程", "结构", "分类", "因果", "步骤", "阅读结构", "知识图谱", "体系", "过程"]
GAME_KEYWORDS = ["练习", "闯关", "匹配", "排序", "挑战", "小游戏", "巩固", "得分"]

PLANNING_SYSTEM_PROMPT_TEMPLATE = """你是资深互动教学课件规划师。
为 12~18 岁学生设计一个单页 interactive HTML 课件计划。

规划原则：
- page_type 固定为 interactive。
- interactive_type 只能是 simulation、diagram、game。
- interactive_spec 必须描述互动意图和核心配置：simulation 写 variables/presets/observations，diagram 写 nodes/edges/reveal_order，game 写 challenge/success_condition/feedback_rules。
- teaching_flow 用 3~5 个教学节奏步骤描述观察、操作、归纳。
- controls 只保留真实影响学习的控件，2~5 个。
- runtime.render_stack 只能是 svg、svg_canvas、canvas_svg、dom_svg；runtime.animation_runtime 只能是 native、gsap_timeline。
- stage_layout 必须说明目标区、主舞台、控制区和结论区如何在单屏内摆放。

只输出 JSON 对象，不输出 Markdown 或解释。
"""


def detect_subject(topic: str) -> str:
    text = (topic or "").lower()
    for subject in ("math", "chemistry", "biology", "geography", "physics", "programming", "chinese", "english"):
        if any(keyword in text for keyword in SUBJECT_KEYWORDS[subject]):
            return subject
    return "general"


def select_interactive_type(topic: str, subject: str) -> str:
    text = (topic or "").lower()
    if any(keyword in text for keyword in GAME_KEYWORDS):
        return "game"
    if any(keyword in text for keyword in DIAGRAM_KEYWORDS):
        return "diagram"
    if any(keyword in text for keyword in SIMULATION_KEYWORDS):
        return "simulation"
    if subject in {"chinese", "english", "geography", "programming"}:
        return "diagram"
    if subject in {"math", "physics", "chemistry", "biology"}:
        return "simulation"
    return "diagram"


def select_render_stack(interactive_type: str, subject: str, topic: str) -> str:
    text = (topic or "").lower()
    if interactive_type == "simulation" and any(keyword in text for keyword in ("粒子", "扩散", "轨迹", "运动", "波", "碰撞")):
        return "svg_canvas"
    if interactive_type == "game":
        return "dom_svg"
    if interactive_type == "diagram":
        return "dom_svg"
    if subject == "math":
        return "svg"
    return "svg_canvas"


def select_animation_runtime(interactive_type: str, render_stack: str) -> str:
    if interactive_type == "diagram" and render_stack == "dom_svg":
        return "gsap_timeline"
    return "native"


def build_planning_prompt(topic: str, primary_color: str) -> tuple[str, str]:
    subject = detect_subject(topic)
    interactive_type = select_interactive_type(topic, subject)
    render_stack = select_render_stack(interactive_type, subject, topic)
    animation_runtime = select_animation_runtime(interactive_type, render_stack)
    user_prompt = f"""请为以下教学主题设计单页 interactive 课件计划。

主题：{topic}
服务端学科识别：{subject}
推荐互动类型：{interactive_type}
推荐渲染栈：{render_stack}
推荐动画运行时：{animation_runtime}
主色调：{primary_color}

必须输出完整 JSON，字段包括：
page_type、interactive_type、subject、title、goal、learner_level、stage_layout、
interactive_spec、teaching_flow、controls、formulas、runtime、primary_color。
"""
    return PLANNING_SYSTEM_PROMPT_TEMPLATE, user_prompt


def build_revision_planning_prompt(
    topic: str,
    instruction: str,
    context: dict[str, Any] | None,
    primary_color: str,
) -> tuple[str, str]:
    system_prompt, base_prompt = build_planning_prompt(topic, primary_color)
    context_payload = {
        "previous_plan": (context or {}).get("plan_summary"),
        "selected_file": (context or {}).get("selected_file"),
        "memory": (context or {}).get("memory"),
        "recent_messages": (context or {}).get("recent_messages"),
    }
    user_prompt = f"""{base_prompt}

这是一次重新规划，不修改旧 HTML，也不读取旧 HTML。
用户新要求：{instruction}
上次计划与会话摘要：
{json.dumps(context_payload, ensure_ascii=False, indent=2)}

请把用户新要求合并进新的 single-page interactive plan。不要输出 HTML。
"""
    return system_prompt, user_prompt


def parse_planning_result(raw: str, topic: str = "", primary_color: str = DEFAULT_PRIMARY_COLOR) -> dict:
    data: dict[str, Any] = {}
    if raw:
        cleaned = raw.strip()
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

    interactive_type = _safe_str(raw.get("interactive_type")) or fallback["interactive_type"]
    if interactive_type not in VALID_INTERACTIVE_TYPES:
        interactive_type = select_interactive_type(topic, subject)

    runtime_raw = raw.get("runtime") if isinstance(raw.get("runtime"), dict) else {}
    render_stack = _safe_str(runtime_raw.get("render_stack") or raw.get("render_stack")) or select_render_stack(interactive_type, subject, topic)
    if render_stack not in VALID_RENDER_STACKS:
        render_stack = select_render_stack(interactive_type, subject, topic)
    animation_runtime = _safe_str(runtime_raw.get("animation_runtime") or raw.get("animation_runtime")) or select_animation_runtime(interactive_type, render_stack)
    if animation_runtime not in VALID_ANIMATION_RUNTIMES:
        animation_runtime = select_animation_runtime(interactive_type, render_stack)

    interactive_spec = _normalize_interactive_spec(raw.get("interactive_spec"), fallback["interactive_spec"], interactive_type, topic)
    teaching_flow = _normalize_teaching_flow(raw.get("teaching_flow"), fallback["teaching_flow"])

    return {
        "page_type": "interactive",
        "interactive_type": interactive_type,
        "subject": subject,
        "title": (_safe_str(raw.get("title")) or fallback["title"])[:48],
        "goal": (_safe_str(raw.get("goal")) or fallback["goal"])[:180],
        "learner_level": (_safe_str(raw.get("learner_level")) or "初中/高中")[:24],
        "stage_layout": (_safe_str(raw.get("stage_layout")) or fallback["stage_layout"])[:220],
        "interactive_spec": interactive_spec,
        "teaching_flow": teaching_flow,
        "controls": _normalize_controls(raw.get("controls"), fallback["controls"]),
        "formulas": _string_list(raw.get("formulas"), fallback["formulas"], max_items=5, max_len=100),
        "runtime": {
            "render_stack": render_stack,
            "animation_runtime": animation_runtime,
            "external_libraries": _string_list(runtime_raw.get("external_libraries"), [], max_items=3, max_len=80),
        },
        "primary_color": _safe_str(raw.get("primary_color")) or primary_color,
    }


def _default_plan(topic: str, primary_color: str) -> dict:
    subject = detect_subject(topic)
    interactive_type = select_interactive_type(topic, subject)
    render_stack = select_render_stack(interactive_type, subject, topic)
    animation_runtime = select_animation_runtime(interactive_type, render_stack)
    return {
        "page_type": "interactive",
        "interactive_type": interactive_type,
        "subject": subject,
        "title": f"{topic}互动课件",
        "goal": f'通过单页互动操作理解"{topic}"的关键概念和变化规律。',
        "learner_level": "初中/高中",
        "stage_layout": "顶部展示学习目标，中间为主舞台，底部放置控制区、当前说明和结论区，移动端纵向堆叠但保持主视觉优先。",
        "interactive_spec": _default_interactive_spec(topic, interactive_type),
        "teaching_flow": [
            {"id": "observe", "label": "观察初始状态", "focus": "核心对象和变量被清晰标注", "caption": "先观察页面中哪些对象会发生变化。"},
            {"id": "interact", "label": "操作互动控件", "focus": "学生调节参数或逐步揭示内容", "caption": "再通过控件改变状态，比较不同结果。"},
            {"id": "conclude", "label": "归纳结论", "focus": "图形、数值和结论同步高亮", "caption": "最后把观察结果和核心规律对应起来。"},
        ],
        "controls": _default_controls(interactive_type),
        "formulas": [topic] if subject == "math" else [],
        "runtime": {
            "render_stack": render_stack,
            "animation_runtime": animation_runtime,
            "external_libraries": [],
        },
        "primary_color": primary_color,
    }


def _default_interactive_spec(topic: str, interactive_type: str) -> dict:
    if interactive_type == "simulation":
        return {
            "concept": topic,
            "description": "学生通过调节参数观察结果变化。",
            "variables": [
                {"name": "parameter", "label": "关键参数", "min": 1, "max": 10, "default": 5, "step": 1, "unit": ""},
            ],
            "presets": [{"id": "default", "label": "默认状态", "values": {"parameter": 5}}],
            "observations": ["观察参数改变后主舞台图形和结论如何同步变化。"],
        }
    if interactive_type == "game":
        return {
            "concept": topic,
            "description": "学生完成一个与知识点直接相关的互动挑战。",
            "challenge": "根据提示完成匹配、排序或选择策略。",
            "success_condition": "所有关键对象放入正确位置并能解释原因。",
            "feedback_rules": ["正确时显示原因解释", "错误时高亮冲突点并给出提示"],
        }
    return {
        "concept": topic,
        "description": "学生逐步揭示节点和关系，理解整体结构。",
        "nodes": [
            {"id": "core", "label": topic, "explanation": "核心概念"},
            {"id": "cause", "label": "关键原因", "explanation": "导致变化或形成结构的主要因素"},
            {"id": "result", "label": "结果结论", "explanation": "最终需要掌握的规律"},
        ],
        "edges": [{"source": "cause", "target": "core"}, {"source": "core", "target": "result"}],
        "reveal_order": ["core", "cause", "result"],
    }


def _default_controls(interactive_type: str) -> list[dict]:
    if interactive_type == "simulation":
        return [
            {"id": "parameter-slider", "label": "关键参数", "type": "slider", "bind": "parameter"},
            {"id": "play-button", "label": "播放", "type": "button", "action": "play"},
            {"id": "reset-button", "label": "重置", "type": "button", "action": "reset"},
        ]
    if interactive_type == "game":
        return [
            {"id": "start-button", "label": "开始挑战", "type": "button", "action": "start"},
            {"id": "check-button", "label": "检查答案", "type": "button", "action": "check"},
            {"id": "reset-button", "label": "重置", "type": "button", "action": "reset"},
        ]
    return [
        {"id": "next-button", "label": "下一步", "type": "button", "action": "next"},
        {"id": "highlight-toggle", "label": "高亮重点", "type": "toggle", "action": "highlight"},
        {"id": "reset-button", "label": "重置", "type": "button", "action": "reset"},
    ]


def _normalize_interactive_spec(raw_spec: object, default: dict, interactive_type: str, topic: str) -> dict:
    if not isinstance(raw_spec, dict):
        return dict(default)
    spec = dict(raw_spec)
    spec.setdefault("concept", topic)
    spec.setdefault("description", default.get("description"))
    if interactive_type == "simulation":
        variables = spec.get("variables")
        spec["variables"] = variables if isinstance(variables, list) and variables else default.get("variables", [])
        observations = spec.get("observations")
        spec["observations"] = observations if isinstance(observations, list) and observations else default.get("observations", [])
    elif interactive_type == "diagram":
        for field in ("nodes", "edges", "reveal_order"):
            value = spec.get(field)
            spec[field] = value if isinstance(value, list) and value else default.get(field, [])
    else:
        spec.setdefault("challenge", default.get("challenge"))
        spec.setdefault("success_condition", default.get("success_condition"))
        rules = spec.get("feedback_rules")
        spec["feedback_rules"] = rules if isinstance(rules, list) and rules else default.get("feedback_rules", [])
    return spec


def _normalize_teaching_flow(raw_flow: object, default: list[dict]) -> list[dict]:
    source = raw_flow if isinstance(raw_flow, list) and raw_flow else default
    flow: list[dict] = []
    seen: set[str] = set()
    for index, item in enumerate(source[:5]):
        if not isinstance(item, dict):
            continue
        step_id = re.sub(r"[^a-zA-Z0-9_-]+", "-", (_safe_str(item.get("id")) or f"step-{index + 1}").lower()).strip("-")
        if step_id in seen:
            step_id = f"{step_id}-{index + 1}"
        seen.add(step_id)
        flow.append(
            {
                "id": step_id,
                "label": (_safe_str(item.get("label")) or f"第{index + 1}步")[:32],
                "focus": (_safe_str(item.get("focus")) or "观察核心变化")[:140],
                "caption": (_safe_str(item.get("caption")) or "观察当前步骤的关键变化。")[:140],
            }
        )
    return flow or list(default)


def _normalize_controls(raw_controls: object, default: list[dict]) -> list[dict]:
    source = raw_controls if isinstance(raw_controls, list) and raw_controls else default
    controls: list[dict] = []
    seen: set[str] = set()
    for index, item in enumerate(source[:5]):
        if not isinstance(item, dict):
            continue
        control_id = re.sub(r"[^a-zA-Z0-9_-]+", "-", (_safe_str(item.get("id")) or f"control-{index + 1}").lower()).strip("-")
        control_type = _safe_str(item.get("type")).lower()
        if control_type not in {"slider", "button", "speed", "toggle", "select"}:
            control_type = "button"
        if control_id in seen:
            control_id = f"{control_id}-{index + 1}"
        seen.add(control_id)
        controls.append(
            {
                "id": control_id[:40],
                "label": (_safe_str(item.get("label")) or control_id)[:24],
                "type": control_type,
                "bind": _safe_str(item.get("bind")) or None,
                "action": _safe_str(item.get("action")) or None,
            }
        )
    return controls or list(default)


def _string_list(value: object, default: list[str], max_items: int, max_len: int = 60) -> list[str]:
    if not isinstance(value, list):
        return list(default[:max_items])
    items = [str(item).strip()[:max_len] for item in value if str(item).strip()]
    return items[:max_items] or list(default[:max_items])


def _safe_str(value: object) -> str:
    return str(value).strip() if value is not None else ""
