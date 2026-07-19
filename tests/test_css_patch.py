from __future__ import annotations

from aetherviz_service.aetherviz.tools.css_patch import (
    apply_css_rule_replacements,
    describe_target_css_rules,
    extract_named_css_rules,
)


def _html() -> str:
    return """<!DOCTYPE html><html><head><style>
#play { font-size: 12px; color: red; }
.label { color: #fff; }
</style></head><body><button id="play">播放</button></body></html>"""


def test_extract_named_css_rules_indexes_unique_selectors() -> None:
    rules = extract_named_css_rules(_html())
    assert "#play" in rules
    assert len(rules["#play"]) == 1
    assert "font-size" in rules["#play"][0].source
    assert rules["#play"][0].source_hash


def test_apply_css_rule_replacements_hash_guarded() -> None:
    html = _html()
    descriptions = describe_target_css_rules(html, ("#play",))
    assert len(descriptions) == 1
    patched = apply_css_rule_replacements(
        html,
        [
            {
                "selector": "#play",
                "source_hash": descriptions[0]["source_hash"],
                "replacement": "#play { font-size: 18px; color: red; }",
            }
        ],
        allowed_selectors=("#play",),
        allowed_targets=(("#play", descriptions[0]["source_hash"]),),
    )
    assert patched.applied == ("#play",)
    assert "font-size: 18px" in patched.html
    assert "color: red" in patched.html


def test_apply_css_rule_replacements_rejects_hash_mismatch() -> None:
    html = _html()
    patched = apply_css_rule_replacements(
        html,
        [
            {
                "selector": "#play",
                "source_hash": "deadbeef",
                "replacement": "#play { font-size: 18px; }",
            }
        ],
        allowed_selectors=("#play",),
        allowed_targets=(("#play", "deadbeef"),),
    )
    assert patched.applied == ()
    assert any(error.startswith("source_hash_mismatch") for error in patched.errors)
