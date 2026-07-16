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

from aetherviz_service.aetherviz.agents.edit_diagnosis_agent import EditDiagnosis, diagnose_edit
from aetherviz_service.aetherviz.agents.html_agent import (
    HTML_SIZE_EVENT_INTERVAL_BYTES,
    HtmlGenerationError,
    HtmlStreamResult,
    build_html_progress_payload,
    build_html_size_payload,
)
from aetherviz_service.aetherviz.agents.instructions import EDIT_HTML_SYSTEM_PROMPT, build_edit_html_prompt
from aetherviz_service.aetherviz.agents.model_factory import (
    create_chat_model,
    extract_llm_text,
    extract_llm_usage,
    has_primary_llm_config,
)
from aetherviz_service.aetherviz.api.sse import agent_error_event, agent_sse_event
from aetherviz_service.aetherviz.limits import (
    FULL_HTML_OUTPUT_RESERVE_CHARS,
    MODEL_HTML_HARD_LIMIT_CHARS,
    estimated_output_capacity_chars,
)
from aetherviz_service.aetherviz.tools.dom_api_contract import (
    find_dom_element_selector_mismatches,
    repair_dom_element_selector_mismatches,
)
from aetherviz_service.aetherviz.tools.edit_context import build_edit_context_summary, is_server_layout_request
from aetherviz_service.aetherviz.tools.edit_operations import (
    EditOperationResult,
)
from aetherviz_service.aetherviz.tools.function_patch import extract_named_functions
from aetherviz_service.aetherviz.tools.html_compare import normalize_html_for_compare
from aetherviz_service.aetherviz.tools.html_output import parse_interactive_html, sanitize_aetherviz_html
from aetherviz_service.aetherviz.tools.layout_contract import assemble_layout_contract, extract_business_html
from aetherviz_service.aetherviz.tools.validation_report import build_validation_report
from aetherviz_service.aetherviz.workflow.html_pipeline import run_html_pipeline
from aetherviz_service.aetherviz.workflow.plan_contract import normalize_plan
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
    plan = normalize_plan((context or {}).get("plan_summary") if isinstance(context, dict) else None, topic)
    business_html = extract_business_html(current_html)
    deterministic_runtime_edit = _deterministic_runtime_edit(business_html, runtime_error)
    candidate_guard = None
    deterministic_pre_repair: dict[str, Any] = {}
    if deterministic_runtime_edit is not None:
        _, deterministic_result = deterministic_runtime_edit
        business_html = deterministic_result.html
        candidate_guard = deterministic_result.guard
        deterministic_pre_repair = {
            "applied": list(deterministic_result.applied),
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
    if diagnosis.strategy == "server_owned_rejected":
        yield agent_error_event(
            run_id=run_id,
            phase="edit_html",
            code="edit_server_layout_owned",
            message="该修改涉及系统统一管理的页面外壳，当前课件不能单独修改这部分内容",
            detail=diagnosis.problem,
        )
        return
    if diagnosis.strategy == "clarification_required":
        yield agent_error_event(
            run_id=run_id,
            phase="edit_html",
            code="edit_clarification_required",
            message=diagnosis.clarification_question or "需要更具体的修改目标后才能安全编辑",
            detail=diagnosis.problem,
        )
        return

    # 模型编译出的需求用于驱动重生成，但不作为函数哈希或精确 CSS 门禁；只有
    # 服务端能证明的运行时契约错误在编辑前后保持硬验收。
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
        initial_metadata={
            "edit_diagnosis_strategy": diagnosis.strategy,
            "edit_diagnosis_confidence": diagnosis.confidence,
            "edit_diagnosis_degraded": diagnosis.degraded,
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
        "为满足全部变更要求和验收标准，可以联动修改相关 DOM、CSS、"
        "SVG/Canvas、状态推导、渲染函数、事件绑定和动画控制器。"
    )


_RETRYABLE_EDIT_CODES = {"edit_no_change", "edit_truncated", "edit_contract_changed"}


def _stream_full_html_edit(
    *,
    topic: str,
    message: str,
    current_html: str,
) -> Iterator[dict[str, Any] | HtmlStreamResult]:
    retry_message = message
    attempts = max(settings.aetherviz_edit_max_retries, 0) + 1
    for attempt in range(attempts):
        try:
            yield from _stream_edit_html(
                topic=topic,
                message=retry_message,
                current_html=current_html,
            )
            return
        except HtmlGenerationError as exc:
            if attempt + 1 >= attempts or exc.code not in _RETRYABLE_EDIT_CODES:
                raise
            yield build_html_progress_payload(
                [
                    {"content": "首轮编辑未形成有效结果", "status": "completed"},
                    {"content": "重新审查完整动画链路并生成", "status": "in_progress"},
                ]
            )
            retry_message = (
                f"{message}\n\n上一轮完整编辑未被接受：{exc.code} / {exc.detail}。"
                "请重新从当前 HTML 开始，不要复用上一轮输出。先在内部检查用户要求会影响的 DOM、样式、"
                "状态、derive/render、事件与动画时间源，再输出确实产生可观察变化且保持核心 Widget 契约的完整 HTML。"
            )


def _deterministic_runtime_edit(
    business_html: str,
    runtime_error: dict[str, Any] | None,
) -> tuple[EditDiagnosis, EditOperationResult] | None:
    error_text = " ".join(str(value) for value in (runtime_error or {}).values()).lower()
    if not ("queryselector" in error_text and "not a valid selector" in error_text and "[object html" in error_text):
        return None
    repaired, applied = repair_dom_element_selector_mismatches(business_html)
    if not applied or repaired == business_html:
        return None
    functions = extract_named_functions(business_html)
    targets = tuple(
        {
            "kind": "function",
            "selector": name,
            "function": name,
            "source_hash": functions[name][0].source_hash,
            "evidence": "deterministic DOM API argument contract",
            "confidence": 1.0,
        }
        for name in applied
        if len(functions.get(name, [])) == 1
    )
    diagnosis = EditDiagnosis(
        intent="fix_runtime_error",
        scope="function_repair",
        strategy="function_repair",
        problem="DOM 元素被错误地作为 querySelector 的 CSS 选择器参数",
        confidence=1.0,
        targets=targets,
        assertions=(
            {
                "type": "runtime_error_absent",
                "selector": "",
                "property": "querySelector",
                "expected": "querySelector 不再接收 DOM 元素",
            },
        ),
        allowed_scope=("function_repair",),
    )

    def guard(candidate: str) -> list[str]:
        return (
            ["edit_runtime_error_still_present:dom_element_used_as_selector"]
            if find_dom_element_selector_mismatches(candidate)
            else []
        )

    result = EditOperationResult(
        html=repaired,
        applied=tuple(f"function:{name}" for name in applied),
        guard=guard,
        strategy="function_patch",
    )
    return diagnosis, result


def _stream_edit_html(
    *,
    topic: str,
    message: str,
    current_html: str,
) -> Iterator[dict[str, Any] | HtmlStreamResult]:
    runner = (
        _traced_stream_edit_html
        if settings.langsmith_tracing and get_current_run_tree() is not None
        else _stream_edit_html_impl
    )
    yield from runner(topic=topic, message=message, current_html=current_html)


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
) -> Iterator[dict[str, Any] | HtmlStreamResult]:
    yield from _stream_edit_html_impl(
        topic=topic,
        message=message,
        current_html=current_html,
    )


def _stream_edit_html_impl(
    *,
    topic: str,
    message: str,
    current_html: str,
) -> Iterator[dict[str, Any] | HtmlStreamResult]:
    if _targets_server_layout(message):
        raise HtmlGenerationError(
            "该修改涉及系统统一管理的页面外壳，当前课件不能单独修改这部分内容",
            code="edit_server_layout_owned",
            detail="server-owned layout change rejected before model invocation",
        )

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
        if normalize_html_for_compare(current_html) == normalize_html_for_compare(edited_html):
            raise HtmlGenerationError(
                "HTML 修改失败，模型未产生实际变化，原页面已保留",
                code="edit_no_change",
                detail="candidate_unchanged",
            )
        contract_errors = _edit_contract_errors(current_html, edited_html)
        if contract_errors:
            raise HtmlGenerationError(
                "HTML 修改失败，重生成结果破坏了原页面核心契约，原页面已保留",
                code="edit_contract_changed",
                detail="; ".join(contract_errors),
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


def _targets_server_layout(message: str) -> bool:
    """Detect explicit requests to mutate layout owned by the server shell."""
    return is_server_layout_request(message)


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
