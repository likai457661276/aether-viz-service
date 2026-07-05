"""SSE stream for statically matched AetherViz knowledge points."""

from __future__ import annotations

from collections.abc import Iterator

from aetherviz_service.aetherviz.knowledge_points import get_knowledge_point
from aetherviz_service.aetherviz.schemas.aetherviz import GenerateAetherVizHtmlMetadata
from aetherviz_service.aetherviz.sse import progress_event, sse_event
from aetherviz_service.aetherviz.static_html import StaticAetherVizHtmlError, load_static_html_for_point


def static_match_stream(topic: str, color: str, match) -> Iterator[str]:
    point = get_knowledge_point(match.knowledge_point_id)
    if point is None:
        raise StaticAetherVizHtmlError(f"知识点不存在：{match.knowledge_point_id}")

    yield progress_event(
        "static_match",
        f"已命中静态知识点：{match.knowledge_point_title}",
        35,
        subject=match.subject,
        knowledge_domain=match.knowledge_domain,
        knowledge_point_id=match.knowledge_point_id,
        grade=match.grade,
        match_confidence=match.confidence,
        mode="static",
    )
    html_output = load_static_html_for_point(point, color)
    metadata = GenerateAetherVizHtmlMetadata(
        topic=topic,
        attempts=0,
        source="static_html",
        degraded=False,
        subject=match.subject,
        knowledge_domain=match.knowledge_domain,
        knowledge_point_id=match.knowledge_point_id,
        knowledge_point_title=match.knowledge_point_title,
        grade=match.grade,
        render_mode="static",
        match_confidence=match.confidence,
    )
    yield sse_event(
        "done",
        {
            "success": True,
            "stage": "done",
            "message": "已返回静态互动可视化页面",
            "progress": 100,
            "phase": "generate",
            "mode": "static",
            "html": html_output,
            "metadata": metadata.model_dump(),
        },
    )
