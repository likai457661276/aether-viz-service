"""Structured diagnostics for normalized teaching plans."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

DiagnosticSeverity = Literal["error", "warning", "info"]


@dataclass(frozen=True)
class PlanDiagnostic:
    code: str
    severity: DiagnosticSeverity
    field: str
    message: str
    repair_action: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PlanNormalizationResult:
    plan: dict[str, Any]
    diagnostics: tuple[PlanDiagnostic, ...] = ()

    def diagnostics_as_dicts(self) -> list[dict[str, Any]]:
        return [item.as_dict() for item in self.diagnostics]


def add_diagnostic(
    diagnostics: list[PlanDiagnostic] | None,
    *,
    code: str,
    severity: DiagnosticSeverity,
    field: str,
    message: str,
    repair_action: str | None = None,
) -> None:
    if diagnostics is None:
        return
    diagnostic = PlanDiagnostic(
        code=code,
        severity=severity,
        field=field,
        message=message[:240],
        repair_action=repair_action,
    )
    if diagnostic not in diagnostics:
        diagnostics.append(diagnostic)


def check_plan_consistency(plan: dict[str, Any]) -> tuple[PlanDiagnostic, ...]:
    """Validate cross-field references after normalization.

    These checks are deterministic postconditions. Any error means the plan must
    not be approved or sent to IR generation.
    """

    diagnostics: list[PlanDiagnostic] = []
    interactive = plan.get("interactive_spec") if isinstance(plan.get("interactive_spec"), dict) else {}
    variables = {
        str(item.get("name") or "")
        for item in interactive.get("variables", [])
        if isinstance(item, dict) and item.get("name") and not item.get("computed")
    }
    representation = (
        plan.get("representation_spec") if isinstance(plan.get("representation_spec"), dict) else {}
    )
    views = [item for item in representation.get("views", []) if isinstance(item, dict)]
    view_ids = {str(item.get("id") or "") for item in views if item.get("id")}
    states = [item for item in representation.get("state_variables", []) if isinstance(item, dict)]
    state_ids = {str(item.get("id") or "") for item in states if item.get("id")}

    for index, state in enumerate(states):
        identifier = str(state.get("id") or "")
        if identifier and variables and identifier not in variables:
            add_diagnostic(
                diagnostics,
                code="state_variable_reference_missing",
                severity="error",
                field=f"representation_spec.state_variables[{index}].id",
                message=f"状态变量 {identifier} 未引用 interactive_spec.variables.name",
            )

    cross_view_types = {"shared_parameter", "projection"}
    for index, item in enumerate(representation.get("correspondences", [])):
        if not isinstance(item, dict):
            continue
        source = str(item.get("source_view") or "")
        target = str(item.get("target_view") or "")
        parameter = str(item.get("parameter") or "")
        relation = str(item.get("type") or "")
        for name, value in (("source_view", source), ("target_view", target)):
            if value and value not in view_ids:
                add_diagnostic(
                    diagnostics,
                    code="correspondence_view_reference_missing",
                    severity="error",
                    field=f"representation_spec.correspondences[{index}].{name}",
                    message=f"对应关系引用了不存在的视图 {value}",
                )
        if parameter and parameter not in state_ids:
            add_diagnostic(
                diagnostics,
                code="correspondence_parameter_reference_missing",
                severity="error",
                field=f"representation_spec.correspondences[{index}].parameter",
                message=f"对应关系引用了不存在的状态变量 {parameter}",
            )
        if relation in cross_view_types and source and target and source == target:
            add_diagnostic(
                diagnostics,
                code="cross_view_relation_uses_single_view",
                severity="error",
                field=f"representation_spec.correspondences[{index}]",
                message=f"{relation} 必须连接两个不同视图",
            )

    recomposition = plan.get("recomposition_spec")
    if isinstance(recomposition, dict):
        topology = {str(item) for item in recomposition.get("topology_variables", []) if str(item)}
        geometry = {str(item) for item in recomposition.get("geometry_variables", []) if str(item)}
        for kind, names in (("topology_variables", topology), ("geometry_variables", geometry)):
            for name in sorted(names - variables):
                add_diagnostic(
                    diagnostics,
                    code="recomposition_variable_reference_missing",
                    severity="error",
                    field=f"recomposition_spec.{kind}",
                    message=f"重排规格引用了不存在的互动变量 {name}",
                )
        overlap = topology & geometry
        if overlap:
            add_diagnostic(
                diagnostics,
                code="recomposition_variable_role_conflict",
                severity="error",
                field="recomposition_spec",
                message=f"变量同时被声明为拓扑变量和几何变量：{', '.join(sorted(overlap))}",
            )

    return tuple(diagnostics)


def has_consistency_errors(diagnostics: tuple[PlanDiagnostic, ...] | list[PlanDiagnostic]) -> bool:
    return any(item.severity == "error" for item in diagnostics)


def merge_serialized_diagnostics(*groups: object) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for group in groups:
        if not isinstance(group, list):
            continue
        for item in group:
            if not isinstance(item, dict):
                continue
            key = (str(item.get("code") or ""), str(item.get("field") or ""), str(item.get("message") or ""))
            if key in seen:
                continue
            seen.add(key)
            result.append(dict(item))
    return result
