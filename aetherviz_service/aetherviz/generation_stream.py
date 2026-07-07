"""SSE stream for approved-plan HTML generation and repair."""

from __future__ import annotations

from collections.abc import Iterator

from aetherviz_service.aetherviz.constants import HTML_OUTPUT_MAX_TOKENS
from aetherviz_service.aetherviz.fallback_validator import AetherVizInteractiveHtmlError
from aetherviz_service.aetherviz.html_output import parse_and_validate_html
from aetherviz_service.aetherviz.prompts import (
    REPAIR_SYSTEM_PROMPT,
    build_interactive_generation_prompt,
    build_repair_prompt,
    system_prompt_for_interactive_type,
)
from aetherviz_service.aetherviz.schemas.aetherviz import GenerateAetherVizHtmlMetadata
from aetherviz_service.aetherviz.sse import progress_event, sse_event
from aetherviz_service.aetherviz.streaming import LLMStreamCallable, estimate_output_tokens, stream_llm_output
from aetherviz_service.aetherviz.validator import AetherVizHtmlValidationError


def generate_from_plan_stream(topic: str, plan: dict, *, llm_stream: LLMStreamCallable) -> Iterator[str]:
    yield progress_event(
        "generating",
        "计划已确认，正在生成单页互动课件",
        65,
        phase="generate",
        interactive_type=plan["interactive_type"],
        plan=plan,
        subject=plan["subject"],
    )

    prompt = build_interactive_generation_prompt(topic, plan)
    system_prompt = system_prompt_for_interactive_type(plan)
    raw_html = yield from stream_llm_output(
        prompt,
        system_prompt=system_prompt,
        max_tokens=HTML_OUTPUT_MAX_TOKENS,
        temperature=0.25,
        stage="html_generating",
        phase="generate",
        message_prefix="正在生成互动页面代码",
        progress_start=66,
        progress_end=90,
        llm_stream=llm_stream,
    )
    output_tokens_total = estimate_output_tokens(raw_html)
    html_output, warnings, attempts, repaired, source = yield from parse_validate_or_repair_stream(
        raw_html,
        topic=topic,
        plan=plan,
        phase="generate",
        original_prompt=prompt,
        source_label="生成",
        llm_stream=llm_stream,
    )

    output_tokens_total = estimate_output_tokens(html_output)
    metadata = GenerateAetherVizHtmlMetadata(
        topic=topic,
        attempts=attempts,
        repaired=repaired,
        source=source,
        degraded=bool(warnings),
        validation_warnings=warnings,
        render_mode=plan["interactive_type"],
        subject=plan["subject"],
        plan=plan,
    )
    yield sse_event(
        "done",
        {
            "success": True,
            "stage": "done",
            "message": f"已返回自包含互动教学页面，共输出约 {output_tokens_total} Token",
            "progress": 100,
            "phase": "generate",
            "interactive_type": plan["interactive_type"],
            "html": html_output,
            "output_tokens_total": output_tokens_total,
            "metadata": metadata.model_dump(),
        },
    )


def parse_validate_or_repair_stream(
    raw_html: str,
    *,
    topic: str,
    plan: dict,
    phase: str,
    original_prompt: str,
    source_label: str,
    llm_stream: LLMStreamCallable,
) -> Iterator[tuple[str, list[str], int, bool, str]]:
    try:
        html_output, warnings = parse_and_validate_html(raw_html, topic, plan)
        return html_output, warnings, 1, False, "llm_interactive"
    except (AetherVizInteractiveHtmlError, AetherVizHtmlValidationError) as first_exc:
        first_error = str(first_exc)
        yield progress_event(
            "repairing",
            f"{source_label}结果未通过质量检查，正在自动修复一次",
            93,
            phase=phase,
            interactive_type=plan.get("interactive_type"),
            subject=plan.get("subject"),
            detail=first_error,
        )

        repair_prompt = build_repair_prompt(
            topic=topic,
            plan=plan,
            original_prompt=original_prompt,
            raw_html=raw_html,
            error_detail=first_error,
            source_label=source_label,
        )
        repaired_raw_html = yield from stream_llm_output(
            repair_prompt,
            system_prompt=REPAIR_SYSTEM_PROMPT,
            max_tokens=HTML_OUTPUT_MAX_TOKENS,
            temperature=0.08,
            stage="html_repairing",
            phase=phase,
            message_prefix="正在修复互动页面代码",
            progress_start=94,
            progress_end=98,
            llm_stream=llm_stream,
        )
        try:
            html_output, warnings = parse_and_validate_html(repaired_raw_html, topic, plan)
        except (AetherVizInteractiveHtmlError, AetherVizHtmlValidationError) as second_exc:
            second_error = str(second_exc)
            combined = f"首次失败：{first_error}；修复失败：{second_error}"
            raise type(first_exc)(combined) from second_exc
        return html_output, warnings, 2, True, "llm_interactive"
