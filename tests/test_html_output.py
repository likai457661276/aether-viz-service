"""HTML output extraction and truncation-recovery tests."""

from __future__ import annotations

import pytest

from aetherviz_service.aetherviz.contracts.html_output import (
    AetherVizInteractiveHtmlError,
    parse_interactive_html,
)
from aetherviz_service.aetherviz.contracts.validation.js_checker import check_inline_javascript

TRUNCATED_MID_SWITCH_CASE = """<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>测试</title></head>
<body>
<div id="aetherviz-stage"></div>
<script>
var state = { progress: 0, playing: false };
function updateVisualization() {
  var p = state.progress;
  document.getElementById('aetherviz-stage').textContent = 'p=' + p;
}
window.addEventListener('message', function (event) {
  var data = event.data || {};
  switch (data.type) {
    case 'SET_WIDGET_STATE':
      Object.assign(state, data.state);
      updateVisualization();
      break;
    case 'REVEAL_ELEMENT':
"""

TRUNCATED_BETWEEN_STATEMENTS = """<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>测试</title></head>
<body>
<div id="aetherviz-stage"></div>
<script>
var state = { progress: 0 };
function tick() {
  state.progress = state.progress + 1;
  if (state.progress > 100) {
    state.progress = 0;
  }
"""


def test_parse_interactive_html_closes_truncated_script_instead_of_raising() -> None:
    """A model output cut off mid <script> must be stitched, not hard-failed.

    Previously this raised AetherVizInteractiveHtmlError immediately, killing the whole
    generate workflow before the existing validation/repair pipeline ever ran.
    """
    result = parse_interactive_html(TRUNCATED_MID_SWITCH_CASE)

    lower = result.lower()
    assert lower.rstrip().endswith("</html>")
    assert "</script>" in lower
    assert "</body>" in lower


def test_parse_interactive_html_recovers_syntactically_valid_js_when_truncated_cleanly() -> None:
    """When truncation happens between complete statements, the brace-balancer should
    yield syntactically valid JS so the page can pass validation without needing a repair pass.
    """
    result = parse_interactive_html(TRUNCATED_BETWEEN_STATEMENTS)

    report = check_inline_javascript(result)

    assert report["ok"] is True


def test_parse_interactive_html_truncated_script_still_flows_into_js_validation() -> None:
    """Even when the balancer cannot fully repair a truncation (e.g. inside an unclosed
    function call), it must not raise - the resulting syntax error should surface through
    the normal validation report so the existing repair loop can fix it.
    """
    result = parse_interactive_html(TRUNCATED_MID_SWITCH_CASE)

    report = check_inline_javascript(result)

    assert report["ok"] is False
    assert report["errors"][0]["type"] == "js_syntax"


def test_parse_interactive_html_still_rejects_empty_output() -> None:
    with pytest.raises(AetherVizInteractiveHtmlError):
        parse_interactive_html("")


def test_parse_interactive_html_still_rejects_output_without_html_markers() -> None:
    with pytest.raises(AetherVizInteractiveHtmlError):
        parse_interactive_html("这是一段没有 HTML 标记的纯文本输出")
