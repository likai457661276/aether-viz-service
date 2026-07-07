"""AetherViz SSE generator orchestration.

动态生成策略：
- 先生成结构化计划，再按确认计划生成自包含互动 HTML。
- revise 基于上次计划摘要 + instruction 重新规划，确认后再生成新 HTML。
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

from aetherviz_service.aetherviz.constants import HTML_OUTPUT_MAX_TOKENS, PLANNING_MAX_TOKENS
from aetherviz_service.aetherviz.edit_stream import edit_html_stream
from aetherviz_service.aetherviz.fallback_planner import normalize_plan
from aetherviz_service.aetherviz.fallback_validator import AetherVizInteractiveHtmlError
from aetherviz_service.aetherviz.generation_stream import generate_from_plan_stream
from aetherviz_service.aetherviz.planning_stream import planning_stream
from aetherviz_service.aetherviz.revision_plan_stream import revise_plan_stream
from aetherviz_service.aetherviz.sse import error_event, sse_event
from aetherviz_service.aetherviz.theme import extract_color_from_topic
from aetherviz_service.aetherviz.validator import AetherVizHtmlValidationError
from aetherviz_service.llm_service import LLMServiceError, call_llm_stream

logger = logging.getLogger(__name__)


def react_generate_stream(
    topic: str,
    phase: str = "plan",
    approved_plan: dict | None = None,
    instruction: str | None = None,
    current_html: str | None = None,
    context: dict | None = None,
) -> Iterator[str]:
    color = extract_color_from_topic(topic)
    yield sse_event(
        "start",
        {
            "success": True,
            "stage": "start",
            "message": f"开始处理《{topic}》的互动可视化任务",
            "progress": 3,
            "phase": phase,
        },
    )

    try:
        if phase == "plan":
            yield from planning_stream(topic, color, llm_stream=call_llm_stream)
            return

        if phase == "generate":
            if not approved_plan:
                yield error_event("plan_required", "动态生成需要先确认计划", "phase=generate 必须携带 approved_plan")
                return
            plan = normalize_plan(approved_plan, topic, color)
            yield from generate_from_plan_stream(topic, plan, llm_stream=call_llm_stream)
            return

        if phase == "revise":
            if not instruction or not instruction.strip():
                yield error_event("instruction_required", "重新规划需要修改意见", "phase=revise 必须携带 instruction")
                return
            yield from revise_plan_stream(topic, instruction, color=color, context=context, llm_stream=call_llm_stream)
            return

        if phase == "edit":
            if not instruction or not instruction.strip():
                yield error_event("instruction_required", "修改 HTML 需要修改意见", "phase=edit 必须携带 instruction")
                return
            if not current_html or not current_html.strip():
                yield error_event("current_html_required", "修改 HTML 需要选中的 HTML 文件", "phase=edit 必须携带 current_html")
                return
            yield from edit_html_stream(
                topic,
                instruction,
                current_html,
                color=color,
                context=context,
                llm_stream=call_llm_stream,
            )
            return

        yield error_event("invalid_phase", "不支持的生成阶段", f"phase={phase}")
    except LLMServiceError as exc:
        yield error_event("llm_error", "调用大模型失败，请检查模型服务配置或稍后重试", str(exc))
    except AetherVizInteractiveHtmlError as exc:
        logger.exception("交互式 HTML 页面生成失败")
        yield error_event("html_generation_failed", "交互式 HTML 页面生成失败", str(exc))
    except AetherVizHtmlValidationError as exc:
        logger.exception("动态 HTML 未通过检查")
        yield error_event("validation_failed", "生成页面未通过质量检查", str(exc))
    except Exception as exc:
        logger.exception("AetherViz 生成异常")
        yield error_event("unknown_error", "生成过程中发生异常，请稍后重试", str(exc))
