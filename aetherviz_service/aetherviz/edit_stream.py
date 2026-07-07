"""SSE stream for editing an existing generated HTML file."""

from __future__ import annotations

from collections.abc import Iterator

from aetherviz_service.aetherviz.constants import HTML_OUTPUT_MAX_TOKENS
from aetherviz_service.aetherviz.fallback_planner import normalize_plan
from aetherviz_service.aetherviz.generation_stream import parse_validate_or_repair_stream
from aetherviz_service.aetherviz.prompts import EDIT_HTML_SYSTEM_PROMPT, build_edit_html_prompt
from aetherviz_service.aetherviz.schemas.aetherviz import GenerateAetherVizHtmlMetadata
from aetherviz_service.aetherviz.sse import progress_event, sse_event
from aetherviz_service.aetherviz.streaming import LLMStreamCallable, estimate_output_tokens, stream_llm_output


def edit_html_stream(
    topic: str,
    instruction: str,
    current_html: str,
    *,
    color: str,
    context: dict | None,
    llm_stream: LLMStreamCallable,
) -> Iterator[str]:
    plan = _plan_from_context(context, topic, color)
    yield progress_event(
        "html_editing",
        "正在基于选中的 HTML 文件应用修改意见",
        65,
        phase="edit",
        interactive_type=plan.get("interactive_type"),
        plan=plan,
        subject=plan.get("subject"),
    )

    prompt = build_edit_html_prompt(
        topic=topic,
        instruction=instruction,
        current_html=current_html,
        context=context,
    )
    raw_html = yield from stream_llm_output(
        prompt,
        system_prompt=EDIT_HTML_SYSTEM_PROMPT,
        max_tokens=HTML_OUTPUT_MAX_TOKENS,
        temperature=0.18,
        stage="html_editing",
        phase="edit",
        message_prefix="正在修改互动页面代码",
        progress_start=66,
        progress_end=92,
        llm_stream=llm_stream,
    )
    html_output, warnings, attempts, repaired, source = yield from parse_validate_or_repair_stream(
        raw_html,
        topic=topic,
        plan=plan,
        phase="edit",
        original_prompt=prompt,
        source_label="编辑",
        llm_stream=llm_stream,
    )

    output_tokens_total = estimate_output_tokens(html_output)
    metadata = GenerateAetherVizHtmlMetadata(
        topic=topic,
        attempts=attempts,
        repaired=repaired,
        source="llm_html_edit" if source == "llm_interactive" else source,
        degraded=bool(warnings),
        validation_warnings=warnings,
        render_mode=plan.get("interactive_type"),
        subject=plan.get("subject"),
        plan=plan,
    )
    yield sse_event(
        "done",
        {
            "success": True,
            "stage": "done",
            "message": f"已生成新的 HTML 修改分支，共输出约 {output_tokens_total} Token",
            "progress": 100,
            "phase": "edit",
            "interactive_type": plan.get("interactive_type"),
            "html": html_output,
            "output_tokens_total": output_tokens_total,
            "metadata": metadata.model_dump(),
        },
    )


def _plan_from_context(context: dict | None, topic: str, color: str) -> dict:
    plan_summary = (context or {}).get("plan_summary")
    return normalize_plan(plan_summary if isinstance(plan_summary, dict) else {}, topic, color)
