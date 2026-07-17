"""HTML edit workflow."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator
from typing import Any

from bs4 import BeautifulSoup
from langchain_core.messages import HumanMessage, SystemMessage
from langsmith import traceable
from langsmith.run_helpers import get_current_run_tree

from aetherviz_service.aetherviz.agents.model_factory import (
    create_chat_model,
    extract_llm_text,
    extract_llm_usage,
    has_primary_llm_config,
)
from aetherviz_service.aetherviz.api.sse import agent_error_event, agent_sse_event
from aetherviz_service.aetherviz.contracts.html_output import parse_interactive_html, sanitize_aetherviz_html
from aetherviz_service.aetherviz.contracts.html_stream import (
    HTML_SIZE_EVENT_INTERVAL_BYTES,
    HtmlGenerationError,
    HtmlStreamResult,
    build_html_progress_payload,
    build_html_size_payload,
)
from aetherviz_service.aetherviz.contracts.layout import assemble_layout_contract, extract_business_html
from aetherviz_service.aetherviz.contracts.pipeline import run_html_pipeline
from aetherviz_service.aetherviz.contracts.validation.report import build_validation_report
from aetherviz_service.aetherviz.edit.context import build_edit_assembly_plan, build_edit_context_summary
from aetherviz_service.aetherviz.edit.diagnosis import EditDiagnosis, diagnose_edit
from aetherviz_service.aetherviz.edit.intent import (
    IntentCheck,
    build_intent_guard,
    evaluate_edit_intent,
)
from aetherviz_service.aetherviz.edit.prompts import EDIT_HTML_SYSTEM_PROMPT, build_edit_html_prompt
from aetherviz_service.aetherviz.edit.runtime_prepair import (
    combine_candidate_guards,
    try_deterministic_runtime_prepair,
)
from aetherviz_service.aetherviz.limits import (
    FULL_HTML_OUTPUT_RESERVE_CHARS,
    MODEL_HTML_HARD_LIMIT_CHARS,
    estimated_output_capacity_chars,
)
from aetherviz_service.config import settings

logger = logging.getLogger(__name__)

_REQUIRED_WIDGET_ACTIONS = (
    "SET_WIDGET_STATE",
    "HIGHLIGHT_ELEMENT",
    "ANNOTATE_ELEMENT",
    "REVEAL_ELEMENT",
)


def run_edit_html_workflow(
    *,
    run_id: str,
    current_html: str,
    message: str,
    context: dict[str, Any] | None,
    edit_target: dict[str, Any] | None = None,
    runtime_error: dict[str, Any] | None = None,
) -> Iterator[str]:
    tracing_enabled = settings.langsmith_tracing and bool((settings.langsmith_api_key or "").strip())
    runner = _traced_run_edit_html_workflow if tracing_enabled else _run_edit_html_workflow_impl
    if runner is _traced_run_edit_html_workflow:
        yield from runner(
            run_id=run_id,
            current_html=current_html,
            message=message,
            context=context,
            edit_target=edit_target,
            runtime_error=runtime_error,
            langsmith_extra={
                "metadata": {
                    "component": "aetherviz",
                    "phase": "edit_html",
                    "run_id": run_id,
                }
            },
        )
        return
    yield from runner(
        run_id=run_id,
        current_html=current_html,
        message=message,
        context=context,
        edit_target=edit_target,
        runtime_error=runtime_error,
    )


@traceable(
    name="aetherviz.edit_workflow",
    run_type="chain",
    metadata={"component": "aetherviz", "phase": "edit_html"},
    process_inputs=lambda inputs: {
        "run_id": inputs.get("run_id"),
        "assembled_chars": len(inputs.get("current_html") or ""),
        "instruction_chars": len(inputs.get("message") or ""),
    },
    reduce_fn=lambda chunks: _summarize_edit_sse(chunks),
)
def _traced_run_edit_html_workflow(
    *,
    run_id: str,
    current_html: str,
    message: str,
    context: dict[str, Any] | None,
    edit_target: dict[str, Any] | None = None,
    runtime_error: dict[str, Any] | None = None,
) -> Iterator[str]:
    yield from _run_edit_html_workflow_impl(
        run_id=run_id,
        current_html=current_html,
        message=message,
        context=context,
        edit_target=edit_target,
        runtime_error=runtime_error,
    )


def _run_edit_html_workflow_impl(
    *,
    run_id: str,
    current_html: str,
    message: str,
    context: dict[str, Any] | None,
    edit_target: dict[str, Any] | None = None,
    runtime_error: dict[str, Any] | None = None,
) -> Iterator[str]:
    topic = _topic_from_context(context)
    # Edit ignores client plan_summary. Assembly/validation plan comes from current HTML.
    business_html = extract_business_html(current_html)
    plan = build_edit_assembly_plan(business_html, topic)
    deterministic_pre_repair_result = try_deterministic_runtime_prepair(business_html, runtime_error)
    prepair_guard = None
    deterministic_pre_repair: dict[str, Any] = {}
    if deterministic_pre_repair_result is not None:
        business_html = deterministic_pre_repair_result.html
        prepair_guard = deterministic_pre_repair_result.guard
        deterministic_pre_repair = {
            "applied": list(deterministic_pre_repair_result.applied),
            "purpose": "修复已证明的运行时契约错误；仍需执行完整用户编辑任务",
        }
    report_html = assemble_layout_contract(business_html, plan) if deterministic_pre_repair else current_html
    current_report = build_validation_report(report_html, plan=plan, model_html=business_html)
    context_summary = build_edit_context_summary(
        instruction=message,
        business_html=business_html,
        context=context,
        validation_report=current_report,
        edit_target=edit_target,
        runtime_error=runtime_error,
        deterministic_pre_repair=deterministic_pre_repair,
    )
    yield agent_sse_event(
        "html.edit_started",
        run_id=run_id,
        phase="edit_html",
        data={
            "message": "正在分析修改目标与动画影响范围",
            "reasoning_enabled": False,
        },
    )
    diagnosis = diagnose_edit(
        instruction=message,
        business_html=business_html,
        context_summary=context_summary,
    )
    yield agent_sse_event(
        "html.edit_diagnosed",
        run_id=run_id,
        phase="edit_html",
        data=diagnosis.public_dict(),
        metadata={"degraded": diagnosis.degraded},
    )
    if diagnosis.strategy == "clarification_required":
        yield agent_error_event(
            run_id=run_id,
            phase="edit_html",
            code="edit_clarification_required",
            message=diagnosis.clarification_question or "需要更具体的修改目标后才能安全编辑",
            detail=diagnosis.problem,
        )
        return

    intent_guard = build_intent_guard(
        baseline_html=business_html,
        change_checks=diagnosis.change_checks,
        preserve_checks=diagnosis.preserve_checks,
    )
    candidate_guard = combine_candidate_guards(prepair_guard, intent_guard)
    yield from run_html_pipeline(
        run_id=run_id,
        phase="edit_html",
        start_event="html.edit_started",
        topic=topic,
        plan=plan,
        html_stream_factory=lambda: _stream_diagnosed_edit(
            topic=topic,
            message=message,
            current_html=business_html,
            diagnosis=diagnosis,
            context_summary=context_summary,
        ),
        emit_start_event=False,
        candidate_guard=candidate_guard,
        include_plan_in_repair=False,
        reasoning_enabled=settings.aetherviz_edit_enable_thinking,
        initial_metadata={
            "edit_diagnosis_strategy": diagnosis.strategy,
            "edit_diagnosis_confidence": diagnosis.confidence,
            "edit_diagnosis_degraded": diagnosis.degraded,
            "intent_check_count": len(diagnosis.change_checks) + len(diagnosis.preserve_checks),
        },
    )


def _stream_diagnosed_edit(
    *,
    topic: str,
    message: str,
    current_html: str,
    diagnosis: EditDiagnosis,
    context_summary: dict[str, Any],
) -> Iterator[dict[str, Any] | HtmlStreamResult]:
    yield from _stream_full_html_edit(
        topic=topic,
        message=_diagnosed_regeneration_message(message, diagnosis, context_summary),
        current_html=current_html,
        diagnosis=diagnosis,
    )


def _diagnosed_regeneration_message(
    message: str,
    diagnosis: EditDiagnosis,
    context_summary: dict[str, Any],
) -> str:
    targets = [
        str(item.get("selector") or item.get("function") or "")
        for item in diagnosis.targets
        if item.get("selector") or item.get("function")
    ]
    evidence = {
        "compiled_task": {
            "resolved_instruction": diagnosis.resolved_instruction or message,
            "change_requirements": list(diagnosis.change_requirements),
            "preserve_requirements": list(diagnosis.preserve_requirements),
            "impact_areas": list(diagnosis.impact_areas),
            "acceptance_criteria": list(diagnosis.acceptance_criteria),
            "problem": diagnosis.problem,
            "scope": diagnosis.scope,
            "targets": targets,
            "change_checks": [check.public_dict() for check in diagnosis.change_checks],
            "preserve_checks": [check.public_dict() for check in diagnosis.preserve_checks],
        },
        "edit_target": context_summary.get("edit_target") or {},
        "runtime_error": context_summary.get("runtime_error") or {},
        "validation": context_summary.get("validation") or {},
        "deterministic_pre_repair": context_summary.get("deterministic_pre_repair") or {},
    }
    return (
        f"原始用户输入（用于核对，不得覆盖已编译任务）：{message}\n\n"
        f"已编译编辑任务（主要执行指令）：{diagnosis.resolved_instruction or message}\n\n"
        "结构化编辑上下文："
        f"{json.dumps(evidence, ensure_ascii=False, separators=(',', ':'))}\n"
        "目标和证据可能不完整，必须结合完整 HTML 独立复核，不要把 selector 或函数名当作修改边界。"
        "输出必须使全部 hard change_checks 为真，且不破坏 hard preserve_checks。"
        "为满足全部变更要求和验收标准，可以联动修改相关 DOM、CSS、"
        "SVG/Canvas、状态推导、渲染函数、事件绑定和动画控制器。"
    )


_RETRYABLE_EDIT_CODES = {
    "edit_intent_not_satisfied",
    "edit_truncated",
    "edit_contract_changed",
}


def _stream_full_html_edit(
    *,
    topic: str,
    message: str,
    current_html: str,
    diagnosis: EditDiagnosis | None = None,
) -> Iterator[dict[str, Any] | HtmlStreamResult]:
    retry_message = message
    attempts = max(settings.aetherviz_edit_max_retries, 0) + 1
    active_diagnosis = diagnosis or _default_intent_diagnosis()
    for attempt in range(attempts):
        try:
            yield from _stream_edit_html(
                topic=topic,
                message=retry_message,
                current_html=current_html,
                diagnosis=active_diagnosis,
            )
            return
        except HtmlGenerationError as exc:
            if attempt + 1 >= attempts or exc.code not in _RETRYABLE_EDIT_CODES:
                raise
            progress_label = (
                "意图验收未通过，正在按失败项重试"
                if exc.code == "edit_intent_not_satisfied"
                else "重新审查完整动画链路并生成"
            )
            yield build_html_progress_payload(
                [
                    {"content": "首轮编辑未形成有效结果", "status": "completed"},
                    {"content": progress_label, "status": "in_progress"},
                ]
            )
            evidence = exc.detail or f"{exc.code}"
            retry_message = (
                f"{message}\n\n上一轮完整编辑未被接受：{exc.code} / {evidence}\n"
                "请重新从当前 HTML 开始，不要复用上一轮输出。先在内部检查用户要求会影响的 DOM、样式、"
                "状态、derive/render、事件与动画时间源，再输出确实满足 hard change_checks、"
                "保持 hard preserve_checks 与核心 Widget 契约的完整 HTML。"
            )


def _default_intent_diagnosis() -> EditDiagnosis:
    return EditDiagnosis(
        intent="edit_html",
        scope="business_html",
        strategy="full_html_regeneration",
        problem="根据用户意见修改当前 HTML",
        confidence=0.5,
        change_checks=(
            IntentCheck(
                id="default_html_must_differ",
                kind="html_must_differ",
                severity="hard",
                baseline_binding="must_differ",
                rationale="候选相对当前 HTML 必须变化",
                group="change",
            ),
        ),
        preserve_checks=(
            IntentCheck(
                id="default_widget_type",
                kind="widget_type_unchanged",
                severity="hard",
                baseline_binding="must_match",
                rationale="保持 widget-config.type",
                group="preserve",
            ),
            IntentCheck(
                id="default_iframe_actions",
                kind="iframe_actions_unchanged",
                severity="hard",
                baseline_binding="must_match",
                rationale="保持核心 iframe actions",
                group="preserve",
            ),
        ),
    )


def _stream_edit_html(
    *,
    topic: str,
    message: str,
    current_html: str,
    diagnosis: EditDiagnosis | None = None,
) -> Iterator[dict[str, Any] | HtmlStreamResult]:
    runner = (
        _traced_stream_edit_html
        if settings.langsmith_tracing and get_current_run_tree() is not None
        else _stream_edit_html_impl
    )
    yield from runner(
        topic=topic,
        message=message,
        current_html=current_html,
        diagnosis=diagnosis,
    )


@traceable(
    name="aetherviz.html_edit",
    run_type="chain",
    metadata={"component": "aetherviz", "stage": "html_edit"},
    process_inputs=lambda inputs: {
        "topic": inputs.get("topic"),
        "business_chars": len(inputs.get("current_html") or ""),
        "instruction_chars": len(inputs.get("message") or ""),
        "full_output_budget_chars": estimated_output_capacity_chars(settings.aetherviz_edit_max_tokens),
        "edit_strategy": "full_html_regeneration",
        "reasoning_enabled": settings.aetherviz_edit_enable_thinking,
        "reasoning_effort": settings.aetherviz_edit_reasoning_effort,
    },
    reduce_fn=lambda items: _summarize_edit_stream(items),
)
def _traced_stream_edit_html(
    *,
    topic: str,
    message: str,
    current_html: str,
    diagnosis: EditDiagnosis | None = None,
) -> Iterator[dict[str, Any] | HtmlStreamResult]:
    yield from _stream_edit_html_impl(
        topic=topic,
        message=message,
        current_html=current_html,
        diagnosis=diagnosis,
    )


def _stream_edit_html_impl(
    *,
    topic: str,
    message: str,
    current_html: str,
    diagnosis: EditDiagnosis | None = None,
) -> Iterator[dict[str, Any] | HtmlStreamResult]:
    active_diagnosis = diagnosis or _default_intent_diagnosis()
    if not has_primary_llm_config():
        raise HtmlGenerationError(
            "HTML 修改失败，未配置可用的模型服务，原页面已保留",
            code="model_unavailable",
            detail="OPENAI_API_KEY is not configured",
        )

    if not _has_full_edit_budget(current_html):
        raise HtmlGenerationError(
            "HTML 修改失败，完整编辑输出预算不足，原页面已保留",
            code="edit_budget_exceeded",
            detail=f"business_chars={len(current_html)}",
        )

    prompt = build_edit_html_prompt(
        instruction=message,
        current_html=current_html,
    )
    raw_text = ""
    last_size_event_bytes = 0
    timed_out = False
    finish_reason: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    deadline = time.monotonic() + max(settings.aetherviz_html_timeout_seconds, 1)
    yield build_html_progress_payload(
        [
            {"content": "分析当前 HTML 与修改意见", "status": "in_progress"},
            {"content": "重新生成完整 HTML", "status": "pending"},
        ]
    )
    try:
        model = create_chat_model("edit")
        messages = [SystemMessage(content=EDIT_HTML_SYSTEM_PROMPT), HumanMessage(content=prompt)]
        output_started = False
        for chunk in model.stream(messages):
            chunk_input_tokens, chunk_output_tokens = extract_llm_usage(chunk)
            input_tokens = chunk_input_tokens or input_tokens
            output_tokens = chunk_output_tokens or output_tokens
            if time.monotonic() > deadline:
                timed_out = True
                logger.warning(
                    "edit_html model timed out after %ss; using best available output",
                    settings.aetherviz_html_timeout_seconds,
                )
                break
            text = extract_llm_text(chunk)
            response_metadata = getattr(chunk, "response_metadata", None)
            if isinstance(response_metadata, dict) and response_metadata.get("finish_reason"):
                finish_reason = str(response_metadata["finish_reason"])
            if text:
                raw_text += text
                current_bytes = len(raw_text.encode("utf-8"))
                if not output_started:
                    output_started = True
                    yield build_html_progress_payload(
                        [
                            {"content": "分析当前 HTML 与修改意见", "status": "completed"},
                            {"content": "重新生成完整 HTML", "status": "in_progress"},
                        ],
                        html_content=raw_text,
                    )
                    last_size_event_bytes = current_bytes
                elif current_bytes - last_size_event_bytes >= HTML_SIZE_EVENT_INTERVAL_BYTES:
                    yield build_html_size_payload(raw_text)
                    last_size_event_bytes = current_bytes
        if not raw_text.strip():
            raise ValueError("edit model returned empty content")
        if timed_out:
            raise HtmlGenerationError(
                "HTML 修改失败，模型响应超时，原页面已保留",
                code="edit_timeout",
                detail=f"chars={len(raw_text)}",
            )
        truncated = "</html" not in raw_text.lower() or finish_reason in {"length", "max_tokens"}
        if truncated:
            raise HtmlGenerationError(
                "HTML 修改失败，模型输出被截断，原页面已保留",
                code="edit_truncated",
                detail=f"finish_reason={finish_reason or 'missing_html_end'}; chars={len(raw_text)}",
            )
        edited_html = sanitize_aetherviz_html(parse_interactive_html(raw_text))
        contract_errors = _edit_contract_errors(current_html, edited_html)
        if contract_errors:
            raise HtmlGenerationError(
                "HTML 修改失败，重生成结果破坏了原页面核心契约，原页面已保留",
                code="edit_contract_changed",
                detail="; ".join(contract_errors),
            )
        intent = evaluate_edit_intent(
            baseline_html=current_html,
            candidate_html=edited_html,
            change_checks=active_diagnosis.change_checks,
            preserve_checks=active_diagnosis.preserve_checks,
        )
        if not intent.ok:
            raise HtmlGenerationError(
                "HTML 修改结果未满足本次编辑验收条件，原页面已保留",
                code="edit_intent_not_satisfied",
                detail=intent.retry_evidence(),
            )
        yield build_html_progress_payload(
            [
                {"content": "分析当前 HTML 与修改意见", "status": "completed"},
                {"content": "重新生成完整 HTML", "status": "completed"},
            ],
            html_content=edited_html,
        )
        yield HtmlStreamResult(
            html=edited_html,
            degraded=timed_out,
            truncated=False,
            strategy="full_html_regeneration",
            finish_reason=finish_reason,
            source_chars=len(current_html),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            output_chars=len(raw_text),
            intent_passed=True,
            intent_soft_failed=tuple(f"{item.check.id}:{item.message}" for item in intent.soft_failed),
            intent_check_count=len(intent.passed) + len(intent.failed) + len(intent.soft_failed),
            intent_summary=intent.summary,
        )
    except GeneratorExit:
        raise
    except HtmlGenerationError:
        raise
    except Exception as exc:
        logger.warning("edit_html model failed: %s", exc)
        raise HtmlGenerationError(
            "HTML 修改失败，未获得可用页面",
            code="edit_failed",
            detail=str(exc),
        ) from exc


def _has_full_edit_budget(current_html: str) -> bool:
    estimated_capacity = estimated_output_capacity_chars(settings.aetherviz_edit_max_tokens)
    return (
        len(current_html) <= MODEL_HTML_HARD_LIMIT_CHARS
        and len(current_html) + FULL_HTML_OUTPUT_RESERVE_CHARS <= estimated_capacity
    )


def _edit_contract_errors(source_html: str, candidate_html: str) -> list[str]:
    errors: list[str] = []
    source_type = _widget_type(source_html)
    candidate_type = _widget_type(candidate_html)
    if source_type and candidate_type != source_type:
        errors.append(f"widget_type_changed:{source_type}->{candidate_type or 'missing'}")

    missing_actions = [
        action for action in _REQUIRED_WIDGET_ACTIONS if action in source_html and action not in candidate_html
    ]
    if missing_actions:
        errors.append(f"widget_actions_missing:{','.join(missing_actions)}")
    return errors


def _widget_type(html: str) -> str | None:
    config = BeautifulSoup(html or "", "html.parser").find("script", id="widget-config")
    if config is None:
        return None
    try:
        payload = json.loads(config.get_text())
    except (TypeError, ValueError):
        return None
    value = payload.get("type") if isinstance(payload, dict) else None
    return str(value) if value else None


def _summarize_edit_stream(items: list[dict[str, Any] | HtmlStreamResult]) -> dict[str, Any]:
    result = next((item for item in reversed(items) if isinstance(item, HtmlStreamResult)), None)
    if result is None:
        return {"completed": False}
    return {
        "completed": True,
        "accepted": True,
        "rolled_back": False,
        "strategy": result.strategy,
        "source_chars": result.source_chars,
        "result_chars": len(result.html),
        "finish_reason": result.finish_reason,
        "truncated": result.truncated,
        "patch_functions": list(result.patch_functions),
        "patch_blocks": list(result.patch_blocks),
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "output_chars": result.output_chars or len(result.html),
        "intent_passed": result.intent_passed,
        "intent_soft_failed": list(result.intent_soft_failed),
        "intent_check_count": result.intent_check_count,
        "intent_summary": result.intent_summary,
        "chars_per_output_token": (
            round((result.output_chars or len(result.html)) / result.output_tokens, 3) if result.output_tokens else None
        ),
    }


def _summarize_edit_sse(chunks: list[str]) -> dict[str, Any]:
    events = [line[7:] for chunk in chunks for line in chunk.splitlines() if line.startswith("event: ")]
    return {"event_count": len(events), "events": events, "completed": "html.done" in events}


def _topic_from_context(context: dict[str, Any] | None) -> str:
    if not isinstance(context, dict):
        return "AI教学动画"
    return str(context.get("topic") or context.get("user_message") or "AI教学动画")
