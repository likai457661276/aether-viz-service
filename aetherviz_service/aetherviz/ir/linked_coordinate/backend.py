"""Registry declaration for the linked-coordinate IR family."""

from aetherviz_service.aetherviz.ir.linked_coordinate.agent import (
    stream_generate_linked_coordinate_html,
)
from aetherviz_service.aetherviz.ir.linked_coordinate.routing import PROFILE, assess
from aetherviz_service.aetherviz.ir.registry import IRBackend

BACKEND = IRBackend(
    key="linked_coordinate_scene",
    representation_types=frozenset({"linked_coordinate_scene"}),
    stream=stream_generate_linked_coordinate_html,
    routing_profile=PROFILE,
    assess=assess,
)
