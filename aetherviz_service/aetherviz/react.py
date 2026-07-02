"""AetherViz SSE generator.

当前动态能力按产品计划主动收敛：
- 静态知识点命中后直接返回静态 HTML。
- 动态生成只走 HTML + CSS + SVG。
- 数学主题固定走 HTML + SVG + KaTeX + GSAP Timeline。
- revise 基于 current_html + instruction 修订当前页面。
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator

from aetherviz_service.aetherviz.fallback_planner import (
    build_planning_prompt,
    normalize_plan,
    parse_planning_result,
)
from aetherviz_service.aetherviz.fallback_validator import (
    AetherVizInteractiveHtmlError,
    parse_interactive_html,
)
from aetherviz_service.aetherviz.knowledge_points import get_knowledge_point
from aetherviz_service.aetherviz.matcher import match_topic_to_knowledge_point
from aetherviz_service.aetherviz.schemas.aetherviz import GenerateAetherVizHtmlMetadata
from aetherviz_service.aetherviz.static_html import (
    StaticAetherVizHtmlError,
    extract_color_from_topic,
    load_static_html_for_point,
)
from aetherviz_service.aetherviz.validator import (
    AetherVizHtmlValidationError,
    sanitize_aetherviz_html,
    validate_aetherviz_html,
)
from aetherviz_service.llm_service import LLMServiceError, call_llm_stream

logger = logging.getLogger(__name__)

_CDN_KATEX_CSS = "https://cdn.staticfile.net/KaTeX/0.16.9/katex.min.css"
_CDN_KATEX_JS = "https://cdn.staticfile.net/KaTeX/0.16.9/katex.min.js"
_CDN_GSAP = "https://cdn.jsdelivr.net/npm/gsap@3.12.5/dist/gsap.min.js"

GENERIC_SVG_SYSTEM_PROMPT = f"""你是 AetherViz 互动教学 SVG 页面工程师。
你只输出一个完整可运行 HTML 文件，从 <!DOCTYPE html> 开始，到 </html> 结束。

硬性边界：
1. 只使用 HTML + CSS + SVG + 原生 JavaScript。
2. 不使用 Three.js、Canvas、D3、图片生成、文件上传或外部业务接口。
3. CSS 和业务 JavaScript 必须内联；除数学模式外不要引入外部脚本。
4. 禁止任何内联事件属性，所有事件用 addEventListener 绑定。
5. 页面必须包含 class="learning-objectives" 的学习目标列表、id="aetherviz-stage" 的主可视化区、class="control-panel" 的控制面板。
6. 控制按钮至少包含 id="play-animation"、id="pause-animation"、id="reset-animation"，且全部绑定真实事件。
7. 声明 window.AetherVizRuntime，包含 play、pause、reset、setSpeed、update、getState。
8. 初始化成功设置 window.__AETHERVIZ_RUNTIME_READY__ = true；失败设置 window.__AETHERVIZ_RUNTIME_ERROR__ 并在页面显示错误。
9. 页面必须在 960x540 与移动宽度下不溢出。

视觉要求：
- 页面直接展示教学动画，不做营销页。
- 使用清晰两区布局：说明区、SVG 舞台、控制区。
- SVG 元素必须有稳定 id，便于后续局部调整。
- 动画和滑块默认即可观察核心变化。
"""

MATH_SYSTEM_PROMPT = f"""你是 AetherViz 数学互动动画工程师。
你只输出一个完整可运行 HTML 文件，从 <!DOCTYPE html> 开始，到 </html> 结束。

数学固定技术栈：
1. HTML + SVG + KaTeX + GSAP Timeline。
2. 只允许引入以下外部资源：
   - KaTeX CSS：{_CDN_KATEX_CSS}
   - KaTeX JS：{_CDN_KATEX_JS}
   - GSAP：{_CDN_GSAP}
3. 不使用 Canvas、Three.js、D3、图片或上传能力。
4. 公式只用 KaTeX 渲染，动画只用 GSAP Timeline 管理。

页面结构要求：
- 包含 <main id="app">。
- 包含 <section id="explain-panel">、<section id="stage">、<svg id="math-svg" viewBox="0 0 960 540">、<section id="control-panel" class="control-panel">。
- 同时兼容校验，主舞台外层或同一节点必须包含 id="aetherviz-stage"。
- 包含 class="learning-objectives" 的 <ul>，至少 3 条。
- 控制按钮必须包含 play-animation、pause-animation、reset-animation，速度控制和至少一个 slider。
- 所有按钮和滑块必须绑定真实事件。
- 滑块变化必须同步更新 SVG 和 KaTeX 公式。
- 声明 window.AetherVizRuntime = {{ play, pause, reset, setSpeed, update, getState }}。
- 初始化成功设置 window.__AETHERVIZ_RUNTIME_READY__ = true；失败设置 window.__AETHERVIZ_RUNTIME_ERROR__ 并显示错误。
"""

REVISE_SYSTEM_PROMPT = f"""你是 AetherViz HTML 修订工程师。
根据用户修改意见，直接修订给定 HTML，并输出完整 <!DOCTYPE html>...</html>。

约束：
- 保持当前页面为独立 HTML。
- 不新增 Three.js、Canvas、文件上传、图片上传或外部业务接口。
- 数学页面继续使用 SVG + KaTeX + GSAP；非数学页面继续使用 SVG。
- 所有事件继续使用 addEventListener。
- 保留或补齐 window.AetherVizRuntime 的 play、pause、reset、setSpeed、update、getState。
- 只输出 HTML，不输出 Markdown 或解释。
"""


def _sse_event(event: str, data: dict[str, object]) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


def _progress_event(stage: str, message: str, progress: int, **extra: object) -> str:
    data: dict[str, object] = {
        "success": True,
        "stage": stage,
        "message": message,
        "progress": progress,
    }
    data.update(extra)
    return _sse_event("progress", data)


def _estimate_output_tokens(value: str) -> int:
    cjk_count = len(re.findall(r"[\u4e00-\u9fff]", value))
    word_count = len(re.findall(r"[A-Za-z0-9_]+(?:[-'][A-Za-z0-9_]+)?", value))
    symbol_count = len(re.sub(r"[\u4e00-\u9fffA-Za-z0-9_\s'-]", "", value))
    return max(0, cjk_count + word_count + (symbol_count + 1) // 2)


def _trim_after_html_end(value: str) -> str:
    end_index = value.lower().find("</html>")
    if end_index < 0:
        return value
    return value[:end_index + len("</html>")]


def _compact_html_for_revision(html: str) -> str:
    compacted = _trim_after_html_end(html).strip()
    if len(compacted) <= 22000:
        return compacted
    return (
        compacted[:11000]
        + "\n\n<!-- 中间过长内容已省略，修订时请保留原有页面结构并按修改意见更新 -->\n\n"
        + compacted[-11000:]
    )


def _stream_llm_output(
    prompt: str,
    *,
    system_prompt: str,
    max_tokens: int,
    temperature: float,
    stage: str,
    phase: str,
    message_prefix: str,
    progress_start: int,
    progress_end: int,
) -> Iterator[str]:
    raw_text = ""
    output_tokens_total = 0
    chunk_index = 0

    for chunk in call_llm_stream(
        prompt,
        system_prompt=system_prompt,
        max_tokens=max_tokens,
        temperature=temperature,
    ):
        raw_text += chunk
        chunk_index += 1
        output_tokens = _estimate_output_tokens(chunk)
        output_tokens_total += output_tokens
        progress = min(
            progress_end,
            progress_start + max(1, round((progress_end - progress_start) * min(output_tokens_total, max_tokens) / max_tokens)),
        )
        yield _sse_event(
            "generation_delta",
            {
                "success": True,
                "stage": stage,
                "message": f"{message_prefix}，已输出约 {output_tokens_total} Token",
                "progress": progress,
                "phase": phase,
                "delta": chunk,
                "output_tokens": output_tokens,
                "output_tokens_total": output_tokens_total,
                "chunk_index": chunk_index,
            },
        )
        if "</html>" in raw_text.lower():
            break

    return _trim_after_html_end(raw_text)


def react_generate_stream(
    topic: str,
    phase: str = "plan",
    approved_plan: dict | None = None,
    current_html: str | None = None,
    instruction: str | None = None,
) -> Iterator[str]:
    color = extract_color_from_topic(topic)
    yield _sse_event(
        "start",
        {
            "success": True,
            "stage": "start",
            "message": f"开始处理《{topic}》的互动可视化任务",
            "progress": 3,
            "phase": phase,
        },
    )

    try:
        if phase != "revise":
            match = match_topic_to_knowledge_point(topic)
            if match is not None:
                yield from _static_match_stream(topic, color, match)
                return

        if phase == "plan":
            yield from _planning_stream(topic, color)
            return

        if phase == "generate":
            if not approved_plan:
                yield _error_event("plan_required", "动态生成需要先确认计划", "phase=generate 必须携带 approved_plan")
                return
            plan = normalize_plan(approved_plan, topic, color)
            yield from _generate_from_plan_stream(topic, plan)
            return

        if phase == "revise":
            if not current_html or not current_html.strip():
                yield _error_event("html_required", "修订页面需要 current_html", "phase=revise 必须携带 current_html")
                return
            if not instruction or not instruction.strip():
                yield _error_event("instruction_required", "修订页面需要修改意见", "phase=revise 必须携带 instruction")
                return
            yield from _revise_html_stream(topic, current_html, instruction)
            return

        yield _error_event("invalid_phase", "不支持的生成阶段", f"phase={phase}")
    except StaticAetherVizHtmlError as exc:
        yield _error_event("static_html_missing", "静态知识点 HTML 文件不可用", str(exc))
    except LLMServiceError as exc:
        yield _error_event("llm_error", "调用大模型失败，请检查模型服务配置或稍后重试", str(exc))
    except AetherVizInteractiveHtmlError as exc:
        logger.exception("交互式 HTML 页面生成失败")
        yield _error_event("fallback_failed", "交互式 HTML 页面生成失败", str(exc))
    except AetherVizHtmlValidationError as exc:
        logger.exception("动态 HTML 未通过检查")
        yield _error_event("validation_failed", "生成页面未通过质量检查", str(exc))
    except Exception as exc:
        logger.exception("AetherViz 生成异常")
        yield _error_event("unknown_error", "生成过程中发生异常，请稍后重试", str(exc))


def _error_event(stage: str, message: str, detail: str) -> str:
    return _sse_event(
        "error",
        {
            "success": False,
            "stage": stage,
            "message": message,
            "detail": detail,
        },
    )


def _static_match_stream(topic: str, color: str, match) -> Iterator[str]:
    point = get_knowledge_point(match.knowledge_point_id)
    if point is None:
        raise StaticAetherVizHtmlError(f"知识点不存在：{match.knowledge_point_id}")

    yield _progress_event(
        "static_match",
        f"已命中静态知识点：{match.knowledge_point_title}",
        35,
        subject=match.subject,
        knowledge_domain=match.knowledge_domain,
        knowledge_point_id=match.knowledge_point_id,
        grade=match.grade,
        match_confidence=match.confidence,
        mode="static",
    )
    html_output = load_static_html_for_point(point, color)
    metadata = GenerateAetherVizHtmlMetadata(
        topic=topic,
        attempts=0,
        source="static_html",
        degraded=False,
        subject=match.subject,
        knowledge_domain=match.knowledge_domain,
        knowledge_point_id=match.knowledge_point_id,
        knowledge_point_title=match.knowledge_point_title,
        grade=match.grade,
        render_mode="static",
        match_confidence=match.confidence,
    )
    yield _sse_event(
        "done",
        {
            "success": True,
            "stage": "done",
            "message": "已返回静态互动可视化页面",
            "progress": 100,
            "phase": "generate",
            "mode": "static",
            "html": html_output,
            "metadata": metadata.model_dump(),
        },
    )


def _planning_stream(topic: str, color: str) -> Iterator[str]:
    yield _progress_event("planning", "正在分析知识点，制定教学动画方案", 20, phase="plan")
    for delta in ("识别学科与核心目标...\n", "选择稳定 HTML + SVG 生成模式...\n", "规划动画步骤、控件和校验点...\n"):
        yield _sse_event(
            "plan_delta",
            {
                "success": True,
                "stage": "planning",
                "message": "正在思考教学动画方案",
                "progress": 30,
                "phase": "plan",
                "delta": delta,
            },
        )

    raw_chunks: list[str] = []
    output_tokens_total = 0
    try:
        planning_sys, planning_user = build_planning_prompt(topic, color)
        for chunk in call_llm_stream(planning_user, system_prompt=planning_sys, max_tokens=1200, temperature=0.25):
            raw_chunks.append(chunk)
            output_tokens = _estimate_output_tokens(chunk)
            output_tokens_total += output_tokens
            yield _sse_event(
                "plan_delta",
                {
                    "success": True,
                    "stage": "planning",
                    "message": f"正在思考教学动画方案，已输出约 {output_tokens_total} Token",
                    "progress": 45,
                    "phase": "plan",
                    "delta": chunk,
                    "output_tokens": output_tokens,
                    "output_tokens_total": output_tokens_total,
                },
            )
        plan = parse_planning_result("".join(raw_chunks), topic, color)
    except Exception as exc:
        logger.warning("AetherViz planning 失败，使用兜底规划: %s", exc)
        plan = parse_planning_result("", topic, color)
        yield _sse_event(
            "plan_delta",
            {
                "success": True,
                "stage": "planning",
                "message": "规划模型暂不可用，已切换兜底计划",
                "progress": 55,
                "phase": "plan",
                "delta": "规划模型暂不可用，已使用服务端兜底计划。\n",
            },
        )

    yield _sse_event(
        "plan_ready",
        {
            "success": True,
            "stage": "plan_ready",
            "message": "教学动画方案已生成，请确认后继续生成 HTML 页面",
            "progress": 60,
            "phase": "plan",
            "mode": plan["mode"],
            "plan": plan,
            "subject": plan["subject"],
            "output_tokens_total": output_tokens_total,
        },
    )


def _generate_from_plan_stream(topic: str, plan: dict) -> Iterator[str]:
    yield _progress_event(
        "generating",
        "计划已确认，正在生成独立 HTML 动画页面",
        65,
        phase="generate",
        mode=plan["mode"],
        plan=plan,
        subject=plan["subject"],
    )

    prompt = _build_generation_prompt(topic, plan)
    system_prompt = MATH_SYSTEM_PROMPT if plan["mode"] == "math_svg_katex_gsap" else GENERIC_SVG_SYSTEM_PROMPT
    raw_html = yield from _stream_llm_output(
        prompt,
        system_prompt=system_prompt,
        max_tokens=9000 if plan["mode"] == "math_svg_katex_gsap" else 7600,
        temperature=0.18,
        stage="html_generating",
        phase="generate",
        message_prefix="正在生成互动页面代码",
        progress_start=66,
        progress_end=90,
    )
    output_tokens_total = _estimate_output_tokens(raw_html)
    html_output, warnings = _parse_and_validate_html(raw_html, topic, plan)

    metadata = GenerateAetherVizHtmlMetadata(
        topic=topic,
        attempts=1,
        repaired=False,
        source="llm_svg",
        degraded=True,
        validation_warnings=warnings,
        render_mode=plan["mode"],
        subject=plan["subject"],
        plan=plan,
    )
    yield _sse_event(
        "done",
        {
            "success": True,
            "stage": "done",
            "message": f"已返回自包含互动教学页面，共输出约 {output_tokens_total} Token",
            "progress": 100,
            "phase": "generate",
            "mode": plan["mode"],
            "html": html_output,
            "output_tokens_total": output_tokens_total,
            "metadata": metadata.model_dump(),
        },
    )


def _revise_html_stream(topic: str, current_html: str, instruction: str) -> Iterator[str]:
    yield _progress_event("revising", "正在根据修改意见修订当前 HTML 页面", 20, phase="revise")
    prompt = f"""教学主题：{topic}

用户修改意见：
{instruction.strip()}

当前 HTML：
{_compact_html_for_revision(current_html)}

请输出修订后的完整 HTML。"""
    raw_html = yield from _stream_llm_output(
        prompt,
        system_prompt=REVISE_SYSTEM_PROMPT,
        max_tokens=9000,
        temperature=0.16,
        stage="html_revising",
        phase="revise",
        message_prefix="正在修订互动页面代码",
        progress_start=25,
        progress_end=92,
    )
    output_tokens_total = _estimate_output_tokens(raw_html)
    plan = normalize_plan({}, topic)
    html_output, warnings = _parse_and_validate_html(raw_html, topic, plan)
    metadata = GenerateAetherVizHtmlMetadata(
        topic=topic,
        attempts=1,
        repaired=False,
        source="llm_svg_revision",
        degraded=True,
        validation_warnings=warnings,
        render_mode=plan["mode"],
        subject=plan["subject"],
        plan=plan,
    )
    yield _sse_event(
        "done",
        {
            "success": True,
            "stage": "done",
            "message": f"页面已完成修订，共输出约 {output_tokens_total} Token",
            "progress": 100,
            "phase": "revise",
            "mode": plan["mode"],
            "html": html_output,
            "output_tokens_total": output_tokens_total,
            "metadata": metadata.model_dump(),
        },
    )


def _parse_and_validate_html(raw_html: str, topic: str, plan: dict) -> tuple[str, list[str]]:
    yield_msg = f"LLM AetherViz SVG 响应长度 {len(raw_html)}"
    logger.info(yield_msg)
    html_output = parse_interactive_html(raw_html)
    cleaned_html = sanitize_aetherviz_html(html_output)
    warnings = validate_aetherviz_html(
        cleaned_html,
        topic=topic,
        strict=False,
    )
    return cleaned_html, warnings


def _build_generation_prompt(topic: str, plan: dict) -> str:
    return f"""请根据确认方案生成一个完整、独立、可直接在浏览器运行的互动教学 HTML 页面。

教学主题：{topic}
生成模式：{plan["mode"]}
页面标题：{plan["title"]}
教学目标：{plan["goal"]}
主色调：{plan.get("primary_color", "#22D3EE")}

视觉步骤：
{json.dumps(plan.get("visual_steps", []), ensure_ascii=False, indent=2)}

控制项：
{json.dumps(plan.get("controls", []), ensure_ascii=False, indent=2)}

公式/关键表达：
{json.dumps(plan.get("formulas", []), ensure_ascii=False, indent=2)}

校验点：
{json.dumps(plan.get("validation_points", []), ensure_ascii=False, indent=2)}

请确保：
- HTML 以 <!DOCTYPE html> 开头，以 </html> 结束。
- 主可视化为 SVG，关键元素有稳定 id。
- 提供播放、暂停、重置、速度控制和至少一个变量交互。
- 声明 window.AetherVizRuntime，并提供 play/pause/reset/setSpeed/update/getState。
- 页面末尾保留“由 宾果AI 为你生成❤️”。
"""
