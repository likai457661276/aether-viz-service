"""Teaching-layer plan normalization (user-facing fields only)."""

from __future__ import annotations

import re
from typing import Any

from aetherviz_service.aetherviz.workflow.plan_detection import (
    SUBJECT_KEYWORDS,
    VALID_INTERACTIVE_TYPES,
    detect_subject,
    select_interactive_type,
)
from aetherviz_service.aetherviz.workflow.plan_utils import (
    DEFAULT_PRIMARY_COLOR,
    clamp,
    normalize_primary_color,
    safe_number,
    safe_str,
    string_list,
)

# Runtime play/pause/reset belong on GenerationSpec.runtime_controls; flat merge
# re-injects them into plan.controls for HTML generation compatibility.
REQUIRED_RUNTIME_CONTROLS = (
    {"id": "play-animation", "label": "播放", "type": "button", "action": "play"},
    {"id": "pause-animation", "label": "暂停", "type": "button", "action": "pause"},
    {"id": "reset-animation", "label": "重置", "type": "button", "action": "reset"},
)

RUNTIME_CONTROL_IDS = frozenset(control["id"] for control in REQUIRED_RUNTIME_CONTROLS)
RUNTIME_CONTROL_ACTIONS = frozenset({"play", "pause", "reset"})


def learning_controls_only(controls: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Strip server runtime play/pause/reset from a controls list."""
    if not controls:
        return []
    result: list[dict[str, Any]] = []
    for item in controls:
        if not isinstance(item, dict):
            continue
        control_id = str(item.get("id") or "")
        action = str(item.get("action") or "").lower()
        if control_id in RUNTIME_CONTROL_IDS or action in RUNTIME_CONTROL_ACTIONS:
            continue
        result.append(dict(item))
    return result


def with_runtime_controls(learning_controls: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Compose flat-plan controls = learning controls + fixed runtime controls."""
    learning = learning_controls_only(learning_controls)
    return [*learning, *[dict(control) for control in REQUIRED_RUNTIME_CONTROLS]]


def normalize_teaching_plan(
    raw_plan: dict | None,
    topic: str,
    primary_color: str = DEFAULT_PRIMARY_COLOR,
) -> dict[str, Any]:
    """Normalize user-facing teaching fields from planner output or defaults."""
    raw = raw_plan if isinstance(raw_plan, dict) else {}
    primary_color = normalize_primary_color(primary_color, DEFAULT_PRIMARY_COLOR)
    source_topic = safe_str(raw.get("source_topic")) or topic
    # Subject is GenerationSpec-owned, but interactive_type selection historically
    # used the raw/detected subject hint for parity with the flat normalizer.
    subject_hint = safe_str(raw.get("subject")) or detect_subject(source_topic)
    if subject_hint not in {*SUBJECT_KEYWORDS.keys(), "astronomy", "general"}:
        subject_hint = detect_subject(source_topic)
    interactive_type = safe_str(raw.get("interactive_type")) or select_interactive_type(
        source_topic, subject_hint
    )
    if interactive_type not in VALID_INTERACTIVE_TYPES:
        interactive_type = select_interactive_type(source_topic, subject_hint)

    baseline_interactive = default_interactive_spec(source_topic, interactive_type)
    interactive_spec = normalize_interactive_spec(
        raw.get("interactive_spec"), baseline_interactive, interactive_type, source_topic
    )
    key_points = string_list(
        raw.get("key_points") or raw.get("keyPoints"),
        default_key_points(source_topic, interactive_type),
        max_items=6,
        max_len=120,
    )
    title = (safe_str(raw.get("title")) or f"{source_topic}互动课件")[:48]
    variable_names = {
        safe_str(variable.get("name"))
        for variable in interactive_spec.get("variables", [])
        if isinstance(variable, dict) and not variable.get("computed") and safe_str(variable.get("name"))
    }
    return {
        "source_topic": source_topic,
        "interactive_type": interactive_type,
        "title": title,
        "goal": (safe_str(raw.get("goal")) or f'通过单页互动操作理解"{source_topic}"的关键概念和变化规律。')[:180],
        "learner_level": (safe_str(raw.get("learner_level")) or "初中/高中")[:24],
        "stage_layout": normalize_stage_layout(
            raw.get("stage_layout"),
            "顶部展示学习目标，中间为主舞台，底部放置控制区、当前说明和结论区，移动端纵向堆叠但保持主视觉优先。",
        ),
        "key_points": key_points,
        "design_brief": normalize_design_brief(raw.get("design_brief"), default_design_brief(source_topic, interactive_type)),
        "interactive_spec": interactive_spec,
        "teaching_flow": normalize_teaching_flow(
            raw.get("teaching_flow"),
            default_teaching_flow(),
        ),
        "controls": normalize_controls(
            raw.get("controls"),
            default_controls(interactive_type),
            valid_bindings=variable_names,
        ),
        "formulas": string_list(
            raw.get("formulas"),
            default_formulas(source_topic, detect_subject(source_topic)),
            max_items=5,
            max_len=100,
        ),
        "primary_color": normalize_primary_color(raw.get("primary_color"), primary_color),
    }


def default_teaching_flow() -> list[dict[str, Any]]:
    return [
        {
            "id": "observe",
            "label": "观察初始状态",
            "focus": "核心对象和变量被清晰标注",
            "caption": "先观察页面中哪些对象会发生变化。",
        },
        {
            "id": "interact",
            "label": "操作互动控件",
            "focus": "学生调节参数或逐步揭示内容",
            "caption": "再通过控件改变状态，比较不同结果。",
        },
        {
            "id": "conclude",
            "label": "归纳结论",
            "focus": "图形、数值和结论同步高亮",
            "caption": "最后把观察结果和核心规律对应起来。",
        },
    ]


def default_interactive_spec(topic: str, interactive_type: str) -> dict:
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
            {
                "id": "cause",
                "label": "关键原因",
                "details": "导致变化或形成结构的主要因素",
                "explanation": "导致变化或形成结构的主要因素",
            },
            {"id": "result", "label": "结果结论", "details": "最终需要掌握的规律", "explanation": "最终需要掌握的规律"},
        ],
        "edges": [{"from": "cause", "to": "core"}, {"from": "core", "to": "result"}],
        "reveal_order": ["core", "cause", "result"],
    }


def default_controls(interactive_type: str) -> list[dict]:
    if interactive_type == "simulation":
        return [
            {"id": "parameter-slider", "label": "关键参数", "type": "slider", "bind": "parameter"},
        ]
    if interactive_type == "game":
        return [
            {"id": "start-button", "label": "开始挑战", "type": "button", "action": "start"},
        ]
    return [
        {"id": "next-button", "label": "下一步", "type": "button", "action": "next"},
    ]


def default_key_points(topic: str, interactive_type: str) -> list[str]:
    if interactive_type == "simulation":
        return ["识别可调变量", "观察变量改变后的画面变化", "把读数变化与核心规律对应起来"]
    if interactive_type == "game":
        return ["明确挑战目标", "操作对象完成任务", "根据即时反馈修正策略"]
    return ["识别核心节点", "逐步揭示关系", "归纳结构性结论"]


def default_formulas(topic: str, subject: str) -> list[str]:
    return [topic] if subject == "math" else []


def default_design_brief(topic: str, interactive_type: str) -> dict[str, Any]:
    return {
        "layout": "舞台优先的单屏自适应分区；宽屏可并排，空间不足时辅助区堆叠或折叠，且不挤压主舞台。",
        "stage_objects": ["main-visual", "control-panel", "caption", "formula"],
        "visual_rules": [
            "采用与前端一致的浅色教学工作台，白色纸张舞台、灰绿背景、深绿标题和绿色交互强调",
            "主题主色只用于主视觉对象、数据系列或少量互动强调，不铺满面板",
            "主舞台展示核心对象，控制区只放真实影响学习的控件，caption 随状态变化",
        ],
        "state_updates": ["控件改变 widget state", "运行时同步图形、读数和说明"],
        "default_preset": "默认状态直接展示一个可理解、可操作的典型案例。",
        "acceptance": ["默认状态可理解", "播放/暂停/重置可用", "支持四类 widget action"],
    }


def normalize_interactive_spec(raw_spec: object, default: dict, interactive_type: str, topic: str) -> dict:
    if not isinstance(raw_spec, dict):
        return dict(default)
    spec = dict(raw_spec)
    spec["type"] = interactive_type
    spec.setdefault("concept", topic)
    spec.setdefault("description", default.get("description"))
    if interactive_type == "simulation":
        variables, bounds = _normalize_simulation_variables(spec.get("variables"), default.get("variables", []))
        bounds = _expand_simulation_bounds_for_presets(variables, bounds, spec.get("presets"))
        spec["variables"] = variables
        spec["presets"] = _normalize_simulation_presets(spec.get("presets"), default.get("presets", []), bounds)
        spec["observations"] = string_list(
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
        raw_reveal_order = [safe_str(item) for item in spec["reveal_order"]]
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


def normalize_teaching_flow(raw_flow: object, default: list[dict]) -> list[dict]:
    source = raw_flow if isinstance(raw_flow, list) and raw_flow else default
    flow: list[dict] = []
    seen: set[str] = set()
    for index, item in enumerate(source[:5]):
        if not isinstance(item, dict):
            continue
        step_id = re.sub(
            r"[^a-zA-Z0-9_-]+",
            "-",
            (safe_str(item.get("id") or item.get("step")) or f"step-{index + 1}").lower(),
        ).strip("-")
        if step_id in seen:
            step_id = f"{step_id}-{index + 1}"
        seen.add(step_id)
        flow.append(
            {
                "id": step_id,
                "label": (safe_str(item.get("label")) or f"第{index + 1}步")[:32],
                "focus": (safe_str(item.get("focus") or item.get("instruction")) or "观察核心变化")[:140],
                "caption": (safe_str(item.get("caption") or item.get("instruction")) or "观察当前步骤的关键变化。")[
                    :140
                ],
            }
        )
    return flow or list(default)


def normalize_controls(
    raw_controls: object,
    default: list[dict],
    *,
    valid_bindings: set[str] | None = None,
) -> list[dict]:
    """Normalize learning controls only; runtime play/pause/reset belong to GenerationSpec merge."""
    source = raw_controls if isinstance(raw_controls, list) and raw_controls else default
    controls: list[dict] = []
    seen: set[str] = set()
    for index, item in enumerate(source):
        if not isinstance(item, dict):
            continue
        action = safe_str(item.get("action")).lower()
        control_id = re.sub(
            r"[^a-zA-Z0-9_-]+", "-", (safe_str(item.get("id")) or f"control-{index + 1}").lower()
        ).strip("-")
        if action in RUNTIME_CONTROL_ACTIONS or control_id in RUNTIME_CONTROL_IDS:
            continue
        control_type = safe_str(item.get("type")).lower()
        if control_type not in {"slider", "button", "speed", "toggle", "select"}:
            control_type = "button"
        if control_id in seen:
            control_id = f"{control_id}-{index + 1}"
        seen.add(control_id)
        bind = safe_str(item.get("bind") or item.get("target_var")) or None
        if valid_bindings is not None and bind not in valid_bindings:
            bind = None
        controls.append(
            {
                "id": control_id[:40],
                "label": (safe_str(item.get("label")) or control_id)[:24],
                "type": control_type,
                "bind": bind,
                "action": action or None,
            }
        )
        if len(controls) == 2:
            break
    return controls

def normalize_stage_layout(value: object, default: str) -> str:
    if isinstance(value, dict):
        value = value.get("description") or value.get("layout")
    return (safe_str(value) or default)[:220]


def normalize_design_brief(raw_brief: object, default: dict[str, Any]) -> dict[str, Any]:
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
        value = next(
            (raw_brief.get(candidate) for candidate in candidates if raw_brief.get(candidate) is not None), None
        )
        if value is None:
            value = default.get(canonical)
        if canonical in {"stage_objects", "visual_rules", "state_updates", "acceptance"}:
            if isinstance(value, list):
                brief[canonical] = [str(item).strip()[:160] for item in value[:8] if str(item).strip()]
            elif safe_str(value):
                brief[canonical] = [safe_str(value)[:160]]
            else:
                brief[canonical] = list(default.get(canonical, []))
        else:
            brief[canonical] = safe_str(value)[:240]
    return brief


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
        name = re.sub(r"[^a-zA-Z0-9_-]+", "-", safe_str(item.get("name")) or f"variable-{index + 1}").strip("-")
        if not name or name in seen:
            continue
        seen.add(name)
        variable: dict[str, Any] = {
            "name": name,
            "label": (safe_str(item.get("label")) or name)[:32],
        }
        if bool(item.get("computed")):
            variable["computed"] = True
            expression = safe_str(item.get("expression"))
            if expression:
                variable["expression"] = expression[:160]
            variables.append(variable)
            continue
        minimum = safe_number(item.get("min"), 0)
        maximum = safe_number(item.get("max"), max(minimum + 1, 10))
        if maximum < minimum:
            minimum, maximum = maximum, minimum
        default_value = clamp(safe_number(item.get("default"), minimum), minimum, maximum)
        step = safe_number(item.get("step"), 1)
        if step <= 0:
            step = 1
        variable.update(
            {
                "min": minimum,
                "max": maximum,
                "step": step,
                "default": default_value,
                "unit": safe_str(item.get("unit"))[:16],
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
            value = clamp(safe_number(raw_values.get(name), minimum), minimum, maximum)
            values[name] = value
        if not values:
            continue
        preset_id = re.sub(
            r"[^a-zA-Z0-9_-]+",
            "-",
            safe_str(item.get("id")) or f"preset-{index + 1}",
        ).strip("-")
        presets.append(
            {
                "id": preset_id or f"preset-{index + 1}",
                "label": (safe_str(item.get("label")) or f"预设{index + 1}")[:32],
                "values": values,
            }
        )
    return presets


def _expand_simulation_bounds_for_presets(
    variables: list[dict[str, Any]],
    bounds: dict[str, tuple[float, float]],
    raw_presets: object,
) -> dict[str, tuple[float, float]]:
    """Keep variable ranges and preset values semantically consistent."""
    if not isinstance(raw_presets, list):
        return bounds

    expanded = dict(bounds)
    for item in raw_presets[:3]:
        if not isinstance(item, dict):
            continue
        raw_values = item.get("values") if isinstance(item.get("values"), dict) else item
        for name, (minimum, maximum) in tuple(expanded.items()):
            if name not in raw_values:
                continue
            value = safe_number(raw_values.get(name), minimum)
            expanded[name] = (min(minimum, value), max(maximum, value))

    for variable in variables:
        name = safe_str(variable.get("name"))
        if name not in expanded or variable.get("computed"):
            continue
        minimum, maximum = expanded[name]
        variable["min"] = minimum
        variable["max"] = maximum
        variable["default"] = clamp(safe_number(variable.get("default"), minimum), minimum, maximum)
    return expanded


def _normalize_diagram_node(node: object, index: int) -> dict:
    if not isinstance(node, dict):
        return {
            "id": f"node-{index + 1}",
            "label": f"节点{index + 1}",
            "details": "观察该节点的含义。",
            "explanation": "观察该节点的含义。",
        }
    node_id = re.sub(r"[^a-zA-Z0-9_-]+", "-", safe_str(node.get("id")) or f"node-{index + 1}").strip("-")
    label = (safe_str(node.get("label")) or node_id or f"节点{index + 1}")[:32]
    details = (safe_str(node.get("details")) or safe_str(node.get("explanation")) or "观察该节点的含义。")[:160]
    return {"id": node_id or f"node-{index + 1}", "label": label, "details": details, "explanation": details}


def _normalize_diagram_edge(edge: object) -> dict:
    if not isinstance(edge, dict):
        return {"from": "core", "to": "result"}
    source = safe_str(edge.get("from") or edge.get("source")) or "core"
    target = safe_str(edge.get("to") or edge.get("target")) or "result"
    normalized = {"from": source, "to": target}
    label = safe_str(edge.get("label"))
    if label:
        normalized["label"] = label[:32]
    return normalized
