"""Registry declaration for finite probability experiments."""

from aetherviz_service.aetherviz.ir.probability_experiment.agent import stream_generate_probability_experiment_html
from aetherviz_service.aetherviz.ir.probability_experiment.routing import PROFILE, assess
from aetherviz_service.aetherviz.ir.registry import IRBackend

BACKEND = IRBackend(
    key="probability_experiment_scene",
    representation_types=frozenset({"probability_experiment", "probability_tree"}),
    stream=stream_generate_probability_experiment_html,
    routing_profile=PROFILE,
    assess=assess,
)
