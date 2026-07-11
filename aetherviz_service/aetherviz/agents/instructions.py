"""Prompt builders for AetherViz dynamic HTML."""

from __future__ import annotations

import json

from aetherviz_service.aetherviz.constants import (
    HTML_OUTPUT_HARD_LIMIT_CHARS,
    HTML_OUTPUT_TARGET_CHARS,
    get_gsap_core_cdn_url,
)

GSAP_CORE_CDN = get_gsap_core_cdn_url()

WIDGET_CORE_PROMPT = """互动 widget 核心契约：
- 生成物必须是一个自包含 interactive widget，不是 PPT 截图、静态海报或普通选择题页面。
- 生成逻辑必须以 scene_outline、widget_outline、interactive_spec 和 design_brief 为唯一蓝图；不得退化成通用模板动画。
- 必须嵌入 `<script type="application/json" id="widget-config">...</script>`；JSON.type 必须等于 simulation、diagram 或 game，并与 plan.interactive_type 一致。widget-config 内容必须是严格的纯 JSON 格式，禁止包含任何 JS 注释（如 // 或 /* */）和尾随逗号。
- widget-config 必须承载本页核心互动配置：simulation 写 concept/description/variables/presets；diagram 写 nodes/edges/revealOrder；game 写 gameType/description/gameConfig/successCondition/feedbackRules。
- 必须实现 `window.addEventListener("message", ...)`，至少处理 SET_WIDGET_STATE、HIGHLIGHT_ELEMENT、ANNOTATE_ELEMENT、REVEAL_ELEMENT 四类 iframe-local widget action。
- 变量控件 ID 使用 `{variable_name}-slider` 或 `data-var="{variable_name}"`；按钮 ID 使用 `{action}-btn` 或计划中的稳定 id；可被高亮/标注的元素必须有 id 或 data-role。
- 主舞台、控制面板、说明、公式和 HUD 必须是分区布局；控制面板不能覆盖 Canvas/SVG，移动端使用堆叠、抽屉或可折叠布局。
- 计算对象位置时必须预留 TOP_MARGIN/BOTTOM_MARGIN 或等价安全区，不能把对象画到控制区、HUD、caption、公式区下面。
- 舞台内只放短标签和图形标注；公式、读数、caption、推导步骤放独立面板。禁止把公式/读数渲染成主舞台超大文本；SVG text 的屏幕视觉字号建议 10~18 CSS px，超过 28 CSS px 必须有明确局部标签理由。
- 使用清晰状态机：running、paused、ended 或等价状态；reset 必须重置所有位置、速度、分数、步骤、按钮文本和参数到初始状态。
- 所有触摸目标至少 44px；slider thumb 至少 24px；Canvas 自定义手势使用 touch-action: none。
- 输出必须只有一个 HTML 文档，只能有一个 <!DOCTYPE html> 和一个 </html>。
"""

STAGE_CENTERING_AND_LABEL_PROMPT = """舞台居中与标签防重叠规则：
- #aetherviz-stage 内主 SVG/Canvas 必须在舞台可视区域水平和垂直居中。SVG 将可变主体放入独立 <g>，在初始化、状态变化和容器尺寸变化后依据实际内容包围盒（getBBox 或等价计算）加安全边距更新 viewBox，并用 preserveAspectRatio="xMidYMid meet"；禁止使用固定 scale + 固定 viewBox 承载会随参数改变范围的图形。Canvas 基于容器实际尺寸和 devicePixelRatio，以 width/2、height/2 为主体中心，并在 ResizeObserver 或 resize 时重新布局。
- SVG 标签的视觉字号必须按 viewBox 与容器像素比例换算，或使用不随主图整体缩放的 HTML 覆盖层，使其在屏幕上保持正常正文/短标签尺寸；不能把 10~18 个 SVG 用户单位误当成固定 CSS 像素。图形轮廓优先使用 vector-effect="non-scaling-stroke"。
- 同一视觉元素上不同用途的文本标签（例如变量名标签与其对应的数值/面积/单位标签）禁止使用完全相同的 x/y 坐标；必须保持可读的最小偏移（至少一个字号高度或等价间距），确保任意两段文字不会互相覆盖。
"""

ADAPTIVE_LAYOUT_PROMPT = """自适应布局与信息密度规则：
- 主舞台是最高优先级区域并获得最大剩余空间；学习目标、控制、公式和 caption 是辅助区域。禁止用两个固定像素侧栏夹住 1fr 主舞台；Grid/Flex 子项使用 min-width:0、min-height:0，并优先采用 minmax(0,1fr)、clamp、auto-fit 或容器查询。
- 蓝图中的“左/右/底部”表示宽屏首选相对位置，不是不可变坐标。可用空间不足时必须自动切换为上下堆叠、紧凑工具栏、抽屉或可折叠辅助区，不能继续压缩、裁切或覆盖主舞台。
- 完整教学步骤用紧凑步骤条展示短标题，详细说明只在当前 caption 展示；重复公式、读数和解释只保留一处，避免为满足“可见”要求重复堆叠内容。
- 以 #aetherviz-stage 的实际容器尺寸而非 window 固定尺寸驱动图形布局；iframe 任意宽高变化后仍须保持主图、短标签和核心控件完整可见。
"""

VISUAL_DESIGN_SYSTEM_PROMPT = """UI 视觉系统（与 AI动态课件前端一致）：
- 默认采用“清爽教学工作台”浅色主题，不生成整页深色/霓虹仪表盘。页面底色使用温和灰绿，主容器和主舞台使用白色/纸张色；以深森林绿承担标题和主要操作、清透绿色承担选中/进度/焦点。可参考语义色：brand #2d4f41、brand-strong #1d3a2f、accent #10b981、accent-soft #ecfdf5、canvas #f6f8f5、paper #ffffff、text #1e332b、muted #52665e、border rgba(45,79,65,.14)。plan.primary_color 只用于主视觉对象、数据系列或少量互动强调，不得把所有面板染成该颜色。
- 采用 PingFang SC、Microsoft YaHei、Noto Sans SC 和系统无衬线字体栈；正文保持高可读性。标题、正文、辅助说明、数值读数建立明确层级，避免全粗体、超大标题、低对比灰字和装饰性英文。
- 外层使用克制的细边框、8~16px 圆角和低透明柔和阴影；主舞台可用极淡点阵/网格帮助定位，但不能干扰图形。不要滥用玻璃拟态、发光、紫色渐变、厚重阴影、胶囊按钮或“每段内容一个卡片”的卡片墙。
- 控件形成一致组件语言：主要按钮用深绿或 accent 实底，次要按钮用白底细边框，当前步骤/选中项用 accent-soft；滑块使用浅轨道、清晰进度和高对比 thumb；输入、按钮、标签必须有 hover、active、focus-visible、disabled 状态。成功/警告/错误分别使用绿/琥珀/红语义，不能只靠颜色传达状态。
- 面板内部用留白、分组标题和细分隔线组织内容；读数/HUD 使用紧凑的浅色强调块，公式使用易读的等宽数字或数学排版。装饰必须服务学科语义，饱和色优先留给数据对象、关键节点、反馈和当前状态。
- 生成前先按实际内容选择密度：控件少时留出呼吸感；变量、节点或游戏状态较多时使用分组、两列紧凑排布、渐进披露或可折叠区，禁止通过缩小字号和触摸目标强塞内容。
"""

INTERACTIVE_HTML_SYSTEM_PROMPT = f"""你是资深单页互动 widget 工程师。
只输出一个完整可运行 HTML 文件，从 <!DOCTYPE html> 开始，到 </html> 结束。
如果模型输出 reasoning_content，必须使用简体中文，且只写面向用户的简短设计摘要。

{WIDGET_CORE_PROMPT}

{VISUAL_DESIGN_SYSTEM_PROMPT}

{ADAPTIVE_LAYOUT_PROMPT}

{STAGE_CENTERING_AND_LABEL_PROMPT}
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
- 必须加载 `<script src="{GSAP_CORE_CDN}"></script>`，并优先用 `gsap.timeline({{ paused: true, defaults: {{ duration, ease }} }})` 组织分镜动画。
- timeline 必须包含有持续时间的 `to`/`from`/`fromTo` tween，或在相邻 `call` 之间使用明确 position/延时；禁止只连续追加零时长 `call()`，否则所有分镜会在同一时刻瞬间执行。
- 播放、暂停、重置、速度和主题参数控件必须控制 GSAP timeline：play/pause/restart/timeScale/progress 或重建 timeline；caption、步骤 active/current 标记和读数必须在 timeline onUpdate 或状态更新函数中同步。
- Canvas 高频粒子、轨迹或物理循环可用 requestAnimationFrame 补充，但 DOM/SVG 入场、强调、变形、步骤切换和教学节奏必须使用 GSAP tween/timeline。
- 如果 `window.gsap` 不可用，必须保留可运行的 native fallback，确保主视觉、caption 和控件仍能响应。
- 输出 HTML 必须控制在 {HTML_OUTPUT_TARGET_CHARS} 字符以内，绝对不要超过 {HTML_OUTPUT_HARD_LIMIT_CHARS} 字符；避免冗长注释、重复 CSS、内联大数据、base64、超长文案和重复 DOM，确保后续 HTML 修改阶段不会因上下文上限截断尾部脚本。
- 边写边估算已输出字符数：写到目标字符数的 70% 左右就要开始收敛，只保留必需的分镜/控件/样式，不要在临近上限时才压缩；宁可减少非核心装饰，也不要让 <script> 结尾的收尾逻辑（事件绑定、AetherVizRuntime、ready 标记）被挤到字符上限之外。
"""

SIMULATION_SYSTEM_PROMPT = INTERACTIVE_HTML_SYSTEM_PROMPT + """
simulation 补充要求：
- 必须把 interactive_spec.variables 落成真实滑块、按钮或预设控件。
- 参数变化要实时驱动画面、数值读数、caption 和结论，不允许只改文字。
- 默认状态能直接理解，至少提供一个可比较的参数变化结果。
- 启动/播放后必须有明显运动、旋转、变形或轨迹变化，不能只有数字变化。
- resetSimulation 或等价函数必须把所有变量、动画时间、图形位置、按钮状态和提示恢复初始值。
- UI 以大面积浅色实验舞台为核心；变量控件按变量分组，实时读数使用一个紧凑结果区，播放控制保持单行或紧凑换行。不要为每个变量、公式和观察结论各建一张大卡片。
"""

DIAGRAM_SYSTEM_PROMPT = INTERACTIVE_HTML_SYSTEM_PROMPT + """
diagram 补充要求：
- 必须把 interactive_spec.nodes、edges、reveal_order 落成节点、连线和逐步揭示。
- 节点和边不能重叠；点击或步骤按钮能高亮当前节点并显示说明。
- 移动端仍应可读，交互不能依赖复杂拖拽。
- UI 以关系画布为核心，通过节点层级、连线粗细/虚实和少量语义色表达结构；详情说明放在单一 inspector/caption 区。禁止把所有节点做成同等权重的卡片墙。
"""

GAME_SYSTEM_PROMPT = INTERACTIVE_HTML_SYSTEM_PROMPT + """
game 补充要求：
- 必须把 interactive_spec.challenge、success_condition、feedback_rules 落成可玩的课堂挑战。
- 不能退化为普通选择题堆叠；需要有操作对象、排序、匹配、调参或策略选择。
- 默认公平开始，提供即时反馈和解释。
- 如果包含实时游戏循环，必须有 3~5 秒安全期或等价安全初始状态，玩家不能一开始就失败。
- 学习必须通过操作发生，题目问答只能作为辅助手段，不能成为唯一玩法。
- UI 保持教学产品而非街机霓虹风：挑战区占主位，分数/进度/生命等 HUD 紧凑集中；可操作对象具有清晰 hover/selected/correct/incorrect 状态，反馈解释紧邻操作结果但不遮挡舞台。
"""

REPAIR_SYSTEM_PROMPT = f"""你是 HTML 最小变更修复器。
只输出完整 <!DOCTYPE html>...</html>，不输出 Markdown、解释或 reasoning。
以输入 HTML 为唯一基线，只修复服务端列出的硬性错误；禁止顺带重做布局、坐标、文案、配色、动画或教学结构。
保留原有 DOM 顺序、CSS、SVG/Canvas 坐标、控件和业务逻辑；没有对应错误时不得改动。
若必须补代码，复用现有函数和状态，不引入新框架、外部接口或 GSAP 插件。
输出必须可解析、可运行且不超过 {HTML_OUTPUT_HARD_LIMIT_CHARS} 字符。
"""

EDIT_HTML_SYSTEM_PROMPT = f"""你是资深单页互动 HTML 修改工程师。
你会收到一个现有 HTML 文件、用户修改意见和可选教案上下文。

{VISUAL_DESIGN_SYSTEM_PROMPT}

{ADAPTIVE_LAYOUT_PROMPT}

{STAGE_CENTERING_AND_LABEL_PROMPT}
要求：
- 只输出修改后的完整 <!DOCTYPE html>...</html>，不输出 Markdown 或解释。
- 以传入的 HTML 文件为唯一修改基线，不要推倒重写，不要生成全新无关页面。
- 保留原页面已有的教学主题、主要结构、交互控件、动画逻辑和可运行脚本。
- 按用户修改意见调整 HTML、CSS、SVG/Canvas/DOM 和业务 JS；若用户反馈配色、组件风格、拥挤、裁切、响应式、居中或标签重叠问题，按上方视觉系统、自适应布局、动态包围盒和标签视觉字号规则定位并修正，不要只替换一个背景色或调整样式表层属性。
- 所有修改都产出新的 HTML 分支，不覆盖旧 HTML。
- 修复明显语法问题，确保内联 JavaScript 可解析。
- 允许且优先使用 GSAP core UMD CDN（{GSAP_CORE_CDN}）；不引入 Three.js、D3、GSAP 插件、其他外部时间线库或外部业务接口。
- 若用户要求优化演示效果，可在现有结构上补充或重构 GSAP timeline，但不要推倒重写。
- 修改 timeline 时禁止只连续追加零时长 `call()`；必须保留有持续时间的 tween 或明确的 position 间隔。
- 修改后的完整 HTML 必须控制在 {HTML_OUTPUT_TARGET_CHARS} 字符以内，绝对不要超过 {HTML_OUTPUT_HARD_LIMIT_CHARS} 字符；如果原文件接近上限，应在不破坏功能的前提下精简重复样式、注释、静态文案和冗余 DOM，确保后续修改仍能完整放入上下文。
- 边写边估算已输出字符数：写到目标字符数的 70% 左右就要开始收敛，优先保留用户要求修复的功能和原有核心结构，只精简非必需的装饰、重复样式和冗余 DOM，不要让 <script> 结尾的收尾逻辑（事件绑定、AetherVizRuntime、ready 标记）被挤到字符上限之外。
"""


def _compact_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


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
    raw_html: str,
    error_detail: str,
    source_label: str,
) -> str:
    return f"""修复以下{source_label}失败的 HTML。
上下文：{_compact_json({"topic": topic, "goal": plan.get("goal", ""), "interactive_type": plan.get("interactive_type", "")})}
硬性错误：{error_detail}
执行原则：逐项修复错误；未被错误点名的布局、坐标、动画、文案和交互保持不变。
原始 HTML：
{raw_html}
只输出修复后的完整 HTML。"""


EDIT_PLAN_SUMMARY_FIELDS = (
    "title",
    "goal",
    "interactive_type",
    "design_brief",
    "interactive_spec",
)


def _trim_plan_summary_for_edit(plan_summary: object) -> object:
    """Keep only fields that materially help HTML edit/bug-fix prompts.

    edit_html 只是在已有 HTML 上做局部修改，不需要完整的 scene_outline、
    widget_actions、teaching_flow、formulas 等生成阶段蓝图字段；裁剪后可
    显著降低 prompt 体积，缩短首 token 延迟。
    """
    if not isinstance(plan_summary, dict):
        return plan_summary
    trimmed = {field: plan_summary[field] for field in EDIT_PLAN_SUMMARY_FIELDS if field in plan_summary}
    return trimmed or plan_summary


def build_edit_html_prompt(
    *,
    topic: str,
    instruction: str,
    current_html: str,
    context: dict | None,
) -> str:
    context_payload = {
        "selected_file": (context or {}).get("selected_file"),
        "plan_summary": _trim_plan_summary_for_edit((context or {}).get("plan_summary")),
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
    interactive_spec = plan.get("interactive_spec") or {}
    widget_outline = plan.get("widget_outline") or {
        "type": interactive_type,
        "concept": interactive_spec.get("concept", topic) if isinstance(interactive_spec, dict) else topic,
    }
    scene_outline = plan.get("scene_outline") or {}
    design_brief = plan.get("design_brief") or {}
    if isinstance(scene_outline, dict):
        # scene_outline 往往内嵌一份 widgetOutline；后文已有规范化后的
        # widget_outline，重复传递只会增加首 token 延迟并制造冲突。
        scene_outline = {
            key: value
            for key, value in scene_outline.items()
            if key not in {"widgetOutline", "widget_outline"}
        }
    widget_actions = plan.get("widget_actions") or []
    teaching_flow = plan.get("teaching_flow", [])
    blueprint = {
        "topic": topic,
        "title": plan["title"],
        "goal": plan["goal"],
        "interactive_type": interactive_type,
        "primary_color": plan.get("primary_color", "#22D3EE"),
        "scene_outline": scene_outline,
        "stage_layout": plan.get(
            "stage_layout",
            "顶部学习目标，中间大舞台，底部 caption、控制条和公式/结论区。",
        ),
        "runtime": runtime,
        "interactive_spec": interactive_spec,
        "widget_outline": widget_outline,
        "design_brief": design_brief,
        "teaching_flow": teaching_flow,
        "controls": plan.get("controls", []),
        "formulas": formulas,
        "widget_actions": widget_actions,
    }
    return f"""按 system 约束，将下列确认蓝图生成一个独立互动教学 HTML。
蓝图：{_compact_json(blueprint)}
渲染建议：{render_stack_hint}
类型验收：{type_hint}
关键落地：widget-config 原样承载 interactive_spec 且 type={interactive_type}；四类 message action 必须作用于真实元素；教学流程完整可见并同步当前步骤；控件绑定真实功能；首屏不依赖异步资源。
只输出完整 HTML。"""
