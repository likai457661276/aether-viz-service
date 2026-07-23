"""Explicit registry for independently versioned IR generation backends."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from functools import partial
from typing import Any

from aetherviz_service.aetherviz.contracts.html_stream import HtmlGenerationError
from aetherviz_service.aetherviz.ir.router.contracts import (
    IRRouteAssessment,
    IRRouteDecision,
    IRRoutingProfile,
)

UNSUPPORTED_GENERATION_BACKEND = "unsupported"

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
        if backend.key == UNSUPPORTED_GENERATION_BACKEND:
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
    ) -> GenerationStreamSelection:
        """Map a route decision to one verified IR stream or an explicit failure stream."""

        backend = self.get(route.selected_backend) if route.selected_backend else None
        if backend is None:
            return GenerationStreamSelection(
                generation_backend=UNSUPPORTED_GENERATION_BACKEND,
                stream_factory=partial(_unsupported_ir_stream, topic, plan, route),
                ir_backend=None,
            )
        return GenerationStreamSelection(
            generation_backend=backend.key,
            stream_factory=partial(backend.stream, topic, plan),
            ir_backend=backend,
        )


def _unsupported_ir_stream(
    topic: str,
    plan: dict[str, Any],
    route: IRRouteDecision,
) -> IRStream:
    del topic, plan
    candidate_failures = [
        {
            "backend_key": candidate.backend_key,
            "score": candidate.score,
            "missing_capabilities": list(candidate.missing_capabilities),
            "exclusion_reasons": list(candidate.exclusion_reasons),
        }
        for candidate in route.candidates
        if candidate.missing_capabilities or candidate.exclusion_reasons
    ]
    reasons = [reason for candidate in route.candidates for reason in candidate.exclusion_reasons]
    if not reasons:
        reasons = [
            f"{item['backend_key']} 缺少 {', '.join(item['missing_capabilities'])}"
            for item in candidate_failures[:3]
            if item["missing_capabilities"]
        ]
    detail = "；".join(dict.fromkeys(reasons)) or "当前计划没有满足全部必需能力的已注册 IR 后端"
    raise HtmlGenerationError(
        "当前教学动画超出已验证 IR 的能力范围，已停止生成",
        code="unsupported_ir_capability",
        detail=detail,
        diagnostics={
            "route": route.as_dict(),
            "candidate_failures": candidate_failures,
        },
    )
    yield  # pragma: no cover - keep this function an iterator factory


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
