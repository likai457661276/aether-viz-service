"""Registry declaration for data distribution IR."""

from aetherviz_service.aetherviz.ir.data_distribution.agent import stream_generate_data_distribution_html
from aetherviz_service.aetherviz.ir.data_distribution.routing import PROFILE, assess
from aetherviz_service.aetherviz.ir.registry import IRBackend

BACKEND = IRBackend(
    key="data_distribution_scene",
    representation_types=frozenset({"data_chart", "data_distribution"}),
    stream=stream_generate_data_distribution_html,
    routing_profile=PROFILE,
    assess=assess,
)
