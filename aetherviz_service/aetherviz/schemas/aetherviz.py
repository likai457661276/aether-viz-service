from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


GenerationMode = Literal[
    "svg_animation",
    "math_interactive",
    "process_flow",
]

AnimationStrategy = Literal["step_by_step", "continuous", "interactive_param"]
RenderStack = Literal["svg", "svg_canvas", "canvas_svg", "dom_svg"]
AnimationRuntime = Literal["native", "gsap_timeline"]


class AetherVizPlanControl(BaseModel):
    id: str
    label: str
    type: Literal["slider", "button", "speed"]


class AetherVizTimelineScene(BaseModel):
    id: str
    label: str
    duration: float | None = None
    focus: str
    caption: str


class AetherVizNumberDesign(BaseModel):
    default_values: list[str] = Field(default_factory=list)
    reason: str | None = None


class AetherVizPlan(BaseModel):
    subject: str
    mode: GenerationMode
    animation_strategy: Optional[AnimationStrategy] = None
    render_stack: Optional[RenderStack] = None
    animation_runtime: AnimationRuntime = "native"
    title: str
    goal: str
    stage_layout: str | None = None
    storyboard: list[str] = Field(default_factory=list)
    timeline_scenes: list[AetherVizTimelineScene] = Field(default_factory=list)
    number_design: AetherVizNumberDesign | None = None
    visual_steps: list[str] = Field(default_factory=list)
    controls: list[AetherVizPlanControl] = Field(default_factory=list)
    formulas: list[str] = Field(default_factory=list)
    primary_color: str = "#22D3EE"


class GenerateAetherVizSpecRequest(BaseModel):
    topic: str = Field(...)
    phase: Literal["plan", "generate", "revise"] = "plan"
    approved_plan: AetherVizPlan | None = None
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
