from typing import Any, Literal

from pydantic import BaseModel, Field


InteractiveType = Literal["simulation", "diagram", "game"]
RenderStack = Literal["svg", "svg_canvas", "canvas_svg", "dom_svg"]
AnimationRuntime = Literal["native", "gsap_timeline"]


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
    subject: str
    title: str
    goal: str
    learner_level: str | None = None
    stage_layout: str | None = None
    interactive_spec: dict[str, Any] = Field(default_factory=dict)
    teaching_flow: list[AetherVizTeachingFlowStep] = Field(default_factory=list)
    controls: list[AetherVizPlanControl] = Field(default_factory=list)
    formulas: list[str] = Field(default_factory=list)
    runtime: AetherVizRuntime = Field(default_factory=AetherVizRuntime)
    primary_color: str = "#22D3EE"


class GenerateAetherVizSpecRequest(BaseModel):
    topic: str = Field(...)
    phase: Literal["plan", "generate", "revise"] = "plan"
    approved_plan: AetherVizPlan | None = None
    # Deprecated: revise no longer reads or sends HTML into the planning chain.
    current_html: str | None = None
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
    knowledge_domain: str | None = None
    knowledge_point_id: str | None = None
    knowledge_point_title: str | None = None
    grade: str | None = None
    render_mode: str | None = None
    match_confidence: float | None = None
    plan: AetherVizPlan | None = None


class StaticAetherVizKnowledgePointItem(BaseModel):
    knowledge_point_id: str
    title: str
    subject: str
    knowledge_domain: str
    grade: str | None = None
    keywords: list[str] = Field(default_factory=list)
    render_mode: str
    static_html_slug: str
    static_html_path: str
    core_concepts: list[str] = Field(default_factory=list)
    key_formulas: list[str] = Field(default_factory=list)
    cover_image_base64: str


class StaticAetherVizKnowledgePointsResponse(BaseModel):
    success: bool = True
    total: int
    knowledge_points: list[StaticAetherVizKnowledgePointItem]


class StaticAetherVizHtmlResponse(BaseModel):
    success: bool = True
    knowledge_point_id: str
    title: str
    subject: str
    knowledge_domain: str
    grade: str | None = None
    render_mode: str
    static_html_slug: str
    static_html_path: str
    primary_color: str
    html: str
