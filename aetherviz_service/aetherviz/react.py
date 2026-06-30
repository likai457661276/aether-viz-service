"""AetherViz SSE generator.

The endpoint now serves static matched HTML first and only falls back to a
single lightweight interactive HTML page generation when no knowledge point matches.
"""

import html
import json
import logging
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
    load_static_html_for_point,
    extract_color_from_topic,
)
from aetherviz_service.aetherviz.validator import (
    AetherVizHtmlValidationError,
    sanitize_aetherviz_html,
    validate_aetherviz_html,
)
from aetherviz_service.aetherviz.fallback_planner import (
    build_planning_prompt,
    parse_planning_result,
)
from aetherviz_service.llm_service import LLMServiceError, call_llm

logger = logging.getLogger(__name__)

FALLBACK_SYSTEM_PROMPT = """你是极其专业、充满创造力的互动教学可视化前端工程师。
你的任务是为指定的教学主题生成一个完整、精美、支持高度互动的自包含 HTML 页面。

【输出要求】：
1. 必须输出且仅输出一个完整的 <!DOCTYPE html> ... </html> 教学网页。
2. 严禁在输出中包裹任何 Markdown 标记（如 ```html 等）或解释说明文字，直接以 <!DOCTYPE html> 开头，以 </html> 结尾。
3. 所有的 CSS 样式、JavaScript 逻辑必须写在 <style> 和 <script> 标签内，实现完全的自包含。

【设计与视觉规范（极重要）】：
- 页面背景：使用深色调高级背景（如 `#0F172A` 或更深颜色），配合清晰易读的前景色（如文字用 `#F8FAFC`, `#CBD5E1`）。
- 整体配色：以指定的主色调（primary_color）作为强调色和按钮、链接、高亮元素的视觉焦点。
- 自适应双栏布局：整体页面高度必须为自然的流式自适应（使用 min-height: 100vh，禁止对 html, body 或最外层容器使用 overflow: hidden 锁定高度或限制 height: 100vh，以便页面能够顺畅滚动并根据内容自适应撑开高度，完美适配 iframe 或不同屏幕）。左侧建议固定为 280px-320px 的“信息与学习区”，展示清晰的网页标题、本课“学习目标”和“核心概念”；右侧为“互动教学与图形区域”。为了防止交互图形、主要面板或 Canvas 动画区域在自适应高度页面下因 100% 相对高度而坍塌为 0，必须显式为右侧动画/绘图核心区域、面板或图形容器设置固定像素高度（如 height: 500px，或使用优雅的高宽比 aspect-ratio 等），确保交互卡片、图形和公式区域不仅有充足的显示空间，更能安全自然地撑开页面。
- 响应式设计：在移动端或小屏下，双栏应自动堆叠为单栏。
- 极致视觉与细节：使用圆角、毛玻璃模糊效果、微光渐变边框或 subtle animations 呈现现代 premium 的交互面板。

【几何图形与图表绘制美学规范（极重要）】：
当你的教学主题需要绘制坐标系、函数曲线、几何图形、电路图或物理向量时，必须遵守以下工业级图表美学规范：
1. 线条粗细分级与极致精致度：
   - ❌ 绝对禁止使用任何超过 4px 粗度的呆板粗线和粗钝色块！
   - ✅ 背景辅助网格线（Grid）：只允许使用精细的 1px 半透明虚线（如 stroke-dasharray="3,3"，使用透明度 0.15 左右的白色或淡灰色 `#334155`）。
   - ✅ 坐标轴（Axes）：使用坚实精细的 1.5px 或 2px 实线（如 `#475569` 或淡蓝灰 `#64748B`）。
   - ✅ 核心几何线、函数数据曲线：使用 3px 粗细的强调色线（主色调），并为其加轻微的 drop-shadow 发光滤镜或微弱渐变，呈现科技发光的高级 premium 质感。
2. 坐标点与标注文字比例：
   - 数据点/交点：使用精美的双圈小圆点（例如半径 5px 的实体点，外圈套一层 stroke-width="2" 且透明度 0.4 的同色光晕圈），半径绝对不能超过 6px！
   - 坐标轴标注与刻度文字（Labels）：字号限制在 12px-14px 之间，使用优雅的斜体字或 KaTeX 排版，颜色使用淡雅的中性色（如 `#94A3B8`），保持绝对的数学严谨度与整洁度。


【交互与功能规范（极重要）】：
- 必须包含一个清晰的“控制/交互面板”，里面提供适合本主题的交互控件（如 range 滑块、点击按钮、Tab 选择卡、选项卡等），以实现丰富而自然的参数调整。
- 所有可交互元素都必须在发生拖拽或点击时，实时有视觉反馈（如改变数值、重绘图表、变换 SVG 图形位置、切换步骤内容或显示答案反馈）。
- 绝对禁止使用 `alert` 或 `confirm` 等阻塞式交互，所有反馈应呈现在页面容器内。
- 允许且建议在 `<script>` 内使用标准的 Web APIs（如 Canvas 绘图、内联 SVG 动画、DOM 操作、数值计算等）来制作美观 of 交互过程。
- 如果引入了外部 CDN 资源，仅允许使用 KaTeX 渲染数学公式（https://cdn.staticfile.net/KaTeX/0.16.9/katex.min.js 和 css），其他全部 JS 和库文件必须内联，不依赖任何第三方 CDN 库（如 d3, three 等），保持全包容性。

【自检与稳定性要求】：
- 不得出现占位符（如 "TODO", "这里补充..."），所有文本、公式、交互必须是完整、高质量、可实际工作的真实内容。
- JavaScript 逻辑代码应该健壮，页面加载时能立刻初始化完成，无任何控制台报错。
- ⚠️【JS 中文编码约束】：JavaScript 代码块（`<script>` 标签）内部的所有注释和字符串字面量，必须使用英文，禁止嵌入中文字符。任何中文文本只允许出现在 HTML 元素的 `textContent`、`innerHTML` 中作为 HTML 内容呈现，以防中文字符被大模型 Token 截断时破坏 UTF-8 编码导致 JavaScript 语法错误。
- ⚠️【KaTeX 异步加载时机】：所有调用 `renderMathInElement` 或 KaTeX 渲染的代码必须放在 `document.addEventListener('DOMContentLoaded', ...)` 回调函数内，并在其后通过 `setTimeout(..., 200)` 进行一次兜底重复调用，确保 KaTeX CDN 脚本及样式完全加载并就绪后再渲染公式，避免因加载时差引发控制台报错。
- ⚠️【篇幅与精简优化】：大模型单次输出有硬性 Token 限制。请务必保持 CSS 和 JS 代码高度精简，杜绝任何无意义的冗长注释，精简重复 HTML 结构，将全局代码字数控制在 2500 tokens 以内，确保以 </html> 标签完整闭合吐出。
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


def react_generate_stream(topic: str) -> Iterator[str]:
    """生成 AetherViz HTML 的 SSE 流式响应。
    
    这是 AetherViz 生成的主入口函数，采用"静态优先 + 动态兜底"的策略：
    
    1. 首先尝试静态匹配：通过关键词匹配预注册的知识点，如果命中则返回预置的静态 HTML
    2. 如果未命中，进入动态兜底流程：
       a. 规划阶段：调用 LLM 分析主题，生成学习目标、核心概念、交互类型等规划
       b. 生成阶段：根据规划调用 LLM 生成完整的交互式 HTML 页面
       c. 校验与修复：验证生成的 HTML，如果校验失败则尝试一次自动修复
    
    整个流程通过 SSE (Server-Sent Events) 流式返回进度和结果。
    
    参数:
        topic: 教学主题，如 "牛顿第二定律"
        
    产出:
        SSE 格式的字符串序列，包含以下事件类型：
        - start: 开始事件
        - progress: 进度更新事件（planning、generating 等阶段）
        - static_match: 静态知识点命中事件
        - done: 完成事件，包含生成的 HTML
        - error: 错误事件
    """
    color = extract_color_from_topic(topic)
    yield _sse_event(
        "start",
        {
            "success": True,
            "stage": "start",
            "message": f"开始生成《{topic}》的互动可视化页面",
            "progress": 3,
        },
    )

    try:
        match = match_topic_to_knowledge_point(topic)
        if match is not None:
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
            return

        # 阶段 1：规划
        yield _progress_event(
            "planning",
            "正在分析知识点，制定可视化规划...",
            35,
            degraded=True,
        )
        try:
            planning_sys, planning_user = build_planning_prompt(topic, color)
            raw_plan = call_llm(
                planning_user,
                system_prompt=planning_sys,
                max_tokens=600,
                temperature=0.4
            )
            plan = parse_planning_result(raw_plan, topic)
        except Exception as exc:
            logger.warning(f"AetherViz fallback planning 失败，使用兜底规划: {exc}")
            plan = parse_planning_result("", topic)

        # 阶段 2：交互页面生成
        yield _progress_event(
            "generating",
            "正在生成交互式教学页面...",
            65,
            degraded=True,
        )
        html_output, attempts, repaired, warnings = _generate_interactive_html_with_repair(topic, color, plan)
        metadata = GenerateAetherVizHtmlMetadata(
            topic=topic,
            attempts=attempts,
            repaired=repaired,
            source="llm_interactive_fallback",
            degraded=True,
            validation_warnings=warnings,
            render_mode="interactive-html",
        )
        yield _sse_event(
            "done",
            {
                "success": True,
                "stage": "done",
                "message": "已返回自包含互动教学页面",
                "progress": 100,
                "html": html_output,
                "metadata": metadata.model_dump(),
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


FALLBACK_REPAIR_SYSTEM_PROMPT = """你是极其专业、充满创造力的互动教学可视化前端工程师。
你的任务是修复一个在之前生成中未通过安全、结构或依赖规则校验的自包含 HTML 教学页面。

【修复原则】：
1. 必须完全保留原页面的教学主题、所有的核心概念、学习目标和已实现的交互图形/JS 逻辑（不要擅自删除它们）。
2. 只针对提供的【校验错误】进行精准修复。
3. 必须输出且仅输出一个完整的，修复后的 <!DOCTYPE html> ... </html> 教学网页。
4. 严禁在输出中包裹任何 Markdown 标记（如 ```html 等）或任何解释说明文字，直接以 <!DOCTYPE html> 开头，以 </html> 结尾。
5. 所有的 CSS 样式、JavaScript 逻辑必须写 in <style> 和 <script> 标签内，实现完全的自包含。

【设计与自愈闭合规范】：
- 确保页面背景使用深色调高级背景（如 `#0F172A` 或更深颜色）。
- 确保所有的 `<script>` 标签和自定义交互函数 `window.updateVisualization = function(progress, state) { ... }` 能够无错运行。
- 大模型输出可能因 Token 限制被截断，请尽量精简非核心样式，确保以 </html> 完整闭合。
"""


def _build_fallback_repair_prompt(raw_html: str, error: str, topic: str) -> str:
    return f"""我们之前为教学主题《{topic}》生成的交互式 HTML 教学页面未通过校验。

【校验错误】：
{error}

【待修复的原始 HTML 代码】：
{raw_html}

请分析上述校验错误，并在保留原页面所有核心交互逻辑、学习目标、KaTeX 公式和图形呈现的基础上，修复该错误，并直接输出修复后完整的 <!DOCTYPE html>...</html> 教学页面 HTML 代码。不要附加任何 Markdown 围栏或解释。
"""


def _generate_interactive_html_with_repair(
    topic: str,
    primary_color: str,
    plan: dict,
) -> tuple[str, int, bool, list[str]]:
    """生成交互式 HTML 页面，并在首次校验失败时自动尝试一次修复。
    
    该函数实现了核心的"生成-校验-修复"循环：
    1. 根据主题、主题色和规划生成 LLM 提示词
    2. 调用 LLM 生成原始 HTML
    3. 解析 HTML（处理代码围栏、截断等问题）
    4. 清理 HTML（边界清理）
    5. 校验 HTML（结构、安全、依赖、内容等）
    6. 如果校验失败，构建修复提示词，调用 LLM 重新生成
    7. 修复后再次校验，返回最终结果
    
    参数:
        topic: 教学主题
        primary_color: 主题色
        plan: 规划字典，包含 learning_objectives、core_concepts、
              interaction_type、interaction_hint
        
    返回:
        (html_output, attempts, repaired, warnings) 四元组：
        - html_output: 最终生成的 HTML 字符串
        - attempts: 尝试次数（1 或 2）
        - repaired: 是否经过修复
        - warnings: 校验警告列表
    """
    user_prompt = _build_fallback_prompt(topic, primary_color, plan)
    raw_html = call_llm(
        user_prompt,
        system_prompt=FALLBACK_SYSTEM_PROMPT,
        max_tokens=6000,
        temperature=0.6,
    )
    logger.info(f"LLM AetherViz Fallback 原始响应 (长度 {len(raw_html)}):\n{raw_html}")

    attempts = 1
    repaired = False

    try:
        html_output = parse_interactive_html(raw_html)
        cleaned_html = sanitize_aetherviz_html(html_output)
        warnings = validate_aetherviz_html(cleaned_html, topic=topic, strict=False)
        return cleaned_html, attempts, repaired, warnings
    except (AetherVizHtmlValidationError, AetherVizInteractiveHtmlError) as first_error:
        logger.warning(f"AetherViz Fallback LLM 首次生成校验失败，尝试 1 次自动修复。错误: {first_error}")
        attempts += 1
        repaired = True

        repair_prompt = _build_fallback_repair_prompt(raw_html, str(first_error), topic)
        repaired_raw_html = call_llm(
            repair_prompt,
            system_prompt=FALLBACK_REPAIR_SYSTEM_PROMPT,
            max_tokens=6000,
            temperature=0.5,
        )
        logger.info(f"LLM AetherViz Fallback 修复响应 (长度 {len(repaired_raw_html)}):\n{repaired_raw_html}")

        html_output = parse_interactive_html(repaired_raw_html)
        cleaned_html = sanitize_aetherviz_html(html_output)
        warnings = validate_aetherviz_html(cleaned_html, topic=topic, strict=False)
        return cleaned_html, attempts, repaired, warnings


def _build_fallback_prompt(topic: str, primary_color: str, plan: dict) -> str:
    """构建用于 LLM 生成交互式 HTML 的用户提示词。
    
    该函数将主题、主题色和规划信息组装成完整的提示词，
    指导 LLM 生成包含以下内容的教学页面：
    - 左侧栏：课程标题、学习目标、核心概念
    - 右侧主区域：交互图形和控制区
    - 具体的交互控件（按钮、滑块、选项卡等）
    
    参数:
        topic: 教学主题
        primary_color: 主题色
        plan: 规划字典
        
    返回:
        格式化后的用户提示词字符串
    """
    objectives = "\n".join(f"- {obj}" for obj in plan.get("learning_objectives", []))
    concepts = "\n".join(f"- {c}" for c in plan.get("core_concepts", []))
    int_type = plan.get("interaction_type", "general")
    int_hint = plan.get("interaction_hint", "")

    return f"""请为以下教学主题设计并编写一个完整且可以直接运行的交互式 HTML 教学页面。

教学主题：{topic}
主色调：{primary_color}
本课学习目标：
{objectives}
核心概念与公式：
{concepts}

【交互模式规划】：
- 交互类型：{int_type}
- 交互实现构想：{int_hint}

【实现要求】：
1. 页面左侧栏展示课程名《{topic}》、学习目标和核心概念（推荐使用 KaTeX 来排版公式）。
2. 页面右侧主区域为交互图形及控制区。
3. 提供具体的控制组件（如按钮、拖动滑块、卡片点击、选项问答等），并在拖拽或操作时，使用 Vanilla JS 通过获取 DOM 元素实时修改样式或属性，呈现即时的动态更新。
4. HTML 必须以 <!DOCTYPE html> 开头，以 </html> 结束，不要带有 ```html 的代码围栏。
"""
