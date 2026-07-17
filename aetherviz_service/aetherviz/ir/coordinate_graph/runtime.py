"""Single-view wrapper around the server-owned coordinate SVG runtime."""

from __future__ import annotations

from typing import Any

from aetherviz_service.aetherviz.ir.coordinate_graph.contract import compile_coordinate_graph_ir
from aetherviz_service.aetherviz.ir.linked_coordinate.runtime import assemble_linked_coordinate_business_html


def assemble_coordinate_graph_business_html(
    ir: dict[str, Any], plan: dict[str, Any], topic: str
) -> str:
    return assemble_linked_coordinate_business_html(
        ir,
        plan,
        topic,
        ir_family="coordinate_graph",
        compile_ir=compile_coordinate_graph_ir,
    )
