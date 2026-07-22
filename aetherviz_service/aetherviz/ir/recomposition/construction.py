"""Compile generic target-construction constraints into bounded transform expressions."""

from __future__ import annotations

import json
import math
import re
from typing import Any

from aetherviz_service.aetherviz.ir.recomposition.assembly import piece_local_polygon
from aetherviz_service.aetherviz.ir.recomposition.contract import (
    expand_geometry_ir,
    normalize_geometry_ir,
    sample_geometry_states,
)

_SUPPORTED_CONSTRAINTS = {
    "attach_edge",
    "coincident_vertex",
    "parallel_edge",
    "perpendicular_edge",
    "rigid_transform",
    "inside_target",
    "cover_target",
}
_TRANSFORM_KEYS = {"x", "y", "rotation", "scale", "opacity"}
_NUMBER_RE = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")


def materialize_target_construction(ir: object, plan: dict[str, Any]) -> dict[str, Any]:
    """Resolve optional construction constraints and return ordinary Geometry IR."""
    if not isinstance(ir, dict):
        return {"ok": False, "changed": False, "ir": ir, "errors": [_issue("candidate_not_object")]}
    normalized = normalize_geometry_ir(ir, plan)
    construction = normalized.get("construction")
    if construction is None:
        normalized.pop("construction", None)
        return {"ok": True, "changed": False, "ir": normalized, "errors": [], "constraints": []}
    if not isinstance(construction, dict) or not isinstance(construction.get("constraints"), list):
        return _construction_fallback(
            normalized,
            errors=[_issue("invalid_target_construction")],
        )
    constraints = construction["constraints"]
    target_boundary = construction.get("target_boundary")
    if not 1 <= len(constraints) <= 24:
        return _construction_fallback(
            normalized,
            errors=[_issue("invalid_construction_constraint_count", count=len(constraints))],
        )

    completed = json.loads(json.dumps(normalized, ensure_ascii=False))
    pieces = completed.get("pieces") if isinstance(completed.get("pieces"), list) else []
    pieces_by_id: dict[str, dict[str, Any]] = {}
    errors: list[dict[str, Any]] = []
    for piece in pieces:
        if not isinstance(piece, dict) or not isinstance(piece.get("id"), str) or piece.get("repeat"):
            continue
        piece_id = str(piece["id"])
        if piece_id in pieces_by_id:
            errors.append(_issue("duplicate_static_piece_id", piece_id=piece_id))
        pieces_by_id[piece_id] = piece

    applied: list[dict[str, Any]] = []
    for index, constraint in enumerate(constraints):
        if (
            isinstance(constraint, dict)
            and constraint.get("type") in {"inside_target", "cover_target"}
            and not isinstance(target_boundary, dict)
        ):
            errors.append(_issue("target_boundary_required", index=index))
            continue
        result = _apply_constraint(constraint, pieces_by_id)
        if not result["ok"]:
            errors.append({**result["error"], "index": index})
        else:
            applied.append({"index": index, "type": constraint.get("type"), "piece_id": constraint.get("piece_id")})
    if errors:
        return _construction_fallback(normalized, errors=errors, constraints=applied)

    completed.pop("construction", None)
    verification = _verify_constraints(completed, plan, constraints, target_boundary)
    if not verification["ok"]:
        return _construction_fallback(
            normalized,
            errors=verification["errors"],
            constraints=applied,
        )
    return {
        "ok": True,
        "changed": True,
        "ir": completed,
        "errors": [],
        "constraints": applied,
        "verification": verification,
    }


def _construction_fallback(
    normalized: dict[str, Any],
    *,
    errors: list[dict[str, Any]],
    constraints: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Keep author targets when construction cannot be solved, so ranking can continue."""
    fallback = json.loads(json.dumps(normalized, ensure_ascii=False))
    fallback.pop("construction", None)
    return {
        "ok": False,
        "changed": True,
        "ir": fallback,
        "errors": errors,
        "constraints": constraints or [],
        "fallback": "stripped_unsolved_construction",
    }


def _apply_constraint(constraint: object, pieces: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(constraint, dict):
        return _failed("invalid_construction_constraint")
    constraint_type = str(constraint.get("type") or "")
    if constraint_type not in _SUPPORTED_CONSTRAINTS:
        return _failed("unsupported_construction_constraint", constraint_type=constraint_type)
    if constraint_type == "cover_target":
        piece_ids = constraint.get("piece_ids")
        if not isinstance(piece_ids, list) or not piece_ids or any(str(item) not in pieces for item in piece_ids):
            return _failed("invalid_cover_target_piece_ids")
        return {"ok": True}
    piece_id = str(constraint.get("piece_id") or "")
    piece = pieces.get(piece_id)
    if piece is None:
        return _failed("construction_piece_must_be_static", piece_id=piece_id)
    if constraint_type == "inside_target":
        return {"ok": True}
    if constraint_type == "rigid_transform":
        transform = constraint.get("transform")
        if not isinstance(transform, dict) or set(transform) != _TRANSFORM_KEYS:
            return _failed("invalid_rigid_transform", piece_id=piece_id)
        piece["target"] = json.loads(json.dumps(transform, ensure_ascii=False))
        _sync_target_keyframe(piece)
        return {"ok": True}

    reference_id = str(constraint.get("to_piece_id") or "")
    reference = pieces.get(reference_id)
    if reference is None or reference_id == piece_id:
        return _failed("invalid_construction_reference", piece_id=piece_id, to_piece_id=reference_id)
    try:
        vertices = _local_vertices(piece)
        reference_vertices = _local_vertices(reference)
        if constraint_type == "coincident_vertex":
            moving_vertex = _vertex(vertices, constraint.get("vertex"))
            fixed_vertex = _vertex(reference_vertices, constraint.get("to_vertex"))
            fixed_world = _world_point(fixed_vertex, reference["target"])
            moving_offset = _rotated_scaled_point(moving_vertex, piece["target"])
            piece["target"]["x"] = _sub(fixed_world[0], moving_offset[0])
            piece["target"]["y"] = _sub(fixed_world[1], moving_offset[1])
        else:
            moving_edge = _edge(vertices, constraint.get("edge"))
            fixed_edge = _edge(reference_vertices, constraint.get("to_edge"))
            reverse = bool(constraint.get("reverse", False)) if constraint_type == "attach_edge" else False
            desired_angle = _add(
                reference["target"].get("rotation", 0),
                _edge_angle(fixed_edge),
                180 if reverse else 0,
                90 if constraint_type == "perpendicular_edge" else 0,
            )
            piece["target"]["rotation"] = _sub(desired_angle, _edge_angle(moving_edge))
            if constraint_type == "attach_edge":
                moving_length = _expression_edge_length(moving_edge)
                fixed_length = _expression_edge_length(fixed_edge)
                moving_scale = _expression_number(piece["target"].get("scale", 1))
                fixed_scale = _expression_number(reference["target"].get("scale", 1))
                if (
                    moving_length is not None
                    and fixed_length is not None
                    and moving_scale is not None
                    and fixed_scale is not None
                ):
                    left_world = moving_length * abs(moving_scale)
                    right_world = fixed_length * abs(fixed_scale)
                    length_delta = abs(left_world - right_world)
                    if length_delta > 0.75:
                        return _failed(
                            "attach_edge_length_mismatch",
                            piece_id=piece_id,
                            to_piece_id=reference_id,
                            left_length=round(left_world, 6),
                            right_length=round(right_world, 6),
                            length_delta=round(length_delta, 6),
                            hint="equalize_local_edge_lengths_before_attach_edge",
                        )
                fixed_anchor = fixed_edge[1] if reverse else fixed_edge[0]
                fixed_world = _world_point(fixed_anchor, reference["target"])
                moving_offset = _rotated_scaled_point(moving_edge[0], piece["target"])
                piece["target"]["x"] = _sub(fixed_world[0], moving_offset[0])
                piece["target"]["y"] = _sub(fixed_world[1], moving_offset[1])
    except (KeyError, TypeError, ValueError) as exc:
        return _failed("construction_geometry_unavailable", piece_id=piece_id, detail=str(exc)[:160])
    _sync_target_keyframe(piece)
    return {"ok": True}


def _local_vertices(piece: dict[str, Any]) -> list[tuple[object, object]]:
    tag = str(piece.get("tag") or "")
    attrs = piece.get("attrs") if isinstance(piece.get("attrs"), dict) else {}
    if tag in {"polygon", "polyline"}:
        points = attrs.get("points")
        if isinstance(points, dict) and points.get("op") == "points" and isinstance(points.get("args"), list):
            vertices = [tuple(item) for item in points["args"] if isinstance(item, list) and len(item) == 2]
        elif isinstance(points, str):
            values = [float(item) for item in _NUMBER_RE.findall(points)]
            vertices = list(zip(values[::2], values[1::2], strict=True)) if len(values) % 2 == 0 else []
        else:
            vertices = []
        if tag == "polyline" and len(vertices) > 1 and vertices[0] == vertices[-1]:
            vertices.pop()
        if len(vertices) < 2:
            raise ValueError("construction_requires_polygon_vertices")
        return [(item[0], item[1]) for item in vertices]
    if tag == "rect":
        x = attrs.get("x", 0)
        y = attrs.get("y", 0)
        width = attrs.get("width")
        height = attrs.get("height")
        if width is None or height is None:
            raise ValueError("construction_rect_requires_dimensions")
        return [(x, y), (_add(x, width), y), (_add(x, width), _add(y, height)), (x, _add(y, height))]
    raise ValueError(f"construction_unsupported_piece_tag:{tag}")


def _vertex(vertices: list[tuple[object, object]], index: object) -> tuple[object, object]:
    if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(vertices):
        raise ValueError("construction_vertex_index_out_of_range")
    return vertices[index]


def _edge(vertices: list[tuple[object, object]], index: object) -> tuple[tuple[object, object], tuple[object, object]]:
    if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(vertices):
        raise ValueError("construction_edge_index_out_of_range")
    return vertices[index], vertices[(index + 1) % len(vertices)]


def _edge_angle(edge: tuple[tuple[object, object], tuple[object, object]]) -> object:
    dx = _sub(edge[1][0], edge[0][0])
    dy = _sub(edge[1][1], edge[0][1])
    if _is_number(dx) and _is_number(dy):
        return math.degrees(math.atan2(float(dy), float(dx)))
    return {"op": "rad_to_deg", "args": [{"op": "atan2", "args": [dy, dx]}]}


def _world_point(point: tuple[object, object], transform: dict[str, Any]) -> tuple[object, object]:
    offset = _rotated_scaled_point(point, transform)
    return _add(transform.get("x", 0), offset[0]), _add(transform.get("y", 0), offset[1])


def _rotated_scaled_point(
    point: tuple[object, object], transform: dict[str, Any]
) -> tuple[object, object]:
    rotation = transform.get("rotation", 0)
    scale = transform.get("scale", 1)
    if all(_is_number(value) for value in (*point, rotation, scale)):
        radians_value = math.radians(float(rotation))
        cosine_value = math.cos(radians_value)
        sine_value = math.sin(radians_value)
        return (
            _rounded(float(scale) * (float(point[0]) * cosine_value - float(point[1]) * sine_value)),
            _rounded(float(scale) * (float(point[0]) * sine_value + float(point[1]) * cosine_value)),
        )
    radians = {"op": "deg_to_rad", "args": [rotation]}
    cosine = {"op": "cos", "args": [radians]}
    sine = {"op": "sin", "args": [radians]}
    return (
        _mul(scale, _sub(_mul(point[0], cosine), _mul(point[1], sine))),
        _mul(scale, _add(_mul(point[0], sine), _mul(point[1], cosine))),
    )


def _sync_target_keyframe(piece: dict[str, Any]) -> None:
    target = piece.get("target") if isinstance(piece.get("target"), dict) else {}
    for keyframe in piece.get("keyframes", []):
        if isinstance(keyframe, dict) and _is_number(keyframe.get("at")) and float(keyframe["at"]) >= 1:
            keyframe.clear()
            keyframe.update({"at": 1, **json.loads(json.dumps(target, ensure_ascii=False))})


def _verify_constraints(
    ir: dict[str, Any],
    plan: dict[str, Any],
    constraints: list[object],
    target_boundary: object,
) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    for state_label, state in sample_geometry_states(plan):
        try:
            expanded_ir = _with_boundary_piece(ir, target_boundary) if isinstance(target_boundary, dict) else ir
            pieces = {str(piece["id"]): piece for piece in expand_geometry_ir(expanded_ir, state)}
            boundary_piece = pieces.pop("__construction_target_boundary__", None)
            boundary = _world_polygon(boundary_piece) if boundary_piece is not None else None
            for index, constraint in enumerate(constraints):
                if isinstance(constraint, dict):
                    error = _verify_constraint(pieces, constraint, boundary)
                    if error is not None:
                        errors.append({**error, "state": state_label, "index": index})
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(_issue("construction_verification_unavailable", state=state_label, detail=str(exc)[:160]))
    return {"ok": not errors, "errors": errors, "sample_count": 3}


def _verify_constraint(
    pieces: dict[str, dict[str, Any]],
    constraint: dict[str, Any],
    boundary: list[tuple[float, float]] | None,
) -> dict[str, Any] | None:
    constraint_type = str(constraint.get("type") or "")
    if constraint_type == "cover_target":
        if boundary is None:
            return _issue("target_boundary_required")
        piece_ids = [str(item) for item in constraint.get("piece_ids", [])]
        polygons = [_world_polygon(pieces[piece_id]) for piece_id in piece_ids if piece_id in pieces]
        if len(polygons) != len(piece_ids):
            return _issue("cover_target_piece_missing_after_expansion")
        coverage = _boundary_coverage_ratio(boundary, polygons)
        required = float(constraint.get("min_coverage_ratio", 0.97))
        return None if coverage + 1e-9 >= required else _issue(
            "cover_target_unsatisfied", coverage_ratio=round(coverage, 6), required_ratio=required
        )
    piece = pieces.get(str(constraint.get("piece_id") or ""))
    if piece is None:
        return _issue("construction_piece_missing_after_expansion")
    if constraint_type == "inside_target":
        if boundary is None:
            return _issue("target_boundary_required")
        bbox = _polygon_bbox(boundary)
        polygon = _world_polygon(piece)
        return None if all(_point_in_bbox(point, bbox, tolerance=0.75) for point in polygon) else _issue(
            "inside_target_unsatisfied"
        )
    if constraint_type == "rigid_transform":
        return None
    reference = pieces.get(str(constraint.get("to_piece_id") or ""))
    if reference is None:
        return _issue("construction_reference_missing_after_expansion")
    moving_polygon = _world_polygon(piece)
    reference_polygon = _world_polygon(reference)
    if constraint_type == "coincident_vertex":
        left = _numeric_vertex(moving_polygon, constraint.get("vertex"))
        right = _numeric_vertex(reference_polygon, constraint.get("to_vertex"))
        return None if _distance(left, right) <= 0.75 else _issue("coincident_vertex_unsatisfied")
    left_edge = _numeric_edge(moving_polygon, constraint.get("edge"))
    right_edge = _numeric_edge(reference_polygon, constraint.get("to_edge"))
    left_vector = (left_edge[1][0] - left_edge[0][0], left_edge[1][1] - left_edge[0][1])
    right_vector = (right_edge[1][0] - right_edge[0][0], right_edge[1][1] - right_edge[0][1])
    left_length = math.hypot(*left_vector)
    right_length = math.hypot(*right_vector)
    if left_length <= 1e-9 or right_length <= 1e-9:
        return _issue("construction_zero_length_edge")
    cross = abs(left_vector[0] * right_vector[1] - left_vector[1] * right_vector[0]) / (
        left_length * right_length
    )
    dot = abs(left_vector[0] * right_vector[0] + left_vector[1] * right_vector[1]) / (
        left_length * right_length
    )
    if constraint_type == "parallel_edge":
        return None if cross <= 1e-6 else _issue("parallel_edge_unsatisfied")
    if constraint_type == "perpendicular_edge":
        return None if dot <= 1e-6 else _issue("perpendicular_edge_unsatisfied")
    reverse = bool(constraint.get("reverse", False))
    expected_start = right_edge[1] if reverse else right_edge[0]
    expected_end = right_edge[0] if reverse else right_edge[1]
    length_delta = abs(left_length - right_length)
    if length_delta > 0.75:
        return _issue(
            "attach_edge_length_mismatch",
            left_length=round(left_length, 6),
            right_length=round(right_length, 6),
            length_delta=round(length_delta, 6),
            hint="equalize_local_edge_lengths_before_attach_edge",
        )
    start_distance = _distance(left_edge[0], expected_start)
    end_distance = _distance(left_edge[1], expected_end)
    if start_distance > 0.75 or end_distance > 0.75:
        return _issue(
            "attach_edge_endpoint_mismatch",
            start_distance=round(start_distance, 6),
            end_distance=round(end_distance, 6),
            reverse=reverse,
            hint="fix_piece_ids_edge_indices_or_reverse",
        )
    return None


def _world_polygon(piece: dict[str, Any]) -> list[tuple[float, float]]:
    polygon = piece_local_polygon(piece)
    transform = piece["target"]
    rotation = math.radians(float(transform.get("rotation", 0)))
    scale = float(transform.get("scale", 1))
    cosine = math.cos(rotation)
    sine = math.sin(rotation)
    x = float(transform.get("x", 0))
    y = float(transform.get("y", 0))
    return [
        (x + scale * (px * cosine - py * sine), y + scale * (px * sine + py * cosine))
        for px, py in polygon
    ]


def _with_boundary_piece(ir: dict[str, Any], boundary: object) -> dict[str, Any]:
    if not isinstance(boundary, dict) or set(boundary) != {"x", "y", "width", "height"}:
        raise ValueError("invalid_target_boundary")
    expanded = json.loads(json.dumps(ir, ensure_ascii=False))
    expanded["pieces"].append(
        {
            "id": "__construction_target_boundary__",
            "tag": "rect",
            "attrs": {
                "x": boundary["x"],
                "y": boundary["y"],
                "width": boundary["width"],
                "height": boundary["height"],
            },
            "source": {"x": 0, "y": 0, "rotation": 0, "scale": 1, "opacity": 0},
            "target": {"x": 0, "y": 0, "rotation": 0, "scale": 1, "opacity": 0},
            "keyframes": [],
        }
    )
    return expanded


def _boundary_coverage_ratio(
    boundary: list[tuple[float, float]], polygons: list[list[tuple[float, float]]]
) -> float:
    min_x, min_y, max_x, max_y = _polygon_bbox(boundary)
    if max_x - min_x <= 1e-9 or max_y - min_y <= 1e-9:
        raise ValueError("invalid_target_boundary_size")
    columns = 48
    rows = 32
    covered = 0
    for row in range(rows):
        y = min_y + (row + 0.5) * (max_y - min_y) / rows
        for column in range(columns):
            x = min_x + (column + 0.5) * (max_x - min_x) / columns
            if any(_point_in_polygon((x, y), polygon) for polygon in polygons):
                covered += 1
    return covered / (columns * rows)


def _point_in_polygon(point: tuple[float, float], polygon: list[tuple[float, float]]) -> bool:
    x, y = point
    inside = False
    previous = polygon[-1]
    for current in polygon:
        x1, y1 = previous
        x2, y2 = current
        if (y1 > y) != (y2 > y):
            crossing = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < crossing:
                inside = not inside
        previous = current
    return inside


def _polygon_bbox(polygon: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    return (
        min(point[0] for point in polygon),
        min(point[1] for point in polygon),
        max(point[0] for point in polygon),
        max(point[1] for point in polygon),
    )


def _point_in_bbox(
    point: tuple[float, float], bbox: tuple[float, float, float, float], *, tolerance: float
) -> bool:
    return (
        bbox[0] - tolerance <= point[0] <= bbox[2] + tolerance
        and bbox[1] - tolerance <= point[1] <= bbox[3] + tolerance
    )


def _numeric_vertex(vertices: list[tuple[float, float]], index: object) -> tuple[float, float]:
    if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(vertices):
        raise ValueError("construction_vertex_index_out_of_range")
    return vertices[index]


def _numeric_edge(
    vertices: list[tuple[float, float]], index: object
) -> tuple[tuple[float, float], tuple[float, float]]:
    point = _numeric_vertex(vertices, index)
    return point, vertices[(int(index) + 1) % len(vertices)]


def _distance(left: tuple[float, float], right: tuple[float, float]) -> float:
    return math.hypot(left[0] - right[0], left[1] - right[1])


def _expression_number(value: object) -> float | None:
    if _is_number(value):
        number = float(value)
        return number if number == number and number not in {float("inf"), float("-inf")} else None
    return None


def _expression_edge_length(edge: tuple[tuple[object, object], tuple[object, object]]) -> float | None:
    start, end = edge
    x1 = _expression_number(start[0])
    y1 = _expression_number(start[1])
    x2 = _expression_number(end[0])
    y2 = _expression_number(end[1])
    if None in {x1, y1, x2, y2}:
        return None
    return math.hypot(x2 - x1, y2 - y1)


def _add(*values: object) -> object:
    flattened = [value for value in values if not (_is_number(value) and abs(float(value)) <= 1e-12)]
    if not flattened:
        return 0
    if all(_is_number(value) for value in flattened):
        return _rounded(sum(float(value) for value in flattened))
    if len(flattened) == 1:
        return flattened[0]
    return {"op": "add", "args": flattened}


def _sub(left: object, right: object) -> object:
    if _is_number(right) and abs(float(right)) <= 1e-12:
        return left
    if _is_number(left) and _is_number(right):
        return _rounded(float(left) - float(right))
    return {"op": "sub", "args": [left, right]}


def _mul(*values: object) -> object:
    if any(_is_number(value) and abs(float(value)) <= 1e-12 for value in values):
        return 0
    flattened = [value for value in values if not (_is_number(value) and abs(float(value) - 1) <= 1e-12)]
    if not flattened:
        return 1
    if all(_is_number(value) for value in flattened):
        result = 1.0
        for value in flattened:
            result *= float(value)
        return _rounded(result)
    if len(flattened) == 1:
        return flattened[0]
    return {"op": "mul", "args": flattened}


def _rounded(value: float) -> int | float:
    rounded = round(value, 9)
    return int(rounded) if rounded.is_integer() else rounded


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _failed(issue_type: str, **details: Any) -> dict[str, Any]:
    return {"ok": False, "error": _issue(issue_type, **details)}


def _issue(issue_type: str, **details: Any) -> dict[str, Any]:
    return {"type": issue_type, **details}
