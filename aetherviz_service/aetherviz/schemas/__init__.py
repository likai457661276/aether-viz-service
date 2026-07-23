"""AetherViz 专属 schema。"""

from aetherviz_service.aetherviz.schemas.aetherviz import (
    AetherVizGenerationSpec,
    AetherVizPlan,
    AetherVizTeachingPlan,
)

__all__ = ["AetherVizPlan", "AetherVizTeachingPlan", "AetherVizGenerationSpec"]
