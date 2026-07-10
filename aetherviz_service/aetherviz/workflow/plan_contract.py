"""Plan contract helpers for single-page interactive content."""

from __future__ import annotations

import json
import re
from typing import Any

from aetherviz_service.aetherviz.constants import get_gsap_core_cdn_url

DEFAULT_PRIMARY_COLOR = "#22D3EE"

SUBJECT_KEYWORDS = {
    "math": ["数学", "几何", "函数", "方程", "概率", "统计", "面积", "体积", "坐标", "圆", "抛物线", "定理", "证明", "公式"],
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
VALID_ANIMATION_RUNTIMES = {"native", "gsap"}
REQUIRED_RUNTIME_CONTROLS = (
    {"id": "play-animation", "label": "播放", "type": "button", "action": "play"},
    {"id": "pause-animation", "label": "暂停", "type": "button", "action": "pause"},
    {"id": "reset-animation", "label": "重置", "type": "button", "action": "reset"},
)

SIMULATION_KEYWORDS = ["运动", "参数", "实验", "函数", "概率", "反应速率", "电路", "轨迹", "速度", "采样"]
DIAGRAM_KEYWORDS = ["流程", "结构", "分类", "因果", "步骤", "阅读结构", "知识图谱", "体系", "过程"]
GAME_KEYWORDS = ["练习", "闯关", "匹配", "排序", "挑战", "小游戏", "巩固", "得分"]

PLANNING_SYSTEM_PROMPT_TEMPLATE = """你是互动教学课件规划器，为 12~18 岁学生设计单页 interactive widget。

仅输出一个合法 JSON 对象，不输出 Markdown、解释、推理过程或未定义字段。
只生成教学语义字段；page_type、widget_type、scene_outline、widget_outline、widget_actions、runtime、subject、primary_color 由服务端确定性补齐。

JSON 顶层字段必须且只能包含：
- interactive_type：固定为 {interactive_type}
- title：不超过 24 个汉字
- goal：一个可观察、可验证的学习目标
- learner_level：简短学段
- stage_layout：字符串，说明目标区、主舞台、控制区和结论区；公式、读数和控制面板不得覆盖主舞台
- key_points：2~4 个字符串
- design_brief：只含 layout、stage_objects、visual_rules、state_updates、default_preset、acceptance
- interactive_spec：严格使用下方 {interactive_type} 规格
- teaching_flow：3~4 项，每项只含 id、label、focus、caption
- controls：只生成 1~2 个真实影响学习的控件，每项只含 id、label、type、bind；不要生成播放、暂停、重置按钮
- formulas：0~3 个字符串

一致性要求：
- controls[].bind 必须等于 interactive_spec 中一个可调变量 name；无可调变量时 controls 输出空数组。
- preset 的每个值必须落在对应变量 min/max 范围内。
- 所有 id 使用小写英文、数字、连字符或下划线，引用必须存在。
- design_brief 必须明确主舞台对象、相对位置、颜色语义、动态更新、默认状态和验收标准。

{type_contract}
"""

INTERACTIVE_TYPE_CONTRACTS = {
    "simulation": """simulation 的 interactive_spec 只含：
- type：固定 simulation
- concept、description
- variables：1~3 项；每项包含 name、label、min、max、step、default、unit，可额外包含 computed、expression
- presets：1~3 项；每项使用 id、label、values，values 的 key 必须引用 variables.name
- observations：2~4 个可观察现象""",
    "diagram": """diagram 的 interactive_spec 只含：
- type：固定 diagram
- concept、description
- nodes：3~7 项，每项只含 id、label、details、explanation
- edges：每项只含 from、to，可选 label；from/to 必须引用 nodes.id
- reveal_order：按揭示顺序列出全部 nodes.id""",
    "game": """game 的 interactive_spec 只含：
- type：固定 game
- concept、description、game_type、challenge、success_condition
- feedback_rules：2~4 个字符串
- game_config：操作型挑战配置，必须包含 controls、fair_start、levels；不得退化为普通选择题堆叠""",
}


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


def select_animation_runtime() -> str:
    return "gsap"


def build_planning_prompt(
    topic: str,
    primary_color: str,
    *,
    interactive_type_override: str | None = None,
    subject_override: str | None = None,
) -> tuple[str, str]:
    subject = subject_override if subject_override in {*SUBJECT_KEYWORDS, "astronomy", "general"} else detect_subject(topic)
    interactive_type = (
        interactive_type_override
        if interactive_type_override in VALID_INTERACTIVE_TYPES
        else select_interactive_type(topic, subject)
    )
    render_stack = select_render_stack(interactive_type, subject, topic)
    animation_runtime = select_animation_runtime()
    system_prompt = PLANNING_SYSTEM_PROMPT_TEMPLATE.format(
        interactive_type=interactive_type,
        type_contract=INTERACTIVE_TYPE_CONTRACTS[interactive_type],
    )
    user_prompt = f"""生成以下主题的完整教学语义 JSON。

主题：{topic}
服务端学科识别：{subject}
固定互动类型：{interactive_type}
服务端渲染栈：{render_stack}
服务端动画运行时：{animation_runtime}
主色调：{primary_color}
"""
    return system_prompt, user_prompt


def select_revision_interactive_type(current_type: object, message: str, topic: str) -> str:
    text = (message or "").lower()
    for interactive_type, keywords in (
        ("game", GAME_KEYWORDS),
        ("diagram", DIAGRAM_KEYWORDS),
        ("simulation", SIMULATION_KEYWORDS),
    ):
        if any(keyword in text for keyword in keywords):
            return interactive_type
    current = _safe_str(current_type)
    if current in VALID_INTERACTIVE_TYPES:
        return current
    subject = detect_subject(topic)
    return select_interactive_type(topic, subject)


def compact_plan_for_revision(plan: dict[str, Any]) -> dict[str, Any]:
    semantic_fields = (
        "interactive_type",
        "title",
        "goal",
        "learner_level",
        "stage_layout",
        "key_points",
        "design_brief",
        "interactive_spec",
        "teaching_flow",
        "controls",
        "formulas",
    )
    return {field: plan[field] for field in semantic_fields if field in plan}


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
    baseline = _default_plan(topic, primary_color)

    subject = _safe_str(raw.get("subject")) or baseline["subject"]
    if subject not in {*SUBJECT_KEYWORDS.keys(), "astronomy", "general"}:
        subject = baseline["subject"]

    interactive_type = _safe_str(raw.get("interactive_type")) or baseline["interactive_type"]
    if interactive_type not in VALID_INTERACTIVE_TYPES:
        interactive_type = select_interactive_type(topic, subject)

    runtime_raw = raw.get("runtime") if isinstance(raw.get("runtime"), dict) else {}
    render_stack = _safe_str(runtime_raw.get("render_stack") or raw.get("render_stack")) or select_render_stack(interactive_type, subject, topic)
    if render_stack not in VALID_RENDER_STACKS:
        render_stack = select_render_stack(interactive_type, subject, topic)
    animation_runtime = _safe_str(runtime_raw.get("animation_runtime") or raw.get("animation_runtime")) or select_animation_runtime()
    if animation_runtime not in VALID_ANIMATION_RUNTIMES:
        animation_runtime = select_animation_runtime()

    interactive_spec = _normalize_interactive_spec(raw.get("interactive_spec"), baseline["interactive_spec"], interactive_type, topic)
    teaching_flow = _normalize_teaching_flow(raw.get("teaching_flow"), baseline["teaching_flow"])
    widget_outline = _normalize_widget_outline(raw.get("widget_outline"), interactive_spec, interactive_type, topic)
    key_points = _string_list(raw.get("key_points") or raw.get("keyPoints"), baseline["key_points"], max_items=6, max_len=120)
    scene_outline = _normalize_scene_outline(raw.get("scene_outline"), baseline["scene_outline"], interactive_type, topic, key_points, widget_outline)
    design_brief = _normalize_design_brief(raw.get("design_brief"), baseline["design_brief"])
    variable_names = {
        _safe_str(variable.get("name"))
        for variable in interactive_spec.get("variables", [])
        if isinstance(variable, dict) and not variable.get("computed") and _safe_str(variable.get("name"))
    }
    title = (_safe_str(raw.get("title")) or baseline["title"])[:48]
    if not isinstance(raw.get("scene_outline"), dict):
        scene_outline["title"] = title

    return {
        "page_type": "interactive",
        "interactive_type": interactive_type,
        "widget_type": interactive_type,
        "scene_outline": scene_outline,
        "subject": subject,
        "title": title,
        "goal": (_safe_str(raw.get("goal")) or baseline["goal"])[:180],
        "learner_level": (_safe_str(raw.get("learner_level")) or "初中/高中")[:24],
        "stage_layout": _normalize_stage_layout(raw.get("stage_layout"), baseline["stage_layout"]),
        "key_points": key_points,
        "design_brief": design_brief,
        "interactive_spec": interactive_spec,
        "widget_outline": widget_outline,
        "widget_actions": _normalize_widget_actions(raw.get("widget_actions"), baseline["widget_actions"], interactive_spec, interactive_type),
        "teaching_flow": teaching_flow,
        "controls": _normalize_controls(raw.get("controls"), baseline["controls"], valid_bindings=variable_names),
        "formulas": _string_list(raw.get("formulas"), baseline["formulas"], max_items=5, max_len=100),
        "runtime": {
            "render_stack": render_stack,
            "animation_runtime": animation_runtime,
            "external_libraries": _normalize_external_libraries(runtime_raw.get("external_libraries"), animation_runtime),
        },
        "primary_color": _safe_str(raw.get("primary_color")) or primary_color,
    }


def _default_plan(topic: str, primary_color: str) -> dict:
    subject = detect_subject(topic)
    interactive_type = select_interactive_type(topic, subject)
    render_stack = select_render_stack(interactive_type, subject, topic)
    animation_runtime = select_animation_runtime()
    interactive_spec = _default_interactive_spec(topic, interactive_type)
    key_points = _default_key_points(topic, interactive_type)
    widget_outline = _normalize_widget_outline(None, interactive_spec, interactive_type, topic)
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
            "external_libraries": _normalize_external_libraries([], animation_runtime),
        },
        "primary_color": primary_color,
    }


def _default_interactive_spec(topic: str, interactive_type: str) -> dict:
    if interactive_type == "simulation":
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
        return [
            {"id": "parameter-slider", "label": "关键参数", "type": "slider", "bind": "parameter"},
            *[dict(control) for control in REQUIRED_RUNTIME_CONTROLS],
        ]
    if interactive_type == "game":
        return [
            {"id": "start-button", "label": "开始挑战", "type": "button", "action": "start"},
            *[dict(control) for control in REQUIRED_RUNTIME_CONTROLS],
        ]
    return [
        {"id": "next-button", "label": "下一步", "type": "button", "action": "next"},
        *[dict(control) for control in REQUIRED_RUNTIME_CONTROLS],
    ]


def _normalize_interactive_spec(raw_spec: object, default: dict, interactive_type: str, topic: str) -> dict:
    if not isinstance(raw_spec, dict):
        return dict(default)
    spec = dict(raw_spec)
    spec["type"] = interactive_type
    spec.setdefault("concept", topic)
    spec.setdefault("description", default.get("description"))
    if interactive_type == "simulation":
        variables, bounds = _normalize_simulation_variables(spec.get("variables"), default.get("variables", []))
        spec["variables"] = variables
        spec["presets"] = _normalize_simulation_presets(spec.get("presets"), default.get("presets", []), bounds)
        spec["observations"] = _string_list(
            spec.get("observations"),
            default.get("observations", []),
            max_items=4,
            max_len=140,
        )
    elif interactive_type == "diagram":
        for field in ("nodes", "edges", "reveal_order"):
            value = spec.get(field)
            spec[field] = value if isinstance(value, list) and value else default.get(field, [])
        spec["nodes"] = [_normalize_diagram_node(node, index) for index, node in enumerate(spec["nodes"])]
        node_ids = [node["id"] for node in spec["nodes"]]
        valid_node_ids = set(node_ids)
        edges = [_normalize_diagram_edge(edge) for edge in spec["edges"]]
        spec["edges"] = [
            edge
            for edge in edges
            if edge["from"] in valid_node_ids and edge["to"] in valid_node_ids and edge["from"] != edge["to"]
        ]
        raw_reveal_order = [_safe_str(item) for item in spec["reveal_order"]]
        reveal_order = list(dict.fromkeys(item for item in raw_reveal_order if item in valid_node_ids))
        spec["reveal_order"] = [*reveal_order, *[node_id for node_id in node_ids if node_id not in reveal_order]]
    else:
        spec.setdefault("challenge", default.get("challenge"))
        spec.setdefault("success_condition", default.get("success_condition"))
        spec.setdefault("game_type", default.get("game_type", "manipulation"))
        spec.setdefault("game_config", default.get("game_config", {}))
        rules = spec.get("feedback_rules")
        spec["feedback_rules"] = rules if isinstance(rules, list) and rules else default.get("feedback_rules", [])
    return spec


def _normalize_simulation_variables(
    raw_variables: object,
    default: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, tuple[float, float]]]:
    source = raw_variables if isinstance(raw_variables, list) and raw_variables else default
    variables: list[dict[str, Any]] = []
    bounds: dict[str, tuple[float, float]] = {}
    seen: set[str] = set()
    for index, item in enumerate(source[:3]):
        if not isinstance(item, dict):
            continue
        name = re.sub(r"[^a-zA-Z0-9_-]+", "-", _safe_str(item.get("name")) or f"variable-{index + 1}").strip("-")
        if not name or name in seen:
            continue
        seen.add(name)
        variable: dict[str, Any] = {
            "name": name,
            "label": (_safe_str(item.get("label")) or name)[:32],
        }
        if bool(item.get("computed")):
            variable["computed"] = True
            expression = _safe_str(item.get("expression"))
            if expression:
                variable["expression"] = expression[:160]
            variables.append(variable)
            continue
        minimum = _safe_number(item.get("min"), 0)
        maximum = _safe_number(item.get("max"), max(minimum + 1, 10))
        if maximum < minimum:
            minimum, maximum = maximum, minimum
        default_value = _clamp(_safe_number(item.get("default"), minimum), minimum, maximum)
        step = _safe_number(item.get("step"), 1)
        if step <= 0:
            step = 1
        variable.update(
            {
                "min": minimum,
                "max": maximum,
                "step": step,
                "default": default_value,
                "unit": _safe_str(item.get("unit"))[:16],
            }
        )
        bounds[name] = (float(minimum), float(maximum))
        variables.append(variable)
    if variables:
        return variables, bounds
    return _normalize_simulation_variables(default, []) if default else ([], {})


def _normalize_simulation_presets(
    raw_presets: object,
    default: list[dict[str, Any]],
    bounds: dict[str, tuple[float, float]],
) -> list[dict[str, Any]]:
    source = raw_presets if isinstance(raw_presets, list) and raw_presets else default
    presets: list[dict[str, Any]] = []
    for index, item in enumerate(source[:3]):
        if not isinstance(item, dict):
            continue
        raw_values = item.get("values") if isinstance(item.get("values"), dict) else item
        values: dict[str, int | float] = {}
        for name, (minimum, maximum) in bounds.items():
            if name not in raw_values:
                continue
            value = _clamp(_safe_number(raw_values.get(name), minimum), minimum, maximum)
            values[name] = value
        if not values:
            continue
        preset_id = re.sub(
            r"[^a-zA-Z0-9_-]+",
            "-",
            _safe_str(item.get("id")) or f"preset-{index + 1}",
        ).strip("-")
        presets.append(
            {
                "id": preset_id or f"preset-{index + 1}",
                "label": (_safe_str(item.get("label")) or f"预设{index + 1}")[:32],
                "values": values,
            }
        )
    return presets


def _normalize_widget_outline(raw_outline: object, interactive_spec: dict, interactive_type: str, topic: str) -> dict:
    outline = dict(raw_outline) if isinstance(raw_outline, dict) else {}
    outline["type"] = interactive_type
    outline.setdefault("topic", topic)
    outline.setdefault("intent", "single_page_interactive_widget")
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
        step_id = re.sub(
            r"[^a-zA-Z0-9_-]+",
            "-",
            (_safe_str(item.get("id") or item.get("step")) or f"step-{index + 1}").lower(),
        ).strip("-")
        if step_id in seen:
            step_id = f"{step_id}-{index + 1}"
        seen.add(step_id)
        flow.append(
            {
                "id": step_id,
                "label": (_safe_str(item.get("label")) or f"第{index + 1}步")[:32],
                "focus": (_safe_str(item.get("focus") or item.get("instruction")) or "观察核心变化")[:140],
                "caption": (_safe_str(item.get("caption") or item.get("instruction")) or "观察当前步骤的关键变化。")[:140],
            }
        )
    return flow or list(default)


def _normalize_controls(
    raw_controls: object,
    default: list[dict],
    *,
    valid_bindings: set[str] | None = None,
) -> list[dict]:
    source = raw_controls if isinstance(raw_controls, list) and raw_controls else default
    controls: list[dict] = []
    seen: set[str] = set()
    lifecycle_actions = {"play", "pause", "reset"}
    lifecycle_ids = {control["id"] for control in REQUIRED_RUNTIME_CONTROLS}
    for index, item in enumerate(source):
        if not isinstance(item, dict):
            continue
        action = _safe_str(item.get("action")).lower()
        control_id = re.sub(r"[^a-zA-Z0-9_-]+", "-", (_safe_str(item.get("id")) or f"control-{index + 1}").lower()).strip("-")
        if action in lifecycle_actions or control_id in lifecycle_ids:
            continue
        control_type = _safe_str(item.get("type")).lower()
        if control_type not in {"slider", "button", "speed", "toggle", "select"}:
            control_type = "button"
        if control_id in seen:
            control_id = f"{control_id}-{index + 1}"
        seen.add(control_id)
        bind = _safe_str(item.get("bind") or item.get("target_var")) or None
        if valid_bindings is not None and bind not in valid_bindings:
            bind = None
        controls.append(
            {
                "id": control_id[:40],
                "label": (_safe_str(item.get("label")) or control_id)[:24],
                "type": control_type,
                "bind": bind,
                "action": action or None,
            }
        )
        if len(controls) == 2:
            break
    return [*controls, *[dict(control) for control in REQUIRED_RUNTIME_CONTROLS]]


def _normalize_stage_layout(value: object, default: str) -> str:
    if isinstance(value, dict):
        value = value.get("description") or value.get("layout")
    return (_safe_str(value) or default)[:220]


def _string_list(value: object, default: list[str], max_items: int, max_len: int = 60) -> list[str]:
    if not isinstance(value, list):
        return list(default[:max_items])
    items = [str(item).strip()[:max_len] for item in value if str(item).strip()]
    return items[:max_items] or list(default[:max_items])


def _normalize_external_libraries(value: object, animation_runtime: str) -> list[str]:
    libraries = _string_list(value, [], max_items=3, max_len=120)
    gsap_cdn_url = get_gsap_core_cdn_url()
    libraries = [library for library in libraries if "gsap" not in library.lower() or library == gsap_cdn_url]
    if animation_runtime == "gsap" and gsap_cdn_url not in libraries:
        return [gsap_cdn_url, *libraries][:3]
    if animation_runtime != "gsap":
        return [library for library in libraries if "gsap" not in library.lower()]
    return libraries


def _safe_str(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _safe_number(value: object, default: int | float) -> int | float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return value
    try:
        parsed = float(str(value))
    except (TypeError, ValueError):
        return default
    return int(parsed) if parsed.is_integer() else parsed


def _clamp(value: int | float, minimum: int | float, maximum: int | float) -> int | float:
    clamped = min(max(float(value), float(minimum)), float(maximum))
    return int(clamped) if clamped.is_integer() else clamped


def _default_key_points(topic: str, interactive_type: str) -> list[str]:
    if interactive_type == "simulation":
        return ["识别可调变量", "观察变量改变后的画面变化", "把读数变化与核心规律对应起来"]
    if interactive_type == "game":
        return ["明确挑战目标", "操作对象完成任务", "根据即时反馈修正策略"]
    return ["识别核心节点", "逐步揭示关系", "归纳结构性结论"]


def _default_formulas(topic: str, subject: str) -> list[str]:
    return [topic] if subject == "math" else []


def _default_scene_outline(topic: str, interactive_type: str, key_points: list[str], widget_outline: dict) -> dict:
    return {
        "id": "scene_1",
        "type": "interactive",
        "title": f"{topic}互动课件",
        "description": f"学生通过互动操作观察{topic}的关键变化。",
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
    return {
        "layout": "单屏分区布局，主舞台、控制区、caption 和公式区互不遮挡。",
        "stage_objects": ["main-visual", "control-panel", "caption", "formula"],
        "visual_rules": ["主舞台展示核心对象", "控制区只放真实影响学习的控件", "caption 随状态变化"],
        "state_updates": ["控件改变 widget state", "运行时同步图形、读数和说明"],
        "default_preset": "默认状态直接展示一个可理解、可操作的典型案例。",
        "acceptance": ["默认状态可理解", "播放/暂停/重置可用", "支持四类 widget action"],
    }


def _normalize_design_brief(raw_brief: object, default: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw_brief, dict):
        return dict(default)
    aliases = {
        "layout": ("layout", "layout_coordinates"),
        "stage_objects": ("stage_objects", "main_stage_objects"),
        "visual_rules": ("visual_rules", "color_semantics"),
        "state_updates": ("state_updates", "dynamic_update_rules"),
        "default_preset": ("default_preset",),
        "acceptance": ("acceptance", "acceptance_criteria"),
    }
    brief: dict[str, Any] = {}
    for canonical, candidates in aliases.items():
        value = next((raw_brief.get(candidate) for candidate in candidates if raw_brief.get(candidate) is not None), None)
        if value is None:
            value = default.get(canonical)
        if canonical in {"stage_objects", "visual_rules", "state_updates", "acceptance"}:
            if isinstance(value, list):
                brief[canonical] = [str(item).strip()[:160] for item in value[:8] if str(item).strip()]
            elif _safe_str(value):
                brief[canonical] = [_safe_str(value)[:160]]
            else:
                brief[canonical] = list(default.get(canonical, []))
        else:
            brief[canonical] = _safe_str(value)[:240]
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
    actions: list[dict[str, Any]] = []
    for item in source[:6]:
        if not isinstance(item, dict):
            continue
        action_type = _safe_str(item.get("type") or item.get("action"))
        params = item.get("params") if isinstance(item.get("params"), dict) else {}
        action: dict[str, Any] = {"type": action_type}
        if action_type == "widget_setState":
            state = item.get("state") if isinstance(item.get("state"), dict) else params
            action["state"] = dict(state)
        else:
            target = _safe_str(item.get("target") or params.get("elementId"))
            if target and not target.startswith(("#", ".", "[")):
                target = f"#{target}"
            action["target"] = target or "[data-role='main-visual']"
        action["content"] = _safe_str(item.get("content") or params.get("text"))[:160]
        actions.append(action)
    found = {str(action.get("type") or "") for action in actions}
    required = {"widget_setState", "widget_highlight", "widget_annotation", "widget_reveal"}
    if not required.issubset(found):
        actions = _default_widget_actions(interactive_spec, interactive_type)
    return actions
