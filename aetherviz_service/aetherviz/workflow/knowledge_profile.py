"""Deterministic, coarse-grained knowledge profiling for prompt composition.

The taxonomy intentionally describes reusable teaching representations rather than
individual knowledge points. It is a routing hint, not a source of subject truth.
"""

from __future__ import annotations

from typing import Any

from aetherviz_service.aetherviz.workflow.plan_detection import detect_subject

CONCEPT_FAMILY_CUES: dict[str, dict[str, tuple[str, ...]]] = {
    "math": {
        "geometry": ("几何", "图形", "三角形", "多边形", "圆", "角", "平行", "垂直", "面积", "体积", "证明", "定理"),
        "function": ("函数", "图像", "坐标", "自变量", "因变量", "参数", "斜率", "抛物线"),
        "algebra": ("代数", "方程", "不等式", "因式", "多项式", "恒等", "根式"),
        "probability_statistics": ("概率", "统计", "频率", "样本", "分布", "随机", "数据"),
        "sequence": ("数列", "序列", "递推", "等差", "等比"),
        "calculus": ("极限", "导数", "微分", "积分", "变化率", "切线"),
        "set_logic": ("集合", "逻辑", "命题", "充分", "必要", "交集", "并集"),
        "number": ("数论", "整数", "质数", "因数", "倍数", "分数", "有理数", "实数"),
    },
    "physics": {
        "mechanics": ("运动", "速度", "加速度", "力", "动量", "能量", "轨迹"),
        "waves_optics": ("波", "振动", "光", "折射", "反射", "干涉"),
        "electricity": ("电流", "电压", "电阻", "电路", "电场", "磁场"),
        "thermodynamics": ("温度", "热", "熵", "气体", "压强"),
    },
    "chemistry": {
        "reaction": ("反应", "速率", "平衡", "催化"),
        "particle_structure": ("原子", "分子", "离子", "电子", "结构"),
        "solution": ("溶液", "浓度", "酸", "碱", "盐", "ph"),
    },
    "biology": {
        "cell_process": ("细胞", "呼吸", "光合", "代谢", "蛋白质"),
        "genetics": ("基因", "dna", "遗传", "染色体"),
        "ecology": ("生态", "种群", "群落", "食物链", "环境"),
    },
}

REPRESENTATION_CUES: dict[str, tuple[str, ...]] = {
    "coordinate_graph": ("函数", "图像", "坐标", "曲线", "斜率", "变化率"),
    "geometric_construction": ("几何", "三角形", "多边形", "圆", "角", "证明", "作图"),
    "number_line": ("数轴", "区间", "不等式", "绝对值"),
    "symbolic_derivation": ("推导", "公式", "方程", "恒等", "证明"),
    "tree_diagram": ("概率树", "分类", "分支", "层级"),
    "data_chart": ("统计", "数据", "样本", "分布", "频率"),
    "process_model": ("过程", "流程", "循环", "反应", "演化"),
    "object_motion": ("运动", "轨迹", "碰撞", "速度", "加速度"),
    "discrete_manipulation": ("排序", "匹配", "组合", "拼接", "拖拽"),
    "relation_network": ("关系", "结构", "因果", "网络", "体系"),
}

GEOMETRIC_RECOMPOSITION_MEASURE_CUES = ("面积", "体积", "容积")
GEOMETRIC_RECOMPOSITION_OPERATION_CUES = (
    "等分",
    "切割",
    "割补",
    "拼合",
    "拼成",
    "重排",
    "重新排列",
    "分割",
    "拆分",
    "逼近",
)
GEOMETRIC_RECOMPOSITION_DERIVATION_CUES = ("推导", "证明", "导出")

PEDAGOGY_CUES: dict[str, tuple[str, ...]] = {
    "proof_animation": ("证明", "推导", "定理", "依据"),
    "parameter_exploration": ("参数", "调节", "变化", "函数", "变量"),
    "construct_and_measure": ("作图", "构造", "测量", "几何"),
    "compare_cases": ("比较", "分类", "不同情况", "对比"),
    "conjecture_and_verify": ("猜想", "验证", "实验", "随机", "采样"),
    "challenge_practice": ("挑战", "闯关", "练习", "匹配", "排序"),
    "step_explanation": ("步骤", "流程", "过程", "推导"),
}

MATCH_PRIORITY = {
    "calculus": 8,
    "probability_statistics": 7,
    "sequence": 6,
    "set_logic": 5,
    "algebra": 4,
    "function": 3,
    "geometry": 2,
    "number": 1,
}


def build_knowledge_profile(topic: str, *, subject: str | None = None) -> dict[str, Any]:
    text = (topic or "").lower()
    resolved_subject = subject or detect_subject(topic)
    concept_family, family_score = _best_match(text, CONCEPT_FAMILY_CUES.get(resolved_subject, {}), "general")
    representation, representation_score = _best_match(text, REPRESENTATION_CUES, _default_representation(resolved_subject))
    pedagogy, pedagogy_score = _best_match(text, PEDAGOGY_CUES, "guided_exploration")
    if resolved_subject == "math" and is_geometric_recomposition_topic(text):
        representation = "geometric_recomposition"
        pedagogy = "decompose_recompose_proof"
        representation_score = max(representation_score, 2)
        pedagogy_score = max(pedagogy_score, 2)
    evidence_count = family_score + representation_score + pedagogy_score
    confidence = min(0.95, 0.45 + evidence_count * 0.08) if evidence_count else 0.35
    return {
        "subject": resolved_subject,
        "concept_family": concept_family,
        "representation_type": representation,
        "pedagogy_pattern": pedagogy,
        "confidence": round(confidence, 2),
    }


def normalize_knowledge_profile(raw: object, topic: str, subject: str) -> dict[str, Any]:
    baseline = build_knowledge_profile(topic, subject=subject)
    if not isinstance(raw, dict):
        return baseline
    result = dict(baseline)
    for key in ("concept_family", "representation_type", "pedagogy_pattern"):
        value = str(raw.get(key) or "").strip()
        if value and len(value) <= 48:
            result[key] = value
    if baseline["representation_type"] == "geometric_recomposition":
        result["representation_type"] = "geometric_recomposition"
        result["pedagogy_pattern"] = "decompose_recompose_proof"
    elif result["representation_type"] == "geometric_recomposition":
        result["representation_type"] = baseline["representation_type"]
        result["pedagogy_pattern"] = baseline["pedagogy_pattern"]
    result["subject"] = subject
    return result


def is_geometric_recomposition_topic(topic: str) -> bool:
    """Detect a reusable cut/rearrange proof shape, not a named knowledge point."""

    text = (topic or "").lower()
    has_measure = any(cue in text for cue in GEOMETRIC_RECOMPOSITION_MEASURE_CUES)
    has_operation = any(cue in text for cue in GEOMETRIC_RECOMPOSITION_OPERATION_CUES)
    has_derivation = any(cue in text for cue in GEOMETRIC_RECOMPOSITION_DERIVATION_CUES)
    return has_operation and (has_measure or has_derivation) or has_measure and has_derivation


def _best_match(text: str, choices: dict[str, tuple[str, ...]], default: str) -> tuple[str, int]:
    scores = {name: sum(1 for cue in cues if cue in text) for name, cues in choices.items()}
    if not scores or max(scores.values(), default=0) == 0:
        return default, 0
    winner = max(scores, key=lambda name: (scores[name], MATCH_PRIORITY.get(name, 0)))
    return winner, scores[winner]


def _default_representation(subject: str) -> str:
    if subject in {"math", "physics", "chemistry", "biology"}:
        return "dynamic_model"
    if subject in {"chinese", "english", "geography", "programming"}:
        return "relation_network"
    return "concept_map"
