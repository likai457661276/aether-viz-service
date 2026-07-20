"""Structured scene IR backends.

The workflow depends only on the registry in this package. Each IR family owns
its model contract, deterministic validation, compiler and server runtime.
"""

from aetherviz_service.aetherviz.ir.registry import (
    UNSUPPORTED_GENERATION_BACKEND,
    GenerationStreamSelection,
    IRBackend,
    IRBackendRegistry,
    resolve_ir_backend,
)

__all__ = [
    "GenerationStreamSelection",
    "IRBackend",
    "IRBackendRegistry",
    "UNSUPPORTED_GENERATION_BACKEND",
    "resolve_ir_backend",
]
