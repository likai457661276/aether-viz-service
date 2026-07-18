"""Validated one-dimensional number-line IR backend."""

from aetherviz_service.aetherviz.ir.number_line.contract import (
    NUMBER_LINE_IR_VERSION,
    compile_number_line_ir,
    validate_number_line_ir,
)

__all__ = ["NUMBER_LINE_IR_VERSION", "compile_number_line_ir", "validate_number_line_ir"]
