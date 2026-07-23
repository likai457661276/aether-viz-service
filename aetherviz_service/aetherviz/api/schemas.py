"""Request schemas for the phase-oriented AetherViz API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from aetherviz_service.aetherviz.schemas.aetherviz import (
    AetherVizGenerationSpec,
    AetherVizPlan,
    AetherVizTeachingPlan,
)

AetherVizPhase = Literal["plan", "revise_plan", "approve_plan", "generate", "edit_html"]
REQUIRED_PLAN_FIELDS = ("interactive_type", "subject", "title", "goal")
REQUIRED_TEACHING_PLAN_FIELDS = ("interactive_type", "title", "goal")


class GenerateAetherVizSpecRequest(BaseModel):
    phase: AetherVizPhase = "plan"
    topic: str = Field(default="")
    context: dict[str, Any] | None = None
    current_plan: AetherVizPlan | dict[str, Any] | None = None
    message: str | None = None
    plan: AetherVizPlan | dict[str, Any] | None = None
    approved_plan: AetherVizPlan | dict[str, Any] | None = None
    teaching_plan: AetherVizTeachingPlan | dict[str, Any] | None = None
    generation_spec: AetherVizGenerationSpec | dict[str, Any] | None = None
    current_html: str | None = None
    edit_target: dict[str, Any] | None = None
    runtime_error: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_phase_payload(self) -> GenerateAetherVizSpecRequest:
        topic_required = self.phase in {"plan", "revise_plan"}
        if topic_required and not self.topic.strip():
            raise ValueError("topic 不能为空")
        if self.phase == "revise_plan":
            if self.current_plan is None and self.teaching_plan is None:
                raise ValueError("current_plan 或 teaching_plan 不能为空")
            if not (self.message or "").strip():
                raise ValueError("message 不能为空")
            if self.current_plan is not None:
                _require_plan_fields(self.current_plan, "current_plan")
            else:
                _require_teaching_plan_fields(self.teaching_plan, "teaching_plan")
        if self.phase == "approve_plan":
            if self.plan is None and self.teaching_plan is None:
                raise ValueError("plan 或 teaching_plan 不能为空")
            if self.plan is not None:
                _require_plan_fields(self.plan, "plan")
            else:
                _require_teaching_plan_fields(self.teaching_plan, "teaching_plan")
        if self.phase == "generate":
            has_flat = self.approved_plan is not None
            has_dual = self.teaching_plan is not None and self.generation_spec is not None
            has_teaching_only = self.teaching_plan is not None and self.generation_spec is None
            if not has_flat and not has_dual and not has_teaching_only:
                raise ValueError("approved_plan 或 teaching_plan(+generation_spec) 不能为空")
            if has_flat:
                _require_plan_fields(self.approved_plan, "approved_plan")
            else:
                _require_teaching_plan_fields(self.teaching_plan, "teaching_plan")
        if self.phase == "edit_html":
            if not (self.current_html or "").strip():
                raise ValueError("current_html 不能为空")
            if not (self.message or "").strip():
                raise ValueError("message 不能为空")
        return self


def dump_plan(value: AetherVizPlan | AetherVizTeachingPlan | dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, (AetherVizPlan, AetherVizTeachingPlan, AetherVizGenerationSpec)):
        return value.model_dump()
    return dict(value)


def dump_generation_spec(
    value: AetherVizGenerationSpec | dict[str, Any] | None,
) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, AetherVizGenerationSpec):
        return value.model_dump()
    return dict(value)


def _require_plan_fields(value: AetherVizPlan | dict[str, Any] | None, field_name: str) -> None:
    if value is None:
        return
    payload = value.model_dump() if isinstance(value, AetherVizPlan) else value
    # Flat legacy plans require subject; teaching-only payloads are validated separately.
    missing = [field for field in REQUIRED_PLAN_FIELDS if not payload.get(field)]
    if missing and "subject" in missing and payload.get("title") and payload.get("goal"):
        # Allow teaching-shaped flat payloads that omit subject (filled at compile).
        missing = [field for field in missing if field != "subject"]
    if missing:
        raise ValueError(f"{field_name} 缺少必要字段：{', '.join(missing)}")


def _require_teaching_plan_fields(
    value: AetherVizTeachingPlan | dict[str, Any] | None,
    field_name: str,
) -> None:
    if value is None:
        return
    payload = value.model_dump() if isinstance(value, AetherVizTeachingPlan) else value
    missing = [field for field in REQUIRED_TEACHING_PLAN_FIELDS if not payload.get(field)]
    if missing:
        raise ValueError(f"{field_name} 缺少必要字段：{', '.join(missing)}")
