"""Subject, interaction type, and render-stack selection for lesson plans."""

from __future__ import annotations

SUBJECT_KEYWORDS = {
    "math": [
        "数学",
        "几何",
        "函数",
        "方程",
        "概率",
        "统计",
        "面积",
        "体积",
        "坐标",
        "圆",
        "抛物线",
        "定理",
        "证明",
        "公式",
        "导数",
        "极限",
        "积分",
        "向量",
        "矩阵",
        "数列",
        "集合",
        "逻辑",
        "不等式",
        "三角",
        "排列",
        "组合",
    ],
    "physics": ["物理", "运动", "速度", "加速度", "力", "能量", "电流", "电压", "波", "光", "抛体"],
    "chemistry": ["化学", "反应", "分子", "原子", "离子", "酸", "碱", "盐", "溶液", "反应速率"],
    "biology": ["生物", "细胞", "基因", "dna", "蛋白质", "光合", "呼吸", "生态", "遗传"],
    "programming": ["算法", "排序", "递归", "树", "图", "状态机", "队列", "栈", "复杂度"],
    "geography": ["地理", "大气", "地球", "经纬", "板块", "地震", "地形", "气候", "水文"],
    "chinese": ["语文", "诗词", "文言", "古文", "修辞", "散文", "小说", "阅读结构"],
    "english": ["英语", "english", "语法", "句型", "词汇", "时态", "从句", "grammar"],
}

VALID_INTERACTIVE_TYPES = {"simulation", "diagram", "game"}
VALID_RENDER_STACKS = {"svg", "svg_canvas", "canvas_svg", "dom_svg"}
VALID_ANIMATION_RUNTIMES = {"gsap"}

SIMULATION_KEYWORDS = ["运动", "参数", "实验", "函数", "概率", "反应速率", "电路", "轨迹", "速度", "采样"]
DIAGRAM_KEYWORDS = ["流程", "结构", "分类", "因果", "步骤", "阅读结构", "知识图谱", "体系", "过程"]
GAME_KEYWORDS = ["练习", "闯关", "匹配", "排序", "挑战", "小游戏", "巩固", "得分"]

PLANNING_SYSTEM_PROMPT_TEMPLATE = """你是互动教学课件规划器，为 12~18 岁学生设计单页 interactive widget。

仅输出一个合法 JSON 对象，不输出 Markdown、解释、推理过程或未定义字段。
只生成用户可读的教学计划字段；机器 IR 规格（representation_spec、recomposition_spec、discipline_spec、runtime、widget_*、scene_outline、subject、knowledge_profile、page_type、widget_type、primary_color）由服务端在确认阶段编译，不要输出这些字段。

JSON 顶层字段必须且只能包含：
- interactive_type：固定为 {interactive_type}
- title：不超过 24 个汉字
- goal：一个可观察、可验证的学习目标
- learner_level：简短学段
- stage_layout：字符串，说明目标区、主舞台、控制区和结论区的相对位置及空间不足时的堆叠/折叠方式；主舞台优先，公式、读数和控制面板不得覆盖或挤压主舞台；不要指定固定像素宽高
- key_points：2~4 个字符串
- design_brief：只含 layout、stage_objects、visual_rules、state_updates、default_preset、acceptance
- interactive_spec：严格使用下方 {interactive_type} 规格
- teaching_flow：3~4 项，每项只含 id、label、focus、caption
- controls：只生成 1~2 个真实影响学习的控件，每项只含 id、label、type、bind；不要生成播放、暂停、重置按钮
- formulas：0~3 个字符串

一致性要求：
- 产品默认面向中国市场：title、goal、key_points、design_brief、interactive_spec 中的学生可见说明、teaching_flow、controls.label 必须使用简体中文；数学公式、化学式、物理量、变量 id/name、坐标轴、点名、国际单位和确有教学必要的外语原文可以保留。必须展示外语术语时，首次出现采用“中文（原文）”。
- controls[].bind 必须等于 interactive_spec 中一个可调变量 name；无可调变量时 controls 输出空数组。
- preset 的每个值必须落在对应变量 min/max 范围内。
- 所有 id 使用小写英文、数字、连字符或下划线，引用必须存在。
- design_brief 必须明确主舞台对象、相对位置、颜色语义、动态更新、默认状态和验收标准。
- design_brief.visual_rules 必须区分浅色教学工作台 UI 与学科图形语义色：UI 保持白色/灰绿纸张感和绿色交互强调，饱和色只用于数据对象、关键节点、游戏反馈或当前状态；不得规划整页深色霓虹面板或卡片墙。
- 若 interactive_spec 含连续几何参数（长度、角度、半径等），min/max 必须保持课堂可读跨度：当 min>0 时 max/min 建议不超过 6；离散计数控件使用整数边界、整数默认值且 step>=1。
- teaching_flow 与 observations 应写清学生如何观察、调节和归纳，便于后续机器规格编译，但不直接描述 IR、后端名称、坐标或 SVG。

{type_contract}
"""
INTERACTIVE_TYPE_CONTRACTS = {
    "simulation": """simulation 的 interactive_spec 只含：
- type：固定 simulation
- concept、description
- variables：1~3 项；每项包含 name、label、min、max、step、default、unit，可额外包含 computed、expression
- presets：1~3 项；每项使用 id、label、values，values 的 key 必须引用 variables.name
- observations：2~4 个可观察现象""",
    "diagram": """diagram 的 interactive_spec 只含：
- type：固定 diagram
- concept、description
- nodes：3~7 项，每项只含 id、label、details、explanation
- edges：每项只含 from、to，可选 label；from/to 必须引用 nodes.id
- reveal_order：按揭示顺序列出全部 nodes.id""",
    "game": """game 的 interactive_spec 只含：
- type：固定 game
- concept、description、game_type、challenge、success_condition
- feedback_rules：2~4 个字符串
- game_config：操作型挑战配置，必须包含 controls、fair_start、levels；不得退化为普通选择题堆叠""",
}


def detect_subject(topic: str) -> str:
    text = (topic or "").lower()
    scores = {
        subject: sum(1 for keyword in keywords if keyword in text) for subject, keywords in SUBJECT_KEYWORDS.items()
    }
    best_score = max(scores.values(), default=0)
    if best_score:
        return max(scores, key=scores.get)
    return "general"


def select_interactive_type(topic: str, subject: str) -> str:
    text = (topic or "").lower()
    if any(keyword in text for keyword in GAME_KEYWORDS):
        return "game"
    if any(keyword in text for keyword in DIAGRAM_KEYWORDS):
        return "diagram"
    if any(keyword in text for keyword in SIMULATION_KEYWORDS):
        return "simulation"
    if subject in {"chinese", "english", "geography", "programming"}:
        return "diagram"
    if subject in {"math", "physics", "chemistry", "biology"}:
        return "simulation"
    return "diagram"


def select_render_stack(interactive_type: str, subject: str, topic: str) -> str:
    text = (topic or "").lower()
    if interactive_type == "simulation" and any(
        keyword in text for keyword in ("粒子", "扩散", "轨迹", "运动", "波", "碰撞")
    ):
        return "svg_canvas"
    if interactive_type in {"game", "diagram"}:
        return "dom_svg"
    if subject == "math":
        return "svg"
    return "svg_canvas"


def select_animation_runtime() -> str:
    return "gsap"


def build_planning_prompt(
    topic: str,
    primary_color: str,
    *,
    interactive_type_override: str | None = None,
    subject_override: str | None = None,
) -> tuple[str, str]:
    from aetherviz_service.aetherviz.workflow.knowledge_profile import build_knowledge_profile

    subject = (
        subject_override if subject_override in {*SUBJECT_KEYWORDS, "astronomy", "general"} else detect_subject(topic)
    )
    interactive_type = (
        interactive_type_override
        if interactive_type_override in VALID_INTERACTIVE_TYPES
        else select_interactive_type(topic, subject)
    )
    knowledge_profile = build_knowledge_profile(topic, subject=subject)
    system_prompt = PLANNING_SYSTEM_PROMPT_TEMPLATE.format(
        interactive_type=interactive_type,
        type_contract=INTERACTIVE_TYPE_CONTRACTS[interactive_type],
    )
    user_prompt = f"""生成以下主题的教学计划 JSON（仅教学语义，不含机器 IR 规格）。

主题：{topic}
服务端学科识别（供参考，不要写入输出）：{subject}
固定互动类型：{interactive_type}
服务端知识画像先验（供参考，不要写入输出）：{knowledge_profile}
主色调（供参考，不要写入输出）：{primary_color}
"""
    return system_prompt, user_prompt

def select_revision_interactive_type(current_type: object, message: str, topic: str) -> str:
    text = (message or "").lower()
    for interactive_type, keywords in (
        ("game", GAME_KEYWORDS),
        ("diagram", DIAGRAM_KEYWORDS),
        ("simulation", SIMULATION_KEYWORDS),
    ):
        if any(keyword in text for keyword in keywords):
            return interactive_type
    current = str(current_type).strip() if current_type is not None else ""
    if current in VALID_INTERACTIVE_TYPES:
        return current
    subject = detect_subject(topic)
    return select_interactive_type(topic, subject)
