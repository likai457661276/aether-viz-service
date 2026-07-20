"""Model-to-IR generation for exact symbolic derivations."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from aetherviz_service.aetherviz.agents.model_factory import create_chat_model, extract_llm_text, has_primary_llm_config
from aetherviz_service.aetherviz.contracts.html_stream import (
    HtmlGenerationError,
    HtmlStreamResult,
    build_html_progress_payload,
)
from aetherviz_service.aetherviz.ir.symbolic_derivation.contract import (
    SYMBOLIC_DERIVATION_IR_MAX_CHARS,
    SYMBOLIC_DERIVATION_IR_VERSION,
    parse_symbolic_derivation_ir,
    parse_symbolic_derivation_ir_candidates,
    rank_symbolic_derivation_ir_candidates,
    symbolic_derivation_ir_candidates_response_schema,
    symbolic_derivation_ir_response_schema,
)
from aetherviz_service.aetherviz.ir.symbolic_derivation.runtime import assemble_symbolic_derivation_business_html

logger = logging.getLogger(__name__)
SYSTEM_PROMPT = f"""你是符号推导 IR 生成器，只输出 JSON，version 固定为 {SYMBOLIC_DERIVATION_IR_VERSION}。表达式只允许数字、symbol 与 add/mul/pow/neg AST；pow 指数只能是 0~8 整数。每一步 before 必须与上一步 after 完全衔接。expression 模式要求前后多项式恒等；equation 模式允许方程差式相差非零常数倍。multiply_nonzero/divide_nonzero 必须用 nonzero 声明非零数字。不得输出 LaTeX、HTML、JavaScript、动画坐标或未经证明的步骤。首版不支持不等式、超越方程、根式有理化或数值近似证明。所有说明使用简体中文，IR 不超过 {SYMBOLIC_DERIVATION_IR_MAX_CHARS} 字符。"""


def stream_generate_symbolic_derivation_html(
    topic: str, plan: dict[str, Any]
) -> Iterator[dict[str, Any] | HtmlStreamResult]:
    if not has_primary_llm_config():
        raise HtmlGenerationError("符号推导 IR 生成失败，未配置可用模型", code="model_unavailable")
    yield build_html_progress_payload(
        [
            {"content": "生成符号推导 IR", "status": "in_progress"},
            {"content": "验证逐步等价性", "status": "pending"},
            {"content": "编译推导运行时", "status": "pending"},
        ]
    )
    raw = _invoke(
        _prompt(topic, plan),
        symbolic_derivation_ir_candidates_response_schema(),
        SYMBOLIC_DERIVATION_IR_MAX_CHARS * 2 + 1024,
    )
    try:
        ranking = rank_symbolic_derivation_ir_candidates(parse_symbolic_derivation_ir_candidates(raw), plan)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        ranking = {
            "ok": False,
            "repair_candidate": raw,
            "repair_report": {"errors": [{"type": type(exc).__name__, "message": str(exc)}]},
        }
    degraded = False
    if not ranking["ok"]:
        degraded = True
        repaired = _invoke(
            _repair_prompt(topic, plan, ranking),
            symbolic_derivation_ir_response_schema(),
            SYMBOLIC_DERIVATION_IR_MAX_CHARS + 512,
        )
        try:
            ranking = rank_symbolic_derivation_ir_candidates([parse_symbolic_derivation_ir(repaired)], plan)
        except (TypeError, ValueError, json.JSONDecodeError):
            ranking = {"ok": False}
    if not ranking["ok"]:
        raise HtmlGenerationError(
            "符号推导 IR 未通过确定性校验，已停止生成",
            code="ir_generation_failed",
            detail="symbolic_derivation_ir_invalid",
        )
    yield build_html_progress_payload(
        [
            {"content": "生成符号推导 IR", "status": "completed"},
            {"content": "验证逐步等价性", "status": "completed"},
            {"content": "编译推导运行时", "status": "completed"},
        ]
    )
    yield HtmlStreamResult(
        html=assemble_symbolic_derivation_business_html(ranking["selected_ir"], plan, topic),
        degraded=degraded,
        truncated=False,
        strategy="symbolic_derivation_ir",
        source_chars=len(raw),
        output_chars=len(raw),
    )


def _invoke(prompt: str, schema: dict[str, Any], limit: int) -> str:
    messages = [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=prompt)]
    raw = ""
    try:
        for chunk in create_chat_model("scene", response_schema=schema).stream(messages):
            raw += extract_llm_text(chunk)
            if len(raw) > limit:
                break
    except Exception as exc:
        logger.warning("strict symbolic schema unavailable; using JSON mode: %s", exc)
        raw = "".join(extract_llm_text(chunk) for chunk in create_chat_model("scene").stream(messages))[:limit]
    return raw


def _prompt(topic: str, plan: dict[str, Any]) -> str:
    return '严格输出 {"candidates":[IR1,IR2]}，两个候选使用不同但完全可验证的步骤粒度。' + json.dumps(
        {
            "topic": topic,
            "goal": plan.get("goal"),
            "representation_spec": plan.get("representation_spec"),
            "teaching_flow": plan.get("teaching_flow"),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _repair_prompt(topic: str, plan: dict[str, Any], ranking: dict[str, Any]) -> str:
    return "只修复报告中的确定性错误，保持题意，输出完整单个 IR。" + json.dumps(
        {"topic": topic, "candidate": ranking.get("repair_candidate"), "report": ranking.get("repair_report")},
        ensure_ascii=False,
        separators=(",", ":"),
    )
