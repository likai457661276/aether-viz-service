from __future__ import annotations

from aetherviz_service.aetherviz.edit.diff_report import build_edit_diff_report


def test_build_edit_diff_report_detects_dom_css_js_and_offline_placeholders() -> None:
    baseline = """<!DOCTYPE html><html><head><style>#play{font-size:12px}</style></head>
<body><button id="play">播放</button>
<script id="widget-config" type="application/json">{"type":"simulation","speed":1}</script>
<script>function play(){return 1}</script></body></html>"""
    candidate = """<!DOCTYPE html><html><head><style>#play{font-size:18px}</style></head>
<body><button id="play">开始</button>
<script id="widget-config" type="application/json">{"type":"simulation","speed":2}</script>
<script>function play(){return 2}</script></body></html>"""

    report = build_edit_diff_report(baseline, candidate)
    assert "#play" in report["dom"]["changed"] or report["dom"]["changed"]
    assert "#play" in report["css"]["changed_rules"]
    assert "play" in report["javascript"]["changed_functions"]
    assert "speed" in report["widget"]["defaults_changed"]
    assert report["widget"]["type_changed"] is False
    assert report["visual"] == {"computed": False, "reason": "offline_only"}
    assert report["runtime"] == {"computed": False, "reason": "offline_only"}
    assert 0 <= report["unrelated_change_ratio"] <= 1
