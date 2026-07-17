"""Shim: use aetherviz.generate.workflow / contracts.pipeline."""
from aetherviz_service.aetherviz.contracts.pipeline import (
    run_html_pipeline,
    _validate,
    _summarize_sse_trace,
    _attempt_quality_repair,
    QUALITY_REPAIR_WARNING_TYPES,
)
from aetherviz_service.aetherviz.generate.workflow import run_generate_workflow

__all__ = [
    "QUALITY_REPAIR_WARNING_TYPES",
    "_attempt_quality_repair",
    "_summarize_sse_trace",
    "_validate",
    "run_generate_workflow",
    "run_html_pipeline",
]
