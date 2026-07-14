"""Generate a bounded scene module and assemble it with the server lifecycle scaffold."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langsmith import traceable
from langsmith.run_helpers import get_current_run_tree

from aetherviz_service.aetherviz.agents.html_agent import HtmlStreamResult, build_html_progress_payload
from aetherviz_service.aetherviz.agents.model_factory import create_chat_model, extract_llm_text, has_primary_llm_config
from aetherviz_service.aetherviz.tools.recomposition_contract import validate_scene_module
from aetherviz_service.aetherviz.tools.recomposition_ir import (
    GEOMETRY_IR_MAX_CHARS,
    GEOMETRY_IR_VERSION,
    compile_geometry_ir,
    extract_geometry_ir_from_scene_source,
    geometry_ir_candidates_response_schema,
    geometry_ir_response_schema,
    normalize_geometry_ir,
    parse_geometry_ir,
    parse_geometry_ir_candidates,
)
from aetherviz_service.aetherviz.tools.recomposition_ranking import (
    public_geometry_ir_ranking,
    rank_geometry_ir_candidates,
)
from aetherviz_service.aetherviz.tools.recomposition_runtime import (
    assemble_recomposition_business_html,
    build_deterministic_scene_module,
)
from aetherviz_service.aetherviz.tools.recomposition_waypoints import (
    complete_intermediate_waypoints,
)
from aetherviz_service.config import settings

logger = logging.getLogger(__name__)

SCENE_SYSTEM_PROMPT = f"""你是二维 SVG 几何切分重排的结构化几何 IR 生成器。
只输出用户要求的 JSON 对象，不输出 Markdown、JavaScript、HTML、注释或解释。单个 IR 的 version 必须是 {GEOMETRY_IR_VERSION}。
顶层结构：{{"version":string,"definitions":array,"pieces":array,"frames":array}}。
definitions 使用 [{{"name":"名称","value":表达式}}]，最多 32 项；可引用 repeat 局部变量。pieces 包含 1~16 个通用图元模板，展开后总数 1~80。
图元结构：{{"repeat":null或{{"count":表达式,"index":"i"}},"id":表达式,"tag":"polygon","attrs":[{{"name":"points","value":表达式}}],"source":完整变换,"target":完整变换,"keyframes":array}}。
tag 仅允许 path、polygon、polyline、rect、circle、ellipse、line。属性按 SVG 图元使用 d、points、x/y、x1/y1/x2/y2、cx/cy/r/rx/ry、width/height、fill、stroke、stroke-width、stroke-dasharray、opacity、class；禁止事件、style、href 和 transform 属性，禁止空图元和文字图元。
变换只允许 x、y、rotation、scale、opacity，值均为受限表达式；scale 必须大于 0，opacity 在 0~1，至少一个图元的 source/target 不同。
表达式仅有四种形态：数值或字符串；{{"state":"计划变量名"}}；{{"var":"definition名"}}；repeat 内可用 {{"local":"i"}}；或 {{"op":"操作符","args":[...]}}。
操作符白名单：add,sub,mul,div,pow,mod,min,max,clamp,neg,abs,sqrt,sin,cos,tan,asin,acos,atan,atan2,hypot,round,floor,ceil,rad_to_deg,deg_to_rad,eq,ne,lt,lte,gt,gte,if,concat,fixed,points,sector_path。atan2 参数为 y,x；sub/div 可接收 2~16 个参数并按从左到右计算。
points 的 args 是若干 [x,y] 表达式对；sector_path 参数依次为 cx,cy,r,startAngle,endAngle，可选第 6 个 sweep(0/1)，角度用弧度。不得发明操作符、字段或引用计划外 state。
frames 必须与 stage_requirements 一一对应，使用 3~5 个静态对象 {{"stage_id":"计划阶段 id","at":与计划阶段一致的数值,"caption":"教学文本","formula":"公式或关系","step":非负整数}}。每个中间 stage_requirements 都必须在图元 keyframes 中出现同一 at；至少达到该阶段 min_piece_ratio 的图元要在该时刻形成区别于 source、target 且偏离首尾直接线性插值的独立几何状态。keyframes 首尾 at 必须为 0/1，总数 3~5；不得输出只有文字说明、没有对应几何关键状态的中间阶段。
几何属性、source/target 和教学解释必须描述同一切分重排；拓扑变量只用于 repeat.count，普通几何变量只改变坐标或尺度。
同一 repeat 生成全等拼片时，attrs 必须定义统一的局部坐标几何；每片在源状态和目标状态的朝向必须只由 source/target.rotation 表达。禁止把 repeat 索引对应的绝对朝向同时编码进 attrs（例如 sector_path 的起止角）和 transform.rotation，避免重复旋转。目标声称对齐、合并或拼成整体时，必须在世界坐标下让拼片边界真实接触，且满足 target_assembly 的连通、重叠率和整体形状阈值。
必须逐项落实 recomposition_spec.proof_constraints：保持 measure_invariants，frames 按 stage_id 和 at 精确覆盖 stage_requirements，中间几何阶段满足 min_piece_ratio，最后一帧用教学文本解释 target_relations；target_relations 由服务端对 minimum/default/maximum 状态执行数值验证，其中引用的 piece_id 必须与展开后图元 id 一致。面积守恒时所有阶段禁止通过 scale 改变图元面积。
progress 不是 state 变量，IR 中严禁引用 progress；source/target 是两个完整端点，服务端负责二者之间的插值。计划变量必须写成 state 引用，只有 definitions 名称才能写成 var 引用。
所有参数在计划给出的 default/min/max 都必须产生正尺寸、有限属性、唯一 id 和可见变换。第一版只做 transform 驱动二维 SVG，不做 path morph。
优先控制在 8 个 definitions、8 个图元模板和 1 个 repeat 内；只保留证明所需的实际几何块，不生成标签背景、占位 g、虚线辅助图或装饰图元。复杂重复结构必须用 repeat 表达，不展开大段近似对象。输出前检查 JSON 引号、逗号和括号完整闭合。
通用语法示例：{{"version":"{GEOMETRY_IR_VERSION}","definitions":[{{"name":"size","value":{{"op":"mul","args":[{{"state":"scale"}},30]}}}}],"pieces":[{{"repeat":null,"id":"piece-0","tag":"polygon","attrs":[{{"name":"points","value":{{"op":"points","args":[[0,0],[{{"var":"size"}},0],[0,{{"var":"size"}}]]}}}},{{"name":"fill","value":"#34d399"}}],"source":{{"x":120,"y":160,"rotation":0,"scale":1,"opacity":1}},"target":{{"x":420,"y":260,"rotation":90,"scale":1,"opacity":1}},"keyframes":[{{"at":0,"x":120,"y":160,"rotation":0,"scale":1,"opacity":1}},{{"at":0.5,"x":250,"y":90,"rotation":35,"scale":1,"opacity":1}},{{"at":1,"x":420,"y":260,"rotation":90,"scale":1,"opacity":1}}]}}],"frames":[{{"stage_id":"source","at":0,"caption":"观察源状态","formula":"关系保持","step":0}},{{"stage_id":"transform-1","at":0.5,"caption":"观察分离后的中间状态","formula":"图元集合不变","step":1}},{{"stage_id":"target","at":1,"caption":"解释目标状态","formula":"度量关系成立","step":2}}]}}。实际 stage_id/at 必须复制计划值；只可引用用户消息列出的 allowed_state_variables；若其中没有 scale，不得照抄示例。
每个 IR 不超过 {GEOMETRY_IR_MAX_CHARS} 字符。不得针对圆、梯形或其他单个知识点调用专用模板；只能组合上述通用图元与表达式。"""


class GeometryIRGenerationError(ValueError):
    def __init__(self, raw_text: str, report: dict[str, Any]) -> None:
        super().__init__(",".join(str(item.get("type")) for item in report.get("errors", [])))
        self.raw_text = raw_text
        self.report = report


def stream_generate_recomposition_html(
    topic: str,
    plan: dict[str, Any],
) -> Iterator[dict[str, Any] | HtmlStreamResult]:
    runner = (
        _traced_stream_generate_recomposition_html
        if settings.langsmith_tracing and get_current_run_tree() is not None
        else _stream_generate_recomposition_html_impl
    )
    yield from runner(topic, plan)


@traceable(
    name="aetherviz.recomposition_scene_generation",
    run_type="chain",
    metadata={"component": "aetherviz", "stage": "scene_generation"},
    process_inputs=lambda inputs: {
        "topic": inputs.get("topic"),
        "representation_type": ((inputs.get("plan") or {}).get("knowledge_profile") or {}).get(
            "representation_type"
        ),
    },
    reduce_fn=lambda items: _summarize_scene_stream(items),
)
def _traced_stream_generate_recomposition_html(
    topic: str,
    plan: dict[str, Any],
) -> Iterator[dict[str, Any] | HtmlStreamResult]:
    yield from _stream_generate_recomposition_html_impl(topic, plan)


def _stream_generate_recomposition_html_impl(
    topic: str,
    plan: dict[str, Any],
) -> Iterator[dict[str, Any] | HtmlStreamResult]:
    yield build_html_progress_payload(
        [
            {"content": "生成结构化几何 IR", "status": "in_progress"},
            {"content": "装配服务端动画生命周期", "status": "pending"},
        ]
    )
    degraded = False
    source = ""
    repair_input = ""
    repair_report: dict[str, Any] | None = None
    if has_primary_llm_config():
        try:
            source, degraded = _generate_scene_source(topic, plan)
        except GeometryIRGenerationError as exc:
            repair_input = exc.raw_text
            repair_report = exc.report
            degraded = True
        except GeneratorExit:
            raise
        except Exception as exc:
            logger.warning("geometry IR generation failed; using generic contract fallback: %s", exc)
            degraded = True
    else:
        degraded = True
    if repair_input and repair_report and has_primary_llm_config():
        try:
            source = _repair_scene_source(topic, plan, repair_input, repair_report)
        except Exception as exc:
            logger.warning("geometry IR bounded repair failed: %s", exc)
    if not source and repair_report and _has_target_assembly_constraints(plan):
        raise GeometryIRGenerationError(repair_input, repair_report)
    report = validate_scene_module(source)
    if not report["ok"]:
        if source:
            logger.warning(
                "scene module rejected; using generic contract fallback: %s",
                [error.get("type") for error in report.get("errors", [])],
            )
        source = build_deterministic_scene_module(plan)
        fallback_report = validate_scene_module(source)
        if not fallback_report["ok"]:
            raise ValueError(f"deterministic scene module violated contract: {fallback_report['errors']}")
        degraded = True
    business_html = assemble_recomposition_business_html(source, plan, topic)
    yield build_html_progress_payload(
        [
            {"content": "生成结构化几何 IR", "status": "completed"},
            {"content": "装配服务端动画生命周期", "status": "completed"},
        ]
    )
    yield HtmlStreamResult(html=business_html, degraded=degraded, truncated=False)


def _generate_scene_source(topic: str, plan: dict[str, Any]) -> tuple[str, bool]:
    source, timed_out, _ranking = _generate_ranked_scene_source(topic, plan)
    return source, timed_out


def _generate_ranked_scene_source(
    topic: str, plan: dict[str, Any]
) -> tuple[str, bool, dict[str, Any]]:
    prompt = _build_scene_prompt(topic, plan)
    raw_text = ""
    timed_out = False
    deadline = time.monotonic() + max(settings.aetherviz_html_timeout_seconds, 1)
    messages = [SystemMessage(content=SCENE_SYSTEM_PROMPT), HumanMessage(content=prompt)]
    for chunk in _stream_scene_response(
        messages, response_schema=geometry_ir_candidates_response_schema()
    ):
        if time.monotonic() > deadline:
            timed_out = True
            break
        text = extract_llm_text(chunk)
        if text:
            raw_text += text
            if len(raw_text) > GEOMETRY_IR_MAX_CHARS * 3 + 2_048:
                timed_out = True
                break
    try:
        candidates = parse_geometry_ir_candidates(raw_text)
    except ValueError as exc:
        raise GeometryIRGenerationError(raw_text, _parse_error_report(str(exc))) from exc
    ranking = _trace_rank_geometry_ir_candidates(candidates, plan)
    ranking["strategy"] = "raw_candidate"
    _log_ranking(ranking)
    if not ranking["ok"]:
        ranking = _attempt_waypoint_completion(candidates, plan, ranking)
        _log_ranking(ranking)
    if not ranking["ok"]:
        repair_candidate = ranking.get("repair_candidate")
        repair_input = (
            json.dumps(repair_candidate, ensure_ascii=False, separators=(",", ":"))
            if isinstance(repair_candidate, dict)
            else raw_text
        )
        raise GeometryIRGenerationError(repair_input, _ranking_error_report(ranking))
    geometry_ir = ranking["selected_ir"]
    return compile_geometry_ir(geometry_ir, plan), timed_out, ranking


def _attempt_waypoint_completion(
    candidates: list[object], plan: dict[str, Any], initial_ranking: dict[str, Any]
) -> dict[str, Any]:
    completed_candidates: list[object] = []
    completion_reports: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        candidate_report = initial_ranking["candidates"][index]
        hard_failures = set(candidate_report.get("hard_failures", []))
        eligible_for_completion = bool(hard_failures) and hard_failures <= {
            "teaching:missing_intermediate_geometry_stage"
        }
        if eligible_for_completion:
            completion = complete_intermediate_waypoints(candidate, plan)
            completed_candidates.append(completion.get("ir") or candidate)
            completion_reports.append(
                {
                    "index": index,
                    "attempted": True,
                    "ok": completion["ok"],
                    "changed": completion["changed"],
                    "reason": completion["reason"],
                    "completed_stage_ids": completion.get("completed_stage_ids", []),
                }
            )
        else:
            completed_candidates.append(candidate)
            completion_reports.append(
                {
                    "index": index,
                    "attempted": False,
                    "ok": False,
                    "changed": False,
                    "reason": "candidate_has_non_waypoint_hard_failures",
                    "hard_failures": sorted(hard_failures),
                }
            )
    completed_ranking = _trace_rank_geometry_ir_candidates(
        completed_candidates,
        plan,
        origins=["waypoint" if report["attempted"] else "model" for report in completion_reports],
    )
    completed_ranking.update(
        {
            "strategy": "deterministic_waypoint_completion",
            "initial_ranking": public_geometry_ir_ranking(initial_ranking),
            "waypoint_completion": completion_reports,
        }
    )
    return completed_ranking


def _log_ranking(ranking: dict[str, Any]) -> None:
    logger.info(
        "geometry IR deterministic ranking: %s",
        json.dumps(
            {
                "strategy": ranking.get("strategy"),
                "selected_index": ranking["selected_index"],
                "ranking": ranking["ranking"],
                "waypoint_completion": ranking.get("waypoint_completion", []),
                "candidates": [
                    {
                        "index": item["index"],
                        "score": item["score"],
                        "eligible": item["eligible"],
                        "hard_failures": item["hard_failures"],
                        "components": item["components"],
                        "fingerprint": item["fingerprint"],
                    }
                    for item in ranking["candidates"]
                ],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    )


@traceable(
    name="aetherviz.geometry_ir_ranking",
    run_type="chain",
    metadata={"component": "aetherviz", "stage": "geometry_ir_ranking"},
    process_inputs=lambda inputs: {
        "candidate_count": len(inputs.get("candidates") or []),
        "origins": inputs.get("origins"),
        "measure_invariant_count": len(
            (((inputs.get("plan") or {}).get("recomposition_spec") or {}).get("proof_constraints") or {}).get(
                "measure_invariants", []
            )
        ),
        "stage_requirement_count": len(
            (((inputs.get("plan") or {}).get("recomposition_spec") or {}).get("proof_constraints") or {}).get(
                "stage_requirements", []
            )
        ),
        "target_assembly": (
            (((inputs.get("plan") or {}).get("recomposition_spec") or {}).get("proof_constraints") or {}).get(
                "target_assembly", []
            )
        ),
    },
    process_outputs=lambda outputs: _trace_ranking_summary(outputs),
)
def _trace_rank_geometry_ir_candidates(
    candidates: list[object],
    plan: dict[str, Any],
    *,
    origins: list[str] | None = None,
) -> dict[str, Any]:
    return rank_geometry_ir_candidates(candidates, plan, origins=origins)


def _trace_ranking_summary(ranking: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": ranking.get("ok"),
        "selected_index": ranking.get("selected_index"),
        "selected_score": ranking.get("selected_score"),
        "decision": ranking.get("decision"),
        "candidates": [
            {
                "index": item.get("index"),
                "score": item.get("score"),
                "eligible": item.get("eligible"),
                "hard_failures": item.get("hard_failures", []),
                "components": item.get("components", {}),
                "assembly_states": item.get("details", {}).get("target_assembly", {}).get("states", []),
                "source_assembly_states": item.get("details", {}).get("target_assembly", {}).get(
                    "source_states", []
                ),
                "unavailable_relations": [
                    warning
                    for warning in item.get("details", {}).get("mathematics", {}).get("warnings", [])
                    if warning.get("type") == "target_relation_unavailable"
                ],
                "fingerprint": item.get("fingerprint"),
            }
            for item in ranking.get("candidates", [])
        ],
    }


def _repair_scene_source(
    topic: str,
    plan: dict[str, Any],
    source: str,
    report: dict[str, Any],
) -> str:
    candidate = source
    if "const sceneIR=" in source:
        candidate = json.dumps(
            extract_geometry_ir_from_scene_source(source),
            ensure_ascii=False,
            separators=(",", ":"),
        )
    prompt = (
        "修复以下结构化几何 IR。只输出满足系统契约的单个 JSON 对象；保留原教学几何意图，"
        "只修复报告中的 schema、边界、有限数值、唯一 id 或源/目标变换问题。将计划变量写成 state，"
        "definitions 才写成 var；删除所有 progress 依赖和空图元，让 source/target 保持为固定端点。"
        "frames 必须复制计划 stage_requirements 的 id/at；每个中间阶段为足够比例图元补充同 at 的非线性几何 keyframe。"
        "同一 repeat 的全等拼片使用统一局部几何，只通过 source/target.rotation 表达各阶段朝向；"
        "若报告含目标拼合失败，调整目标世界坐标使拼片连通、少重叠并达到声明的整体形状阈值。"
        "将结果精简到最多 8 个 definitions、8 个图元模板和 1 个 repeat，并检查 JSON 完整闭合。\n"
        + json.dumps(
            {
                "topic": topic,
                "allowed_state_variables": _allowed_state_variables(plan),
                "recomposition_spec": plan.get("recomposition_spec"),
                "errors": report.get("errors", []),
                "candidate": candidate,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    raw_text = ""
    messages = [SystemMessage(content=SCENE_SYSTEM_PROMPT), HumanMessage(content=prompt)]
    for chunk in _stream_scene_response(messages):
        raw_text += extract_llm_text(chunk)
        if len(raw_text) > GEOMETRY_IR_MAX_CHARS + 1_024:
            break
    geometry_ir = normalize_geometry_ir(parse_geometry_ir(raw_text), plan)
    ranking = _trace_rank_geometry_ir_candidates([geometry_ir], plan, origins=["repair"])
    if not ranking["ok"]:
        raise GeometryIRGenerationError(raw_text, _ranking_error_report(ranking))
    return compile_geometry_ir(ranking["selected_ir"], plan)


def _build_scene_prompt(topic: str, plan: dict[str, Any]) -> str:
    allowed_state_variables = _allowed_state_variables(plan)
    compact = {
        "topic": topic,
        "allowed_state_variables": allowed_state_variables,
        "goal": plan.get("goal"),
        "knowledge_profile": plan.get("knowledge_profile"),
        "recomposition_spec": plan.get("recomposition_spec"),
        "interactive_spec": plan.get("interactive_spec"),
        "teaching_flow": plan.get("teaching_flow"),
        "formulas": plan.get("formulas"),
        "discipline_spec": plan.get("discipline_spec"),
    }
    return (
        "根据以下已确认计划一次生成 3 个相互独立的通用结构化几何 IR 候选。顶层严格输出 "
        "{\"candidates\":[IR1,IR2,IR3]}，不得少于 2 个，不生成 HTML。每个候选应采用不同但通用的切分或运动布局；"
        "先确定切分后稳定图元集合，再用 source/target 表达同一组 id 的重排；"
        "不得输出可执行代码，也不得使用任何知识点专用分支。只能用 allowed_state_variables，严禁 progress；"
        "画布为 960×560，默认状态的主体图形建议占 160~420px，避免把 1~8 这类抽象参数直接当像素尺寸。\n"
        + json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
    )


def _has_target_assembly_constraints(plan: dict[str, Any]) -> bool:
    spec = plan.get("recomposition_spec") if isinstance(plan.get("recomposition_spec"), dict) else {}
    proof = spec.get("proof_constraints") if isinstance(spec.get("proof_constraints"), dict) else {}
    constraints = proof.get("target_assembly")
    return isinstance(constraints, list) and any(isinstance(item, dict) for item in constraints)


def _parse_error_report(message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "severity": "error",
        "summary": "结构化几何 IR 解析失败",
        "errors": [{"type": "geometry_ir_parse", "message": message, "line": None}],
        "warnings": [],
    }


def _ranking_error_report(ranking: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": False,
        "severity": "error",
        "summary": "所有几何 IR 候选均未通过确定性硬校验",
        "errors": [
            {
                "type": "geometry_ir_candidate_rejected",
                "candidate_index": item["index"],
                "hard_failures": item["hard_failures"],
                "score": item["score"],
                "assembly_diagnostics": item.get("details", {}).get("target_assembly", {}),
                "teaching_diagnostics": _compact_teaching_diagnostics(
                    item.get("details", {}).get("teaching_semantics", {})
                ),
            }
            for item in ranking.get("candidates", [])
        ],
        "warnings": [],
        "ranking": public_geometry_ir_ranking(ranking),
    }


def _compact_teaching_diagnostics(report: object) -> dict[str, Any]:
    if not isinstance(report, dict):
        return {}
    failed_checks: list[dict[str, Any]] = []
    for check in report.get("checks", []):
        if not isinstance(check, dict) or check.get("kind") != "intermediate_geometry":
            continue
        if float(check.get("ratio", 0)) >= float(check.get("required_ratio", 1)):
            continue
        evidence = [
            item
            for item in check.get("piece_evidence", [])
            if isinstance(item, dict) and not item.get("evidenced")
        ]
        failed_checks.append(
            {
                "stage_id": check.get("name"),
                "state": check.get("state"),
                "at": check.get("at"),
                "ratio": check.get("ratio"),
                "required_ratio": check.get("required_ratio"),
                "reason_counts": check.get("reason_counts", {}),
                "failed_piece_evidence": evidence[:16],
                "omitted_failed_pieces": max(0, len(evidence) - 16),
            }
        )
    return {
        "error_types": sorted(
            {
                str(item.get("type"))
                for item in report.get("errors", [])
                if isinstance(item, dict)
            }
        ),
        "failed_intermediate_checks": failed_checks,
    }


def _allowed_state_variables(plan: dict[str, Any]) -> list[str]:
    interactive = plan.get("interactive_spec") if isinstance(plan.get("interactive_spec"), dict) else {}
    return [
        str(item.get("name"))
        for item in interactive.get("variables", [])
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    ]


def _stream_scene_response(
    messages: list[SystemMessage | HumanMessage],
    *,
    response_schema: dict[str, Any] | None = None,
) -> Iterator[Any]:
    """Prefer strict schema decoding; retry once with JSON mode for compatible gateways."""
    try:
        yield from create_chat_model(
            "scene", response_schema=response_schema or geometry_ir_response_schema()
        ).stream(messages)
    except GeneratorExit:
        raise
    except Exception as exc:
        logger.warning("strict geometry IR response schema unavailable; using JSON mode: %s", exc)
        yield from create_chat_model("scene").stream(messages)


def _summarize_scene_stream(items: list[dict[str, Any] | HtmlStreamResult]) -> dict[str, Any]:
    result = next((item for item in reversed(items) if isinstance(item, HtmlStreamResult)), None)
    if result is None:
        return {"completed": False}
    return {
        "completed": True,
        "chars": len(result.html),
        "degraded": result.degraded,
        "truncated": result.truncated,
    }
