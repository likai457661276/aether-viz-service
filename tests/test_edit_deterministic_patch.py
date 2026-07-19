from __future__ import annotations

from aetherviz_service.aetherviz.edit.patch.deterministic import (
    apply_deterministic_operations,
    resolve_relative_value,
)
from aetherviz_service.aetherviz.edit.spec import EditOperation


def _html() -> str:
    return """<!DOCTYPE html>
<html><head><style>
#play-animation { font-size: 12px; }
:root { --speed: 1s; }
</style></head>
<body>
<button id="play-animation">播放</button>
<span class="label">旧说明</span>
<script id="widget-config" type="application/json">{"type":"simulation","speed":2}</script>
<script>function play(){ const delay = 1; const duration = 2; }</script>
</body></html>"""


def test_resolve_relative_value_scales_px_and_duration() -> None:
    assert resolve_relative_value("12px", ratio=1.5) == "18px"
    assert resolve_relative_value("2s", degree="moderate") == "2.4s"


def test_apply_replace_text_and_css_relative() -> None:
    result = apply_deterministic_operations(
        _html(),
        (
            EditOperation(type="replace_text", selector="#play-animation", value="开始"),
            EditOperation(
                type="set_css_declaration",
                selector="#play-animation",
                property="font-size",
                value_mode="relative",
                ratio=1.5,
            ),
        ),
    )
    assert "replace_text:#play-animation" in result.applied
    assert "set_css_declaration:#play-animation" in result.applied
    assert "开始" in result.html
    assert "font-size: 18px" in result.html or "font-size:18px" in result.html.replace(" ", "")


def test_apply_update_widget_default_and_remove_element() -> None:
    result = apply_deterministic_operations(
        _html(),
        (
            EditOperation(
                type="update_widget_default",
                property="speed",
                value_mode="absolute",
                value="3",
            ),
            EditOperation(type="remove_element", selector=".label"),
        ),
    )
    assert result.unresolved == ()
    assert '"speed":3' in result.html or '"speed": 3' in result.html
    assert "旧说明" not in result.html


def test_apply_replace_numeric_literal_in_function() -> None:
    result = apply_deterministic_operations(
        _html(),
        (
            EditOperation(
                type="replace_numeric_literal",
                function="play",
                property="duration",
                value_mode="relative",
                degree="strong",
            ),
        ),
    )
    assert result.applied
    assert "3" in result.html  # 2 * 1.5
    assert "delay = 1" in result.html
    assert "duration = 3" in result.html


def test_replace_numeric_literal_rejects_missing_property() -> None:
    result = apply_deterministic_operations(
        _html(),
        (
            EditOperation(
                type="replace_numeric_literal",
                function="play",
                value_mode="relative",
                ratio=2,
            ),
        ),
    )

    assert result.applied == ()
    assert any("missing_property" in item for item in result.unresolved)
