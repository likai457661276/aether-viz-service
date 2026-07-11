"""Request schemas for the phase-oriented AetherViz API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from aetherviz_service.aetherviz.schemas.aetherviz import AetherVizPlan

AetherVizPhase = Literal["plan", "revise_plan", "approve_plan", "generate", "edit_html"]
REQUIRED_PLAN_FIELDS = ("interactive_type", "subject", "title", "goal")


class GenerateAetherVizSpecRequest(BaseModel):
    phase: AetherVizPhase = "plan"
    topic: str = Field(default="")
    context: dict[str, Any] | None = None
    current_plan: AetherVizPlan | dict[str, Any] | None = None
    message: str | None = None
    plan: AetherVizPlan | dict[str, Any] | None = None
    approved_plan: AetherVizPlan | dict[str, Any] | None = None
    current_html: str | None = None

    @model_validator(mode="after")
    def validate_phase_payload(self) -> GenerateAetherVizSpecRequest:
        topic_required = self.phase in {"plan", "revise_plan"}
        if topic_required and not self.topic.strip():
            raise ValueError("topic 不能为空")
        if self.phase == "revise_plan":
            if self.current_plan is None:
                raise ValueError("current_plan 不能为空")
            if not (self.message or "").strip():
                raise ValueError("message 不能为空")
            _require_plan_fields(self.current_plan, "current_plan")
        if self.phase == "approve_plan" and self.plan is None:
            raise ValueError("plan 不能为空")
        if self.phase == "approve_plan":
            _require_plan_fields(self.plan, "plan")
        if self.phase == "generate" and self.approved_plan is None:
            raise ValueError("approved_plan 不能为空")
        if self.phase == "generate":
            _require_plan_fields(self.approved_plan, "approved_plan")
        if self.phase == "edit_html":
            if not (self.current_html or "").strip():
                raise ValueError("current_html 不能为空")
            if not (self.message or "").strip():
                raise ValueError("message 不能为空")
        return self


def dump_plan(value: AetherVizPlan | dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, AetherVizPlan):
        return value.model_dump()
    return dict(value)


def _require_plan_fields(value: AetherVizPlan | dict[str, Any] | None, field_name: str) -> None:
    if value is None:
        return
    payload = value.model_dump() if isinstance(value, AetherVizPlan) else value
    missing = [field for field in REQUIRED_PLAN_FIELDS if not payload.get(field)]
    if missing:
        raise ValueError(f"{field_name} 缺少必要字段：{', '.join(missing)}")
