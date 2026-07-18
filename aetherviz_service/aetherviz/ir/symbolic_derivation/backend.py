"""Registry declaration for symbolic derivation IR."""

from aetherviz_service.aetherviz.ir.registry import IRBackend
from aetherviz_service.aetherviz.ir.symbolic_derivation.agent import stream_generate_symbolic_derivation_html
from aetherviz_service.aetherviz.ir.symbolic_derivation.routing import PROFILE, assess

BACKEND = IRBackend(
    key="symbolic_derivation_scene",
    representation_types=frozenset({"symbolic_derivation", "equation_derivation"}),
    stream=stream_generate_symbolic_derivation_html,
    routing_profile=PROFILE,
    assess=assess,
)
