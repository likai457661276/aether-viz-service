"""Parametric regular-polygon geometry IR backend."""

from aetherviz_service.aetherviz.ir.parametric_geometry.contract import (
    PARAMETRIC_GEOMETRY_IR_VERSION,
    compile_parametric_geometry_ir,
    validate_parametric_geometry_ir,
)

__all__ = [
    "PARAMETRIC_GEOMETRY_IR_VERSION",
    "compile_parametric_geometry_ir",
    "validate_parametric_geometry_ir",
]
