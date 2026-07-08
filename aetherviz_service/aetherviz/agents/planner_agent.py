"""Planning agent for initial and revised lesson plans."""

from __future__ import annotations

import json
import logging
from typing import Any

from aetherviz_service.aetherviz.agents.model_factory import (
    create_agent_app,
    extract_agent_text,
    has_planning_llm_config,
)
from aetherviz_service.aetherviz.fallback_planner import build_planning_prompt, normalize_plan, parse_planning_result
from aetherviz_service.aetherviz.theme import extract_color_from_topic

logger = logging.getLogger(__name__)


PLANNER_SYSTEM_PROMPT = """你是 planning_agent，只负责生成或修订 AI互动实验教案计划。
输出必须是完整 JSON 计划对象，不输出 Markdown。每次修订都重新生成完整计划，不返回局部 patch。"""


def create_plan(topic: str, *, context: dict[str, Any] | None = None) -> tuple[dict[str, Any], bool]:
    color = extract_color_from_topic(topic)
    system_prompt, user_prompt = build_planning_prompt(topic, color)
    if not has_planning_llm_config():
        return _fallback_plan(topic, color, status="draft"), True
    try:
        agent = create_agent_app("planning", system_prompt=f"{PLANNER_SYSTEM_PROMPT}\n\n{system_prompt}")
        result = agent.invoke({"messages": [{"role": "user", "content": user_prompt}]})
        plan = parse_planning_result(extract_agent_text(result), topic, color)
        plan["status"] = "draft"
        plan["plan_id"] = plan.get("plan_id") or _plan_id(topic, "draft")
        plan["context_status"] = {"status": "normal"}
        return plan, False
    except Exception as exc:
        logger.warning("planning_agent failed, using fallback plan: %s", exc)
        return _fallback_plan(topic, color, status="draft"), True


def revise_plan(
    topic: str,
    *,
    current_plan: dict[str, Any],
    message: str,
    context: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], bool]:
    color = extract_color_from_topic(topic)
    prompt = f"""请根据用户修改意见重新生成完整教案计划。

教学主题：{topic}
用户修改意见：{message}
当前计划 JSON：
{json.dumps(current_plan, ensure_ascii=False)}

要求：
- 必须输出完整计划 JSON，不输出 diff。
- status 设为 revised。
- revision_summary 简要说明本次修改。
"""
    if not has_planning_llm_config():
        plan = normalize_plan(current_plan, topic, color)
        return _apply_revision_fallback(plan, topic, message), True
    try:
        system_prompt, _ = build_planning_prompt(topic, color)
        agent = create_agent_app("planning", system_prompt=f"{PLANNER_SYSTEM_PROMPT}\n\n{system_prompt}")
        result = agent.invoke({"messages": [{"role": "user", "content": prompt}]})
        plan = parse_planning_result(extract_agent_text(result), topic, color)
        plan["status"] = "revised"
        plan["plan_id"] = plan.get("plan_id") or _plan_id(topic, "revised")
        plan["revision_summary"] = plan.get("revision_summary") or message[:120]
        plan["context_status"] = {"status": "normal"}
        return plan, False
    except Exception as exc:
        logger.warning("planning_agent revision failed, using fallback revision: %s", exc)
        plan = normalize_plan(current_plan, topic, color)
        return _apply_revision_fallback(plan, topic, message), True


def approve_plan(plan: dict[str, Any]) -> dict[str, Any]:
    topic = str(plan.get("topic") or plan.get("title") or "AI互动实验")
    approved = normalize_plan(plan, topic, str(plan.get("primary_color") or "#22D3EE"))
    approved["status"] = "approved"
    approved["plan_id"] = approved.get("plan_id") or _plan_id(topic, "approved")
    approved["context_status"] = {"status": "normal"}
    return approved


def _fallback_plan(topic: str, color: str, *, status: str) -> dict[str, Any]:
    plan = normalize_plan({}, topic, color)
    plan["status"] = status
    plan["plan_id"] = _plan_id(topic, status)
    plan["revision_summary"] = ""
    plan["context_status"] = {"status": "normal"}
    return plan


def _apply_revision_fallback(plan: dict[str, Any], topic: str, message: str) -> dict[str, Any]:
    revised = dict(plan)
    revised["status"] = "revised"
    revised["plan_id"] = _plan_id(topic, "revised")
    revised["revision_summary"] = message[:160]
    revised["goal"] = f'{plan.get("goal", "")} 修订要求：{message[:80]}'.strip()[:180]
    revised["context_status"] = {"status": "compressed"}
    return revised


def _plan_id(topic: str, suffix: str) -> str:
    return f"plan_{abs(hash((topic, suffix))) % 10_000_000}_{suffix}"
