"""Server-owned layout contract and deterministic HTML assembly."""

from __future__ import annotations

import html as html_lib
import json
import re
from typing import Any

from bs4 import BeautifulSoup, Tag

LAYOUT_CONTRACT_VERSION = "math-shell-v1"

LAYOUT_CONTRACT_CSS = r"""
<style data-aetherviz-layout-contract="math-shell-v1">
:root{--av-brand:#2d4f41;--av-brand-strong:#1d3a2f;--av-accent:#10b981;--av-soft:#ecfdf5;--av-canvas:#f6f8f5;--av-paper:#fff;--av-text:#1e332b;--av-muted:#52665e;--av-border:rgba(45,79,65,.14);--av-gap:clamp(10px,1.5vw,18px);--av-radius:14px}
html,body{width:100%;height:100%;margin:0;overflow:hidden}body{font-family:PingFang SC,Microsoft YaHei,Noto Sans SC,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:var(--av-canvas);color:var(--av-text)}
#aetherviz-app-shell{height:100dvh;box-sizing:border-box;display:grid;grid-template-columns:minmax(0,1fr) clamp(260px,28vw,360px);grid-template-rows:auto minmax(0,1fr) auto;grid-template-areas:"header header" "stage inspector" "status inspector";gap:var(--av-gap);padding:clamp(12px,2vw,24px);overflow:hidden}
#aetherviz-app-shell>*{min-width:0;min-height:0}.av-header{grid-area:header;display:flex;align-items:flex-start;justify-content:space-between;gap:16px}.av-title{margin:0;font-size:clamp(20px,2.4vw,30px);line-height:1.2;color:var(--av-brand-strong)}.av-goal{margin:6px 0 0;color:var(--av-muted);font-size:14px;line-height:1.45}.av-objectives{max-width:min(46vw,620px);font-size:13px;color:var(--av-muted)}.av-objectives ul{display:flex;gap:8px 18px;flex-wrap:wrap;margin:0;padding-left:18px}
#aetherviz-stage{grid-area:stage;position:relative;display:grid;place-items:center;min-width:0;min-height:260px;overflow:hidden;background:var(--av-paper);border:1px solid var(--av-border);border-radius:var(--av-radius);box-shadow:0 8px 28px rgba(29,58,47,.07)}#aetherviz-stage>[data-role="main-visual"],#aetherviz-stage>svg,#aetherviz-stage>canvas{display:block;max-width:100%;max-height:100%;width:100%;height:100%;min-width:0;min-height:0}#aetherviz-stage svg{overflow:visible}#aetherviz-stage canvas{object-fit:contain}
.av-inspector{grid-area:inspector;display:grid;grid-template-rows:auto auto minmax(0,1fr);gap:12px;overflow:hidden}.av-panel{box-sizing:border-box;background:var(--av-paper);border:1px solid var(--av-border);border-radius:var(--av-radius);padding:14px;min-width:0}.av-primary-controls{overflow:auto;scrollbar-gutter:stable}.av-primary-controls .control-panel,.av-primary-controls>[data-region="controls"]{display:flex;flex-wrap:wrap;align-items:center;gap:10px}.av-primary-controls input[type="range"]{min-width:120px;flex:1}.av-primary-controls button,.av-primary-controls input,.av-primary-controls select{min-height:44px;font:inherit}.av-details{overflow:auto;scrollbar-gutter:stable}.av-details:empty{display:none}.av-details>[data-region="teaching-flow"]{margin-top:12px}
.av-status{grid-area:status;display:grid;grid-template-columns:minmax(0,1fr) minmax(180px,.7fr);gap:var(--av-gap);align-items:stretch}.av-caption,.av-formula{min-width:0;overflow:auto;scrollbar-gutter:stable}.av-caption{font-size:14px;line-height:1.55}.av-formula{font-variant-numeric:tabular-nums;white-space:normal}.av-empty{color:var(--av-muted);font-size:13px}
@media(max-width:959px){#aetherviz-app-shell{grid-template-columns:minmax(0,1fr);grid-template-rows:auto minmax(240px,1fr) auto auto;grid-template-areas:"header" "stage" "status" "inspector";overflow:auto}.av-header{display:block}.av-objectives{max-width:none;margin-top:8px}.av-inspector{display:block;overflow:visible}.av-inspector>.av-panel{margin-top:10px}.av-details{max-height:32dvh}.av-primary-controls{overflow:visible}}
@media(max-width:599px){#aetherviz-app-shell{height:100dvh;padding:10px;gap:10px;grid-template-rows:auto clamp(240px,45dvh,420px) auto auto}.av-goal{display:none}.av-objectives li:nth-child(n+3){display:none}.av-status{grid-template-columns:minmax(0,1fr)}.av-formula{max-height:92px}.av-primary-controls .control-panel,.av-primary-controls>[data-region="controls"]{display:grid;grid-template-columns:repeat(2,minmax(0,1fr))}.av-primary-controls input[type="range"]{width:100%;min-width:0}.av-details{max-height:28dvh}}
@media(prefers-reduced-motion:reduce){*,*::before,*::after{scroll-behavior:auto!important;animation-duration:.01ms!important;animation-iteration-count:1!important;transition-duration:.01ms!important}}
</style>
"""


def assemble_layout_contract(html: str, plan: dict[str, Any] | None = None) -> str:
    """Rebuild the body into the canonical shell while preserving business content.

    The model may author SVG/Canvas, controls, explanatory regions and scripts,
    but cannot determine the final page grid, region order or scroll ownership.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    if soup.html is None:
        soup = BeautifulSoup(f"<!DOCTYPE html><html><head></head><body>{html}</body></html>", "html.parser")
    if soup.head is None:
        soup.html.insert(0, soup.new_tag("head"))
    if soup.body is None:
        soup.html.append(soup.new_tag("body"))
    assert soup.head is not None and soup.body is not None

    for old in soup.select('[data-aetherviz-layout-contract], [data-aetherviz-layout-guard="true"]'):
        old.decompose()
    for style in soup.find_all("style"):
        # Business styles may describe slot contents, but cannot use !important
        # to outrank the server-owned shell injected at the end of <head>.
        style.string = re.sub(r"\s*!\s*important\b", "", style.get_text(), flags=re.IGNORECASE)

    scripts = [node.extract() for node in list(soup.body.find_all("script"))]
    stage = _extract_first(soup.body, "#aetherviz-stage")
    objectives = _extract_first(soup.body, '[data-region="learning-goal"], .learning-objectives')
    caption = _extract_first(soup.body, '[data-region="caption"], .animation-caption, #animation-caption')
    formula = _extract_first(soup.body, '[data-region="formula"], .formula, .katex-target')
    teaching_flow = _extract_first(soup.body, '[data-region="teaching-flow"], .teaching-flow, .storyboard')
    existing_secondary = _extract_first(soup.body, '[data-region="secondary-controls"]')
    controls = _extract_first(soup.body, '[data-region="controls"], .control-panel, .controls')
    if controls is None:
        control_nodes = [
            node.extract()
            for node in soup.body.select(
                "#play-animation, #pause-animation, #reset-animation, input, select, button[data-var]"
            )
        ]
        if control_nodes:
            controls_soup = BeautifulSoup('<div class="control-panel" data-region="controls"></div>', "html.parser")
            controls = controls_soup.div
            assert controls is not None
            for node in control_nodes:
                controls.append(node)
    secondary_controls: list[Tag] = []
    if controls is not None:
        secondary_controls = [
            node.extract()
            for node in controls.select('[data-control-priority="secondary"]')
            if isinstance(node, Tag)
        ]
    if existing_secondary is not None:
        secondary_controls.extend(
            child.extract() for child in list(existing_secondary.children) if isinstance(child, Tag)
        )
        existing_secondary.decompose()

    plan = plan if isinstance(plan, dict) else {}
    shell = BeautifulSoup(_shell_markup(plan), "html.parser")
    shell_root = shell.select_one("#aetherviz-app-shell")
    assert shell_root is not None

    target_stage = shell_root.select_one("#aetherviz-stage")
    assert target_stage is not None
    if stage is not None:
        _move_children(stage, target_stage)
        for key, value in stage.attrs.items():
            if key not in {"id", "class", "data-region"}:
                target_stage.attrs.setdefault(key, value)
    else:
        placeholder = soup.new_tag("div", attrs={"data-role": "main-visual", "class": "av-empty"})
        placeholder.string = "主视觉正在初始化"
        target_stage.append(placeholder)

    if objectives is not None:
        objectives.decompose()
    _fill_slot(shell_root.select_one(".av-primary-controls"), controls)
    _fill_slot(shell_root.select_one(".av-caption"), caption, "操作参数并观察主视觉变化。")
    _fill_slot(shell_root.select_one(".av-formula"), formula, "关键关系将在此同步显示。")
    details = shell_root.select_one(".av-details")
    _fill_slot(details, teaching_flow)
    if details is not None and secondary_controls:
        secondary = BeautifulSoup(
            '<section class="av-secondary-controls" data-region="secondary-controls"></section>',
            "html.parser",
        ).section
        assert secondary is not None
        for node in secondary_controls:
            secondary.append(node)
        details.append(secondary)

    soup.body.clear()
    soup.body["data-layout-contract"] = LAYOUT_CONTRACT_VERSION
    soup.body.append(shell_root)
    for script in scripts:
        soup.body.append(script)
    soup.head.append(BeautifulSoup(LAYOUT_CONTRACT_CSS, "html.parser").style)
    return "<!DOCTYPE html>\n" + str(soup.html)


def _extract_first(root: Tag, selector: str) -> Tag | None:
    node = root.select_one(selector)
    return node.extract() if isinstance(node, Tag) else None


def _move_children(source: Tag, target: Tag) -> None:
    for child in list(source.contents):
        target.append(child.extract())


def _fill_slot(target: Tag | None, source: Tag | None, fallback: str = "") -> None:
    if target is None:
        return
    if source is not None:
        target.append(source)
    elif fallback:
        empty = BeautifulSoup(f'<span class="av-empty">{html_lib.escape(fallback)}</span>', "html.parser").span
        if empty is not None:
            target.append(empty)


def _shell_markup(plan: dict[str, Any]) -> str:
    title = html_lib.escape(str(plan.get("title") or "AI互动实验"))
    goal = html_lib.escape(str(plan.get("goal") or "观察、操作并解释关键关系"))
    objectives = (
        plan.get("learning_objectives")
        or plan.get("objectives")
        or plan.get("key_points")
        or []
    )
    if not isinstance(objectives, list):
        objectives = []
    items = "".join(f"<li>{html_lib.escape(str(item))}</li>" for item in objectives[:3])
    if not items:
        items = f"<li>{goal}</li>"
    contract = html_lib.escape(json.dumps(layout_contract_for_plan(plan), ensure_ascii=False, separators=(",", ":")))
    return f"""<main id="aetherviz-app-shell" data-region="app-shell" data-layout-version="{LAYOUT_CONTRACT_VERSION}" data-layout-contract-json="{contract}">
<header class="av-header" data-layout-slot="header"><div><h1 class="av-title">{title}</h1><p class="av-goal">{goal}</p></div><section class="av-objectives learning-objectives" data-region="learning-goal"><ul>{items}</ul></section></header>
<section id="aetherviz-stage" data-region="stage" data-layout-slot="stage"></section>
<aside class="av-inspector" data-layout-slot="inspector"><section class="av-panel av-primary-controls" data-layout-slot="primary-controls"></section><section class="av-panel av-details" data-layout-slot="details"></section></aside>
<section class="av-status" data-layout-slot="status"><div class="av-panel av-caption" data-region="caption"></div><div class="av-panel av-formula" data-region="formula"></div></section>
</main>"""


def layout_contract_for_plan(plan: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return the stable, topic-independent presentation contract."""
    source = plan if isinstance(plan, dict) else {}
    controls = source.get("controls") if isinstance(source.get("controls"), list) else []
    return {
        "version": LAYOUT_CONTRACT_VERSION,
        "mode": "stage_inspector",
        "regions": ["header", "stage", "primary-controls", "status", "details"],
        "presentation": {
            "primary_control_limit": min(max(len(controls), 1), 3),
            "visible_objective_limit": 3,
            "mobile_visible_objective_limit": 2,
            "details_disclosure": "scroll",
        },
        "invariants": ["server_owned_grid", "no_page_scroll_wide", "stage_priority", "internal_scroll"],
    }
