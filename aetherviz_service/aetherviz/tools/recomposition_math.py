"""Deterministic mathematical invariants for generic 2D recomposition IR."""

from __future__ import annotations

import math
import re
from typing import Any

from aetherviz_service.aetherviz.tools.recomposition_ir import (
    expand_geometry_ir,
    sample_geometry_states,
)

DEFAULT_TOLERANCE = 1e-6
MAX_RELATIONS = 12
ALLOWED_RELATION_TYPES = {
    "equal_area",
    "equal_length",
    "equal_angle",
    "parallel",
    "perpendicular",
    "coincident",
    "collinear",
    "congruent",
}

Point = tuple[float, float]


class GeometryRelationUnavailable(ValueError):
    """Raised when a relation is valid but the current geometry cannot prove it."""


def evaluate_mathematical_invariants(ir: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    """Evaluate declared invariants and structured relations over bounded plan states."""
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    proof = _proof_constraints(plan)
    invariants = [str(item) for item in proof.get("measure_invariants", [])]
    relations = proof.get("target_relations", [])
    if not isinstance(relations, list):
        relations = []

    for state_label, state in sample_geometry_states(plan):
        try:
            pieces = expand_geometry_ir(ir, state)
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(_issue("mathematical_geometry_expansion", str(exc), state=state_label))
            continue
        piece_map = {str(piece.get("id")): piece for piece in pieces}
        for invariant in invariants:
            passed, details = _evaluate_invariant(invariant, pieces)
            check = {"kind": "invariant", "name": invariant, "state": state_label, **details}
            checks.append({**check, "passed": passed})
            if not passed:
                errors.append(
                    _issue(
                        "mathematical_invariant_failed",
                        f"度量不变量 {invariant} 不成立",
                        invariant=invariant,
                        state=state_label,
                        **details,
                    )
                )
        for index, relation in enumerate(relations[:MAX_RELATIONS]):
            if not isinstance(relation, dict):
                warnings.append(
                    _issue(
                        "unstructured_target_relation",
                        "目标关系不是可计算对象",
                        relation=index,
                        state=state_label,
                    )
                )
                continue
            relation_id = str(relation.get("id") or f"relation-{index}")
            relation_type = str(relation.get("type") or "")
            if relation_type not in ALLOWED_RELATION_TYPES:
                warnings.append(
                    _issue(
                        "unsupported_target_relation",
                        "目标关系类型不可计算",
                        relation=relation_id,
                        relation_type=relation_type,
                        state=state_label,
                    )
                )
                continue
            try:
                passed, details = _evaluate_relation(relation, piece_map)
            except GeometryRelationUnavailable as exc:
                warnings.append(
                    _issue(
                        "target_relation_unavailable",
                        str(exc),
                        relation=relation_id,
                        relation_type=relation_type,
                        state=state_label,
                    )
                )
                continue
            checks.append(
                {
                    "kind": "relation",
                    "name": relation_id,
                    "relation_type": relation_type,
                    "state": state_label,
                    "passed": passed,
                    **details,
                }
            )
            if not passed:
                errors.append(
                    _issue(
                        "mathematical_relation_failed",
                        f"结构化几何关系 {relation_id} 不成立",
                        relation=relation_id,
                        relation_type=relation_type,
                        state=state_label,
                        **details,
                    )
                )
    return {"ok": not errors, "errors": errors, "warnings": warnings, "checks": checks}


def _proof_constraints(plan: dict[str, Any]) -> dict[str, Any]:
    spec = plan.get("recomposition_spec") if isinstance(plan.get("recomposition_spec"), dict) else {}
    proof = spec.get("proof_constraints") if isinstance(spec.get("proof_constraints"), dict) else {}
    return proof


def _evaluate_invariant(name: str, pieces: list[dict[str, Any]]) -> tuple[bool, dict[str, Any]]:
    failed: list[str] = []
    for piece in pieces:
        piece_id = str(piece.get("id"))
        source_scale = _scale(piece, "source")
        target_scale = _scale(piece, "target")
        keyframe_scales = [float(frame.get("scale", 1)) for frame in piece.get("keyframes", [])]
        scales = [source_scale, *keyframe_scales, target_scale]
        if name == "area_preserved" and any(
            not math.isclose(abs(scale) ** 2, abs(source_scale) ** 2, rel_tol=DEFAULT_TOLERANCE, abs_tol=DEFAULT_TOLERANCE)
            for scale in scales[1:]
        ):
            failed.append(piece_id)
        elif name == "length_preserved" and any(
            not math.isclose(abs(scale), abs(source_scale), rel_tol=DEFAULT_TOLERANCE, abs_tol=DEFAULT_TOLERANCE)
            for scale in scales[1:]
        ):
            failed.append(piece_id)
        elif name == "angle_preserved" and any(scale <= 0 for scale in scales):
            failed.append(piece_id)
        elif name == "piece_congruence" and not _pieces_congruent(piece, "source", piece, "target"):
            failed.append(piece_id)
    return not failed, {"failed_pieces": failed}


def _evaluate_relation(
    relation: dict[str, Any], piece_map: dict[str, dict[str, Any]]
) -> tuple[bool, dict[str, Any]]:
    relation_type = str(relation["type"])
    tolerance = _tolerance(relation.get("tolerance"))
    if relation_type == "equal_area":
        left = _area(relation.get("left"), piece_map)
        right = _area(relation.get("right"), piece_map)
        return _close(left, right, tolerance), {"left": left, "right": right, "tolerance": tolerance}
    if relation_type == "equal_length":
        left = _segment_length(relation.get("left"), piece_map)
        right = _segment_length(relation.get("right"), piece_map)
        return _close(left, right, tolerance), {"left": left, "right": right, "tolerance": tolerance}
    if relation_type == "equal_angle":
        left = _angle(relation.get("left"), piece_map)
        right = _angle(relation.get("right"), piece_map)
        return _close(left, right, tolerance), {"left": left, "right": right, "tolerance": tolerance}
    if relation_type in {"parallel", "perpendicular"}:
        first = _segment_vector(relation.get("left"), piece_map)
        second = _segment_vector(relation.get("right"), piece_map)
        denominator = _vector_length(first) * _vector_length(second)
        if denominator <= DEFAULT_TOLERANCE:
            raise GeometryRelationUnavailable("线段长度过小，无法判定方向关系")
        value = abs(_cross(first, second)) / denominator if relation_type == "parallel" else abs(_dot(first, second)) / denominator
        return value <= tolerance, {"normalized_residual": value, "tolerance": tolerance}
    if relation_type == "coincident":
        left = _point(relation.get("left"), piece_map)
        right = _point(relation.get("right"), piece_map)
        distance = math.dist(left, right)
        return distance <= tolerance, {"distance": distance, "tolerance": tolerance}
    if relation_type == "collinear":
        raw_points = relation.get("points")
        if not isinstance(raw_points, list) or not 3 <= len(raw_points) <= 8:
            raise GeometryRelationUnavailable("共线关系需要 3~8 个点")
        points = [_point(item, piece_map) for item in raw_points]
        baseline = (points[1][0] - points[0][0], points[1][1] - points[0][1])
        baseline_length = _vector_length(baseline)
        if baseline_length <= DEFAULT_TOLERANCE:
            raise GeometryRelationUnavailable("共线关系的基准点重合")
        residual = max(
            abs(_cross(baseline, (point[0] - points[0][0], point[1] - points[0][1]))) / baseline_length
            for point in points[2:]
        )
        return residual <= tolerance, {"distance_residual": residual, "tolerance": tolerance}
    if relation_type == "congruent":
        left_piece, left_stage = _piece_ref(relation.get("left"), piece_map)
        right_piece, right_stage = _piece_ref(relation.get("right"), piece_map)
        passed = _pieces_congruent(left_piece, left_stage, right_piece, right_stage, tolerance)
        return passed, {"tolerance": tolerance}
    raise GeometryRelationUnavailable(f"不支持的关系：{relation_type}")


def _area(reference: object, piece_map: dict[str, dict[str, Any]]) -> float:
    if not isinstance(reference, dict):
        raise GeometryRelationUnavailable("面积引用必须是对象")
    stage = _stage(reference)
    piece_ids = reference.get("piece_ids")
    if piece_ids is None:
        pieces = list(piece_map.values())
    elif isinstance(piece_ids, list) and piece_ids:
        pieces = [_require_piece(str(piece_id), piece_map) for piece_id in piece_ids]
    else:
        raise GeometryRelationUnavailable("piece_ids 必须是非空数组")
    total = 0.0
    for piece in pieces:
        base = _base_area(piece)
        total += base * abs(_scale(piece, stage)) ** 2
    return total


def _base_area(piece: dict[str, Any]) -> float:
    tag = str(piece.get("tag"))
    attrs = piece.get("attrs", {})
    if tag in {"polygon", "polyline"}:
        points = _parse_points(attrs.get("points"))
        if tag == "polyline" and points[0] != points[-1]:
            raise GeometryRelationUnavailable("非闭合 polyline 没有可计算面积")
        return abs(
            sum(
                x1 * y2 - x2 * y1
                for (x1, y1), (x2, y2) in zip(
                    points, points[1:] + points[:1], strict=True
                )
            )
        ) / 2
    if tag == "rect":
        return _number(attrs.get("width")) * _number(attrs.get("height"))
    if tag == "circle":
        return math.pi * _number(attrs.get("r")) ** 2
    if tag == "ellipse":
        return math.pi * _number(attrs.get("rx")) * _number(attrs.get("ry"))
    raise GeometryRelationUnavailable(f"图元 {piece.get('id')}({tag}) 没有可计算面积")


def _segment_length(reference: object, piece_map: dict[str, dict[str, Any]]) -> float:
    return _vector_length(_segment_vector(reference, piece_map))


def _segment_vector(reference: object, piece_map: dict[str, dict[str, Any]]) -> Point:
    if not isinstance(reference, dict):
        raise GeometryRelationUnavailable("线段引用必须是对象")
    start = _point(reference.get("start"), piece_map)
    end = _point(reference.get("end"), piece_map)
    return end[0] - start[0], end[1] - start[1]


def _angle(reference: object, piece_map: dict[str, dict[str, Any]]) -> float:
    if not isinstance(reference, dict) or not isinstance(reference.get("points"), list) or len(reference["points"]) != 3:
        raise GeometryRelationUnavailable("角引用需要三个点")
    first, vertex, last = [_point(item, piece_map) for item in reference["points"]]
    left = (first[0] - vertex[0], first[1] - vertex[1])
    right = (last[0] - vertex[0], last[1] - vertex[1])
    denominator = _vector_length(left) * _vector_length(right)
    if denominator <= DEFAULT_TOLERANCE:
        raise GeometryRelationUnavailable("角的边长度过小")
    cosine = max(-1.0, min(1.0, _dot(left, right) / denominator))
    return math.acos(cosine)


def _point(reference: object, piece_map: dict[str, dict[str, Any]]) -> Point:
    if not isinstance(reference, dict):
        raise GeometryRelationUnavailable("点引用必须是对象")
    piece = _require_piece(str(reference.get("piece_id") or ""), piece_map)
    stage = _stage(reference)
    points = _local_points(piece)
    anchor = str(reference.get("anchor") or "center")
    if anchor == "center":
        local = (sum(point[0] for point in points) / len(points), sum(point[1] for point in points) / len(points))
    elif anchor == "vertex":
        index = reference.get("index")
        if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(points):
            raise GeometryRelationUnavailable(f"图元 {piece.get('id')} 的顶点索引不合法")
        local = points[index]
    else:
        raise GeometryRelationUnavailable(f"不支持的点锚点：{anchor}")
    return _transform_point(local, piece.get(stage, {}))


def _local_points(piece: dict[str, Any]) -> list[Point]:
    tag = str(piece.get("tag"))
    attrs = piece.get("attrs", {})
    if tag in {"polygon", "polyline"}:
        return _parse_points(attrs.get("points"))
    if tag == "rect":
        x = _number(attrs.get("x", 0))
        y = _number(attrs.get("y", 0))
        width = _number(attrs.get("width"))
        height = _number(attrs.get("height"))
        return [(x, y), (x + width, y), (x + width, y + height), (x, y + height)]
    if tag == "line":
        return [(_number(attrs.get("x1")), _number(attrs.get("y1"))), (_number(attrs.get("x2")), _number(attrs.get("y2")))]
    if tag in {"circle", "ellipse"}:
        cx = _number(attrs.get("cx", 0))
        cy = _number(attrs.get("cy", 0))
        rx = _number(attrs.get("r" if tag == "circle" else "rx"))
        ry = _number(attrs.get("r" if tag == "circle" else "ry"))
        return [(cx + rx, cy), (cx, cy + ry), (cx - rx, cy), (cx, cy - ry)]
    raise GeometryRelationUnavailable(f"图元 {piece.get('id')}({tag}) 没有可引用顶点")


def _pieces_congruent(
    left: dict[str, Any],
    left_stage: str,
    right: dict[str, Any],
    right_stage: str,
    tolerance: float = DEFAULT_TOLERANCE,
) -> bool:
    if left.get("tag") != right.get("tag"):
        return False
    left_scale = abs(_scale(left, left_stage))
    right_scale = abs(_scale(right, right_stage))
    tag = str(left.get("tag"))
    if tag == "path":
        return left.get("attrs", {}).get("d") == right.get("attrs", {}).get("d") and _close(left_scale, right_scale, tolerance)
    try:
        left_signature = _distance_signature(_local_points(left), left_scale)
        right_signature = _distance_signature(_local_points(right), right_scale)
    except GeometryRelationUnavailable:
        return False
    return len(left_signature) == len(right_signature) and all(
        _close(first, second, tolerance)
        for first, second in zip(left_signature, right_signature, strict=True)
    )


def _distance_signature(points: list[Point], scale: float) -> list[float]:
    if not points:
        raise GeometryRelationUnavailable("图元没有几何点")
    return sorted(math.dist(points[first], points[second]) * scale for first in range(len(points)) for second in range(first + 1, len(points)))


def _piece_ref(reference: object, piece_map: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], str]:
    if not isinstance(reference, dict):
        raise GeometryRelationUnavailable("图元引用必须是对象")
    return _require_piece(str(reference.get("piece_id") or ""), piece_map), _stage(reference)


def _require_piece(piece_id: str, piece_map: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if piece_id not in piece_map:
        raise GeometryRelationUnavailable(f"未找到图元：{piece_id}")
    return piece_map[piece_id]


def _stage(reference: dict[str, Any]) -> str:
    stage = str(reference.get("stage") or "target")
    if stage not in {"source", "target"}:
        raise GeometryRelationUnavailable(f"不支持的几何阶段：{stage}")
    return stage


def _scale(piece: dict[str, Any], stage: str) -> float:
    transform = piece.get(stage)
    if not isinstance(transform, dict):
        raise GeometryRelationUnavailable(f"图元 {piece.get('id')} 缺少 {stage} 变换")
    return _number(transform.get("scale", 1))


def _transform_point(point: Point, transform: object) -> Point:
    if not isinstance(transform, dict):
        raise GeometryRelationUnavailable("点变换不完整")
    scale = _number(transform.get("scale", 1))
    angle = math.radians(_number(transform.get("rotation", 0)))
    x = point[0] * scale
    y = point[1] * scale
    return (
        x * math.cos(angle) - y * math.sin(angle) + _number(transform.get("x", 0)),
        x * math.sin(angle) + y * math.cos(angle) + _number(transform.get("y", 0)),
    )


def _parse_points(value: object) -> list[Point]:
    if not isinstance(value, str):
        raise GeometryRelationUnavailable("points 必须是已求值字符串")
    numbers = [float(item) for item in re.findall(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?", value)]
    if len(numbers) < 4 or len(numbers) % 2:
        raise GeometryRelationUnavailable("points 坐标不完整")
    return list(zip(numbers[::2], numbers[1::2], strict=True))


def _number(value: object) -> float:
    if isinstance(value, bool):
        raise GeometryRelationUnavailable("需要有限数值")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise GeometryRelationUnavailable("需要有限数值") from exc
    if not math.isfinite(number):
        raise GeometryRelationUnavailable("需要有限数值")
    return number


def _tolerance(value: object) -> float:
    try:
        tolerance = float(value) if value is not None else DEFAULT_TOLERANCE
    except (TypeError, ValueError):
        tolerance = DEFAULT_TOLERANCE
    return min(0.1, max(1e-9, tolerance))


def _close(left: float, right: float, tolerance: float) -> bool:
    return math.isclose(left, right, rel_tol=tolerance, abs_tol=tolerance)


def _vector_length(vector: Point) -> float:
    return math.hypot(vector[0], vector[1])


def _dot(left: Point, right: Point) -> float:
    return left[0] * right[0] + left[1] * right[1]


def _cross(left: Point, right: Point) -> float:
    return left[0] * right[1] - left[1] * right[0]


def _issue(issue_type: str, message: str, **details: object) -> dict[str, Any]:
    return {"type": issue_type, "message": message, **details}
