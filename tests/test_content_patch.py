from __future__ import annotations

import json
from unittest.mock import MagicMock

from aetherviz_service.aetherviz.agents import edit_patch_agent
from aetherviz_service.aetherviz.agents.edit_patch_agent import EditPatchResult
from aetherviz_service.aetherviz.tools.content_patch import (
    apply_content_replacements,
    content_patch_causal_error,
    parse_css_declaration_edits,
    select_content_descriptions,
)
from aetherviz_service.aetherviz.tools.css_patch import parse_css_rules
from aetherviz_service.aetherviz.tools.edit_targeting import extract_edit_evidence
from aetherviz_service.aetherviz.tools.function_patch import select_edit_function_descriptions

SOURCE = """<!DOCTYPE html><html><head><style>#stage{display:none;color:red}</style></head>
<body><main id="stage" data-role="main-visual"><svg><circle r="4"></circle></svg></main>
<p data-region="caption">旧说明</p></body></html>"""


def test_select_content_descriptions_for_blank_visual() -> None:
    descriptions = select_content_descriptions(SOURCE, "动画图像默认空白，请正确显示")

    assert {item["kind"] for item in descriptions} == {"css_rule", "visual"}
    assert next(item for item in descriptions if item["kind"] == "css_rule")["selector"] == "#stage"


def test_apply_css_rule_replacement_requires_hash_and_preserves_selector() -> None:
    descriptions = select_content_descriptions(SOURCE, "动画图像默认空白，请正确显示")
    style = next(item for item in descriptions if item["kind"] == "css_rule")
    result = apply_content_replacements(
        SOURCE,
        [
            {
                "kind": "css_rule",
                "target_id": style["target_id"],
                "source_hash": style["source_hash"],
                "replacement": "#stage{display:grid;color:red}",
            }
        ],
        allowed_descriptions=descriptions,
    )

    assert result.errors == ()
    assert result.applied == (style["target_id"],)
    assert "display:grid" in result.html


def test_content_replacement_rejects_identity_change_and_script() -> None:
    descriptions = select_content_descriptions(SOURCE, "动画图像默认空白，请正确显示")
    visual = next(item for item in descriptions if item["kind"] == "visual")
    result = apply_content_replacements(
        SOURCE,
        [
            {
                "kind": "visual",
                "target_id": visual["target_id"],
                "source_hash": visual["source_hash"],
                "replacement": '<main id="other" data-role="main-visual"><script>alert(1)</script></main>',
            }
        ],
        allowed_descriptions=descriptions,
    )

    assert result.html == SOURCE
    assert result.applied == ()
    assert result.errors[0].startswith("content_script_not_allowed:")


def test_edit_agent_applies_structured_css_rule_patch(monkeypatch) -> None:
    descriptions = select_content_descriptions(SOURCE, "动画图像默认空白，请正确显示")
    style = next(item for item in descriptions if item["kind"] == "css_rule")
    response = json.dumps(
        {
            "replacements": [],
            "blocks": [
                {
                    "kind": "css_rule",
                    "target_id": style["target_id"],
                    "source_hash": style["source_hash"],
                    "replacement": "#stage{display:grid;color:red}",
                }
            ],
        }
    )

    class PatchModel:
        def stream(self, messages):
            yield MagicMock(
                content=response,
                response_metadata={"finish_reason": "stop"},
                usage_metadata={"input_tokens": 800, "output_tokens": 120},
            )

    monkeypatch.setattr(edit_patch_agent, "create_chat_model", lambda kind: PatchModel())
    result = next(
        item
        for item in edit_patch_agent._stream_edit_patch_impl(
            raw_html=SOURCE,
            instruction="动画图像默认空白，请正确显示",
            topic="动画",
        )
        if isinstance(item, EditPatchResult)
    )

    assert result.strategy == "structured_patch"
    assert result.applied_blocks == (style["target_id"],)
    assert result.output_tokens == 120
    assert "display:grid" in result.html


def test_style_candidates_do_not_crowd_out_visual_target() -> None:
    styles = "".join(f"<style>.style-{index}{{color:red}}</style>" for index in range(6))
    html = f'<html><head>{styles}</head><body><main data-role="main-visual"><svg></svg></main></body></html>'

    descriptions = select_content_descriptions(html, "动画图像空白，请正确显示")

    assert any(item["kind"] == "visual" for item in descriptions)
    assert sum(item["kind"] == "css_rule" for item in descriptions) <= 2


def test_explicit_selector_targets_second_visual_region() -> None:
    html = """<html><body>
<div id="first" data-role="main-visual"><svg></svg></div>
<div id="second" data-role="main-visual"><svg></svg></div>
</body></html>"""

    descriptions = select_content_descriptions(html, "请修改 #second 的颜色")

    visual = next(item for item in descriptions if item["kind"] == "visual")
    assert visual["selector"] == "#second"
    assert visual["score"] == 100
    assert any(value.startswith("explicit_selector") for value in visual["evidence"])


def test_validation_report_selector_is_used_as_targeting_evidence() -> None:
    html = '<html><body><div id="target">旧内容</div><div id="other">其他</div></body></html>'
    context = {"validation_report": {"errors": [{"type": "text_mismatch", "scope": "#target"}]}}

    descriptions = select_content_descriptions(html, "修复检查问题", context)

    target = next(item for item in descriptions if item["selector"] == "#target")
    assert target["score"] == 90
    assert target["region"] == "div"


def test_css_rule_replacement_rejects_selector_change() -> None:
    descriptions = select_content_descriptions(SOURCE, "请修改 #stage 的颜色")
    rule = next(item for item in descriptions if item["kind"] == "css_rule")

    result = apply_content_replacements(
        SOURCE,
        [
            {
                "kind": "css_rule",
                "target_id": rule["target_id"],
                "source_hash": rule["source_hash"],
                "replacement": ".other{display:grid;color:blue}",
            }
        ],
        allowed_descriptions=descriptions,
    )

    assert result.html == SOURCE
    assert result.errors[0].startswith("content_css_selector_mismatch:")


def test_dom_dependency_selects_function_that_references_target() -> None:
    html = """<html><body><div id="second" data-role="main-visual"></div><script>
function initializeSpecialView() {
  const mount = document.querySelector('#second');
  mount.replaceChildren(document.createElement('canvas'));
}
</script></body></html>"""
    blocks = select_content_descriptions(html, "请修复 #second 空白")
    selectors = tuple(item["selector"] for item in blocks if item["selector"])

    functions = select_edit_function_descriptions(
        html,
        "请修复 #second 空白",
        target_selectors=selectors,
    )

    assert {item["function"] for item in functions} == {"initializeSpecialView"}


def test_edit_evidence_is_bounded_to_supported_report_fields() -> None:
    evidence = extract_edit_evidence(
        "修复它",
        {
            "validation_report": {"errors": [{"scope": "#target"}]},
            "memory": {"secret": "must-not-be-included"},
        },
    )

    assert evidence.report_selectors == ("#target",)
    assert all("must-not-be-included" not in hint for hint in evidence.report_hints)


def test_nested_media_css_rule_can_be_targeted_and_replaced() -> None:
    html = """<html><head><style>
@media (max-width: 600px) { #stage { display:none; width:100%; } }
</style></head><body><main id="stage" data-role="main-visual"></main></body></html>"""
    descriptions = select_content_descriptions(html, "移动端 #stage 不显示")
    rule = next(item for item in descriptions if item["kind"] == "css_rule")

    result = apply_content_replacements(
        html,
        [
            {
                "kind": "css_rule",
                "target_id": rule["target_id"],
                "source_hash": rule["source_hash"],
                "replacement": "#stage { display:grid; width:100%; }",
            }
        ],
        allowed_descriptions=descriptions,
    )

    assert result.errors == ()
    assert "@media (max-width: 600px) { #stage { display:grid; width:100%; } }" in result.html


def test_text_color_css_patch_passes_composite_intent_causal_check() -> None:
    descriptions = select_content_descriptions(SOURCE, "把 #stage 的文字颜色改成蓝色")
    rule = next(item for item in descriptions if item["kind"] == "css_rule")
    after = SOURCE.replace("color:red", "color:blue")

    error = content_patch_causal_error(
        SOURCE,
        after,
        "把 #stage 的文字颜色改成蓝色",
        context=None,
        applied_descriptions=[rule],
        function_changed=False,
    )

    assert error is None


def test_css_parser_handles_complex_values_and_nested_grouping_rules() -> None:
    css = r'''/* { ignored } */
@layer demo {
  @supports selector(:has(*)) {
    @media (width > 500px) {
      #stage:is(.ready, [data-state="a;b"]) {
        --icon: "data:image/svg+xml,<svg>{x}</svg>";
        width: calc(100% - 2rem);
      }
    }
  }
}'''

    parsed = parse_css_rules(css)

    assert parsed.status == "exact"
    assert len(parsed.rules) == 1
    assert parsed.rules[0].selector.startswith("#stage:is")
    assert [value.split()[0] for value in parsed.rules[0].at_rule_path] == ["@layer", "@supports", "@media"]


def test_unsupported_css_uses_bounded_style_fallback() -> None:
    html = """<html><head><style>
@unknown-layout demo { #stage { color:red; } }
</style></head><body><main id="stage" data-role="main-visual"></main></body></html>"""

    descriptions = select_content_descriptions(html, "修改 #stage 的颜色")

    style = next(item for item in descriptions if item["kind"] == "style")
    assert style["parse_status"] == "unsupported"
    assert "style_block_fallback:unsupported" in style["evidence"]
    assert not any(item["kind"] == "css_rule" for item in descriptions)


def test_malformed_css_uses_bounded_style_fallback() -> None:
    html = """<html><head><style>#stage { color:red;</style></head>
<body><main id="stage" data-role="main-visual"></main></body></html>"""

    descriptions = select_content_descriptions(html, "修改 #stage 的颜色")

    style = next(item for item in descriptions if item["kind"] == "style")
    assert style["parse_status"] == "malformed"


def test_css_declaration_edit_updates_removes_and_adds_properties_transactionally() -> None:
    descriptions = select_content_descriptions(SOURCE, "修改 #stage 的样式")
    rule = next(item for item in descriptions if item["kind"] == "css_rule")

    result = apply_content_replacements(
        SOURCE,
        [],
        allowed_descriptions=descriptions,
        declaration_edits=[
            {
                "target_id": rule["target_id"],
                "source_hash": rule["source_hash"],
                "set": {"display": "grid", "background-color": "#fff"},
                "remove": ["color"],
            }
        ],
    )

    assert result.errors == ()
    assert result.operations == ("css_declarations",)
    assert "display:grid" in result.html
    assert "background-color:#fff" in result.html
    assert "color:red" not in result.html


def test_css_declaration_edit_rejects_external_url_and_rolls_back() -> None:
    descriptions = select_content_descriptions(SOURCE, "修改 #stage 的背景")
    rule = next(item for item in descriptions if item["kind"] == "css_rule")

    result = apply_content_replacements(
        SOURCE,
        [],
        allowed_descriptions=descriptions,
        declaration_edits=[
            {
                "target_id": rule["target_id"],
                "source_hash": rule["source_hash"],
                "set": {"background": "url(https://example.com/x.png)"},
                "remove": [],
            }
        ],
    )

    assert result.html == SOURCE
    assert result.applied == ()
    assert result.errors[0].startswith("css_declaration_unsafe_value:background:")


def test_duplicate_css_rules_are_addressed_by_source_span() -> None:
    html = """<html><head><style>#stage{color:red}#stage{color:red}</style></head>
<body><main id="stage" data-role="main-visual"></main></body></html>"""
    descriptions = select_content_descriptions(html, "修改 #stage 的颜色")
    rules = [item for item in descriptions if item["kind"] == "css_rule"]

    result = apply_content_replacements(
        html,
        [],
        allowed_descriptions=descriptions,
        declaration_edits=[
            {
                "target_id": rules[1]["target_id"],
                "source_hash": rules[1]["source_hash"],
                "set": {"color": "blue"},
                "remove": [],
            }
        ],
    )

    assert result.errors == ()
    assert result.html.count("color:red") == 1
    assert result.html.count("color:blue") == 1


def test_edit_agent_prefers_structured_css_declaration_operation(monkeypatch) -> None:
    descriptions = select_content_descriptions(SOURCE, "修改 #stage 的显示方式")
    rule = next(item for item in descriptions if item["kind"] == "css_rule")
    response = json.dumps(
        {
            "replacements": [],
            "blocks": [],
            "css_edits": [
                {
                    "target_id": rule["target_id"],
                    "source_hash": rule["source_hash"],
                    "set": {"display": "grid"},
                    "remove": [],
                }
            ],
        }
    )

    class PatchModel:
        def stream(self, messages):
            yield MagicMock(content=response, response_metadata={"finish_reason": "stop"})

    monkeypatch.setattr(edit_patch_agent, "create_chat_model", lambda kind: PatchModel())
    result = next(
        item
        for item in edit_patch_agent._stream_edit_patch_impl(
            raw_html=SOURCE,
            instruction="修改 #stage 的显示方式",
            topic="动画",
        )
        if isinstance(item, EditPatchResult)
    )

    assert result.applied_operations == ("css_declarations",)
    assert result.allow_full_html_fallback is False
    assert "display:grid" in result.html


def test_parse_css_declaration_edits_bounds_and_normalizes_payload() -> None:
    edits = parse_css_declaration_edits(
        '{"css_edits":[{"target_id":"x","source_hash":"h","set":{"color":"blue"},"remove":["display"]}]}'
    )

    assert edits == [
        {
            "target_id": "x",
            "source_hash": "h",
            "set": {"color": "blue"},
            "remove": ["display"],
        }
    ]


def test_successive_css_declaration_edits_retarget_current_source() -> None:
    first_descriptions = select_content_descriptions(SOURCE, "修改 #stage 的颜色")
    first_rule = next(item for item in first_descriptions if item["kind"] == "css_rule")
    first = apply_content_replacements(
        SOURCE,
        [],
        allowed_descriptions=first_descriptions,
        declaration_edits=[
            {
                "target_id": first_rule["target_id"],
                "source_hash": first_rule["source_hash"],
                "set": {"color": "blue"},
                "remove": [],
            }
        ],
    )

    second_descriptions = select_content_descriptions(first.html, "修改 #stage 的显示方式")
    second_rule = next(item for item in second_descriptions if item["kind"] == "css_rule")
    second = apply_content_replacements(
        first.html,
        [],
        allowed_descriptions=second_descriptions,
        declaration_edits=[
            {
                "target_id": second_rule["target_id"],
                "source_hash": second_rule["source_hash"],
                "set": {"display": "grid"},
                "remove": [],
            }
        ],
    )

    assert first.errors == ()
    assert second.errors == ()
    assert "color:blue" in second.html
    assert "display:grid" in second.html
    assert second_rule["target_id"] != first_rule["target_id"]
