"""Fallback planning logic for the AetherViz interactive teaching animation generator."""

from __future__ import annotations

import json
import re

DEFAULT_PRIMARY_COLOR = "#22D3EE"

SUBJECT_KEYWORDS = {
    "math": ["数学", "几何", "证明", "三角", "函数", "代数", "方程", "概率", "统计", "向量", "面积", "体积", "导数", "积分", "勾股", "坐标", "平行四边形", "圆", "椭圆", "抛物线"],
    "physics": ["物理", "牛顿", "力", "运动", "碰撞", "弹簧", "速度", "加速度", "动量", "能量", "重力", "摩擦", "浮力", "电阻", "电流", "电压", "惯性", "波", "光"],
    "chemistry": ["化学", "反应", "元素", "分子", "原子", "周期表", "离子", "酸", "碱", "盐", "氧化", "还原", "溶液", "溶解度"],
    "biology": ["生物", "细胞", "基因", "dna", "蛋白质", "光合", "呼吸", "植物", "动物", "生态", "遗传"],
    "programming": ["算法", "排序", "递归", "树", "图", "状态机", "队列", "栈", "复杂度", "编程", "代码"],
    "geography": ["地理", "大气", "地球", "经纬", "板块", "地震", "地形", "气候", "水文", "洋流"],
    "chinese": ["语文", "诗词", "文言", "古文", "修辞", "散文", "小说", "汉字", "阅读"],
    "english": ["英语", "english", "语法", "句型", "词汇", "单词", "时态", "从句", "grammar", "tense"],
}

VALID_MODES = {"svg_animation", "math_interactive", "process_flow"}
VALID_ANIMATION_STRATEGIES = {"step_by_step", "continuous", "interactive_param"}
VALID_RENDER_STACKS = {"svg", "svg_canvas", "canvas_svg", "dom_svg"}
VALID_ANIMATION_RUNTIMES = {"native", "gsap_timeline"}

PLANNING_SYSTEM_PROMPT_TEMPLATE = """你是 AetherViz 互动教学动画规划师。
根据用户教学主题，为中学生（12~18岁）设计一套清晰、直观、流畅的互动教学动画方案。

你的核心目标：让学生通过观察动画和调节参数，自然理解教学主题的核心原理。

---

规划要求：

1. **动画策略（animation_strategy）**优先于技术选型：
   - step_by_step：分步骤演示，每一步有明确的"当前状态高亮"和"步骤说明"
   - continuous：连续变化动画，适合展示渐变、运动轨迹等平滑过程
   - interactive_param：参数调控型，学生拖拽滑块实时观察结果变化

2. **生成模式（mode）**根据主题特点自主选择：
   - svg_animation：通用 SVG 动画，适合大多数主题
   - math_interactive：数学互动，需要展示几何关系或函数图像
   - process_flow：过程流程型，适合化学反应、生物过程等

3. **渲染栈（render_stack）**决定画面职责，不再把所有效果都塞进 SVG：
   - svg：几何证明、函数图像、少量对象的结构变化
   - svg_canvas：Canvas 负责连续运动/粒子/轨迹，SVG 负责坐标轴、标注、公式锚点
   - canvas_svg：Canvas 为主视觉，SVG/DOM 只做少量标注和交互热点
   - dom_svg：流程卡片、时间轴、步骤解释为主，SVG 做连接线和高亮

4. **动画运行时（animation_runtime）**决定动画编排职责：
   - native：简单参数联动、CSS/RAF 过渡、Canvas 高频绘制
   - gsap_timeline：分步讲解、几何剪拼、公式同步高亮、复杂进出场和播放控制
   - Canvas 粒子、波动、碰撞等高频场景优先 native；如选 gsap_timeline，GSAP 只驱动分镜状态或阶段，不逐对象驱动粒子。

5. **number_design** 必须给出默认数值和设计理由。默认数值应通俗、可心算、符合教学目标，避免随机长小数。

6. **stage_layout** 描述首屏舞台编排：目标导航、主舞台、公式/结论区、紧凑控制条如何摆放，必须避免小图挤在角落，也不能导致 iframe 出现页面级滚动条。

7. **storyboard** 描述教学分镜：每一幕包含镜头焦点、运动对象、同步出现的解释或公式。

8. **timeline_scenes** 把 storyboard 落成 3~6 个可播放 scene，每个 scene 包含 id、label、duration、focus、caption；如果 animation_runtime=gsap_timeline，每个 scene 必须对应后续 HTML 里的 timeline label。

9. **visual_steps** 描述动画演示的节奏，格式示例：
   "第1步：[初始状态描述] → [过渡描述] → [终态说明]"
   每步要描述：什么在移动/变化、变化速度、学生应该观察什么。

10. **controls** 只保留真正影响核心原理理解的控件，不超过 4 个。默认不要规划全局进度条/进度滑块；需要回看分镜时优先使用“下一步/上一步/演示一次”按钮，滑块只用于真实教学变量。

11. **formulas** 如果主题涉及公式，列出核心公式；无公式主题可为空列表。

---

字段约束：
- subject：math / physics / chemistry / biology / astronomy / programming / geography / chinese / english / general
- mode：svg_animation / math_interactive / process_flow
- animation_strategy：step_by_step / continuous / interactive_param
- render_stack：svg / svg_canvas / canvas_svg / dom_svg
- animation_runtime：native / gsap_timeline
- title：页面标题（不超过 20 字）
- goal：一句话教学目标，描述学生能从动画中学到什么
- stage_layout：一句话描述页面舞台布局与信息层级
- storyboard：3~5 条教学分镜，每条说明镜头焦点、运动对象、解释文字
- timeline_scenes：3~6 个对象，每个包含 id、label、duration、focus、caption
- number_design：对象，包含 default_values 数组和 reason 字符串
- visual_steps：3~5 条，每条描述动画节奏与学生关注点
- controls：2~4 个控件，每个包含 id、label、type（slider/button/speed），不要默认使用旧式进度滑块
- formulas：0~4 条核心公式或关键表达
- primary_color：主色（十六进制）

只输出 JSON 对象，不输出 Markdown 或解释。

输出 JSON 示例：
{
  "subject": "math",
  "mode": "math_interactive",
  "animation_strategy": "interactive_param",
  "render_stack": "svg",
  "animation_runtime": "gsap_timeline",
  "title": "平行四边形面积互动动画",
  "goal": "通过拖动底和高，观察面积随两个参数实时变化，理解面积公式 S = a × h 的几何意义。",
  "stage_layout": "顶部用目标胶囊提示学习路径，中间大舞台展示可拖拽图形，底部紧凑控制条和公式结论区，整体控制在单屏内。",
  "storyboard": [
    "镜头1：平行四边形居中放大，底和高依次点亮，旁边出现面积读数",
    "镜头2：拖动底边时图形横向伸缩，公式中的 a 和面积数字同步变化",
    "镜头3：剪拼动画把斜边三角形平移为长方形，结论区高亮 S=a×h"
  ],
  "timeline_scenes": [
    {"id": "scene_intro", "label": "认识底和高", "duration": 1.0, "focus": "平行四边形居中出现，底和高依次点亮", "caption": "先找到底和高，它们决定面积。"},
    {"id": "scene_param", "label": "参数变化", "duration": 1.2, "focus": "底边滑块变化，面积读数同步更新", "caption": "底变长时，面积按同样比例增大。"},
    {"id": "scene_cut", "label": "剪拼验证", "duration": 1.5, "focus": "斜边三角形平移为长方形", "caption": "剪拼后面积不变，所以 S=a×h。"}
  ],
  "number_design": {
    "default_values": ["底 = 6", "高 = 4", "面积 = 24"],
    "reason": "使用一位整数和可心算面积，学生能快速验证底乘高的关系。"
  },
  "visual_steps": [
    "第1步：展示标准平行四边形，底和高用彩色标注，面积数值同步显示",
    "第2步：拖动底部滑块，底边长度平滑变化，面积数值实时更新，学生观察底与面积的比例关系",
    "第3步：拖动高度滑块，等效长方形辅助线同步显示，说明高的作用",
    "第4步：点击'剪拼演示'，动画展示平行四边形变形为等面积长方形的过程"
  ],
  "controls": [
    {"id": "base-slider", "label": "底边长", "type": "slider"},
    {"id": "height-slider", "label": "高", "type": "slider"},
    {"id": "demo-btn", "label": "剪拼演示", "type": "button"},
    {"id": "speed-control", "label": "速度", "type": "speed"}
  ],
  "formulas": ["S = a \\times h"],
  "primary_color": "#22D3EE"
}
"""


def detect_subject(topic: str) -> str:
    if not topic:
        return "general"
    topic_lower = topic.lower()
    for subject in ("math", "chemistry", "biology", "geography", "physics", "programming", "chinese", "english"):
        if any(keyword in topic_lower for keyword in SUBJECT_KEYWORDS[subject]):
            return subject
    return "general"


def select_generation_mode(subject: str) -> str:
    if subject == "math":
        return "math_interactive"
    if subject in ("chemistry", "biology"):
        return "process_flow"
    return "svg_animation"


def select_animation_strategy(subject: str) -> str:
    if subject == "math":
        return "interactive_param"
    if subject in ("physics",):
        return "continuous"
    return "step_by_step"


def select_render_stack(subject: str, topic: str = "") -> str:
    topic_lower = topic.lower()
    if any(keyword in topic_lower for keyword in ("粒子", "扩散", "热", "流场", "波", "轨迹", "运动", "碰撞")):
        return "svg_canvas"
    if subject == "math":
        return "svg"
    if subject in ("chemistry", "biology"):
        return "dom_svg"
    if subject == "physics":
        return "svg_canvas"
    return "dom_svg"


def select_animation_runtime(subject: str, topic: str = "", render_stack: str = "svg") -> str:
    topic_lower = topic.lower()
    if render_stack in {"svg_canvas", "canvas_svg"} and any(
        keyword in topic_lower for keyword in ("粒子", "扩散", "流体", "波动", "碰撞", "分子", "布朗")
    ):
        return "native"
    if subject == "math" and any(
        keyword in topic_lower for keyword in ("几何", "面积", "体积", "勾股", "三角", "函数", "剪拼", "证明", "圆", "抛物线")
    ):
        return "gsap_timeline"
    if subject in {"chemistry", "biology"} and any(
        keyword in topic_lower for keyword in ("过程", "反应", "阶段", "循环", "链", "转化", "光合", "呼吸")
    ):
        return "gsap_timeline"
    if subject in {"chinese", "english", "geography"}:
        return "gsap_timeline"
    return "native"


def build_planning_prompt(topic: str, primary_color: str) -> tuple[str, str]:
    subject = detect_subject(topic)
    mode = select_generation_mode(subject)
    animation_strategy = select_animation_strategy(subject)
    render_stack = select_render_stack(subject, topic)
    animation_runtime = select_animation_runtime(subject, topic, render_stack)
    user_prompt = f"""请为以下教学主题设计一套 AetherViz 互动教学动画方案：

主题：{topic}
服务端学科识别：{subject}
推荐生成模式：{mode}
推荐动画策略：{animation_strategy}
推荐渲染栈：{render_stack}
推荐动画运行时：{animation_runtime}
主色调：{primary_color}

受众：初高中学生（12~18岁），需要通过直观的动画和参数调控来理解核心原理。

请以服务端识别结果为默认方案；只有当主题语义明显更适合其它合法值时，才调整 mode、animation_strategy、render_stack 或 animation_runtime。必须输出 stage_layout、storyboard、timeline_scenes 和 number_design，让后续 HTML 生成有清晰舞台、分镜时间线和学生友好默认数值。输出完整 JSON 方案。
"""
    return PLANNING_SYSTEM_PROMPT_TEMPLATE, user_prompt


def parse_planning_result(raw: str, topic: str = "", primary_color: str = DEFAULT_PRIMARY_COLOR) -> dict:
    data: dict = {}
    if raw:
        cleaned = raw.strip()
        if "```" in cleaned:
            fence_match = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL | re.IGNORECASE)
            if fence_match:
                cleaned = fence_match.group(1).strip()
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            cleaned = match.group(0)
        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                data = parsed
        except Exception:
            data = {}
    return normalize_plan(data, topic, primary_color)


def normalize_plan(raw_plan: dict | None, topic: str, primary_color: str = DEFAULT_PRIMARY_COLOR) -> dict:
    raw = raw_plan if isinstance(raw_plan, dict) else {}
    fallback = _default_plan(topic, primary_color)

    detected_subject = fallback["subject"]
    subject = _safe_str(raw.get("subject")) or detected_subject
    if subject not in {*SUBJECT_KEYWORDS.keys(), "astronomy", "general"}:
        subject = detected_subject
    if detected_subject != "general" and subject != detected_subject:
        subject = detected_subject

    mode = _safe_str(raw.get("mode")) or select_generation_mode(subject)
    if mode not in VALID_MODES:
        mode = select_generation_mode(subject)
    if subject in {"math", "chemistry", "biology"}:
        mode = select_generation_mode(subject)

    animation_strategy = _safe_str(raw.get("animation_strategy")) or select_animation_strategy(subject)
    if animation_strategy not in VALID_ANIMATION_STRATEGIES:
        animation_strategy = select_animation_strategy(subject)

    render_stack = _safe_str(raw.get("render_stack")) or select_render_stack(subject, topic)
    if render_stack not in VALID_RENDER_STACKS:
        render_stack = select_render_stack(subject, topic)

    animation_runtime = _safe_str(raw.get("animation_runtime")) or select_animation_runtime(subject, topic, render_stack)
    if animation_runtime not in VALID_ANIMATION_RUNTIMES:
        animation_runtime = select_animation_runtime(subject, topic, render_stack)
    if render_stack in {"svg_canvas", "canvas_svg"} and any(
        keyword in topic.lower() for keyword in ("粒子", "扩散", "流体", "波动", "碰撞", "分子", "布朗")
    ):
        animation_runtime = "native"

    formulas = _string_list(raw.get("formulas"), fallback["formulas"], max_items=4, max_len=80)
    storyboard = _string_list(raw.get("storyboard"), fallback["storyboard"], max_items=5, max_len=220)
    timeline_scenes = _normalize_timeline_scenes(raw.get("timeline_scenes"), storyboard, fallback["timeline_scenes"])
    number_design = _normalize_number_design(raw.get("number_design"), fallback["number_design"])

    return {
        "subject": subject,
        "mode": mode,
        "animation_strategy": animation_strategy,
        "render_stack": render_stack,
        "animation_runtime": animation_runtime,
        "title": (_safe_str(raw.get("title")) or fallback["title"])[:48],
        "goal": (_safe_str(raw.get("goal")) or fallback["goal"])[:160],
        "stage_layout": (_safe_str(raw.get("stage_layout")) or fallback["stage_layout"])[:180],
        "storyboard": storyboard,
        "timeline_scenes": timeline_scenes,
        "number_design": number_design,
        "visual_steps": _string_list(raw.get("visual_steps"), fallback["visual_steps"], max_items=5, max_len=180),
        "controls": _normalize_controls(raw.get("controls"), fallback["controls"]),
        "formulas": formulas,
        "primary_color": _safe_str(raw.get("primary_color")) or primary_color,
    }


def _default_plan(topic: str, primary_color: str = DEFAULT_PRIMARY_COLOR) -> dict:
    subject = detect_subject(topic)
    mode = select_generation_mode(subject)
    animation_strategy = select_animation_strategy(subject)
    render_stack = select_render_stack(subject, topic)
    animation_runtime = select_animation_runtime(subject, topic, render_stack)

    if subject == "math":
        timeline_scenes = [
            {"id": "scene_intro", "label": "认识对象", "duration": 1.0, "focus": "核心图形居中出现，关键变量依次点亮", "caption": "先观察图形中的关键变量。"},
            {"id": "scene_change", "label": "变量变化", "duration": 1.2, "focus": "拖动主要变量时图形与数值同步变化", "caption": "变量变化会直接影响图形和公式结果。"},
            {"id": "scene_formula", "label": "公式验证", "duration": 1.0, "focus": "公式区替换默认数值并高亮结论", "caption": "把数值代入公式，验证图形和计算结果一致。"},
        ]
        return {
            "subject": subject,
            "mode": mode,
            "animation_strategy": animation_strategy,
            "render_stack": render_stack,
            "animation_runtime": animation_runtime,
            "title": f"{topic}互动动画",
            "goal": f'通过交互式图形和公式同步更新，理解"{topic}"的核心数学关系。',
            "stage_layout": "顶部展示学习目标导航，中间用大比例 SVG 舞台呈现核心图形，底部集中放置参数滑块、播放按钮和公式结论，整体单屏无滚动。",
            "storyboard": [
                "镜头1：核心图形居中放大，关键点、边、角或坐标轴依次点亮",
                "镜头2：主变量变化时图形平滑变形，相关数值贴近对象同步更新",
                "镜头3：公式区同步替换数值并高亮等式两侧，学生看到图形与代数一致",
            ],
            "timeline_scenes": timeline_scenes,
            "number_design": _default_number_design(topic, subject),
            "visual_steps": [
                "第1步：展示核心图形，标注关键变量（颜色区分），数值同步显示在图形旁",
                "第2步：拖动主要变量滑块，图形平滑变化，相关公式实时更新，观察数量关系",
                "第3步：播放完整变化过程，关键节点高亮并显示文字说明",
                "第4步：验证结论——调节不同参数组合，确认核心规律始终成立",
            ],
            "controls": [
                {"id": "variable-slider", "label": "主要变量", "type": "slider"},
                {"id": "play-btn", "label": "播放演示", "type": "button"},
                {"id": "speed-control", "label": "速度", "type": "speed"},
            ],
            "formulas": [topic],
            "primary_color": primary_color,
        }

    if subject in ("chemistry", "biology"):
        timeline_scenes = [
            {"id": "scene_initial", "label": "初始状态", "duration": 1.0, "focus": "初始结构或反应物居中展示", "caption": "先确认过程开始前有哪些关键组成。"},
            {"id": "scene_process", "label": "阶段变化", "duration": 1.4, "focus": "当前阶段元素移动或高亮，解释文字同步出现", "caption": "观察当前阶段发生了什么变化。"},
            {"id": "scene_result", "label": "结果对照", "duration": 1.0, "focus": "最终状态与初始状态对比", "caption": "对比前后状态，总结关键规律。"},
        ]
        return {
            "subject": subject,
            "mode": mode,
            "animation_strategy": "step_by_step",
            "render_stack": render_stack,
            "animation_runtime": animation_runtime,
            "title": f"{topic}过程动画",
            "goal": f'通过分步动画清晰展示"{topic}"的完整过程，理解每个阶段的变化与原因。',
            "stage_layout": "顶部用阶段导航说明流程，中间用 DOM/SVG 大舞台展示过程节点，右侧或底部显示当前阶段解释和关键变化，整体单屏无滚动。",
            "storyboard": [
                "镜头1：初始结构或反应物放大展示，关键组成部分用颜色分组",
                "镜头2：当前阶段元素沿路径移动或变形，非当前元素淡化，解释文字同步出现",
                "镜头3：最终状态与初始状态并排对照，高亮发生变化的结构或数量",
            ],
            "timeline_scenes": timeline_scenes,
            "number_design": _default_number_design(topic, subject),
            "visual_steps": [
                "第1步：展示初始状态，标注各个关键组成部分",
                "第2步：动画展示第一阶段变化，当前变化部分高亮，显示步骤说明",
                "第3步：连续展示中间过程，平滑过渡，每步骤有文字说明",
                "第4步：展示最终状态，对比初始与最终的变化，总结规律",
            ],
            "controls": [
                {"id": "step-btn", "label": "下一步", "type": "button"},
                {"id": "replay-btn", "label": "演示一次", "type": "button"},
                {"id": "speed-control", "label": "速度", "type": "speed"},
            ],
            "formulas": [],
            "primary_color": primary_color,
        }

    return {
        "subject": subject,
        "mode": mode,
        "animation_strategy": animation_strategy,
        "render_stack": render_stack,
        "animation_runtime": animation_runtime,
        "title": f"{topic}互动动画",
        "goal": f'通过直观动画演示，帮助学生理解"{topic}"的核心过程和关键规律。',
        "stage_layout": "顶部展示学习目标，中央保留大面积动画舞台，底部紧凑控制条负责播放、重置、速度和主要参数，公式或结论固定在舞台下方，整体单屏无滚动。",
        "storyboard": [
            "镜头1：初始场景居中出现，核心对象和变量依次标注",
            "镜头2：播放核心变化过程，运动对象留下轨迹或状态残影，当前结论同步显示",
            "镜头3：调节参数后重新播放，对比不同情境下的结果差异",
        ],
        "timeline_scenes": [
            {"id": "scene_intro", "label": "初始观察", "duration": 1.0, "focus": "核心对象和变量依次标注", "caption": "先观察场景中的核心对象。"},
            {"id": "scene_motion", "label": "过程变化", "duration": 1.3, "focus": "播放主要变化过程并显示轨迹或阶段", "caption": "观察变化过程中哪些量在改变。"},
            {"id": "scene_compare", "label": "参数对比", "duration": 1.0, "focus": "调节参数后对比结果差异", "caption": "换一组参数，比较结果有什么不同。"},
        ],
        "number_design": _default_number_design(topic, subject),
        "visual_steps": [
            "第1步：展示主题相关的初始场景，标注核心要素",
            "第2步：动画演示核心变化过程，平滑过渡，关键部分彩色高亮",
            "第3步：通过参数控件观察不同情境下的结果变化",
            "第4步：展示总结页面，回顾核心规律",
        ],
        "controls": [
            {"id": "play-btn", "label": "播放演示", "type": "button"},
            {"id": "speed-control", "label": "速度", "type": "speed"},
            {"id": "reset-button", "label": "重置", "type": "button"},
        ],
        "formulas": [],
        "primary_color": primary_color,
    }


def _normalize_controls(raw_controls: object, default: list[dict]) -> list[dict]:
    source = raw_controls if isinstance(raw_controls, list) and raw_controls else default
    controls: list[dict] = []
    seen: set[str] = set()
    for item in source[:4]:
        if not isinstance(item, dict):
            continue
        control_id = re.sub(r"[^a-zA-Z0-9_-]+", "-", _safe_str(item.get("id")).lower()).strip("-")
        label = _safe_str(item.get("label"))
        control_type = _safe_str(item.get("type")).lower()
        if not control_id or control_id in seen or control_type not in {"slider", "button", "speed"}:
            continue
        seen.add(control_id)
        controls.append({"id": control_id[:40], "label": label[:24] or control_id, "type": control_type})
    return controls or list(default)


def _normalize_timeline_scenes(raw_scenes: object, storyboard: list[str], default: list[dict]) -> list[dict]:
    source = raw_scenes if isinstance(raw_scenes, list) and raw_scenes else default
    scenes: list[dict] = []
    seen: set[str] = set()
    for index, item in enumerate(source[:6]):
        if not isinstance(item, dict):
            continue
        raw_id = _safe_str(item.get("id")) or f"scene_{index + 1}"
        scene_id = re.sub(r"[^a-zA-Z0-9_-]+", "-", raw_id.lower()).strip("-") or f"scene_{index + 1}"
        if scene_id in seen:
            scene_id = f"{scene_id}-{index + 1}"
        seen.add(scene_id)
        duration = _safe_duration(item.get("duration"))
        fallback_text = storyboard[index] if index < len(storyboard) else f"第{index + 1}幕：观察核心变化"
        label = _safe_str(item.get("label")) or f"第{index + 1}幕"
        focus = _safe_str(item.get("focus")) or fallback_text
        caption = _safe_str(item.get("caption")) or fallback_text
        scenes.append(
            {
                "id": scene_id[:48],
                "label": label[:32],
                "duration": duration,
                "focus": focus[:120],
                "caption": caption[:120],
            }
        )

    if scenes:
        return scenes

    return [
        {
            "id": f"scene_{index + 1}",
            "label": f"第{index + 1}幕",
            "duration": 1.0,
            "focus": shot[:120],
            "caption": shot[:120],
        }
        for index, shot in enumerate(storyboard[:5])
    ]


def _normalize_number_design(raw_design: object, default: dict) -> dict:
    source = raw_design if isinstance(raw_design, dict) else default
    default_values = _string_list(source.get("default_values"), default.get("default_values", []), max_items=6, max_len=40)
    reason = _safe_str(source.get("reason")) or _safe_str(default.get("reason"))
    return {
        "default_values": default_values,
        "reason": reason[:160] if reason else None,
    }


def _default_number_design(topic: str, subject: str) -> dict:
    topic_lower = topic.lower()
    if "勾股" in topic or "直角三角" in topic:
        return {
            "default_values": ["a = 3", "b = 4", "c = 5"],
            "reason": "使用学生熟悉且可心算的 3-4-5 勾股数组，便于直接验证 a² + b² = c²。",
        }
    if any(keyword in topic for keyword in ("平行四边形", "面积", "长方形", "三角形面积")):
        return {
            "default_values": ["底 = 6", "高 = 4", "面积 = 24"],
            "reason": "使用一位整数和可心算结果，学生能快速把图形面积与乘法关系对应起来。",
        }
    if any(keyword in topic for keyword in ("一次函数", "线性函数", "函数")):
        return {
            "default_values": ["k = 2", "b = 1", "x = 3", "y = 7"],
            "reason": "使用简单斜率、截距和整数点，便于学生心算验证函数图像与代数表达。",
        }
    if subject == "physics":
        return {
            "default_values": ["时间 = 1s", "速度 = 2m/s", "质量 = 1kg"],
            "reason": "使用常见单位和小整数，降低单位换算成本，让学生专注观察物理关系。",
        }
    if subject in {"chemistry", "biology"} or any(keyword in topic_lower for keyword in ("分子", "粒子", "样本")):
        return {
            "default_values": ["样本数 = 20", "速度 = 1x", "阶段 = 3"],
            "reason": "使用适中的样本数和标准速度，既能看到整体趋势，也不会让画面过于拥挤。",
        }
    return {
        "default_values": ["速度 = 1x", "步骤 = 3", "重点变量 = 默认值"],
        "reason": "使用默认速度、三段式步骤和一个核心变量，便于学生从初始状态逐步观察到结论。",
    }


def _safe_duration(value: object) -> float:
    try:
        duration = float(value)
    except (TypeError, ValueError):
        duration = 1.0
    return min(max(duration, 0.2), 8.0)


def _string_list(value: object, default: list[str], max_items: int, max_len: int = 60) -> list[str]:
    if not isinstance(value, list):
        return list(default[:max_items])
    items = [str(item).strip()[:max_len] for item in value if str(item).strip()]
    return items[:max_items] or list(default[:max_items])


def _safe_str(value: object) -> str:
    return str(value).strip() if value is not None else ""
