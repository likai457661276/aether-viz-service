"""Capability catalog for planning prompts — capability language only, no backend names."""

from __future__ import annotations

from aetherviz_service.aetherviz.ir.registry import DEFAULT_IR_REGISTRY, IRBackendRegistry


def build_ir_capability_catalog(registry: IRBackendRegistry = DEFAULT_IR_REGISTRY) -> str:
    """Build a planner-facing cheat sheet from registered routing profiles.

    Descriptions, capabilities, and exclusions stay in generic capability language.
    Backend keys and knowledge-point names are intentionally omitted.
    """
    lines = [
        "已验证可视化能力族（只描述通用能力，不要填写实现后端名称或知识点专用模板）：",
    ]
    for index, backend in enumerate(registry.backends(), start=1):
        profile = backend.routing_profile
        description = str(profile.description or "").strip() or "通用可视化能力"
        capabilities = "、".join(sorted(profile.capabilities)) or "未声明"
        views = "、".join(sorted(profile.supported_view_kinds)) or "未限定"
        exclusions = "；".join(str(item).strip() for item in profile.exclusions if str(item).strip()) or "无"
        lines.append(
            f"{index}. {description}\n"
            f"   能力标签：{capabilities}\n"
            f"   常用视图 kind：{views}\n"
            f"   会被拒的组合：{exclusions}"
        )
    lines.append(
        "填写 representation_spec 时：只组合上述能力可覆盖的 views / correspondences / "
        "required_invariants / interaction_requirements；若某组合会被拒，改选另一组能力组合，"
        "而不是点名实现后端。"
    )
    return "\n".join(lines)
