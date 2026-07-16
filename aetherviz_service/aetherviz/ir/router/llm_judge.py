"""Short structured-output model call for ambiguous IR routes."""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langsmith import traceable

from aetherviz_service.aetherviz.agents.model_factory import create_chat_model, extract_llm_text
from aetherviz_service.aetherviz.ir.registry import IRBackend
from aetherviz_service.aetherviz.ir.router.contracts import IRRouteAssessment
from aetherviz_service.aetherviz.ir.router.prompt import SYSTEM_PROMPT, build_router_prompt

logger = logging.getLogger(__name__)


def router_response_schema(backend_keys: tuple[str, ...]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "selected_backend": {"enum": [None, *backend_keys]},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "required_capabilities": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 12,
            },
            "evidence": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
        },
        "required": ["selected_backend", "confidence", "required_capabilities", "evidence"],
    }


@traceable(
    name="aetherviz.ir_routing_judge",
    run_type="llm",
    metadata={"component": "aetherviz", "stage": "ir_routing"},
)
def judge_ir_route(
    plan: dict[str, Any],
    candidates: tuple[IRRouteAssessment, ...],
    backends: tuple[IRBackend, ...],
) -> dict[str, Any]:
    keys = tuple(item.backend_key for item in candidates if item.eligible)
    if not keys:
        return {"selected_backend": None, "confidence": 1.0, "required_capabilities": [], "evidence": []}
    schema = router_response_schema(keys)
    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=build_router_prompt(plan, candidates, backends)),
    ]
    try:
        message = create_chat_model("routing", response_schema=schema).invoke(messages)
    except Exception as exc:
        logger.warning("strict IR router schema unavailable; using JSON mode: %s", exc)
        message = create_chat_model("routing").invoke(messages)
    raw = extract_llm_text(message).strip()
    if raw.startswith("```"):
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("ir_router_response_must_be_object")
    return value
