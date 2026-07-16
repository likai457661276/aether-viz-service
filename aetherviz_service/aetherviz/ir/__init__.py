"""Structured scene IR backends.

The workflow depends only on the registry in this package. Each IR family owns
its model contract, deterministic validation, compiler and server runtime.
"""

from aetherviz_service.aetherviz.ir.registry import IRBackend, IRBackendRegistry, resolve_ir_backend

__all__ = ["IRBackend", "IRBackendRegistry", "resolve_ir_backend"]
