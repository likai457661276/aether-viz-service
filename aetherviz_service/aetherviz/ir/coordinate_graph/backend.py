"""Registry declaration for the single-view coordinate graph IR family."""

from aetherviz_service.aetherviz.ir.coordinate_graph.agent import stream_generate_coordinate_graph_html
from aetherviz_service.aetherviz.ir.coordinate_graph.routing import PROFILE, assess
from aetherviz_service.aetherviz.ir.registry import IRBackend

BACKEND = IRBackend(
    key="coordinate_graph_scene",
    representation_types=frozenset({"coordinate_graph"}),
    stream=stream_generate_coordinate_graph_html,
    routing_profile=PROFILE,
    assess=assess,
)
