from __future__ import annotations

from aetherviz_service.aetherviz.edit.diagnosis import EditDiagnosis
from aetherviz_service.aetherviz.edit.intent import IntentCheck
from aetherviz_service.aetherviz.edit.spec import EditOperation
from aetherviz_service.aetherviz.edit.strategy import (
    complexity_score,
    route_edit_strategy,
    strategy_ladder_from,
    upgrade_strategy,
)


def _base_diagnosis(**overrides) -> EditDiagnosis:
    payload = {
        "intent": "edit",
        "scope": "business_html",
        "strategy": "full_html_regeneration",
        "problem": "test",
        "confidence": 0.9,
        "change_checks": (
            IntentCheck(
                id="c1",
                kind="html_must_differ",
                severity="hard",
                baseline_binding="must_differ",
                group="change",
            ),
        ),
    }
    payload.update(overrides)
    return EditDiagnosis(**payload)


def test_complexity_score_formula() -> None:
    score = complexity_score(
        targets=[{"kind": "css"}, {"kind": "dom"}],
        impact_areas=("css", "animation", "events"),
        operations=(),
    )
    # 2*1 + 3*2 + 2*3 + 0*5 = 2+6+6 = 14
    assert score == 14


def test_route_prefers_deterministic_for_low_complexity_bindable_ops() -> None:
    diagnosis = _base_diagnosis(
        operations=(
            EditOperation(
                type="replace_text",
                selector="#play-animation",
                value="开始",
            ),
        ),
        impact_areas=("dom",),
        targets=(
            {
                "kind": "dom",
                "selector": "#play-animation",
                "function": "",
                "source_hash": "",
                "evidence": "",
                "confidence": 1.0,
            },
        ),
    )
    html = "<button id='play-animation'>播放</button>"
    strategy, route = route_edit_strategy(diagnosis=diagnosis, business_html=html)
    assert strategy == "deterministic_patch"
    assert route["operations_bindable"] is True
    assert route["reason"] == "operations_bindable"


def test_route_rejects_partial_deterministic_coverage_for_multiple_requirements() -> None:
    diagnosis = _base_diagnosis(
        change_requirements=("把按钮文案改为开始", "把动画速度提高一倍"),
        operations=(
            EditOperation(
                type="replace_text",
                selector="#play-animation",
                value="开始",
            ),
        ),
        impact_areas=("dom", "animation"),
        targets=(
            {
                "kind": "dom",
                "selector": "#play-animation",
                "function": "",
                "source_hash": "",
                "evidence": "",
                "confidence": 1.0,
            },
        ),
    )

    strategy, route = route_edit_strategy(
        diagnosis=diagnosis,
        business_html="<button id='play-animation'>播放</button>",
    )

    assert strategy != "deterministic_patch"
    assert route["operations_bindable"] is True
    assert route["operations_cover_requirements"] is False


def test_route_falls_back_to_full_for_high_complexity() -> None:
    diagnosis = _base_diagnosis(
        impact_areas=("dom", "css", "state", "render", "events", "animation", "runtime"),
        targets=tuple(
            {
                "kind": "function",
                "selector": "",
                "function": f"f{i}",
                "source_hash": "",
                "evidence": "",
                "confidence": 0.5,
            }
            for i in range(4)
        ),
    )
    strategy, route = route_edit_strategy(diagnosis=diagnosis, business_html="<html></html>")
    assert strategy == "full_html_regeneration"
    assert route["complexity_score"] > 8


def test_strategy_ladder_and_upgrade() -> None:
    assert strategy_ladder_from("deterministic_patch") == (
        "deterministic_patch",
        "scoped_model_patch",
        "full_html_regeneration",
    )
    assert upgrade_strategy("deterministic_patch") == "scoped_model_patch"
    assert upgrade_strategy("full_html_regeneration") is None
