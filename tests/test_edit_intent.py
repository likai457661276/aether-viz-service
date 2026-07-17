"""Tests for deterministic edit intent satisfaction checks."""

from __future__ import annotations

from aetherviz_service.aetherviz.edit.intent import (
    IntentCheck,
    build_intent_guard,
    evaluate_edit_intent,
)
from aetherviz_service.aetherviz.edit.runtime_prepair import combine_candidate_guards
from aetherviz_service.aetherviz.tools.function_patch import extract_named_functions


def _baseline() -> str:
    return """<!DOCTYPE html><html><head><style>#play{font-size:12px;color:#111}.label{color:#fff}</style></head>
<body>
<main data-role="main-visual">
  <button id="play" data-role="control">播放</button>
  <span class="label">旧说明</span>
</main>
<script id="widget-config" type="application/json">{"type":"simulation","defaults":{"speed":1}}</script>
<script>
function play(){window.started=true}
function deriveState(s){return s}
</script>
</body></html>"""


def test_html_must_differ_and_text_contains() -> None:
    baseline = _baseline()
    candidate = baseline.replace("旧说明", "新说明").replace("12px", "16px")
    evaluation = evaluate_edit_intent(
        baseline_html=baseline,
        candidate_html=candidate,
        change_checks=(
            IntentCheck(id="c1", kind="html_must_differ", group="change"),
            IntentCheck(
                id="c2",
                kind="text_contains",
                selector=".label",
                expected="新说明",
                group="change",
            ),
            IntentCheck(
                id="c3",
                kind="css_declaration",
                selector="#play",
                property="font-size",
                expected="16px",
                group="change",
            ),
        ),
    )
    assert evaluation.ok
    assert evaluation.summary == "intent_ok"


def test_css_declaration_accepts_grouped_selector_and_inline_style() -> None:
    baseline = _baseline()
    grouped = baseline.replace("#play{font-size:12px", "#play,.secondary{font-size:16px")
    inline = baseline.replace('id="play"', 'id="play" style="font-size:16px"')
    check = IntentCheck(
        id="c_css",
        kind="css_declaration",
        selector="#play",
        property="font-size",
        expected="16px",
        group="change",
    )

    assert evaluate_edit_intent(
        baseline_html=baseline,
        candidate_html=grouped,
        change_checks=(check,),
    ).ok
    assert evaluate_edit_intent(
        baseline_html=baseline,
        candidate_html=inline,
        change_checks=(check,),
    ).ok


def test_function_body_changed_and_preserve() -> None:
    baseline = _baseline()
    play_hash = extract_named_functions(baseline)["play"][0].source_hash
    candidate = baseline.replace(
        "function play(){window.started=true}",
        "function play(){window.started=true;window.playState='playing'}",
    )
    evaluation = evaluate_edit_intent(
        baseline_html=baseline,
        candidate_html=candidate,
        change_checks=(
            IntentCheck(
                id="c_fn",
                kind="function_body_changed",
                function="play",
                group="change",
            ),
        ),
        preserve_checks=(
            IntentCheck(
                id="p_derive",
                kind="function_body_unchanged",
                function="deriveState",
                group="preserve",
            ),
            IntentCheck(id="p_type", kind="widget_type_unchanged", group="preserve"),
        ),
    )
    assert evaluation.ok
    assert extract_named_functions(candidate)["play"][0].source_hash != play_hash


def test_unchanged_candidate_fails_hard() -> None:
    baseline = _baseline()
    evaluation = evaluate_edit_intent(
        baseline_html=baseline,
        candidate_html=baseline,
        change_checks=(IntentCheck(id="c1", kind="html_must_differ", group="change"),),
    )
    assert not evaluation.ok
    assert "html_unchanged" in evaluation.summary
    assert evaluation.as_guard_errors()


def test_soft_failure_does_not_block() -> None:
    baseline = _baseline()
    candidate = baseline.replace("旧说明", "新说明")
    evaluation = evaluate_edit_intent(
        baseline_html=baseline,
        candidate_html=candidate,
        change_checks=(
            IntentCheck(id="c1", kind="html_must_differ", group="change"),
            IntentCheck(
                id="c_soft",
                kind="text_contains",
                selector=".label",
                expected="不存在的文案",
                severity="soft",
                group="change",
            ),
        ),
    )
    assert evaluation.ok
    assert len(evaluation.soft_failed) == 1


def test_numeric_and_widget_default_changed() -> None:
    baseline = _baseline()
    candidate = baseline.replace('"speed":1', '"speed":2').replace("12px", "18px")
    evaluation = evaluate_edit_intent(
        baseline_html=baseline,
        candidate_html=candidate,
        change_checks=(
            IntentCheck(id="c_num", kind="numeric_changed", selector="", group="change"),
            IntentCheck(
                id="c_widget",
                kind="widget_default_changed",
                property="defaults",
                group="change",
            ),
        ),
    )
    assert evaluation.ok


def test_intent_guard_and_combined_with_dom_prepair() -> None:
    baseline = _baseline()
    dirty = baseline.replace(
        "function play(){window.started=true}",
        "function play(selector){return document.querySelector(selector)}"
        "document.querySelectorAll('button').forEach(el=>play(el))",
    )
    candidate = baseline.replace("旧说明", "新说明")

    intent_guard = build_intent_guard(
        baseline_html=baseline,
        change_checks=(IntentCheck(id="c1", kind="html_must_differ", group="change"),),
    )
    assert intent_guard(candidate) == []
    assert intent_guard(baseline)

    def dom_guard(html: str) -> list[str]:
        from aetherviz_service.aetherviz.contracts.validation.dom_api_contract import (
            find_dom_element_selector_mismatches,
        )

        return (
            ["edit_runtime_error_still_present:dom_element_used_as_selector"]
            if find_dom_element_selector_mismatches(html)
            else []
        )

    combined = combine_candidate_guards(dom_guard, intent_guard)
    assert combined is not None
    assert combined(candidate) == []
    assert "edit_runtime_error_still_present" in combined(dirty)[0]


def test_retry_evidence_lists_failed_hard_checks() -> None:
    baseline = _baseline()
    evaluation = evaluate_edit_intent(
        baseline_html=baseline,
        candidate_html=baseline,
        change_checks=(IntentCheck(id="c1", kind="html_must_differ", group="change", rationale="必须变化"),),
        preserve_checks=(IntentCheck(id="p1", kind="widget_type_unchanged", group="preserve"),),
    )
    evidence = evaluation.retry_evidence()
    assert "id=c1" in evidence
    assert "kind=html_must_differ" in evidence
    assert "请针对失败 hard checks 修正" in evidence
