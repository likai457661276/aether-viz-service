"""Registry declaration for the number-line IR family."""

from aetherviz_service.aetherviz.ir.number_line.agent import stream_generate_number_line_html
from aetherviz_service.aetherviz.ir.number_line.routing import PROFILE, assess
from aetherviz_service.aetherviz.ir.registry import IRBackend

BACKEND = IRBackend(
    key="number_line_scene",
    representation_types=frozenset({"number_line"}),
    stream=stream_generate_number_line_html,
    routing_profile=PROFILE,
    assess=assess,
)
