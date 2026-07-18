"""Registry declaration for discrete structures."""

from aetherviz_service.aetherviz.ir.discrete_structure.agent import stream_generate_discrete_structure_html
from aetherviz_service.aetherviz.ir.discrete_structure.routing import PROFILE, assess
from aetherviz_service.aetherviz.ir.registry import IRBackend

BACKEND = IRBackend(
    key="discrete_structure_scene",
    representation_types=frozenset({"discrete_structure", "graph_structure", "combinatorial_structure"}),
    stream=stream_generate_discrete_structure_html,
    routing_profile=PROFILE,
    assess=assess,
)
