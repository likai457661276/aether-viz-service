"""Stable contracts shared by the IR registry and router."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class IRRoutingProfile:
    description: str = ""
    capabilities: frozenset[str] = frozenset()
    required_capabilities: frozenset[str] = frozenset()
    supported_view_kinds: frozenset[str] = frozenset()
    exclusions: tuple[str, ...] = ()


@dataclass(frozen=True)
class IRRouteAssessment:
    backend_key: str
    eligible: bool
    score: float
    matched_capabilities: tuple[str, ...] = ()
    missing_capabilities: tuple[str, ...] = ()
    exclusion_reasons: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class IRRouteDecision:
    selected_backend: str | None
    source: str
    confidence: float
    plan_fingerprint: str
    candidates: tuple[IRRouteAssessment, ...]
    reasons: tuple[str, ...] = ()
    llm_invoked: bool = False
    llm_accepted: bool = False
    fallback: str | None = None
    elapsed_ms: int = 0
    # Structured LLM judge output retained even in shadow/reject paths so
    # deterministic top vs Flash suggestion can be compared offline.
    llm_selected_backend: str | None = None
    llm_confidence: float | None = None
    llm_required_capabilities: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {
            "version": "ir-routing-v1",
            "selected_backend": self.selected_backend,
            "source": self.source,
            "confidence": self.confidence,
            "plan_fingerprint": self.plan_fingerprint,
            "candidates": [item.as_dict() for item in self.candidates],
            "reasons": list(self.reasons),
            "llm_invoked": self.llm_invoked,
            "llm_accepted": self.llm_accepted,
            "fallback": self.fallback,
            "elapsed_ms": self.elapsed_ms,
            "llm_selected_backend": self.llm_selected_backend,
            "llm_confidence": self.llm_confidence,
            "llm_required_capabilities": list(self.llm_required_capabilities),
        }
