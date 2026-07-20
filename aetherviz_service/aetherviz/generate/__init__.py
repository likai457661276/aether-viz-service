"""Initial IR-backed HTML generation workflow (plan -> verified IR -> HTML)."""

from typing import TYPE_CHECKING, Any

__all__ = ["run_generate_workflow"]

if TYPE_CHECKING:
    from aetherviz_service.aetherviz.generate.workflow import run_generate_workflow


def __getattr__(name: str) -> Any:
    """Load the public workflow lazily to avoid the IR/generate import cycle."""

    if name != "run_generate_workflow":
        raise AttributeError(name)
    from aetherviz_service.aetherviz.generate.workflow import run_generate_workflow

    return run_generate_workflow
