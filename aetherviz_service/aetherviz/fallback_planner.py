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
VALID_ANIMATION_RUNTIMES = {"native"}

SIMULATION_KEYWORDS = ["运动", "参数", "实验", "函数", "概率", "反应速率", "电路", "轨迹", "速度", "采样"]
DIAGRAM_KEYWORDS = ["流程", "结构", "分类", "因果", "步骤", "阅读结构", "知识图谱", "体系", "过程"]
GAME_KEYWORDS = ["练习", "闯关", "匹配", "排序", "挑战", "小游戏", "巩固", "得分"]

PLANNING_SYSTEM_PROMPT_TEMPLATE = """你是资深互动教学课件规划师。
为 12~18 岁学生设计一个 OpenMAIC 风格的单页 interactive widget 计划。

规划原则：
- page_type 固定为 interactive。
- interactive_type 只能是 simulation、diagram、game。
- 输出必须同时具备 OpenMAIC 两层结构：scene_outline 描述课堂场景，interactive_spec 描述可直接生成 HTML 的 WidgetConfig。
- scene_outline 必须包含 id、type、title、description、keyPoints、order、widgetType、widgetOutline；widgetType 必须与 interactive_type 一致。
- interactive_spec 是 OpenMAIC WidgetOutline + WidgetConfig 的单页化核心，必须能直接嵌入 HTML 的 script#widget-config。
- simulation: interactive_spec 必须写 type、concept、description、variables、presets、observations；变量 name 要可作为 slider id/data-var。
- diagram: interactive_spec 必须写 type、concept、description、nodes、edges、reveal_order；nodes 每项必须有 id、label、details/explanation。
- game: interactive_spec 必须写 type、concept、description、game_type、challenge、success_condition、feedback_rules、game_config；必须是操作型挑战，不是普通选择题堆叠。
- teaching_flow 用 3~5 个教学节奏步骤描述观察、操作、归纳。
- controls 只保留真实影响学习的控件，2~5 个。
- runtime.render_stack 只能是 svg、svg_canvas、canvas_svg、dom_svg；runtime.animation_runtime 固定为 native。
- stage_layout 必须说明目标区、主舞台、控制区和结论区如何在单屏内摆放。
- stage_layout 必须明确公式、读数、caption 与控制面板不进入主舞台覆盖层；主舞台只放图形和短标签。
- design_brief 必须写出主舞台对象、布局坐标/相对位置、颜色语义、动态更新规则、默认预设和验收标准。
- widget_actions 必须给出 OpenMAIC iframe action 示例，至少覆盖 widget_setState、widget_highlight、widget_annotation、widget_reveal。

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
page_type、interactive_type、widget_type、scene_outline、subject、title、goal、learner_level、stage_layout、
key_points、design_brief、interactive_spec、widget_outline、widget_actions、teaching_flow、controls、formulas、runtime、primary_color。
widget_type 必须与 interactive_type 相同；widget_outline 用于概括主舞台对象、状态机、可观察变化和必须响应的 action，不替代 interactive_spec。
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
    widget_outline = _normalize_widget_outline(raw.get("widget_outline"), interactive_spec, interactive_type, topic)
    key_points = _string_list(raw.get("key_points") or raw.get("keyPoints"), fallback["key_points"], max_items=6, max_len=120)
    scene_outline = _normalize_scene_outline(raw.get("scene_outline"), fallback["scene_outline"], interactive_type, topic, key_points, widget_outline)
    design_brief = _normalize_design_brief(raw.get("design_brief"), fallback["design_brief"])

    return {
        "page_type": "interactive",
        "interactive_type": interactive_type,
        "widget_type": interactive_type,
        "scene_outline": scene_outline,
        "subject": subject,
        "title": (_safe_str(raw.get("title")) or fallback["title"])[:48],
        "goal": (_safe_str(raw.get("goal")) or fallback["goal"])[:180],
        "learner_level": (_safe_str(raw.get("learner_level")) or "初中/高中")[:24],
        "stage_layout": (_safe_str(raw.get("stage_layout")) or fallback["stage_layout"])[:220],
        "key_points": key_points,
        "design_brief": design_brief,
        "interactive_spec": interactive_spec,
        "widget_outline": widget_outline,
        "widget_actions": _normalize_widget_actions(raw.get("widget_actions"), fallback["widget_actions"], interactive_spec, interactive_type),
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
    interactive_spec = _default_interactive_spec(topic, interactive_type)
    key_points = _default_key_points(topic, interactive_type)
    widget_outline = _normalize_widget_outline(None, interactive_spec, interactive_type, topic)
    if _is_pythagorean_topic(topic):
        render_stack = "svg"
        widget_outline = {
            "type": "simulation",
            "topic": topic,
            "intent": "single_page_openmaic_widget",
            "concept": "勾股定理的几何证明",
            "core_objects": ["直角三角形", "a² 正方形", "b² 正方形", "c² 正方形"],
            "keyVariables": ["a（直角边1）", "b（直角边2）"],
            "state_model": ["观察三边", "调节边长", "比较面积", "归纳公式"],
            "observable_changes": ["三角形边长实时变化", "三个正方形面积数值同步更新", "a²+b² 与 c² 比较结果保持相等"],
            "required_regions": ["learning-goal", "stage", "controls", "caption", "formula"],
        }
    return {
        "page_type": "interactive",
        "interactive_type": interactive_type,
        "widget_type": interactive_type,
        "scene_outline": _default_scene_outline(topic, interactive_type, key_points, widget_outline),
        "subject": subject,
        "title": f"{topic}互动课件",
        "goal": f'通过单页互动操作理解"{topic}"的关键概念和变化规律。',
        "learner_level": "初中/高中",
        "stage_layout": "顶部展示学习目标，中间为主舞台，底部放置控制区、当前说明和结论区，移动端纵向堆叠但保持主视觉优先。",
        "key_points": key_points,
        "design_brief": _default_design_brief(topic, interactive_type),
        "interactive_spec": interactive_spec,
        "widget_outline": widget_outline,
        "widget_actions": _default_widget_actions(interactive_spec, interactive_type),
        "teaching_flow": [
            {"id": "observe", "label": "观察初始状态", "focus": "核心对象和变量被清晰标注", "caption": "先观察页面中哪些对象会发生变化。"},
            {"id": "interact", "label": "操作互动控件", "focus": "学生调节参数或逐步揭示内容", "caption": "再通过控件改变状态，比较不同结果。"},
            {"id": "conclude", "label": "归纳结论", "focus": "图形、数值和结论同步高亮", "caption": "最后把观察结果和核心规律对应起来。"},
        ],
        "controls": _default_controls(interactive_type, topic),
        "formulas": _default_formulas(topic, subject),
        "runtime": {
            "render_stack": render_stack,
            "animation_runtime": animation_runtime,
            "external_libraries": [],
        },
        "primary_color": primary_color,
    }


def _default_interactive_spec(topic: str, interactive_type: str) -> dict:
    if interactive_type == "simulation":
        if _is_pythagorean_topic(topic):
            return {
                "type": "simulation",
                "concept": "勾股定理的几何证明",
                "description": "学生通过拖动直角边 a 和 b，观察 a²、b² 与 c² 三个正方形面积关系。",
                "variables": [
                    {"name": "a", "label": "直角边 a", "min": 3, "max": 9, "default": 6, "step": 0.5, "unit": ""},
                    {"name": "b", "label": "直角边 b", "min": 4, "max": 12, "default": 8, "step": 0.5, "unit": ""},
                ],
                "presets": [
                    {"id": "triple-345", "label": "3-4-5", "values": {"a": 3, "b": 4}},
                    {"id": "triple-51213", "label": "5-12-13", "values": {"a": 5, "b": 12}},
                    {"id": "triple-6810", "label": "6-8-10", "values": {"a": 6, "b": 8}},
                    {"id": "isosceles", "label": "等腰直角", "values": {"a": 6, "b": 6}},
                    {"id": "triple-72425", "label": "7-24-25", "values": {"a": 7, "b": 24}},
                ],
                "observations": [
                    "直角三角形两条直角边改变时，斜边 c 按 c=√(a²+b²) 同步变化。",
                    "红色 a² 正方形、青色 b² 正方形和紫色 c² 正方形面积读数同步更新。",
                    "无论怎样调节，a²+b² 的结果都与 c² 相等。",
                ],
                "visual_model": {
                    "kind": "right_triangle_with_squares",
                    "stage": "grid_svg",
                    "triangle": {"right_angle_vertex": "O", "legs": ["a", "b"], "hypotenuse": "c"},
                    "squares": [
                        {"id": "square-a", "attached_to": "a", "area": "a²", "color_role": "red"},
                        {"id": "square-b", "attached_to": "b", "area": "b²", "color_role": "cyan"},
                        {"id": "square-c", "attached_to": "c", "area": "c²", "color_role": "violet"},
                    ],
                    "labels": ["a = {a}", "b = {b}", "c = √(a²+b²)", "a² + b² = c²"],
                },
            }
        return {
            "type": "simulation",
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
            "type": "game",
            "concept": topic,
            "description": "学生完成一个与知识点直接相关的互动挑战。",
            "game_type": "manipulation",
            "challenge": "根据提示完成匹配、排序或选择策略。",
            "success_condition": "所有关键对象放入正确位置并能解释原因。",
            "feedback_rules": ["正确时显示原因解释", "错误时高亮冲突点并给出提示"],
            "game_config": {
                "controls": ["drag", "check", "reset"],
                "fair_start": "默认状态没有失败条件，学生先观察目标再开始操作。",
                "levels": [{"id": "level-1", "label": "基础挑战"}],
            },
        }
    return {
        "type": "diagram",
        "concept": topic,
        "description": "学生逐步揭示节点和关系，理解整体结构。",
        "nodes": [
            {"id": "core", "label": topic, "details": "核心概念", "explanation": "核心概念"},
            {"id": "cause", "label": "关键原因", "details": "导致变化或形成结构的主要因素", "explanation": "导致变化或形成结构的主要因素"},
            {"id": "result", "label": "结果结论", "details": "最终需要掌握的规律", "explanation": "最终需要掌握的规律"},
        ],
        "edges": [{"from": "cause", "to": "core"}, {"from": "core", "to": "result"}],
        "reveal_order": ["core", "cause", "result"],
    }


def _default_controls(interactive_type: str, topic: str = "") -> list[dict]:
    if interactive_type == "simulation":
        if _is_pythagorean_topic(topic):
            return [
                {"id": "a-slider", "label": "直角边 a", "type": "slider", "bind": "a"},
                {"id": "b-slider", "label": "直角边 b", "type": "slider", "bind": "b"},
                {"id": "play-animation", "label": "启动演示", "type": "button", "action": "play"},
                {"id": "pause-animation", "label": "暂停", "type": "button", "action": "pause"},
                {"id": "reset-animation", "label": "重置", "type": "button", "action": "reset"},
            ]
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
    spec["type"] = interactive_type
    spec.setdefault("concept", topic)
    spec.setdefault("description", default.get("description"))
    if interactive_type == "simulation":
        variables = spec.get("variables")
        spec["variables"] = variables if isinstance(variables, list) and variables else default.get("variables", [])
        observations = spec.get("observations")
        spec["observations"] = observations if isinstance(observations, list) and observations else default.get("observations", [])
        presets = spec.get("presets")
        spec["presets"] = presets if isinstance(presets, list) and presets else default.get("presets", [])
        if _is_pythagorean_topic(topic):
            spec = _enrich_pythagorean_spec(spec, default)
    elif interactive_type == "diagram":
        for field in ("nodes", "edges", "reveal_order"):
            value = spec.get(field)
            spec[field] = value if isinstance(value, list) and value else default.get(field, [])
        spec["nodes"] = [_normalize_diagram_node(node, index) for index, node in enumerate(spec["nodes"])]
        spec["edges"] = [_normalize_diagram_edge(edge) for edge in spec["edges"]]
    else:
        spec.setdefault("challenge", default.get("challenge"))
        spec.setdefault("success_condition", default.get("success_condition"))
        spec.setdefault("game_type", default.get("game_type", "manipulation"))
        spec.setdefault("game_config", default.get("game_config", {}))
        rules = spec.get("feedback_rules")
        spec["feedback_rules"] = rules if isinstance(rules, list) and rules else default.get("feedback_rules", [])
    return spec


def _enrich_pythagorean_spec(spec: dict, default: dict) -> dict:
    names = {str(item.get("name") or "") for item in spec.get("variables", []) if isinstance(item, dict)}
    if not {"a", "b"}.issubset(names):
        spec["variables"] = default.get("variables", [])
    if len(spec.get("presets", [])) < 3:
        spec["presets"] = default.get("presets", [])
    spec.setdefault("visual_model", default.get("visual_model", {}))
    spec["concept"] = "勾股定理的几何证明"
    spec["description"] = "学生通过拖动直角边 a 和 b，观察 a²、b² 与 c² 三个正方形面积关系。"
    return spec


def _normalize_widget_outline(raw_outline: object, interactive_spec: dict, interactive_type: str, topic: str) -> dict:
    outline = dict(raw_outline) if isinstance(raw_outline, dict) else {}
    outline["type"] = interactive_type
    outline.setdefault("topic", topic)
    outline.setdefault("intent", "single_page_openmaic_widget")
    outline.setdefault("concept", interactive_spec.get("concept") or topic)
    if interactive_type == "simulation":
        outline.setdefault("core_objects", [item.get("name") for item in interactive_spec.get("variables", []) if isinstance(item, dict)] or ["parameter"])
        outline.setdefault("state_model", ["running", "paused", "ended"])
        outline.setdefault("observable_changes", interactive_spec.get("observations") or ["参数变化驱动画面、读数和结论同步变化"])
    elif interactive_type == "diagram":
        outline.setdefault("core_objects", [item.get("id") for item in interactive_spec.get("nodes", []) if isinstance(item, dict)] or ["core"])
        outline.setdefault("state_model", ["hidden", "revealed", "highlighted"])
        outline.setdefault("observable_changes", ["节点逐步揭示", "关系连线高亮", "说明同步更新"])
    else:
        outline.setdefault("core_objects", ["challenge", "choice", "feedback"])
        outline.setdefault("state_model", ["ready", "playing", "success"])
        outline.setdefault("observable_changes", ["操作对象移动", "结果即时反馈", "成功条件高亮"])
    outline.setdefault("required_regions", ["learning-goal", "stage", "controls", "caption", "formula"])
    return outline


def _normalize_diagram_node(node: object, index: int) -> dict:
    if not isinstance(node, dict):
        return {"id": f"node-{index + 1}", "label": f"节点{index + 1}", "details": "观察该节点的含义。", "explanation": "观察该节点的含义。"}
    node_id = re.sub(r"[^a-zA-Z0-9_-]+", "-", _safe_str(node.get("id")) or f"node-{index + 1}").strip("-")
    label = (_safe_str(node.get("label")) or node_id or f"节点{index + 1}")[:32]
    details = (_safe_str(node.get("details")) or _safe_str(node.get("explanation")) or "观察该节点的含义。")[:160]
    return {"id": node_id or f"node-{index + 1}", "label": label, "details": details, "explanation": details}


def _normalize_diagram_edge(edge: object) -> dict:
    if not isinstance(edge, dict):
        return {"from": "core", "to": "result"}
    source = _safe_str(edge.get("from") or edge.get("source")) or "core"
    target = _safe_str(edge.get("to") or edge.get("target")) or "result"
    normalized = {"from": source, "to": target}
    label = _safe_str(edge.get("label"))
    if label:
        normalized["label"] = label[:32]
    return normalized


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


def _is_pythagorean_topic(topic: str) -> bool:
    text = (topic or "").lower()
    return "勾股" in text or "pythagorean" in text


def _default_key_points(topic: str, interactive_type: str) -> list[str]:
    if _is_pythagorean_topic(topic):
        return [
            "操作说明：调整直角边 a 和 b 的长度",
            "观察 a²、b²、c² 三个正方形面积同步变化",
            "比较 a²+b² 与 c² 的数值始终相等",
            "理解面积法证明勾股定理的本质",
        ]
    if interactive_type == "simulation":
        return ["识别可调变量", "观察变量改变后的画面变化", "把读数变化与核心规律对应起来"]
    if interactive_type == "game":
        return ["明确挑战目标", "操作对象完成任务", "根据即时反馈修正策略"]
    return ["识别核心节点", "逐步揭示关系", "归纳结构性结论"]


def _default_formulas(topic: str, subject: str) -> list[str]:
    if _is_pythagorean_topic(topic):
        return ["a^2+b^2=c^2", "c=\\sqrt{a^2+b^2}", "S_{a^2}+S_{b^2}=S_{c^2}"]
    return [topic] if subject == "math" else []


def _default_scene_outline(topic: str, interactive_type: str, key_points: list[str], widget_outline: dict) -> dict:
    return {
        "id": "scene_1",
        "type": "interactive",
        "title": f"{topic}互动证明" if _is_pythagorean_topic(topic) else f"{topic}互动课件",
        "description": (
            "学生通过拖动滑块改变直角边长度，观察面积关系，直观理解定理。"
            if _is_pythagorean_topic(topic)
            else f"学生通过互动操作观察{topic}的关键变化。"
        ),
        "keyPoints": key_points,
        "order": 1,
        "widgetType": interactive_type,
        "widgetOutline": widget_outline,
    }


def _normalize_scene_outline(
    raw_outline: object,
    default: dict,
    interactive_type: str,
    topic: str,
    key_points: list[str],
    widget_outline: dict,
) -> dict:
    outline = dict(raw_outline) if isinstance(raw_outline, dict) else dict(default)
    outline["type"] = "interactive"
    outline["widgetType"] = interactive_type
    outline.setdefault("id", "scene_1")
    outline.setdefault("title", default.get("title") or f"{topic}互动课件")
    outline.setdefault("description", default.get("description") or f"学生通过互动操作观察{topic}。")
    raw_key_points = outline.get("keyPoints") or outline.get("key_points")
    outline["keyPoints"] = _string_list(raw_key_points, key_points, max_items=6, max_len=120)
    outline["order"] = int(outline.get("order") or 1)
    outline["widgetOutline"] = dict(outline.get("widgetOutline")) if isinstance(outline.get("widgetOutline"), dict) else widget_outline
    return outline


def _default_design_brief(topic: str, interactive_type: str) -> dict[str, Any]:
    if _is_pythagorean_topic(topic):
        return {
            "layout": "左侧控制面板，右侧大网格 SVG 舞台；控制面板不覆盖主舞台。",
            "stage_objects": ["right-triangle", "square-a", "square-b", "square-c", "area-readout", "formula-proof"],
            "visual_rules": [
                "直角顶点固定，a 沿水平轴、b 沿竖直轴缩放，斜边 c 自动重算。",
                "a² 正方形用红色，b² 正方形用青色，c² 正方形用紫色半透明斜放。",
                "舞台标签只显示短文本，完整公式和读数放在侧栏或 HUD。",
            ],
            "state_updates": [
                "slider a/b input 触发 updateGeometry",
                "updateGeometry 同步 SVG points、square polygons、label、readout 和 caption",
                "presets 通过 SET_WIDGET_STATE 或按钮写入 a/b 并派发 input/change",
            ],
            "acceptance": ["默认 6-8-10 可见", "拖动 a/b 后 a²+b² 与 c² 始终一致", "支持四类 widget action"],
        }
    return {
        "layout": "单屏分区布局，主舞台、控制区、caption 和公式区互不遮挡。",
        "stage_objects": ["main-visual", "control-panel", "caption", "formula"],
        "visual_rules": ["主舞台展示核心对象", "控制区只放真实影响学习的控件", "caption 随状态变化"],
        "state_updates": ["控件改变 widget state", "运行时同步图形、读数和说明"],
        "acceptance": ["默认状态可理解", "播放/暂停/重置可用", "支持四类 widget action"],
    }


def _normalize_design_brief(raw_brief: object, default: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw_brief, dict):
        return dict(default)
    brief = dict(default)
    for key, value in raw_brief.items():
        if isinstance(value, (str, int, float, bool, list, dict)):
            brief[str(key)] = value
    return brief


def _default_widget_actions(interactive_spec: dict, interactive_type: str) -> list[dict[str, Any]]:
    state: dict[str, Any] = {}
    if interactive_type == "simulation":
        for variable in interactive_spec.get("variables", []):
            if isinstance(variable, dict) and variable.get("name"):
                state[str(variable["name"])] = variable.get("default", 1)
    return [
        {"type": "widget_setState", "state": state or {"parameter": 1}, "content": "同步当前互动变量。"},
        {"type": "widget_highlight", "target": "[data-role='main-visual']", "content": "高亮主视觉。"},
        {"type": "widget_annotation", "target": "[data-region='caption']", "content": "补充教师讲解标注。"},
        {"type": "widget_reveal", "target": "[data-role='main-visual']", "content": "揭示当前关键元素。"},
    ]


def _normalize_widget_actions(
    raw_actions: object,
    default: list[dict[str, Any]],
    interactive_spec: dict,
    interactive_type: str,
) -> list[dict[str, Any]]:
    source = raw_actions if isinstance(raw_actions, list) and raw_actions else default
    actions = [dict(action) for action in source[:6] if isinstance(action, dict)]
    found = {str(action.get("type") or "") for action in actions}
    required = {"widget_setState", "widget_highlight", "widget_annotation", "widget_reveal"}
    if not required.issubset(found):
        actions = _default_widget_actions(interactive_spec, interactive_type)
    return actions
