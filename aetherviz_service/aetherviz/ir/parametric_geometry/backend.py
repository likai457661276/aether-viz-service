"""Registry declaration for parametric geometry IR."""

from aetherviz_service.aetherviz.ir.parametric_geometry.agent import stream_generate_parametric_geometry_html
from aetherviz_service.aetherviz.ir.parametric_geometry.routing import PROFILE, assess
from aetherviz_service.aetherviz.ir.registry import IRBackend

BACKEND = IRBackend(
    key="parametric_geometry_scene",
    representation_types=frozenset({"geometric_construction"}),
    stream=stream_generate_parametric_geometry_html,
    routing_profile=PROFILE,
    assess=assess,
)
