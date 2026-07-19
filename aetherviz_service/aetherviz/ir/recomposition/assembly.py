"""Deterministic world-coordinate assembly checks for recomposition targets."""

from __future__ import annotations

import math
import re
from collections import deque
from copy import deepcopy
from typing import Any

from aetherviz_service.aetherviz.ir.recomposition.constants import CANVAS_HEIGHT, CANVAS_WIDTH
from aetherviz_service.aetherviz.ir.recomposition.contract import (
    expand_geometry_ir,
    sample_geometry_states,
)

Point = tuple[float, float]
Polygon = list[Point]

_GRID_SIZE = 88
_CURVE_STEPS = 24
_NUMBER_PATTERN = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"


class AssemblyGeometryUnavailable(ValueError):
    """Raised when a declared assembly constraint cannot be measured."""


def evaluate_target_assembly(ir: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    """Evaluate structured target-assembly constraints at bounded plan states."""
    constraints = _constraints(plan)
    if not constraints:
        return {"ok": True, "errors": [], "warnings": [], "checks": [], "states": []}

    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    states: list[dict[str, Any]] = []
    source_states: list[dict[str, Any]] = []
    source_overlap_limit = min(
        (float(item.get("max_overlap_ratio", 0.1)) for item in constraints),
        default=0.1,
    )
    for state_label, state in sample_geometry_states(plan):
        pieces = expand_geometry_ir(ir, state)
        try:
            source_metrics = _assembly_metrics(pieces, stage="source")
            source_states.append({"state": state_label, **source_metrics})
            if source_metrics["overlap_ratio"] > source_overlap_limit:
                errors.append(
                    _issue(
                        "source_assembly_overlap_failed",
                        "源状态图元存在明显重叠，不能表示有效切分",
                        state=state_label,
                        overlap_ratio=source_metrics["overlap_ratio"],
                        maximum_overlap_ratio=source_overlap_limit,
                    )
                )
            if not _bbox_in_canvas(source_metrics["bbox"]):
                errors.append(
                    _issue(
                        "source_assembly_out_of_bounds",
                        "源状态整体超出画布边界",
                        state=state_label,
                        bbox=source_metrics["bbox"],
                        canvas=[0, 0, CANVAS_WIDTH, CANVAS_HEIGHT],
                    )
                )
        except (AssemblyGeometryUnavailable, KeyError, TypeError, ValueError) as exc:
            warnings.append(_issue("source_assembly_unavailable", str(exc), state=state_label))
        try:
            metrics = _assembly_metrics(pieces, stage="target")
        except (AssemblyGeometryUnavailable, KeyError, TypeError, ValueError) as exc:
            warnings.append(_issue("target_assembly_unavailable", str(exc), state=state_label))
            continue
        states.append({"state": state_label, **metrics})
        if not _bbox_in_canvas(metrics["bbox"]):
            errors.append(
                _issue(
                    "target_assembly_out_of_bounds",
                    "目标拼合整体超出画布边界",
                    state=state_label,
                    bbox=metrics["bbox"],
                    canvas=[0, 0, CANVAS_WIDTH, CANVAS_HEIGHT],
                )
            )
        for constraint in constraints:
            result = _evaluate_constraint(constraint, metrics)
            check = {
                "kind": "target_assembly",
                "name": constraint["id"],
                "constraint_type": constraint["type"],
                "state": state_label,
                **result,
            }
            checks.append(check)
            if not result["passed"]:
                errors.append(
                    _issue(
                        "target_assembly_failed",
                        f"目标拼合约束 {constraint['id']} 不成立",
                        constraint=constraint["id"],
                        constraint_type=constraint["type"],
                        state=state_label,
                        **{key: value for key, value in result.items() if key != "passed"},
                    )
                )

    for constraint in constraints:
        if not constraint.get("monotonic") or len(states) < 2:
            continue
        ordered_states = sorted(
            states,
            key=lambda item: {"minimum": 0, "default": 1, "maximum": 2}.get(str(item.get("state")), 3),
        )
        scores = [float(item["rectangularity"]) for item in ordered_states]
        tolerance = float(constraint.get("trend_tolerance", 0.08))
        passed = all(right + tolerance >= left for left, right in zip(scores, scores[1:], strict=False))
        checks.append(
            {
                "kind": "target_assembly_trend",
                "name": constraint["id"],
                "constraint_type": constraint["type"],
                "passed": passed,
                "scores": scores,
                "tolerance": tolerance,
            }
        )
        if not passed:
            errors.append(
                _issue(
                    "target_assembly_trend_failed",
                    f"目标拼合质量未随参数边界保持或改善：{constraint['id']}",
                    constraint=constraint["id"],
                    scores=scores,
                    tolerance=tolerance,
                )
            )

    if constraints and not states:
        errors.append(
            _issue(
                "target_assembly_not_measurable",
                "计划明确要求目标拼合约束，但所有采样状态均无法计算",
            )
        )
    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
        "states": states,
        "source_states": source_states,
    }


def measure_scene_footprints(ir: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    """Measure source/target visible unions without requiring an assembly constraint."""
    endpoints: dict[str, list[dict[str, Any]]] = {"source": [], "target": []}
    warnings: list[dict[str, Any]] = []
    for state_label, state in sample_geometry_states(plan):
        pieces = expand_geometry_ir(ir, state)
        for endpoint in endpoints:
            try:
                metrics = _assembly_metrics(pieces, stage=endpoint)
            except (AssemblyGeometryUnavailable, KeyError, TypeError, ValueError) as exc:
                warnings.append(_issue("scene_footprint_unavailable", str(exc), state=state_label, endpoint=endpoint))
                continue
            endpoints[endpoint].append({"state": state_label, **metrics})
    return {"endpoints": endpoints, "warnings": warnings}


def translate_target_assembly_into_canvas(
    ir: object,
    assembly_report: dict[str, Any],
) -> dict[str, Any]:
    """Translate a valid target assembly when its sampled union only misses canvas bounds."""
    if not isinstance(ir, dict):
        return {"ok": False, "changed": False, "reason": "invalid_geometry_ir", "ir": ir}
    errors = assembly_report.get("errors")
    if not isinstance(errors, list) or not errors:
        return {"ok": False, "changed": False, "reason": "no_assembly_error", "ir": ir}
    error_types = {str(item.get("type") or "") for item in errors if isinstance(item, dict)}
    if error_types != {"target_assembly_out_of_bounds"}:
        return {
            "ok": False,
            "changed": False,
            "reason": "assembly_has_non_bounds_failures",
            "ir": ir,
        }
    states = assembly_report.get("states")
    bboxes = (
        [item.get("bbox") for item in states if isinstance(item, dict) and _valid_bbox(item.get("bbox"))]
        if isinstance(states, list)
        else []
    )
    if not bboxes:
        return {"ok": False, "changed": False, "reason": "missing_target_bbox", "ir": ir}
    min_x = min(float(bbox[0]) for bbox in bboxes)
    min_y = min(float(bbox[1]) for bbox in bboxes)
    max_x = max(float(bbox[2]) for bbox in bboxes)
    max_y = max(float(bbox[3]) for bbox in bboxes)
    if max_x - min_x > CANVAS_WIDTH or max_y - min_y > CANVAS_HEIGHT:
        return {
            "ok": False,
            "changed": False,
            "reason": "target_union_larger_than_canvas",
            "ir": ir,
        }
    dx = _axis_translation(min_x, max_x, CANVAS_WIDTH)
    dy = _axis_translation(min_y, max_y, CANVAS_HEIGHT)
    if abs(dx) <= 1e-9 and abs(dy) <= 1e-9:
        return {"ok": True, "changed": False, "reason": "already_in_canvas", "ir": ir}

    repaired = deepcopy(ir)
    pieces = repaired.get("pieces")
    if not isinstance(pieces, list):
        return {"ok": False, "changed": False, "reason": "missing_pieces", "ir": ir}
    for piece in pieces:
        if not isinstance(piece, dict):
            continue
        _translate_transform(piece.get("target"), dx, dy)
        keyframes = piece.get("keyframes")
        if not isinstance(keyframes, list):
            continue
        for keyframe in keyframes:
            if isinstance(keyframe, dict) and _number(keyframe.get("at")) >= 1 - 1e-9:
                _translate_transform(keyframe, dx, dy)
    return {
        "ok": True,
        "changed": True,
        "reason": "target_assembly_translated_into_canvas",
        "translation": {"x": round(dx, 6), "y": round(dy, 6)},
        "ir": repaired,
    }


def _valid_bbox(value: object) -> bool:
    if not isinstance(value, list) or len(value) != 4:
        return False
    try:
        numbers = [float(item) for item in value]
    except (TypeError, ValueError):
        return False
    return all(math.isfinite(item) for item in numbers) and numbers[0] <= numbers[2] and numbers[1] <= numbers[3]


def _axis_translation(minimum: float, maximum: float, limit: float) -> float:
    if minimum < 0:
        return -minimum
    if maximum > limit:
        return limit - maximum
    return 0.0


def _translate_transform(value: object, dx: float, dy: float) -> None:
    if not isinstance(value, dict):
        return
    if abs(dx) > 1e-9:
        value["x"] = _translated_expression(value.get("x", 0), dx)
    if abs(dy) > 1e-9:
        value["y"] = _translated_expression(value.get("y", 0), dy)


def _translated_expression(value: object, delta: float) -> object:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return round(float(value) + delta, 9)
    return {"op": "add", "args": [value, round(delta, 9)]}


def _bbox_in_canvas(bbox: object) -> bool:
    if not isinstance(bbox, list) or len(bbox) != 4:
        return False
    min_x, min_y, max_x, max_y = (float(value) for value in bbox)
    return 0 <= min_x <= max_x <= CANVAS_WIDTH and 0 <= min_y <= max_y <= CANVAS_HEIGHT


def piece_local_polygon(piece: dict[str, Any]) -> Polygon:
    """Return a bounded polygonal outline for a supported evaluated SVG piece."""
    tag = str(piece.get("tag") or "")
    attrs = piece.get("attrs") if isinstance(piece.get("attrs"), dict) else {}
    if tag in {"polygon", "polyline"}:
        points = _parse_points(attrs.get("points"))
        if tag == "polyline" and points[0] != points[-1]:
            raise AssemblyGeometryUnavailable("非闭合 polyline 不能用于面积拼合")
        return points
    if tag == "rect":
        x = _number(attrs.get("x", 0))
        y = _number(attrs.get("y", 0))
        width = _number(attrs.get("width"))
        height = _number(attrs.get("height"))
        return [(x, y), (x + width, y), (x + width, y + height), (x, y + height)]
    if tag in {"circle", "ellipse"}:
        cx = _number(attrs.get("cx", 0))
        cy = _number(attrs.get("cy", 0))
        rx = _number(attrs.get("r" if tag == "circle" else "rx"))
        ry = _number(attrs.get("r" if tag == "circle" else "ry"))
        return [
            (
                cx + rx * math.cos(2 * math.pi * index / _CURVE_STEPS),
                cy + ry * math.sin(2 * math.pi * index / _CURVE_STEPS),
            )
            for index in range(_CURVE_STEPS)
        ]
    if tag == "path":
        return _sector_path_polygon(attrs.get("d"))
    raise AssemblyGeometryUnavailable(f"图元 {piece.get('id')}({tag}) 不支持面积拼合计算")


def polygon_area(points: Polygon) -> float:
    """Return unsigned polygon area."""
    if len(points) < 3:
        return 0.0
    return (
        abs(
            sum(
                first[0] * second[1] - second[0] * first[1]
                for first, second in zip(points, points[1:] + points[:1], strict=True)
            )
        )
        / 2
    )


def _assembly_metrics(pieces: list[dict[str, Any]], *, stage: str) -> dict[str, Any]:
    polygons: list[Polygon] = []
    unsupported: list[str] = []
    for piece in pieces:
        if _number(piece.get(stage, {}).get("opacity", 1)) <= 0.01:
            continue
        try:
            local = piece_local_polygon(piece)
            world = [_transform_point(point, piece.get(stage)) for point in local]
        except AssemblyGeometryUnavailable:
            unsupported.append(str(piece.get("id") or ""))
            continue
        if polygon_area(world) > 1e-6:
            polygons.append(world)
    if not polygons:
        raise AssemblyGeometryUnavailable("目标状态没有可计算面积的图元")
    if unsupported:
        raise AssemblyGeometryUnavailable(f"目标状态包含不支持的面积图元：{','.join(unsupported[:4])}")

    min_x = min(point[0] for polygon in polygons for point in polygon)
    max_x = max(point[0] for polygon in polygons for point in polygon)
    min_y = min(point[1] for polygon in polygons for point in polygon)
    max_y = max(point[1] for polygon in polygons for point in polygon)
    width = max_x - min_x
    height = max_y - min_y
    if width <= 1e-6 or height <= 1e-6:
        raise AssemblyGeometryUnavailable("目标拼合包围盒退化")

    cell = max(width, height) / _GRID_SIZE
    columns = max(1, math.ceil(width / cell))
    rows = max(1, math.ceil(height / cell))
    occupied: set[tuple[int, int]] = set()
    overlapped: set[tuple[int, int]] = set()
    for row in range(rows):
        y = min_y + (row + 0.5) * cell
        for column in range(columns):
            x = min_x + (column + 0.5) * cell
            count = sum(_point_in_polygon((x, y), polygon) for polygon in polygons)
            if count:
                occupied.add((column, row))
            if count > 1:
                overlapped.add((column, row))
    if not occupied:
        raise AssemblyGeometryUnavailable("目标拼合栅格采样为空")
    components = _component_count(occupied)
    total_piece_area = sum(polygon_area(polygon) for polygon in polygons)
    union_area = len(occupied) * cell * cell
    oriented_bbox_area = _minimum_oriented_bbox_area(polygons)
    overlap_ratio = max(0.0, (total_piece_area - union_area) / total_piece_area)
    raster_overlap_ratio = len(overlapped) / len(occupied)
    return {
        "piece_count": len(polygons),
        "component_count": components,
        "rectangularity": round(min(1.0, union_area / oriented_bbox_area), 6),
        "overlap_ratio": round(max(overlap_ratio, raster_overlap_ratio), 6),
        "bbox": [round(min_x, 3), round(min_y, 3), round(max_x, 3), round(max_y, 3)],
        "oriented_bbox_area": round(oriented_bbox_area, 3),
        "grid": [columns, rows],
    }


def _evaluate_constraint(constraint: dict[str, Any], metrics: dict[str, Any]) -> dict[str, Any]:
    constraint_type = constraint["type"]
    if constraint_type == "connected":
        limit = int(constraint.get("max_components", 1))
        actual = int(metrics["component_count"])
        return {"passed": actual <= limit, "actual": actual, "maximum": limit}
    if constraint_type == "non_overlapping":
        limit = float(constraint.get("max_overlap_ratio", 0.08))
        actual = float(metrics["overlap_ratio"])
        return {"passed": actual <= limit, "actual": actual, "maximum": limit}
    if constraint_type == "approximate_rectangle":
        minimum = float(constraint.get("min_rectangularity", 0.62))
        overlap_limit = float(constraint.get("max_overlap_ratio", 0.1))
        components_limit = int(constraint.get("max_components", 1))
        rectangularity = float(metrics["rectangularity"])
        overlap = float(metrics["overlap_ratio"])
        components = int(metrics["component_count"])
        return {
            "passed": rectangularity >= minimum and overlap <= overlap_limit and components <= components_limit,
            "rectangularity": rectangularity,
            "minimum_rectangularity": minimum,
            "overlap_ratio": overlap,
            "maximum_overlap_ratio": overlap_limit,
            "component_count": components,
            "maximum_components": components_limit,
        }
    raise AssemblyGeometryUnavailable(f"不支持的目标拼合约束：{constraint_type}")


def _constraints(plan: dict[str, Any]) -> list[dict[str, Any]]:
    spec = plan.get("recomposition_spec") if isinstance(plan.get("recomposition_spec"), dict) else {}
    proof = spec.get("proof_constraints") if isinstance(spec.get("proof_constraints"), dict) else {}
    value = proof.get("target_assembly")
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _sector_path_polygon(value: object) -> Polygon:
    if not isinstance(value, str):
        raise AssemblyGeometryUnavailable("path d 必须是已求值字符串")
    numbers = [float(item) for item in re.findall(_NUMBER_PATTERN, value)]
    # Restricted sector_path emits: M cx cy L sx sy A r r 0 large sweep ex ey Z.
    if (
        len(numbers) != 11
        or not value.lstrip().startswith("M")
        or " A " not in value
        or not value.rstrip().endswith("Z")
    ):
        raise AssemblyGeometryUnavailable("仅支持由 sector_path 生成的闭合 path")
    cx, cy, sx, sy, rx, ry, _axis, large, sweep, ex, ey = numbers[:11]
    if not math.isclose(rx, ry, rel_tol=1e-6, abs_tol=1e-6) or rx <= 0:
        raise AssemblyGeometryUnavailable("sector_path 半径无效")
    start = math.atan2(sy - cy, sx - cx)
    end = math.atan2(ey - cy, ex - cx)
    delta = (end - start) % (2 * math.pi) if sweep else -((start - end) % (2 * math.pi))
    if bool(large) != (abs(delta) > math.pi):
        delta += -2 * math.pi if delta > 0 else 2 * math.pi
    steps = max(4, math.ceil(abs(delta) / (2 * math.pi) * _CURVE_STEPS))
    return [(cx, cy)] + [
        (cx + rx * math.cos(start + delta * index / steps), cy + rx * math.sin(start + delta * index / steps))
        for index in range(steps + 1)
    ]


def _transform_point(point: Point, transform: object) -> Point:
    if not isinstance(transform, dict):
        raise AssemblyGeometryUnavailable("图元变换不完整")
    scale = _number(transform.get("scale", 1))
    angle = math.radians(_number(transform.get("rotation", 0)))
    x = point[0] * scale
    y = point[1] * scale
    return (
        x * math.cos(angle) - y * math.sin(angle) + _number(transform.get("x", 0)),
        x * math.sin(angle) + y * math.cos(angle) + _number(transform.get("y", 0)),
    )


def _parse_points(value: object) -> Polygon:
    if not isinstance(value, str):
        raise AssemblyGeometryUnavailable("points 必须是已求值字符串")
    numbers = [float(item) for item in re.findall(_NUMBER_PATTERN, value)]
    if len(numbers) < 6 or len(numbers) % 2:
        raise AssemblyGeometryUnavailable("points 坐标不完整")
    return list(zip(numbers[::2], numbers[1::2], strict=True))


def _point_in_polygon(point: Point, polygon: Polygon) -> bool:
    x, y = point
    inside = False
    previous = polygon[-1]
    for current in polygon:
        x1, y1 = previous
        x2, y2 = current
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
        previous = current
    return inside


def _component_count(occupied: set[tuple[int, int]]) -> int:
    remaining = set(occupied)
    components = 0
    while remaining:
        components += 1
        queue = deque([remaining.pop()])
        while queue:
            column, row = queue.popleft()
            for neighbor in ((column - 1, row), (column + 1, row), (column, row - 1), (column, row + 1)):
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    queue.append(neighbor)
    return components


def _minimum_oriented_bbox_area(polygons: list[Polygon]) -> float:
    points = [point for polygon in polygons for point in polygon]
    angles = {
        round(math.atan2(second[1] - first[1], second[0] - first[0]) % (math.pi / 2), 6)
        for polygon in polygons
        for first, second in zip(polygon, polygon[1:] + polygon[:1], strict=True)
        if math.dist(first, second) > 1e-9
    }
    ordered = sorted(angles)
    if len(ordered) > 256:
        stride = math.ceil(len(ordered) / 256)
        ordered = ordered[::stride]
    minimum = math.inf
    for angle in ordered or [0.0]:
        cosine = math.cos(angle)
        sine = math.sin(angle)
        rotated_x = [point[0] * cosine + point[1] * sine for point in points]
        rotated_y = [-point[0] * sine + point[1] * cosine for point in points]
        area = (max(rotated_x) - min(rotated_x)) * (max(rotated_y) - min(rotated_y))
        minimum = min(minimum, area)
    if not math.isfinite(minimum) or minimum <= 1e-6:
        raise AssemblyGeometryUnavailable("目标拼合最小方向包围盒退化")
    return minimum


def _number(value: object) -> float:
    if isinstance(value, bool):
        raise AssemblyGeometryUnavailable("需要有限数值")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise AssemblyGeometryUnavailable("需要有限数值") from exc
    if not math.isfinite(number):
        raise AssemblyGeometryUnavailable("需要有限数值")
    return number


def _issue(issue_type: str, message: str, **details: object) -> dict[str, Any]:
    return {"type": issue_type, "message": message, **details}
