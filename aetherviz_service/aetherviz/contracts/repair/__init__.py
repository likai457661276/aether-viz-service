"""Deterministic and model repair helpers for the delivery pipeline."""

from aetherviz_service.aetherviz.contracts.repair.session import (
    CANDIDATE_FATAL_ERROR_TYPES,
    REPAIR_STRATEGY_ORDER,
    RepairSession,
    accept_hard_repair_candidate,
    error_signature,
)

__all__ = [
    "CANDIDATE_FATAL_ERROR_TYPES",
    "REPAIR_STRATEGY_ORDER",
    "RepairSession",
    "accept_hard_repair_candidate",
    "error_signature",
]
