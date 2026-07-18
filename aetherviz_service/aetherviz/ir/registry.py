"""Explicit registry for independently versioned IR generation backends."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from functools import partial
from typing import Any

from aetherviz_service.aetherviz.ir.router.contracts import (
    IRRouteAssessment,
    IRRouteDecision,
    IRRoutingProfile,
)

DIRECT_GENERATION_BACKEND = "direct"

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


@dataclass(frozen=True)
class GenerationStreamSelection:
    """Resolved HTML/IR stream factory for one generate request."""

    generation_backend: str
    stream_factory: Callable[[], IRStream]
    ir_backend: IRBackend | None = None


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
        if backend.key == DIRECT_GENERATION_BACKEND:
            raise ValueError(f"reserved_ir_backend:{backend.key}")
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

    def select_for_route(
        self,
        route: IRRouteDecision,
        *,
        topic: str,
        plan: dict[str, Any],
        direct_stream: IRStreamFactory,
    ) -> GenerationStreamSelection:
        """Map a route decision to one stream factory; unknown/missing keys fall back to direct."""

        backend = self.get(route.selected_backend) if route.selected_backend else None
        if backend is None:
            return GenerationStreamSelection(
                generation_backend=DIRECT_GENERATION_BACKEND,
                stream_factory=partial(direct_stream, topic, plan),
                ir_backend=None,
            )
        return GenerationStreamSelection(
            generation_backend=backend.key,
            stream_factory=partial(backend.stream, topic, plan),
            ir_backend=backend,
        )


def _build_default_registry() -> IRBackendRegistry:
    # Imports stay local so each IR package can depend on shared agent primitives
    # without making the workflow import every compiler implementation.
    from aetherviz_service.aetherviz.ir.constraint_geometry.backend import BACKEND as constraint_geometry
    from aetherviz_service.aetherviz.ir.coordinate_graph.backend import BACKEND as coordinate_graph
    from aetherviz_service.aetherviz.ir.data_distribution.backend import BACKEND as data_distribution
    from aetherviz_service.aetherviz.ir.discrete_structure.backend import BACKEND as discrete_structure
    from aetherviz_service.aetherviz.ir.linked_coordinate.backend import BACKEND as linked_coordinate
    from aetherviz_service.aetherviz.ir.number_line.backend import BACKEND as number_line
    from aetherviz_service.aetherviz.ir.parametric_geometry.backend import BACKEND as parametric_geometry
    from aetherviz_service.aetherviz.ir.probability_experiment.backend import BACKEND as probability_experiment
    from aetherviz_service.aetherviz.ir.recomposition.backend import BACKEND as recomposition
    from aetherviz_service.aetherviz.ir.symbolic_derivation.backend import BACKEND as symbolic_derivation

    return IRBackendRegistry(
        (
            recomposition,
            linked_coordinate,
            coordinate_graph,
            parametric_geometry,
            number_line,
            constraint_geometry,
            data_distribution,
            symbolic_derivation,
            probability_experiment,
            discrete_structure,
        )
    )


DEFAULT_IR_REGISTRY = _build_default_registry()


def resolve_ir_backend(plan: dict[str, Any]) -> IRBackend | None:
    return DEFAULT_IR_REGISTRY.resolve(plan)
