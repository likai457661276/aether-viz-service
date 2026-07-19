"""Unit tests for table-driven generation prompt module selection."""

from __future__ import annotations

from aetherviz_service.aetherviz.generate.prompts import (
    REPRESENTATION_PROMPT_MIN_CONFIDENCE,
    REPRESENTATION_PROMPT_MODULES,
    resolve_generation_prompt_modules,
    system_prompt_for_interactive_type,
)


def _plan(
    *,
    interactive_type: str = "simulation",
    subject: str = "math",
    representation_type: str = "coordinate_graph",
    confidence: float = 0.8,
) -> dict:
    return {
        "interactive_type": interactive_type,
        "subject": subject,
        "knowledge_profile": {
            "representation_type": representation_type,
            "confidence": confidence,
        },
    }


def test_prompt_modules_apply_known_high_confidence_representation() -> None:
    selection = resolve_generation_prompt_modules(_plan())
    assert selection.subject_group == "math"
    assert selection.representation_applied is True
    assert selection.fallback_reason is None
    assert "坐标图表征" in selection.render()
    assert "数学语义补充" in selection.render()


def test_prompt_modules_fallback_on_low_confidence() -> None:
    selection = resolve_generation_prompt_modules(_plan(confidence=REPRESENTATION_PROMPT_MIN_CONFIDENCE - 0.01))
    assert selection.representation_applied is False
    assert selection.fallback_reason == "low_confidence"
    assert "坐标图表征" not in selection.render()
    assert "数学语义补充" in selection.render()


def test_prompt_modules_fallback_on_unknown_representation() -> None:
    selection = resolve_generation_prompt_modules(_plan(representation_type="not_a_real_type"))
    assert selection.representation_applied is False
    assert selection.fallback_reason == "unknown_representation"
    for module in REPRESENTATION_PROMPT_MODULES.values():
        assert module not in selection.render()


def test_prompt_modules_fallback_on_missing_representation() -> None:
    selection = resolve_generation_prompt_modules(_plan(representation_type=""))
    assert selection.fallback_reason == "missing_representation"
    assert selection.representation_applied is False


def test_system_prompt_uses_generic_base_for_unknown_interactive_type() -> None:
    prompt = system_prompt_for_interactive_type(_plan(interactive_type="unknown_widget"))
    assert "simulation 补充要求" not in prompt
    assert "自包含 interactive widget" in prompt
