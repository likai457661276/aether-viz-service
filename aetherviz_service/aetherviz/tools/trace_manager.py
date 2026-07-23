"""In-memory generation trace manager with JSONL persistence."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from aetherviz_service.aetherviz.contracts.generation_trace import GenerationTrace, TraceStage

DEFAULT_TRACE_DIR = Path("logs/traces")


class TraceManager:
    """Collect stage observations for one generation request and persist JSONL."""

    def __init__(self, *, output_dir: Path | str | None = None) -> None:
        self._output_dir = Path(output_dir) if output_dir is not None else DEFAULT_TRACE_DIR
        self._trace: GenerationTrace | None = None
        self._open_stages: dict[str, TraceStage] = {}

    def start_trace(self, request_id: str, user_prompt: str) -> GenerationTrace:
        self._trace = GenerationTrace(
            request_id=request_id,
            user_prompt=user_prompt,
            start_time=time.time(),
            status="running",
        )
        self._open_stages.clear()
        return self._trace

    def start_stage(self, name: str) -> TraceStage:
        trace = self._require_trace()
        if name in self._open_stages:
            raise ValueError(f"stage already running: {name}")
        stage = TraceStage(name=name, status="running", start_time=time.time())
        self._open_stages[name] = stage
        trace.stages.append(stage)
        return stage

    def add_stage(self, name: str) -> TraceStage:
        """Alias for start_stage()."""

        return self.start_stage(name)

    def finish_stage(self, name: str, metadata: dict[str, Any] | None = None) -> TraceStage:
        stage = self._require_open_stage(name)
        now = time.time()
        stage.end_time = now
        stage.duration_ms = max(0, int((now - stage.start_time) * 1000))
        stage.status = "success"
        if metadata:
            stage.metadata.update(metadata)
        del self._open_stages[name]
        return stage

    def fail_trace(
        self,
        failed_stage: str,
        error: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> GenerationTrace:
        """Mark the request failed at a stage. Does not raise or swallow caller exceptions."""

        trace = self._require_trace()
        now = time.time()
        stage = self._open_stages.get(failed_stage)
        if stage is None:
            stage = next((item for item in reversed(trace.stages) if item.name == failed_stage), None)
        if stage is None:
            stage = TraceStage(name=failed_stage, status="running", start_time=now)
            trace.stages.append(stage)
        stage.status = "failed"
        stage.end_time = now
        stage.duration_ms = max(0, int((now - stage.start_time) * 1000))
        stage.error = error
        if metadata:
            stage.metadata.update(metadata)
        self._open_stages.pop(failed_stage, None)

        for open_name, open_stage in list(self._open_stages.items()):
            open_stage.status = "failed"
            open_stage.end_time = now
            open_stage.duration_ms = max(0, int((now - open_stage.start_time) * 1000))
            open_stage.error = open_stage.error or f"aborted after {failed_stage} failed"
            del self._open_stages[open_name]

        if trace.status != "failed":
            trace.status = "failed"
            trace.failed_stage = failed_stage
            trace.error = error
            trace.end_time = now
        return trace

    def complete_trace(self, metadata: dict[str, Any] | None = None) -> GenerationTrace:
        """Mark the request successful after all stages finished."""

        trace = self._require_trace()
        if self._open_stages:
            raise ValueError(f"cannot complete trace with open stages: {sorted(self._open_stages)}")
        if metadata:
            final = next((item for item in reversed(trace.stages) if item.name == "final_result"), None)
            if final is not None:
                final.metadata.update(metadata)
        if trace.status == "running":
            trace.status = "success"
            trace.end_time = time.time()
            trace.error = None
            trace.failed_stage = None
        return trace

    def get_trace(self) -> GenerationTrace | None:
        return self._trace

    def current_open_stage(self) -> str | None:
        """Return the earliest open stage name, if any."""

        return next(iter(self._open_stages), None)

    def save(self) -> Path | None:
        """Append one JSON object as a JSONL line. Always persists failed traces."""

        if self._trace is None:
            return None
        self._output_dir.mkdir(parents=True, exist_ok=True)
        path = self._output_dir / "generation_traces.jsonl"
        payload = self._trace.model_dump(mode="json")
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return path

    def _require_trace(self) -> GenerationTrace:
        if self._trace is None:
            raise RuntimeError("trace has not been started")
        return self._trace

    def _require_open_stage(self, name: str) -> TraceStage:
        stage = self._open_stages.get(name)
        if stage is None:
            raise ValueError(f"stage is not running: {name}")
        return stage


def classify_generation_error_stage(code: str) -> str:
    """Map HtmlGenerationError / pipeline error codes to a failed stage name."""

    normalized = (code or "").strip().lower()
    if normalized in {"unsupported_ir_capability"}:
        return "ir_routing"
    if normalized in {"validation_failed"}:
        return "validation"
    if normalized in {"runtime_error"} or "compile" in normalized:
        return "runtime_compile"
    return "ir_generation"
