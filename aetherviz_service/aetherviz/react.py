"""AetherViz SSE generator.

动态生成策略：
- 静态知识点命中后直接返回静态 HTML。
- 动态生成走 HTML + CSS + SVG/Canvas/DOM 分层渲染。
- 复杂分镜可按计划使用 GSAP Timeline 编排，Canvas 高频绘制仍由 RAF 负责。
- 生成目标：让中学生通过观察动画和调节参数，自然理解教学主题的核心原理。
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
from aetherviz_service.llm_service import LLMServiceError, LLMStreamChunk, call_llm_stream

logger = logging.getLogger(__name__)

_CDN_KATEX_CSS = "https://cdn.staticfile.net/KaTeX/0.16.9/katex.min.css"
_CDN_KATEX_JS = "https://cdn.staticfile.net/KaTeX/0.16.9/katex.min.js"
_CDN_KATEX_AUTO = "https://cdn.staticfile.net/KaTeX/0.16.9/contrib/auto-render.min.js"
_CDN_GSAP = "https://cdn.jsdelivr.net/npm/gsap@3.15.0/dist/gsap.min.js"
PLANNING_MAX_TOKENS = 1200
HTML_OUTPUT_MAX_TOKENS = 12000
HTML_ENABLE_THINKING = False

GENERIC_SVG_SYSTEM_PROMPT = """你是 AetherViz 互动教学动画工程师。
你的页面是一个面向中学生的互动教学工具，学生通过观察动画和调节参数来理解教学主题的核心原理。

你只输出一个完整可运行 HTML 文件，从 <!DOCTYPE html> 开始，到 </html> 结束。

技术路线（按计划中的 render_stack 执行）：
- svg：用 SVG 表达结构、坐标、几何关系、少量运动对象和清晰标注。
- svg_canvas：Canvas 负责连续运动、轨迹、粒子或残影；SVG 负责坐标轴、辅助线、标签和高亮；DOM 负责解释文案。
- canvas_svg：Canvas 是主视觉，SVG/DOM 只放少量标注和控件，禁止用大量 SVG 节点模拟高频运动。
- dom_svg：流程卡片、阶段解释、时间轴为主，SVG 负责连接线、路径和当前步骤高亮。

动画质量标准（最重要）：
- 动画过渡平滑：状态变化使用统一 requestAnimationFrame 时间线或 CSS transition（200ms~800ms），避免突变。
- 分步演示清晰：当前步骤用颜色/高亮标注，配合简洁文字说明告知学生"现在发生了什么"。
- 数值变化有视觉反馈：滑块拖动时，图形和数值同步更新，无明显延迟。
- 动画默认自动播放，用户可暂停、重置、调速，并能拖动进度或单步回看关键节点。

舞台编排要求：
- 首屏必须是居中的教学舞台，不要把主图缩成角落里的小图；#aetherviz-stage 的主视觉应占页面主体宽度。
- #aetherviz-stage 必须具备居中布局：使用 display:grid; place-items:center; 或 display:flex; align-items:center; justify-content:center;，并让主 SVG/Canvas 设置 margin:auto、max-width:100%、max-height:100%。
- SVG 主视觉不要把核心图形画在 viewBox 左下角；把图形主体放在 viewBox 中心区域，或用 <g id="main-visual-group"> 统一 transform 到舞台中心。
- Canvas 主视觉必须按画布尺寸计算 centerX = width / 2、centerY = height / 2，再围绕中心绘制主体；禁止用固定左下角坐标作为默认主体位置。
- 推荐结构：顶部 3~4 个学习目标胶囊，中间大舞台，底部控制条，公式/结论区紧贴舞台下方。
- 所有标签和公式不能遮挡主图；标签必须有避让或留白，长文字放到舞台外的说明区。
- 每一幕必须有可见的步骤说明元素（例如 class="animation-caption" 或 class="step-caption"），文字说明当前焦点和学生该观察什么。
- 默认状态必须一眼能看出核心现象，不依赖用户先调参。

页面结构要求：
- 三区布局：学习目标区（class="learning-objectives"，至少 3 条）、主可视化区（id="aetherviz-stage"）、控制面板（class="control-panel"）。
- 控制按钮包含 id="play-animation"（播放/重新播放）、id="pause-animation"（暂停）、id="reset-animation"（重置），全部绑定真实事件。
- 所有事件用 addEventListener 绑定，禁止内联事件属性（onXxx="..."）。
- 声明 window.AetherVizRuntime = { play, pause, reset, setSpeed, update, getState }。
- 初始化成功设置 window.__AETHERVIZ_RUNTIME_READY__ = true；异常设置 window.__AETHERVIZ_RUNTIME_ERROR__ 并在页面显示错误提示。
- 页面在 960×540 和移动端宽度下均不溢出。

技术约束：
- 使用 HTML + CSS + SVG/Canvas + 原生 JavaScript，CSS 和 JS 内联。
- 默认不引入 Three.js、D3、GSAP、图片生成或外部业务接口。
- 仅当生成计划明确要求 animation_runtime=gsap_timeline 时，允许引入固定 GSAP CDN，并只把 GSAP 用作时间线编排，不作为渲染栈。
- SVG / Canvas / DOM 关键元素有稳定 id，便于后续修订。
"""

MATH_SYSTEM_PROMPT = """你是 AetherViz 数学互动教学动画工程师。
你的页面让中学生通过拖拽参数、观察图形变化来直观理解数学关系，而不是被动看公式。

你只输出一个完整可运行 HTML 文件，从 <!DOCTYPE html> 开始，到 </html> 结束。

动画质量标准（最重要）：
- 图形变化平滑：几何图形随参数变化时，使用统一 requestAnimationFrame 时间线或 CSS transition 实现流畅过渡。
- 公式与图形联动：参数变化时，公式中对应的数值实时更新，学生同时看到几何直观和代数表达。
- 关键步骤高亮：分步演示时，当前变化的图形元素用对比色标注，并显示简洁文字说明。
- 数值显示清晰：在图形旁边显示当前参数值，随滑块实时更新。
- 每一幕必须有可见的步骤说明元素（例如 class="animation-caption" 或 class="step-caption"），说明当前焦点、变化对象和结论。

舞台编排要求：
- 主图必须居中且足够大，避免小图、标签重叠和公式挤压。
- #aetherviz-stage 必须具备居中布局：使用 display:grid; place-items:center; 或 display:flex; align-items:center; justify-content:center;，并让主 SVG/Canvas 设置 margin:auto、max-width:100%、max-height:100%。
- SVG 坐标系必须让核心几何图形落在 viewBox 中央，不能把三角形、坐标轴或面积块默认画在左下角；必要时用 <g id="main-visual-group"> 包住主体并平移到中心。
- Canvas 场景必须按实际画布尺寸计算中心点并围绕中心绘制，拖动参数后也要保持主体在可视区域中心。
- 推荐结构：顶部学习目标胶囊，中间大比例数学舞台，底部参数控制条，公式/结论区紧贴舞台下方。
- 公式用于解释图形变化，不要先堆公式；变量高亮颜色要和图中对象一致。

技术选型（根据最适合的方案自主选择）：
- 首选 SVG：大多数平面几何、函数图像、向量场景用 SVG 最清晰。
- 允许使用内联 Canvas（<canvas> + 2D Context）：参数方程轨迹、连续曲线、粒子动画等场景。
- 如涉及公式展示，推荐引入 KaTeX（CDN 引入任意稳定版本）；也可用 SVG <text> 或 HTML 文本展示。
- 默认不引入 Three.js、D3、GSAP 或其他动画库。
- 仅当生成计划明确要求 animation_runtime=gsap_timeline 时，允许引入固定 GSAP CDN，并用 GSAP Timeline 管理分镜节奏、公式同步高亮和播放控制。

页面结构要求：
- 三区布局：学习目标区（class="learning-objectives"，至少 3 条说明学生能学到什么）、主可视化区（id="aetherviz-stage"，内含图形主体）、控制面板（class="control-panel"）。
- 控制按钮包含 id="play-animation"（播放演示）、id="pause-animation"（暂停）、id="reset-animation"（重置），全部绑定真实事件。
- 所有事件用 addEventListener 绑定，禁止内联事件属性（onXxx="..."）。
- 声明 window.AetherVizRuntime = { play, pause, reset, setSpeed, update, getState }。
- 初始化成功设置 window.__AETHERVIZ_RUNTIME_READY__ = true；异常设置 window.__AETHERVIZ_RUNTIME_ERROR__ 并在页面显示错误提示。
- 页面在 960×540 和移动端宽度下均不溢出。
"""

REVISE_SYSTEM_PROMPT = """你是 AetherViz HTML 修订工程师。
根据用户修改意见，直接修订给定 HTML，并输出完整 <!DOCTYPE html>...</html>。

修订原则：
- 修订后的页面动画必须能完整播放并清晰演示教学目标，这是首要判断标准。
- 修订后的 #aetherviz-stage 内主 SVG/Canvas 必须居中显示；如果主图偏在左下角或角落，优先修复 SVG viewBox/主体 group transform 或 Canvas centerX/centerY 绘制逻辑。
- 保持当前页面为独立 HTML，CSS 和 JS 继续内联。
- 所有事件继续使用 addEventListener。
- 保留或补齐 window.AetherVizRuntime 的 play、pause、reset、setSpeed、update、getState。
- 不引入 Three.js 或外部业务接口；若当前 HTML 已使用 GSAP Timeline，可保留固定版本 GSAP CDN 并修复其播放控制，不要退回静态页面。
- 只输出 HTML，不输出 Markdown 或解释。
"""

REPAIR_SYSTEM_PROMPT = """你是 AetherViz HTML 自动修复工程师。
你会收到一次失败的 HTML 输出、服务端校验错误和原始生成上下文。

修复的第一优先级：动画能完整播放并清晰演示教学目标。
在保证动画质量的前提下，再修复具体的结构问题。

具体修复要求：
- 只输出修复后的完整 <!DOCTYPE html>...</html>，不输出 Markdown 或解释。
- 保持独立 HTML，CSS 与业务 JavaScript 内联。
- 确保学习目标（class="learning-objectives"，至少 3 条）、主可视化区（id="aetherviz-stage"）、控制面板（class="control-panel"）存在。
- 确保 #aetherviz-stage 内主 SVG/Canvas 在舞台水平和垂直居中；SVG 需要用居中的 viewBox 或 main-visual-group，Canvas 需要基于 width/height 的中心点绘制。
- 确保播放/暂停/重置按钮（id="play-animation"、id="pause-animation"、id="reset-animation"）存在并绑定真实事件。
- 确保 window.AetherVizRuntime = { play, pause, reset, setSpeed, update, getState } 声明完整。
- 确保 window.__AETHERVIZ_RUNTIME_READY__ = true 在初始化成功时设置。
- 不引入 Three.js 或外部业务接口。若原计划 animation_runtime=gsap_timeline，应保留固定 GSAP CDN、补齐 timeline label 和控制绑定，不要退回静态 SVG。
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


def _coerce_llm_stream_chunk(chunk: object) -> LLMStreamChunk:
    if isinstance(chunk, LLMStreamChunk):
        return chunk
    if isinstance(chunk, str):
        return LLMStreamChunk(kind="content", delta=chunk)
    if isinstance(chunk, dict):
        return LLMStreamChunk(kind=str(chunk.get("kind") or "content"), delta=str(chunk.get("delta") or ""))
    return LLMStreamChunk(
        kind=str(getattr(chunk, "kind", "content") or "content"),
        delta=str(getattr(chunk, "delta", "") or ""),
    )


def _is_math_mode(mode: str | None) -> bool:
    return mode == "math_interactive"


def _is_gsap_timeline_plan(plan: dict | None) -> bool:
    return bool(plan and plan.get("animation_runtime") == "gsap_timeline")


def _system_prompt_for_plan(base_prompt: str, plan: dict) -> str:
    if not _is_gsap_timeline_plan(plan):
        return base_prompt
    return f"""{base_prompt}

GSAP Timeline 计划要求：
- 本计划 animation_runtime=gsap_timeline，必须引入且只能引入固定 CDN：{_CDN_GSAP}
- 使用 const tl = gsap.timeline({{ paused: true, defaults: {{ ease: "power2.inOut" }}, onUpdate: syncRuntimeState }});
- 使用 addLabel() 为每个 timeline_scenes scene 建立可读 label，至少 3 个 label，label 名称应与 scene id 对应。
- timeline 内至少包含 3 个真实 tween/set 调用，用于元素进出场、步骤高亮、公式同步或 caption 更新。
- 播放按钮调用 tl.play() 或 tl.restart()；暂停按钮调用 tl.pause()；重置按钮调用 tl.pause(0) 或 tl.progress(0)。
- 速度控制调用 tl.timeScale(value)，进度控制调用 tl.progress(value)。
- window.AetherVizRuntime 统一代理 timeline：play、pause、reset、setSpeed、update、getState 都要真实读写 tl。
- Canvas 高频运动仍用 requestAnimationFrame 绘制；如果页面使用 Canvas，GSAP 只驱动 state.progress 或阶段值，再调用 renderCanvas。
"""


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

    for raw_chunk in call_llm_stream(
        prompt,
        system_prompt=system_prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        enable_thinking=HTML_ENABLE_THINKING,
    ):
        chunk = _coerce_llm_stream_chunk(raw_chunk)
        if not chunk.delta:
            continue
        if chunk.kind == "reasoning":
            output_tokens = _estimate_output_tokens(chunk.delta)
            yield _sse_event(
                "thinking_delta",
                {
                    "success": True,
                    "stage": stage,
                    "message": f"{message_prefix}，正在推理",
                    "progress": progress_start,
                    "phase": phase,
                    "delta": chunk.delta,
                    "output_tokens": output_tokens,
                    "output_tokens_total": output_tokens_total,
                    "chunk_index": chunk_index,
                },
            )
            continue

        delta = chunk.delta
        raw_text += delta
        chunk_index += 1
        output_tokens = _estimate_output_tokens(delta)
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
                "delta": delta,
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
    for delta in (
        "识别学科与核心目标...\n",
        "选择 SVG/Canvas/DOM 渲染栈与动画运行时...\n",
        "规划学生友好默认数值...\n",
        "规划舞台布局、教学分镜、时间线和互动控件...\n",
    ):
        yield _sse_event(
            "plan_delta",
            {
                "success": True,
                "stage": "planning",
                "message": "正在生成教学动画方案",
                "progress": 30,
                "phase": "plan",
                "delta": delta,
            },
        )

    raw_chunks: list[str] = []
    output_tokens_total = 0
    try:
        planning_sys, planning_user = build_planning_prompt(topic, color)
        for raw_chunk in call_llm_stream(
            planning_user,
            system_prompt=planning_sys,
            max_tokens=PLANNING_MAX_TOKENS,
            temperature=0.25,
            enable_thinking=False,
        ):
            chunk = _coerce_llm_stream_chunk(raw_chunk)
            if not chunk.delta:
                continue
            if chunk.kind == "reasoning":
                continue
            raw_chunks.append(chunk.delta)
            output_tokens = _estimate_output_tokens(chunk.delta)
            output_tokens_total += output_tokens
            yield _sse_event(
                "plan_delta",
                {
                    "success": True,
                    "stage": "planning",
                    "message": f"正在生成教学动画方案，已输出约 {output_tokens_total} Token",
                    "progress": 45,
                    "phase": "plan",
                    "delta": chunk.delta,
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
    base_system_prompt = MATH_SYSTEM_PROMPT if _is_math_mode(plan["mode"]) else GENERIC_SVG_SYSTEM_PROMPT
    system_prompt = _system_prompt_for_plan(base_system_prompt, plan)
    raw_html = yield from _stream_llm_output(
        prompt,
        system_prompt=system_prompt,
        max_tokens=HTML_OUTPUT_MAX_TOKENS,
        temperature=0.18,
        stage="html_generating",
        phase="generate",
        message_prefix="正在生成互动页面代码",
        progress_start=66,
        progress_end=90,
    )
    output_tokens_total = _estimate_output_tokens(raw_html)
    html_output, warnings, attempts, repaired = yield from _parse_validate_or_repair_stream(
        raw_html,
        topic=topic,
        plan=plan,
        phase="generate",
        original_prompt=prompt,
        source_label="生成",
    )

    metadata = GenerateAetherVizHtmlMetadata(
        topic=topic,
        attempts=attempts,
        repaired=repaired,
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
        max_tokens=HTML_OUTPUT_MAX_TOKENS,
        temperature=0.16,
        stage="html_revising",
        phase="revise",
        message_prefix="正在修订互动页面代码",
        progress_start=25,
        progress_end=92,
    )
    output_tokens_total = _estimate_output_tokens(raw_html)
    plan = normalize_plan({}, topic)
    html_output, warnings, attempts, repaired = yield from _parse_validate_or_repair_stream(
        raw_html,
        topic=topic,
        plan=plan,
        phase="revise",
        original_prompt=prompt,
        source_label="修订",
    )
    metadata = GenerateAetherVizHtmlMetadata(
        topic=topic,
        attempts=attempts,
        repaired=repaired,
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


def _parse_validate_or_repair_stream(
    raw_html: str,
    *,
    topic: str,
    plan: dict,
    phase: str,
    original_prompt: str,
    source_label: str,
) -> Iterator[tuple[str, list[str], int, bool]]:
    try:
        html_output, warnings = _parse_and_validate_html(raw_html, topic, plan)
        return html_output, warnings, 1, False
    except (AetherVizInteractiveHtmlError, AetherVizHtmlValidationError) as first_exc:
        first_error = str(first_exc)
        yield _progress_event(
            "repairing",
            f"{source_label}结果未通过质量检查，正在自动修复一次",
            93,
            phase=phase,
            mode=plan.get("mode"),
            subject=plan.get("subject"),
            detail=first_error,
        )

        repair_prompt = _build_repair_prompt(
            topic=topic,
            plan=plan,
            original_prompt=original_prompt,
            raw_html=raw_html,
            error_detail=first_error,
            source_label=source_label,
        )
        repaired_raw_html = yield from _stream_llm_output(
            repair_prompt,
            system_prompt=_system_prompt_for_plan(REPAIR_SYSTEM_PROMPT, plan),
            max_tokens=HTML_OUTPUT_MAX_TOKENS,
            temperature=0.08,
            stage="html_repairing",
            phase=phase,
            message_prefix="正在修复互动页面代码",
            progress_start=94,
            progress_end=98,
        )
        try:
            html_output, warnings = _parse_and_validate_html(repaired_raw_html, topic, plan)
        except (AetherVizInteractiveHtmlError, AetherVizHtmlValidationError) as second_exc:
            combined = f"首次失败：{first_error}；修复失败：{second_exc}"
            raise type(first_exc)(combined) from second_exc
        return html_output, warnings, 2, True


def _build_repair_prompt(
    *,
    topic: str,
    plan: dict,
    original_prompt: str,
    raw_html: str,
    error_detail: str,
    source_label: str,
) -> str:
    return f"""请修复一次失败的 AetherViz {source_label} HTML 输出。

教学主题：{topic}
教学目标：{plan.get("goal", "")}
动画运行时：{plan.get("animation_runtime", "native")}
分镜时间线：
{json.dumps(plan.get("timeline_scenes", []), ensure_ascii=False, indent=2)}
默认数值设计：
{json.dumps(plan.get("number_design") or {}, ensure_ascii=False, indent=2)}

修复第一目标：确保动画能完整播放并清晰演示上述教学目标。
舞台居中目标：#aetherviz-stage 内主 SVG/Canvas 必须在画布中居中显示，不能偏在左下角或任意角落。若是 SVG，请修正 viewBox、preserveAspectRatio、主体 group transform 或元素坐标；若是 Canvas，请按 width/2、height/2 计算中心后绘制主体。

服务端校验错误（需逐一修复）：
{error_detail}

原始任务提示词（供参考）：
{original_prompt}

失败 HTML（请在此基础上修复，不要推倒重写）：
{_compact_html_for_revision(raw_html)}

请直接输出修复后的完整 HTML，不要输出任何解释。"""


def _build_generation_prompt(topic: str, plan: dict) -> str:
    animation_strategy = plan.get("animation_strategy", "step_by_step")
    render_stack = plan.get("render_stack") or "svg"
    animation_runtime = plan.get("animation_runtime") or "native"
    strategy_hint = {
        "step_by_step": '分步骤演示：每个步骤有清晰的过渡动画（200~600ms），当前步骤用高亮颜色标注，配合文字说明告知学生"现在发生了什么"、"应该观察什么"。',
        "continuous": "连续动画：运动过程平滑流畅（requestAnimationFrame 驱动），轨迹清晰可见，学生可通过速度控制观察细节，关键时刻用颜色和标注突出。",
        "interactive_param": "参数调控：学生拖动滑块时图形实时响应（无延迟感），数值在图形旁同步更新，让学生通过探索不同参数发现规律。",
    }.get(animation_strategy, "动画流畅，演示清晰，分步骤高亮当前状态。")
    render_stack_hint = {
        "svg": "使用 SVG 作为主视觉：适合结构、几何、坐标轴和少量运动对象。初始化元素后通过 transform、d、x/y 等属性更新，禁止每帧重建整棵 SVG。",
        "svg_canvas": "使用 SVG + Canvas 分层：Canvas 绘制连续运动、轨迹、粒子或残影；SVG 叠加坐标轴、辅助线、关键标签和高亮；DOM 显示步骤说明和公式。",
        "canvas_svg": "使用 Canvas 作为主视觉：高频动画和大量对象全部在 Canvas 中绘制；SVG/DOM 只保留少量标签、交互热点、说明和公式。",
        "dom_svg": "使用 DOM + SVG：流程节点、阶段卡片和文字解释由 DOM 承担，SVG 负责连接线、路径移动和当前步骤高亮。",
    }.get(str(render_stack), "根据主题选择 SVG、Canvas 或 DOM/SVG 分层，确保主视觉清晰可读。")

    formulas = plan.get("formulas", [])
    formula_section = (
        f"核心公式/关键表达（需在页面中展示，并随参数实时更新）:\n{json.dumps(formulas, ensure_ascii=False, indent=2)}\n"
        if formulas
        else ""
    )
    number_design = plan.get("number_design") or {}
    number_design_section = (
        f"默认数值设计（必须落实到初始状态、控件默认值和公式数值中）:\n{json.dumps(number_design, ensure_ascii=False, indent=2)}\n"
        if number_design
        else ""
    )
    timeline_scenes = plan.get("timeline_scenes", [])
    timeline_section = (
        f"分镜时间线（每一幕都要能在页面里播放、暂停、重置和拖动进度观察）:\n{json.dumps(timeline_scenes, ensure_ascii=False, indent=2)}\n"
        if timeline_scenes
        else ""
    )
    if animation_runtime == "gsap_timeline":
        runtime_section = f"""动画运行时（必须落实）：
- 使用 GSAP Timeline 编排动画，不要只引用库。
- 引入且只能引入固定 CDN：{_CDN_GSAP}
- 声明 const tl = gsap.timeline({{ paused: true, defaults: {{ ease: "power2.inOut" }}, onUpdate: syncRuntimeState }});
- timeline_scenes 每个 scene 都要有 tl.addLabel(scene.id, ...)，至少 3 个 label。
- 每个 scene 至少对应一个 .to() / .from() / .fromTo() / .set()，用来驱动画面、caption、公式或高亮。
- id="play-animation" 绑定 tl.play() 或 tl.restart()；id="pause-animation" 绑定 tl.pause()；id="reset-animation" 绑定 tl.pause(0) 或 tl.progress(0)。
- 速度控件绑定 tl.timeScale(value)，进度控件绑定 tl.progress(value)。
- animation-caption 或 step-caption 必须随 tl 的当前 scene 同步更新。
- window.AetherVizRuntime 必须代理 timeline 的 play、pause、reset、setSpeed、update、getState。
- Canvas 高频运动仍用 requestAnimationFrame 绘制；若使用 Canvas，GSAP 只驱动 progress/state，再调用 renderCanvas。
"""
    else:
        runtime_section = """动画运行时（必须落实）：
- 使用 native 运行时：requestAnimationFrame、CSS transition、classList 或原生 DOM/SVG/Canvas 更新。
- 不要引入 GSAP；播放、暂停、重置、速度和进度控制仍必须真实驱动画面。
"""

    return f"""请根据以下教学方案，生成一个完整、独立、可直接在浏览器运行的互动教学 HTML 页面。

教学主题：{topic}
页面标题：{plan["title"]}
教学目标：{plan["goal"]}
主色调：{plan.get("primary_color", "#22D3EE")}

渲染栈（务必落实，不要只画静态 SVG）：
{render_stack_hint}

{runtime_section}

舞台布局（首屏应按此编排）：
{plan.get("stage_layout", "顶部学习目标，中间大舞台，底部控制条和公式结论区。")}

主视觉居中契约（必须落实，服务端会校验）：
- #aetherviz-stage 使用居中布局，例如 display:grid; place-items:center; 或 display:flex; align-items:center; justify-content:center;。
- 主 SVG/Canvas 设置 display:block; margin:auto; max-width:100%; max-height:100%，SVG 还要设置 preserveAspectRatio="xMidYMid meet"。
- SVG 主体不要画在 viewBox 的左下角：核心图形的视觉中心应接近 viewBox 中心；推荐使用 <g id="main-visual-group"> 包住主体并把它平移到舞台中央。
- Canvas 主体不要用固定左下角坐标绘制：每次 resize/render 都按 const centerX = width / 2、const centerY = height / 2 计算中心点，再围绕中心绘制。

教学分镜（按镜头组织动画，不要把所有元素一次性堆出来）：
{json.dumps(plan.get("storyboard", []), ensure_ascii=False, indent=2)}

{timeline_section}

{number_design_section}

动画演示策略（务必实现）：
{strategy_hint}

视觉演示步骤（按顺序实现每一步的动画效果）：
{json.dumps(plan.get("visual_steps", []), ensure_ascii=False, indent=2)}

交互控件（每个控件必须绑定真实功能，不能是装饰性的）：
{json.dumps(plan.get("controls", []), ensure_ascii=False, indent=2)}

{formula_section}页面末尾保留"由 宾果AI 为你生成❤️"。
"""
