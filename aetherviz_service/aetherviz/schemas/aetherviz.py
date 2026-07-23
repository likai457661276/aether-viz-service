from typing import Any, Literal

from pydantic import BaseModel, Field

from aetherviz_service.aetherviz.constants import get_gsap_core_cdn_url

InteractiveType = Literal["simulation", "diagram", "game"]
RenderStack = Literal["svg", "svg_canvas", "canvas_svg", "dom_svg"]
AnimationRuntime = Literal["gsap"]

# Field ownership mirrors workflow/plan_layers.py. Keep these lists in sync when
# adding plan keys.
TEACHING_PLAN_FIELDS = (
    "source_topic",
    "interactive_type",
    "title",
    "goal",
    "learner_level",
    "stage_layout",
    "key_points",
    "design_brief",
    "interactive_spec",
    "teaching_flow",
    "controls",
    "formulas",
    "primary_color",
)
GENERATION_SPEC_FIELDS = (
    "page_type",
    "widget_type",
    "subject",
    "knowledge_profile",
    "representation_spec",
    "recomposition_spec",
    "discipline_spec",
    "scene_outline",
    "widget_outline",
    "widget_actions",
    "runtime",
    "runtime_controls",
)


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


class AetherVizTeachingPlan(BaseModel):
    """User-facing teaching animation plan.

    Produced by ``phase=plan`` / ``revise_plan`` and confirmed by the user.
    Machine IR routing fields must not live here.
    """

    source_topic: str | None = None
    interactive_type: InteractiveType
    title: str
    goal: str
    learner_level: str | None = None
    stage_layout: str | None = None
    key_points: list[str] = Field(default_factory=list)
    design_brief: dict[str, Any] = Field(default_factory=dict)
    interactive_spec: dict[str, Any] = Field(default_factory=dict)
    teaching_flow: list[AetherVizTeachingFlowStep] = Field(default_factory=list)
    controls: list[AetherVizPlanControl] = Field(default_factory=list)
    formulas: list[str] = Field(default_factory=list)
    primary_color: str = "#22D3EE"
    status: Literal["draft", "revised", "approved"] | None = None
    revision_summary: str | None = None
    context_status: dict[str, Any] | None = None


class AetherVizGenerationSpec(BaseModel):
    """Machine generation / IR routing contract.

    Derived at ``approve_plan`` from a confirmed TeachingPlan. Opaque to the
    user; must not rewrite confirmed teaching semantics (except allowed
    interactive_spec numeric span narrowing for recomposition feasibility).
    """

    page_type: Literal["interactive"] = "interactive"
    widget_type: InteractiveType | None = None
    subject: str
    knowledge_profile: dict[str, Any] = Field(default_factory=dict)
    representation_spec: dict[str, Any] = Field(default_factory=dict)
    recomposition_spec: dict[str, Any] | None = None
    discipline_spec: dict[str, list[str]] = Field(default_factory=dict)
    scene_outline: dict[str, Any] | None = None
    widget_outline: dict[str, Any] | None = None
    widget_actions: list[dict[str, Any]] = Field(default_factory=list)
    runtime: AetherVizRuntime = Field(default_factory=AetherVizRuntime)
    runtime_controls: list[AetherVizPlanControl] = Field(default_factory=list)


class AetherVizPlan(BaseModel):
    """Legacy flat plan combining TeachingPlan + GenerationSpec.

    Prefer ``AetherVizTeachingPlan`` + ``AetherVizGenerationSpec`` for new
    Approach B wire shapes. This model remains the P1 compatibility surface.
    """

    page_type: Literal["interactive"] = "interactive"
    source_topic: str | None = None
    interactive_type: InteractiveType
    widget_type: InteractiveType | None = None
    scene_outline: dict[str, Any] | None = None
    subject: str
    knowledge_profile: dict[str, Any] = Field(default_factory=dict)
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
    discipline_spec: dict[str, list[str]] = Field(default_factory=dict)
    representation_spec: dict[str, Any] = Field(default_factory=dict)
    recomposition_spec: dict[str, Any] | None = None
    runtime: AetherVizRuntime = Field(default_factory=AetherVizRuntime)
    runtime_controls: list[AetherVizPlanControl] = Field(default_factory=list)
    primary_color: str = "#22D3EE"
