"""Fallback planning logic for AetherViz, including subject-specific prompts and fallback plan parser."""

from __future__ import annotations

import json
import re

PLANNING_SYSTEM_PROMPT_TEMPLATE = """你是资深的教学可视化规划师。
根据用户的教学主题，输出一个 JSON 规划，用于指导后续交互式 HTML 教学页面生成。
只输出 JSON 对象，不含 Markdown 标记、代码块或任何解释文字。

字段约束：
- learning_objectives：3~5 条简短中文学习目标（每条不超过 30 字）
- core_concepts：1~4 条核心概念或公式
- interaction_type：选择以下最适合该教学主题的交互类型之一：
  - "param_explorer"：参数探索器（提供滑块/输入，实时计算或改变图表/公式，适合物理公式、数学函数等）
  - "step_reveal"：分步揭示（点击"下一步"逐步展示推导、步骤、算法过程，适合数学方程求解、生物/化学步骤）
  - "tab_compare"：对比标签页（Tab 切换不同概念、对立观点，适合对比辨析、文科概念）
  - "clickable_diagram"：可点击图解（点击图中的不同部位/标记，展示详细结构说明，适合生物解剖、地理模型、仪器结构）
  - "quiz"：问答检测（选择题/填空题并提供即时智能反馈，适合知识巩固）
  - "number_visual"：数形结合（通过数学曲线、数轴或几何图形直观呈现抽象数据）
  - "general"：通用综合交互（自定义的综合教学交互）
- interaction_hint：1~2 句话的交互实现提示，规划应提供哪些具体的交互控件（如滑块、按钮、Tab）以及点击后页面产生何种视觉更新。

学科专属指导方针：
{subject_guide}

输出的 JSON 结构如下：
{{
  "learning_objectives": ["目标1", "目标2"],
  "core_concepts": ["公式/概念1", "公式/概念2"],
  "interaction_type": "param_explorer",
  "interaction_hint": "提示文字，如：提供力F和质量m两个滑块，实时计算并动态更新加速度a=F/m的变化过程。"
}}
"""

SUBJECT_PROMPT_GUIDES = {
    "math": "数学分支：强调“数形结合”与“抽象直观化”。必须规划直观的坐标系、函数曲线、数轴或几何图形。在场景描述中注重动态几何变化（如点在线上移动、面积随参数变化）。",
    "physics": "物理分支：强调“受力与运动”和“状态演变”。要求标注力、速度向量（使用箭头），强调物理量（如加速度、动能）随时间的动态走势，以及电路、光路、声波的直观传播。",
    "chemistry": "化学分支：强调“微观变化”和“实验装置”。必须描述微观分子/原子碰撞与化学键断裂与形成的动态过程，或清晰的烧杯、试管反应实验现象（如变色、气泡、沉淀）。",
    "biology": "生物分支：强调“结构剖面”与“生命流转”。必须描述细胞结构、器官解剖图、生态系统中的能量流动，或者像光合作用、DNA复制这类的动态生理代谢过程。",
    "geography": "地理分支：强调“空间模型”与“演变机制”。必须规划三维地形断面、地球公转/自转动画、气压带风带分布，或水循环、洋流移动等大尺度自然地理演变过程。",
    "chinese": "语文分支：强调“意境可视化”与“文本结构拆解”。可以规划出诗词所描绘的中国画意境（如孤舟蓑笠翁的画面演变），或把复杂的文章结构、人物关系、修辞对比用连线和卡片直观树状展示。",
    "english": "英语分支：强调“情境对话”与“语言逻辑图示”。必须规划典型的生活/对话场景，或者用句子结构树、时态时间轴来图解语法与词汇词义的区别。",
    "general": "通用分支：强调结构化的教学设计，使用清晰的布局和对立/对比动画来解释概念。通过动画过程，直观呈现抽象主题的内部机制。"
}


def detect_subject(topic: str) -> str:
    """从教学主题字符串中自动检测学科分类。
    
    通过关键词匹配的方式判断主题所属学科（数学、物理、化学、生物等），
    如果没有匹配到任何学科关键词，则返回 "general"（通用学科）。
    
    参数:
        topic: 教学主题字符串，如 "牛顿第二定律"、"二次函数" 等
        
    返回:
        学科标识符，如 "physics"、"math"、"chemistry"、"general" 等
    """
    if not topic:
        return "general"
    
    topic_lower = topic.lower()
    
    # 关键词映射表
    keywords_map = {
        "math": [
            "数学", "几何", "三角", "函数", "代数", "方程", "概率", "统计", "向量", "矩阵",
            "微积分", "极限", "面积", "体积", "导数", "勾股", "坐标", "解析几何"
        ],
        "biology": [
            "生物", "细胞", "基因", "dna", "蛋白质", "进化", "染色体", "光合", "呼吸",
            "植物", "动物", "器官", "生命", "生态", "生理", "遗传"
        ],
        "chemistry": [
            "化学", "反应", "元素", "分子", "原子", "周期表", "离子", "酸", "碱", "盐",
            "氧化", "还原", "溶液", "溶解度", "实验", "烧杯", "试管", "化合", "分解"
        ],
        "physics": [
            "物理", "力", "加速度", "速度", "重力", "摩擦", "浮力", "电阻", "电流", "电压",
            "光", "透镜", "简谐", "波动", "热学", "磁场", "惯性", "力学", "光学", "电磁"
        ],
        "geography": [
            "地理", "大气", "地球", "自转", "公转", "经纬", "板块", "地震", "地形", "气候",
            "水文", "洋流", "人口", "城市化", "地质", "风带", "气压"
        ],
        "chinese": [
            "语文", "诗词", "诗歌", "文言", "古文", "现代文", "修辞", "比喻", "拟人", "散文",
            "小说", "汉字", "拼音", "阅读理解", "作文", "琵琶行", "出师表"
        ],
        "english": [
            "英语", "english", "语法", "句型", "词汇", "单词", "时态", "从句", "阅读",
            "口语", "写作", "dictation", "grammar", "tense", "vocabulary"
        ]
    }
    
    for subject, keywords in keywords_map.items():
        for keyword in keywords:
            if keyword in topic_lower:
                return subject
                
    return "general"


def build_planning_prompt(topic: str, primary_color: str) -> tuple[str, str]:
    """构建用于 LLM 规划阶段的系统提示词和用户提示词。
    
    该函数会先检测主题所属学科，然后根据学科特点选择对应的指导方针，
    最终组装成完整的规划提示词。规划阶段的目标是让 LLM 输出一个 JSON，
    包含学习目标、核心概念、交互类型和交互提示。
    
    参数:
        topic: 教学主题，如 "牛顿第二定律"
        primary_color: 主题色，如 "#3B82F6"
        
    返回:
        (system_prompt, user_prompt) 二元组，分别用于 LLM 的 system 和 user 消息
    """
    subject = detect_subject(topic)
    subject_guide = SUBJECT_PROMPT_GUIDES.get(subject, SUBJECT_PROMPT_GUIDES["general"])
    
    # 填充 system prompt 模板
    system_prompt = PLANNING_SYSTEM_PROMPT_TEMPLATE.format(subject_guide=subject_guide)
    
    user_prompt = f"""请针对教学主题：“{topic}” 进行可视化页面规划。
主色调为：{primary_color}。

你的输出必须完全符合 JSON 格式，包含 learning_objectives、core_concepts、interaction_type 和 interaction_hint。
"""
    return system_prompt, user_prompt


def parse_planning_result(raw: str, topic: str = "") -> dict:
    """解析 LLM 返回的规划结果 JSON，并进行字段校验与修复。
    
    该函数负责：
    1. 清理 LLM 输出中可能包含的 Markdown 代码围栏（```json...```）
    2. 使用正则提取最外层的 JSON 对象
    3. 对学习目标、核心概念、交互类型等字段进行校验
    4. 如果任何环节失败（包括 JSON 解析异常），回退到默认规划
    
    参数:
        raw: LLM 原始输出字符串
        topic: 教学主题，用于生成默认值
        
    返回:
        标准化的规划字典，包含 learning_objectives、core_concepts、
        interaction_type、interaction_hint 四个字段
    """
    if not raw:
        return _default_plan(topic)
        
    # 尝试清理非 JSON 包裹的内容
    cleaned = raw.strip()
    if "```" in cleaned:
        fence_match = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL | re.IGNORECASE)
        if fence_match:
            cleaned = fence_match.group(1).strip()
        
    # 正则提取最外层的 {}
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        cleaned = match.group(0)
        
    try:
        data = json.loads(cleaned)
        
        # 字段校验与修复
        objectives = data.get("learning_objectives", [])
        if not isinstance(objectives, list) or not objectives:
            objectives = [f"理解 {topic} 的基本概念"]
        else:
            objectives = [str(obj)[:30] for obj in objectives if obj][:5]
            
        concepts = data.get("core_concepts", [])
        if not isinstance(concepts, list) or not concepts:
            concepts = [topic]
        else:
            concepts = [str(c) for c in concepts if c][:4]
            
        int_type = str(data.get("interaction_type", "general")).strip().lower()
        valid_types = {
            "param_explorer", "step_reveal", "tab_compare", 
            "clickable_diagram", "quiz", "number_visual", "general"
        }
        if int_type not in valid_types:
            int_type = "general"
            
        int_hint = data.get("interaction_hint", "")
        if not isinstance(int_hint, str) or not int_hint:
            int_hint = f"设计一个直观的交互界面，辅助学生理解 {topic}。"
        else:
            int_hint = int_hint[:200]  # 限制长度
            
        return {
            "learning_objectives": objectives,
            "core_concepts": concepts,
            "interaction_type": int_type,
            "interaction_hint": int_hint
        }
    except Exception:
        return _default_plan(topic)


def _default_plan(topic: str) -> dict:
    """生成一个安全的默认规划字典。
    
    当 LLM 规划失败或输出无法解析时，使用此函数生成兜底规划。
    默认使用 "general" 通用交互类型，确保后续 HTML 生成流程能正常进行。
    
    参数:
        topic: 教学主题，用于填充学习目标和核心概念
        
    返回:
        包含完整规划字段的字典
    """
    return {
        "learning_objectives": [
            f"掌握 {topic} 的核心知识要点",
            "通过交互操作探究相关参数或步骤的影响",
            "能够自主分析并总结所学规律"
        ],
        "core_concepts": [
            topic
        ],
        "interaction_type": "general",
        "interaction_hint": f"设计一个直观、美观且交互丰富的 HTML 教学页面，直观呈现关于“{topic}”的核心概念和变化规律。"
    }
