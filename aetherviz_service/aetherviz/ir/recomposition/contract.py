"""Stable package boundary for geometric recomposition IR contracts."""

from aetherviz_service.aetherviz.tools.recomposition_contract import validate_scene_module
from aetherviz_service.aetherviz.tools.recomposition_ir import (
    GEOMETRY_IR_VERSION,
    compile_geometry_ir,
    geometry_ir_candidates_response_schema,
    geometry_ir_response_schema,
    parse_geometry_ir,
    validate_geometry_ir,
)

__all__ = [
    "GEOMETRY_IR_VERSION",
    "compile_geometry_ir",
    "geometry_ir_candidates_response_schema",
    "geometry_ir_response_schema",
    "parse_geometry_ir",
    "validate_geometry_ir",
    "validate_scene_module",
]
