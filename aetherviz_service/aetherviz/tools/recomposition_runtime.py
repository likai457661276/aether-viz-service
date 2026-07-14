"""Server-owned SVG lifecycle scaffold for geometric recomposition scenes."""

from __future__ import annotations

import html
import json
import re
from typing import Any

from aetherviz_service.aetherviz.constants import get_gsap_core_cdn_url, get_katex_cdn_urls, is_katex_enabled
from aetherviz_service.aetherviz.tools.recomposition_ir import (
    build_deterministic_geometry_ir,
    compile_geometry_ir,
)

_SAFE_ID_RE = re.compile(r"[^a-zA-Z0-9_-]+")


def assemble_recomposition_business_html(scene_source: str, plan: dict[str, Any], topic: str) -> str:
    title = html.escape(str(plan.get("title") or topic or "几何重排互动课件"))
    goal = html.escape(str(plan.get("goal") or "观察切分图形如何保持关系并完成重排。"))
    topic_text = html.escape(str(topic or "几何重排"))
    primary = html.escape(str(plan.get("primary_color") or "#10B981"), quote=True)
    interactive_spec = plan.get("interactive_spec") if isinstance(plan.get("interactive_spec"), dict) else {}
    variables = [
        variable
        for variable in interactive_spec.get("variables", [])
        if isinstance(variable, dict) and not variable.get("computed")
    ][:3]
    recomposition_spec = (
        plan.get("recomposition_spec") if isinstance(plan.get("recomposition_spec"), dict) else {}
    )
    defaults = {
        str(variable.get("name")): _finite_number(variable.get("default"), 0)
        for variable in variables
        if str(variable.get("name") or "").strip()
    }
    widget_config = {
        "type": plan.get("interactive_type", "simulation"),
        "concept": topic,
        "variables": variables,
        "recomposition": recomposition_spec,
    }
    teaching_flow = plan.get("teaching_flow") if isinstance(plan.get("teaching_flow"), list) else []
    formulas = plan.get("formulas") if isinstance(plan.get("formulas"), list) else []
    initial_caption = next(
        (str(step.get("caption")) for step in teaching_flow if isinstance(step, dict) and step.get("caption")),
        "观察图形块从源状态移动到目标状态。",
    )
    initial_formula = str(formulas[0]) if formulas else "保持图形块身份与度量关系不变"
    controls = "".join(_variable_control(variable) for variable in variables)
    flow_markup = "".join(
        f'<li data-step="{index}">{html.escape(str(step.get("label") or f"第{index + 1}步"))}</li>'
        for index, step in enumerate(teaching_flow[:5])
        if isinstance(step, dict)
    )
    if not flow_markup:
        flow_markup = "<li data-step=\"0\">观察源图形</li><li data-step=\"1\">跟随重排过程</li><li data-step=\"2\">解释目标关系</li>"

    gsap_script = f'<script src="{html.escape(get_gsap_core_cdn_url(), quote=True)}"></script>'
    katex_assets = ""
    if formulas and is_katex_enabled():
        katex_css, katex_js = get_katex_cdn_urls()
        katex_assets = (
            f'<link rel="stylesheet" href="{html.escape(katex_css, quote=True)}">'
            f'<script src="{html.escape(katex_js, quote=True)}"></script>'
        )

    runtime_script = _RUNTIME_SCRIPT.replace("__SCENE_MODULE__", scene_source.strip())
    runtime_script = runtime_script.replace("__DEFAULT_STATE__", _json_for_script(defaults))
    runtime_script = runtime_script.replace("__RECOMPOSITION_SPEC__", _json_for_script(recomposition_spec))
    runtime_script = runtime_script.replace("__INITIAL_CAPTION__", _json_for_script(initial_caption))
    runtime_script = runtime_script.replace("__INITIAL_FORMULA__", _json_for_script(initial_formula))

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
{gsap_script}{katex_assets}
<style>
:root{{--recomp-primary:{primary};--recomp-ink:#17362d;--recomp-soft:#ecfdf5}}
.recomp-svg{{width:100%;height:100%;min-height:280px;background:linear-gradient(145deg,#fff,#f4fbf7)}}
.recomp-piece{{vector-effect:non-scaling-stroke;stroke:#174c3c;stroke-width:2;stroke-linejoin:round}}
.recomp-control-panel{{display:flex;flex-wrap:wrap;gap:10px}}
.recomp-control{{display:grid;grid-template-rows:auto 44px;gap:4px;min-width:150px;flex:1}}
.recomp-actions{{display:flex;gap:8px;flex-wrap:wrap;width:100%}}
.recomp-actions button{{border:1px solid #b7d5c9;border-radius:8px;background:#fff;color:var(--recomp-ink);padding:8px 12px}}
.recomp-actions button:first-child{{background:var(--recomp-primary);border-color:var(--recomp-primary);color:#fff}}
.recomp-caption{{margin:0;color:var(--recomp-ink)}}
.recomp-formula{{margin:0;font-weight:650;color:#24634f}}
.recomp-flow{{margin:0;padding-left:20px;line-height:1.7}}
.recomp-flow li[aria-current="step"]{{color:#047857;font-weight:700}}
</style>
<script type="application/json" id="widget-config">{_json_for_script(widget_config)}</script>
</head>
<body>
<header data-region="learning-goal"><h1>{title}</h1><p>{goal}</p></header>
<section id="aetherviz-stage" aria-label="{topic_text}互动舞台">
  <svg class="recomp-svg" data-role="main-visual" viewBox="0 0 960 560" role="img" aria-label="{topic_text}">
    <g id="recomposition-pieces" aria-label="可重排图形块"></g>
  </svg>
</section>
<section class="recomp-control-panel" data-region="controls">
  {controls}
  <div class="recomp-actions">
    <button id="play-animation" type="button">播放</button>
    <button id="pause-animation" type="button">暂停</button>
    <button id="reset-animation" type="button">重置</button>
    <label>速度 <select id="animation-speed"><option value="0.5">0.5×</option><option value="1" selected>1×</option><option value="2">2×</option></select></label>
  </div>
</section>
<section data-region="caption"><p id="animation-caption" class="recomp-caption">{html.escape(initial_caption)}</p></section>
<section data-region="formula"><p id="animation-formula" class="recomp-formula">{html.escape(initial_formula)}</p></section>
<ol class="recomp-flow" data-region="teaching-flow">{flow_markup}</ol>
<script>{runtime_script}</script>
</body>
</html>"""


def build_deterministic_scene_module(plan: dict[str, Any]) -> str:
    return compile_geometry_ir(build_deterministic_geometry_ir(plan), plan)


def _variable_control(variable: dict[str, Any]) -> str:
    name = str(variable.get("name") or "parameter")
    safe_id = _SAFE_ID_RE.sub("-", name).strip("-") or "parameter"
    label = html.escape(str(variable.get("label") or name))
    minimum = _finite_number(variable.get("min"), 0)
    maximum = _finite_number(variable.get("max"), max(minimum + 1, 10))
    step = _finite_number(variable.get("step"), 1)
    default = min(max(_finite_number(variable.get("default"), minimum), minimum), maximum)
    return (
        '<label class="recomp-control">'
        f"<span>{label}</span>"
        f'<input id="recomp-{html.escape(safe_id, quote=True)}" type="range" data-var="{html.escape(name, quote=True)}" '
        f'min="{minimum:g}" max="{maximum:g}" step="{max(step, 0.000001):g}" value="{default:g}">'
        "</label>"
    )


def _finite_number(value: object, fallback: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(fallback)
    if number != number or number in {float("inf"), float("-inf")}:
        return float(fallback)
    return number


def _json_for_script(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


_RUNTIME_SCRIPT = r"""(function(){
'use strict';
const DEFAULT_STATE=Object.freeze(__DEFAULT_STATE__);
const RECOMPOSITION_SPEC=Object.freeze(__RECOMPOSITION_SPEC__);
const sceneMath=Object.freeze({
  clamp(value,min,max){return Math.max(Number(min),Math.min(Number(max),Number(value)||0));},
  lerp(start,end,t){const p=Math.max(0,Math.min(1,Number(t)||0));return Number(start)+(Number(end)-Number(start))*p;},
  interpolate(start,end,t){const p=Math.max(0,Math.min(1,Number(t)||0));return Number(start)+(Number(end)-Number(start))*p;},
  fixed(value,digits){const number=Number(value);return (Number.isFinite(number)?number:0).toFixed(Math.max(0,Math.min(6,Number(digits)||0)));},
  sectorPath(cx,cy,r,startAngle,endAngle){const x1=cx+r*Math.cos(startAngle),y1=cy+r*Math.sin(startAngle),x2=cx+r*Math.cos(endAngle),y2=cy+r*Math.sin(endAngle);const large=Math.abs(endAngle-startAngle)>Math.PI?1:0;return 'M '+cx+' '+cy+' L '+x1+' '+y1+' A '+r+' '+r+' 0 '+large+' 1 '+x2+' '+y2+' Z';},
  interpolatePieces(pieces,progress){const p=Math.max(0,Math.min(1,Number(progress)||0));return {pieces:pieces.map((piece)=>{const stages=Array.isArray(piece.transformKeyframes)&&piece.transformKeyframes.length>=2?piece.transformKeyframes:[{at:0,...(piece.sourceTransform||{})},{at:1,...(piece.targetTransform||{})}];let right=stages.findIndex((stage)=>Number(stage.at)>=p);if(right<0)right=stages.length-1;const left=Math.max(0,right-1),a=stages[left]||{},b=stages[right]||a,span=Math.max(0.000001,Number(b.at)-Number(a.at)),local=left===right?0:Math.max(0,Math.min(1,(p-Number(a.at))/span)),e=local*local*(3-2*local);const mix=(key,fallback)=>{const start=Number(a[key]),end=Number(b[key]),av=Number.isFinite(start)?start:fallback,bv=Number.isFinite(end)?end:av;return av+(bv-av)*e;};const x=mix('x',0),y=mix('y',0),rotation=mix('rotation',0),scale=mix('scale',1),opacity=mix('opacity',1);return {id:piece.id,attrs:{transform:'translate('+x.toFixed(3)+' '+y.toFixed(3)+') rotate('+rotation.toFixed(3)+') scale('+scale.toFixed(4)+')',opacity:opacity.toFixed(4)}};})};}
});
const clamp=sceneMath.clamp,fixed=sceneMath.fixed;
const state=Object.assign({},DEFAULT_STATE);
__SCENE_MODULE__
const SVG_NS='http://www.w3.org/2000/svg';
const ALLOWED_TAGS=new Set(['path','polygon','polyline','rect','circle','ellipse','line','g']);
const BASE_ATTRS=new Set(['d','points','x','y','x1','y1','x2','y2','cx','cy','r','rx','ry','width','height','fill','stroke','stroke-width','stroke-dasharray','opacity','transform','class']);
const FRAME_ATTRS=new Set(['x','y','cx','cy','r','rx','ry','width','height','fill','stroke','opacity','transform','class']);
const registry=new Map();
const layer=document.getElementById('recomposition-pieces');
const caption=document.getElementById('animation-caption');
const formula=document.getElementById('animation-formula');
const steps=Array.from(document.querySelectorAll('[data-region="teaching-flow"] [data-step]'));
let geometry={pieces:[]},controller=null,currentProgress=0,playing=false,lastFormula='';
const animationBackend=window.gsap?'gsap':'native';
function finite(value){const number=Number(value);return Number.isFinite(number)?number:null;}
function cloneState(){return Object.assign({},state);}
function safeAttrs(attrs,allowed){const result={};if(!attrs||typeof attrs!=='object')return result;for(const key of Object.keys(attrs)){if(!allowed.has(key))continue;const value=attrs[key],serialized=String(value);if((typeof value==='number'&&!Number.isFinite(value))||/NaN|Infinity/.test(serialized))throw new Error('non_finite_attr:'+key);result[key]=serialized;}return result;}
function normalizeGeometry(raw){if(!raw||!Array.isArray(raw.pieces)||raw.pieces.length<1||raw.pieces.length>80)throw new Error('invalid_piece_count');const ids=new Set();const pieces=raw.pieces.map((piece,index)=>{if(!piece||typeof piece!=='object')throw new Error('invalid_piece:'+index);const id=String(piece.id||'');if(!id||ids.has(id))throw new Error('duplicate_piece_id:'+id);ids.add(id);const tag=String(piece.tag||'path').toLowerCase();if(!ALLOWED_TAGS.has(tag))throw new Error('invalid_piece_tag:'+tag);if(!piece.sourceTransform||!piece.targetTransform)throw new Error('missing_transform_state:'+id);return Object.assign({},piece,{id,tag,attrs:safeAttrs(piece.attrs,BASE_ATTRS)});});return {pieces};}
function setAttrs(node,attrs){for(const key of Object.keys(attrs))node.setAttribute(key,attrs[key]);}
function createPiece(piece){const node=document.createElementNS(SVG_NS,piece.tag);node.setAttribute('data-piece-id',piece.id);node.setAttribute('class','recomp-piece');setAttrs(node,piece.attrs);layer.appendChild(node);registry.set(piece.id,node);}
function buildScene(){playing=false;if(controller)controller.pause();registry.clear();layer.replaceChildren();geometry=normalizeGeometry(sceneModule.buildGeometry(cloneState()));for(const piece of geometry.pieces)createPiece(piece);if(registry.size!==geometry.pieces.length)throw new Error('registry_size_mismatch');currentProgress=0;applyProgress(0);}
function refreshGeometry(){const next=normalizeGeometry(sceneModule.buildGeometry(cloneState()));if(next.pieces.length!==geometry.pieces.length)throw new Error('geometry_changed_topology');for(const piece of next.pieces){const node=registry.get(piece.id);if(!node)throw new Error('missing_registered_piece:'+piece.id);setAttrs(node,piece.attrs);}geometry=next;applyProgress(currentProgress);}
function applyDisplay(progress){const display=sceneModule.deriveDisplay(cloneState(),progress)||{};caption.textContent=String(display.caption||__INITIAL_CAPTION__);const nextFormula=String(display.formula||__INITIAL_FORMULA__);if(nextFormula!==lastFormula){lastFormula=nextFormula;if(window.katex&&typeof window.katex.render==='function'){try{window.katex.render(nextFormula,formula,{throwOnError:false});}catch(_){formula.textContent=nextFormula;}}else formula.textContent=nextFormula;}const requestedStep=Number(display.step);const fallbackStep=Math.min(steps.length-1,Math.floor(progress*Math.max(steps.length,1)));const active=Math.max(0,Math.min(steps.length-1,Number.isFinite(requestedStep)?Math.round(requestedStep):fallbackStep));steps.forEach((step,index)=>index===active?step.setAttribute('aria-current','step'):step.removeAttribute('aria-current'));}
function applyProgress(progress){currentProgress=Math.max(0,Math.min(1,Number(progress)||0));const frame=sceneModule.deriveFrame(geometry,cloneState(),currentProgress)||{};const pieces=Array.isArray(frame.pieces)?frame.pieces:[];for(const piece of pieces){const node=registry.get(String(piece.id||''));if(!node)throw new Error('frame_unknown_piece:'+String(piece.id||''));setAttrs(node,safeAttrs(piece.attrs,FRAME_ATTRS));}if(currentProgress>=1)playing=false;applyDisplay(currentProgress);}
function update(patch){const next=patch&&typeof patch==='object'?patch:{};const before=String(sceneModule.structureKey(cloneState()));for(const key of Object.keys(DEFAULT_STATE)){if(Object.prototype.hasOwnProperty.call(next,key)){const value=finite(next[key]);if(value!==null)state[key]=value;}}const after=String(sceneModule.structureKey(cloneState()));if(before!==after)buildScene();else refreshGeometry();if(Object.prototype.hasOwnProperty.call(next,'progress'))controller.setProgress(next.progress);return getState();}
function play(){playing=true;controller.play();}
function pause(){playing=false;controller.pause();}
function reset(){playing=false;Object.assign(state,DEFAULT_STATE);for(const input of document.querySelectorAll('[data-var]')){const key=input.getAttribute('data-var');if(Object.prototype.hasOwnProperty.call(DEFAULT_STATE,key))input.value=String(DEFAULT_STATE[key]);}buildScene();controller.reset();}
function setSpeed(value){controller.setSpeed(value);}
function getState(){return Object.assign({},cloneState(),{progress:currentProgress,isPlaying:playing,pieceCount:registry.size,animationBackend});}
function bindControls(){document.getElementById('play-animation').addEventListener('click',play);document.getElementById('pause-animation').addEventListener('click',pause);document.getElementById('reset-animation').addEventListener('click',reset);document.getElementById('animation-speed').addEventListener('change',(event)=>setSpeed(event.target.value));for(const input of document.querySelectorAll('[data-var]'))input.addEventListener('input',(event)=>{const key=event.target.getAttribute('data-var');const value=finite(event.target.value);if(key&&value!==null)update({[key]:value});});}
function handleWidgetAction(event){const message=event.data||{};if(message.type==='SET_WIDGET_STATE'&&message.state)update(message.state);if(message.type==='HIGHLIGHT_ELEMENT'&&message.target){const node=document.querySelector(message.target);if(node)node.setAttribute('data-highlighted','true');}if(message.type==='ANNOTATE_ELEMENT'&&message.content)caption.textContent=String(message.content);if(message.type==='REVEAL_ELEMENT'&&message.target){const node=document.querySelector(message.target);if(node)node.hidden=false;}}
try{if(!window.AetherVizAnimationController)throw new Error('missing_animation_controller');buildScene();controller=window.AetherVizAnimationController.create({duration:4,update:applyProgress,ease:'power1.inOut'});bindControls();window.addEventListener('message',handleWidgetAction);window.AetherVizRuntime={play,pause,reset,setSpeed,update,getState};window.__AETHERVIZ_RUNTIME_READY__=true;}catch(error){window.__AETHERVIZ_RUNTIME_ERROR__=String(error&&error.message||error);caption.textContent='课件初始化失败：'+window.__AETHERVIZ_RUNTIME_ERROR__;}
})();"""
