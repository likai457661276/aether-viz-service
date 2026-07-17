"""Server-owned SVG compiler and lifecycle runtime for linked-coordinate IR."""

from __future__ import annotations

import html
import json
import re
from typing import Any

from aetherviz_service.aetherviz.constants import get_gsap_core_cdn_url
from aetherviz_service.aetherviz.ir.linked_coordinate.contract import compile_linked_coordinate_ir

_SAFE_ID_RE = re.compile(r"[^a-zA-Z0-9_-]+")


def assemble_linked_coordinate_business_html(
    ir: dict[str, Any], plan: dict[str, Any], topic: str
) -> str:
    ir_json = compile_linked_coordinate_ir(ir, plan)
    title = html.escape(str(plan.get("title") or topic or "联动坐标互动课件"))
    goal = html.escape(str(plan.get("goal") or "观察多个数学表征之间的同步关系。"))
    topic_text = html.escape(str(topic or title))
    primary = html.escape(str(plan.get("primary_color") or "#10B981"), quote=True)
    variables = _variables(plan)
    defaults = {str(item["name"]): _finite(item.get("default"), 0) for item in variables}
    controls = "".join(_variable_control(item) for item in variables)
    teaching_flow = plan.get("teaching_flow") if isinstance(plan.get("teaching_flow"), list) else []
    flow_markup = "".join(
        f'<li data-step="{index}">{html.escape(str(item.get("label") or f"第{index + 1}步"))}</li>'
        for index, item in enumerate(teaching_flow[:5])
        if isinstance(item, dict)
    ) or '<li data-step="0">观察对应对象</li><li data-step="1">改变参数</li><li data-step="2">归纳联动关系</li>'
    caption = next(
        (
            str(item.get("caption"))
            for item in teaching_flow
            if isinstance(item, dict) and item.get("caption")
        ),
        "拖动参数，观察各坐标表征中的点、曲线与投影如何同步变化。",
    )
    formulas = plan.get("formulas") if isinstance(plan.get("formulas"), list) else []
    formula = str(formulas[0]) if formulas else "同一参数通过统一表达式映射到所有表征"
    widget_config = {
        "type": plan.get("interactive_type", "simulation"),
        "concept": topic,
        "variables": variables,
        "ir": {"family": "linked_coordinate", "version": ir.get("version")},
    }
    runtime = _RUNTIME_SCRIPT.replace("__SCENE_IR__", ir_json)
    runtime = runtime.replace("__DEFAULT_STATE__", _json_for_script(defaults))
    runtime = runtime.replace("__INITIAL_CAPTION__", _json_for_script(caption))
    runtime = runtime.replace("__INITIAL_FORMULA__", _json_for_script(formula))
    gsap_url = html.escape(get_gsap_core_cdn_url(), quote=True)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<script src="{gsap_url}"></script>
<style>
:root{{--linked-primary:{primary};--linked-ink:#17362d;--linked-grid:#dce8e3}}
.linked-svg{{display:block;width:100%;height:100%;min-height:280px;background:linear-gradient(145deg,#fff,#f5faf8)}}
.linked-grid{{stroke:var(--linked-grid);stroke-width:1;vector-effect:non-scaling-stroke}}
.linked-axis{{stroke:#78958a;stroke-width:1.5;vector-effect:non-scaling-stroke}}
.linked-curve{{fill:none;stroke-width:3;stroke-linecap:round;stroke-linejoin:round;vector-effect:non-scaling-stroke}}
.linked-link{{fill:none;stroke-width:1.5;vector-effect:non-scaling-stroke}}
.linked-point{{stroke:#fff;stroke-width:2;vector-effect:non-scaling-stroke}}
.linked-label{{fill:var(--linked-ink);font-size:15px;font-weight:650}}
.linked-controls{{display:flex;flex-wrap:wrap;gap:10px;width:100%}}
.linked-control{{display:grid;grid-template-rows:auto 44px;gap:4px;min-width:min(180px,100%);flex:1}}
.linked-actions{{display:flex;gap:8px;flex-wrap:wrap;width:100%}}
.linked-actions button{{min-height:44px;flex:1 1 96px;border:1px solid #b7d5c9;border-radius:8px;background:#fff;color:var(--linked-ink);padding:8px 12px}}
.linked-actions button:first-child{{background:var(--linked-primary);border-color:var(--linked-primary);color:#fff}}
.linked-readout{{display:flex;gap:12px;flex-wrap:wrap;color:var(--linked-ink)}}
.linked-flow{{margin:0;padding-left:20px;line-height:1.7}}
.linked-flow li[aria-current="step"]{{color:#047857;font-weight:700}}
</style>
<script type="application/json" id="widget-config">{_json_for_script(widget_config)}</script>
</head>
<body>
<header data-region="learning-goal"><h1>{title}</h1><p>{goal}</p></header>
<section id="aetherviz-stage" aria-label="{topic_text}互动舞台">
  <svg class="linked-svg" data-role="main-visual" viewBox="0 0 960 560" role="img" aria-label="{topic_text}">
    <g id="linked-coordinate-systems"></g>
    <g id="linked-curves"></g>
    <g id="linked-links"></g>
    <g id="linked-points"></g>
  </svg>
</section>
<section class="linked-controls" data-region="controls">
  {controls}
  <div class="linked-actions">
    <button id="play-animation" type="button">播放</button>
    <button id="pause-animation" type="button">暂停</button>
    <button id="reset-animation" type="button">重置</button>
    <label>速度 <select id="animation-speed"><option value="0.5">0.5×</option><option value="1" selected>1×</option><option value="2">2×</option></select></label>
  </div>
</section>
<section class="linked-readout" data-region="caption"><p id="animation-caption">{html.escape(caption)}</p><p id="linked-values"></p></section>
<section data-region="formula"><p id="animation-formula">{html.escape(formula)}</p></section>
<ol class="linked-flow" data-region="teaching-flow">{flow_markup}</ol>
<script>{runtime}</script>
</body>
</html>"""


def _variables(plan: dict[str, Any]) -> list[dict[str, Any]]:
    spec = plan.get("interactive_spec") if isinstance(plan.get("interactive_spec"), dict) else {}
    return [
        item
        for item in spec.get("variables", [])
        if isinstance(item, dict) and not item.get("computed") and str(item.get("name") or "").strip()
    ][:3]


def _variable_control(variable: dict[str, Any]) -> str:
    name = str(variable.get("name") or "parameter")
    safe_id = _SAFE_ID_RE.sub("-", name).strip("-") or "parameter"
    label = html.escape(str(variable.get("label") or name))
    minimum = _finite(variable.get("min"), 0)
    maximum = _finite(variable.get("max"), minimum + 1)
    default = min(max(_finite(variable.get("default"), minimum), minimum), maximum)
    step = max(_finite(variable.get("step"), (maximum - minimum) / 100 or 0.01), 0.000001)
    unit = html.escape(str(variable.get("unit") or ""))
    return (
        '<label class="linked-control">'
        f'<span>{label} <output data-output-for="{html.escape(name, quote=True)}">{default:g}{unit}</output></span>'
        f'<input id="linked-{html.escape(safe_id, quote=True)}" type="range" data-var="{html.escape(name, quote=True)}" '
        f'min="{minimum:g}" max="{maximum:g}" step="{step:g}" value="{default:g}">'
        "</label>"
    )


def _finite(value: object, fallback: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return float(fallback)
    return result if result == result and result not in {float("inf"), float("-inf")} else float(fallback)


def _json_for_script(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


_RUNTIME_SCRIPT = r"""(function(){
'use strict';
const IR=Object.freeze(__SCENE_IR__);
const DEFAULT_STATE=Object.freeze(__DEFAULT_STATE__);
const state=Object.assign({},DEFAULT_STATE);
const SVG_NS='http://www.w3.org/2000/svg';
const systemsLayer=document.getElementById('linked-coordinate-systems');
const curvesLayer=document.getElementById('linked-curves');
const linksLayer=document.getElementById('linked-links');
const pointsLayer=document.getElementById('linked-points');
const caption=document.getElementById('animation-caption');
const formula=document.getElementById('animation-formula');
const valueReadout=document.getElementById('linked-values');
const steps=Array.from(document.querySelectorAll('[data-region="teaching-flow"] [data-step]'));
const systemMap=new Map(IR.coordinate_systems.map((item)=>[item.id,item]));
const pointNodes=new Map(),curveNodes=new Map(),linkNodes=new Map(),labelNodes=new Map();
let controller=null,currentProgress=0,playing=false;
function finite(value){const number=Number(value);if(!Number.isFinite(number))throw new Error('ir_non_finite_number');return number;}
function applyOp(name,args){const n=(index)=>finite(args[index]);if(name==='add')return args.reduce((sum,value)=>sum+finite(value),0);if(name==='sub')return args.slice(1).reduce((value,item)=>value-finite(item),n(0));if(name==='mul')return args.reduce((value,item)=>value*finite(item),1);if(name==='div')return args.slice(1).reduce((value,item)=>{const divisor=finite(item);if(divisor===0)throw new Error('ir_division_by_zero');return value/divisor;},n(0));if(name==='pow')return Math.pow(n(0),n(1));if(name==='mod')return n(0)%n(1);if(name==='min')return Math.min(...args.map(finite));if(name==='max')return Math.max(...args.map(finite));if(name==='clamp')return Math.max(n(1),Math.min(n(2),n(0)));if(name==='neg')return -n(0);if(name==='abs')return Math.abs(n(0));if(name==='sqrt')return Math.sqrt(n(0));if(name==='sin')return Math.sin(n(0));if(name==='cos')return Math.cos(n(0));if(name==='tan')return Math.tan(n(0));if(name==='asin')return Math.asin(n(0));if(name==='acos')return Math.acos(n(0));if(name==='atan')return Math.atan(n(0));if(name==='atan2')return Math.atan2(n(0),n(1));if(name==='exp')return Math.exp(n(0));if(name==='log')return Math.log(n(0));if(name==='deg_to_rad')return n(0)*Math.PI/180;throw new Error('ir_unknown_operator:'+name);}
function evaluator(locals){const cache=new Map(),resolving=new Set(),defs=Object.fromEntries(IR.definitions.map((item)=>[item.name,item.value]));function evaluate(node){if(typeof node==='number')return finite(node);if(!node||typeof node!=='object'||Array.isArray(node))throw new Error('ir_invalid_expression');if(Object.prototype.hasOwnProperty.call(node,'state'))return finite(state[node.state]);if(Object.prototype.hasOwnProperty.call(node,'local'))return finite(locals[node.local]);if(Object.prototype.hasOwnProperty.call(node,'var')){if(cache.has(node.var))return cache.get(node.var);if(resolving.has(node.var)||!Object.prototype.hasOwnProperty.call(defs,node.var))throw new Error('ir_invalid_definition:'+node.var);resolving.add(node.var);const value=evaluate(defs[node.var]);resolving.delete(node.var);cache.set(node.var,value);return value;}if(Object.prototype.hasOwnProperty.call(node,'op'))return finite(applyOp(node.op,node.args.map(evaluate)));throw new Error('ir_invalid_expression');}return evaluate;}
function mapPoint(system,x,y,evaluate){const xd=system.x_domain.map(evaluate),yd=system.y_domain.map(evaluate);return {x:system.x+(x-xd[0])*system.width/(xd[1]-xd[0]),y:system.y+system.height-(y-yd[0])*system.height/(yd[1]-yd[0])};}
function svgNode(tag,attrs,parent){const node=document.createElementNS(SVG_NS,tag);for(const [key,value] of Object.entries(attrs))node.setAttribute(key,String(value));parent.appendChild(node);return node;}
function buildSystems(){systemsLayer.replaceChildren();const evaluate=evaluator({});for(const system of IR.coordinate_systems){const xd=system.x_domain.map(evaluate),yd=system.y_domain.map(evaluate);const origin=mapPoint(system,0,0,evaluate);svgNode('rect',{x:system.x,y:system.y,width:system.width,height:system.height,rx:8,fill:'#fff',stroke:'#d9e7e1'},systemsLayer);for(let index=1;index<5;index++){const x=system.x+system.width*index/5,y=system.y+system.height*index/5;svgNode('line',{x1:x,y1:system.y,x2:x,y2:system.y+system.height,class:'linked-grid'},systemsLayer);svgNode('line',{x1:system.x,y1:y,x2:system.x+system.width,y2:y,class:'linked-grid'},systemsLayer);}if(origin.x>=system.x&&origin.x<=system.x+system.width)svgNode('line',{x1:origin.x,y1:system.y,x2:origin.x,y2:system.y+system.height,class:'linked-axis'},systemsLayer);if(origin.y>=system.y&&origin.y<=system.y+system.height)svgNode('line',{x1:system.x,y1:origin.y,x2:system.x+system.width,y2:origin.y,class:'linked-axis'},systemsLayer);const label=svgNode('text',{x:system.x+10,y:system.y+22,class:'linked-label'},systemsLayer);label.textContent=system.label;label.setAttribute('aria-label',system.label+'，横轴 '+xd[0].toFixed(2)+' 到 '+xd[1].toFixed(2)+'，纵轴 '+yd[0].toFixed(2)+' 到 '+yd[1].toFixed(2));}}
function buildNodes(){curvesLayer.replaceChildren();linksLayer.replaceChildren();pointsLayer.replaceChildren();curveNodes.clear();pointNodes.clear();linkNodes.clear();labelNodes.clear();for(const curve of IR.curves)curveNodes.set(curve.id,svgNode('path',{class:'linked-curve',stroke:curve.stroke,pathLength:1,'data-curve-id':curve.id},curvesLayer));for(const link of IR.links)linkNodes.set(link.id,svgNode('line',{class:'linked-link',stroke:link.stroke,'stroke-dasharray':link.dash,'data-link-id':link.id},linksLayer));for(const point of IR.points){pointNodes.set(point.id,svgNode('circle',{class:'linked-point',r:point.radius,fill:point.fill,'data-point-id':point.id},pointsLayer));if(point.label){const label=svgNode('text',{class:'linked-label','data-label-for':point.id},pointsLayer);label.textContent=point.label;labelNodes.set(point.id,label);}}}
function render(){const evaluate=evaluator({}),screenPoints=new Map(),readout=[];buildSystems();for(const curve of IR.curves){const system=systemMap.get(curve.system),domain=curve.domain.map(evaluate),parts=[];for(let index=0;index<curve.samples;index++){const t=domain[0]+(domain[1]-domain[0])*index/(curve.samples-1),localEval=evaluator({[curve.parameter]:t}),point=mapPoint(system,localEval(curve.x),localEval(curve.y),evaluate);parts.push((index?'L':'M')+point.x.toFixed(3)+' '+point.y.toFixed(3));}const curveNode=curveNodes.get(curve.id);curveNode.setAttribute('d',parts.join(' '));if(curve.reveal){const start=evaluate(curve.reveal.from),end=evaluate(curve.reveal.to),value=evaluate(curve.reveal.value),ratio=Math.max(0,Math.min(1,(value-start)/(end-start)));curveNode.setAttribute('stroke-dasharray',ratio.toFixed(6)+' 1');curveNode.setAttribute('visibility',ratio<=0?'hidden':'visible');}else{curveNode.removeAttribute('stroke-dasharray');curveNode.setAttribute('visibility','visible');}}for(const point of IR.points){const system=systemMap.get(point.system),x=evaluate(point.x),y=evaluate(point.y),screen=mapPoint(system,x,y,evaluate),node=pointNodes.get(point.id);screenPoints.set(point.id,screen);node.setAttribute('cx',screen.x.toFixed(3));node.setAttribute('cy',screen.y.toFixed(3));const label=labelNodes.get(point.id);if(label){label.setAttribute('x',(screen.x+10).toFixed(3));label.setAttribute('y',(screen.y-10).toFixed(3));}readout.push(point.label+': ('+x.toFixed(2)+', '+y.toFixed(2)+')');}for(const link of IR.links){const start=screenPoints.get(link.from),end=screenPoints.get(link.to),node=linkNodes.get(link.id);node.setAttribute('x1',start.x.toFixed(3));node.setAttribute('y1',start.y.toFixed(3));node.setAttribute('x2',end.x.toFixed(3));node.setAttribute('y2',end.y.toFixed(3));}for(const input of document.querySelectorAll('[data-var]')){const key=input.getAttribute('data-var');if(Object.prototype.hasOwnProperty.call(state,key)){input.value=String(state[key]);const output=document.querySelector('[data-output-for="'+CSS.escape(key)+'"]');if(output)output.textContent=Number(state[key]).toFixed(2);}}valueReadout.textContent=readout.join(' · ');const active=Math.max(0,Math.min(steps.length-1,Math.floor(currentProgress*Math.max(steps.length,1))));steps.forEach((step,index)=>index===active?step.setAttribute('aria-current','step'):step.removeAttribute('aria-current'));caption.textContent=__INITIAL_CAPTION__;formula.textContent=__INITIAL_FORMULA__;}
function applyProgress(progress){currentProgress=Math.max(0,Math.min(1,Number(progress)||0));const evaluate=evaluator({}),animation=IR.animation;state[animation.variable]=evaluate(animation.from)+(evaluate(animation.to)-evaluate(animation.from))*currentProgress;render();if(currentProgress>=1)playing=false;}
function update(patch){for(const key of Object.keys(DEFAULT_STATE)){if(Object.prototype.hasOwnProperty.call(patch||{},key)){const value=Number(patch[key]);if(Number.isFinite(value))state[key]=value;}}render();return getState();}
function play(){playing=true;controller.play();}
function pause(){playing=false;controller.pause();}
function reset(){playing=false;Object.assign(state,DEFAULT_STATE);controller.reset();currentProgress=0;render();}
function setSpeed(value){controller.setSpeed(value);}
function getState(){return Object.assign({},state,{progress:currentProgress,isPlaying:playing,irFamily:'linked_coordinate'});}
function bindControls(){document.getElementById('play-animation').addEventListener('click',play);document.getElementById('pause-animation').addEventListener('click',pause);document.getElementById('reset-animation').addEventListener('click',reset);document.getElementById('animation-speed').addEventListener('change',(event)=>setSpeed(event.target.value));for(const input of document.querySelectorAll('[data-var]'))input.addEventListener('input',(event)=>update({[event.target.getAttribute('data-var')]:event.target.value}));}
function handleWidgetAction(event){const message=event.data||{};if(message.type==='SET_WIDGET_STATE'&&message.state)update(message.state);if(message.type==='HIGHLIGHT_ELEMENT'&&message.target){const node=document.querySelector(message.target);if(node)node.setAttribute('data-highlighted','true');}if(message.type==='ANNOTATE_ELEMENT'&&message.content)caption.textContent=String(message.content);if(message.type==='REVEAL_ELEMENT'&&message.target){const node=document.querySelector(message.target);if(node)node.hidden=false;}}
try{if(!window.AetherVizAnimationController)throw new Error('missing_animation_controller');buildSystems();buildNodes();render();controller=window.AetherVizAnimationController.create({duration:Number(IR.animation.duration)||4,update:applyProgress,ease:'power1.inOut'});bindControls();window.addEventListener('message',handleWidgetAction);window.AetherVizRuntime={play,pause,reset,setSpeed,update,getState};window.__AETHERVIZ_RUNTIME_READY__=true;}catch(error){window.__AETHERVIZ_RUNTIME_ERROR__=String(error&&error.message||error);caption.textContent='课件初始化失败：'+window.__AETHERVIZ_RUNTIME_ERROR__;}
})();"""
