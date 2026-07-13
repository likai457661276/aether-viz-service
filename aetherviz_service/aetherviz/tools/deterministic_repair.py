"""Deterministic, model-free repairs for generated HTML."""

from __future__ import annotations

import html as html_lib
import json
import re
from typing import Any

from aetherviz_service.aetherviz.tools.widget_contract_checker import REQUIRED_RUNTIME_METHODS

_JS_IDENTIFIER = r"[A-Za-z_$][\w$]*"
_JS_MEMBER = rf"{_JS_IDENTIFIER}(?:\s*\.\s*{_JS_IDENTIFIER}|\s*\[\s*['\"]{_JS_IDENTIFIER}['\"]\s*\])*"
_UNSTABLE_PRESERVED_CHILD_RE = re.compile(
    rf"(?P<declaration>(?:const|let|var)\s+(?P<child>{_JS_IDENTIFIER})\s*=\s*"
    rf"(?P<parent>{_JS_MEMBER})\.(?:firstChild|lastChild)\s*;)"
    rf"(?P<middle>[\s\S]{{0,1600}}?"
    rf"(?P=parent)\s*\.\s*(?:innerHTML\s*=\s*['\"]\s*['\"]|replaceChildren\s*\(\s*\))\s*;?"
    rf"[\s\S]{{0,800}}?)"
    rf"(?P<append>(?P=parent)\s*\.\s*appendChild\s*\(\s*(?P=child)\s*\))"
)
_INDEXED_ANGLE_PAIR_RE = re.compile(
    rf"(?P<start_decl>(?:const|let|var)\s+(?P<start>{_JS_IDENTIFIER})\s*=)\s*"
    rf"(?P<index>{_JS_IDENTIFIER})\s*\*\s*(?P<step>{_JS_IDENTIFIER})\s*;"
    rf"(?P<between>\s*)"
    rf"(?P<end_decl>(?:const|let|var)\s+(?P<end>{_JS_IDENTIFIER})\s*=)\s*"
    rf"\(\s*(?P=index)\s*\+\s*1\s*\)\s*\*\s*(?P=step)\s*;"
)


def deterministic_repair_html(
    html: str,
    report: dict[str, Any] | None = None,
    *,
    plan: dict[str, Any] | None = None,
) -> str:
    repaired = html.strip()
    if not repaired.lower().startswith("<!doctype html>"):
        repaired = "<!DOCTYPE html>\n" + repaired
    if "</body>" not in repaired.lower():
        if "</html>" in repaired.lower():
            close_index = repaired.lower().rfind("</html>")
            repaired = repaired[:close_index] + "\n</body>\n" + repaired[close_index:]
        else:
            repaired += "\n</body>"
    if "</html>" not in repaired.lower():
        repaired += "\n</html>"
    error_types = {
        str(error.get("type"))
        for error in ((report or {}).get("errors") or [])
        if isinstance(error, dict)
    }
    warning_types = {
        str(warning.get("type"))
        for warning in ((report or {}).get("warnings") or [])
        if isinstance(warning, dict)
    }
    if error_types:
        # Keep hard-error repair minimal. Quality normalization runs in the
        # dedicated quality phase after the repaired document validates.
        warning_types = set()
    if plan is not None or "missing_widget_config" in error_types:
        repaired = _insert_widget_config(repaired, plan)
    if plan is not None or "missing_control" in error_types:
        repaired = _insert_runtime_controls(repaired)
    if "inline_event" in error_types:
        repaired = _move_inline_events_to_listeners(repaired)
    if error_types & {"missing_runtime", "missing_runtime_method"}:
        repaired = _ensure_runtime_methods(repaired)
    if "non_node_append_child" in error_types:
        repaired = _rewrite_assignment_append_child(repaired)
    if "unstable_preserved_child" in error_types:
        repaired = _guard_unstable_preserved_children(repaired)
    if "html_length_hard_limit" in error_types:
        repaired = re.sub(r"<!--(?!\[if)[\s\S]*?-->", "", repaired, flags=re.IGNORECASE)
        repaired = re.sub(r">\s+<", "><", repaired)
    if warning_types & {
        "abstract_svg_text_scale_risk",
        "abstract_svg_stroke_scale_risk",
        "mixed_svg_unit_system",
    }:
        repaired = _insert_svg_scale_guard(repaired)
    if "duplicate_geometry_transform_encoding" in warning_types:
        repaired = _localize_indexed_angle_geometry(repaired)
    if "missing_stage_shrink_guard" in warning_types:
        repaired = _insert_stage_shrink_guard(repaired)
    if error_types & {
        "missing_layout_contract",
        "missing_layout_shell",
        "invalid_layout_slot",
        "invalid_layout_styles",
        "invalid_range_control_contract",
    }:
        from aetherviz_service.aetherviz.tools.layout_contract import assemble_layout_contract

        repaired = assemble_layout_contract(repaired, plan)
    # Do not make a completely missing business runtime look healthy by adding
    # only protocol fallbacks. These bridges are for near-valid model repairs
    # that implemented the runtime but missed one host integration marker.
    if "missing_runtime" not in error_types:
        if "missing_message_listener" in error_types:
            repaired = _insert_message_listener_bridge(repaired)
        if "missing_runtime_ready" in error_types:
            repaired = _insert_runtime_ready_guard(repaired)
    return repaired


def _insert_svg_scale_guard(html: str) -> str:
    """Normalize SVG screen typography and strokes without knowing the topic.

    The guard records each text node's authored screen-size target once and
    recomputes its user-unit font size from the current screen CTM. It also makes
    authored strokes non-scaling. Mutation/resize hooks cover runtime-created SVG.
    """
    if 'data-aetherviz-scale-guard="true"' in html:
        return html
    script = r'''<script data-aetherviz-scale-guard="true">(function(){
function normalize(root){(root||document).querySelectorAll('#aetherviz-stage svg').forEach(function(svg){
svg.querySelectorAll('path,line,polyline,polygon,circle,ellipse,rect').forEach(function(el){if(getComputedStyle(el).stroke&&getComputedStyle(el).stroke!=='none')el.style.vectorEffect='non-scaling-stroke';});
svg.querySelectorAll('text').forEach(function(el){var ctm=el.getScreenCTM();if(!ctm)return;var scale=Math.sqrt(Math.abs(ctm.a*ctm.d-ctm.b*ctm.c));if(!scale)return;var target=parseFloat(el.dataset.aethervizScreenFont||getComputedStyle(el).fontSize);if(!Number.isFinite(target)||target<=0)return;el.dataset.aethervizScreenFont=String(target);el.style.fontSize=(target/scale)+'px';});
});}
var queued=false;function schedule(){if(queued)return;queued=true;requestAnimationFrame(function(){queued=false;normalize(document);});}
schedule();new MutationObserver(schedule).observe(document.getElementById('aetherviz-stage')||document.body,{childList:true,subtree:true});
if(window.ResizeObserver)new ResizeObserver(schedule).observe(document.getElementById('aetherviz-stage')||document.body);
})();</script>
'''
    body_close = re.search(r"</body\s*>", html, re.IGNORECASE)
    insert_at = body_close.start() if body_close else len(html)
    return html[:insert_at] + script + html[insert_at:]


def _insert_stage_shrink_guard(html: str) -> str:
    if 'data-aetherviz-layout-guard="true"' in html:
        return html
    style = (
        '<style data-aetherviz-layout-guard="true">'
        '#aetherviz-stage{min-width:0;min-height:0}'
        '[data-region="app-shell"]>*{min-width:0;min-height:0}'
        '@media(max-width:900px){#aetherviz-stage{min-height:clamp(240px,45vh,420px)}}'
        '</style>\n'
    )
    head_close = re.search(r"</head\s*>", html, re.IGNORECASE)
    insert_at = head_close.start() if head_close else 0
    return html[:insert_at] + style + html[insert_at:]


def _ensure_runtime_methods(html: str) -> str:
    """Guarantee window.AetherVizRuntime exists with all contract methods.

    Existing methods are preserved; only missing ones get safe fallbacks so the
    iframe control protocol never crashes on a partially implemented runtime.
    """
    fallbacks = {
        method: "function(){return {};}" if method == "getState" else "function(){}"
        for method in REQUIRED_RUNTIME_METHODS
    }
    patches = "".join(
        f'if(typeof r.{method}!=="function")r.{method}={fallback};'
        for method, fallback in fallbacks.items()
    )
    script = (
        "<script>(function(){var r=window.AetherVizRuntime="
        "window.AetherVizRuntime||{};" + patches + "})();</script>\n"
    )
    body_close = re.search(r"</body\s*>", html, re.IGNORECASE)
    insert_at = body_close.start() if body_close else len(html)
    return html[:insert_at] + script + html[insert_at:]


_ASSIGNMENT_APPEND_RE = re.compile(
    r"\.appendChild\(\s*(?P<obj>[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*(?:\([^()]*\))?"
    r"(?:\.[A-Za-z_$][\w$]*)*)\.(?P<prop>[A-Za-z_$][\w$]*)\s*=\s*"
    r"(?P<value>\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*'|`(?:[^`\\]|\\.)*`|[\d.]+)\s*\)"
)


def _rewrite_assignment_append_child(html: str) -> str:
    """Rewrite `x.appendChild(el.prop = literal)` into a Node-returning form.

    Assignment expressions evaluate to the assigned literal (not the element),
    so the original code throws at runtime. `Object.assign` returns the target
    element, which keeps behavior while satisfying appendChild's Node contract.
    """

    def rewrite(match: re.Match[str]) -> str:
        obj, prop, value = match.group("obj"), match.group("prop"), match.group("value")
        return f".appendChild(Object.assign({obj},{{{prop}:{value}}}))"

    return _ASSIGNMENT_APPEND_RE.sub(rewrite, html)


def _guard_unstable_preserved_children(html: str) -> str:
    """Guard nullable first/lastChild sentinels before re-appending them."""

    def rewrite(match: re.Match[str]) -> str:
        child = match.group("child")
        return (
            match.group("declaration")
            + match.group("middle")
            + f"if({child} instanceof Node){{{match.group('append')}}}"
        )

    return _UNSTABLE_PRESERVED_CHILD_RE.sub(rewrite, html)


def _localize_indexed_angle_geometry(html: str) -> str:
    """Author one centered local angular shape and leave instance direction to transforms."""

    def rewrite(match: re.Match[str]) -> str:
        step = match.group("step")
        return (
            f"{match.group('start_decl')} -{step}/2;"
            f"{match.group('between')}"
            f"{match.group('end_decl')} {step}/2;"
        )

    return _INDEXED_ANGLE_PAIR_RE.sub(rewrite, html)


def _insert_message_listener_bridge(html: str) -> str:
    if 'data-aetherviz-message-bridge="true"' in html:
        return html
    script = r'''<script data-aetherviz-message-bridge="true">(function(){
window.addEventListener('message',function(event){var data=event.data;if(!data||typeof data!=='object')return;var runtime=window.AetherVizRuntime||{};
if(data.type==='SET_WIDGET_STATE'&&typeof runtime.update==='function')runtime.update(data.state||{});
else if(data.type==='HIGHLIGHT_ELEMENT'||data.type==='REVEAL_ELEMENT'||data.type==='ANNOTATE_ELEMENT'){var target=typeof data.target==='string'?document.querySelector(data.target):null;if(!target)return;if(data.type==='HIGHLIGHT_ELEMENT')target.setAttribute('data-aetherviz-highlight','true');else if(data.type==='REVEAL_ELEMENT')target.hidden=false;else if(data.content!=null)target.setAttribute('aria-label',String(data.content));}
});})();</script>'''
    return _insert_before_body_close(html, script)


def _insert_runtime_ready_guard(html: str) -> str:
    if 'data-aetherviz-ready-guard="true"' in html:
        return html
    methods = json.dumps(list(REQUIRED_RUNTIME_METHODS), separators=(",", ":"))
    script = f'''<script data-aetherviz-ready-guard="true">(function(){{
function markReady(){{var runtime=window.AetherVizRuntime;if(window.__AETHERVIZ_RUNTIME_ERROR__||!runtime)return;if({methods}.every(function(name){{return typeof runtime[name]==='function';}}))window.__AETHERVIZ_RUNTIME_READY__=true;}}
function schedule(){{requestAnimationFrame(markReady);}}if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',schedule,{{once:true}});else schedule();
}})();</script>'''
    return _insert_before_body_close(html, script)


def _insert_before_body_close(html: str, markup: str) -> str:
    body_close = re.search(r"</body\s*>", html, re.IGNORECASE)
    insert_at = body_close.start() if body_close else len(html)
    return html[:insert_at] + markup + "\n" + html[insert_at:]


def _move_inline_events_to_listeners(html: str) -> str:
    """Move inline onXxx handlers into equivalent addEventListener bindings."""
    handlers: list[tuple[str, str, str]] = []
    tag_index = 0
    event_attr = re.compile(r"\s+(on[a-zA-Z]+)\s*=\s*(['\"])(.*?)\2", re.DOTALL)

    def rewrite_tag(match: re.Match[str]) -> str:
        nonlocal tag_index
        tag = match.group(0)
        found = list(event_attr.finditer(tag))
        if not found:
            return tag
        marker = f"aetherviz-event-{tag_index}"
        tag_index += 1
        for attr in found:
            handlers.append((marker, attr.group(1)[2:].lower(), html_lib.unescape(attr.group(3)).strip()))
        tag = event_attr.sub("", tag)
        insert_at = tag.rfind("/>")
        if insert_at < 0:
            insert_at = tag.rfind(">")
        return tag[:insert_at] + f' data-aetherviz-event="{marker}"' + tag[insert_at:]

    repaired = re.sub(r"<[A-Za-z][^<>]*>", rewrite_tag, html)
    if not handlers:
        return html
    bindings = "".join(
        "var el=document.querySelector(" + json.dumps(f'[data-aetherviz-event="{marker}"]') + ");"
        + f"if(el)el.addEventListener({json.dumps(event_name)},function(event){{{source}}});"
        for marker, event_name, source in handlers
    )
    script = f"<script>(function(){{{bindings}}})();</script>\n"
    body_close = re.search(r"</body\s*>", repaired, re.IGNORECASE)
    insert_at = body_close.start() if body_close else len(repaired)
    return repaired[:insert_at] + script + repaired[insert_at:]


def _insert_widget_config(html: str, plan: dict[str, Any] | None) -> str:
    source = plan if isinstance(plan, dict) else {}
    interactive_type = str(source.get("interactive_type") or "diagram")
    if interactive_type not in {"simulation", "diagram", "game"}:
        interactive_type = "diagram"
    spec = source.get("interactive_spec")
    payload = dict(spec) if isinstance(spec, dict) else {}
    payload["type"] = interactive_type
    config_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    markup = f'<script type="application/json" id="widget-config">{config_json}</script>\n'
    existing = re.search(
        r"<script\b(?=[^>]*\bid\s*=\s*(['\"])widget-config\1)[^>]*>[\s\S]*?</script\s*>",
        html,
        re.IGNORECASE,
    )
    if existing:
        return html[: existing.start()] + markup.rstrip() + html[existing.end() :]
    head_close = re.search(r"</head\s*>", html, re.IGNORECASE)
    if head_close:
        return html[: head_close.start()] + markup + html[head_close.start() :]
    html_open = re.search(r"<html\b[^>]*>", html, re.IGNORECASE)
    insert_at = html_open.end() if html_open else 0
    return html[:insert_at] + "\n<head>\n" + markup + "</head>\n" + html[insert_at:]


def _insert_runtime_controls(html: str) -> str:
    controls = (
        ("play-animation", "播放", "play"),
        ("pause-animation", "暂停", "pause"),
        ("reset-animation", "重置", "reset"),
    )
    missing = [
        item
        for item in controls
        if not re.search(rf"\bid\s*=\s*(['\"]){item[0]}\1", html, re.IGNORECASE)
    ]
    if not missing:
        return html
    buttons = "".join(
        f'<button id="{control_id}" type="button" data-action="{action}">{label}</button>'
        for control_id, label, action in missing
    )
    repaired = _insert_into_control_panel(html, buttons)
    if repaired == html:
        body_close = re.search(r"</body\s*>", html, re.IGNORECASE)
        insert_at = body_close.start() if body_close else len(html)
        repaired = (
            html[:insert_at]
            + f'<div class="control-panel" data-region="controls">{buttons}</div>\n'
            + html[insert_at:]
        )

    bindings = json.dumps({control_id: action for control_id, _, action in missing}, ensure_ascii=True)
    script = (
        "<script>(function(){var bindings="
        + bindings
        + ";Object.keys(bindings).forEach(function(id){var el=document.getElementById(id);"
        "if(!el)return;el.addEventListener('click',function(){var runtime=window.AetherVizRuntime;"
        "var method=bindings[id];if(runtime&&typeof runtime[method]==='function')runtime[method]();});});})();</script>\n"
    )
    body_close = re.search(r"</body\s*>", repaired, re.IGNORECASE)
    insert_at = body_close.start() if body_close else len(repaired)
    return repaired[:insert_at] + script + repaired[insert_at:]


def _insert_into_control_panel(html: str, markup: str) -> str:
    opening = re.search(
        r"<div\b[^>]*\bclass\s*=\s*(['\"])[^'\"]*\bcontrol-panel\b[^'\"]*\1[^>]*>",
        html,
        re.IGNORECASE,
    )
    if not opening:
        return html
    depth = 0
    for token in re.finditer(r"<div\b[^>]*>|</div\s*>", html[opening.start() :], re.IGNORECASE):
        if token.group(0).lower().startswith("</div"):
            depth -= 1
            if depth == 0:
                insert_at = opening.start() + token.start()
                return html[:insert_at] + markup + html[insert_at:]
        else:
            depth += 1
    return html
