"""Plan-stage route preview with one bounded representation_spec self-correction."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from aetherviz_service.aetherviz.agents.model_factory import create_chat_model, extract_llm_text, has_planning_llm_config
from aetherviz_service.aetherviz.ir.registry import DEFAULT_IR_REGISTRY, IRBackendRegistry
from aetherviz_service.aetherviz.ir.router.capability_catalog import build_ir_capability_catalog
from aetherviz_service.aetherviz.ir.router.contracts import IRRouteDecision
from aetherviz_service.aetherviz.ir.router.service import resolve_generation_route
from aetherviz_service.aetherviz.workflow.plan_contract import normalize_plan
from aetherviz_service.config import settings

logger = logging.getLogger(__name__)

_REFINE_SYSTEM_PROMPT = """你是互动教学课件的表征规格修订器。
只输出一个合法 JSON 对象，不输出 Markdown 或解释。
JSON 顶层字段只能包含 representation_spec，以及在教学语义确实需要切分重排时可选的 recomposition_spec。
representation_spec 是服务端选择实现的权威能力配置：描述通用视觉能力，不直接填写实现后端名称。
字段约束与规划器一致：version 固定 1.0；views / state_variables / correspondences / required_invariants / interaction_requirements 使用既定枚举。

{capability_catalog}

根据路由预览反馈修正能力配置，使计划落入已验证能力范围；未要求变更的教学语义字段由服务端保留。
"""


def maybe_refine_plan_for_route(
    plan: dict[str, Any],
    *,
    topic: str,
    registry: IRBackendRegistry = DEFAULT_IR_REGISTRY,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run deterministic route preview; if unroutable or low confidence, refine spec once."""
    color = str(plan.get("primary_color") or "#22D3EE")
    normalized = normalize_plan(plan, topic, color)
    preview = resolve_generation_route(normalized, registry=registry, allow_llm=False)
    metrics: dict[str, Any] = {
        "route_preview_attempted": True,
        "route_preview_refined": False,
        "route_preview_selected_backend": preview.selected_backend,
        "route_preview_confidence": preview.confidence,
        "route_preview_reasons": list(preview.reasons)[:8],
    }
    if not _needs_refinement(preview):
        return normalized, metrics
    if not has_planning_llm_config():
        metrics["route_preview_skipped"] = "planning_llm_unavailable"
        return normalized, metrics

    feedback = format_route_preview_feedback(preview)
    try:
        refined_fields = _refine_representation_fields(normalized, topic=topic, feedback=feedback)
    except Exception as exc:
        logger.warning("plan route preview refine failed: %s", exc)
        metrics["route_preview_skipped"] = type(exc).__name__
        return normalized, metrics

    merged = dict(normalized)
    if "representation_spec" in refined_fields:
        merged["representation_spec"] = refined_fields["representation_spec"]
    if "recomposition_spec" in refined_fields:
        merged["recomposition_spec"] = refined_fields["recomposition_spec"]
    elif "recomposition_spec" in merged and "recomposition_spec" not in refined_fields:
        # Keep existing recomposition unless the model explicitly replaced it.
        pass
    refined = normalize_plan(merged, topic, color)
    metrics["route_preview_refined"] = True
    post = resolve_generation_route(refined, registry=registry, allow_llm=False)
    metrics["route_preview_selected_backend"] = post.selected_backend
    metrics["route_preview_confidence"] = post.confidence
    metrics["route_preview_reasons"] = list(post.reasons)[:8]
    return refined, metrics


def _needs_refinement(route: IRRouteDecision) -> bool:
    if route.selected_backend is None:
        return True
    return route.confidence < settings.aetherviz_ir_router_deterministic_threshold


def format_route_preview_feedback(route: IRRouteDecision) -> str:
    lines: list[str] = []
    if route.selected_backend is None:
        lines.append("当前草稿没有合格的可视化能力后端（selected_backend=None）。")
    else:
        lines.append(
            f"当前草稿路由置信度偏低：confidence={route.confidence:.3f}，"
            f"低于确定性阈值 {settings.aetherviz_ir_router_deterministic_threshold:.2f}。"
        )
    for candidate in route.candidates[:6]:
        missing = "、".join(candidate.missing_capabilities) or "无"
        exclusions = "；".join(candidate.exclusion_reasons) or "无"
        lines.append(
            f"- 候选能力族 score={candidate.score:.3f} eligible={candidate.eligible}；"
            f"缺失能力：{missing}；排除原因：{exclusions}"
        )
    if route.reasons:
        lines.append("路由理由：" + "；".join(str(item) for item in route.reasons[:6]))
    return "\n".join(lines)


def _refine_representation_fields(plan: dict[str, Any], *, topic: str, feedback: str) -> dict[str, Any]:
    system_prompt = _REFINE_SYSTEM_PROMPT.format(capability_catalog=build_ir_capability_catalog())
    compact = {
        "title": plan.get("title"),
        "goal": plan.get("goal"),
        "interactive_type": plan.get("interactive_type"),
        "interactive_spec": plan.get("interactive_spec"),
        "discipline_spec": plan.get("discipline_spec"),
        "representation_spec": plan.get("representation_spec"),
        "recomposition_spec": plan.get("recomposition_spec"),
        "teaching_flow": plan.get("teaching_flow"),
        "design_brief": plan.get("design_brief"),
    }
    user_prompt = (
        f"主题：{topic}\n"
        f"路由预览反馈：\n{feedback}\n\n"
        f"当前教学语义草稿（仅供修订表征规格）：\n"
        f"{json.dumps(compact, ensure_ascii=False, separators=(',', ':'))}\n"
    )
    model = create_chat_model("planning")
    response = model.invoke(
        [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
    )
    raw = extract_llm_text(response).strip()
    if not raw:
        raise ValueError("empty_route_preview_refine")
    fence = re.search(r"```(?:json)?\s*(.*?)```", raw, re.DOTALL | re.IGNORECASE)
    if fence:
        raw = fence.group(1).strip()
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError("route_preview_refine_not_json")
    parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("route_preview_refine_not_object")
    result: dict[str, Any] = {}
    if isinstance(parsed.get("representation_spec"), dict):
        result["representation_spec"] = parsed["representation_spec"]
    if isinstance(parsed.get("recomposition_spec"), dict):
        result["recomposition_spec"] = parsed["recomposition_spec"]
    if "representation_spec" not in result:
        raise ValueError("route_preview_refine_missing_representation_spec")
    return result
