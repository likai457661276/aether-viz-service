"""Generation-spec (machine-layer) derivation from a teaching plan."""

from __future__ import annotations

import re
from typing import Any

from aetherviz_service.aetherviz.constants import get_gsap_core_cdn_url, get_katex_cdn_urls, is_katex_enabled
from aetherviz_service.aetherviz.workflow.knowledge_profile import normalize_knowledge_profile
from aetherviz_service.aetherviz.workflow.plan_detection import (
    SUBJECT_KEYWORDS,
    VALID_ANIMATION_RUNTIMES,
    VALID_RENDER_STACKS,
    detect_subject,
    select_animation_runtime,
    select_render_stack,
)
from aetherviz_service.aetherviz.workflow.plan_diagnostics import PlanDiagnostic, add_diagnostic
from aetherviz_service.aetherviz.workflow.plan_utils import clamp, safe_number, safe_str, string_list
from aetherviz_service.aetherviz.workflow.representation_spec import normalize_representation_spec
from aetherviz_service.aetherviz.workflow.teaching_plan import REQUIRED_RUNTIME_CONTROLS

# Continuous geometry spans wider than this ratio commonly empty the visual scale
# interval (minimum readable vs maximum fit). Prefer shrinking plan bounds over
# asking IR repair to absorb impossible linear pixel spans.
_GEOMETRY_VARIABLE_MAX_RATIO = 6.0
_GEOMETRY_VARIABLE_MAX_ABS_SPAN = 8.0


def derive_generation_spec(
    teaching_plan: dict[str, Any],
    raw_plan: dict | None,
    *,
    diagnostics: list[PlanDiagnostic] | None = None,
) -> dict[str, Any]:
    """Derive machine IR routing / generation fields from a teaching plan.

    May narrow interactive_spec geometry variable spans in-place on teaching_plan
    when recomposition evidence is present. Does not rewrite other teaching fields.
    """
    raw = raw_plan if isinstance(raw_plan, dict) else {}
    source_topic = safe_str(teaching_plan.get("source_topic")) or safe_str(raw.get("source_topic"))
    interactive_type = safe_str(teaching_plan.get("interactive_type"))
    interactive_spec = teaching_plan.get("interactive_spec")
    if not isinstance(interactive_spec, dict):
        interactive_spec = {}
        teaching_plan["interactive_spec"] = interactive_spec
    key_points = teaching_plan.get("key_points") if isinstance(teaching_plan.get("key_points"), list) else []
    formulas = teaching_plan.get("formulas") if isinstance(teaching_plan.get("formulas"), list) else []
    title = safe_str(teaching_plan.get("title"))

    subject = safe_str(raw.get("subject")) or detect_subject(source_topic)
    if subject not in {*SUBJECT_KEYWORDS.keys(), "astronomy", "general"}:
        subject = detect_subject(source_topic)

    knowledge_profile = normalize_knowledge_profile(raw.get("knowledge_profile"), source_topic, subject)
    if float(knowledge_profile.get("confidence") or 0) < 0.45:
        add_diagnostic(
            diagnostics,
            code="knowledge_profile_low_confidence",
            severity="warning",
            field="knowledge_profile.confidence",
            message="主题线索不足，知识画像采用通用降级结果",
        )

    runtime_raw = raw.get("runtime") if isinstance(raw.get("runtime"), dict) else {}
    render_stack = safe_str(runtime_raw.get("render_stack") or raw.get("render_stack")) or select_render_stack(
        interactive_type, subject, source_topic
    )
    if render_stack not in VALID_RENDER_STACKS:
        render_stack = select_render_stack(interactive_type, subject, source_topic)
    animation_runtime = (
        safe_str(runtime_raw.get("animation_runtime") or raw.get("animation_runtime")) or select_animation_runtime()
    )
    if animation_runtime not in VALID_ANIMATION_RUNTIMES:
        animation_runtime = select_animation_runtime()

    widget_outline = normalize_widget_outline(
        raw.get("widget_outline"), interactive_spec, interactive_type, source_topic
    )
    scene_outline = normalize_scene_outline(
        raw.get("scene_outline"),
        default_scene_outline(source_topic, interactive_type, key_points, widget_outline),
        interactive_type,
        source_topic,
        key_points,
        widget_outline,
    )
    if not isinstance(raw.get("scene_outline"), dict):
        scene_outline["title"] = title

    has_recomposition = has_recomposition_evidence(
        raw,
        source_topic,
        interactive_spec,
        knowledge_profile,
    )
    if has_recomposition and knowledge_profile.get("representation_type") != "geometric_recomposition":
        # representation_spec is the authoritative capability contract.  A
        # stale coarse profile must not force an exact piece-rearrangement
        # proof through unconstrained HTML generation.
        knowledge_profile = {
            **knowledge_profile,
            "representation_type": "geometric_recomposition",
            "pedagogy_pattern": "decompose_recompose_proof",
        }
    recomposition_spec = (
        normalize_recomposition_spec(raw.get("recomposition_spec"), interactive_spec)
        if has_recomposition
        else None
    )
    if recomposition_spec is not None:
        narrow_recomposition_geometry_spans(
            interactive_spec,
            recomposition_spec.get("geometry_variables", []),
        )

    discipline_default = default_discipline_spec(source_topic, knowledge_profile)
    discipline_spec = normalize_discipline_spec(raw.get("discipline_spec"), discipline_default)
    representation_spec = normalize_representation_spec(
        raw.get("representation_spec"),
        topic=source_topic,
        interactive_spec=interactive_spec,
        discipline_spec=discipline_spec,
        knowledge_profile=knowledge_profile,
        recomposition_spec=recomposition_spec,
        diagnostics=diagnostics,
    )

    result: dict[str, Any] = {
        "page_type": "interactive",
        "widget_type": interactive_type,
        "subject": subject,
        "knowledge_profile": knowledge_profile,
        "representation_spec": representation_spec,
        "discipline_spec": discipline_spec,
        "scene_outline": scene_outline,
        "widget_outline": widget_outline,
        "widget_actions": normalize_widget_actions(
            raw.get("widget_actions"),
            default_widget_actions(interactive_spec, interactive_type),
            interactive_spec,
            interactive_type,
        ),
        "runtime": {
            "render_stack": render_stack,
            "animation_runtime": animation_runtime,
            "external_libraries": normalize_external_libraries(
                animation_runtime,
                include_katex=bool(formulas),
            ),
        },
        "runtime_controls": [dict(control) for control in REQUIRED_RUNTIME_CONTROLS],
    }
    if recomposition_spec is not None:
        result["recomposition_spec"] = recomposition_spec
    return result


def has_recomposition_evidence(
    raw: dict[str, Any],
    topic: str,
    interactive_spec: dict[str, Any],
    knowledge_profile: dict[str, Any],
) -> bool:
    if knowledge_profile.get("representation_type") == "geometric_recomposition":
        return True
    representation = raw.get("representation_spec")
    if isinstance(representation, dict):
        correspondences = representation.get("correspondences")
        if isinstance(correspondences, list) and any(
            isinstance(item, dict) and item.get("type") == "decompose_recompose" for item in correspondences
        ):
            return True
        views = {
            str(item.get("kind") or "")
            for item in representation.get("views", [])
            if isinstance(item, dict)
        }
        invariants = {str(item) for item in representation.get("required_invariants", [])}
        states = [item for item in representation.get("state_variables", []) if isinstance(item, dict)]
        stable_topology = not any(item.get("semantic_type") == "discrete" for item in states)
        preserved_measure = invariants & {"area_preserved", "length_preserved", "angle_preserved"}
        if stable_topology and "geometric_scene" in views and "piece_congruence" in invariants and preserved_measure:
            return True
    semantic = " ".join(
        (
            topic,
            str(interactive_spec.get("concept") or ""),
            str(interactive_spec.get("description") or ""),
            " ".join(str(item) for item in interactive_spec.get("observations", [])),
        )
    ).lower()
    cues = (
        "切分",
        "切割",
        "重排",
        "拼接",
        "拼合",
        "拼图",
        "割补",
        "等积",
        "recompose",
        "rearrange",
        "dissect",
    )
    return isinstance(raw.get("recomposition_spec"), dict) and any(cue in semantic for cue in cues)


def normalize_recomposition_spec(raw_spec: object, interactive_spec: dict[str, Any]) -> dict[str, Any]:
    raw = raw_spec if isinstance(raw_spec, dict) else {}
    variables = [
        variable
        for variable in interactive_spec.get("variables", [])
        if isinstance(variable, dict) and not variable.get("computed") and safe_str(variable.get("name"))
    ]
    variable_names = [safe_str(variable.get("name")) for variable in variables]
    variables_by_name = {safe_str(variable.get("name")): variable for variable in variables}
    inferred_topology = [
        name
        for name in variable_names
        if _looks_like_topology_count(variables_by_name[name])
    ]
    requested_topology = string_list(raw.get("topology_variables"), [], max_items=3, max_len=40)
    topology = [
        name
        for name in requested_topology
        if name in variable_names and _is_discrete_topology_variable(variables_by_name[name])
    ] or [
        name
        for name in inferred_topology
        if _is_discrete_topology_variable(variables_by_name[name])
    ]
    requested_geometry = string_list(raw.get("geometry_variables"), [], max_items=3, max_len=40)
    geometry = [name for name in requested_geometry if name in variable_names and name not in topology]
    if not geometry:
        geometry = [name for name in variable_names if name not in topology]
    invariants = string_list(
        raw.get("invariants"),
        [
            "piece_identity_preserved",
            "piece_count_constant_during_animation",
            "source_target_piece_sets_equal",
            "no_structural_mutation_during_animation",
        ],
        max_items=8,
        max_len=72,
    )
    proof_raw = raw.get("proof_constraints") if isinstance(raw.get("proof_constraints"), dict) else {}
    allowed_measures = {"area_preserved", "length_preserved", "angle_preserved", "piece_congruence"}
    requested_measures = string_list(
        proof_raw.get("measure_invariants"),
        ["area_preserved", "piece_congruence"],
        max_items=4,
        max_len=40,
    )
    measure_invariants = [item for item in requested_measures if item in allowed_measures]
    if not measure_invariants:
        measure_invariants = ["area_preserved", "piece_congruence"]
    elif "piece_congruence" not in measure_invariants:
        measure_invariants.append("piece_congruence")
    stage_requirements = _normalize_stage_requirements(proof_raw.get("stage_requirements"))
    return {
        "topology_variables": topology,
        "geometry_variables": geometry,
        "animation_variable": "progress",
        "invariants": invariants,
        "proof_constraints": {
            "piece_policy": "stable_ids",
            "measure_invariants": measure_invariants,
            "target_relations": _normalize_target_relations(proof_raw.get("target_relations"), measure_invariants),
            "target_assembly": _normalize_target_assembly(proof_raw.get("target_assembly")),
            "stage_requirements": stage_requirements,
        },
    }


def narrow_recomposition_geometry_spans(
    interactive_spec: dict[str, Any],
    geometry_variables: object,
) -> None:
    """Shrink extreme continuous geometry min/max at the planning layer."""
    names = {
        str(name)
        for name in geometry_variables
        if isinstance(geometry_variables, list) and str(name or "").strip()
    }
    if not names:
        return
    variables = interactive_spec.get("variables")
    if not isinstance(variables, list):
        return
    for variable in variables:
        if not isinstance(variable, dict) or variable.get("computed"):
            continue
        name = safe_str(variable.get("name"))
        if name not in names:
            continue
        minimum = float(safe_number(variable.get("min"), 0))
        maximum = float(safe_number(variable.get("max"), max(minimum + 1, 10)))
        if maximum < minimum:
            minimum, maximum = maximum, minimum
        default = float(safe_number(variable.get("default"), minimum))
        step = float(safe_number(variable.get("step"), 1))
        if step <= 0:
            step = 1.0
        if minimum > 0:
            ratio = maximum / minimum
            if ratio > _GEOMETRY_VARIABLE_MAX_RATIO + 1e-9:
                # Keep the default teaching value; shrink the farther endpoint.
                if default * default <= minimum * maximum:
                    maximum = minimum * _GEOMETRY_VARIABLE_MAX_RATIO
                else:
                    minimum = maximum / _GEOMETRY_VARIABLE_MAX_RATIO
        elif maximum - minimum > _GEOMETRY_VARIABLE_MAX_ABS_SPAN + 1e-9:
            half = _GEOMETRY_VARIABLE_MAX_ABS_SPAN / 2.0
            minimum = default - half
            maximum = default + half
        if maximum < minimum:
            minimum, maximum = maximum, minimum
        default = clamp(default, minimum, maximum)
        variable["min"] = safe_number(minimum, minimum)
        variable["max"] = safe_number(maximum, maximum)
        variable["default"] = default
        variable["step"] = safe_number(step, step)
    presets = interactive_spec.get("presets")
    if not isinstance(presets, list):
        return
    bounds = {
        safe_str(variable.get("name")): (
            float(variable.get("min", 0)),
            float(variable.get("max", 0)),
        )
        for variable in variables
        if isinstance(variable, dict) and not variable.get("computed") and safe_str(variable.get("name"))
    }
    for preset in presets:
        if not isinstance(preset, dict) or not isinstance(preset.get("values"), dict):
            continue
        values = preset["values"]
        for name, (low, high) in bounds.items():
            if name in values:
                values[name] = clamp(safe_number(values.get(name), low), low, high)


def normalize_widget_outline(raw_outline: object, interactive_spec: dict, interactive_type: str, topic: str) -> dict:
    outline = dict(raw_outline) if isinstance(raw_outline, dict) else {}
    outline["type"] = interactive_type
    outline.setdefault("topic", topic)
    outline.setdefault("intent", "single_page_interactive_widget")
    outline.setdefault("concept", interactive_spec.get("concept") or topic)
    if interactive_type == "simulation":
        outline.setdefault(
            "core_objects",
            [item.get("name") for item in interactive_spec.get("variables", []) if isinstance(item, dict)]
            or ["parameter"],
        )
        outline.setdefault("state_model", ["running", "paused", "ended"])
        outline.setdefault(
            "observable_changes", interactive_spec.get("observations") or ["参数变化驱动画面、读数和结论同步变化"]
        )
    elif interactive_type == "diagram":
        outline.setdefault(
            "core_objects",
            [item.get("id") for item in interactive_spec.get("nodes", []) if isinstance(item, dict)] or ["core"],
        )
        outline.setdefault("state_model", ["hidden", "revealed", "highlighted"])
        outline.setdefault("observable_changes", ["节点逐步揭示", "关系连线高亮", "说明同步更新"])
    else:
        outline.setdefault("core_objects", ["challenge", "choice", "feedback"])
        outline.setdefault("state_model", ["ready", "playing", "success"])
        outline.setdefault("observable_changes", ["操作对象移动", "结果即时反馈", "成功条件高亮"])
    outline.setdefault("required_regions", ["learning-goal", "stage", "controls", "caption", "formula"])
    return outline


def default_scene_outline(topic: str, interactive_type: str, key_points: list[str], widget_outline: dict) -> dict:
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


def normalize_scene_outline(
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
    outline["keyPoints"] = string_list(raw_key_points, key_points, max_items=6, max_len=120)
    outline["order"] = int(outline.get("order") or 1)
    outline["widgetOutline"] = (
        dict(outline.get("widgetOutline")) if isinstance(outline.get("widgetOutline"), dict) else widget_outline
    )
    return outline


def default_discipline_spec(topic: str, profile: dict[str, Any]) -> dict[str, list[str]]:
    """Provide a small semantic scaffold without encoding a concrete lesson answer."""
    return {
        "entities": [f"{topic}中的核心对象与可观察状态"],
        "relations": ["对象、变量、图形与结论必须由同一状态模型关联"],
        "invariants": ["交互过程中保持学科定义、单位、依赖关系和关键约束成立"],
        "boundary_cases": ["覆盖默认状态、参数边界和至少一个有教学意义的特殊状态"],
        "representations": [str(profile.get("representation_type") or "dynamic_model"), "文字解释与视觉状态同步"],
    }


def normalize_discipline_spec(raw_spec: object, default: dict[str, list[str]]) -> dict[str, list[str]]:
    source = raw_spec if isinstance(raw_spec, dict) else {}
    result: dict[str, list[str]] = {}
    for field in ("entities", "relations", "invariants", "boundary_cases", "representations"):
        result[field] = string_list(source.get(field), default.get(field, []), max_items=6, max_len=160)
    return result


def default_widget_actions(interactive_spec: dict, interactive_type: str) -> list[dict[str, Any]]:
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


def normalize_widget_actions(
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
        action_type = safe_str(item.get("type") or item.get("action"))
        params = item.get("params") if isinstance(item.get("params"), dict) else {}
        action: dict[str, Any] = {"type": action_type}
        if action_type == "widget_setState":
            state = item.get("state") if isinstance(item.get("state"), dict) else params
            action["state"] = dict(state)
        else:
            target = safe_str(item.get("target") or params.get("elementId"))
            if target and not target.startswith(("#", ".", "[")):
                target = f"#{target}"
            action["target"] = target or "[data-role='main-visual']"
        action["content"] = safe_str(item.get("content") or params.get("text"))[:160]
        actions.append(action)
    found = {str(action.get("type") or "") for action in actions}
    required = {"widget_setState", "widget_highlight", "widget_annotation", "widget_reveal"}
    if not required.issubset(found):
        actions = default_widget_actions(interactive_spec, interactive_type)
    return actions


def normalize_external_libraries(animation_runtime: str, *, include_katex: bool) -> list[str]:
    libraries: list[str] = []
    if animation_runtime == "gsap":
        libraries.append(get_gsap_core_cdn_url())
    if include_katex and is_katex_enabled():
        libraries.extend(get_katex_cdn_urls())
    return libraries


def _is_discrete_topology_variable(variable: dict[str, Any]) -> bool:
    """Only integer-stepped bounded controls may change expanded piece identity/count."""
    values = [variable.get(key) for key in ("min", "max", "default", "step")]
    try:
        minimum, maximum, default, step = (float(value) for value in values)
    except (TypeError, ValueError):
        return False
    return (
        step >= 1
        and step.is_integer()
        and minimum.is_integer()
        and maximum.is_integer()
        and default.is_integer()
    )


def _looks_like_topology_count(variable: dict[str, Any]) -> bool:
    """Recognize count semantics from stable machine names or user-facing labels."""
    text = " ".join(
        (
            safe_str(variable.get("name")).lower(),
            safe_str(variable.get("label")).lower(),
        )
    )
    cues = (
        "count",
        "piece",
        "segment",
        "sector",
        "slice",
        "part",
        "number",
        "数量",
        "份数",
        "片数",
        "段数",
        "个数",
        "分块",
        "切分",
        "等分",
    )
    return any(cue in text for cue in cues)


def _normalize_stage_requirements(value: object) -> list[dict[str, Any]]:
    raw_stages = [item for item in value[:5] if isinstance(item, dict)] if isinstance(value, list) else []
    if len(raw_stages) < 3:
        raw_stages = [
            {"id": "source", "intent": "展示切分前或切分后的源图元集合"},
            {"id": "transform", "intent": "展示同一组图元形成可观察的中间几何状态"},
            {"id": "target", "intent": "展示目标排列并建立度量等式"},
        ]

    stage_count = len(raw_stages)
    used_ids: set[str] = set()
    stages: list[dict[str, Any]] = []
    for index, item in enumerate(raw_stages):
        role = "source" if index == 0 else "target" if index == stage_count - 1 else "intermediate"
        default_id = role if role != "intermediate" else f"transform-{index}"
        stage_id = (
            re.sub(
                r"[^a-zA-Z0-9_-]+",
                "-",
                (safe_str(item.get("id")) or default_id).lower(),
            ).strip("-")[:40]
            or default_id
        )
        if stage_id in used_ids:
            stage_id = f"{default_id}-{index}"[:40]
        used_ids.add(stage_id)
        at = 0.0 if role == "source" else 1.0 if role == "target" else index / (stage_count - 1)
        stages.append(
            {
                "id": stage_id,
                "role": role,
                "at": round(at, 6),
                "intent": (safe_str(item.get("intent")) or "展示几何关系")[:120],
                "geometry_requirement": ("transform_keyframe" if role == "intermediate" else f"{role}_snapshot"),
                "min_piece_ratio": (
                    clamp(safe_number(item.get("min_piece_ratio"), 0.5), 0.1, 1.0) if role == "intermediate" else 1.0
                ),
                "required_relations": string_list(item.get("required_relations"), [], max_items=4, max_len=48),
            }
        )
    return stages


def _normalize_target_relations(value: object, measure_invariants: list[str]) -> list[dict[str, Any]]:
    allowed_types = {
        "equal_area",
        "equal_length",
        "equal_angle",
        "parallel",
        "perpendicular",
        "coincident",
        "collinear",
        "congruent",
    }
    relations: list[dict[str, Any]] = []
    if isinstance(value, list):
        for index, item in enumerate(value[:12]):
            if not isinstance(item, dict) or item.get("type") not in allowed_types:
                continue
            relation: dict[str, Any] = {
                "id": re.sub(
                    r"[^a-zA-Z0-9_-]+",
                    "-",
                    (safe_str(item.get("id")) or f"relation-{index + 1}").lower(),
                ).strip("-")[:48]
                or f"relation-{index + 1}",
                "type": item["type"],
                "tolerance": clamp(safe_number(item.get("tolerance"), 1e-6), 1e-9, 0.1),
            }
            for key in ("left", "right"):
                reference = _normalize_relation_reference(item.get(key), depth=0)
                if reference is not None:
                    relation[key] = reference
            if item["type"] == "collinear" and isinstance(item.get("points"), list):
                points = [
                    normalized
                    for point in item["points"][:8]
                    if (normalized := _normalize_relation_reference(point, depth=0)) is not None
                ]
                if points:
                    relation["points"] = points
            relations.append(relation)
    if not relations and "area_preserved" in measure_invariants:
        relations.append(
            {
                "id": "source-target-area",
                "type": "equal_area",
                "left": {"stage": "source"},
                "right": {"stage": "target"},
                "tolerance": 1e-6,
            }
        )
    return relations


def _normalize_target_assembly(value: object) -> list[dict[str, Any]]:
    allowed_types = {"connected", "non_overlapping", "approximate_rectangle"}
    constraints: list[dict[str, Any]] = []
    if not isinstance(value, list):
        return constraints
    for index, item in enumerate(value[:4]):
        if not isinstance(item, dict) or item.get("type") not in allowed_types:
            continue
        constraint_type = str(item["type"])
        constraint: dict[str, Any] = {
            "id": re.sub(
                r"[^a-zA-Z0-9_-]+",
                "-",
                (safe_str(item.get("id")) or f"assembly-{index + 1}").lower(),
            ).strip("-")[:48]
            or f"assembly-{index + 1}",
            "type": constraint_type,
        }
        if constraint_type in {"connected", "approximate_rectangle"}:
            constraint["max_components"] = int(clamp(safe_number(item.get("max_components"), 1), 1, 4))
        if constraint_type in {"non_overlapping", "approximate_rectangle"}:
            constraint["max_overlap_ratio"] = clamp(safe_number(item.get("max_overlap_ratio"), 0.1), 0, 0.5)
        if constraint_type == "approximate_rectangle":
            constraint["min_rectangularity"] = clamp(safe_number(item.get("min_rectangularity"), 0.62), 0.4, 0.95)
            constraint["monotonic"] = bool(item.get("monotonic", False))
            constraint["trend_tolerance"] = clamp(safe_number(item.get("trend_tolerance"), 0.08), 0, 0.25)
        constraints.append(constraint)
    return constraints


def _normalize_relation_reference(value: object, *, depth: int) -> object | None:
    if depth > 4:
        return None
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float, str)):
        return value
    if isinstance(value, list):
        return [
            normalized
            for item in value[:8]
            if (normalized := _normalize_relation_reference(item, depth=depth + 1)) is not None
        ]
    if not isinstance(value, dict):
        return None
    allowed_keys = {"stage", "piece_id", "piece_ids", "anchor", "index", "start", "end", "points"}
    return {
        str(key): normalized
        for key, item in value.items()
        if key in allowed_keys and (normalized := _normalize_relation_reference(item, depth=depth + 1)) is not None
    }

