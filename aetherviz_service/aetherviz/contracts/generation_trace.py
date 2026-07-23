"""Lightweight generation-pipeline trace contracts.

Records per-request stage timing and metadata for offline analysis.
Does not bind to any storage backend.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TraceStage(BaseModel):
    """One observed stage inside a generation request."""

    name: str
    status: str = "running"
    start_time: float
    end_time: float | None = None
    duration_ms: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class GenerationTrace(BaseModel):
    """End-to-end generation pipeline observation for a single request."""

    request_id: str
    user_prompt: str
    start_time: float
    end_time: float | None = None
    stages: list[TraceStage] = Field(default_factory=list)
    status: str = "running"
    error: str | None = None
    failed_stage: str | None = None
