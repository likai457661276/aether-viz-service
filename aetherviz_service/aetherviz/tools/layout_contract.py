"""Server-owned layout contract and deterministic HTML assembly."""

from __future__ import annotations

import html as html_lib
import json
import re
from typing import Any

from bs4 import BeautifulSoup, Tag

LAYOUT_CONTRACT_VERSION = "math-shell-v1"

_BUSINESS_STYLE_MARKER = "data-aetherviz-business-style"
_CSS_RULE_RE = re.compile(r"(?P<selectors>[^{}]+)\{(?P<body>[^{}]*)\}")
_RANGE_SELECTOR_RE = re.compile(r"input\s*\[\s*type\s*=\s*['\"]?range['\"]?\s*\]", re.IGNORECASE)
_SERVER_SELECTOR_RE = re.compile(
    r"(?:^|[\s>+~,:])(?:html|body)(?:$|[\s>+~.#[:])|"
    r"#aetherviz-app-shell\b|\.av-[A-Za-z0-9_-]*\b|"
    r"^\s*#aetherviz-stage(?:\[[^\]]+\])?\s*$|"
    r"^\s*\.control-panel\s*$|"
    r"^\s*\[data-region\s*=\s*['\"]?(?:stage|controls|caption|formula|teaching-flow)['\"]?\]"
    r"(?:\.[A-Za-z0-9_-]+)*\s*$",
    re.IGNORECASE,
)

LAYOUT_CONTRACT_CSS = r"""
<style data-aetherviz-layout-contract="math-shell-v1">
:root{--av-brand:#2d4f41;--av-brand-strong:#1d3a2f;--av-accent:#10b981;--av-soft:#ecfdf5;--av-canvas:#f6f8f5;--av-paper:#fff;--av-text:#1e332b;--av-muted:#52665e;--av-border:rgba(45,79,65,.14);--av-gap:clamp(10px,1.5vw,18px);--av-radius:14px}
html,body{width:100%;height:100%;margin:0;overflow:hidden}body{font-family:PingFang SC,Microsoft YaHei,Noto Sans SC,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:var(--av-canvas);color:var(--av-text)}
#aetherviz-app-shell{height:100dvh;box-sizing:border-box;display:grid;grid-template-columns:minmax(0,1fr) clamp(260px,28vw,360px);grid-template-rows:auto minmax(0,1fr) auto;grid-template-areas:"header header" "stage inspector" "status inspector";gap:var(--av-gap);padding:clamp(12px,2vw,24px);overflow:hidden}
#aetherviz-app-shell *,#aetherviz-app-shell *::before,#aetherviz-app-shell *::after{box-sizing:border-box}#aetherviz-app-shell>*{min-width:0;min-height:0}.av-header{grid-area:header;display:flex;align-items:flex-start;justify-content:space-between;gap:16px}.av-title{margin:0;font-size:clamp(20px,2.4vw,30px);line-height:1.2;color:var(--av-brand-strong)}.av-goal{margin:6px 0 0;color:var(--av-muted);font-size:14px;line-height:1.45}.av-objectives{max-width:min(46vw,620px);font-size:13px;color:var(--av-muted)}.av-objectives ul{display:flex;gap:8px 18px;flex-wrap:wrap;margin:0;padding-left:18px}
#aetherviz-stage{grid-area:stage;position:relative;display:grid;place-items:center;min-width:0;min-height:260px;overflow:hidden;background:var(--av-paper);border:1px solid var(--av-border);border-radius:var(--av-radius);box-shadow:0 8px 28px rgba(29,58,47,.07)}#aetherviz-stage>[data-role="main-visual"],#aetherviz-stage>svg,#aetherviz-stage>canvas{display:block;max-width:100%;max-height:100%;width:100%;height:100%;min-width:0;min-height:0}#aetherviz-stage svg{overflow:visible}#aetherviz-stage canvas{object-fit:contain}
.av-inspector{grid-area:inspector;display:grid;grid-template-rows:auto auto minmax(0,1fr);gap:12px;overflow:hidden}.av-panel{box-sizing:border-box;background:var(--av-paper);border:1px solid var(--av-border);border-radius:var(--av-radius);padding:14px;min-width:0}.av-primary-controls{overflow:auto;scrollbar-gutter:stable}.av-primary-controls>.control-panel,.av-primary-controls>[data-region="controls"]{display:flex;flex-flow:row wrap;align-items:flex-start;align-content:flex-start;gap:10px;width:100%;height:auto;min-height:0;max-height:none;margin:0;padding:0;border:0;border-radius:0;background:transparent;box-shadow:none;overflow:visible}.av-primary-controls .control-group,.av-primary-controls [data-control-group]{display:grid;grid-template-rows:auto 44px;align-items:start;gap:6px;flex:1 1 180px;min-width:min(180px,100%);height:auto;min-height:0}.av-primary-controls .action-buttons,.av-primary-controls .btn-group{display:flex;flex:1 1 100%;flex-flow:row wrap;align-items:center;gap:8px;min-width:0;height:auto;margin:0}.av-primary-controls button,.av-primary-controls input:not([type="range"]),.av-primary-controls select{min-height:44px;font:inherit}.av-primary-controls button,.av-secondary-controls button{white-space:nowrap;word-break:keep-all}.av-primary-controls .action-buttons button,.av-primary-controls .btn-group button{flex:1 0 auto}.av-details{overflow:auto;scrollbar-gutter:stable}.av-details:empty{display:none}.av-details>[data-region="teaching-flow"]{margin-top:12px}
.av-primary-controls button,.av-secondary-controls button{appearance:none;border:1px solid #b9d3c8;border-radius:10px;background:linear-gradient(180deg,#fff 0%,#f7fbf9 100%);color:var(--av-brand-strong);padding:9px 15px;cursor:pointer;box-shadow:0 2px 0 rgba(29,58,47,.11),0 4px 10px rgba(29,58,47,.06);transition:transform 120ms ease,box-shadow 120ms ease,border-color 160ms ease,background-color 160ms ease,color 160ms ease}.av-primary-controls button:hover,.av-secondary-controls button:hover{border-color:#78ad97;background:#f4fbf7;box-shadow:0 3px 0 rgba(29,58,47,.13),0 6px 14px rgba(29,58,47,.09);transform:translateY(-1px)}.av-primary-controls button:active,.av-secondary-controls button:active{transform:translateY(2px) scale(.98);box-shadow:inset 0 2px 4px rgba(29,58,47,.16)}.av-primary-controls button:focus-visible,.av-secondary-controls button:focus-visible{outline:3px solid color-mix(in srgb,var(--av-accent) 28%,transparent);outline-offset:2px}.av-primary-controls button:disabled,.av-secondary-controls button:disabled{cursor:not-allowed;opacity:.52;transform:none;box-shadow:none}.av-primary-controls #play-animation{border-color:var(--av-brand);background:linear-gradient(180deg,#3a6654 0%,var(--av-brand) 100%);color:#fff;box-shadow:0 2px 0 var(--av-brand-strong),0 5px 12px rgba(29,58,47,.18)}.av-primary-controls #play-animation:hover{background:linear-gradient(180deg,#426f5d 0%,#315746 100%)}.av-primary-controls #play-animation[aria-pressed="true"],.av-primary-controls #pause-animation[aria-pressed="true"]{border-color:#059669;background:var(--av-soft);color:#047857;box-shadow:inset 0 0 0 2px rgba(16,185,129,.18),0 2px 6px rgba(29,58,47,.08)}.av-primary-controls #play-animation[aria-pressed="true"]{background:linear-gradient(180deg,#10b981 0%,#059669 100%);color:#fff}.av-primary-controls button.av-reset-confirm{animation:av-reset-confirm 320ms ease-out}.av-primary-controls select,.av-secondary-controls select{appearance:none;min-width:82px;border:1px solid #b9d3c8;border-radius:10px;background-color:#fff;background-image:linear-gradient(45deg,transparent 50%,var(--av-brand) 50%),linear-gradient(135deg,var(--av-brand) 50%,transparent 50%);background-position:calc(100% - 16px) calc(50% - 2px),calc(100% - 11px) calc(50% - 2px);background-size:5px 5px,5px 5px;background-repeat:no-repeat;color:var(--av-brand-strong);padding:9px 34px 9px 12px;cursor:pointer;box-shadow:0 2px 8px rgba(29,58,47,.07);transition:border-color 160ms ease,box-shadow 160ms ease,background-color 160ms ease}.av-primary-controls select:hover,.av-secondary-controls select:hover{border-color:#78ad97;background-color:#f7fbf9}.av-primary-controls select:focus-visible,.av-secondary-controls select:focus-visible{border-color:var(--av-accent);outline:0;box-shadow:0 0 0 3px rgba(16,185,129,.18)}.av-primary-controls select:disabled,.av-secondary-controls select:disabled{cursor:not-allowed;opacity:.55}@keyframes av-reset-confirm{0%{transform:scale(1)}45%{border-color:var(--av-accent);background:var(--av-soft);color:#047857;transform:scale(.95)}100%{transform:scale(1)}}
.av-primary-controls input[type="range"],.av-secondary-controls input[type="range"]{-webkit-appearance:none;appearance:none;box-sizing:border-box;display:block;width:100%;min-width:120px;max-height:44px;height:44px;min-height:44px;margin:0;padding:0;background:transparent;border:0;outline:0;cursor:pointer;flex:0 0 44px;align-self:start;--av-range-progress:50%}
.av-primary-controls input[type="range"]::-webkit-slider-runnable-track,.av-secondary-controls input[type="range"]::-webkit-slider-runnable-track{height:6px;border:0;border-radius:999px;background:linear-gradient(to right,var(--av-accent) 0,var(--av-accent) var(--av-range-progress),#dfe8e4 var(--av-range-progress),#dfe8e4 100%)}
.av-primary-controls input[type="range"]::-webkit-slider-thumb,.av-secondary-controls input[type="range"]::-webkit-slider-thumb{-webkit-appearance:none;appearance:none;width:24px;height:24px;margin-top:-9px;border:2px solid var(--av-paper);border-radius:50%;background:var(--av-accent);box-shadow:0 1px 4px rgba(29,58,47,.28)}
.av-primary-controls input[type="range"]::-moz-range-track,.av-secondary-controls input[type="range"]::-moz-range-track{height:6px;border:0;border-radius:999px;background:#dfe8e4}.av-primary-controls input[type="range"]::-moz-range-progress,.av-secondary-controls input[type="range"]::-moz-range-progress{height:6px;border-radius:999px;background:var(--av-accent)}.av-primary-controls input[type="range"]::-moz-range-thumb,.av-secondary-controls input[type="range"]::-moz-range-thumb{width:20px;height:20px;border:2px solid var(--av-paper);border-radius:50%;background:var(--av-accent);box-shadow:0 1px 4px rgba(29,58,47,.28)}
.av-primary-controls input[type="range"]:focus-visible,.av-secondary-controls input[type="range"]:focus-visible{outline:2px solid color-mix(in srgb,var(--av-accent) 45%,transparent);outline-offset:2px}.av-primary-controls input[type="range"]:disabled,.av-secondary-controls input[type="range"]:disabled{cursor:not-allowed;opacity:.55}
.av-status{grid-area:status;display:grid;grid-template-columns:minmax(0,1fr) minmax(180px,.7fr);gap:var(--av-gap);align-items:stretch}.av-caption,.av-formula{min-width:0;overflow:auto;scrollbar-gutter:stable}.av-caption{font-size:14px;line-height:1.55}.av-formula{font-variant-numeric:tabular-nums;white-space:normal}.av-empty{color:var(--av-muted);font-size:13px}
@media(min-width:960px) and (max-height:620px){#aetherviz-stage{min-height:0}.av-status{max-height:32dvh}.av-caption,.av-formula{max-height:32dvh}}
@media(max-width:959px){#aetherviz-app-shell{grid-template-columns:minmax(0,1fr);grid-template-rows:auto minmax(260px,1fr) auto auto;grid-template-areas:"header" "stage" "status" "inspector";overflow:auto}.av-header{display:block}.av-objectives{max-width:none;margin-top:8px}.av-inspector{display:block;overflow:visible}.av-inspector>.av-panel{margin-top:10px}.av-details{max-height:32dvh}.av-primary-controls{overflow:visible}.av-primary-controls>.control-panel,.av-primary-controls>[data-region="controls"]{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));align-items:start}.av-primary-controls .action-buttons,.av-primary-controls .btn-group{grid-column:1/-1}.av-primary-controls input[type="range"]{width:100%;min-width:0}}
@media(max-width:599px){#aetherviz-app-shell{height:100dvh;padding:10px;gap:10px;grid-template-rows:auto clamp(240px,45dvh,420px) auto auto}.av-goal{display:none}.av-objectives li:nth-child(n+3){display:none}.av-status{grid-template-columns:minmax(0,1fr)}.av-formula{max-height:92px}.av-primary-controls .control-panel,.av-primary-controls>[data-region="controls"]{display:grid;grid-template-columns:repeat(2,minmax(0,1fr))}.av-primary-controls input[type="range"]{width:100%;min-width:0}.av-details{max-height:28dvh}}
@media(prefers-reduced-motion:reduce){*,*::before,*::after{scroll-behavior:auto!important;animation-duration:.01ms!important;animation-iteration-count:1!important;transition-duration:.01ms!important}}
</style>
"""

CONTROL_CONTRACT_SCRIPT = r'''<script data-aetherviz-control-contract="range-v1">(function(){
var cache=new WeakMap(),running=false,resetTimer=0;
function sync(el){var min=Number(el.min),max=Number(el.max),value=Number(el.value);if(!Number.isFinite(min))min=0;if(!Number.isFinite(max)||max<=min)max=min+100;if(!Number.isFinite(value))value=min;var percent=Math.max(0,Math.min(100,(value-min)/(max-min)*100));var key=min+'|'+max+'|'+value;if(cache.get(el)===key)return;cache.set(el,key);el.style.setProperty('--av-range-progress',percent+'%');el.setAttribute('aria-valuenow',String(value));}
function syncAll(){document.querySelectorAll('#aetherviz-app-shell input[type="range"]').forEach(sync);}
function setPlaybackState(state){var play=document.getElementById('play-animation'),pause=document.getElementById('pause-animation'),reset=document.getElementById('reset-animation');if(play)play.setAttribute('aria-pressed',String(state==='playing'));if(pause)pause.setAttribute('aria-pressed',String(state==='paused'));if(state==='reset'&&reset){reset.classList.remove('av-reset-confirm');void reset.offsetWidth;reset.classList.add('av-reset-confirm');clearTimeout(resetTimer);resetTimer=setTimeout(function(){reset.classList.remove('av-reset-confirm');},360);}}
function frame(){if(!document.documentElement.contains(document.getElementById('aetherviz-app-shell'))){running=false;return;}syncAll();requestAnimationFrame(frame);}
function start(){syncAll();setPlaybackState('idle');if(!running){running=true;requestAnimationFrame(frame);}}
document.addEventListener('input',function(e){if(e.target&&e.target.matches('input[type="range"]'))sync(e.target);},true);document.addEventListener('change',function(e){if(e.target&&e.target.matches('input[type="range"]'))sync(e.target);},true);
document.addEventListener('aetherviz:animation-state',function(e){setPlaybackState(e.detail&&e.detail.state||'idle');});
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
window.AetherVizControlContract={sync:sync,syncAll:syncAll,setPlaybackState:setPlaybackState,version:'range-v1'};
})();</script>'''

ANIMATION_CONTRACT_SCRIPT = r'''<script data-aetherviz-animation-contract="controller-v1">(function(){
function create(opts){opts=opts||{};var duration=Math.max(Number(opts.duration)||1,.001),update=typeof opts.update==='function'?opts.update:function(){},progress=0,speed=1,playing=false,raf=0,start=0,tween=null;
function emit(state){document.dispatchEvent(new CustomEvent('aetherviz:animation-state',{detail:{state:state,progress:progress}}));}
function apply(value){progress=Math.max(0,Math.min(1,Number(value)||0));update(progress);}
function stopNative(){if(raf)cancelAnimationFrame(raf);raf=0;}
function nativeFrame(now){if(!playing)return;if(!start)start=now-progress*duration*1000/speed;apply((now-start)*speed/(duration*1000));if(progress>=1){playing=false;raf=0;emit('ended');return;}raf=requestAnimationFrame(nativeFrame);}
function play(){if(playing)return;if(progress>=1)apply(0);playing=true;emit('playing');if(window.gsap){if(tween){tween.kill();tween=null;}tween=window.gsap.to({p:progress},{p:1,duration:duration*(1-progress),ease:opts.ease||'none',onUpdate:function(){apply(this.targets()[0].p);},onComplete:function(){playing=false;tween=null;emit('ended');}});tween.timeScale(speed);}else{start=0;raf=requestAnimationFrame(nativeFrame);}}
function pause(){playing=false;if(tween)tween.pause();stopNative();emit('paused');}
function reset(){playing=false;if(tween){tween.pause();tween.kill();tween=null;}stopNative();start=0;apply(0);emit('reset');}
function setSpeed(value){speed=Math.max(Number(value)||1,.01);if(tween)tween.timeScale(speed);if(playing&&!window.gsap){stopNative();start=0;raf=requestAnimationFrame(nativeFrame);}}
return{play:play,pause:pause,reset:reset,restart:function(){reset();play();},setSpeed:setSpeed,getProgress:function(){return progress;},setProgress:apply};}
window.AetherVizAnimationController={create:create,version:'controller-v1'};
})();</script>'''


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

    for old in soup.select(
        '[data-aetherviz-layout-contract], [data-aetherviz-layout-guard="true"], '
        '[data-aetherviz-control-contract], [data-aetherviz-animation-contract]'
    ):
        old.decompose()
    for style in soup.find_all("style"):
        # Business styles may describe slot contents, but cannot use !important
        # to outrank the server-owned shell injected at the end of <head>.
        css = re.sub(r"\s*!\s*important\b", "", style.get_text(), flags=re.IGNORECASE)
        style.string = sanitize_business_css(css)
        style[_BUSINESS_STYLE_MARKER] = "true"

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
    control_script = BeautifulSoup(CONTROL_CONTRACT_SCRIPT, "html.parser").script
    if control_script is not None:
        soup.body.append(control_script)
    animation_script = BeautifulSoup(ANIMATION_CONTRACT_SCRIPT, "html.parser").script
    if animation_script is not None:
        soup.body.append(animation_script)
    for script in scripts:
        soup.body.append(script)
    soup.head.append(BeautifulSoup(LAYOUT_CONTRACT_CSS, "html.parser").style)
    return "<!DOCTYPE html>\n" + str(soup.html)


def extract_business_html(html: str) -> str:
    """Remove the server-owned shell before sending an existing page to a model.

    ``assemble_layout_contract`` is intentionally idempotent but its result is
    much larger than the model-authored document.  Editing the assembled page
    wastes the completion budget reproducing CSS and runtime guards.  This
    inverse keeps only the semantic regions, business assets and business
    scripts needed to assemble the same page again.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    shell = soup.select_one("#aetherviz-app-shell")
    if not isinstance(shell, Tag):
        return html

    for owned in soup.select(
        '[data-aetherviz-layout-contract], [data-aetherviz-layout-guard="true"], '
        '[data-aetherviz-control-contract], [data-aetherviz-animation-contract]'
    ):
        owned.decompose()

    assert soup.body is not None
    business_scripts = [script.extract() for script in list(soup.body.find_all("script"))]
    regions: list[Tag] = []

    stage = shell.select_one("#aetherviz-stage")
    if isinstance(stage, Tag):
        stage.extract()
        for attribute in ("class", "data-layout-slot"):
            stage.attrs.pop(attribute, None)
        regions.append(stage)

    primary = shell.select_one(".av-primary-controls")
    if isinstance(primary, Tag):
        controls = primary.select_one('[data-region="controls"], .control-panel, .controls')
        if isinstance(controls, Tag):
            regions.append(controls.extract())
        else:
            wrapper = soup.new_tag("div", attrs={"class": "control-panel", "data-region": "controls"})
            for child in list(primary.contents):
                if isinstance(child, Tag) and "av-empty" in child.get("class", []):
                    continue
                wrapper.append(child.extract())
            if wrapper.contents:
                regions.append(wrapper)

    for selector, region_name in (
        (".av-caption", "caption"),
        (".av-formula", "formula"),
    ):
        slot = shell.select_one(selector)
        if not isinstance(slot, Tag):
            continue
        source = slot.select_one(f'[data-region="{region_name}"]')
        if isinstance(source, Tag) and source is not slot:
            regions.append(source.extract())
            continue
        if slot.select_one(".av-empty") is None and slot.get_text(strip=True):
            wrapper = soup.new_tag("div", attrs={"data-region": region_name})
            for child in list(slot.contents):
                wrapper.append(child.extract())
            regions.append(wrapper)

    details = shell.select_one(".av-details")
    if isinstance(details, Tag):
        for child in list(details.children):
            if not isinstance(child, Tag):
                continue
            if child.get("data-region") in {"teaching-flow", "secondary-controls"} or child.select_one(
                '[data-region="teaching-flow"]'
            ):
                regions.append(child.extract())

    soup.body.clear()
    soup.body.attrs = {}
    for region in regions:
        soup.body.append(region)
    for script in business_scripts:
        soup.body.append(script)
    return "<!DOCTYPE html>\n" + str(soup.html)


def business_css_ownership_violations(css: str) -> list[str]:
    """Return business selectors that attempt to own server layout or range chrome."""
    violations: list[str] = []
    for match in _CSS_RULE_RE.finditer(css or ""):
        selectors = match.group("selectors").strip()
        if selectors.startswith("@"):
            continue
        for selector in selectors.split(","):
            normalized = selector.strip()
            if normalized == ":root" and all(
                not declaration.strip() or declaration.strip().startswith("--")
                for declaration in match.group("body").split(";")
            ):
                continue
            if _is_server_owned_selector(normalized):
                violations.append(normalized)
    return violations


def sanitize_business_css(css: str) -> str:
    """Remove server-owned selectors while preserving topic-independent visual styles."""

    def rewrite(match: re.Match[str]) -> str:
        selectors = match.group("selectors")
        body = match.group("body")
        stripped = selectors.strip()
        if stripped.startswith("@"):
            return match.group(0)
        kept: list[str] = []
        for selector in selectors.split(","):
            normalized = selector.strip()
            if normalized == ":root":
                custom_properties = ";".join(
                    declaration.strip()
                    for declaration in body.split(";")
                    if declaration.strip().startswith("--")
                )
                if custom_properties:
                    kept.append(":root")
                    body = custom_properties + ";"
                continue
            if not _is_server_owned_selector(normalized):
                kept.append(normalized)
        if not kept:
            return ""
        return f"{','.join(kept)}{{{body}}}"

    return _CSS_RULE_RE.sub(rewrite, css or "")


def _is_server_owned_selector(selector: str) -> bool:
    return bool(selector) and bool(
        selector == ":root"
        or _RANGE_SELECTOR_RE.search(selector)
        or _SERVER_SELECTOR_RE.search(selector)
    )


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
    title = html_lib.escape(str(plan.get("title") or "AI教学动画"))
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
