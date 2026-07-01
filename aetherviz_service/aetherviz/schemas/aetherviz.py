from typing import Literal

from pydantic import BaseModel, Field


class AetherVizRenderStack(BaseModel):
    subject: str
    mode: str
    main: str
    auxiliary: list[str] = Field(default_factory=list)


class AetherVizPlanVariable(BaseModel):
    name: str
    unit: str = ""
    default: str | int | float = ""
    min: str | int | float | None = None
    max: str | int | float | None = None
    recommended: str | int | float = ""
    classroom_tip: str = ""
    meaning: str = ""


class AetherVizPerformanceBudget(BaseModel):
    pixel_ratio_max: float = 2
    mobile_pixel_ratio_max: float = 1.5
    dynamic_svg_nodes_max: int = 300
    particles_desktop_max: int = 3000
    particles_mobile_max: int = 1200
    trajectory_points_max: int = 300


class AetherVizPlan(BaseModel):
    subject: str
    experiment_type: str
    render_stack: AetherVizRenderStack
    main_renderer: str
    learning_objectives: list[str] = Field(default_factory=list)
    core_concepts: list[str] = Field(default_factory=list)
    teacher_demo_flow: list[str] = Field(default_factory=list)
    key_variables: list[AetherVizPlanVariable] = Field(default_factory=list)
    performance_budget: AetherVizPerformanceBudget = Field(default_factory=AetherVizPerformanceBudget)
    self_check_items: list[str] = Field(default_factory=list)
    primary_color: str
    interaction_type: str = "general"
    interaction_hint: str = ""


class GenerateAetherVizSpecRequest(BaseModel):
    topic: str = Field(...)
    phase: Literal["plan", "generate"] = "plan"
    approved_plan: AetherVizPlan | None = None


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
