"""AetherViz phase-oriented route."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from aetherviz_service.aetherviz.agents.runtime import agent_runtime_stream
from aetherviz_service.aetherviz.api.schemas import GenerateAetherVizSpecRequest, dump_plan


router = APIRouter(tags=["aetherviz"])


@router.post("/generate-aetherviz-spec")
def generate_aetherviz_spec(payload: dict[str, Any]) -> StreamingResponse:
    try:
        request = GenerateAetherVizSpecRequest.model_validate(payload)
    except ValidationError as exc:
        error = exc.errors()[0]
        detail = str(error.get("msg") or "请求参数错误")
        if detail.startswith("Value error, "):
            detail = detail.removeprefix("Value error, ")
        raise HTTPException(status_code=400, detail=detail) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return StreamingResponse(
        agent_runtime_stream(
            phase=request.phase,
            topic=request.topic.strip(),
            current_plan=dump_plan(request.current_plan),
            message=(request.message or "").strip() or None,
            plan=dump_plan(request.plan),
            approved_plan=dump_plan(request.approved_plan),
            current_html=request.current_html,
            context=request.context,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
