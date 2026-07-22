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

from aetherviz_service.aetherviz.agents.model_factory import create_chat_model, extract_llm_text, has_primary_llm_config
from aetherviz_service.aetherviz.contracts.html_stream import (
    HtmlGenerationError,
    HtmlStreamResult,
    build_html_progress_payload,
)
from aetherviz_service.aetherviz.ir.recomposition.assembly import (
    scale_scene_footprints_into_canvas,
    translate_target_assembly_into_canvas,
)
from aetherviz_service.aetherviz.ir.recomposition.construction import (
    materialize_target_construction,
)
from aetherviz_service.aetherviz.ir.recomposition.contract import (
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
from aetherviz_service.aetherviz.ir.recomposition.feasibility import (
    evaluate_recomposition_plan_feasibility,
    format_recomposition_feasibility_errors,
)
from aetherviz_service.aetherviz.ir.recomposition.ranking import (
    public_geometry_ir_ranking,
    rank_geometry_ir_candidates,
)
from aetherviz_service.aetherviz.ir.recomposition.runtime import (
    assemble_recomposition_business_html,
)
from aetherviz_service.aetherviz.ir.recomposition.scene_contract import validate_scene_module
from aetherviz_service.aetherviz.ir.recomposition.waypoints import (
    complete_intermediate_waypoints,
)
from aetherviz_service.config import settings

logger = logging.getLogger(__name__)

_DETERMINISTIC_COMPLETION_MAX_ROUNDS = 3

SCENE_SYSTEM_PROMPT = f"""你是二维 SVG 几何切分重排的结构化几何 IR 生成器。
只输出用户要求的 JSON 对象，不输出 Markdown、JavaScript、HTML、注释或解释。单个 IR 的 version 必须是 {GEOMETRY_IR_VERSION}。
顶层结构：{{"version":string,"definitions":array,"pieces":array,"frames":array,"construction":null或约束对象}}。
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
当多个静态 polygon/polyline/rect 图元需要精确拼边时，优先输出 construction={{"target_boundary":null或{{"x":表达式,"y":表达式,"width":表达式,"height":表达式}},"constraints":[...]}}，由服务端把通用约束求解成 target transform。约束按数组顺序执行，只能引用无 repeat 且 id 为固定字符串的图元：attach_edge 使用 piece_id/edge/to_piece_id/to_edge/reverse；coincident_vertex 使用 piece_id/vertex/to_piece_id/to_vertex；parallel_edge、perpendicular_edge 使用两组图元和边索引；rigid_transform 使用 piece_id/完整 transform；inside_target 使用 piece_id；cover_target 使用 piece_ids/min_coverage_ratio，后二者必须同时给出 target_boundary。边索引按局部顶点顺序从 0 开始，attach_edge 两边长度必须在 minimum/default/maximum 状态一致。construction 不能代替 source/target/keyframes，target 仍提供完整初值；不得引用 circle/ellipse/path、repeat 展开 id 或自然语言锚点。
使用 sector_path 表示重复的全等径向拼片时，局部起止角必须固定为 -halfAngle/+halfAngle，源朝向使用 rad_to_deg(i*angleStep)。若目标约束为 approximate_rectangle，可使用通用交错咬合：令 halfAngle=π/N、stepX=r*sin(halfAngle)、stepY=r*cos(halfAngle)，第 i 片目标 x=x0+i*stepX；偶数片 y=y0、rotation=90，奇数片 y=y0+stepY、rotation=-90。这样相邻径向边界重合且弧边形成随 N 增大而趋平的上下边界；不得用 arcLen 作为逐片中心间距，不得把上下两组分成互不接触的行。
必须逐项落实 recomposition_spec.proof_constraints：保持 measure_invariants，frames 按 stage_id 和 at 精确覆盖 stage_requirements，中间几何阶段满足 min_piece_ratio，最后一帧用教学文本解释 target_relations；target_relations 由服务端对 minimum/default/maximum 状态执行数值验证，其中引用的 piece_id 必须与展开后图元 id 一致。面积守恒时所有阶段禁止通过 scale 改变图元面积。
progress 不是 state 变量，IR 中严禁引用 progress；source/target 是两个完整端点，服务端负责二者之间的插值。计划变量必须写成 state 引用，只有 definitions 名称才能写成 var 引用。
所有参数在计划给出的 default/min/max 都必须产生正尺寸、有限属性、唯一 id 和可见变换。第一版只做 transform 驱动二维 SVG，不做 path morph。
source/target 在 minimum/default/maximum 状态的可见图元并集都必须具备课堂可读尺度：长边至少 128px；短边小于 64px 时包围盒面积至少占画布 1.5%。默认主体优先占 160~420px，且在画布中部均衡布局，禁止仅保证变换锚点入界却让实际图形缩在角落。
输出前必须检查统一像素尺度是否存在可行区间：minimum 状态达到上述可读阈值所需的缩放下限，不得大于 maximum 状态完整放入 960×560 画布允许的缩放上限。若区间为空，不得继续使用单一“参数×常数”比例；应使用 clamp/min/max 归一化视觉尺寸，或重构局部坐标，使抽象参数变化仍保留教学关系但视觉跨度受控。
优先控制在 8 个 definitions、8 个图元模板和 1 个 repeat 内；只保留证明所需的实际几何块，不生成标签背景、占位 g、虚线辅助图或装饰图元。复杂重复结构必须用 repeat 表达，不展开大段近似对象。输出前检查 JSON 引号、逗号和括号完整闭合。
通用语法示例：{{"version":"{GEOMETRY_IR_VERSION}","definitions":[{{"name":"size","value":{{"op":"mul","args":[{{"state":"scale"}},30]}}}}],"pieces":[{{"repeat":null,"id":"piece-0","tag":"polygon","attrs":[{{"name":"points","value":{{"op":"points","args":[[0,0],[{{"var":"size"}},0],[0,{{"var":"size"}}]]}}}},{{"name":"fill","value":"#34d399"}}],"source":{{"x":120,"y":160,"rotation":0,"scale":1,"opacity":1}},"target":{{"x":420,"y":260,"rotation":90,"scale":1,"opacity":1}},"keyframes":[{{"at":0,"x":120,"y":160,"rotation":0,"scale":1,"opacity":1}},{{"at":0.5,"x":250,"y":90,"rotation":35,"scale":1,"opacity":1}},{{"at":1,"x":420,"y":260,"rotation":90,"scale":1,"opacity":1}}]}}],"frames":[{{"stage_id":"source","at":0,"caption":"观察源状态","formula":"关系保持","step":0}},{{"stage_id":"transform-1","at":0.5,"caption":"观察分离后的中间状态","formula":"图元集合不变","step":1}},{{"stage_id":"target","at":1,"caption":"解释目标状态","formula":"度量关系成立","step":2}}],"construction":null}}。实际 stage_id/at 必须复制计划值；只可引用用户消息列出的 allowed_state_variables；若其中没有 scale，不得照抄示例。
每个 IR 不超过 {GEOMETRY_IR_MAX_CHARS} 字符。不得针对圆、梯形或其他单个知识点调用专用模板；只能组合上述通用图元与表达式。"""


class GeometryIRGenerationError(ValueError):
    def __init__(self, raw_text: str, report: dict[str, Any]) -> None:
        reasons: list[str] = []
        for item in report.get("errors", []):
            if not isinstance(item, dict):
                continue
            failures = item.get("hard_failures")
            values = failures if isinstance(failures, list) else [item.get("type")]
            for value in values:
                reason = str(value or "").strip()
                if reason and reason not in reasons:
                    reasons.append(reason)
        super().__init__(",".join(reasons) or "geometry_ir_generation_failed")
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
        "representation_type": ((inputs.get("plan") or {}).get("knowledge_profile") or {}).get("representation_type"),
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
    feasibility = evaluate_recomposition_plan_feasibility(plan)
    if not feasibility["ok"]:
        raise HtmlGenerationError(
            "当前几何重排计划超出可验证 IR 的有界能力，已停止生成",
            code="unsupported_ir_capability",
            detail=format_recomposition_feasibility_errors(feasibility),
        )
    if not has_primary_llm_config():
        raise HtmlGenerationError("几何重排 IR 生成失败，未配置可用模型", code="model_unavailable")
    degraded = False
    try:
        source, degraded = _generate_scene_source(topic, plan)
    except GeometryIRGenerationError as exc:
        try:
            source = _repair_scene_source(topic, plan, exc.raw_text, exc.report)
        except Exception as repair_exc:
            logger.warning("geometry IR bounded repair failed: %s", repair_exc)
            repair_detail = str(repair_exc).strip()
            initial_detail = str(exc).strip()
            raise HtmlGenerationError(
                "几何重排 IR 未通过确定性校验，已停止生成",
                code="ir_generation_failed",
                detail=(
                    f"initial={initial_detail};repair={repair_detail}"
                    if repair_detail and repair_detail != initial_detail
                    else initial_detail
                ),
            ) from repair_exc
        degraded = True
    except GeneratorExit:
        raise
    except Exception as exc:
        logger.warning("geometry IR generation failed: %s", exc)
        raise HtmlGenerationError(
            "几何重排 IR 生成失败，已停止生成",
            code="ir_generation_failed",
            detail=type(exc).__name__,
        ) from exc
    report = validate_scene_module(source)
    if not report["ok"]:
        errors = [str(error.get("type")) for error in report.get("errors", []) if isinstance(error, dict)]
        raise HtmlGenerationError(
            "几何重排 Scene Module 未通过运行时契约校验，已停止生成",
            code="ir_generation_failed",
            detail=",".join(errors[:8]) or "recomposition_scene_module_invalid",
        )
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


def _generate_ranked_scene_source(topic: str, plan: dict[str, Any]) -> tuple[str, bool, dict[str, Any]]:
    prompt = _build_scene_prompt(topic, plan)
    raw_text = ""
    timed_out = False
    deadline = time.monotonic() + max(settings.aetherviz_html_timeout_seconds, 1)
    messages = [SystemMessage(content=SCENE_SYSTEM_PROMPT), HumanMessage(content=prompt)]
    for chunk in _stream_scene_response(messages, response_schema=geometry_ir_candidates_response_schema()):
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
    candidates, construction_reports = _materialize_candidate_constructions(candidates, plan)
    ranking = _trace_rank_geometry_ir_candidates(candidates, plan)
    ranking["strategy"] = "raw_candidate"
    ranking["construction_materialization"] = construction_reports
    _log_ranking(ranking)
    if not ranking["ok"]:
        ranking, candidates = _complete_candidates_deterministically(candidates, plan, ranking)
        ranking["construction_materialization"] = construction_reports
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


def _attempt_target_bounds_completion(
    candidates: list[object],
    plan: dict[str, Any],
    initial_ranking: dict[str, Any],
) -> tuple[dict[str, Any], list[object]]:
    return _attempt_completion_stage(candidates, plan, initial_ranking, stage="bounds")


def _attempt_footprint_scale_completion(
    candidates: list[object],
    plan: dict[str, Any],
    initial_ranking: dict[str, Any],
) -> tuple[dict[str, Any], list[object]]:
    return _attempt_completion_stage(candidates, plan, initial_ranking, stage="scale")


def _attempt_waypoint_completion(
    candidates: list[object], plan: dict[str, Any], initial_ranking: dict[str, Any]
) -> dict[str, Any]:
    completed_ranking, _ = _attempt_completion_stage(
        candidates, plan, initial_ranking, stage="waypoint"
    )
    return completed_ranking


def _complete_candidates_deterministically(
    candidates: list[object],
    plan: dict[str, Any],
    initial_ranking: dict[str, Any],
) -> tuple[dict[str, Any], list[object]]:
    """Apply orthogonal candidate repairs until no hard failure is removed."""
    current_candidates = list(candidates)
    current_ranking = initial_ranking
    initial_public = public_geometry_ir_ranking(initial_ranking)
    history: list[dict[str, Any]] = []
    accepted_strategies: list[str] = []
    aggregate_reports = {
        "waypoint_completion": [],
        "target_bounds_completion": [],
        "footprint_scale_completion": [],
    }
    for round_index in range(1, _DETERMINISTIC_COMPLETION_MAX_ROUNDS + 1):
        accepted_this_round = False
        for stage in ("waypoint", "bounds", "scale"):
            next_ranking, next_candidates = _attempt_completion_stage(
                current_candidates,
                plan,
                current_ranking,
                stage=stage,
            )
            report_key = _completion_stage_config(stage)["report_key"]
            reports = next_ranking.get(report_key, [])
            aggregate_reports[report_key].extend(
                [{**item, "round": round_index} for item in reports if item.get("attempted")]
            )
            accepted_count = sum(bool(item.get("accepted")) for item in reports)
            history.append(
                {
                    "round": round_index,
                    "stage": stage,
                    "attempted": sum(bool(item.get("attempted")) for item in reports),
                    "accepted": accepted_count,
                }
            )
            if accepted_count:
                accepted_this_round = True
                accepted_strategies.append(str(next_ranking["strategy"]))
                current_candidates = next_candidates
                current_ranking = next_ranking
            if current_ranking["ok"]:
                break
        if current_ranking["ok"] or not accepted_this_round:
            break

    if accepted_strategies:
        current_ranking["strategy"] = (
            accepted_strategies[0]
            if len(set(accepted_strategies)) == 1
            else "deterministic_composite_completion"
        )
    else:
        current_ranking = dict(current_ranking)
        current_ranking["strategy"] = "raw_candidate"
    current_ranking["initial_ranking"] = initial_public
    current_ranking["completion_history"] = history
    current_ranking.update(aggregate_reports)
    return current_ranking, current_candidates


def _attempt_completion_stage(
    candidates: list[object],
    plan: dict[str, Any],
    initial_ranking: dict[str, Any],
    *,
    stage: str,
) -> tuple[dict[str, Any], list[object]]:
    config = _completion_stage_config(stage)
    repaired_candidates = list(candidates)
    repair_reports: list[dict[str, Any]] = []
    accepted_origins = [
        str(item.get("origin") or "model") for item in initial_ranking.get("candidates", [])
    ]
    accepted_any = False
    for index, candidate in enumerate(candidates):
        candidate_report = initial_ranking["candidates"][index]
        before_failures = set(candidate_report.get("hard_failures", []))
        if config["failure"] not in before_failures:
            repair_reports.append(
                {
                    "index": index,
                    "attempted": False,
                    "ok": False,
                    "accepted": False,
                    "changed": False,
                    "reason": "relevant_hard_failure_absent",
                    "hard_failures": sorted(before_failures),
                }
            )
            continue
        repair = _run_completion_repair(stage, candidate, plan, candidate_report)
        proposed = repair.get("ir") or candidate
        report = {
            "index": index,
            "attempted": True,
            "ok": False,
            "accepted": False,
            "changed": bool(repair.get("changed")),
            "reason": repair.get("reason"),
            **_completion_repair_evidence(stage, repair),
        }
        if repair.get("changed"):
            proposal_ranking = _trace_rank_geometry_ir_candidates(
                [proposed], plan, origins=[config["origin"]]
            )
            after_failures = set(proposal_ranking["candidates"][0].get("hard_failures", []))
            accepted = after_failures < before_failures
            report.update(
                {
                    "ok": accepted,
                    "accepted": accepted,
                    "before_hard_failures": sorted(before_failures),
                    "after_hard_failures": sorted(after_failures),
                    "removed_hard_failures": sorted(before_failures - after_failures),
                    "introduced_hard_failures": sorted(after_failures - before_failures),
                }
            )
            if accepted:
                repaired_candidates[index] = proposed
                accepted_origins[index] = config["origin"]
                accepted_any = True
            else:
                report["reason"] = "repair_did_not_monotonically_reduce_hard_failures"
        repair_reports.append(report)

    repaired_ranking = (
        _trace_rank_geometry_ir_candidates(repaired_candidates, plan, origins=accepted_origins)
        if accepted_any
        else dict(initial_ranking)
    )
    repaired_ranking.update(
        {
            "strategy": config["strategy"],
            "initial_ranking": public_geometry_ir_ranking(initial_ranking),
            config["report_key"]: repair_reports,
        }
    )
    return repaired_ranking, repaired_candidates


def _completion_stage_config(stage: str) -> dict[str, str]:
    configs = {
        "waypoint": {
            "failure": "teaching:missing_intermediate_geometry_stage",
            "origin": "waypoint",
            "strategy": "deterministic_waypoint_completion",
            "report_key": "waypoint_completion",
        },
        "bounds": {
            "failure": "assembly:target_assembly_out_of_bounds",
            "origin": "bounds",
            "strategy": "deterministic_target_bounds_completion",
            "report_key": "target_bounds_completion",
        },
        "scale": {
            "failure": "safety:undersized_visual_footprint",
            "origin": "scale",
            "strategy": "deterministic_footprint_scale_completion",
            "report_key": "footprint_scale_completion",
        },
    }
    return configs[stage]


def _run_completion_repair(
    stage: str,
    candidate: object,
    plan: dict[str, Any],
    candidate_report: dict[str, Any],
) -> dict[str, Any]:
    details = candidate_report.get("details", {})
    if stage == "waypoint":
        return complete_intermediate_waypoints(candidate, plan)
    if stage == "bounds":
        return translate_target_assembly_into_canvas(candidate, details.get("target_assembly", {}))
    return scale_scene_footprints_into_canvas(
        candidate, details.get("visual_footprints", {}), plan
    )


def _completion_repair_evidence(stage: str, repair: dict[str, Any]) -> dict[str, Any]:
    if stage == "waypoint":
        return {"completed_stage_ids": repair.get("completed_stage_ids", [])}
    if stage == "bounds":
        return {"translation": repair.get("translation")}
    return {
        "scale": repair.get("scale"),
        "boost": repair.get("boost"),
        "translations": repair.get("translations"),
        "analysis": repair.get("analysis"),
        "reason": repair.get("reason"),
    }


def _materialize_candidate_constructions(
    candidates: list[object], plan: dict[str, Any]
) -> tuple[list[object], list[dict[str, Any]]]:
    materialized: list[object] = []
    reports: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        result = materialize_target_construction(candidate, plan)
        materialized.append(result.get("ir") or candidate)
        reports.append(_public_construction_report(index, result))
    return materialized, reports


def _public_construction_report(index: int, report: dict[str, Any]) -> dict[str, Any]:
    return {
        "index": index,
        "ok": bool(report.get("ok")),
        "changed": bool(report.get("changed")),
        "constraints": report.get("constraints", []),
        "errors": [
            {key: item.get(key) for key in ("type", "index", "piece_id", "to_piece_id", "state") if key in item}
            for item in report.get("errors", [])
            if isinstance(item, dict)
        ],
    }


def _log_ranking(ranking: dict[str, Any]) -> None:
    logger.info(
        "geometry IR deterministic ranking: %s",
        json.dumps(
            {
                "strategy": ranking.get("strategy"),
                "selected_index": ranking["selected_index"],
                "ranking": ranking["ranking"],
                "target_bounds_completion": ranking.get("target_bounds_completion", []),
                "footprint_scale_completion": ranking.get("footprint_scale_completion", []),
                "waypoint_completion": ranking.get("waypoint_completion", []),
                "construction_materialization": ranking.get("construction_materialization", []),
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
        "strategy": ranking.get("strategy"),
        "construction_materialization": ranking.get("construction_materialization", []),
        "completion_history": ranking.get("completion_history", []),
        "waypoint_completion": ranking.get("waypoint_completion", []),
        "target_bounds_completion": ranking.get("target_bounds_completion", []),
        "footprint_scale_completion": ranking.get("footprint_scale_completion", []),
        "candidates": [
            {
                "index": item.get("index"),
                "score": item.get("score"),
                "eligible": item.get("eligible"),
                "hard_failures": item.get("hard_failures", []),
                "components": item.get("components", {}),
                "assembly_states": item.get("details", {}).get("target_assembly", {}).get("states", []),
                "source_assembly_states": item.get("details", {}).get("target_assembly", {}).get("source_states", []),
                "visual_footprints": item.get("details", {}).get("visual_footprints", {}).get("endpoints", {}),
                "footprint_scale_analysis": item.get("details", {})
                .get("motion_safety", {})
                .get("scale_analysis", {}),
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
        "若报告含 undersized_visual_footprint，先读取 footprint_diagnostics 的缩放区间；只有 required_scale 不大于 maximum_scale 时才整体缩放并重新居中。"
        "若报告含 visual_scale_range_conflict，禁止仅用统一系数放大；必须收窄通用几何变量对应的像素跨度、使用 clamp/min/max，或重构局部坐标，使 minimum 可读且 maximum 入界。"
        "若使用 sector_path 逼近矩形，必须采用系统说明中的固定局部扇形与交错咬合坐标，不得继续沿用按索引旋转过的局部 path、arcLen 间距或分离的上下行。"
        "静态多边形需要精确拼边时可改用通用 construction constraints，让服务端求解 target；约束必须使用固定 piece id 和有效边/顶点索引，自定义目标区域用 target_boundary 配合 inside_target/cover_target。"
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
    for chunk in _stream_scene_response(messages, response_schema=geometry_ir_response_schema()):
        raw_text += extract_llm_text(chunk)
        if len(raw_text) > GEOMETRY_IR_MAX_CHARS + 1_024:
            break
    geometry_ir = normalize_geometry_ir(parse_geometry_ir(raw_text), plan)
    construction = materialize_target_construction(geometry_ir, plan)
    geometry_ir = construction.get("ir") or geometry_ir
    ranking = _trace_rank_geometry_ir_candidates([geometry_ir], plan, origins=["repair"])
    ranking["construction_materialization"] = [_public_construction_report(0, construction)]
    if not ranking["ok"]:
        ranking, _ = _complete_candidates_deterministically([geometry_ir], plan, ranking)
        ranking["construction_materialization"] = [_public_construction_report(0, construction)]
        _log_ranking(ranking)
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
        '{"candidates":[IR1,IR2,IR3]}，不得少于 2 个，不生成 HTML。每个候选应采用不同但通用的切分或运动布局；'
        "先确定切分后稳定图元集合，再用 source/target 表达同一组 id 的重排；"
        "不得输出可执行代码，也不得使用任何知识点专用分支。只能用 allowed_state_variables，严禁 progress；"
        "画布为 960×560，默认状态的主体图形建议占 160~420px，避免把 1~8 这类抽象参数直接当像素尺寸；"
        "先验证 minimum 可读所需缩放下限不大于 maximum 入界允许上限，冲突时用 clamp/min/max 约束视觉尺寸跨度。\n"
        "若计划声明 target_assembly 且候选由多个静态 polygon/rect 拼片组成，优先用 construction.constraints 表达边连接、点重合或平行/垂直关系，由服务端确定性求解 target，避免手写近似坐标。\n"
        + json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
    )


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
                "assembly_diagnostics": _compact_assembly_diagnostics(
                    item.get("details", {}).get("target_assembly", {})
                ),
                "teaching_diagnostics": _compact_teaching_diagnostics(
                    item.get("details", {}).get("teaching_semantics", {})
                ),
                "footprint_diagnostics": _compact_footprint_diagnostics(
                    item.get("details", {}).get("motion_safety", {})
                ),
            }
            for item in ranking.get("candidates", [])
        ],
        "warnings": [],
        "ranking": public_geometry_ir_ranking(ranking),
    }


def _compact_footprint_diagnostics(report: object) -> dict[str, Any]:
    if not isinstance(report, dict):
        return {}
    errors = [
        {
            key: item.get(key)
            for key in ("type", "state", "endpoint", "bbox", "area_ratio", "required_scale", "maximum_scale")
            if key in item
        }
        for item in report.get("errors", [])
        if isinstance(item, dict)
        and item.get("type") in {"undersized_visual_footprint", "visual_scale_range_conflict"}
    ]
    return {"errors": errors, "scale_analysis": report.get("scale_analysis", {})}


def _compact_teaching_diagnostics(report: object) -> dict[str, Any]:
    if not isinstance(report, dict):
        return {}
    failed_checks: list[dict[str, Any]] = []
    for check in report.get("checks", []):
        if not isinstance(check, dict) or check.get("kind") != "intermediate_geometry":
            continue
        if float(check.get("ratio", 0)) >= float(check.get("required_ratio", 1)):
            continue
        failed_checks.append(
            {
                "stage_id": check.get("name"),
                "state": check.get("state"),
                "at": check.get("at"),
                "ratio": check.get("ratio"),
                "required_ratio": check.get("required_ratio"),
                "reason_counts": check.get("reason_counts", {}),
            }
        )
    return {
        "error_types": sorted({str(item.get("type")) for item in report.get("errors", []) if isinstance(item, dict)}),
        "failed_intermediate_checks": failed_checks,
    }


def _compact_assembly_diagnostics(report: object) -> dict[str, Any]:
    if not isinstance(report, dict):
        return {}
    states = []
    for state in report.get("states", []):
        if not isinstance(state, dict):
            continue
        states.append(
            {
                key: state.get(key)
                for key in (
                    "state",
                    "piece_count",
                    "component_count",
                    "rectangularity",
                    "overlap_ratio",
                    "bbox",
                )
            }
        )
    failures = []
    for error in report.get("errors", []):
        if not isinstance(error, dict):
            continue
        failures.append(
            {
                key: error.get(key)
                for key in (
                    "type",
                    "constraint",
                    "state",
                    "minimum_rectangularity",
                    "maximum_overlap_ratio",
                    "maximum_components",
                    "scores",
                    "tolerance",
                )
                if key in error
            }
        )
    return {"errors": failures, "states": states}


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
        yield from create_chat_model("scene", response_schema=response_schema or geometry_ir_response_schema()).stream(
            messages
        )
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
