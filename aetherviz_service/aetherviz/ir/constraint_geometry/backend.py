"""Registry declaration for constraint geometry IR."""

from aetherviz_service.aetherviz.ir.constraint_geometry.agent import stream_generate_constraint_geometry_html
from aetherviz_service.aetherviz.ir.constraint_geometry.routing import PROFILE, assess
from aetherviz_service.aetherviz.ir.registry import IRBackend

BACKEND = IRBackend(
    key="constraint_geometry_scene",
    representation_types=frozenset({"constraint_geometry"}),
    stream=stream_generate_constraint_geometry_html,
    routing_profile=PROFILE,
    assess=assess,
)
