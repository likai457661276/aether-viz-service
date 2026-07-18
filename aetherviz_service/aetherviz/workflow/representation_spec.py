"""Generic visual-representation contract used by IR routing.

The contract describes reusable capabilities instead of named knowledge points.
Model output is treated as a hint and normalized against the approved plan.
"""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Any

REPRESENTATION_SPEC_VERSION = "1.0"
VIEW_KINDS = {
    "coordinate_plane",
    "geometric_scene",
    "number_line",
    "data_chart",
    "process_diagram",
    "symbolic_panel",
    "object_scene",
}
STATE_TYPES = {"scalar", "angle", "length", "time", "ratio", "vector", "discrete"}
CORRESPONDENCE_TYPES = {
    "shared_parameter",
    "point_on_curve",
    "projection",
    "equal_value",
    "coincident",
    "transform",
    "decompose_recompose",
    "derived_value",
}
INVARIANT_TYPES = {
    "point_on_curve",
    "equal_value",
    "coincident",
    "piece_identity_preserved",
    "piece_count_constant",
    "area_preserved",
    "length_preserved",
    "angle_preserved",
    "piece_congruence",
    "collinear",
    "parallel",
    "perpendicular",
    "equal_length",
    "midpoint",
    "point_on_circle",
    "tangent",
    "equal_angle",
    "supplementary",
}
INTERACTION_REQUIREMENTS = {"scrub", "play", "pause", "reset", "preset", "drag", "reveal", "trace"}

_LINK_RELATIONS = ("联动", "对应", "同步", "映射", "投影", "共享参数", "同一参数")
_GRAPH_CONCEPTS = ("函数", "图像", "坐标", "曲线", "波形", "正弦", "余弦")
_SOURCE_MOTIONS = ("轨迹", "圆周", "单位圆", "运动", "旋转", "向量", "动点", "投影")


def normalize_representation_spec(
    raw: object,
    *,
    topic: str,
    interactive_spec: dict[str, Any],
    discipline_spec: dict[str, Any],
    knowledge_profile: dict[str, Any],
    recomposition_spec: dict[str, Any] | None,
) -> dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    views = _normalize_views(source.get("views"))
    states = _normalize_states(source.get("state_variables"), interactive_spec)
    correspondences = _normalize_correspondences(source.get("correspondences"), views, states)
    invariants = _string_enum_list(source.get("required_invariants"), INVARIANT_TYPES, 12)
    interactions = _string_enum_list(source.get("interaction_requirements"), INTERACTION_REQUIREMENTS, 8)

    representation = str(knowledge_profile.get("representation_type") or "")
    semantic_text = _semantic_text(topic, discipline_spec, interactive_spec)
    if not views or not correspondences:
        inferred = _infer_structure(
            semantic_text,
            representation=representation,
            state_names=[str(item["id"]) for item in states],
            has_recomposition=bool(recomposition_spec),
        )
        views = views or inferred["views"]
        correspondences = correspondences or inferred["correspondences"]
        invariants = invariants or inferred["required_invariants"]

    correspondences, invariants = _augment_linked_correspondence(
        views=views,
        states=states,
        correspondences=correspondences,
        invariants=invariants,
        representation=representation,
        semantic_text=semantic_text,
    )
    invariants = _normalize_invariant_compatibility(
        invariants,
        representation=representation,
        states=states,
        correspondences=correspondences,
    )

    if not interactions and interactive_spec.get("type") == "simulation":
        interactions = ["scrub", "play", "pause", "reset"]
    return {
        "version": REPRESENTATION_SPEC_VERSION,
        "views": views,
        "state_variables": states,
        "correspondences": correspondences,
        "required_invariants": invariants,
        "interaction_requirements": interactions,
    }


def _normalize_invariant_compatibility(
    invariants: list[str],
    *,
    representation: str,
    states: list[dict[str, Any]],
    correspondences: list[dict[str, str]],
) -> list[str]:
    """Remove topology invariants that contradict parameter-driven construction.

    Piece identity/count/congruence describe a fixed recomposition topology. They
    cannot be hard requirements when a discrete construction parameter changes
    the number of generated vertices or edges.
    """

    recomposition = representation == "geometric_recomposition" or any(
        item.get("type") == "decompose_recompose" for item in correspondences
    )
    topology_changes = representation == "geometric_construction" and any(
        item.get("semantic_type") == "discrete" for item in states
    )
    if recomposition or not topology_changes:
        return invariants
    incompatible = {"piece_identity_preserved", "piece_count_constant", "piece_congruence"}
    return [item for item in invariants if item not in incompatible]


def _augment_linked_correspondence(
    *,
    views: list[dict[str, str]],
    states: list[dict[str, Any]],
    correspondences: list[dict[str, str]],
    invariants: list[str],
    representation: str,
    semantic_text: str,
) -> tuple[list[dict[str, str]], list[str]]:
    strong_types = {"point_on_curve", "projection", "equal_value", "coincident"}
    if any(item["type"] in strong_types for item in correspondences) or not states:
        return correspondences, invariants
    coordinate_views = [item for item in views if item["kind"] == "coordinate_plane"]
    source_views = [item for item in views if item["kind"] != "coordinate_plane"]
    semantic_linked = (
        any(cue in semantic_text for cue in _LINK_RELATIONS)
        and any(cue in semantic_text for cue in _GRAPH_CONCEPTS)
        and any(cue in semantic_text for cue in _SOURCE_MOTIONS)
    )
    if (
        len(coordinate_views) != 1
        or len(source_views) != 1
        or not (representation == "linked_coordinate_scene" or semantic_linked)
    ):
        return correspondences, invariants
    relation = "point_on_curve" if "point_on_curve" in invariants else "equal_value"
    parameter = str(states[0]["id"])
    augmented = [
        *correspondences,
        {
            "type": relation,
            "source_view": source_views[0]["id"],
            "target_view": coordinate_views[0]["id"],
            "parameter": parameter,
            "source": "dynamic-value",
            "target": "graph-value",
        },
    ]
    required = list(invariants)
    for invariant in ("point_on_curve", "equal_value"):
        if invariant not in required:
            required.append(invariant)
    return augmented[:12], required[:12]


def representation_spec_fingerprint(plan: dict[str, Any]) -> str:
    payload = {
        "source_topic": plan.get("source_topic"),
        "subject": plan.get("subject"),
        "interactive_type": plan.get("interactive_type"),
        "representation_spec": plan.get("representation_spec"),
        "teaching_flow": plan.get("teaching_flow"),
        "scene_outline": plan.get("scene_outline"),
        "widget_outline": plan.get("widget_outline"),
    }
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(serialized.encode("utf-8")).hexdigest()


def _normalize_views(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in value[:6]:
        if not isinstance(item, dict):
            continue
        identifier = _identifier(item.get("id"))
        kind = str(item.get("kind") or "")
        if not identifier or identifier in seen or kind not in VIEW_KINDS:
            continue
        seen.add(identifier)
        result.append({"id": identifier, "kind": kind, "role": str(item.get("role") or "")[:120]})
    return result


def _normalize_states(value: object, interactive_spec: dict[str, Any]) -> list[dict[str, Any]]:
    supplied = value if isinstance(value, list) else []
    by_name = {
        str(item.get("name")): item
        for item in interactive_spec.get("variables", [])
        if isinstance(item, dict) and item.get("name") and not item.get("computed")
    }
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in supplied:
        if not isinstance(item, dict):
            continue
        identifier = _identifier(item.get("id"))
        if not identifier or identifier in seen:
            continue
        if by_name and identifier not in by_name:
            continue
        source = by_name.get(identifier, {})
        semantic_type = str(item.get("semantic_type") or _infer_state_type(item, source))
        if semantic_type not in STATE_TYPES:
            semantic_type = "scalar"
        result.append(_state(identifier, item, source, semantic_type))
        seen.add(identifier)
    for identifier, source in by_name.items():
        if identifier in seen or not _identifier(identifier):
            continue
        result.append(_state(identifier, {}, source, _infer_state_type({}, source)))
    return result[:6]


def _state(identifier: str, item: dict[str, Any], source: dict[str, Any], semantic_type: str) -> dict[str, Any]:
    unit = str(source.get("unit") or item.get("unit") or "")[:16]
    display_unit = str(item.get("display_unit") or unit)[:16]
    return {
        "id": identifier,
        "semantic_type": semantic_type,
        "minimum": _number(source.get("min"), item.get("minimum"), 0),
        "maximum": _number(source.get("max"), item.get("maximum"), 1),
        "default": _number(source.get("default"), item.get("default"), 0),
        "unit": unit,
        "display_unit": display_unit,
    }


def _normalize_correspondences(
    value: object, views: list[dict[str, str]], states: list[dict[str, Any]]
) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    view_ids = {item["id"] for item in views}
    state_ids = {str(item["id"]) for item in states}
    result: list[dict[str, str]] = []
    for item in value[:12]:
        if not isinstance(item, dict) or item.get("type") not in CORRESPONDENCE_TYPES:
            continue
        normalized = {
            "type": str(item["type"]),
            "source_view": str(item.get("source_view") or "")[:64],
            "target_view": str(item.get("target_view") or "")[:64],
            "parameter": str(item.get("parameter") or "")[:64],
            "source": str(item.get("source") or "")[:120],
            "target": str(item.get("target") or "")[:120],
        }
        if normalized["source_view"] and normalized["source_view"] not in view_ids:
            continue
        if normalized["target_view"] and normalized["target_view"] not in view_ids:
            continue
        if normalized["parameter"] and normalized["parameter"] not in state_ids:
            continue
        result.append(normalized)
    return result


def _infer_structure(
    text: str, *, representation: str, state_names: list[str], has_recomposition: bool
) -> dict[str, Any]:
    parameter = state_names[0] if state_names else ""
    linked = (
        any(cue in text for cue in _LINK_RELATIONS)
        and any(cue in text for cue in _GRAPH_CONCEPTS)
        and any(cue in text for cue in _SOURCE_MOTIONS)
    )
    if linked:
        relation = "projection" if "投影" in text else "equal_value"
        return {
            "views": [
                {"id": "source-view", "kind": "geometric_scene", "role": "参数运动或来源表征"},
                {"id": "graph-view", "kind": "coordinate_plane", "role": "函数或坐标表征"},
            ],
            "correspondences": [
                {
                    "type": "shared_parameter",
                    "source_view": "source-view",
                    "target_view": "graph-view",
                    "parameter": parameter,
                    "source": "",
                    "target": "",
                },
                {
                    "type": relation,
                    "source_view": "source-view",
                    "target_view": "graph-view",
                    "parameter": parameter,
                    "source": "dynamic-value",
                    "target": "graph-value",
                },
            ],
            "required_invariants": ["point_on_curve", "equal_value"],
        }
    if representation == "geometric_recomposition" or has_recomposition:
        return {
            "views": [{"id": "geometry-view", "kind": "geometric_scene", "role": "切分重排证明"}],
            "correspondences": [
                {
                    "type": "decompose_recompose",
                    "source_view": "geometry-view",
                    "target_view": "geometry-view",
                    "parameter": parameter,
                    "source": "source-pieces",
                    "target": "target-assembly",
                }
            ],
            "required_invariants": ["piece_identity_preserved", "piece_count_constant", "piece_congruence"],
        }
    if representation == "number_line":
        return {
            "views": [{"id": "number-line-view", "kind": "number_line", "role": "数、区间与一维关系"}],
            "correspondences": [],
            "required_invariants": ["equal_value"] if parameter else [],
        }
    kind = "coordinate_plane" if any(cue in text for cue in _GRAPH_CONCEPTS) else "object_scene"
    return {
        "views": [{"id": "primary-view", "kind": kind, "role": "主要教学表征"}],
        "correspondences": [],
        "required_invariants": [],
    }


def _semantic_text(topic: str, discipline: dict[str, Any], interactive: dict[str, Any]) -> str:
    return " ".join(
        [
            topic,
            json.dumps(discipline, ensure_ascii=False),
            str(interactive.get("concept") or ""),
            str(interactive.get("description") or ""),
            " ".join(str(item) for item in interactive.get("observations", [])),
        ]
    ).lower()


def _infer_state_type(item: dict[str, Any], source: dict[str, Any]) -> str:
    text = " ".join(
        str(value)
        for value in (item.get("id"), source.get("name"), source.get("label"), item.get("unit"), source.get("unit"))
    ).lower()
    if any(cue in text for cue in ("angle", "theta", "角", "°", "deg", "rad")):
        return "angle"
    if any(cue in text for cue in ("time", "时间", "秒")):
        return "time"
    if any(cue in text for cue in ("length", "长度", "半径", "距离")):
        return "length"
    return "scalar"


def _string_enum_list(value: object, allowed: set[str], maximum: int) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = str(item or "")
        if text in allowed and text not in result:
            result.append(text)
    return result[:maximum]


def _identifier(value: object) -> str:
    text = str(value or "")[:64]
    return text if text and all(char.isalnum() or char in "_-" for char in text) else ""


def _number(primary: object, secondary: object, default: float) -> float:
    for value in (primary, secondary):
        if isinstance(value, bool):
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return default
