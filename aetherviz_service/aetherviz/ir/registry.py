"""Explicit registry for independently versioned IR generation backends."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

from aetherviz_service.aetherviz.ir.router.contracts import IRRouteAssessment, IRRoutingProfile

IRStream = Iterator[Any]
IRStreamFactory = Callable[[str, dict[str, Any]], IRStream]


@dataclass(frozen=True)
class IRBackend:
    """A generation backend selected by normalized representation type."""

    key: str
    representation_types: frozenset[str]
    stream: IRStreamFactory
    routing_profile: IRRoutingProfile = field(default_factory=IRRoutingProfile)
    assess: Callable[[dict[str, Any]], IRRouteAssessment] | None = None


class IRBackendRegistry:
    """Validated immutable-by-convention mapping of representations to backends."""

    def __init__(self, backends: tuple[IRBackend, ...] = ()) -> None:
        self._by_representation: dict[str, IRBackend] = {}
        self._by_key: dict[str, IRBackend] = {}
        for backend in backends:
            self.register(backend)

    def register(self, backend: IRBackend) -> None:
        if not backend.key or backend.key in self._by_key:
            raise ValueError(f"duplicate_ir_backend:{backend.key}")
        if not backend.representation_types:
            raise ValueError(f"ir_backend_without_representation:{backend.key}")
        overlaps = sorted(set(backend.representation_types) & set(self._by_representation))
        if overlaps:
            raise ValueError(f"duplicate_ir_representation:{','.join(overlaps)}")
        self._by_key[backend.key] = backend
        for representation in backend.representation_types:
            self._by_representation[representation] = backend

    def resolve(self, plan: dict[str, Any]) -> IRBackend | None:
        profile = plan.get("knowledge_profile")
        representation = profile.get("representation_type") if isinstance(profile, dict) else None
        return self._by_representation.get(str(representation or ""))

    def backends(self) -> tuple[IRBackend, ...]:
        return tuple(self._by_key.values())

    def get(self, key: str) -> IRBackend | None:
        return self._by_key.get(key)

    def assess(self, plan: dict[str, Any]) -> tuple[IRRouteAssessment, ...]:
        assessments = [backend.assess(plan) for backend in self.backends() if backend.assess is not None]
        return tuple(sorted(assessments, key=lambda item: (-item.score, item.backend_key)))


def _build_default_registry() -> IRBackendRegistry:
    # Imports stay local so each IR package can depend on shared agent primitives
    # without making the workflow import every compiler implementation.
    from aetherviz_service.aetherviz.ir.linked_coordinate.backend import BACKEND as linked_coordinate
    from aetherviz_service.aetherviz.ir.recomposition.backend import BACKEND as recomposition

    return IRBackendRegistry((recomposition, linked_coordinate))


DEFAULT_IR_REGISTRY = _build_default_registry()


def resolve_ir_backend(plan: dict[str, Any]) -> IRBackend | None:
    return DEFAULT_IR_REGISTRY.resolve(plan)
