"""Fallback planning logic for AetherViz v5.2."""

from __future__ import annotations

import json
import re
from copy import deepcopy

DEFAULT_PRIMARY_COLOR = "#22D3EE"

PLANNING_SYSTEM_PROMPT_TEMPLATE = """你是 AetherViz Master 5.2 互动教育可视化规划师。
根据用户教学主题，输出一个 JSON 规划，用于指导后续完整独立 HTML 教学页面生成。
只输出 JSON 对象，不含 Markdown 标记、代码块或任何解释文字。

必须遵守：
- 先识别学科、实验类型、渲染路由、交互目标，再规划页面。
- 不要所有主题默认 Three.js；数学函数、几何、统计、算法流程优先 SVG/D3/DOM。
- 单屏只突出 1 个主要结论，重点变量不超过 3 个。
- 所有变量必须使用学生容易感知、便于课堂比较的数值，并写清单位、默认值、范围、推荐值和课堂提示。
- 教师应能在 3 分钟内按计划演示完整规律。
- 生成 HTML 时必须使用统一 Animation Runtime、固定时间步、resize 管线、错误兜底与性能预算。

字段约束：
- subject：math / physics / chemistry / biology / astronomy / programming / geography / chinese / english / general
- experiment_type：简短中文实验类型，如“力学参数实验”“函数图像探究”
- render_stack：对象，包含 subject、mode、main、auxiliary
- main_renderer：svg / three / canvas / hybrid / dom
- learning_objectives：3~4 条简短中文学习目标
- core_concepts：1~4 条核心概念或公式
- teacher_demo_flow：按“生活类比 → 可观察现象 → 简单公式 → 交互验证 → 一句话小结”给出 4~5 步
- key_variables：最多 3 个变量，每个含 name、unit、default、min、max、recommended、classroom_tip、meaning
- performance_budget：对象，含 pixel_ratio_max、mobile_pixel_ratio_max、dynamic_svg_nodes_max、particles_desktop_max、particles_mobile_max、trajectory_points_max
- self_check_items：5~8 条生成前自检项
- primary_color：主色
- interaction_type：param_explorer / step_reveal / tab_compare / clickable_diagram / quiz / number_visual / general
- interaction_hint：1~2 句话说明交互控件和视觉变化

学科专属指导方针：
{subject_guide}

输出 JSON 示例：
{{
  "subject": "physics",
  "experiment_type": "力学参数实验",
  "render_stack": {{"subject": "physics", "mode": "three-physics-svg", "main": "three", "auxiliary": ["svg-hud", "katex"]}},
  "main_renderer": "three",
  "learning_objectives": ["理解力与加速度的关系", "观察质量变化对运动的影响", "用数值解释 F=ma"],
  "core_concepts": ["F=ma", "质量越大，同样的力越难改变运动"],
  "teacher_demo_flow": ["先用推购物车类比力和质量", "观察箭头变长时小车加速更明显", "用 F=ma 计算当前加速度", "拖动质量和力验证规律", "小结：同样质量下力越大加速度越大"],
  "key_variables": [
    {{"name": "质量", "unit": "kg", "default": 2, "min": 1, "max": 10, "recommended": 2, "classroom_tip": "质量越大，同样的力越难推动", "meaning": "演示中 1 格约等于 1 米"}}
  ],
  "performance_budget": {{"pixel_ratio_max": 2, "mobile_pixel_ratio_max": 1.5, "dynamic_svg_nodes_max": 300, "particles_desktop_max": 3000, "particles_mobile_max": 1200, "trajectory_points_max": 300}},
  "self_check_items": ["首屏主渲染区非空", "按钮和滑块有效"],
  "primary_color": "#22D3EE",
  "interaction_type": "param_explorer",
  "interaction_hint": "提供力和质量滑块，实时更新加速度数值、运动轨迹和受力箭头。"
}}
"""

SUBJECT_PROMPT_GUIDES = {
    "math": "数学分支：优先 SVG/D3/KaTeX。强调坐标轴、函数曲线、几何拖拽、面积或参数变化，数值范围便于读图和心算。",
    "physics": "物理分支：力学/运动学可用 Three.js + SVG HUD，波动/流场可用 Canvas 或 Points。必须标注力、速度、加速度等向量和单位。",
    "chemistry": "化学分支：分子结构可用 Three.js 球棍模型，反应过程优先 SVG 流程 + 粒子示意。数值使用浓度、温度、粒子示意数量。",
    "biology": "生物分支：结构类可用半透明 Three.js 或 SVG 标签，过程类优先时间轴和阶段动画。强调比例、阶段和学生可理解说明。",
    "astronomy": "天文分支：可用 Three.js 轨道系统和粒子星空。必须说明缩放模型，不展示难以感知的真实天文数量级。",
    "programming": "编程/系统分支：优先 SVG 状态机、流程图和代码面板。节点数量、数组长度和递归深度要便于逐步演示。",
    "geography": "地理分支：可用 SVG/D3/Canvas 表达空间模型、流向、分层和时间演变；避免过多 3D 复杂地形。",
    "chinese": "语文分支：优先 DOM/SVG 结构拆解、人物关系、意象时间线和文本高亮，不强行 3D。",
    "english": "英语分支：优先 DOM/SVG 句法树、情境对话和时态时间轴。",
    "general": "通用：使用清晰结构和可观察交互解释概念，默认 SVG/DOM 为主，必要时补充 Canvas。"
}

SUBJECT_KEYWORDS = {
    "math": ["数学", "几何", "证明", "三角", "函数", "代数", "方程", "概率", "统计", "分布", "向量", "矩阵", "微积分", "极限", "面积", "体积", "导数", "积分", "勾股", "坐标", "解析几何"],
    "programming": ["算法", "排序", "递归", "树", "图", "状态机", "队列", "栈", "复杂度", "网络", "数据库", "编程", "代码", "tcp"],
    "chemistry": ["化学", "反应", "元素", "分子", "原子", "周期表", "离子", "酸", "碱", "盐", "氧化", "还原", "溶液", "溶解度", "实验", "烧杯", "试管", "化合", "分解", "晶体"],
    "biology": ["生物", "细胞", "基因", "dna", "蛋白质", "进化", "染色体", "光合", "呼吸", "植物", "动物", "器官", "生命", "生态", "生理", "遗传", "复制", "神经"],
    "astronomy": ["天文", "行星", "恒星", "黑洞", "宇宙", "日食", "月食", "引力", "星系", "轨道"],
    "physics": ["物理", "力", "运动", "碰撞", "弹簧", "轨道", "速度", "加速度", "动量", "能量", "重力", "摩擦", "浮力", "电阻", "电流", "电压", "光", "透镜", "简谐", "波动", "热学", "磁场", "电场", "惯性", "力学", "光学", "电磁"],
    "geography": ["地理", "大气", "地球", "自转", "公转", "经纬", "板块", "地震", "地形", "气候", "水文", "洋流", "人口", "城市化", "地质", "风带", "气压"],
    "chinese": ["语文", "诗词", "诗歌", "文言", "古文", "现代文", "修辞", "比喻", "拟人", "散文", "小说", "汉字", "拼音", "阅读理解", "作文", "琵琶行", "出师表", "灰雀"],
    "english": ["英语", "english", "语法", "句型", "词汇", "单词", "时态", "从句", "阅读", "口语", "写作", "dictation", "grammar", "tense", "vocabulary"],
}

VALID_INTERACTION_TYPES = {
    "param_explorer", "step_reveal", "tab_compare", "clickable_diagram", "quiz", "number_visual", "general"
}

DEFAULT_PERFORMANCE_BUDGET = {
    "pixel_ratio_max": 2,
    "mobile_pixel_ratio_max": 1.5,
    "dynamic_svg_nodes_max": 300,
    "particles_desktop_max": 3000,
    "particles_mobile_max": 1200,
    "trajectory_points_max": 300,
}

DEFAULT_SELF_CHECK_ITEMS = [
    "首屏主渲染区非空",
    "播放、暂停、单步、重置和随机实验按钮有效",
    "恢复课堂推荐值按钮有效",
    "resize 后画面和标注不错位",
    "移动端控制面板不遮挡主动画",
    "默认数值容易心算且范围不过宽",
    "动画循环中不创建大量 DOM、Geometry、Material 或 Texture",
]


def detect_subject(topic: str) -> str:
    if not topic:
        return "general"
    topic_lower = topic.lower()
    subject_order = [
        "math",
        "programming",
        "chemistry",
        "biology",
        "astronomy",
        "geography",
        "chinese",
        "english",
        "physics",
    ]
    for subject in subject_order:
        keywords = SUBJECT_KEYWORDS[subject]
        if any(keyword in topic_lower for keyword in keywords):
            return subject
    return "general"


def select_render_stack(topic: str) -> dict:
    subject = detect_subject(topic)
    topic_lower = topic.lower()
    if subject == "math":
        return {"subject": subject, "mode": "svg-d3-katex", "main": "svg", "auxiliary": ["katex", "dom-controls"]}
    if subject == "programming":
        return {"subject": subject, "mode": "svg-state-canvas", "main": "svg", "auxiliary": ["canvas", "code-panel"]}
    if subject == "chemistry":
        reaction_words = ["反应", "酸碱", "氧化", "还原", "速率", "溶液"]
        if any(word in topic_lower for word in reaction_words):
            return {"subject": subject, "mode": "svg-reaction-canvas", "main": "svg", "auxiliary": ["canvas-particles", "katex"]}
        return {"subject": subject, "mode": "three-molecule-svg", "main": "three", "auxiliary": ["svg-labels", "katex"]}
    if subject == "biology":
        process_words = ["复制", "光合作用", "呼吸", "循环", "分裂", "遗传"]
        main = "svg" if any(word in topic_lower for word in process_words) else "three"
        return {"subject": subject, "mode": "bio-hybrid", "main": main, "auxiliary": ["svg-labels", "timeline", "katex"]}
    if subject == "astronomy":
        return {"subject": subject, "mode": "three-orbit-particles", "main": "three", "auxiliary": ["particles", "svg-data"]}
    if subject == "physics":
        if any(word in topic_lower for word in ["波", "电场", "磁场", "流场"]):
            return {"subject": subject, "mode": "canvas-or-points-field", "main": "canvas", "auxiliary": ["svg-field-lines", "katex"]}
        return {"subject": subject, "mode": "three-physics-svg", "main": "three", "auxiliary": ["svg-hud", "katex"]}
    if subject in {"chinese", "english"}:
        return {"subject": subject, "mode": "dom-svg-reading", "main": "dom", "auxiliary": ["svg-links", "text-highlight"]}
    if subject == "geography":
        return {"subject": subject, "mode": "svg-d3-canvas-map", "main": "svg", "auxiliary": ["canvas-flow", "dom-panel"]}
    return {"subject": "general", "mode": "hybrid-basic", "main": "svg", "auxiliary": ["dom-controls", "katex"]}


def detect_experiment_type(topic: str, subject: str) -> str:
    topic_lower = topic.lower()
    if subject == "physics":
        if any(word in topic_lower for word in ["波", "电场", "磁场"]):
            return "波动与场可视化"
        return "力学参数实验"
    if subject == "math":
        if any(word in topic_lower for word in ["几何", "证明", "勾股"]):
            return "几何证明实验"
        return "函数与数形结合实验"
    if subject == "chemistry":
        return "微观反应过程实验" if "反应" in topic_lower else "分子结构观察实验"
    if subject == "biology":
        return "生命过程阶段演示" if any(word in topic_lower for word in ["复制", "光合", "呼吸", "分裂"]) else "生物结构标注实验"
    if subject == "astronomy":
        return "缩放轨道模型实验"
    if subject == "programming":
        return "算法状态演示"
    return "综合互动教学演示"


def build_planning_prompt(topic: str, primary_color: str) -> tuple[str, str]:
    subject = detect_subject(topic)
    subject_guide = SUBJECT_PROMPT_GUIDES.get(subject, SUBJECT_PROMPT_GUIDES["general"])
    render_stack = select_render_stack(topic)
    system_prompt = PLANNING_SYSTEM_PROMPT_TEMPLATE.format(subject_guide=subject_guide)
    user_prompt = f"""请针对教学主题：“{topic}” 进行 AetherViz 5.2 可视化页面规划。
主色调为：{primary_color}。
服务端初步学科识别：{subject}。
服务端初步渲染路由：{json.dumps(render_stack, ensure_ascii=False)}。

请输出完整 JSON，必须包含 subject、experiment_type、render_stack、main_renderer、learning_objectives、core_concepts、teacher_demo_flow、key_variables、performance_budget、self_check_items、primary_color、interaction_type、interaction_hint。
"""
    return system_prompt, user_prompt


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

    subject = _safe_str(raw.get("subject")) or fallback["subject"]
    if subject not in SUBJECT_PROMPT_GUIDES:
        subject = detect_subject(topic)

    render_stack = raw.get("render_stack")
    if not isinstance(render_stack, dict):
        render_stack = select_render_stack(topic)
    else:
        base_stack = select_render_stack(topic)
        render_stack = {
            "subject": _safe_str(render_stack.get("subject")) or subject,
            "mode": _safe_str(render_stack.get("mode")) or base_stack["mode"],
            "main": _safe_str(render_stack.get("main")) or base_stack["main"],
            "auxiliary": _string_list(render_stack.get("auxiliary"), base_stack["auxiliary"], max_items=4),
        }

    objectives = _string_list(raw.get("learning_objectives"), fallback["learning_objectives"], max_items=4, max_len=40)
    concepts = _string_list(raw.get("core_concepts"), fallback["core_concepts"], max_items=4, max_len=80)
    demo_flow = _string_list(raw.get("teacher_demo_flow"), fallback["teacher_demo_flow"], max_items=5, max_len=80)
    self_check = _string_list(raw.get("self_check_items"), DEFAULT_SELF_CHECK_ITEMS, max_items=8, max_len=80)

    interaction_type = _safe_str(raw.get("interaction_type")).lower() or fallback["interaction_type"]
    if interaction_type not in VALID_INTERACTION_TYPES:
        interaction_type = fallback["interaction_type"]

    performance_budget = deepcopy(DEFAULT_PERFORMANCE_BUDGET)
    if isinstance(raw.get("performance_budget"), dict):
        for key, default_value in DEFAULT_PERFORMANCE_BUDGET.items():
            performance_budget[key] = _number(raw["performance_budget"].get(key), default_value)

    variables = _normalize_variables(raw.get("key_variables"), subject)

    return {
        "subject": subject,
        "experiment_type": _safe_str(raw.get("experiment_type")) or fallback["experiment_type"],
        "render_stack": render_stack,
        "main_renderer": _safe_str(raw.get("main_renderer")) or render_stack["main"],
        "learning_objectives": objectives,
        "core_concepts": concepts,
        "teacher_demo_flow": demo_flow,
        "key_variables": variables,
        "performance_budget": performance_budget,
        "self_check_items": self_check,
        "primary_color": _safe_str(raw.get("primary_color")) or primary_color,
        "interaction_type": interaction_type,
        "interaction_hint": (_safe_str(raw.get("interaction_hint")) or fallback["interaction_hint"])[:240],
    }


def _default_plan(topic: str, primary_color: str = DEFAULT_PRIMARY_COLOR) -> dict:
    subject = detect_subject(topic)
    render_stack = select_render_stack(topic)
    experiment_type = detect_experiment_type(topic, subject)
    return {
        "subject": subject,
        "experiment_type": experiment_type,
        "render_stack": render_stack,
        "main_renderer": render_stack["main"],
        "learning_objectives": [
            f"理解{topic}的核心现象",
            "观察关键变量变化带来的结果",
            "用简单数值解释课堂规律",
        ],
        "core_concepts": [topic],
        "teacher_demo_flow": [
            "先用生活类比引入主题",
            "观察默认画面中的核心现象",
            "给出最关键的公式或概念",
            "拖动变量验证变化规律",
            "用一句话总结本节结论",
        ],
        "key_variables": _normalize_variables(None, subject),
        "performance_budget": deepcopy(DEFAULT_PERFORMANCE_BUDGET),
        "self_check_items": list(DEFAULT_SELF_CHECK_ITEMS),
        "primary_color": primary_color,
        "interaction_type": "param_explorer" if subject in {"physics", "math", "chemistry"} else "general",
        "interaction_hint": f"设计一个直观、美观且交互丰富的 HTML 教学页面，直观呈现关于“{topic}”的核心概念和变化规律。",
    }


def _normalize_variables(raw_variables: object, subject: str) -> list[dict]:
    source = raw_variables if isinstance(raw_variables, list) and raw_variables else _default_variables(subject)
    variables: list[dict] = []
    for item in source[:3]:
        if not isinstance(item, dict):
            continue
        name = _safe_str(item.get("name"))
        if not name:
            continue
        variables.append({
            "name": name[:24],
            "unit": _safe_str(item.get("unit"))[:16],
            "default": item.get("default", item.get("recommended", "")),
            "min": item.get("min"),
            "max": item.get("max"),
            "recommended": item.get("recommended", item.get("default", "")),
            "classroom_tip": (_safe_str(item.get("classroom_tip")) or "调整后观察画面和数值如何变化。")[:80],
            "meaning": (_safe_str(item.get("meaning")) or "使用课堂演示缩放模型，便于观察规律。")[:80],
        })
    return variables or _default_variables("general")


def _default_variables(subject: str) -> list[dict]:
    defaults = {
        "physics": [
            {"name": "质量", "unit": "kg", "default": 2, "min": 1, "max": 10, "recommended": 2, "classroom_tip": "质量越大，同样的力越难推动。", "meaning": "演示中 1 格约等于 1 米。"},
            {"name": "作用力", "unit": "N", "default": 10, "min": 1, "max": 50, "recommended": 10, "classroom_tip": "力越大，速度变化越明显。", "meaning": "箭头长度表示力的相对大小。"},
        ],
        "math": [
            {"name": "参数 a", "unit": "", "default": 1, "min": -5, "max": 5, "recommended": 1, "classroom_tip": "观察曲线随参数改变的形状。", "meaning": "坐标范围控制在 -10 到 10，便于读图。"},
            {"name": "角度", "unit": "°", "default": 45, "min": 0, "max": 90, "recommended": 45, "classroom_tip": "使用常见角便于心算和比较。", "meaning": "角度变化用于观察几何或函数关系。"},
        ],
        "chemistry": [
            {"name": "浓度", "unit": "mol/L", "default": 1, "min": 0.1, "max": 2, "recommended": 1, "classroom_tip": "浓度越高，粒子碰撞机会越多。", "meaning": "粒子数量是示意值，不代表真实微观数量。"},
            {"name": "温度", "unit": "°C", "default": 25, "min": 20, "max": 80, "recommended": 25, "classroom_tip": "温度升高通常会让反应更快。", "meaning": "用课堂可见速度表达趋势。"},
        ],
        "biology": [
            {"name": "阶段", "unit": "步", "default": 1, "min": 1, "max": 5, "recommended": 1, "classroom_tip": "逐步观察生命过程的关键变化。", "meaning": "阶段编号用于降低认知负荷。"},
            {"name": "完成比例", "unit": "%", "default": 50, "min": 0, "max": 100, "recommended": 50, "classroom_tip": "比例越高，过程越接近完成。", "meaning": "比例是示意值，强调趋势。"},
        ],
        "programming": [
            {"name": "数组长度", "unit": "项", "default": 8, "min": 6, "max": 12, "recommended": 8, "classroom_tip": "项目越少，越适合逐步跟踪。", "meaning": "节点数控制在学生可人工推演范围内。"},
            {"name": "速度", "unit": "倍", "default": 1, "min": 0.5, "max": 2, "recommended": 1, "classroom_tip": "慢速适合讲解每一步状态。", "meaning": "速度只影响演示节奏。"},
        ],
    }
    return deepcopy(defaults.get(subject, [
        {"name": "进度", "unit": "%", "default": 50, "min": 0, "max": 100, "recommended": 50, "classroom_tip": "拖动进度观察关键状态变化。", "meaning": "使用示意进度表达抽象过程。"}
    ]))


def _string_list(value: object, default: list[str], max_items: int, max_len: int = 60) -> list[str]:
    if not isinstance(value, list):
        return list(default[:max_items])
    items = [str(item).strip()[:max_len] for item in value if str(item).strip()]
    return items[:max_items] or list(default[:max_items])


def _safe_str(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _number(value: object, default: int | float) -> int | float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return int(parsed) if isinstance(default, int) else parsed
