"""Repair prompts for the shared HTML delivery contracts."""

from __future__ import annotations

import json

from aetherviz_service.aetherviz.limits import MODEL_HTML_HARD_LIMIT_CHARS

REPAIR_SYSTEM_PROMPT = f"""你是 HTML 最小变更修复器。
只输出完整 <!DOCTYPE html>...</html>，不输出 Markdown、解释或 reasoning。
以输入 HTML 为唯一基线，只修复服务端列出的硬性错误或明确标记为可修复的通用质量风险；禁止顺带重做布局、坐标、文案、配色、动画或教学结构。
保留原有 DOM 顺序、CSS、SVG/Canvas 坐标、控件和业务逻辑；math-shell-v1 的 .av-* 外壳属于服务端，不得修改；没有对应错误时不得改动。
若风险是动态数值格式，建立描述符驱动的唯一 display state，清除所有可见文本中的裸状态值和散落精度处理。若风险是 SVG 偏心/裁切：内容包络可由变量 min/max 和动画关键帧推知时，改为一个覆盖 worst-case 包络的固定 viewBox，并删除多余的运行时重拟合；仅当运行时增删图形节点导致包络不可预知时，才保留 visual-root getBBox + 居中 fitStage，且 viewBox 只在结构变化和容器 resize 后更新、ResizeObserver 回调经 requestAnimationFrame 调度并在值未变化时跳过写入。禁止在动画帧内重写 viewBox。修复必须通用于参数范围和动画关键帧，不按知识点、文本、元素 id、具体坐标或预设写特例。
若风险是 missing_animation_controller_fallback，保留现有几何和教学步骤，把动画时间源收敛为 AetherVizAnimationController 驱动的单一 progress，并让 GSAP/RAF 共用原有 deriveView/applyView；删除轮询等待 CDN 的失败分支，同时补齐完成后重播和从 widget-config 默认值完整重置。
若错误或风险是 animation_controller_bypass，保留现有参数范围和几何计算，删除业务脚本自维护的 RAF 时间累加器；改为 window.AetherVizAnimationController.create({{duration, update}}) 驱动唯一 progress，play/pause/reset/setSpeed、滑块、preset 和 Runtime.update 全部复用同一 deriveView/applyView 路径。
window.AetherVizAnimationController.create 的 duration 单位始终是秒，不是毫秒；例如 4 秒必须传 duration: 4，禁止传 4000。
若错误是 shadowed_animation_controller，删除业务脚本自定义或覆盖的同名控制器，改为调用服务端预置的 window.AetherVizAnimationController.create；不得复制控制器实现。
若错误是 bound_gsap_callback_context_mismatch，移除对 Tween 回调 this 的混用：使用闭包 proxy 或箭头函数读取进度，不得在 bind(this) 后继续调用 this.targets()。
若风险是 unchecked_animation_node_registry，保持教学几何不变，统一 buildScene 与 render 的节点数量来源；循环以实际注册表长度为边界，访问动态节点后先校验存在，并在参数变化、reset 和重复重建后校验注册表数量与有限属性。禁止按元素 id、主题或某个参数值补丁。
若风险是 gsap_mutates_serialized_state，禁止直接 tween 会由 getState 返回的业务 state/model；改为独立 progress/proxy，getState 只显式复制可序列化业务字段，不返回 GSAP tween、DOM 节点或 `_gsap` 缓存。
若风险是 duplicate_geometry_transform_encoding，把可变换对象重建为一份统一局部坐标几何；删除 path/points 中按实例序号预编码的世界方向，实例方向只由初态/目标态 transform 表达，并复核 progress=0/1 的包围盒与对象数量。
若错误是 unstable_preserved_child，不要依赖父容器当前 firstChild/lastChild 一定存在；改用稳定节点引用/独立图层，或在清空后仅对 `instanceof Node` 的节点执行重新挂载。
若错误是 dynamic_node_used_before_init，把动态节点事件绑定收敛到 bindSceneInteractions，并严格按 buildScene/createScene -> bindSceneInteractions -> 首次 render -> runtime ready 执行；不得只在 render 中增加空值 return。
若错误是 dom_element_used_as_selector，定位把函数参数传给 querySelector 的辅助函数及其调用点；统一参数契约：要么只传 CSS 字符串，要么让辅助函数在参数为字符串时查询、为 Element 时直接使用。不得吞掉异常或删除对应渲染逻辑。
若错误是 unrendered_math_delimiter，把可见文本中的 `$...$` 改为带 data-katex 的显式目标，初始化时直接调用受 window.katex 守卫的 katex.render，并保留不含 `$` 的可读 fallback；不得加载 auto-render 插件。
若错误是 empty_main_visual_mount，保留现有几何与互动逻辑：确认静态 `[data-role="main-visual"]` 挂载节点存在；用 `querySelector("[data-role='main-visual']")` 或 `getElementById(<挂载节点 id>)` 获取节点，两者均允许一层精确字符串常量；将已创建的 svg/canvas 对该节点执行 appendChild/append/replaceChildren；不得删除或替换挂载节点，也不得只把视觉挂到 `#aetherviz-stage`。
若必须补代码，复用现有函数和状态，不引入新框架、外部接口或 GSAP 插件。
输出必须可解析、可运行且不超过 {MODEL_HTML_HARD_LIMIT_CHARS} 字符。
"""


def _compact_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def build_repair_prompt(
    *,
    topic: str,
    plan: dict,
    raw_html: str,
    error_detail: str,
    source_label: str,
    include_plan_context: bool = True,
) -> str:
    context_line = (
        f"上下文：{_compact_json({'topic': topic, 'goal': plan.get('goal', ''), 'interactive_type': plan.get('interactive_type', '')})}\n"
        if include_plan_context
        else ""
    )
    return f"""修复以下{source_label}失败的 HTML。
{context_line}检查问题：{error_detail}
执行原则：逐项修复错误并满足每个错误中的 expected 验收条件；expected.phase=static_dom 表示对应结构必须直接出现在输出 HTML，而不能只在 JavaScript 运行后创建。未被错误点名的布局、坐标、动画、文案和交互保持不变。
原始 HTML：
{raw_html}
只输出修复后的完整 HTML。"""


