"""Shim: use aetherviz.generate.html_agent / contracts.html_stream."""
from aetherviz_service.aetherviz.contracts.html_stream import (
    HTML_REASONING_EVENT_INTERVAL_MS,
    HTML_SIZE_EVENT_INTERVAL_BYTES,
    HtmlGenerationError,
    HtmlStreamResult,
    build_html_progress_payload,
    build_html_reasoning_payload,
    build_html_size_payload,
)
from aetherviz_service.aetherviz.generate.html_agent import stream_generate_html

__all__ = [
    "HTML_REASONING_EVENT_INTERVAL_MS",
    "HTML_SIZE_EVENT_INTERVAL_BYTES",
    "HtmlGenerationError",
    "HtmlStreamResult",
    "build_html_progress_payload",
    "build_html_reasoning_payload",
    "build_html_size_payload",
    "stream_generate_html",
]
