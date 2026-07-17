"""Bounded hard-error repair session for the HTML delivery pipeline.

Strategy order is fixed and capped: deterministic → function-model → full-doc model.
This is an explicit state machine, not a LangChain create_agent / open tool loop.
Introduce create_agent only if repair strategies proliferate beyond maintainable hand-written
branches; keep max model attempts aligned with ``aetherviz_max_repair_attempts``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

from aetherviz_service.aetherviz.api.sse import agent_sse_event
from aetherviz_service.aetherviz.contracts.html_compare import normalize_html_for_compare
from aetherviz_service.aetherviz.contracts.layout import assemble_layout_contract
from aetherviz_service.aetherviz.contracts.repair.deterministic import deterministic_can_address
from aetherviz_service.aetherviz.contracts.repair.function import FunctionRepairResult, stream_repair_functions
from aetherviz_service.aetherviz.contracts.repair.model import RepairStreamResult, stream_repair_html
from aetherviz_service.aetherviz.tools.function_patch import (
    repair_function_targets,
    target_functions_from_report,
)
from aetherviz_service.config import settings

CANDIDATE_FATAL_ERROR_TYPES = {
    "js_syntax",
    "missing_runtime_ready",
    "truncated_model_output",
}

REPAIR_STRATEGY_ORDER = (
    "deterministic",
    "function-model",
    "model",
)


class RepairSession:
    """Run a bounded hard-repair pass and yield SSE events."""

    def __init__(
        self,
        *,
        max_model_attempts: int | None = None,
        deterministic_can_address_fn: Callable[[dict[str, Any]], bool] = deterministic_can_address,
        function_repair_stream: Callable[..., Iterator[Any]] = stream_repair_functions,
        model_repair_stream: Callable[..., Iterator[Any]] = stream_repair_html,
    ) -> None:
        configured = settings.aetherviz_max_repair_attempts if max_model_attempts is None else max_model_attempts
        self.max_model_attempts = max(int(configured), 0)
        self._deterministic_can_address = deterministic_can_address_fn
        self._function_repair_stream = function_repair_stream
        self._model_repair_stream = model_repair_stream

    def run(
        self,
        *,
        run_id: str,
        phase: str,
        topic: str,
        plan: dict[str, Any],
        html: str,
        report: dict[str, Any],
        metadata: dict[str, Any],
        started_at: float,
        source_truncated: bool,
        include_plan_in_repair: bool = True,
    ) -> Iterator[str]:
        from aetherviz_service.aetherviz.contracts import pipeline as pipeline_mod

        repaired = False
        if source_truncated:
            metadata["repair_rejection_reason"] = "source_truncated"
            return html, report, False, metadata["degraded"]
        hard_report = pipeline_mod._hard_error_only_report(report)
        deterministic_html = html
        if self._deterministic_can_address(hard_report):
            deterministic_html = pipeline_mod._run_deterministic_repair(html, hard_report, plan)
        if deterministic_html != html:
            previous_html = html
            previous_report = report
            attempt_number = pipeline_mod._next_repair_attempt(metadata)
            yield agent_sse_event(
                "repair.started",
                run_id=run_id,
                phase=phase,
                data={
                    "attempt": attempt_number,
                    "repair_attempt": attempt_number,
                    "strategy": "deterministic",
                    "summary": hard_report.get("summary"),
                },
                metadata=pipeline_mod._metadata(metadata, started_at, stage="repair"),
            )
            assembled_html = assemble_layout_contract(deterministic_html, plan)
            yield agent_sse_event(
                "html.delta",
                run_id=run_id,
                phase=phase,
                data={"delta": "", "bytes": len(assembled_html.encode("utf-8")), "chars": len(assembled_html)},
                metadata=pipeline_mod._metadata(metadata, started_at, stage="repair"),
            )
            candidate_report = pipeline_mod._validate(
                assembled_html,
                truncated=source_truncated,
                plan=plan,
                model_html=deterministic_html,
            )
            accepted, rejection_reason = accept_hard_repair_candidate(
                baseline_report=previous_report,
                candidate_report=candidate_report,
                candidate_truncated=source_truncated,
            )
            if accepted:
                html = deterministic_html
                report = candidate_report
                repaired = True
                yield from pipeline_mod._emit_validation_events(
                    run_id=run_id,
                    phase=phase,
                    report=report,
                    metadata=metadata,
                    started_at=started_at,
                    stage="repair",
                )
            else:
                html = previous_html
                report = previous_report
                yield pipeline_mod._emit_candidate_validation_event(
                    run_id=run_id,
                    phase=phase,
                    report=candidate_report,
                    metadata=metadata,
                    started_at=started_at,
                    rejection_reason=rejection_reason,
                    will_continue=True,
                )
                rollback_html = assemble_layout_contract(html, plan)
                yield agent_sse_event(
                    "html.delta",
                    run_id=run_id,
                    phase=phase,
                    data={"delta": "", "bytes": len(rollback_html.encode("utf-8")), "chars": len(rollback_html)},
                    metadata=pipeline_mod._metadata(metadata, started_at, stage="repair"),
                )
            metadata["validation_warnings"] = [warning["message"] for warning in report.get("warnings", [])]
            yield agent_sse_event(
                "repair.done",
                run_id=run_id,
                phase=phase,
                data={
                    "attempt": attempt_number,
                    "repair_attempt": attempt_number,
                    "strategy": "deterministic",
                    "ok": report["ok"],
                    "accepted": accepted,
                    "rejection_reason": rejection_reason,
                    "summary": report.get("summary"),
                    "bytes": len(assemble_layout_contract(html, plan).encode("utf-8")),
                    "chars": len(assemble_layout_contract(html, plan)),
                },
                metadata=pipeline_mod._metadata(metadata, started_at, stage="repair"),
            )
            if accepted and report["ok"]:
                return html, report, repaired, metadata["degraded"]

        max_attempts = self.max_model_attempts
        if max_attempts and target_functions_from_report(report):
            html, report, function_repaired, function_degraded = yield from self._attempt_function_repair(
                run_id=run_id,
                phase=phase,
                plan=plan,
                html=html,
                report=report,
                metadata=metadata,
                started_at=started_at,
            )
            repaired = repaired or function_repaired
            metadata["degraded"] = metadata["degraded"] or function_degraded
            metadata["validation_warnings"] = [warning["message"] for warning in report.get("warnings", [])]
            if report["ok"]:
                return html, report, repaired, metadata["degraded"]

        for _attempt in range(max_attempts):
            had_prior_repair = repaired
            previous_html = html
            previous_report = report
            previous_degraded = metadata["degraded"]
            previous_truncated = metadata.get("truncated", False)
            attempt_number = pipeline_mod._next_repair_attempt(metadata)
            hard_report = pipeline_mod._hard_error_only_report(report)
            yield agent_sse_event(
                "repair.started",
                run_id=run_id,
                phase=phase,
                data={
                    "attempt": attempt_number,
                    "repair_attempt": attempt_number,
                    "strategy": "model",
                    "summary": hard_report.get("summary"),
                    "errors": hard_report.get("errors", [])[:5],
                },
                metadata=pipeline_mod._metadata(metadata, started_at, stage="repair"),
            )
            repair_degraded = False
            repair_truncated = False
            for item in self._model_repair_stream(
                topic=topic,
                plan=plan,
                raw_html=html,
                report=hard_report,
                include_plan_context=include_plan_in_repair,
            ):
                if isinstance(item, RepairStreamResult):
                    html, repair_degraded = item.html, item.degraded
                    repair_truncated = item.truncated
                    assembled_html = assemble_layout_contract(html, plan)
                    yield agent_sse_event(
                        "html.delta",
                        run_id=run_id,
                        phase=phase,
                        data={
                            "delta": "",
                            "bytes": len(assembled_html.encode("utf-8")),
                            "chars": len(assembled_html),
                        },
                        metadata=pipeline_mod._metadata(metadata, started_at, stage="repair"),
                    )
                    continue
                yield agent_sse_event(
                    "html.delta",
                    run_id=run_id,
                    phase=phase,
                    data=item,
                    metadata=pipeline_mod._metadata(metadata, started_at, stage="repair"),
                )
            candidate_unchanged = normalize_html_for_compare(html) == normalize_html_for_compare(previous_html)
            assembled_html = assemble_layout_contract(html, plan)
            candidate_report = (
                previous_report
                if candidate_unchanged
                else pipeline_mod._validate(assembled_html, truncated=repair_truncated, plan=plan, model_html=html)
            )
            if not candidate_unchanged and not candidate_report["ok"] and not repair_truncated:
                post_hard_report = pipeline_mod._hard_error_only_report(candidate_report)
                post_model_html = html
                if self._deterministic_can_address(post_hard_report):
                    post_model_html = pipeline_mod._run_deterministic_repair(html, post_hard_report, plan)
                if post_model_html != html:
                    html = post_model_html
                    assembled_html = assemble_layout_contract(html, plan)
                    yield agent_sse_event(
                        "html.delta",
                        run_id=run_id,
                        phase=phase,
                        data={
                            "delta": "",
                            "bytes": len(assembled_html.encode("utf-8")),
                            "chars": len(assembled_html),
                        },
                        metadata=pipeline_mod._metadata(metadata, started_at, stage="repair"),
                    )
                    candidate_report = pipeline_mod._validate(
                        assembled_html,
                        truncated=repair_truncated,
                        plan=plan,
                        model_html=html,
                    )
            if candidate_unchanged:
                accepted, rejection_reason = False, "unchanged_candidate"
            else:
                accepted, rejection_reason = accept_hard_repair_candidate(
                    baseline_report=previous_report,
                    candidate_report=candidate_report,
                    candidate_truncated=repair_truncated,
                )
            candidate_error_types = list(error_signature(candidate_report))
            if accepted:
                report = candidate_report
                repaired = True
                metadata["degraded"] = previous_degraded or repair_degraded
                metadata["truncated"] = False
                yield from pipeline_mod._emit_validation_events(
                    run_id=run_id,
                    phase=phase,
                    report=report,
                    metadata=metadata,
                    started_at=started_at,
                    stage="repair",
                )
            else:
                html = previous_html
                report = previous_report
                repaired = had_prior_repair
                metadata["degraded"] = previous_degraded
                metadata["truncated"] = previous_truncated
                metadata["validation_warnings"] = [warning["message"] for warning in report.get("warnings", [])]
                metadata["repair_rejected"] = True
                metadata["repair_rejected_error_types"] = candidate_error_types
                metadata["repair_rejection_reason"] = rejection_reason
                yield pipeline_mod._emit_candidate_validation_event(
                    run_id=run_id,
                    phase=phase,
                    report=candidate_report,
                    metadata=metadata,
                    started_at=started_at,
                    rejection_reason=rejection_reason,
                    will_continue=False,
                )
                rollback_html = assemble_layout_contract(html, plan)
                yield agent_sse_event(
                    "html.delta",
                    run_id=run_id,
                    phase=phase,
                    data={"delta": "", "bytes": len(rollback_html.encode("utf-8")), "chars": len(rollback_html)},
                    metadata=pipeline_mod._metadata(metadata, started_at, stage="repair"),
                )
            metadata["validation_warnings"] = [warning["message"] for warning in report.get("warnings", [])]
            yield agent_sse_event(
                "repair.done",
                run_id=run_id,
                phase=phase,
                data={
                    "attempt": attempt_number,
                    "repair_attempt": attempt_number,
                    "strategy": "model",
                    "ok": report["ok"],
                    "accepted": accepted,
                    "stalled": rejection_reason in {"no_hard_error_reduction", "unchanged_candidate"},
                    "rejection_reason": rejection_reason,
                    "remaining_error_types": candidate_error_types,
                    "summary": report.get("summary"),
                    "bytes": len(assemble_layout_contract(html, plan).encode("utf-8")),
                    "chars": len(assemble_layout_contract(html, plan)),
                    "model_chars": len(html),
                },
                metadata=pipeline_mod._metadata(metadata, started_at, stage="repair"),
            )
            if report["ok"]:
                break
            if not accepted or html == previous_html:
                break
        return html, report, repaired, metadata["degraded"]

    def _attempt_function_repair(
        self,
        *,
        run_id: str,
        phase: str,
        plan: dict[str, Any],
        html: str,
        report: dict[str, Any],
        metadata: dict[str, Any],
        started_at: float,
    ) -> Iterator[str]:
        from aetherviz_service.aetherviz.contracts import pipeline as pipeline_mod

        baseline_html = html
        baseline_report = report
        attempt_number = pipeline_mod._next_repair_attempt(metadata)
        yield agent_sse_event(
            "repair.started",
            run_id=run_id,
            phase=phase,
            data={
                "attempt": attempt_number,
                "repair_attempt": attempt_number,
                "strategy": "function-model",
                "functions": list(repair_function_targets(html, report)),
                "errors": report.get("errors", [])[:5],
            },
            metadata=pipeline_mod._metadata(metadata, started_at, stage="repair"),
        )
        candidate = baseline_html
        applied: tuple[str, ...] = ()
        degraded = False
        patch_errors: tuple[str, ...] = ()
        for item in self._function_repair_stream(
            raw_html=baseline_html,
            report=pipeline_mod._hard_error_only_report(report),
        ):
            if isinstance(item, FunctionRepairResult):
                candidate = item.html
                applied = item.applied
                degraded = item.degraded
                patch_errors = item.errors
                continue
            yield agent_sse_event(
                "html.delta",
                run_id=run_id,
                phase=phase,
                data=item,
                metadata=pipeline_mod._metadata(metadata, started_at, stage="repair"),
            )
        assembled_candidate = assemble_layout_contract(candidate, plan)
        candidate_report = pipeline_mod._validate(assembled_candidate, plan=plan, model_html=candidate)
        accepted, rejection_reason = accept_hard_repair_candidate(
            baseline_report=baseline_report,
            candidate_report=candidate_report,
            candidate_truncated=False,
        )
        accepted = accepted and candidate != baseline_html and bool(applied)
        if not accepted and rejection_reason is None:
            rejection_reason = "no_function_patch_applied"
        if accepted:
            html = candidate
            report = candidate_report
            yield from pipeline_mod._emit_validation_events(
                run_id=run_id,
                phase=phase,
                report=report,
                metadata=metadata,
                started_at=started_at,
                stage="repair",
            )
        else:
            html = baseline_html
            report = baseline_report
            yield pipeline_mod._emit_candidate_validation_event(
                run_id=run_id,
                phase=phase,
                report=candidate_report,
                metadata=metadata,
                started_at=started_at,
                rejection_reason=rejection_reason,
                will_continue=True,
            )
        assembled_result = assemble_layout_contract(html, plan)
        yield agent_sse_event(
            "html.delta",
            run_id=run_id,
            phase=phase,
            data={"delta": "", "bytes": len(assembled_result.encode("utf-8")), "chars": len(assembled_result)},
            metadata=pipeline_mod._metadata(metadata, started_at, stage="repair"),
        )
        yield agent_sse_event(
            "repair.done",
            run_id=run_id,
            phase=phase,
            data={
                "attempt": attempt_number,
                "repair_attempt": attempt_number,
                "strategy": "function-model",
                "ok": report["ok"],
                "accepted": accepted,
                "rejection_reason": rejection_reason,
                "functions": list(applied),
                "patch_errors": list(patch_errors),
                "remaining_error_types": list(error_signature(report)),
                "bytes": len(assembled_result.encode("utf-8")),
                "chars": len(assembled_result),
            },
            metadata=pipeline_mod._metadata(metadata, started_at, stage="repair"),
        )
        return html, report, accepted, degraded if accepted else False


def error_signature(report: dict[str, Any]) -> tuple[str, ...]:
    return tuple(
        sorted(
            str(error.get("type") or error.get("message") or "unknown")
            for error in report.get("errors", [])
            if isinstance(error, dict)
        )
    )


def accept_hard_repair_candidate(
    *,
    baseline_report: dict[str, Any],
    candidate_report: dict[str, Any],
    candidate_truncated: bool,
) -> tuple[bool, str | None]:
    if candidate_truncated:
        return False, "truncated_candidate"
    baseline_errors = set(error_signature(baseline_report))
    candidate_errors = set(error_signature(candidate_report))
    new_fatal_errors = (candidate_errors - baseline_errors) & CANDIDATE_FATAL_ERROR_TYPES
    if new_fatal_errors:
        return False, "new_fatal_errors:" + ",".join(sorted(new_fatal_errors))
    if candidate_report.get("ok"):
        return True, None
    if len(candidate_report.get("errors", [])) < len(baseline_report.get("errors", [])):
        return True, None
    return False, "no_hard_error_reduction"
