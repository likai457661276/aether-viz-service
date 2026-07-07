"""AetherViz 路由。"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from aetherviz_service.aetherviz.react import react_generate_stream
from aetherviz_service.aetherviz.schemas.aetherviz import GenerateAetherVizSpecRequest


router = APIRouter(tags=["aetherviz"])


@router.post("/generate-aetherviz-spec")
def generate_aetherviz_spec(request: GenerateAetherVizSpecRequest) -> StreamingResponse:
    if not request.topic.strip():
        raise HTTPException(status_code=400, detail="topic 不能为空")
    if request.phase == "generate" and request.approved_plan is None:
        raise HTTPException(status_code=400, detail="approved_plan 不能为空")
    if request.phase == "edit":
        if not (request.instruction or "").strip():
            raise HTTPException(status_code=400, detail="instruction 不能为空")
        if not (request.current_html or "").strip():
            raise HTTPException(status_code=400, detail="current_html 不能为空")

    return StreamingResponse(
        react_generate_stream(
            topic=request.topic.strip(),
            phase=request.phase,
            approved_plan=request.approved_plan.model_dump() if request.approved_plan else None,
            instruction=request.instruction,
            current_html=request.current_html,
            context=request.context,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
