"""Validated constraint-driven geometry IR backend."""

from aetherviz_service.aetherviz.ir.constraint_geometry.contract import (
    CONSTRAINT_GEOMETRY_IR_VERSION,
    compile_constraint_geometry_ir,
    validate_constraint_geometry_ir,
)

__all__ = [
    "CONSTRAINT_GEOMETRY_IR_VERSION",
    "compile_constraint_geometry_ir",
    "validate_constraint_geometry_ir",
]
