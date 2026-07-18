"""Strict contract and deterministic statistics compiler for data scenes."""

from __future__ import annotations

import json
import math
import statistics
from copy import deepcopy
from hashlib import sha256
from typing import Any

DATA_DISTRIBUTION_IR_VERSION = "aetherviz.data-distribution-ir.v1"
DATA_DISTRIBUTION_IR_MAX_CHARS = 24_000
EXPRESSION_OPS = frozenset(
    {"add", "sub", "mul", "div", "pow", "min", "max", "neg", "abs", "sqrt", "round", "floor", "ceil"}
)
CHART_TYPES = frozenset({"table", "bar", "line", "scatter", "histogram", "box"})
METRIC_TYPES = frozenset(
    {
        "count",
        "sum",
        "mean",
        "median",
        "variance",
        "standard_deviation",
        "minimum",
        "maximum",
        "q1",
        "q3",
        "iqr",
        "linear_regression",
    }
)


class DataDistributionIRValidationError(ValueError):
    def __init__(self, report: dict[str, Any]) -> None:
        self.report = report
        super().__init__(report.get("summary") or "data_distribution_ir_invalid")


def _expression_schema() -> dict[str, Any]:
    return {
        "oneOf": [
            {"type": "number"},
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["state"],
                "properties": {"state": {"type": "string", "minLength": 1, "maxLength": 64}},
            },
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["op", "args"],
                "properties": {
                    "op": {"type": "string", "enum": sorted(EXPRESSION_OPS)},
                    "args": {"type": "array", "minItems": 1, "maxItems": 4, "items": {"$ref": "#/$defs/expression"}},
                },
            },
        ]
    }


def data_distribution_ir_response_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "$defs": {"expression": _expression_schema()},
        "required": ["version", "animation", "fields", "rows", "charts", "metrics", "observation"],
        "properties": {
            "version": {"type": "string", "enum": [DATA_DISTRIBUTION_IR_VERSION]},
            "animation": {
                "type": "object",
                "additionalProperties": False,
                "required": ["variable", "from", "to", "default", "duration"],
                "properties": {
                    "variable": {"type": "string", "minLength": 1, "maxLength": 64},
                    "from": {"type": "number"},
                    "to": {"type": "number"},
                    "default": {"type": "number"},
                    "duration": {"type": "number", "minimum": 2, "maximum": 12},
                },
            },
            "fields": {
                "type": "array",
                "minItems": 1,
                "maxItems": 12,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["id", "label", "type"],
                    "properties": {
                        "id": {"type": "string", "minLength": 1, "maxLength": 64},
                        "label": {"type": "string", "minLength": 1, "maxLength": 32},
                        "type": {"type": "string", "enum": ["number", "category"]},
                        "unit": {"type": "string", "maxLength": 16},
                    },
                },
            },
            "rows": {
                "type": "array",
                "minItems": 2,
                "maxItems": 240,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["id", "cells"],
                    "properties": {
                        "id": {"type": "string", "minLength": 1, "maxLength": 64},
                        "cells": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 12,
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["field", "value"],
                                "properties": {
                                    "field": {"type": "string"},
                                    "value": {
                                        "oneOf": [
                                            {"type": "string", "maxLength": 80},
                                            {"$ref": "#/$defs/expression"},
                                        ]
                                    },
                                },
                            },
                        },
                    },
                },
            },
            "charts": {
                "type": "array",
                "minItems": 1,
                "maxItems": 4,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["id", "type", "title"],
                    "properties": {
                        "id": {"type": "string", "minLength": 1, "maxLength": 64},
                        "type": {"type": "string", "enum": sorted(CHART_TYPES)},
                        "title": {"type": "string", "minLength": 1, "maxLength": 48},
                        "x_field": {"type": "string"},
                        "y_field": {"type": "string"},
                        "category_field": {"type": "string"},
                        "value_field": {"type": "string"},
                        "group_field": {"type": "string"},
                        "bin_width": {"$ref": "#/$defs/expression"},
                    },
                },
            },
            "metrics": {
                "type": "array",
                "maxItems": 12,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["id", "type", "label", "precision"],
                    "properties": {
                        "id": {"type": "string", "minLength": 1, "maxLength": 64},
                        "type": {"type": "string", "enum": sorted(METRIC_TYPES)},
                        "label": {"type": "string", "minLength": 1, "maxLength": 40},
                        "field": {"type": "string"},
                        "x_field": {"type": "string"},
                        "y_field": {"type": "string"},
                        "precision": {"type": "integer", "minimum": 0, "maximum": 6},
                        "sample": {"type": "boolean"},
                    },
                },
            },
            "observation": {"type": "string", "minLength": 1, "maxLength": 240},
        },
    }


def data_distribution_ir_candidates_response_schema() -> dict[str, Any]:
    candidate = data_distribution_ir_response_schema()
    definitions = candidate.pop("$defs")
    return {
        "type": "object",
        "additionalProperties": False,
        "$defs": definitions,
        "required": ["candidates"],
        "properties": {"candidates": {"type": "array", "minItems": 2, "maxItems": 2, "items": candidate}},
    }


def normalize_data_distribution_ir(ir: object, plan: dict[str, Any]) -> object:
    if not isinstance(ir, dict):
        return ir
    candidate = deepcopy(ir)
    variables = _plan_variables(plan)
    animation = candidate.get("animation") if isinstance(candidate.get("animation"), dict) else {}
    selected = next(
        (item for item in variables if item["name"] == animation.get("variable")), variables[0] if variables else None
    )
    if selected:
        animation.update(
            {
                "variable": selected["name"],
                "from": selected["min"],
                "to": selected["max"],
                "default": selected["default"],
            }
        )
    candidate["animation"] = animation
    candidate.setdefault("metrics", [])
    return candidate


def validate_data_distribution_ir(ir: object, plan: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_data_distribution_ir(ir, plan)
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if not isinstance(normalized, dict):
        return _report([_error("invalid_data_distribution_ir", "数据分布 IR 必须是对象")], [])
    if normalized.get("version") != DATA_DISTRIBUTION_IR_VERSION:
        errors.append(_error("unsupported_data_distribution_ir_version", "数据分布 IR 版本不受支持"))
    variables = {item["name"]: item for item in _plan_variables(plan)}
    animation = normalized.get("animation") if isinstance(normalized.get("animation"), dict) else {}
    if animation.get("variable") not in variables:
        errors.append(_error("unknown_distribution_animation_state", "动画变量必须引用计划中的可调变量"))
    fields = normalized.get("fields") if isinstance(normalized.get("fields"), list) else []
    rows = normalized.get("rows") if isinstance(normalized.get("rows"), list) else []
    charts = normalized.get("charts") if isinstance(normalized.get("charts"), list) else []
    metrics = normalized.get("metrics") if isinstance(normalized.get("metrics"), list) else []
    try:
        duration = float(animation.get("duration"))
        if not math.isfinite(duration) or not 2 <= duration <= 12:
            raise ValueError
    except (TypeError, ValueError):
        errors.append(_error("invalid_distribution_animation_duration", "动画时长必须为 2 到 12 秒"))
    if not 1 <= len(fields) <= 12 or not 2 <= len(rows) <= 240:
        errors.append(_error("invalid_distribution_dataset_size", "字段数须为 1~12，数据行数须为 2~240"))
    if not 1 <= len(charts) <= 4 or len(metrics) > 12:
        errors.append(_error("invalid_distribution_view_size", "图表数须为 1~4，统计量不超过 12 个"))
    field_ids = _unique_ids(fields, "field", errors)
    row_ids = _unique_ids(rows, "row", errors)
    chart_ids = _unique_ids(charts, "chart", errors)
    metric_ids = _unique_ids(metrics, "metric", errors)
    if not field_ids or len(rows) < 2 or not chart_ids:
        errors.append(_error("incomplete_distribution_dataset", "至少需要一个字段、两行数据和一个图表"))
    numeric = {str(item.get("id")) for item in fields if isinstance(item, dict) and item.get("type") == "number"}
    categories = field_ids - numeric
    for row in rows:
        if not isinstance(row, dict):
            errors.append(_error("invalid_distribution_row", "数据行必须是对象"))
            continue
        cells = row.get("cells") if isinstance(row.get("cells"), list) else []
        refs = [str(cell.get("field")) for cell in cells if isinstance(cell, dict)]
        if len(refs) != len(set(refs)) or set(refs) != field_ids:
            errors.append(_error("invalid_distribution_row_cells", f"数据行 {row.get('id')} 必须且只能覆盖全部字段"))
        for cell in cells:
            if not isinstance(cell, dict):
                continue
            field = str(cell.get("field") or "")
            value = cell.get("value")
            if field in numeric:
                _validate_expression(value, variables, errors)
            elif field in categories and not isinstance(value, str):
                errors.append(_error("invalid_distribution_category", f"分类字段 {field} 必须使用字符串"))
    for chart in charts:
        _validate_chart(chart, field_ids, numeric, errors)
    for metric in metrics:
        _validate_metric(metric, numeric, errors)
    if len(set().union(row_ids, chart_ids, metric_ids)) != len(row_ids) + len(chart_ids) + len(metric_ids):
        errors.append(_error("duplicate_distribution_object_id", "行、图表和统计量 id 必须全局唯一"))
    if not errors:
        states = _sample_states(variables)
        for state in states:
            try:
                evaluated = _evaluate_rows(normalized, state)
                for chart in charts:
                    if chart.get("type") == "histogram":
                        width = _evaluate(chart.get("bin_width"), state)
                        values = [float(row[str(chart.get("value_field"))]) for row in evaluated]
                        if width <= 0 or (max(values) - min(values)) / width > 80:
                            raise ValueError("直方图分箱宽度必须为正且分箱数不超过 80")
                for metric in metrics:
                    _derive_metric(metric, evaluated)
            except (KeyError, TypeError, ValueError, ZeroDivisionError, OverflowError) as exc:
                errors.append(_error("distribution_derivation_failed", str(exc)))
                break
    return _report(errors, warnings)


def parse_data_distribution_ir(raw: str) -> dict[str, Any]:
    if len(raw) > DATA_DISTRIBUTION_IR_MAX_CHARS:
        raise ValueError("data_distribution_ir_too_large")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("data_distribution_ir_not_object")
    return value


def parse_data_distribution_ir_candidates(raw: str) -> list[dict[str, Any]]:
    value = json.loads(raw)
    candidates = value.get("candidates") if isinstance(value, dict) else None
    if (
        not isinstance(candidates, list)
        or len(candidates) != 2
        or not all(isinstance(item, dict) for item in candidates)
    ):
        raise ValueError("data_distribution_ir_candidates_invalid")
    return candidates


def rank_data_distribution_ir_candidates(candidates: list[dict[str, Any]], plan: dict[str, Any]) -> dict[str, Any]:
    ranked: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
    failures: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for candidate in candidates:
        normalized = normalize_data_distribution_ir(candidate, plan)
        report = validate_data_distribution_ir(normalized, plan)
        if report["ok"]:
            score = len(normalized.get("charts", [])) * 10 + len(normalized.get("metrics", []))
            ranked.append((score, normalized, report))
        else:
            failures.append((normalized, report))
    if ranked:
        ranked.sort(key=lambda item: item[0], reverse=True)
        return {"ok": True, "selected_ir": ranked[0][1], "report": ranked[0][2]}
    candidate, report = failures[0] if failures else ({}, _report([_error("missing_candidate", "没有候选 IR")], []))
    return {"ok": False, "repair_candidate": candidate, "repair_report": report}


def compile_data_distribution_ir(ir: dict[str, Any], plan: dict[str, Any]) -> str:
    normalized = normalize_data_distribution_ir(ir, plan)
    report = validate_data_distribution_ir(normalized, plan)
    if not report["ok"]:
        raise DataDistributionIRValidationError(report)
    payload = deepcopy(normalized)
    payload["contract_hash"] = sha256(
        json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:16]
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def derive_statistics(ir: dict[str, Any], state: dict[str, float]) -> dict[str, Any]:
    rows = _evaluate_rows(ir, state)
    return {str(item["id"]): _derive_metric(item, rows) for item in ir.get("metrics", [])}


def _validate_chart(chart: object, fields: set[str], numeric: set[str], errors: list[dict[str, Any]]) -> None:
    if not isinstance(chart, dict) or chart.get("type") not in CHART_TYPES:
        errors.append(_error("invalid_distribution_chart", "图表类型不受支持"))
        return
    kind = chart["type"]
    required = {
        "table": (),
        "bar": ("category_field", "value_field"),
        "line": ("x_field", "y_field"),
        "scatter": ("x_field", "y_field"),
        "histogram": ("value_field", "bin_width"),
        "box": ("value_field",),
    }[kind]
    for key in required:
        if key == "bin_width":
            if chart.get(key) is None:
                errors.append(_error("missing_distribution_chart_field", f"{kind} 缺少 {key}"))
        elif chart.get(key) not in fields:
            errors.append(_error("missing_distribution_chart_field", f"{kind} 的 {key} 引用无效"))
    for key in ("x_field", "y_field", "value_field"):
        if chart.get(key) is not None and chart.get(key) not in numeric:
            errors.append(_error("non_numeric_distribution_axis", f"{kind} 的 {key} 必须引用数值字段"))
    for key in ("category_field", "group_field"):
        if chart.get(key) is not None and chart.get(key) not in fields:
            errors.append(_error("unknown_distribution_group", f"{kind} 的 {key} 引用无效"))


def _validate_metric(metric: object, numeric: set[str], errors: list[dict[str, Any]]) -> None:
    if not isinstance(metric, dict) or metric.get("type") not in METRIC_TYPES:
        errors.append(_error("invalid_distribution_metric", "统计量类型不受支持"))
        return
    if metric["type"] == "linear_regression":
        if metric.get("x_field") not in numeric or metric.get("y_field") not in numeric:
            errors.append(_error("invalid_regression_fields", "线性回归必须引用两个数值字段"))
    elif metric.get("field") not in numeric:
        errors.append(_error("invalid_metric_field", f"统计量 {metric.get('id')} 必须引用数值字段"))


def _validate_expression(expr: object, variables: dict[str, dict[str, float]], errors: list[dict[str, Any]]) -> None:
    if isinstance(expr, bool):
        errors.append(_error("invalid_distribution_expression", "布尔值不是数值表达式"))
    elif isinstance(expr, (int, float)):
        if not math.isfinite(float(expr)):
            errors.append(_error("non_finite_distribution_value", "数据值必须有限"))
    elif isinstance(expr, dict) and set(expr) == {"state"}:
        if expr.get("state") not in variables:
            errors.append(_error("unknown_distribution_state", "表达式引用了未知状态"))
    elif (
        isinstance(expr, dict)
        and set(expr) == {"op", "args"}
        and expr.get("op") in EXPRESSION_OPS
        and isinstance(expr.get("args"), list)
        and 1 <= len(expr["args"]) <= 4
    ):
        for arg in expr["args"]:
            _validate_expression(arg, variables, errors)
    else:
        errors.append(_error("invalid_distribution_expression", "数值表达式结构或操作符无效"))


def _evaluate(expr: object, state: dict[str, float]) -> float:
    if isinstance(expr, bool):
        raise ValueError("布尔值不是数值")
    if isinstance(expr, (int, float)):
        value = float(expr)
    elif isinstance(expr, dict) and "state" in expr:
        value = float(state[str(expr["state"])])
    elif isinstance(expr, dict):
        values = [_evaluate(arg, state) for arg in expr.get("args", [])]
        op = expr.get("op")
        if op == "add":
            value = sum(values)
        elif op == "sub":
            value = values[0] - sum(values[1:])
        elif op == "mul":
            value = math.prod(values)
        elif op == "div":
            value = values[0] / math.prod(values[1:])
        elif op == "pow":
            value = values[0] ** values[1]
        elif op == "min":
            value = min(values)
        elif op == "max":
            value = max(values)
        elif op == "neg":
            value = -values[0]
        elif op == "abs":
            value = abs(values[0])
        elif op == "sqrt":
            value = math.sqrt(values[0])
        elif op == "round":
            value = round(values[0])
        elif op == "floor":
            value = math.floor(values[0])
        elif op == "ceil":
            value = math.ceil(values[0])
        else:
            raise ValueError("未知数据表达式操作符")
    else:
        raise ValueError("无效数据表达式")
    if not math.isfinite(value):
        raise ValueError("数据表达式结果必须有限")
    return value


def _evaluate_rows(ir: dict[str, Any], state: dict[str, float]) -> list[dict[str, Any]]:
    numeric = {str(item["id"]) for item in ir.get("fields", []) if item.get("type") == "number"}
    result = []
    for row in ir.get("rows", []):
        values = {
            str(cell["field"]): (_evaluate(cell["value"], state) if cell["field"] in numeric else str(cell["value"]))
            for cell in row["cells"]
        }
        values["__id"] = row["id"]
        result.append(values)
    return result


def _derive_metric(metric: dict[str, Any], rows: list[dict[str, Any]]) -> Any:
    kind = metric["type"]
    if kind == "linear_regression":
        xs = [float(row[metric["x_field"]]) for row in rows]
        ys = [float(row[metric["y_field"]]) for row in rows]
        x_mean, y_mean = statistics.fmean(xs), statistics.fmean(ys)
        denominator = sum((x - x_mean) ** 2 for x in xs)
        if denominator == 0:
            raise ValueError("线性回归的 x 不能全部相同")
        slope = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys, strict=True)) / denominator
        intercept = y_mean - slope * x_mean
        ss_total = sum((y - y_mean) ** 2 for y in ys)
        ss_residual = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, ys, strict=True))
        return {"slope": slope, "intercept": intercept, "r_squared": 1 - ss_residual / ss_total if ss_total else 1.0}
    values = sorted(float(row[metric["field"]]) for row in rows)
    if kind == "count":
        return len(values)
    if kind == "sum":
        return sum(values)
    if kind == "mean":
        return statistics.fmean(values)
    if kind == "median":
        return statistics.median(values)
    if kind == "variance":
        return statistics.variance(values) if metric.get("sample") else statistics.pvariance(values)
    if kind == "standard_deviation":
        return statistics.stdev(values) if metric.get("sample") else statistics.pstdev(values)
    if kind == "minimum":
        return min(values)
    if kind == "maximum":
        return max(values)
    q1, _, q3 = statistics.quantiles(values, n=4, method="inclusive")
    if kind == "q1":
        return q1
    if kind == "q3":
        return q3
    if kind == "iqr":
        return q3 - q1
    raise ValueError("未知统计量")


def _plan_variables(plan: dict[str, Any]) -> list[dict[str, float]]:
    spec = plan.get("interactive_spec") if isinstance(plan.get("interactive_spec"), dict) else {}
    result = []
    for item in spec.get("variables", []):
        if not isinstance(item, dict) or item.get("computed") or not item.get("name"):
            continue
        try:
            low, high, default = float(item.get("min")), float(item.get("max")), float(item.get("default"))
        except (TypeError, ValueError):
            continue
        if math.isfinite(low) and math.isfinite(high) and low < high and low <= default <= high:
            result.append({"name": str(item["name"]), "min": low, "max": high, "default": default})
    return result


def _sample_states(variables: dict[str, dict[str, float]]) -> list[dict[str, float]]:
    base = {name: item["default"] for name, item in variables.items()}
    states = [base]
    for name, item in variables.items():
        states.extend(({**base, name: item["min"]}, {**base, name: item["max"]}))
    return states


def _unique_ids(items: list[object], kind: str, errors: list[dict[str, Any]]) -> set[str]:
    ids = [str(item.get("id") or "") for item in items if isinstance(item, dict)]
    if any(not identifier for identifier in ids) or len(ids) != len(items) or len(ids) != len(set(ids)):
        errors.append(_error(f"invalid_{kind}_ids", f"{kind} id 必须非空且唯一"))
    return {identifier for identifier in ids if identifier}


def _error(kind: str, message: str) -> dict[str, Any]:
    return {"type": kind, "message": message}


def _report(errors: list[dict[str, Any]], warnings: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "ok": not errors,
        "severity": "error" if errors else ("warning" if warnings else "ok"),
        "summary": f"发现 {len(errors)} 个错误，{len(warnings)} 个提示"
        if errors or warnings
        else "数据分布 IR 检查通过",
        "errors": errors,
        "warnings": warnings,
    }
