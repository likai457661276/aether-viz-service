from typing import Any, Literal

from pydantic import BaseModel, Field

from aetherviz_service.aetherviz.constants import get_gsap_core_cdn_url

InteractiveType = Literal["simulation", "diagram", "game"]
RenderStack = Literal["svg", "svg_canvas", "canvas_svg", "dom_svg"]
AnimationRuntime = Literal["native", "gsap"]


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
    animation_runtime: AnimationRuntime = "gsap"
    external_libraries: list[str] = Field(default_factory=lambda: [get_gsap_core_cdn_url()])


class AetherVizPlan(BaseModel):
    page_type: Literal["interactive"] = "interactive"
    interactive_type: InteractiveType
    widget_type: InteractiveType | None = None
    scene_outline: dict[str, Any] | None = None
    subject: str
    title: str
    goal: str
    learner_level: str | None = None
    stage_layout: str | None = None
    key_points: list[str] = Field(default_factory=list)
    design_brief: dict[str, Any] = Field(default_factory=dict)
    interactive_spec: dict[str, Any] = Field(default_factory=dict)
    widget_outline: dict[str, Any] | None = None
    widget_actions: list[dict[str, Any]] = Field(default_factory=list)
    teaching_flow: list[AetherVizTeachingFlowStep] = Field(default_factory=list)
    controls: list[AetherVizPlanControl] = Field(default_factory=list)
    formulas: list[str] = Field(default_factory=list)
    runtime: AetherVizRuntime = Field(default_factory=AetherVizRuntime)
    primary_color: str = "#22D3EE"

