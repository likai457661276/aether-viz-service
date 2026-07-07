"""Prompt templates and prompt builders for AetherViz dynamic HTML."""

from __future__ import annotations

import json

from aetherviz_service.aetherviz.constants import HTML_OUTPUT_HARD_LIMIT_CHARS, HTML_OUTPUT_TARGET_CHARS

GSAP_CORE_CDN = "https://cdn.jsdelivr.net/npm/gsap@3/dist/gsap.min.js"

OPENMAIC_WIDGET_CORE_PROMPT = """OpenMAIC interactive widget 核心契约：
- 生成物必须是一个自包含 interactive widget，不是 PPT 截图、静态海报或普通选择题页面。
- 生成逻辑必须以 scene_outline、widget_outline、interactive_spec 和 design_brief 为唯一蓝图；不得退化成通用模板动画。
- 必须嵌入 `<script type="application/json" id="widget-config">...</script>`；JSON.type 必须等于 simulation、diagram 或 game，并与 plan.interactive_type 一致。widget-config 内容必须是严格的纯 JSON 格式，禁止包含任何 JS 注释（如 // 或 /* */）和尾随逗号。
- widget-config 必须承载本页核心互动配置：simulation 写 concept/description/variables/presets；diagram 写 nodes/edges/revealOrder；game 写 gameType/description/gameConfig/successCondition/feedbackRules。
- 必须实现 `window.addEventListener("message", ...)`，至少处理 SET_WIDGET_STATE、HIGHLIGHT_ELEMENT、ANNOTATE_ELEMENT、REVEAL_ELEMENT 四类 iframe-local widget action。
- 变量控件 ID 使用 `{variable_name}-slider` 或 `data-var="{variable_name}"`；按钮 ID 使用 `{action}-btn` 或计划中的稳定 id；可被高亮/标注的元素必须有 id 或 data-role。
- 主舞台、控制面板、说明、公式和 HUD 必须是分区布局；控制面板不能覆盖 Canvas/SVG，移动端使用堆叠、抽屉或可折叠布局。
- 计算对象位置时必须预留 TOP_MARGIN/BOTTOM_MARGIN 或等价安全区，不能把对象画到控制区、HUD、caption、公式区下面。
- 舞台内只放短标签和图形标注；公式、读数、caption、推导步骤放独立面板。禁止把公式/读数渲染成主舞台超大文本；SVG text 建议 10~18px，超过 28px 必须有明确局部标签理由。
- 使用清晰状态机：running、paused、ended 或等价状态；reset 必须重置所有位置、速度、分数、步骤、按钮文本和参数到初始状态。
- 所有触摸目标至少 44px；slider thumb 至少 24px；Canvas 自定义手势使用 touch-action: none。
- 输出必须只有一个 HTML 文档，只能有一个 <!DOCTYPE html> 和一个 </html>。
"""

INTERACTIVE_HTML_SYSTEM_PROMPT = f"""你是资深 OpenMAIC 单页互动 widget 工程师。
只输出一个完整可运行 HTML 文件，从 <!DOCTYPE html> 开始，到 </html> 结束。
如果模型输出 reasoning_content，必须使用简体中文，且只写面向用户的简短设计摘要。

{OPENMAIC_WIDGET_CORE_PROMPT}

硬性要求：
- 页面面向 12~18 岁学生，默认必须呈现可理解的首屏状态；simulation/diagram 可以自动演示首段，game 必须公平开始且不能自动失败。
- 主视觉清晰、元素少而准；不要用大量装饰、虚构数据或无关图形填充画面。
- 页面类型固定为 single-page interactive，必须按 plan.interactive_type 生成 simulation、diagram 或 game。
- 至少呈现 3 个可观察状态变化：对象移动/变形、颜色或高亮变化、数值/公式/caption 同步变化。
- 每一幕使用 class="animation-caption" 或 id="animation-caption" 的中文旁白说明当前发生了什么、为什么重要、学生该观察什么；caption 必须随动画状态更新。
- 页面必须可见展示完整分镜/动画实现说明列表（例如第1幕到第4幕），不能只显示当前幕；当前播放到哪一幕必须用 class="active"、aria-current="step" 或 data-current="true" 同步标注。
- 主可视化区使用 id="aetherviz-stage"，主 SVG/Canvas 居中，主元素有稳定 id/class 或 data-role，便于修订和校验。
- 学习目标区 class="learning-objectives" 且 data-region="learning-goal" 至少 3 条；控制区 class="control-panel" 且 data-region="controls" 至少包含播放(id="play-animation")、暂停(id="pause-animation")、重置(id="reset-animation")和一个真实参数或速度控件。
- 公式或结论区使用 data-region="formula"；步骤说明使用 data-region="caption"；页面主布局容器优先使用 data-region="app-shell"。
- 控件、caption、公式/概念区不能遮挡主图；长文本放独立说明区或自动换行；主舞台内禁止出现巨型公式、巨型读数或覆盖图形的大段文字。
- 单屏适配 960x540、常见桌面宽度和移动端；html/body 高度 100%，禁止页面级滚动条。
- 所有事件用 addEventListener 绑定，禁止内联 onXxx。
- 声明 window.AetherVizRuntime = {{ play, pause, reset, setSpeed, update, getState }}。
- 初始化成功设置 window.__AETHERVIZ_RUNTIME_READY__ = true；异常设置 window.__AETHERVIZ_RUNTIME_ERROR__ 并在页面显示错误提示。
- CSS 和业务 JS 内联；除 GSAP core UMD CDN 外，不引入 Three.js、D3、图片生成、外部时间线库插件或外部业务接口。
- 必须加载 `<script src="https://cdn.jsdelivr.net/npm/gsap@3/dist/gsap.min.js"></script>`，并优先用 `gsap.timeline({{ paused: true, defaults: {{ duration, ease }} }})` 组织分镜动画。
- 播放、暂停、重置、速度和主题参数控件必须控制 GSAP timeline：play/pause/restart/timeScale/progress 或重建 timeline；caption、步骤 active/current 标记和读数必须在 timeline onUpdate 或状态更新函数中同步。
- Canvas 高频粒子、轨迹或物理循环可用 requestAnimationFrame 补充，但 DOM/SVG 入场、强调、变形、步骤切换和教学节奏必须使用 GSAP tween/timeline。
- 如果 `window.gsap` 不可用，必须保留可运行的 native fallback，确保主视觉、caption 和控件仍能响应。
- 输出 HTML 必须控制在 {HTML_OUTPUT_TARGET_CHARS} 字符以内，绝对不要超过 {HTML_OUTPUT_HARD_LIMIT_CHARS} 字符；避免冗长注释、重复 CSS、内联大数据、base64、超长文案和重复 DOM，确保后续 HTML 修改阶段不会因上下文上限截断尾部脚本。
"""

SIMULATION_SYSTEM_PROMPT = INTERACTIVE_HTML_SYSTEM_PROMPT + """
simulation 补充要求：
- 必须把 interactive_spec.variables 落成真实滑块、按钮或预设控件。
- 参数变化要实时驱动画面、数值读数、caption 和结论，不允许只改文字。
- 默认状态能直接理解，至少提供一个可比较的参数变化结果。
- 启动/播放后必须有明显运动、旋转、变形或轨迹变化，不能只有数字变化。
- resetSimulation 或等价函数必须把所有变量、动画时间、图形位置、按钮状态和提示恢复初始值。
"""

DIAGRAM_SYSTEM_PROMPT = INTERACTIVE_HTML_SYSTEM_PROMPT + """
diagram 补充要求：
- 必须把 interactive_spec.nodes、edges、reveal_order 落成节点、连线和逐步揭示。
- 节点和边不能重叠；点击或步骤按钮能高亮当前节点并显示说明。
- 移动端仍应可读，交互不能依赖复杂拖拽。
"""

GAME_SYSTEM_PROMPT = INTERACTIVE_HTML_SYSTEM_PROMPT + """
game 补充要求：
- 必须把 interactive_spec.challenge、success_condition、feedback_rules 落成可玩的课堂挑战。
- 不能退化为普通选择题堆叠；需要有操作对象、排序、匹配、调参或策略选择。
- 默认公平开始，提供即时反馈和解释。
- 如果包含实时游戏循环，必须有 3~5 秒安全期或等价安全初始状态，玩家不能一开始就失败。
- 学习必须通过操作发生，题目问答只能作为辅助手段，不能成为唯一玩法。
"""

REPAIR_SYSTEM_PROMPT = f"""你是资深 HTML 自动修复工程师。
你会收到一次失败的 HTML 输出、服务端校验错误和原始生成上下文。
如果模型输出 reasoning_content，必须使用简体中文，并以面向用户的简短思考摘要描述正在做的设计取舍；不要使用英文。

修复的第一优先级：动画能完整播放并清晰演示教学目标。
在保证动画质量的前提下，再修复具体的结构问题。
禁止用通用 HTML 替换原页面；必须在原始设计意图和已确认计划范围内修复。

具体修复要求：
- 只输出修复后的完整 <!DOCTYPE html>...</html>，不输出 Markdown 或解释。
- 保持独立 HTML，CSS 与业务 JavaScript 内联。
- 补齐 OpenMAIC widget 契约：`script#widget-config[type="application/json"]`、message action listener、稳定元素 id/data-role。
- 确保学习目标（class="learning-objectives"，至少 3 条）、主可视化区（id="aetherviz-stage"）、控制面板（class="control-panel"）存在。
- 确保 #aetherviz-stage 内主 SVG/Canvas 在舞台水平和垂直居中；SVG 需要用居中的 viewBox 或 main-visual-group，Canvas 需要基于 width/height 的中心点绘制。
- 确保页面保留中文旁白式 caption，并像完整互动课件一样默认进入可观察状态。
- 确保页面可见展示完整教学流程列表，并随互动进度同步标注当前步骤，不能只保留当前 caption。
- 确保舞台使用适合 iframe 预览的响应式布局，适配 960×540、常见桌面宽度和移动端。
- 确保页面使用单屏无滚动布局，html/body 与页面根容器压缩在 iframe 首屏内，禁止页面级滚动条。
- 确保标签、公式、步骤说明和控件避让主图，长文本进入说明区或自动换行。
- 在保证动画可播放优先的前提下，优先使用独立布局区域承载控制面板、caption、公式结论区，并给主舞台预留底部安全间距，避免悬浮遮挡。
- 移除舞台内巨型公式、巨型读数和遮挡主图的大字号文本；公式和读数迁移到 data-region="formula" 或 HUD 面板。
- 移除页脚署名、品牌署名和生成来源文字。
- 默认移除全局进度条/进度滑块；除非原始主题明确要求，否则不要恢复进度条。
- 确保播放/暂停/重置按钮（id="play-animation"、id="pause-animation"、id="reset-animation"）存在并绑定真实事件。
- 确保 window.AetherVizRuntime = {{ play, pause, reset, setSpeed, update, getState }} 声明完整。
- 确保 window.__AETHERVIZ_RUNTIME_READY__ = true 在初始化成功时设置。
- 允许且优先使用 GSAP core UMD CDN（https://cdn.jsdelivr.net/npm/gsap@3/dist/gsap.min.js）；不引入 Three.js、D3、GSAP 插件、其他外部时间线库或外部业务接口。
- 如果原页面缺少 GSAP，请补充 GSAP core CDN，并把关键分镜整理为可控 timeline；保留 requestAnimationFrame 只作为 Canvas/物理循环补充。
- 修复后的完整 HTML 必须控制在 {HTML_OUTPUT_TARGET_CHARS} 字符以内，绝对不要超过 {HTML_OUTPUT_HARD_LIMIT_CHARS} 字符；修复时优先压缩重复 CSS/JS、删除冗长注释和重复 DOM，禁止用长篇说明或大段静态数据撑大文件。
"""

EDIT_HTML_SYSTEM_PROMPT = f"""你是资深 OpenMAIC 单页互动 HTML 修改工程师。
你会收到一个现有 HTML 文件、用户修改意见和可选教案上下文。

要求：
- 只输出修改后的完整 <!DOCTYPE html>...</html>，不输出 Markdown 或解释。
- 以传入的 HTML 文件为唯一修改基线，不要推倒重写，不要生成全新无关页面。
- 保留原页面已有的教学主题、主要结构、交互控件、动画逻辑和可运行脚本。
- 按用户修改意见调整 HTML、CSS、SVG/Canvas/DOM 和业务 JS。
- 所有修改都产出新的 HTML 分支，不覆盖旧 HTML。
- 修复明显语法问题，确保内联 JavaScript 可解析。
- 允许且优先使用 GSAP core UMD CDN（https://cdn.jsdelivr.net/npm/gsap@3/dist/gsap.min.js）；不引入 Three.js、D3、GSAP 插件、其他外部时间线库或外部业务接口。
- 若用户要求优化演示效果，可在现有结构上补充或重构 GSAP timeline，但不要推倒重写。
- 修改后的完整 HTML 必须控制在 {HTML_OUTPUT_TARGET_CHARS} 字符以内，绝对不要超过 {HTML_OUTPUT_HARD_LIMIT_CHARS} 字符；如果原文件接近上限，应在不破坏功能的前提下精简重复样式、注释、静态文案和冗余 DOM，确保后续修改仍能完整放入上下文。
"""


def system_prompt_for_interactive_type(plan: dict) -> str:
    return {
        "simulation": SIMULATION_SYSTEM_PROMPT,
        "diagram": DIAGRAM_SYSTEM_PROMPT,
        "game": GAME_SYSTEM_PROMPT,
    }.get(str(plan.get("interactive_type")), INTERACTIVE_HTML_SYSTEM_PROMPT)


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
动画运行时：{(plan.get("runtime") or {}).get("animation_runtime", plan.get("animation_runtime", "gsap"))}
互动类型：{plan.get("interactive_type", "")}
互动规格：
{json.dumps(plan.get("interactive_spec") or {}, ensure_ascii=False, indent=2)}
设计蓝图：
{json.dumps(plan.get("design_brief") or {}, ensure_ascii=False, indent=2)}
教学流程：
{json.dumps(plan.get("teaching_flow", []), ensure_ascii=False, indent=2)}

修复第一目标：确保动画能完整播放并清晰演示上述教学目标。
舞台居中目标：#aetherviz-stage 内主 SVG/Canvas 必须在画布中居中显示，不能偏在左下角或任意角落。若是 SVG，请修正 viewBox、preserveAspectRatio、主体 group transform 或元素坐标；若是 Canvas，请按 width/2、height/2 计算中心后绘制主体。

服务端校验错误（需逐一修复）：
{error_detail}

原始任务提示词（供参考）：
{original_prompt}

失败 HTML（请在此基础上修复，不要推倒重写；若原文过长，以下只保留前 {HTML_OUTPUT_HARD_LIMIT_CHARS} 字符，修复输出必须压缩到上限以内）：
{raw_html[:HTML_OUTPUT_HARD_LIMIT_CHARS]}

请直接输出修复后的完整 HTML，不要输出任何解释。"""


def build_edit_html_prompt(
    *,
    topic: str,
    instruction: str,
    current_html: str,
    context: dict | None,
) -> str:
    context_payload = {
        "selected_file": (context or {}).get("selected_file"),
        "plan_summary": (context or {}).get("plan_summary"),
        "memory": (context or {}).get("memory"),
        "recent_messages": (context or {}).get("recent_messages"),
    }
    return f"""请根据用户修改意见编辑当前 HTML 文件，并输出编辑后的完整 HTML。

教学主题：{topic}
用户修改意见：{instruction}

可选上下文：
{json.dumps(context_payload, ensure_ascii=False, indent=2)}

当前 HTML 文件：
{current_html[:40000]}

请直接输出修改后的完整 HTML。"""


def build_interactive_generation_prompt(topic: str, plan: dict) -> str:
    runtime = plan.get("runtime") if isinstance(plan.get("runtime"), dict) else {}
    render_stack = runtime.get("render_stack") or "svg"
    interactive_type = plan.get("interactive_type", "simulation")
    type_hint = {
        "simulation": "仿真互动：学生调节变量时，主舞台、参数读数、caption 和结论必须实时同步变化。",
        "diagram": "图解互动：按 reveal_order 逐步揭示节点和关系，当前节点高亮，说明区同步展示解释。",
        "game": "游戏互动：提供明确挑战、操作对象、成功条件和反馈解释，学生完成操作后得到即时反馈。",
    }.get(interactive_type, "单页互动课件：操作、画面、说明和结论同步响应。")
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
    interactive_spec = plan.get("interactive_spec") or {}
    widget_outline = plan.get("widget_outline") or {
        "type": interactive_type,
        "concept": interactive_spec.get("concept", topic) if isinstance(interactive_spec, dict) else topic,
    }
    scene_outline = plan.get("scene_outline") or {}
    design_brief = plan.get("design_brief") or {}
    key_points = plan.get("key_points") or scene_outline.get("keyPoints") or []
    widget_actions = plan.get("widget_actions") or []
    teaching_flow = plan.get("teaching_flow", [])
    teaching_flow_section = (
        f"教学流程（页面需要完整展示，并能同步标注当前步骤）:\n{json.dumps(teaching_flow, ensure_ascii=False, indent=2)}\n"
        if teaching_flow
        else ""
    )
    runtime_section = f"""动画运行时（必须落实）：
- 使用 GSAP core：在 head 或业务脚本前加载 `{GSAP_CORE_CDN}`，禁止使用 GSAP 插件和其他动画库。
- 使用 `gsap.timeline({{ paused: true, defaults: {{ duration: 0.55, ease: "power2.out" }} }})` 或等价 timeline 编排 3~5 个教学分镜；用 label 命名分镜，避免只靠 setTimeout/delay 串联。
- 播放、暂停、重置、速度和主题参数控件必须真实控制 timeline：play、pause、restart、timeScale、progress 或按参数重建 timeline。
- timeline 的 onUpdate 或统一 updateScene 函数必须同步更新 caption、完整分镜列表 active/current 标记、读数/公式和关键元素高亮。
- 使用 GSAP transform 别名（x、y、scale、rotation、autoAlpha、svgOrigin/transformOrigin）驱动 DOM/SVG 元素，避免每帧重建 SVG。
- Canvas 高频动画可以继续使用 requestAnimationFrame，但需由 GSAP timeline 控制教学节奏、透明度、强调态或阶段切换。
- 必须实现 `window.gsap` 缺失时的 native fallback，fallback 至少保证播放、暂停、重置、参数变更、caption 和主视觉状态更新可用。
- 运行时更新当前步骤时，必须同步更新完整分镜列表的 active/current 标记，其他幕说明仍保持可见。
- 默认不要生成可见全局进度条或进度滑块；window.AetherVizRuntime.update(value) 可内部跳转当前步骤或动画状态。
"""

    return f"""任务：根据确认后的方案生成一个独立互动教学 HTML。

主题：{topic}
标题：{plan["title"]}
目标：{plan["goal"]}
互动类型：{interactive_type}
主色：{plan.get("primary_color", "#22D3EE")}

1. OpenMAIC Scene Outline
{json.dumps(scene_outline, ensure_ascii=False, indent=2)}

2. 关键教学点
{json.dumps(key_points, ensure_ascii=False, indent=2)}

3. 渲染栈
{render_stack_hint}

4. 运行时
{runtime_section}

5. 舞台布局
{plan.get("stage_layout", "顶部学习目标，中间大舞台，底部 caption、控制条和公式/结论区。")}

6. 互动规格
{json.dumps(interactive_spec, ensure_ascii=False, indent=2)}

7. Widget Outline
{json.dumps(widget_outline, ensure_ascii=False, indent=2)}

8. Design Brief
{json.dumps(design_brief, ensure_ascii=False, indent=2)}

9. OpenMAIC widget 契约落地
- 必须把第 6 节互动规格原样转化为 `script#widget-config[type="application/json"]`。
- widget-config.type 必须是 "{interactive_type}"。
- 必须实现 iframe action message listener：SET_WIDGET_STATE、HIGHLIGHT_ELEMENT、ANNOTATE_ELEMENT、REVEAL_ELEMENT。
- SET_WIDGET_STATE 必须能更新对应 slider/input/select 并派发 input/change 事件，让画面实时刷新。
- HIGHLIGHT_ELEMENT/ANNOTATE_ELEMENT/REVEAL_ELEMENT 必须作用于真实 DOM/SVG 元素，不能写空 switch。
- 页面初始化不得依赖 localStorage、外部接口或异步资源才能显示主视觉。
OpenMAIC action 示例（需要可执行地映射到上述 message listener）:
{json.dumps(widget_actions, ensure_ascii=False, indent=2)}

10. 互动验收
- 默认进入可观察状态，至少 3 个可观察状态变化，不能只是静态图形加文字。
- #aetherviz-stage 内主 SVG/Canvas 居中；SVG 使用 preserveAspectRatio="xMidYMid meet" 和稳定主视觉 id/class/data-role。
- 主舞台使用 id="aetherviz-stage" 和 data-region="stage"；控制区、公式区、caption 区使用稳定 data-region，关键教学元素使用 data-role。
- animation-caption 或 step-caption 必须随动画状态更新。
- 必须在页面中显示完整教学流程列表，覆盖 teaching_flow 条目；当前步骤用 active/current 状态同步标注，不能只显示当前 caption。
- 控件必须绑定真实功能；不要生成可见全局进度条或进度滑块。
- 公式、读数、caption 和说明不得作为主舞台巨型文字覆盖图形；主舞台内文字仅用于短标签，复杂表达放到公式/HUD 面板。
- 不输出页脚署名、品牌署名或生成来源文案。

11. 互动类型要求
{type_hint}

{teaching_flow_section}

12. 控件
{json.dumps(plan.get("controls", []), ensure_ascii=False, indent=2)}

{formula_section}输出格式：只输出完整 HTML，不要输出 Markdown、解释或页面署名。
"""
