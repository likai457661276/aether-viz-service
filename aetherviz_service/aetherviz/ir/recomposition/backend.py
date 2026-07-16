"""Registry adapter for the existing geometric recomposition IR family.

The implementation remains import-compatible in its original modules while it
is migrated package-by-package; new callers depend only on this adapter.
"""

from aetherviz_service.aetherviz.ir.recomposition.agent import (
    stream_generate_recomposition_html,
)
from aetherviz_service.aetherviz.ir.recomposition.routing import PROFILE, assess
from aetherviz_service.aetherviz.ir.registry import IRBackend

BACKEND = IRBackend(
    key="recomposition_scene",
    representation_types=frozenset({"geometric_recomposition"}),
    stream=stream_generate_recomposition_html,
    routing_profile=PROFILE,
    assess=assess,
)
