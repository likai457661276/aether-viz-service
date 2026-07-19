"""Scoped model patch: replace named functions and CSS rules without full HTML regen."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from aetherviz_service.aetherviz.agents.model_factory import (
    create_chat_model,
    extract_llm_text,
    extract_llm_usage,
    has_primary_llm_config,
)
from aetherviz_service.aetherviz.contracts.html_stream import (
    HtmlGenerationError,
    HtmlStreamResult,
    build_html_progress_payload,
)
from aetherviz_service.aetherviz.edit.diagnosis import EditDiagnosis
from aetherviz_service.aetherviz.edit.intent import evaluate_edit_intent
from aetherviz_service.aetherviz.limits import (
    MAX_CSS_RULE_REPLACEMENT_CHARS,
    MAX_FUNCTION_REPLACEMENT_CHARS,
)
from aetherviz_service.aetherviz.tools.css_patch import (
    apply_css_rule_replacements,
    describe_target_css_rules,
    parse_css_rule_replacements,
)
from aetherviz_service.aetherviz.tools.function_patch import (
    apply_function_replacements,
    describe_target_functions,
    parse_function_replacements,
)

logger = logging.getLogger(__name__)

SCOPED_EDIT_SYSTEM_PROMPT = f"""你是 AetherViz 局部 HTML 补丁编辑器。
只输出一个 JSON 对象：
{{"function_replacements":[{{"function":"函数名","source_hash":"原哈希","replacement":"完整函数声明"}}],"css_rule_replacements":[{{"selector":"选择器","source_hash":"原哈希","replacement":"完整 CSS 规则"}}]}}
规则：
1. 只能替换输入中列出的函数和 CSS 规则，必须原样返回 source_hash。
2. 不得输出完整 HTML、Markdown 或解释。
3. 只实施已编译编辑任务要求的定向修改；保持未列出的函数、样式与交互不变。
4. 函数替换总长度不超过 {MAX_FUNCTION_REPLACEMENT_CHARS} 字符；CSS 规则替换总长度不超过 {MAX_CSS_RULE_REPLACEMENT_CHARS} 字符。
5. 若某目标无需修改，不要把它放进 replacements。
"""


def stream_scoped_model_patch(
    *,
    topic: str,
    message: str,
    current_html: str,
    diagnosis: EditDiagnosis,
) -> Iterator[dict[str, Any] | HtmlStreamResult]:
    del topic  # reserved for tracing parity with full edit
    if not has_primary_llm_config():
        raise HtmlGenerationError(
            "HTML 修改失败，未配置可用的模型服务，原页面已保留",
            code="model_unavailable",
            detail="OPENAI_API_KEY is not configured",
        )

    function_names = _target_function_names(diagnosis)
    css_selectors = _target_css_selectors(diagnosis)
    function_descriptions = [
        item
        for item in describe_target_functions(current_html, function_names)
        if len(item["source"]) <= MAX_FUNCTION_REPLACEMENT_CHARS
    ][:3]
    css_descriptions = [
        item
        for item in describe_target_css_rules(current_html, css_selectors)
        if len(item["source"]) <= MAX_CSS_RULE_REPLACEMENT_CHARS
    ][:3]
    if not function_descriptions and not css_descriptions:
        raise HtmlGenerationError(
            "HTML 修改失败，局部补丁缺少可绑定目标，原页面已保留",
            code="edit_failed",
            detail="scoped_patch_no_bindable_targets",
        )

    yield build_html_progress_payload(
        [
            {"content": "分析局部函数与样式目标", "status": "in_progress"},
            {"content": "生成结构化局部补丁", "status": "pending"},
        ]
    )

    prompt = json.dumps(
        {
            "compiled_task": {
                "resolved_instruction": diagnosis.resolved_instruction or message,
                "change_requirements": list(diagnosis.change_requirements),
                "preserve_requirements": list(diagnosis.preserve_requirements),
                "acceptance_criteria": list(diagnosis.acceptance_criteria),
                "change_checks": [check.public_dict() for check in diagnosis.change_checks],
                "preserve_checks": [check.public_dict() for check in diagnosis.preserve_checks],
            },
            "functions": function_descriptions,
            "css_rules": css_descriptions,
            "allowed_functions": [item["function"] for item in function_descriptions],
            "allowed_selectors": [item["selector"] for item in css_descriptions],
            "user_message": message,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )

    raw_text = ""
    input_tokens: int | None = None
    output_tokens: int | None = None
    try:
        model = create_chat_model("edit")
        for chunk in model.stream([SystemMessage(content=SCOPED_EDIT_SYSTEM_PROMPT), HumanMessage(content=prompt)]):
            chunk_input_tokens, chunk_output_tokens = extract_llm_usage(chunk)
            input_tokens = chunk_input_tokens or input_tokens
            output_tokens = chunk_output_tokens or output_tokens
            raw_text += extract_llm_text(chunk)
            if len(raw_text) > MAX_FUNCTION_REPLACEMENT_CHARS + MAX_CSS_RULE_REPLACEMENT_CHARS + 4_000:
                break
    except GeneratorExit:
        raise
    except Exception as exc:
        logger.warning("scoped model patch failed: %s", exc)
        raise HtmlGenerationError(
            "HTML 修改失败，局部补丁生成异常，原页面已保留",
            code="edit_failed",
            detail=str(exc),
        ) from exc

    if not raw_text.strip():
        raise HtmlGenerationError(
            "HTML 修改失败，局部补丁模型返回空内容，原页面已保留",
            code="edit_failed",
            detail="scoped_patch_empty",
        )

    payload = _parse_scoped_payload(raw_text)
    function_replacements = payload.get("function_replacements") or parse_function_replacements(raw_text)
    css_replacements = payload.get("css_rule_replacements") or parse_css_rule_replacements(raw_text)

    updated = current_html
    applied_functions: tuple[str, ...] = ()
    applied_css: tuple[str, ...] = ()
    errors: list[str] = []

    if function_replacements and function_descriptions:
        patch = apply_function_replacements(
            updated,
            function_replacements,
            allowed_functions=tuple(item["function"] for item in function_descriptions),
            allowed_targets=tuple((str(item["function"]), str(item["source_hash"])) for item in function_descriptions),
        )
        if patch.errors and not patch.applied:
            errors.extend(patch.errors)
        else:
            updated = patch.html
            applied_functions = patch.applied
            errors.extend(patch.errors)

    if css_replacements and css_descriptions:
        patch = apply_css_rule_replacements(
            updated,
            css_replacements,
            allowed_selectors=tuple(item["selector"] for item in css_descriptions),
            allowed_targets=tuple((str(item["selector"]), str(item["source_hash"])) for item in css_descriptions),
        )
        if patch.errors and not patch.applied:
            errors.extend(patch.errors)
        else:
            updated = patch.html
            applied_css = patch.applied
            errors.extend(patch.errors)

    if not applied_functions and not applied_css:
        raise HtmlGenerationError(
            "HTML 修改失败，局部补丁未能安全应用，原页面已保留",
            code="edit_failed",
            detail="; ".join(errors[:8]) or "scoped_patch_not_applied",
        )

    intent = evaluate_edit_intent(
        baseline_html=current_html,
        candidate_html=updated,
        change_checks=diagnosis.change_checks,
        preserve_checks=diagnosis.preserve_checks,
    )
    if not intent.ok:
        raise HtmlGenerationError(
            "HTML 修改结果未满足本次编辑验收条件，原页面已保留",
            code="edit_intent_not_satisfied",
            detail=intent.retry_evidence(),
        )

    yield build_html_progress_payload(
        [
            {"content": "分析局部函数与样式目标", "status": "completed"},
            {"content": "生成结构化局部补丁", "status": "completed"},
        ],
        html_content=updated,
    )
    yield HtmlStreamResult(
        html=updated,
        degraded=False,
        truncated=False,
        strategy="scoped_model_patch",
        source_chars=len(current_html),
        patch_functions=applied_functions,
        patch_blocks=applied_css,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        output_chars=len(raw_text),
        intent_passed=True,
        intent_soft_failed=tuple(f"{item.check.id}:{item.message}" for item in intent.soft_failed),
        intent_check_count=len(intent.passed) + len(intent.failed) + len(intent.soft_failed),
        intent_summary=intent.summary,
    )


def _target_function_names(diagnosis: EditDiagnosis) -> tuple[str, ...]:
    names: list[str] = []
    for item in diagnosis.targets:
        name = str(item.get("function") or "")
        if name and name not in names:
            names.append(name)
    for op in diagnosis.operations:
        if op.function and op.function not in names:
            names.append(op.function)
    return tuple(names[:5])


def _target_css_selectors(diagnosis: EditDiagnosis) -> tuple[str, ...]:
    selectors: list[str] = []
    for item in diagnosis.targets:
        kind = str(item.get("kind") or "")
        selector = str(item.get("selector") or "")
        if selector and (kind in {"css", "dom", ""} or not kind) and selector not in selectors:
            # Prefer CSS-looking selectors; still allow element selectors for inline style patches via full regen fallback.
            selectors.append(selector)
    for op in diagnosis.operations:
        if op.type in {"set_css_declaration", "set_css_variable"} and op.selector and op.selector not in selectors:
            selectors.append(op.selector)
    return tuple(selectors[:5])


def _parse_scoped_payload(raw_text: str) -> dict[str, Any]:
    text = (raw_text or "").strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        text = match.group(0)
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}
