from __future__ import annotations

from aetherviz_service.aetherviz.edit.spec import (
    EDIT_OPERATION_SCHEMA,
    EditOperation,
    normalize_operations,
    operations_are_deterministic,
)
from aetherviz_service.aetherviz.edit.targeting import resolve_role_selector


def _html() -> str:
    return """<!DOCTYPE html><html><head><style>#play-animation{font-size:12px}</style></head>
<body>
<button id="play-animation">播放</button>
<span class="label">说明</span>
<script id="widget-config" type="application/json">{"type":"simulation","speed":1}</script>
<script>function play(){ const duration = 2; }</script>
</body></html>"""


def test_normalize_operations_keeps_bindable_text_and_css_ops() -> None:
    ops, dropped = normalize_operations(
        [
            {
                "type": "replace_text",
                "selector": "#play-animation",
                "role": "",
                "property": "",
                "attribute": "",
                "function": "",
                "value_mode": "absolute",
                "value": "开始",
                "ratio": None,
                "degree": "",
            },
            {
                "type": "set_css_declaration",
                "selector": "#play-animation",
                "role": "",
                "property": "font-size",
                "attribute": "",
                "function": "",
                "value_mode": "relative",
                "value": "",
                "ratio": 1.5,
                "degree": "",
            },
            {
                "type": "replace_text",
                "selector": "#missing",
                "role": "",
                "property": "",
                "attribute": "",
                "function": "",
                "value_mode": "absolute",
                "value": "x",
                "ratio": None,
                "degree": "",
            },
        ],
        business_html=_html(),
    )
    assert len(ops) == 2
    assert ops[0].type == "replace_text"
    assert ops[1].type == "set_css_declaration"
    assert any("selector_missing" in item for item in dropped)
    assert operations_are_deterministic(ops)


def test_normalize_operations_resolves_role_alias() -> None:
    ops, dropped = normalize_operations(
        [
            {
                "type": "replace_text",
                "selector": "",
                "role": "play-control",
                "property": "",
                "attribute": "",
                "function": "",
                "value_mode": "absolute",
                "value": "播放中",
                "ratio": None,
                "degree": "",
            }
        ],
        business_html=_html(),
        resolve_role_selector=resolve_role_selector,
    )
    assert dropped == ()
    assert len(ops) == 1
    assert ops[0].selector == "#play-animation"


def test_edit_operation_public_dict() -> None:
    op = EditOperation(type="remove_element", selector=".label")
    payload = op.public_dict()
    assert payload["type"] == "remove_element"
    assert payload["selector"] == ".label"


def test_operation_schema_allows_null_ratio() -> None:
    ratio_schema = EDIT_OPERATION_SCHEMA["properties"]["ratio"]
    assert {item["type"] for item in ratio_schema["anyOf"]} == {"number", "null"}


def test_normalize_numeric_operation_requires_named_property() -> None:
    operations, dropped = normalize_operations(
        [
            {
                "type": "replace_numeric_literal",
                "selector": "",
                "role": "",
                "property": "",
                "attribute": "",
                "function": "play",
                "value_mode": "relative",
                "value": "",
                "ratio": 2,
                "degree": "",
            }
        ],
        business_html=_html(),
    )

    assert operations == ()
    assert any("missing_property" in item for item in dropped)
