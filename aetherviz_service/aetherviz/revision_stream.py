"""SSE stream for local AetherViz HTML revision."""

from __future__ import annotations

from collections.abc import Iterator

from aetherviz_service.aetherviz.constants import HTML_OUTPUT_MAX_TOKENS
from aetherviz_service.aetherviz.fallback_planner import normalize_plan
from aetherviz_service.aetherviz.fallback_validator import AetherVizInteractiveHtmlError
from aetherviz_service.aetherviz.html_output import parse_and_validate_html
from aetherviz_service.aetherviz.prompts import REPAIR_SYSTEM_PROMPT, REVISE_SYSTEM_PROMPT, system_prompt_for_plan
from aetherviz_service.aetherviz.revision import (
    AetherVizRevisionError,
    analyze_revision,
    apply_revision_patch,
    build_adjusted_plan_fallback_prompt,
    build_revision_index,
    build_revision_patch_prompt,
    build_revision_patch_repair_prompt,
    parse_revision_patch,
    summarize_revision_index,
    validate_revised_html,
)
from aetherviz_service.aetherviz.schemas.aetherviz import GenerateAetherVizHtmlMetadata
from aetherviz_service.aetherviz.sse import progress_event, sse_event
from aetherviz_service.aetherviz.streaming import LLMStreamCallable, estimate_output_tokens, stream_llm_output
from aetherviz_service.aetherviz.validator import AetherVizHtmlValidationError


def revise_html_stream(
    topic: str,
    current_html: str,
    instruction: str,
    *,
    context: dict | None = None,
    llm_stream: LLMStreamCallable,
) -> Iterator[str]:
    yield sse_event(
        "revise_analyzing",
        {
            "success": True,
            "stage": "revise_analyzing",
            "message": "正在分析 HTML 结构和修改意图",
            "progress": 20,
            "phase": "revise",
        },
    )
    provided_index = extract_revision_index_from_context(context)
    analysis = analyze_revision(current_html, instruction, provided_index)
    plan = plan_from_context_or_default(context, topic)

    yield sse_event(
        "revise_locating",
        {
            "success": True,
            "stage": "revise_locating",
            "message": f"已定位 {len(analysis.targets)} 个候选修改区域",
            "progress": 32,
            "phase": "revise",
            "revision_intent": analysis.intent,
            "index_status": analysis.index_status,
            "targets": [
                {
                    "kind": target.get("kind"),
                    "type": target.get("type"),
                    "selector": target.get("selector"),
                    "summary": target.get("summary"),
                }
                for target in analysis.targets[:6]
            ],
        },
    )

    prompt = build_revision_patch_prompt(
        topic=topic,
        instruction=instruction,
        analysis=analysis,
        context=context,
    )
    yield sse_event(
        "revise_patching",
        {
            "success": True,
            "stage": "revise_patching",
            "message": "正在生成局部修改补丁",
            "progress": 46,
            "phase": "revise",
        },
    )
    raw_patch = yield from stream_llm_output(
        prompt,
        system_prompt=REVISE_SYSTEM_PROMPT,
        max_tokens=HTML_OUTPUT_MAX_TOKENS,
        temperature=0.12,
        stage="html_revising",
        phase="revise",
        message_prefix="正在生成局部修改补丁",
        progress_start=48,
        progress_end=74,
        llm_stream=llm_stream,
    )
    output_tokens_total = estimate_output_tokens(raw_patch)

    yield sse_event(
        "revise_merging",
        {
            "success": True,
            "stage": "revise_merging",
            "message": "正在合并局部补丁并校验 HTML",
            "progress": 78,
            "phase": "revise",
        },
    )
    html_output, warnings, attempts, repaired = yield from apply_patch_validate_or_repair_stream(
        raw_patch,
        topic=topic,
        instruction=instruction,
        analysis=analysis,
        context=context,
        plan=plan,
        llm_stream=llm_stream,
    )
    metadata = GenerateAetherVizHtmlMetadata(
        topic=topic,
        attempts=attempts,
        repaired=repaired,
        source="llm_svg_revision",
        degraded=True,
        validation_warnings=warnings,
        render_mode=plan["mode"],
        subject=plan["subject"],
        plan=plan,
    )
    yield sse_event(
        "done",
        {
            "success": True,
            "stage": "done",
            "message": f"页面已完成修订，共输出约 {output_tokens_total} Token",
            "progress": 100,
            "phase": "revise",
            "mode": plan["mode"],
            "html": html_output,
            "output_tokens_total": output_tokens_total,
            "metadata": metadata.model_dump(),
            "revision_index": build_revision_index(html_output),
        },
    )


def extract_revision_index_from_context(context: dict | None) -> dict | None:
    if not isinstance(context, dict):
        return None
    revision_index = context.get("revision_index")
    if isinstance(revision_index, dict):
        return revision_index
    selected_file = context.get("selected_file")
    if isinstance(selected_file, dict) and isinstance(selected_file.get("revision_index"), dict):
        return selected_file["revision_index"]
    return None


def plan_from_context_or_default(context: dict | None, topic: str) -> dict:
    if isinstance(context, dict) and isinstance(context.get("plan_summary"), dict):
        return normalize_plan(context["plan_summary"], topic)
    return normalize_plan({}, topic)


def apply_revision_patch_once(
    raw_patch: str,
    *,
    topic: str,
    analysis,
) -> tuple[str, list[str]]:
    patch_payload = parse_revision_patch(raw_patch)
    merged_html = apply_revision_patch(analysis.normalized_html, patch_payload)
    return validate_revised_html(merged_html, original_html=analysis.normalized_html, topic=topic)


def apply_patch_validate_or_repair_stream(
    raw_patch: str,
    *,
    topic: str,
    instruction: str,
    analysis,
    context: dict | None,
    plan: dict,
    llm_stream: LLMStreamCallable,
) -> Iterator[tuple[str, list[str], int, bool]]:
    try:
        html_output, warnings = apply_revision_patch_once(raw_patch, topic=topic, analysis=analysis)
        return html_output, warnings, 1, False
    except (AetherVizRevisionError, AetherVizHtmlValidationError) as first_exc:
        first_error = str(first_exc)
        yield progress_event(
            "repairing",
            "局部补丁未通过合并校验，正在自动修复一次",
            84,
            phase="revise",
            mode=plan.get("mode"),
            subject=plan.get("subject"),
            detail=first_error,
        )
        repair_prompt = build_revision_patch_repair_prompt(
            topic=topic,
            instruction=instruction,
            analysis=analysis,
            failed_patch=raw_patch,
            error_detail=first_error,
            context=context,
        )
        repaired_patch = yield from stream_llm_output(
            repair_prompt,
            system_prompt=REVISE_SYSTEM_PROMPT,
            max_tokens=HTML_OUTPUT_MAX_TOKENS,
            temperature=0.08,
            stage="html_repairing",
            phase="revise",
            message_prefix="正在修复局部修改补丁",
            progress_start=85,
            progress_end=91,
            llm_stream=llm_stream,
        )
        try:
            html_output, warnings = apply_revision_patch_once(repaired_patch, topic=topic, analysis=analysis)
            return html_output, warnings, 2, True
        except (AetherVizRevisionError, AetherVizHtmlValidationError) as second_exc:
            fallback_error = f"首次失败：{first_error}；修复失败：{second_exc}"
            yield progress_event(
                "fallback_planning",
                "局部补丁修复失败，正在进入方案级兜底生成",
                92,
                phase="revise",
                mode=plan.get("mode"),
                subject=plan.get("subject"),
                detail=fallback_error,
                revision_index_summary=summarize_revision_index(analysis.revision_index),
            )
            fallback_prompt = build_adjusted_plan_fallback_prompt(
                topic=topic,
                instruction=instruction,
                analysis=analysis,
                error_detail=fallback_error,
                context=context,
            )
            fallback_raw_html = yield from stream_llm_output(
                fallback_prompt,
                system_prompt=system_prompt_for_plan(REPAIR_SYSTEM_PROMPT, plan),
                max_tokens=HTML_OUTPUT_MAX_TOKENS,
                temperature=0.12,
                stage="html_repairing",
                phase="revise",
                message_prefix="正在按调整后的方案重新生成页面",
                progress_start=93,
                progress_end=98,
                llm_stream=llm_stream,
            )
            try:
                html_output, warnings = parse_and_validate_html(fallback_raw_html, topic, plan)
            except (AetherVizInteractiveHtmlError, AetherVizHtmlValidationError) as fallback_exc:
                combined = f"{fallback_error}；方案级兜底失败：{fallback_exc}"
                raise AetherVizRevisionError(combined) from fallback_exc
            return html_output, warnings, 3, True
