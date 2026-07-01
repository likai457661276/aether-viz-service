"""AetherViz SSE generator — 双阶段 SSE (plan / generate)。

静态知识点优先命中；未命中时采用双阶段流程：
  phase=plan  → 流式规划，返回 plan_ready 事件
  phase=generate (+ approved_plan) → 流式生成 HTML，并在首次校验失败时自动修复一次
"""

import json
import logging
import re
from collections.abc import Iterator

from aetherviz_service.aetherviz.fallback_validator import (
    AetherVizInteractiveHtmlError,
    parse_interactive_html,
)
from aetherviz_service.aetherviz.knowledge_points import get_knowledge_point
from aetherviz_service.aetherviz.matcher import match_topic_to_knowledge_point
from aetherviz_service.aetherviz.schemas.aetherviz import GenerateAetherVizHtmlMetadata
from aetherviz_service.aetherviz.static_html import (
    DEFAULT_PRIMARY_COLOR,
    StaticAetherVizHtmlError,
    extract_color_from_topic,
    load_static_html_for_point,
)
from aetherviz_service.aetherviz.validator import (
    AetherVizHtmlValidationError,
    sanitize_aetherviz_html,
    validate_aetherviz_html,
)
from aetherviz_service.aetherviz.fallback_planner import (
    build_planning_prompt,
    normalize_plan,
    parse_planning_result,
)
from aetherviz_service.llm_service import LLMServiceError, call_llm, call_llm_stream

logger = logging.getLogger(__name__)

# ─── CDN URL 常量（与 validator.py ALLOWED_EXTERNAL_URLS 保持一致，避免版本漂移）───
_CDN_TAILWIND = "https://cdn.tailwindcss.com"
_CDN_THREEJS = "https://cdn.staticfile.net/three.js/r134/three.min.js"
_CDN_KATEX_CSS = "https://cdn.staticfile.net/KaTeX/0.16.9/katex.min.css"
_CDN_KATEX_JS = "https://cdn.staticfile.net/KaTeX/0.16.9/katex.min.js"
_CDN_KATEX_AUTO = "https://cdn.staticfile.net/KaTeX/0.16.9/contrib/auto-render.min.js"
_CDN_D3 = "https://cdn.staticfile.net/d3/7.9.0/d3.min.js"

FALLBACK_SYSTEM_PROMPT = f"""你是 AetherViz Master 5.2 互动教育可视化建筑师。
你的任务是根据已经确认的结构化计划，生成一个完整、稳定、课堂可演示、数值可感知的自包含互动教学 HTML 页面。

输出要求：
1. 只能输出一个完整 HTML 文件，从 <!DOCTYPE html> 开始，到 </html> 结束。
2. 不要输出 Markdown、代码围栏、解释或说明。
3. CSS 与 JavaScript 必须内联；按计划的 render_stack 决定是否引入 CDN。
4. 必须使用以下固定 CDN URL（不得更换版本或域名）：
   - Tailwind CSS：{_CDN_TAILWIND}
   - Three.js r134：{_CDN_THREEJS}（仅 3D/Hybrid 路由引入）
   - KaTeX CSS：{_CDN_KATEX_CSS}
   - KaTeX JS：{_CDN_KATEX_JS}
   - KaTeX Auto-render：{_CDN_KATEX_AUTO}
   - D3 v7：{_CDN_D3}（仅 SVG/数据图表路由引入）

AetherViz 5.2 硬性规范与安全红线：
- ❌ 安全红线：严禁在 HTML 标签内直接编写任何内联事件属性（如 ❌ onclick="..."、ondragover="..."、ondrop="..."、ondragleave="..."、onload="..." 等）。所有的点击、拖拽、输入监听等交互，必须全部在 <script> 标签中获取 DOM 元素并使用 .addEventListener('click/dragover/...', ...) 进行动态事件注册和绑定。
- 按计划选择主渲染器，不要所有主题默认 Three.js。SVG 能清楚表达时优先 SVG/D3/DOM。
- 页面包含顶部导航、左侧学习栏、中央主渲染区、控制面板。
- 侧边栏必须包含学习目标（class="learning-objectives" 的 <ul>，至少 3 条 <li>）、核心公式/概念、原理解释、课堂演示提示、数值为什么这样选、为什么重要。
- 控制面板中每个重点变量必须同时显示名称、当前值、单位、推荐值和课堂提示。
- 默认值、范围和随机实验数值必须便于学生心算和比较。
- 控制按钮必须使用以下固定 ID（不得更改）：
    id="play-animation"（播放/重新播放）、id="pause-animation"（暂停）、
    id="step-animation"（单步）、id="reset-animation"（重置）、
    id="random-experiment"（随机实验）、id="restore-recommended"（恢复推荐值）。
  点击事件通过 document.getElementById('play-animation').addEventListener('click', ...) 绑定。
- 动画必须使用统一 Animation Runtime：一个 requestAnimationFrame 主循环、delta 钳制、固定时间步 1/60、每帧最多 5 个物理子步。
- 所有图层共享同一个 state 对象、同一个 resize 管线；resize 时同步 renderer、SVG viewBox、Canvas 尺寸和 HUD。
- Three.js 路由必须检测 WebGL，可用 HemisphereLight + DirectionalLight。
  OrbitControls 必须内联简化实现，类名为 AetherVizOrbitControls，并挂载到 window.AetherVizOrbitControls。
  实现必须包含 enableDamping、dampingFactor 属性和 update() 方法。
- SVG/D3 动态节点默认不超过 300；Canvas/粒子对象必须复用。
- 初始化必须用 try/catch 包裹：
    成功时执行 window.__AETHERVIZ_RUNTIME_READY__ = true;
    失败时执行 window.__AETHERVIZ_RUNTIME_ERROR__ = error.message; 并立刻在页面上渲染展示一个高对比度的友好报错面板（必须采用深色背景如 #0F172A 或 #1E293B，明亮的高对比度文字如纯白 #FFFFFF 或亮红 #EF4444，以及醒目的红色边框 border border-red-600，字号不小于 14px，确保错误信息字迹清晰、极易阅读，绝对不能白屏）。
- CDN 资源加载失败时必须显示缺失资源名称和刷新提示。
- 移动端控制面板、公式、测验和主动画不能互相遮挡。
- HTML 末尾内容添加"由 宾果AI 为你生成❤️"。
- ⚠️ 篇幅与体积控制（防截断）：大模型单次生成有 token 长度限制。请务必保持 CSS 和 JS 逻辑高度精练。尽量使用 Tailwind CSS 完成排版，不要在 <style> 中书写大段冗余的自定义 CSS。避免引入极其冗长的数据表或书写大段代码注释。力求页面功能完整且代码行数紧凑，控制产出在 2500 词内，确保以 </html> 顺利完整闭合。

视觉风格：
- 赛博教育风、玻璃拟态、霓虹强调色。
- 使用 Professional Teal-Cyan Theme，并可按学科切换强调色。
- 文字清晰，不使用阻塞式 alert/confirm。

自检：
- 页面加载后首屏主渲染区非空。
- 所有按钮和滑块可用。
- 暂停后物理状态不继续变化。
- 默认状态无需调参即可看出核心现象。
- window.__AETHERVIZ_RUNTIME_READY__ 在成功初始化后必须为 true。
"""

FALLBACK_REPAIR_SYSTEM_PROMPT = f"""你是极其专业、充满创造力的互动教学可视化前端工程师。
你的任务是修复一个在之前生成中未通过安全、结构或依赖规则校验的自包含 HTML 教学页面。

【修复原则】：
1. 必须完全保留原页面的教学主题、所有的核心概念、学习目标和已实现的交互图形/JS 逻辑（不要擅自删除它们）。
2. 只针对提供的【校验错误】进行精准修复。
3. 必须输出且仅输出一个完整的，修复后的 <!DOCTYPE html> ... </html> 教学网页。
4. 严禁在输出中包裹任何 Markdown 标记（如 ```html 等）或任何解释说明文字，直接以 <!DOCTYPE html> 开头，以 </html> 结尾。
5. 所有的 CSS 样式、JavaScript 逻辑必须写在 <style> 和 <script> 标签内，实现完全的自包含。

【硬性规范（修复后必须满足，否则仍会校验失败）】：
- ❌ 绝对禁止在 HTML 标签内书写任何内联事件属性（如 onclick、ondragover、ondrop、onload 等），必须全部通过 DOM 获取并用 addEventListener() 动态绑定监听器！
- CDN URL 必须使用以下固定地址：
    Tailwind：{_CDN_TAILWIND}
    Three.js：{_CDN_THREEJS}（仅 3D 路由）
    KaTeX CSS：{_CDN_KATEX_CSS} / KaTeX JS：{_CDN_KATEX_JS} / Auto-render：{_CDN_KATEX_AUTO}
    D3：{_CDN_D3}（仅 SVG/图表路由）
- 学习目标必须在 class="learning-objectives" 的 <ul> 内以 <li> 列出，至少 3 条。
- 控制按钮 ID 固定：play-animation / pause-animation / step-animation / reset-animation /
  random-experiment / restore-recommended，通过 getElementById + addEventListener('click') 绑定。
- OrbitControls（如使用）必须内联，类名 AetherVizOrbitControls，挂载至 window.AetherVizOrbitControls，
  包含 enableDamping / dampingFactor / update()。
- 初始化 try/catch：成功分支 window.__AETHERVIZ_RUNTIME_READY__ = true；
  失败分支 window.__AETHERVIZ_RUNTIME_ERROR__ = error.message; 并在页面上渲染展示一个高对比度的友好报错面板（深色背景 #0F172A，红色粗边框，纯白文字 #FFFFFF，确保字迹清晰可读）。

【设计与自愈闭合规范】：
- 确保页面背景使用深色调高级背景（如 #0F172A 或更深颜色）。
- 大模型输出可能因 Token 限制被截断，请尽量精简非核心样式，确保以 </html> 完整闭合。
"""


# ─── 工具函数 ───────────────────────────────────────────────────────────────

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


def _resolve_max_tokens(plan: dict) -> int:
    """根据渲染路由动态计算 max_tokens 上限。

    Three.js 页面需要内联 OrbitControls、场景/相机/渲染器初始化和动画循环，
    代码量远大于 SVG/DOM 页面，按渲染器差异化分配上限以避免截断或浪费。

    token 估算（基于实测 HTML 输出）：
        three / hybrid : ~6000-9000 tokens（含 OrbitControls 内联实现）
        canvas         : ~4000-6000 tokens
        svg / d3       : ~3000-5000 tokens
        dom            : ~2000-4000 tokens
    """
    renderer = str(plan.get("main_renderer") or "").lower()
    if "three" in renderer or "hybrid" in renderer:
        return 10000
    if "canvas" in renderer:
        return 8000
    if "svg" in renderer or "d3" in renderer:
        return 7000
    if "dom" in renderer:
        return 5000
    return 8000  # 默认兜底


def _stream_llm_output(
    prompt: str,
    *,
    system_prompt: str,
    max_tokens: int,
    temperature: float,
    stage: str,
    message_prefix: str,
    progress_start: int,
    progress_end: int,
) -> Iterator[str]:
    """流式调用 LLM，同步 yield SSE generation_delta 事件，并通过 return 返回拼接后的完整文本。

    调用方必须用 `result = yield from _stream_llm_output(...)` 接收返回值（PEP 380）。
    """
    raw_chunks: list[str] = []
    output_tokens_total = 0
    chunk_index = 0

    for chunk in call_llm_stream(
        prompt,
        system_prompt=system_prompt,
        max_tokens=max_tokens,
        temperature=temperature,
    ):
        raw_chunks.append(chunk)
        chunk_index += 1
        output_tokens = _estimate_output_tokens(chunk)
        output_tokens_total += output_tokens
        progress = min(
            progress_end,
            progress_start + max(1, round(
                (progress_end - progress_start) * min(output_tokens_total, max_tokens) / max_tokens
            )),
        )
        yield _sse_event(
            "generation_delta",
            {
                "success": True,
                "stage": stage,
                "message": f"{message_prefix}，已输出约 {output_tokens_total} Token",
                "progress": progress,
                "phase": "generate",
                "delta": chunk,
                "output_tokens": output_tokens,
                "output_tokens_total": output_tokens_total,
                "chunk_index": chunk_index,
            },
        )

    return "".join(raw_chunks)


# ─── 主入口 ──────────────────────────────────────────────────────────────────

def react_generate_stream(
    topic: str,
    phase: str = "plan",
    approved_plan: dict | None = None,
) -> Iterator[str]:
    """生成 AetherViz 的双阶段 SSE 流式响应。"""
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
        match = match_topic_to_knowledge_point(topic)
        if match is not None:
            yield from _static_match_stream(topic, color, match)
            return

        if phase == "plan":
            yield from _planning_stream(topic, color)
            return

        if phase == "generate":
            if not approved_plan:
                yield _sse_event(
                    "error",
                    {
                        "success": False,
                        "stage": "plan_required",
                        "message": "动态生成需要先确认计划",
                        "detail": "phase=generate 必须携带 approved_plan",
                    },
                )
                return

            plan = normalize_plan(approved_plan, topic, color)
            yield from _generate_from_approved_plan_stream(topic, color, plan)
            return

        yield _sse_event(
            "error",
            {
                "success": False,
                "stage": "invalid_phase",
                "message": "不支持的生成阶段",
                "detail": f"phase={phase}",
            },
        )
    except StaticAetherVizHtmlError as exc:
        yield _sse_event(
            "error",
            {
                "success": False,
                "stage": "static_html_missing",
                "message": "静态知识点 HTML 文件不可用",
                "detail": str(exc),
            },
        )
    except LLMServiceError as exc:
        yield _sse_event(
            "error",
            {
                "success": False,
                "stage": "llm_error",
                "message": "调用大模型失败，请检查模型服务配置或稍后重试",
                "detail": str(exc),
            },
        )
    except AetherVizInteractiveHtmlError as exc:
        logger.exception("交互式 HTML 页面生成失败")
        yield _sse_event(
            "error",
            {
                "success": False,
                "stage": "fallback_failed",
                "message": "交互式 HTML 页面生成失败",
                "detail": str(exc),
            },
        )
    except AetherVizHtmlValidationError as exc:
        logger.exception("降级 HTML 未通过检查")
        yield _sse_event(
            "error",
            {
                "success": False,
                "stage": "validation_failed",
                "message": "降级 HTML 未通过检查",
                "detail": str(exc),
            },
        )
    except Exception as exc:
        logger.exception("AetherViz 生成异常")
        yield _sse_event(
            "error",
            {
                "success": False,
                "stage": "unknown_error",
                "message": "生成过程中发生异常，请稍后重试",
                "detail": str(exc),
            },
        )


# ─── 静态命中路径 ─────────────────────────────────────────────────────────────

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
        render_mode=match.render_mode,
        match_confidence=match.confidence,
    )
    yield _sse_event(
        "done",
        {
            "success": True,
            "stage": "done",
            "message": "已返回静态互动可视化页面",
            "progress": 100,
            "html": html_output,
            "metadata": metadata.model_dump(),
        },
    )


# ─── 规划阶段 ─────────────────────────────────────────────────────────────────

def _planning_stream(topic: str, color: str) -> Iterator[str]:
    yield _progress_event("planning", "正在分析知识点，制定可视化规划...", 20, degraded=True)
    for delta in (
        "识别学科与实验类型...\n",
        "选择最稳定的主渲染器与辅助图层...\n",
        "规划课堂演示变量、单位和推荐值...\n",
    ):
        yield _sse_event(
            "plan_delta",
            {
                "success": True,
                "stage": "planning",
                "message": "正在思考可视化计划",
                "progress": 30,
                "delta": delta,
            },
        )

    raw_chunks: list[str] = []
    output_tokens_total = 0
    try:
        planning_sys, planning_user = build_planning_prompt(topic, color)
        for chunk in call_llm_stream(
            planning_user,
            system_prompt=planning_sys,
            max_tokens=1400,
            temperature=0.35,
        ):
            raw_chunks.append(chunk)
            output_tokens = _estimate_output_tokens(chunk)
            output_tokens_total += output_tokens
            yield _sse_event(
                "plan_delta",
                {
                    "success": True,
                    "stage": "planning",
                    "message": f"正在思考可视化计划，已输出约 {output_tokens_total} Token",
                    "progress": 45,
                    "delta": chunk,
                    "output_tokens": output_tokens,
                    "output_tokens_total": output_tokens_total,
                },
            )
        plan = parse_planning_result("".join(raw_chunks), topic, color)
    except Exception as exc:
        logger.warning(f"AetherViz fallback planning 失败，使用兜底规划: {exc}")
        plan = parse_planning_result("", topic, color)
        yield _sse_event(
            "plan_delta",
            {
                "success": True,
                "stage": "planning",
                "message": "规划模型暂不可用，已切换兜底计划",
                "progress": 55,
                "delta": "规划模型暂不可用，已使用服务端兜底计划。\n",
            },
        )

    yield _sse_event(
        "plan_ready",
        {
            "success": True,
            "stage": "plan_ready",
            "message": "计划已生成，请确认后继续生成互动课件",
            "progress": 60,
            "plan": plan,
            "subject": plan["subject"],
            "core_concepts": plan["core_concepts"],
            "render_mode": plan["render_stack"]["mode"],
            "output_tokens_total": output_tokens_total,
        },
    )


# ─── 生成阶段 ─────────────────────────────────────────────────────────────────

def _generate_from_approved_plan_stream(topic: str, color: str, plan: dict) -> Iterator[str]:
    yield _progress_event(
        "generating",
        "计划已确认，正在生成交互式教学页面...",
        65,
        degraded=True,
        plan=plan,
        subject=plan["subject"],
        core_concepts=plan["core_concepts"],
    )
    html_output, attempts, repaired, warnings, output_tokens_total = yield from _generate_interactive_html_with_repair_stream(topic, color, plan)
    metadata = GenerateAetherVizHtmlMetadata(
        topic=topic,
        attempts=attempts,
        repaired=repaired,
        source="llm_interactive_fallback",
        degraded=True,
        validation_warnings=warnings,
        render_mode=plan["render_stack"]["mode"],
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
            "html": html_output,
            "output_tokens_total": output_tokens_total,
            "metadata": metadata.model_dump(),
        },
    )


def _generate_interactive_html_with_repair_stream(
    topic: str,
    primary_color: str,
    plan: dict,
) -> Iterator[str]:
    """生成交互式 HTML 页面，并在首次校验失败时自动尝试一次修复。

    使用 PEP 380 `yield from` 委托：调用方通过 `result = yield from` 接收 return 值。
    返回值为五元组 (html_output, attempts, repaired, warnings, output_tokens_total)。
    """
    max_tokens = _resolve_max_tokens(plan)
    user_prompt = _build_fallback_prompt(topic, primary_color, plan)
    raw_html = yield from _stream_llm_output(
        user_prompt,
        system_prompt=FALLBACK_SYSTEM_PROMPT,
        max_tokens=max_tokens,
        temperature=0.2,
        stage="html_generating",
        message_prefix="正在生成互动页面代码",
        progress_start=66,
        progress_end=84,
    )
    logger.info(f"LLM AetherViz Fallback 原始响应 (max_tokens={max_tokens}, 长度 {len(raw_html)}):\n{raw_html}")
    output_tokens_total = _estimate_output_tokens(raw_html)

    attempts = 1
    repaired = False

    try:
        yield _progress_event(
            "html_parse",
            "正在整理模型输出，提取完整 HTML",
            86,
            phase="generate",
            output_tokens_total=output_tokens_total,
        )
        html_output = parse_interactive_html(raw_html)
        cleaned_html = sanitize_aetherviz_html(html_output)
        yield _progress_event(
            "html_validate",
            "正在校验页面结构、脚本安全和互动控件",
            90,
            phase="generate",
            output_tokens_total=output_tokens_total,
        )
        warnings = validate_aetherviz_html(
            cleaned_html,
            topic=topic,
            strict=False,
            render_stack=plan.get("render_stack"),
            main_renderer=plan.get("main_renderer"),
        )
        yield _progress_event(
            "html_validated",
            "页面校验完成，准备返回互动课件",
            98,
            phase="generate",
            output_tokens_total=output_tokens_total,
        )
        return cleaned_html, attempts, repaired, warnings, output_tokens_total
    except (AetherVizHtmlValidationError, AetherVizInteractiveHtmlError) as first_error:
        logger.warning(f"AetherViz Fallback LLM 首次生成校验失败，尝试 1 次自动修复。错误: {first_error}")
        attempts += 1
        repaired = True
        yield _progress_event(
            "html_repair",
            "页面结构需要修复，正在进行一次自动修复",
            92,
            phase="generate",
            output_tokens_total=output_tokens_total,
        )

        repair_prompt = _build_fallback_repair_prompt(raw_html, str(first_error), topic, plan)
        repaired_raw_html = yield from _stream_llm_output(
            repair_prompt,
            system_prompt=FALLBACK_REPAIR_SYSTEM_PROMPT,
            max_tokens=max_tokens,
            temperature=0.2,
            stage="html_repairing",
            message_prefix="正在修复互动页面代码",
            progress_start=92,
            progress_end=97,
        )
        logger.info(f"LLM AetherViz Fallback 修复响应 (max_tokens={max_tokens}, 长度 {len(repaired_raw_html)}):\n{repaired_raw_html}")
        output_tokens_total += _estimate_output_tokens(repaired_raw_html)

        yield _progress_event(
            "html_recheck",
            "正在复查修复后的页面",
            98,
            phase="generate",
            output_tokens_total=output_tokens_total,
        )
        html_output = parse_interactive_html(repaired_raw_html)
        cleaned_html = sanitize_aetherviz_html(html_output)
        warnings = validate_aetherviz_html(
            cleaned_html,
            topic=topic,
            strict=False,
            render_stack=plan.get("render_stack"),
            main_renderer=plan.get("main_renderer"),
        )
        return cleaned_html, attempts, repaired, warnings, output_tokens_total


# ─── 提示词构建 ───────────────────────────────────────────────────────────────

def _build_fallback_repair_prompt(raw_html: str, error: str, topic: str, plan: dict | None = None) -> str:
    render_requirements = ""
    target_objectives = ""
    target_variables = ""

    if plan:
        render_requirements = f"""
【确认计划中的渲染路由，不得改换】：
{json.dumps({
    "subject": plan.get("subject"),
    "experiment_type": plan.get("experiment_type"),
    "render_stack": plan.get("render_stack"),
    "main_renderer": plan.get("main_renderer"),
}, ensure_ascii=False, indent=2)}

修复时必须让最终 HTML 满足上述渲染路由：
- main_renderer=svg 时必须提供 SVG 主渲染面，不要默认引入或初始化 Three.js。
- main_renderer=three 时必须提供 Three.js 场景、相机、WebGLRenderer、OrbitControls、WebGL 兜底。
- main_renderer=canvas 时必须提供 Canvas/2D 上下文或 Three.js Points 主渲染面。
- 所有动态图层必须共用一个 requestAnimationFrame 主循环。
"""
        objectives_list = plan.get("learning_objectives", [])
        if objectives_list:
            target_objectives = "\n【必须包含的完整学习目标】：\n" + "\n".join(f"- {obj}" for obj in objectives_list)

        vars_list = plan.get("key_variables", [])
        if vars_list:
            slim_vars = [
                {
                    "name": v.get("name", ""),
                    "unit": v.get("unit", ""),
                    "default": v.get("default"),
                    "min": v.get("min"),
                    "max": v.get("max"),
                    "recommended": v.get("recommended"),
                    "classroom_tip": v.get("classroom_tip", ""),
                }
                for v in vars_list
            ]
            target_variables = "\n【必须包含且不可遗漏的控制变量】：\n" + json.dumps(slim_vars, ensure_ascii=False, indent=2)

    return f"""我们之前为教学主题《{topic}》生成的交互式 HTML 教学页面未通过校验。

【校验错误】：
{error}
{render_requirements}{target_objectives}{target_variables}

【待修复的原始 HTML 代码】：
{raw_html}

请分析上述校验错误，并在保留原页面所有核心交互逻辑、学习目标、KaTeX 公式和图形呈现的基础上，修复该错误，并直接输出修复后完整的 <!DOCTYPE html>...</html> 教学页面 HTML 代码。不要附加任何 Markdown 围栏或解释。
"""


def _build_fallback_prompt(topic: str, primary_color: str, plan: dict) -> str:
    """构建用于 LLM 生成交互式 HTML 的用户提示词。

    精简版：移除 performance_budget / self_check_items（已在系统提示词中覆盖），
    key_variables 只保留核心字段，降低 token 消耗，减少模型注意力分散。
    """
    objectives = "\n".join(f"- {obj}" for obj in plan.get("learning_objectives", []))
    concepts = "\n".join(f"- {c}" for c in plan.get("core_concepts", []))
    demo_flow = "\n".join(f"- {step}" for step in plan.get("teacher_demo_flow", []))
    # 只保留核心字段，去掉 meaning 等冗余字段
    key_vars_slim = [
        {
            "name": v.get("name", ""),
            "unit": v.get("unit", ""),
            "default": v.get("default"),
            "min": v.get("min"),
            "max": v.get("max"),
            "recommended": v.get("recommended"),
            "classroom_tip": v.get("classroom_tip", ""),
        }
        for v in plan.get("key_variables", [])
    ]
    variables = json.dumps(key_vars_slim, ensure_ascii=False, indent=2)
    render_stack = json.dumps(plan.get("render_stack", {}), ensure_ascii=False)
    int_type = plan.get("interaction_type", "general")
    int_hint = plan.get("interaction_hint", "")

    return f"""请为以下教学主题设计并编写一个完整且可以直接运行的交互式 HTML 教学页面。

教学主题：{topic}
主色调：{primary_color}
实验类型：{plan.get("experiment_type", "综合互动教学演示")}
渲染路由：{render_stack}
主渲染器：{plan.get("main_renderer", "svg")}
本课学习目标：
{objectives}
核心概念与公式：
{concepts}
教师 3 分钟演示流程：
{demo_flow}
重点变量：
{variables}

【交互模式规划】：
- 交互类型：{int_type}
- 交互实现构想：{int_hint}

【实现要求】：
1. 严格按照确认计划生成，不要改换主题或随意增加第 4 个重点变量。
2. 按渲染路由选择最小稳定技术栈；只有需要 3D/Hybrid 时才引入 Three.js。
3. 使用统一 state 对象和统一 Animation Runtime，不要多个独立 requestAnimationFrame。
4. 每个滑块显示单位、当前值、推荐值和课堂提示语。
5. HTML 必须以 <!DOCTYPE html> 开头，以 </html> 结束，不要带有 ```html 的代码围栏。
"""
