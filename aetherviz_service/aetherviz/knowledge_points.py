"""AetherViz knowledge-point registry.

匹配阶段只依赖这里声明的静态知识点。
"""

from dataclasses import dataclass

from aetherviz_service.aetherviz.cover_images import COVER_IMAGE_BASE64_BY_STATIC_HTML_KEY


@dataclass(frozen=True)
class KnowledgePoint:
    subject: str
    knowledge_domain: str
    knowledge_point_id: str
    title: str
    keywords: tuple[str, ...]
    render_mode: str
    static_html_slug: str
    grade: str | None = None
    core_concepts: tuple[str, ...] = ()
    key_formulas: tuple[str, ...] = ()
    cover_image_base64: str = ""


def _point(
    subject: str,
    domain: str,
    point_slug: str,
    title: str,
    keywords: tuple[str, ...],
    grade: str,
    render_mode: str = "static-html",
    static_html_slug: str | None = None,
    core_concepts: tuple[str, ...] = (),
    key_formulas: tuple[str, ...] = (),
) -> KnowledgePoint:
    knowledge_point_id = f"{subject}/{point_slug}"
    resolved_static_html_slug = static_html_slug or point_slug.replace("_", "-")
    return KnowledgePoint(
        subject=subject,
        knowledge_domain=domain,
        knowledge_point_id=knowledge_point_id,
        title=title,
        keywords=keywords,
        render_mode=render_mode,
        static_html_slug=resolved_static_html_slug,
        grade=grade,
        core_concepts=core_concepts or keywords,
        key_formulas=key_formulas,
        cover_image_base64=COVER_IMAGE_BASE64_BY_STATIC_HTML_KEY.get(
            f"{subject}/{resolved_static_html_slug}",
            "",
        ),
    )


KNOWLEDGE_POINTS: dict[str, KnowledgePoint] = {
    point.knowledge_point_id: point
    for point in (
        _point("physics", "mechanics", "newton_first_law", "牛顿第一定律", ("牛顿第一定律", "惯性", "匀速直线运动"), "八年级"),
        _point("physics", "mechanics", "newton_second_law", "牛顿第二定律", ("牛顿第二定律", "F=ma", "加速度"), "高一"),
        _point("physics", "mechanics", "newton_third_law", "牛顿第三定律", ("牛顿第三定律", "作用力", "反作用力"), "高一"),
        _point("physics", "mechanics", "force_acceleration", "力与加速度", ("力与加速度", "合力", "加速度"), "高一"),
        _point("physics", "mechanics", "f_ma_demo", "力与加速度", ("F=ma演示", "F=ma", "力", "质量", "加速度"), "高一", static_html_slug="force-acceleration"),
        _point("physics", "mechanics", "momentum_conservation", "动量守恒", ("动量守恒", "碰撞", "速度"), "高二"),
        _point("physics", "mechanics", "gravity", "重力作用", ("重力", "重力作用", "重力加速度"), "八年级"),
        _point("physics", "mechanics", "friction_demo", "摩擦力演示", ("摩擦力", "摩擦力演示", "粗糙"), "八年级"),
        _point("physics", "mechanics", "spring_oscillator", "弹簧振子", ("弹簧振子", "弹簧", "回复力"), "高二"),
        _point("physics", "waves", "simple_harmonic_motion", "简谐运动", ("简谐运动", "振动", "正弦"), "高二"),
        _point("physics", "mechanics", "free_fall", "自由落体", ("自由落体", "下落", "重力加速度"), "高一"),
        _point("physics", "mechanics", "projectile_motion", "抛体运动", ("抛体运动", "平抛", "斜抛", "抛物线"), "高一"),
        _point("physics", "mechanics", "circular_motion", "圆周运动", ("圆周运动", "向心力", "向心加速度"), "高一"),
        _point("physics", "mechanics", "friction_motion_relation", "摩擦力与运动关系", ("摩擦力与运动", "静摩擦", "滑动摩擦"), "八年级"),
        _point("physics", "mechanics", "collision_experiment", "碰撞实验", ("碰撞实验", "弹性碰撞", "非弹性碰撞"), "高二"),
        _point("math", "number_and_algebra", "rational_number", "有理数", ("有理数", "正数", "负数", "数轴"), "七年级"),
        _point("math", "number_and_algebra", "rational_numbers", "有理数运算", ("有理数运算", "有理数", "四则运算"), "七年级"),
        _point("math", "number_and_algebra", "rational_add_subtract", "有理数的加减法", ("有理数的加减法", "加法", "减法", "数轴"), "七年级"),
        _point("math", "number_and_algebra", "rational_multiply_divide", "有理数的乘除法", ("有理数的乘除法", "乘法", "除法", "符号法则"), "七年级"),
        _point("math", "number_and_algebra", "rational_power", "有理数的乘方", ("有理数的乘方", "乘方", "幂", "底数", "指数"), "七年级"),
        _point("math", "number_and_algebra", "algebraic_expression", "整式", ("整式", "单项式", "多项式", "系数", "次数"), "七年级"),
        _point("math", "number_and_algebra", "algebraic_add_subtract", "整式加减", ("整式加减", "合并同类项", "去括号"), "七年级"),
        _point("math", "number_and_algebra", "factorization", "整式乘除与因式分解", ("整式乘除", "因式分解", "平方差", "完全平方"), "七年级"),
        _point("math", "number_and_algebra", "fraction", "分式", ("分式", "分式方程", "约分", "通分"), "七年级"),
        _point("math", "number_and_algebra", "linear_equation", "一元一次方程", ("一元一次方程", "解方程", "移项"), "七年级"),
        _point("math", "number_and_algebra", "system_equations", "二元一次方程组", ("二元一次方程组", "代入消元", "加减消元"), "七年级"),
        _point("math", "number_and_algebra", "inequality", "不等式与不等式组", ("不等式", "不等式组", "解集", "数轴"), "七年级"),
        _point("math", "number_and_algebra", "quadratic", "一元二次方程", ("一元二次方程", "二次方程", "求根公式", "配方法"), "九年级"),
        _point("math", "functions", "linear_function", "一次函数", ("一次函数", "函数图像", "斜率", "截距"), "八年级"),
        _point(
            "math",
            "functions",
            "quadratic_function",
            "二次函数",
            ("二次函数", "抛物线", "顶点式", "对称轴", "判别式", "函数最值"),
            "高一",
            static_html_slug="quadratic-function",
            key_formulas=("y = ax² + bx + c", "xᵥ = -b / 2a", "Δ = b² - 4ac"),
        ),
        _point("math", "geometry", "geometry_figure", "几何图形", ("几何图形", "线段", "角", "圆"), "七年级"),
        _point("math", "geometry", "geometry", "平面几何基础", ("平面几何", "几何基础", "点", "线", "面"), "七年级"),
        _point("math", "geometry", "parallel_perpendicular", "平行线与相交线", ("平行线", "相交线", "垂直", "同位角", "内错角"), "七年级"),
        _point("math", "geometry", "triangle", "三角形", ("三角形", "边", "角", "内角和"), "七年级"),
        _point("math", "geometry", "congruent_triangles", "全等三角形", ("全等三角形", "SSS", "SAS", "ASA", "AAS"), "七年级"),
        _point("math", "geometry", "axisymmetry", "轴对称", ("轴对称", "对称轴", "镜像", "翻折"), "七年级"),
        _point("math", "geometry", "geometric_proof", "几何证明", ("几何证明", "证明", "推理", "命题"), "七年级"),
        _point("math", "geometry", "coordinate_system", "平面直角坐标系", ("平面直角坐标系", "坐标系", "横坐标", "纵坐标", "象限"), "七年级"),
        _point("math", "geometry", "trigonometry", "三角函数基础", ("三角函数", "正弦", "余弦", "正切"), "九年级"),
        _point("math", "geometry", "polygon_area", "多边形的面积", ("多边形的面积", "割补法", "三角剖分", "几何面积", "多边形面积"), "五年级"),
        _point(
            "math",
            "geometry",
            "spatial_geometry",
            "空间几何",
            ("空间几何", "立体几何", "空间直角坐标系", "空间向量", "三维空间"),
            "高二",
            static_html_slug="spatial-geometry",
            key_formulas=("d = \\sqrt{(x_2-x_1)^2 + (y_2-y_1)^2 + (z_2-z_1)^2}", "\\cos \\langle\\vec{a},\\vec{b}\\rangle = \\frac{\\vec{a}\\cdot\\vec{b}}{|\\vec{a}|\\cdot|\\vec{b}|}"),
        ),
        _point("math", "statistics_probability", "data_collection", "数据的收集与整理", ("数据的收集与整理", "数据的收集", "统计量", "样本容量"), "七年级"),
        _point("math", "statistics_probability", "probability", "概率初步", ("概率", "随机事件", "可能性"), "七年级"),
        _point("chemistry", "matter_structure", "atomic_structure", "原子结构", ("原子结构", "原子核", "电子", "质子", "中子"), "九年级"),
        _point("chemistry", "matter_structure", "periodic_table", "元素周期表", ("元素周期表", "元素", "周期", "族"), "九年级"),
        _point("chemistry", "matter_structure", "carbon_allotropes", "碳的同素异形体", ("碳的同素异形体", "金刚石", "石墨", "富勒烯"), "九年级"),
        _point("chemistry", "reactions", "chemical_reaction_types", "化学反应类型", ("化学反应类型", "化合反应", "分解反应", "置换反应", "复分解反应"), "九年级"),
        _point("chemistry", "reactions", "acid_base_neutralization", "酸碱中和反应", ("酸碱中和", "中和反应", "酸", "碱", "pH"), "九年级"),
        _point("chemistry", "reactions", "combustion_fire", "燃烧与灭火", ("燃烧", "灭火", "可燃物", "氧气", "着火点"), "九年级"),
        _point("chemistry", "reactions", "metal_reactivity", "金属活动性顺序", ("金属活动性", "金属活动性顺序", "置换反应"), "九年级"),
        _point("chemistry", "solutions", "solution_solubility", "溶液与溶解度", ("溶液", "溶解度", "溶质", "溶剂", "饱和溶液"), "九年级"),
        _point("chemistry", "environment", "water_purification", "水的净化", ("水的净化", "过滤", "吸附", "蒸馏"), "九年级"),
        _point(
            "chemistry",
            "reactions",
            "redox_reaction",
            "氧化还原反应",
            ("氧化还原反应", "氧化还原", "氧化剂", "还原剂", "电子转移", "化合价"),
            "高一",
            key_formulas=(
                "\\text{失电子} \\rightarrow \\text{化合价升高} \\rightarrow \\text{被氧化} \\rightarrow \\text{还原剂}",
                "\\text{得电子} \\rightarrow \\text{化合价降低} \\rightarrow \\text{被还原} \\rightarrow \\text{氧化剂}",
                "\\text{CuO} + \\text{H}_2 \\xrightarrow{\\Delta} \\text{Cu} + \\text{H}_2\\text{O}",
            ),
        ),
        _point(
            "chemistry",
            "reactions",
            "chemical_reaction_rate",
            "化学反应速率",
            ("化学反应速率", "反应速率", "碰撞理论", "活化分子", "催化剂", "温度影响", "浓度影响"),
            "高二",
            static_html_slug="chemical-reaction-rate",
            key_formulas=(
                "v = \\frac{\\Delta c}{\\Delta t}",
                "v(A) : v(B) = a : b \\quad (aA + bB \\rightarrow cC)",
                "\\text{有效碰撞} \\leftarrow \\text{活化分子} \\leftarrow \\text{活化能}",
            ),
        ),
        _point("chinese", "modern_literature", "huique", "灰雀", ("灰雀", "列宁", "小男孩", "诚实", "爱护鸟类", "知错就改"), "三年级"),
        _point(
            "biology",
            "biomolecules",
            "protein_structure_function",
            "蛋白质的结构与功能",
            ("蛋白质", "氨基酸", "肽键", "脱水缩合", "空间结构", "结构多样性"),
            "高一",
            static_html_slug="protein-structure-function",
            key_formulas=(
                "\\text{肽键数} = \\text{失去水分数} = \\text{氨基酸数} - \\text{肽链数}",
                "\\text{蛋白质相对分子质量} = n \\times a - 18 \\times (n - m)",
            ),
        ),
        _point(
            "biology",
            "genetics",
            "dna_structure",
            "DNA的分子结构",
            ("DNA", "双螺旋", "碱基互补配对", "脱氧核苷酸", "氢键"),
            "高二",
            static_html_slug="dna-structure",
            key_formulas=(
                "A = T, \\quad G = C",
                "A + G = T + C \\quad (\\text{卡加夫法则})",
                "\\text{氢键数} = 2 \\times A + 3 \\times G",
            ),
        ),
    )
}


def get_knowledge_point(knowledge_point_id: str) -> KnowledgePoint | None:
    return KNOWLEDGE_POINTS.get(knowledge_point_id)


def knowledge_point_exists(knowledge_point_id: str) -> bool:
    return knowledge_point_id in KNOWLEDGE_POINTS


def validate_knowledge_point_registry() -> None:
    for point in KNOWLEDGE_POINTS.values():
        if not point.static_html_slug:
            raise ValueError(f"Missing static HTML slug: {point.knowledge_point_id}")
        if not point.grade:
            raise ValueError(f"Missing grade: {point.knowledge_point_id}")
        if not point.cover_image_base64:
            raise ValueError(f"Missing cover image: {point.knowledge_point_id}")


def knowledge_point_summary() -> str:
    lines = []
    for point in KNOWLEDGE_POINTS.values():
        lines.append(
            f"- {point.knowledge_point_id}: {point.title}；"
            f"subject={point.subject}；knowledge_domain={point.knowledge_domain}；"
            f"grade={point.grade}；"
            f"render_mode={point.render_mode}；static_html_slug={point.static_html_slug}；"
            f"关键词：{', '.join(point.keywords)}"
        )
    return "\n".join(lines)


def supported_knowledge_points_summary() -> str:
    grouped: dict[str, list[str]] = {}
    for point in KNOWLEDGE_POINTS.values():
        grouped.setdefault(point.subject, []).append(point.title)
    return "；".join(f"{subject}: {', '.join(titles)}" for subject, titles in grouped.items())
