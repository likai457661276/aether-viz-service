from __future__ import annotations

from bs4 import BeautifulSoup

from aetherviz_service.aetherviz.edit.targeting import (
    build_role_hints,
    infer_roles_from_instruction,
    resolve_role_selector,
)


def _html() -> str:
    return """<!DOCTYPE html><html><body>
<div id="aetherviz-stage"><div data-role="main-visual"></div></div>
<button id="play-animation">播放</button>
<section data-region="caption">说明文字</section>
<span data-edit-role="point-label" data-edit-entity="point-a">A</span>
</body></html>"""


def test_resolve_role_selector_prefers_existing_stable_id() -> None:
    soup = BeautifulSoup(_html(), "html.parser")
    assert resolve_role_selector("play-control", soup) == "#play-animation"
    assert resolve_role_selector("primary-visual", soup) == "[data-role='main-visual']"
    assert resolve_role_selector("explanation-panel", soup) == "[data-region='caption']"


def test_infer_roles_from_instruction_keywords() -> None:
    assert "play-control" in infer_roles_from_instruction("把播放按钮放大一点")
    assert "primary-visual" in infer_roles_from_instruction("主视觉太小了")


def test_build_role_hints_includes_edit_role_markers() -> None:
    soup = BeautifulSoup(_html(), "html.parser")
    hints = build_role_hints(soup, instruction="把播放按钮调大")
    roles = {item["role"]: item for item in hints}
    assert roles["play-control"]["present"] is True
    assert roles["play-control"]["instruction_match"] is True
    assert roles["point-label"]["selector"] == "[data-edit-role='point-label']"
    assert roles["point-label"]["entity"] == "point-a"
