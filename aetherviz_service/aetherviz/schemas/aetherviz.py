from typing import Any, Literal

from pydantic import BaseModel, Field


InteractiveType = Literal["simulation", "diagram", "game"]
RenderStack = Literal["svg", "svg_canvas", "canvas_svg", "dom_svg"]
AnimationRuntime = Literal["native"]


class AetherVizPlanControl(BaseModel):
    id: str
    label: str
    type: Literal["slider", "button", "speed", "toggle", "select"]
    bind: str | None = None
    action: str | None = None


class AetherVizTeachingFlowStep(BaseModel):
    id: str
    label: str
    focus: str
    caption: str


class AetherVizRuntime(BaseModel):
    render_stack: RenderStack = "svg"
    animation_runtime: AnimationRuntime = "native"
    external_libraries: list[str] = Field(default_factory=list)


class AetherVizPlan(BaseModel):
    page_type: Literal["interactive"] = "interactive"
    interactive_type: InteractiveType
    widget_type: InteractiveType | None = None
    subject: str
    title: str
    goal: str
    learner_level: str | None = None
    stage_layout: str | None = None
    interactive_spec: dict[str, Any] = Field(default_factory=dict)
    widget_outline: dict[str, Any] | None = None
    teaching_flow: list[AetherVizTeachingFlowStep] = Field(default_factory=list)
    controls: list[AetherVizPlanControl] = Field(default_factory=list)
    formulas: list[str] = Field(default_factory=list)
    runtime: AetherVizRuntime = Field(default_factory=AetherVizRuntime)
    primary_color: str = "#22D3EE"


class GenerateAetherVizSpecRequest(BaseModel):
    topic: str = Field(...)
    phase: Literal["plan", "generate", "revise"] = "plan"
    approved_plan: AetherVizPlan | None = None
    instruction: str | None = None
    context: dict[str, Any] | None = None


class GenerateAetherVizHtmlMetadata(BaseModel):
    topic: str
    attempts: int
    source: str | None = None
    repaired: bool = False
    degraded: bool = False
    validation_warnings: list[str] = Field(default_factory=list)
    subject: str | None = None
    render_mode: str | None = None
    plan: AetherVizPlan | None = None
