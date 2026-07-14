"""Static contract for model-generated geometric recomposition scene modules."""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from aetherviz_service.aetherviz.tools.javascript_syntax import check_javascript_syntax

SCENE_MODULE_MAX_CHARS = 12_000
SCENE_MODULE_TARGET_CHARS = 8_000
REQUIRED_SCENE_METHODS = ("structureKey", "buildGeometry", "deriveFrame", "deriveDisplay")
FORBIDDEN_SCENE_PATTERNS: dict[str, re.Pattern[str]] = {
    "document": re.compile(r"\bdocument\b"),
    "window": re.compile(r"\bwindow\b"),
    "dom_creation": re.compile(r"\bcreateElement(?:NS)?\b"),
    "dom_mutation": re.compile(r"\b(?:appendChild|removeChild|replaceChildren|innerHTML)\b"),
    "dynamic_code": re.compile(r"\b(?:eval|Function)\s*\("),
    "network": re.compile(r"\b(?:fetch|XMLHttpRequest|WebSocket)\b"),
    "animation_loop": re.compile(r"\b(?:requestAnimationFrame|setInterval|setTimeout)\s*\("),
    "animation_library": re.compile(r"\bgsap\s*\."),
    "script_escape": re.compile(r"</script", re.IGNORECASE),
    "node_runtime": re.compile(r"\b(?:process|require|globalThis|__proto__)\b|\bimport\s*\("),
}


def validate_scene_module(source: str) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    text = (source or "").strip()
    if not text:
        errors.append(_issue("empty_scene_module", "Scene Module 为空"))
    if len(text) > SCENE_MODULE_MAX_CHARS:
        errors.append(
            _issue(
                "scene_module_too_long",
                f"Scene Module 长度 {len(text)} 超过上限 {SCENE_MODULE_MAX_CHARS}",
            )
        )
    if not re.search(r"\bconst\s+sceneModule\s*=\s*\{", text):
        errors.append(_issue("missing_scene_module", "缺少 const sceneModule = {...} 声明"))
    for method in REQUIRED_SCENE_METHODS:
        if not re.search(
            rf"\b{re.escape(method)}\s*(?:\([^)]*\)\s*\{{|:\s*function\s*\(|"
            rf":\s*(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>)",
            text,
        ):
            errors.append(_issue("missing_scene_method", f"Scene Module 缺少 {method} 方法", method=method))
    for name, pattern in FORBIDDEN_SCENE_PATTERNS.items():
        if pattern.search(text):
            errors.append(_issue("forbidden_scene_api", f"Scene Module 使用了禁止能力：{name}", api=name))
    syntax_error = check_javascript_syntax(text)
    if syntax_error:
        errors.append(_issue("scene_module_js_syntax", syntax_error))
    elif runtime_error := _check_scene_module_runtime(text):
        errors.append(_issue("scene_module_runtime", runtime_error))
    if "sourceTransform" not in text or "targetTransform" not in text:
        errors.append(
            _issue(
                "missing_piece_transform_states",
                "Scene Module 必须为图形块提供 sourceTransform 和 targetTransform",
            )
        )
    if len(text) > SCENE_MODULE_TARGET_CHARS:
        warnings.append(
            _issue(
                "scene_module_above_target",
                f"Scene Module 长度 {len(text)} 超过建议值 {SCENE_MODULE_TARGET_CHARS}",
            )
        )
    return {
        "ok": not errors,
        "severity": "error" if errors else "warning" if warnings else "info",
        "summary": "Scene Module 契约检查完成",
        "errors": errors,
        "warnings": warnings,
    }


def _check_scene_module_runtime(source: str) -> str | None:
    node = shutil.which("node")
    if not node:
        return None
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as temp_file:
            temp_file.write(source)
            temp_path = Path(temp_file.name)
        result = subprocess.run(
            [node, "-e", _NODE_SCENE_SMOKE, str(temp_path)],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except Exception as exc:
        return f"Scene Module 运行冒烟检查失败：{exc}"
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
    if result.returncode == 0:
        return None
    detail = next(
        (line.strip() for line in reversed((result.stderr + "\n" + result.stdout).splitlines()) if line.strip()),
        "unknown runtime error",
    )
    return detail[:500]


_NODE_SCENE_SMOKE = r"""
const fs=require('fs'),vm=require('vm');
const source=fs.readFileSync(process.argv[1],'utf8');
const prelude=`
const sceneMath=Object.freeze({
 clamp(value,min,max){return Math.max(Number(min),Math.min(Number(max),Number(value)||0));},
 lerp(start,end,t){return Number(start)+(Number(end)-Number(start))*(Number(t)||0);},
 interpolate(start,end,t){return Number(start)+(Number(end)-Number(start))*(Number(t)||0);},
 fixed(value,digits){const number=Number(value);return (Number.isFinite(number)?number:0).toFixed(Math.max(0,Math.min(6,Number(digits)||0)));},
 sectorPath(cx,cy,r,a,b){return 'M '+cx+' '+cy+' L '+(cx+r*Math.cos(a))+' '+(cy+r*Math.sin(a))+' A '+r+' '+r+' 0 '+(Math.abs(b-a)>Math.PI?1:0)+' 1 '+(cx+r*Math.cos(b))+' '+(cy+r*Math.sin(b))+' Z';},
 interpolatePieces(pieces,progress){return {pieces:pieces.map((piece)=>({id:piece.id,attrs:{transform:'translate(0 0)',opacity:'1'}}))};}
});`;
const aliases=`const clamp=sceneMath.clamp,fixed=sceneMath.fixed;const state={parameter:5,pieceCount:8,sectors:8,segments:8,scale:4,radius:4,base:6,height:4,width:6};`;
const smoke=`
if(typeof sceneModule!=='object')throw new Error('sceneModule unavailable');
const collectStateNames=(value,names=new Set())=>{if(Array.isArray(value)){for(const item of value)collectStateNames(item,names);return names;}if(!value||typeof value!=='object')return names;if(typeof value.state==='string')names.add(value.state);for(const item of Object.values(value))collectStateNames(item,names);return names;};
const requiredStateNames=typeof sceneIR==='object'?collectStateNames(sceneIR):new Set();
const states=[
 {parameter:5,pieceCount:8,sectors:8,segments:8,scale:4,radius:4,base:6,height:4,width:6},
 {parameter:1,pieceCount:4,sectors:4,segments:4,scale:1,radius:1,base:1,height:1,width:1},
 {parameter:10,pieceCount:24,sectors:24,segments:24,scale:8,radius:8,base:10,height:10,width:10}
];
for(const [index,state] of states.entries())for(const name of requiredStateNames)if(!(name in state))state[name]=[8,4,16][index];
const allowedTags=new Set(['path','polygon','polyline','rect','circle','ellipse','line','g']);
for(const state of states){
 String(sceneModule.structureKey(state));
 const geometry=sceneModule.buildGeometry(state);
 if(!geometry||!Array.isArray(geometry.pieces)||geometry.pieces.length<1||geometry.pieces.length>80)throw new Error('invalid pieces');
 const ids=new Set();let changed=false;
 for(const piece of geometry.pieces){if(!piece||!piece.id||ids.has(String(piece.id)))throw new Error('invalid piece id');ids.add(String(piece.id));if(!allowedTags.has(String(piece.tag||'path').toLowerCase()))throw new Error('invalid piece tag:'+piece.tag);for(const value of Object.values(piece.attrs||{}))if(/NaN|Infinity/.test(String(value)))throw new Error('non-finite piece attr:'+piece.id);if(!piece.sourceTransform||!piece.targetTransform||typeof piece.sourceTransform!=='object'||typeof piece.targetTransform!=='object')throw new Error('missing transform state:'+piece.id);for(const transform of [piece.sourceTransform,piece.targetTransform])for(const key of ['x','y','rotation','scale','opacity'])if(key in transform&&!Number.isFinite(Number(transform[key])))throw new Error('non-finite transform:'+piece.id+':'+key);for(const key of ['x','y','rotation','scale','opacity']){const fallback=key==='scale'||key==='opacity'?1:0;if(Number(piece.sourceTransform[key]??fallback)!==Number(piece.targetTransform[key]??fallback))changed=true;}}
 if(!changed)throw new Error('source and target transforms are identical');
 const frame=sceneModule.deriveFrame(geometry,state,.5);
 if(!frame||!Array.isArray(frame.pieces))throw new Error('invalid frame');
 sceneModule.deriveDisplay(state,.5);
}`;
try{const context=vm.createContext({}, {codeGeneration:{strings:false,wasm:false}});new vm.Script(prelude+aliases+source+smoke).runInContext(context,{timeout:200});}catch(error){console.error(String(error&&error.message||error));process.exit(1);}
"""


def _issue(issue_type: str, message: str, **details: object) -> dict[str, Any]:
    return {"type": issue_type, "message": message, "line": None, **details}
