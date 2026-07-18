"""Exact polynomial contract for step-by-step symbolic derivations."""

from __future__ import annotations

import json
import math
from copy import deepcopy
from fractions import Fraction
from hashlib import sha256
from typing import Any

SYMBOLIC_DERIVATION_IR_VERSION = "aetherviz.symbolic-derivation-ir.v1"
SYMBOLIC_DERIVATION_IR_MAX_CHARS = 20_000
OPS = frozenset({"add", "mul", "pow", "neg"})
RULES = frozenset(
    {
        "simplify",
        "expand",
        "factor",
        "commute",
        "associate",
        "distribute",
        "add_both_sides",
        "subtract_both_sides",
        "multiply_nonzero",
        "divide_nonzero",
        "substitute_identity",
    }
)


class SymbolicDerivationIRValidationError(ValueError):
    def __init__(self, report: dict[str, Any]) -> None:
        self.report = report
        super().__init__(report.get("summary") or "symbolic_derivation_ir_invalid")


def _expr_schema() -> dict[str, Any]:
    return {
        "oneOf": [
            {"type": "number"},
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["symbol"],
                "properties": {"symbol": {"type": "string", "pattern": "^[A-Za-z][A-Za-z0-9_]{0,15}$"}},
            },
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["op", "args"],
                "properties": {
                    "op": {"type": "string", "enum": sorted(OPS)},
                    "args": {"type": "array", "minItems": 1, "maxItems": 8, "items": {"$ref": "#/$defs/expression"}},
                },
            },
        ]
    }


def symbolic_derivation_ir_response_schema() -> dict[str, Any]:
    relation = {
        "type": "object",
        "additionalProperties": False,
        "required": ["left", "right"],
        "properties": {"left": {"$ref": "#/$defs/expression"}, "right": {"$ref": "#/$defs/expression"}},
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "$defs": {"expression": _expr_schema(), "relation": relation},
        "required": ["version", "mode", "variables", "steps", "observation"],
        "properties": {
            "version": {"type": "string", "enum": [SYMBOLIC_DERIVATION_IR_VERSION]},
            "mode": {"type": "string", "enum": ["expression", "equation"]},
            "variables": {
                "type": "array",
                "minItems": 1,
                "maxItems": 6,
                "uniqueItems": True,
                "items": {"type": "string", "pattern": "^[A-Za-z][A-Za-z0-9_]{0,15}$"},
            },
            "steps": {
                "type": "array",
                "minItems": 2,
                "maxItems": 16,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["id", "before", "after", "rule", "explanation"],
                    "properties": {
                        "id": {"type": "string", "minLength": 1, "maxLength": 48},
                        "before": {"$ref": "#/$defs/relation"},
                        "after": {"$ref": "#/$defs/relation"},
                        "rule": {"type": "string", "enum": sorted(RULES)},
                        "explanation": {"type": "string", "minLength": 1, "maxLength": 160},
                        "nonzero": {"type": "number"},
                    },
                },
            },
            "observation": {"type": "string", "minLength": 1, "maxLength": 240},
        },
    }


def symbolic_derivation_ir_candidates_response_schema() -> dict[str, Any]:
    item = symbolic_derivation_ir_response_schema()
    defs = item.pop("$defs")
    return {
        "type": "object",
        "additionalProperties": False,
        "$defs": defs,
        "required": ["candidates"],
        "properties": {"candidates": {"type": "array", "minItems": 2, "maxItems": 2, "items": item}},
    }


def validate_symbolic_derivation_ir(ir: object, _plan: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    if not isinstance(ir, dict):
        return _report([_error("invalid_symbolic_ir", "符号推导 IR 必须是对象")])
    if ir.get("version") != SYMBOLIC_DERIVATION_IR_VERSION:
        errors.append(_error("unsupported_symbolic_ir_version", "符号推导 IR 版本不受支持"))
    variables = ir.get("variables") if isinstance(ir.get("variables"), list) else []
    if not 1 <= len(variables) <= 6 or len(set(variables)) != len(variables):
        errors.append(_error("invalid_symbolic_variables", "变量须为 1~6 个且唯一"))
    steps = ir.get("steps") if isinstance(ir.get("steps"), list) else []
    if not 2 <= len(steps) <= 16:
        errors.append(_error("invalid_derivation_step_count", "推导步骤须为 2~16 步"))
    ids: set[str] = set()
    previous: object = None
    for step in steps:
        if not isinstance(step, dict):
            errors.append(_error("invalid_derivation_step", "推导步骤必须是对象"))
            continue
        identifier = str(step.get("id") or "")
        if not identifier or identifier in ids:
            errors.append(_error("invalid_derivation_step_id", "步骤 id 必须非空且唯一"))
        ids.add(identifier)
        if step.get("rule") not in RULES:
            errors.append(_error("invalid_derivation_rule", f"步骤 {identifier} 的规则不受支持"))
        try:
            before = _relation_poly(step.get("before"), set(variables))
            after = _relation_poly(step.get("after"), set(variables))
            if previous is not None and before != previous:
                errors.append(_error("disconnected_derivation_steps", f"步骤 {identifier} 未承接上一步结果"))
            if not _equivalent(before, after, equation=ir.get("mode") == "equation"):
                errors.append(_error("non_equivalent_derivation_step", f"步骤 {identifier} 前后不等价"))
            if step.get("rule") in {"multiply_nonzero", "divide_nonzero"}:
                value = step.get("nonzero")
                if (
                    not isinstance(value, (int, float))
                    or isinstance(value, bool)
                    or not math.isfinite(float(value))
                    or float(value) == 0
                ):
                    errors.append(_error("missing_nonzero_guard", f"步骤 {identifier} 必须声明非零常数"))
            previous = after
        except ValueError as exc:
            errors.append(_error("invalid_symbolic_expression", f"步骤 {identifier}: {exc}"))
    return _report(errors)


def parse_symbolic_derivation_ir(raw: str) -> dict[str, Any]:
    if len(raw) > SYMBOLIC_DERIVATION_IR_MAX_CHARS:
        raise ValueError("symbolic_derivation_ir_too_large")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("symbolic_derivation_ir_not_object")
    return value


def parse_symbolic_derivation_ir_candidates(raw: str) -> list[dict[str, Any]]:
    value = json.loads(raw)
    candidates = value.get("candidates") if isinstance(value, dict) else None
    if (
        not isinstance(candidates, list)
        or len(candidates) != 2
        or not all(isinstance(item, dict) for item in candidates)
    ):
        raise ValueError("symbolic_derivation_ir_candidates_invalid")
    return candidates


def rank_symbolic_derivation_ir_candidates(candidates: list[dict[str, Any]], plan: dict[str, Any]) -> dict[str, Any]:
    valid = [(len(item.get("steps", [])), item, validate_symbolic_derivation_ir(item, plan)) for item in candidates]
    valid = [item for item in valid if item[2]["ok"]]
    if valid:
        valid.sort(key=lambda item: item[0], reverse=True)
        return {"ok": True, "selected_ir": valid[0][1], "report": valid[0][2]}
    candidate = candidates[0] if candidates else {}
    return {
        "ok": False,
        "repair_candidate": candidate,
        "repair_report": validate_symbolic_derivation_ir(candidate, plan),
    }


def compile_symbolic_derivation_ir(ir: dict[str, Any], plan: dict[str, Any]) -> str:
    report = validate_symbolic_derivation_ir(ir, plan)
    if not report["ok"]:
        raise SymbolicDerivationIRValidationError(report)
    payload = deepcopy(ir)
    payload["contract_hash"] = sha256(
        json.dumps(ir, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:16]
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


Monomial = tuple[tuple[str, int], ...]
Polynomial = dict[Monomial, Fraction]


def _poly(expr: object, variables: set[str]) -> Polynomial:
    if isinstance(expr, bool):
        raise ValueError("布尔值不是代数表达式")
    if isinstance(expr, (int, float)):
        if not math.isfinite(float(expr)):
            raise ValueError("常数必须有限")
        return {(): Fraction(str(expr))}
    if isinstance(expr, dict) and set(expr) == {"symbol"}:
        symbol = str(expr["symbol"])
        if symbol not in variables:
            raise ValueError(f"未知变量 {symbol}")
        return {((symbol, 1),): Fraction(1)}
    if (
        not isinstance(expr, dict)
        or set(expr) != {"op", "args"}
        or expr.get("op") not in OPS
        or not isinstance(expr.get("args"), list)
    ):
        raise ValueError("表达式 AST 无效")
    args = expr["args"]
    if not 1 <= len(args) <= 8:
        raise ValueError("操作数数量无效")
    op = expr["op"]
    if op == "add":
        result: Polynomial = {}
        for arg in args:
            result = _add(result, _poly(arg, variables))
        return result
    if op == "mul":
        result = {(): Fraction(1)}
        for arg in args:
            result = _mul(result, _poly(arg, variables))
        return result
    if op == "neg":
        if len(args) != 1:
            raise ValueError("neg 只接受一个操作数")
        return {key: -value for key, value in _poly(args[0], variables).items()}
    if len(args) != 2 or not isinstance(args[1], int) or isinstance(args[1], bool) or not 0 <= args[1] <= 8:
        raise ValueError("pow 指数须为 0~8 的整数")
    result = {(): Fraction(1)}
    base = _poly(args[0], variables)
    for _ in range(args[1]):
        result = _mul(result, base)
    return result


def _add(a: Polynomial, b: Polynomial) -> Polynomial:
    result = dict(a)
    for key, value in b.items():
        result[key] = result.get(key, Fraction()) + value
    return {key: value for key, value in result.items() if value}


def _mul(a: Polynomial, b: Polynomial) -> Polynomial:
    result: Polynomial = {}
    for ak, av in a.items():
        for bk, bv in b.items():
            powers: dict[str, int] = {}
            for name, power in ak + bk:
                powers[name] = powers.get(name, 0) + power
            key = tuple(sorted((name, power) for name, power in powers.items() if power))
            result[key] = result.get(key, Fraction()) + av * bv
    return {key: value for key, value in result.items() if value}


def _relation_poly(value: object, variables: set[str]) -> Polynomial:
    if not isinstance(value, dict) or set(value) != {"left", "right"}:
        raise ValueError("关系必须包含 left/right")
    return _add(
        _poly(value["left"], variables),
        {key: -coefficient for key, coefficient in _poly(value["right"], variables).items()},
    )


def _equivalent(before: Polynomial, after: Polynomial, *, equation: bool) -> bool:
    if before == after:
        return True
    if not equation or not before or not after:
        return False
    common = next(iter(before.keys() & after.keys()), None)
    if common is None:
        return False
    ratio = after[common] / before[common]
    return ratio != 0 and after == {key: value * ratio for key, value in before.items()}


def _error(kind: str, message: str) -> dict[str, str]:
    return {"type": kind, "message": message}


def _report(errors: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "ok": not errors,
        "severity": "error" if errors else "ok",
        "summary": f"发现 {len(errors)} 个错误" if errors else "符号推导 IR 检查通过",
        "errors": errors,
        "warnings": [],
    }
