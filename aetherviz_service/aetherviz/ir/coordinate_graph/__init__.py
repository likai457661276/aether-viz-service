"""Single-view coordinate graph IR built on the shared coordinate compiler."""

from aetherviz_service.aetherviz.ir.coordinate_graph.contract import (
    COORDINATE_GRAPH_IR_VERSION,
    compile_coordinate_graph_ir,
    validate_coordinate_graph_ir,
)

__all__ = [
    "COORDINATE_GRAPH_IR_VERSION",
    "compile_coordinate_graph_ir",
    "validate_coordinate_graph_ir",
]
