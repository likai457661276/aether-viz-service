from typing import Literal

from pydantic import BaseModel, Field


GenerationMode = Literal["generic_svg", "math_svg_katex_css", "math_svg_katex_gsap"]


class AetherVizPlanControl(BaseModel):
    id: str
    label: str
    type: Literal["slider", "button", "speed"]


class AetherVizPlan(BaseModel):
    subject: str
    mode: GenerationMode
    title: str
    goal: str
    visual_steps: list[str] = Field(default_factory=list)
    controls: list[AetherVizPlanControl] = Field(default_factory=list)
    formulas: list[str] = Field(default_factory=list)
    validation_points: list[str] = Field(default_factory=list)
    primary_color: str = "#22D3EE"


class GenerateAetherVizSpecRequest(BaseModel):
    topic: str = Field(...)
    phase: Literal["plan", "generate", "revise"] = "plan"
    approved_plan: AetherVizPlan | None = None
    current_html: str | None = None
    instruction: str | None = None


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
