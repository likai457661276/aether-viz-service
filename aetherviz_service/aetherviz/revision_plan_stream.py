"""SSE stream for revise-as-replan AetherViz flow."""

from __future__ import annotations

import logging
from collections.abc import Iterator

from aetherviz_service.aetherviz.constants import PLANNING_MAX_TOKENS
from aetherviz_service.aetherviz.fallback_planner import build_revision_planning_prompt, parse_planning_result
from aetherviz_service.aetherviz.sse import progress_event, sse_event
from aetherviz_service.aetherviz.streaming import LLMStreamCallable, coerce_llm_stream_chunk, estimate_output_tokens

logger = logging.getLogger(__name__)


def revise_plan_stream(
    topic: str,
    instruction: str,
    *,
    color: str,
    context: dict | None,
    llm_stream: LLMStreamCallable,
) -> Iterator[str]:
    yield progress_event("revise_planning", "正在理解修改要求并重新规划互动教案", 20, phase="revise")

    raw_chunks: list[str] = []
    output_tokens_total = 0
    try:
        planning_sys, planning_user = build_revision_planning_prompt(topic, instruction, context, color)
        for raw_chunk in llm_stream(
            planning_user,
            system_prompt=planning_sys,
            max_tokens=PLANNING_MAX_TOKENS,
            temperature=0.25,
            enable_thinking=False,
        ):
            chunk = coerce_llm_stream_chunk(raw_chunk)
            if not chunk.delta or chunk.kind == "reasoning":
                continue
            raw_chunks.append(chunk.delta)
            output_tokens = estimate_output_tokens(chunk.delta)
            output_tokens_total += output_tokens
            yield sse_event(
                "plan_delta",
                {
                    "success": True,
                    "stage": "revise_planning",
                    "message": f"正在重新规划互动教案，已输出约 {output_tokens_total} Token",
                    "progress": 45,
                    "phase": "revise",
                    "delta": chunk.delta,
                    "output_tokens": output_tokens,
                    "output_tokens_total": output_tokens_total,
                },
            )
        plan = parse_planning_result("".join(raw_chunks), topic, color)
    except Exception as exc:
        logger.warning("AetherViz 重新规划失败，使用兜底规划: %s", exc)
        plan = parse_planning_result("", topic, color)
        yield sse_event(
            "plan_delta",
            {
                "success": True,
                "stage": "revise_planning",
                "message": "规划模型暂不可用，已切换兜底计划",
                "progress": 55,
                "phase": "revise",
                "delta": "规划模型暂不可用，已使用服务端兜底计划。\n",
            },
        )

    yield sse_event(
        "plan_ready",
        {
            "success": True,
            "stage": "plan_ready",
            "message": "新的互动课件方案已生成，请确认后重新生成 HTML 页面",
            "progress": 60,
            "phase": "revise",
            "interactive_type": plan["interactive_type"],
            "plan": plan,
            "subject": plan["subject"],
            "output_tokens_total": output_tokens_total,
        },
    )
