"""Public entry point for the shared HTML validation and repair pipeline."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

from aetherviz_service.aetherviz.agents.html_agent import HtmlStreamResult


def run_html_pipeline(
    *,
    run_id: str,
    phase: str,
    start_event: str,
    topic: str,
    plan: dict[str, Any],
    html_stream_factory: Callable[[], Iterator[dict[str, Any] | HtmlStreamResult]],
    emit_start_event: bool = True,
    candidate_guard: Callable[[str], list[str]] | None = None,
    initial_metadata: dict[str, Any] | None = None,
) -> Iterator[str]:
    """Run the shared pipeline without exposing a workflow module's private symbol."""
    from aetherviz_service.aetherviz.workflow.generate_workflow import run_html_pipeline as implementation

    yield from implementation(
        run_id=run_id,
        phase=phase,
        start_event=start_event,
        topic=topic,
        plan=plan,
        html_stream_factory=html_stream_factory,
        emit_start_event=emit_start_event,
        candidate_guard=candidate_guard,
        initial_metadata=initial_metadata,
    )
