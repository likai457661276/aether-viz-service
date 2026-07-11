"""Cheap, non-blocking alignment checks between a plan and generated HTML."""

from __future__ import annotations

from typing import Any

from bs4 import BeautifulSoup


def check_discipline_consistency(
    html: str,
    *,
    plan: dict[str, Any] | None = None,
    soup: BeautifulSoup | None = None,
) -> dict[str, Any]:
    warnings: list[dict[str, Any]] = []
    if not isinstance(plan, dict) or not plan:
        return _report(warnings)
    parsed = soup or BeautifulSoup(html or "", "html.parser")
    profile = plan.get("knowledge_profile") if isinstance(plan.get("knowledge_profile"), dict) else {}
    discipline_spec = plan.get("discipline_spec") if isinstance(plan.get("discipline_spec"), dict) else {}
    representation = str(profile.get("representation_type") or "")

    if not any(discipline_spec.get(field) for field in ("entities", "relations", "invariants", "boundary_cases", "representations")):
        warnings.append(_warning("missing_discipline_spec", "计划缺少通用学科语义规格，生成结果难以进行语义对齐检查"))

    if representation in {"coordinate_graph", "geometric_construction"} and parsed.find("svg") is None:
        warnings.append(_warning("representation_mismatch", f"计划要求 {representation} 表征，但主页面未检测到 SVG 几何/坐标画布"))
    if representation == "data_chart" and parsed.find(["svg", "canvas"]) is None:
        warnings.append(_warning("representation_mismatch", "计划要求数据图表表征，但未检测到 SVG 或 Canvas"))
    if representation == "symbolic_derivation" and parsed.select_one('[data-region="formula"]') is None:
        warnings.append(_warning("missing_symbolic_region", "计划要求符号推导表征，但未检测到独立公式/推导区域"))
    if representation in {"process_model", "relation_network"}:
        spec = plan.get("interactive_spec") if isinstance(plan.get("interactive_spec"), dict) else {}
        if plan.get("interactive_type") == "diagram" and (not spec.get("nodes") or not spec.get("edges")):
            warnings.append(_warning("incomplete_relation_spec", "关系/过程表征缺少可校验的节点或关系定义"))

    boundary_cases = discipline_spec.get("boundary_cases") if isinstance(discipline_spec, dict) else []
    interactive_spec = plan.get("interactive_spec") if isinstance(plan.get("interactive_spec"), dict) else {}
    if boundary_cases and plan.get("interactive_type") == "simulation" and not interactive_spec.get("presets"):
        warnings.append(_warning("missing_boundary_preset", "计划声明了边界/特殊状态，但 simulation 未提供可到达的 preset"))
    return _report(warnings)


def _warning(kind: str, message: str) -> dict[str, Any]:
    return {"type": kind, "message": message, "line": None}


def _report(warnings: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "ok": True,
        "severity": "warning" if warnings else "info",
        "summary": f"发现 {len(warnings)} 个学科语义对齐风险" if warnings else "学科语义对齐检查通过",
        "errors": [],
        "warnings": warnings,
    }
