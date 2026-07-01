"""AetherViz 路由。"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse

import aetherviz_service.aetherviz.static_html as static_html_module
from aetherviz_service.aetherviz.knowledge_points import KNOWLEDGE_POINTS, KnowledgePoint
from aetherviz_service.aetherviz.react import react_generate_stream
from aetherviz_service.aetherviz.schemas.aetherviz import (
    GenerateAetherVizSpecRequest,
    StaticAetherVizHtmlResponse,
    StaticAetherVizKnowledgePointItem,
    StaticAetherVizKnowledgePointsResponse,
)
from aetherviz_service.aetherviz.static_html import StaticAetherVizHtmlError


router = APIRouter(tags=["aetherviz"])


def _static_html_relative_path(point: KnowledgePoint) -> str:
    return str(
        static_html_module.static_html_path_for_point(point).relative_to(
            static_html_module.HTML_ROOT
        )
    )


def _static_knowledge_point_item(point: KnowledgePoint) -> StaticAetherVizKnowledgePointItem:
    return StaticAetherVizKnowledgePointItem(
        knowledge_point_id=point.knowledge_point_id,
        title=point.title,
        subject=point.subject,
        knowledge_domain=point.knowledge_domain,
        grade=point.grade,
        keywords=list(point.keywords),
        render_mode=point.render_mode,
        static_html_slug=point.static_html_slug,
        static_html_path=_static_html_relative_path(point),
        core_concepts=list(point.core_concepts),
        key_formulas=list(point.key_formulas),
        cover_image_base64=point.cover_image_base64,
    )


@router.get(
    "/aetherviz-static-knowledge-points",
    response_model=StaticAetherVizKnowledgePointsResponse,
)
def list_static_aetherviz_knowledge_points() -> StaticAetherVizKnowledgePointsResponse:
    points = [
        point
        for point in KNOWLEDGE_POINTS.values()
        if point.render_mode == "static-html" and point.static_html_slug
    ]
    items = [
        _static_knowledge_point_item(point)
        for point in sorted(points, key=lambda item: (item.subject, item.knowledge_point_id))
    ]
    return StaticAetherVizKnowledgePointsResponse(total=len(items), knowledge_points=items)


@router.get(
    "/aetherviz-static-html",
    response_model=StaticAetherVizHtmlResponse,
)
def get_static_aetherviz_html(knowledge_point_id: str) -> StaticAetherVizHtmlResponse:
    point = KNOWLEDGE_POINTS.get(knowledge_point_id)
    if not point or point.render_mode != "static-html" or not point.static_html_slug:
        raise HTTPException(status_code=404, detail="静态知识点不存在")

    primary_color = static_html_module.DEFAULT_PRIMARY_COLOR
    try:
        html = static_html_module.load_static_html_for_point(point, primary_color)
    except StaticAetherVizHtmlError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return StaticAetherVizHtmlResponse(
        knowledge_point_id=point.knowledge_point_id,
        title=point.title,
        subject=point.subject,
        knowledge_domain=point.knowledge_domain,
        grade=point.grade,
        render_mode=point.render_mode,
        static_html_slug=point.static_html_slug,
        static_html_path=_static_html_relative_path(point),
        primary_color=primary_color,
        html=html,
    )


@router.get("/static-html/{static_html_path:path}", response_class=HTMLResponse)
def get_static_aetherviz_html_by_path(static_html_path: str) -> HTMLResponse:
    try:
        html = static_html_module.load_static_html_for_relative_path(
            static_html_path,
            static_html_module.DEFAULT_PRIMARY_COLOR,
        )
    except StaticAetherVizHtmlError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return HTMLResponse(content=html)


@router.post("/generate-aetherviz-spec")
def generate_aetherviz_spec(request: GenerateAetherVizSpecRequest) -> StreamingResponse:
    if not request.topic.strip():
        raise HTTPException(status_code=400, detail="topic 不能为空")
    if request.phase == "generate" and request.approved_plan is None:
        raise HTTPException(status_code=400, detail="approved_plan 不能为空")

    return StreamingResponse(
        react_generate_stream(
            topic=request.topic.strip(),
            phase=request.phase,
            approved_plan=request.approved_plan.model_dump() if request.approved_plan else None,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
