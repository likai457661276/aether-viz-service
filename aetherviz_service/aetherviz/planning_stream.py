"""SSE stream for AetherViz fallback plan generation."""

from __future__ import annotations

import logging
from collections.abc import Iterator

from aetherviz_service.aetherviz.constants import PLANNING_MAX_TOKENS
from aetherviz_service.aetherviz.fallback_planner import build_planning_prompt, parse_planning_result
from aetherviz_service.aetherviz.sse import progress_event, sse_event
from aetherviz_service.aetherviz.streaming import LLMStreamCallable, coerce_llm_stream_chunk, estimate_output_tokens

logger = logging.getLogger(__name__)


def planning_stream(topic: str, color: str, *, llm_stream: LLMStreamCallable) -> Iterator[str]:
    yield progress_event("planning", "正在分析知识点，制定教学动画方案", 20, phase="plan")
    for delta in (
        "识别学科与核心目标...\n",
        "选择 SVG/Canvas/DOM 渲染栈与动画运行时...\n",
        "规划学生友好默认数值...\n",
        "规划舞台布局、教学分镜、时间线和互动控件...\n",
    ):
        yield sse_event(
            "plan_delta",
            {
                "success": True,
                "stage": "planning",
                "message": "正在生成教学动画方案",
                "progress": 30,
                "phase": "plan",
                "delta": delta,
            },
        )

    raw_chunks: list[str] = []
    output_tokens_total = 0
    try:
        planning_sys, planning_user = build_planning_prompt(topic, color)
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
                    "stage": "planning",
                    "message": f"正在生成教学动画方案，已输出约 {output_tokens_total} Token",
                    "progress": 45,
                    "phase": "plan",
                    "delta": chunk.delta,
                    "output_tokens": output_tokens,
                    "output_tokens_total": output_tokens_total,
                },
            )
        plan = parse_planning_result("".join(raw_chunks), topic, color)
    except Exception as exc:
        logger.warning("AetherViz planning 失败，使用兜底规划: %s", exc)
        plan = parse_planning_result("", topic, color)
        yield sse_event(
            "plan_delta",
            {
                "success": True,
                "stage": "planning",
                "message": "规划模型暂不可用，已切换兜底计划",
                "progress": 55,
                "phase": "plan",
                "delta": "规划模型暂不可用，已使用服务端兜底计划。\n",
            },
        )

    yield sse_event(
        "plan_ready",
        {
            "success": True,
            "stage": "plan_ready",
            "message": "教学动画方案已生成，请确认后继续生成 HTML 页面",
            "progress": 60,
            "phase": "plan",
            "mode": plan["mode"],
            "plan": plan,
            "subject": plan["subject"],
            "output_tokens_total": output_tokens_total,
        },
    )
