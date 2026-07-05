"""Prompt templates and prompt builders for AetherViz dynamic HTML."""

from __future__ import annotations

import json

from aetherviz_service.aetherviz.streaming import compact_html_for_revision

CDN_GSAP = "https://cdn.jsdelivr.net/npm/gsap@3.15.0/dist/gsap.min.js"

BASE_HTML_SYSTEM_PROMPT = """你是资深互动教学 HTML 工程师。
只输出一个完整可运行 HTML 文件，从 <!DOCTYPE html> 开始，到 </html> 结束。
如果模型输出 reasoning_content，必须使用简体中文，且只写面向用户的简短设计摘要。

硬性要求：
- 页面面向 12~18 岁学生，必须默认自动播放，不需要点击才开始。
- 主视觉清晰、元素少而准；不要用大量装饰、虚构数据或无关图形填充画面。
- 至少呈现 3 个可观察状态变化：对象移动/变形、颜色或高亮变化、数值/公式/caption 同步变化。
- 每一幕使用 class="animation-caption" 或 id="animation-caption" 的中文旁白说明当前发生了什么、为什么重要、学生该观察什么；caption 必须随动画状态更新。
- 页面必须可见展示完整分镜/动画实现说明列表（例如第1幕到第4幕），不能只显示当前幕；当前播放到哪一幕必须用 class="active"、aria-current="step" 或 data-current="true" 同步标注。
- 主可视化区使用 id="aetherviz-stage"，主 SVG/Canvas 居中，主元素有稳定 id/class 或 data-role，便于修订和校验。
- 学习目标区 class="learning-objectives" 且 data-region="learning-goal" 至少 3 条；控制区 class="control-panel" 且 data-region="controls" 至少包含播放、暂停、重置和一个真实参数或速度控件。
- 公式或结论区使用 data-region="formula"；步骤说明使用 data-region="caption"；页面主布局容器优先使用 data-region="app-shell"。
- 控件、caption、公式/概念区不能遮挡主图；长文本放独立说明区或自动换行。
- 单屏适配 960x540、常见桌面宽度和移动端；html/body 高度 100%，禁止页面级滚动条。
- 所有事件用 addEventListener 绑定，禁止内联 onXxx。
- 声明 window.AetherVizRuntime = { play, pause, reset, setSpeed, update, getState }。
- 初始化成功设置 window.__AETHERVIZ_RUNTIME_READY__ = true；异常设置 window.__AETHERVIZ_RUNTIME_ERROR__ 并在页面显示错误提示。
- CSS 和业务 JS 内联；不引入 Three.js、D3、图片生成或外部业务接口。
- 仅当计划 animation_runtime=gsap_timeline 时允许引入固定 GSAP CDN，并只用 GSAP 管理时间线。
"""

GENERIC_SVG_SYSTEM_PROMPT = BASE_HTML_SYSTEM_PROMPT
MATH_SYSTEM_PROMPT = BASE_HTML_SYSTEM_PROMPT + """
数学主题补充：
- 优先用 SVG 表达几何、坐标、函数或代数关系。
- 公式必须服务于图形变化，参数、图中标注和公式数值要同步更新。
- 不要只画静态公式或孤立色块；必须让学生看到关系如何随状态变化。
"""

REVISE_SYSTEM_PROMPT = """你是资深 HTML 局部修订工程师。
根据用户修改意见和结构化索引上下文，输出局部补丁 JSON，不输出完整 HTML。
如果模型输出 reasoning_content，必须使用简体中文，并以面向用户的简短思考摘要描述正在做的设计取舍；不要使用英文。

修订原则：
- 修订后的页面动画必须能完整播放并清晰演示教学目标，这是首要判断标准。
- 只修改与用户意见直接相关的 DOM、CSS 或 JS 片段。
- 优先保持原有结构、事件绑定、运行时 API 和白名单资源。
- 对文案修改，优先 replace_region 或替换相关 caption 函数/文案对象。
- 对布局/颜色修改，优先 upsert_css_rule。
- 对动画节奏/交互修改，优先 replace_js_function；函数边界不明确时才 replace_script_block。
- 保留 window.AetherVizRuntime 的 play、pause、reset、setSpeed、update、getState。
- 不引入 Three.js 或外部业务接口；若当前 HTML 已使用 GSAP Timeline，可保留固定版本 GSAP CDN 并修复其播放控制，不要退回静态页面。
- 输出必须是严格 JSON：{"patch_plan":"...","patches":[...]}。
"""

REPAIR_SYSTEM_PROMPT = """你是资深 HTML 自动修复工程师。
你会收到一次失败的 HTML 输出、服务端校验错误和原始生成上下文。
如果模型输出 reasoning_content，必须使用简体中文，并以面向用户的简短思考摘要描述正在做的设计取舍；不要使用英文。

修复的第一优先级：动画能完整播放并清晰演示教学目标。
在保证动画质量的前提下，再修复具体的结构问题。

具体修复要求：
- 只输出修复后的完整 <!DOCTYPE html>...</html>，不输出 Markdown 或解释。
- 保持独立 HTML，CSS 与业务 JavaScript 内联。
- 确保学习目标（class="learning-objectives"，至少 3 条）、主可视化区（id="aetherviz-stage"）、控制面板（class="control-panel"）存在。
- 确保 #aetherviz-stage 内主 SVG/Canvas 在舞台水平和垂直居中；SVG 需要用居中的 viewBox 或 main-visual-group，Canvas 需要基于 width/height 的中心点绘制。
- 确保页面保留中文旁白式 caption，并像完整教学动画一样默认自动播放。
- 确保页面可见展示完整分镜/动画实现说明列表（例如第1幕到第4幕），并随动画进度同步标注当前幕，不能只保留当前幕 caption。
- 确保舞台使用适合 iframe 预览的响应式布局，适配 960×540、常见桌面宽度和移动端。
- 确保页面使用单屏无滚动布局，html/body 与页面根容器压缩在 iframe 首屏内，禁止页面级滚动条。
- 确保标签、公式、步骤说明和控件避让主图，长文本进入说明区或自动换行。
- 在保证动画可播放优先的前提下，优先使用独立布局区域承载控制面板、caption、公式结论区，并给主舞台预留底部安全间距，避免悬浮遮挡。
- 移除页脚署名、品牌署名和生成来源文字。
- 默认移除全局进度条/进度滑块；除非原始主题明确要求，否则不要恢复进度条。
- 确保播放/暂停/重置按钮（id="play-animation"、id="pause-animation"、id="reset-animation"）存在并绑定真实事件。
- 确保 window.AetherVizRuntime = { play, pause, reset, setSpeed, update, getState } 声明完整。
- 确保 window.__AETHERVIZ_RUNTIME_READY__ = true 在初始化成功时设置。
- 不引入 Three.js 或外部业务接口。若原计划 animation_runtime=gsap_timeline，应保留固定 GSAP CDN、补齐 timeline label 和控制绑定，不要退回静态 SVG。
"""


def is_math_mode(mode: str | None) -> bool:
    return mode == "math_interactive"


def is_gsap_timeline_plan(plan: dict | None) -> bool:
    return bool(plan and plan.get("animation_runtime") == "gsap_timeline")


def system_prompt_for_plan(base_prompt: str, plan: dict) -> str:
    if not is_gsap_timeline_plan(plan):
        return base_prompt
    return f"""{base_prompt}

GSAP Timeline 计划要求：
- 本计划 animation_runtime=gsap_timeline，必须引入且只能引入固定 CDN：{CDN_GSAP}
- 使用 const tl = gsap.timeline({{ paused: true, defaults: {{ ease: "power2.inOut" }}, onUpdate: syncRuntimeState }});
- 使用 addLabel() 为每个 timeline_scenes scene 建立可读 label，至少 3 个 label，label 名称应与 scene id 对应。
- timeline 内至少包含 3 个真实 tween/set 调用，用于元素进出场、步骤高亮、公式同步或 caption 更新。
- 播放按钮调用 tl.play() 或 tl.restart()；暂停按钮调用 tl.pause()；重置按钮调用 tl.pause(0) 或 tl.progress(0)。
- 速度控制调用 tl.timeScale(value)；不要生成可见全局进度条，window.AetherVizRuntime.update(value) 可在内部调用 tl.progress(value) 供宿主程序跳转状态。
- window.AetherVizRuntime 统一代理 timeline：play、pause、reset、setSpeed、update、getState 都要真实读写 tl。
- Canvas 高频运动仍用 requestAnimationFrame 绘制；如果页面使用 Canvas，GSAP 只驱动 state.progress 或阶段值，再调用 renderCanvas。
"""


def build_repair_prompt(
    *,
    topic: str,
    plan: dict,
    original_prompt: str,
    raw_html: str,
    error_detail: str,
    source_label: str,
) -> str:
    return f"""请修复一次失败的{source_label} HTML 输出。

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
{compact_html_for_revision(raw_html)}

请直接输出修复后的完整 HTML，不要输出任何解释。"""


def build_generation_prompt(topic: str, plan: dict) -> str:
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
        f"分镜时间线（每一幕都要能在页面里播放、暂停、重置，并能通过按钮或参数控件回看关键状态）:\n{json.dumps(timeline_scenes, ensure_ascii=False, indent=2)}\n"
        if timeline_scenes
        else ""
    )
    if animation_runtime == "gsap_timeline":
        runtime_section = f"""动画运行时（必须落实）：
- 使用 GSAP Timeline 编排动画，不要只引用库。
- 引入且只能引入固定 CDN：{CDN_GSAP}
- 声明 const tl = gsap.timeline({{ paused: true, defaults: {{ ease: "power2.inOut" }}, onUpdate: syncRuntimeState }});
- timeline_scenes 每个 scene 都要有 tl.addLabel(scene.id, ...)，至少 3 个 label。
- 每个 scene 至少对应一个 .to() / .from() / .fromTo() / .set()，用来驱动画面、caption、公式或高亮。
- id="play-animation" 绑定 tl.play() 或 tl.restart()；id="pause-animation" 绑定 tl.pause()；id="reset-animation" 绑定 tl.pause(0) 或 tl.progress(0)。
- 速度控件绑定 tl.timeScale(value)；默认不要生成可见全局进度条或进度滑块。
- animation-caption 或 step-caption 必须随 tl 的当前 scene 同步更新。
- 页面中的完整分镜列表必须随 tl 的当前 scene 同步更新 active/current 标记，当前幕可高亮，但其他幕说明仍保持可见。
- window.AetherVizRuntime 必须代理 timeline 的 play、pause、reset、setSpeed、update、getState，其中 update(value) 可内部调用 tl.progress(value) 以支持宿主程序跳转，但不要因此渲染进度条。
- Canvas 高频运动仍用 requestAnimationFrame 绘制；若使用 Canvas，GSAP 只驱动 progress/state，再调用 renderCanvas。
"""
    else:
        runtime_section = """动画运行时（必须落实）：
- 使用 native 运行时：requestAnimationFrame、CSS transition、classList 或原生 DOM/SVG/Canvas 更新。
- 不要引入 GSAP；播放、暂停、重置、速度和主题参数控件仍必须真实驱动画面。
- 运行时更新当前步骤时，必须同步更新完整分镜列表的 active/current 标记，其他幕说明仍保持可见。
- 默认不要生成可见全局进度条或进度滑块；window.AetherVizRuntime.update(value) 可内部跳转当前步骤或动画状态。
"""

    storyboard_text = "\n".join(f"  第{i+1}幕：{s}" for i, s in enumerate(plan.get("storyboard", [])))
    visual_steps_text = "\n".join(f"  {s}" for s in plan.get("visual_steps", []))

    return f"""任务：根据确认后的方案生成一个独立互动教学 HTML。

主题：{topic}
标题：{plan["title"]}
目标：{plan["goal"]}
主色：{plan.get("primary_color", "#22D3EE")}

1. 渲染栈
{render_stack_hint}

2. 运行时
{runtime_section}

3. 舞台布局
{plan.get("stage_layout", "顶部学习目标，中间大舞台，底部 caption、控制条和公式/结论区。")}

4. 动画验收
- 默认自动播放，至少 3 个可观察状态变化，不能只是静态图形加文字。
- #aetherviz-stage 内主 SVG/Canvas 居中；SVG 使用 preserveAspectRatio="xMidYMid meet" 和稳定主视觉 id/class/data-role。
- 主舞台使用 id="aetherviz-stage" 和 data-region="stage"；控制区、公式区、caption 区使用稳定 data-region，关键教学元素使用 data-role。
- animation-caption 或 step-caption 必须随动画状态更新。
- 必须在页面中显示完整分镜/动画实现说明列表，覆盖所有 timeline_scenes 或 storyboard 条目；当前幕用 active/current 状态同步标注，不能只显示当前幕。
- 控件必须绑定真实功能；不要生成可见全局进度条或进度滑块。
- 不输出页脚署名、品牌署名或生成来源文案。

5. 教学分镜
{storyboard_text}

{timeline_section}
{number_design_section}
6. 动画策略
{strategy_hint}

7. 视觉步骤
{visual_steps_text}

8. 控件
{json.dumps(plan.get("controls", []), ensure_ascii=False, indent=2)}

{formula_section}输出格式：只输出完整 HTML，不要输出 Markdown、解释或页面署名。
"""
