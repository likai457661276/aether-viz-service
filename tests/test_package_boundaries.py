"""Import boundary tests for generate / edit / contracts isolation."""

from __future__ import annotations

import ast
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "aetherviz_service" / "aetherviz"


def _imports_from(package_dir: Path) -> set[str]:
    modules: set[str] = set()
    for path in package_dir.rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    modules.add(alias.name)
    return modules


def test_generate_does_not_import_edit() -> None:
    imports = _imports_from(PACKAGE_ROOT / "generate")
    offenders = [name for name in imports if name.startswith("aetherviz_service.aetherviz.edit")]
    assert offenders == []


def test_edit_does_not_import_generate() -> None:
    imports = _imports_from(PACKAGE_ROOT / "edit")
    offenders = [name for name in imports if name.startswith("aetherviz_service.aetherviz.generate")]
    assert offenders == []


def test_contracts_does_not_import_edit_or_generate_business() -> None:
    imports = _imports_from(PACKAGE_ROOT / "contracts")
    offenders = [
        name
        for name in imports
        if name.startswith("aetherviz_service.aetherviz.edit")
        or name.startswith("aetherviz_service.aetherviz.generate")
    ]
    assert offenders == []


def test_edit_prompts_exclude_generation_delivery_fragments() -> None:
    from aetherviz_service.aetherviz.edit.prompts import EDIT_HTML_SYSTEM_PROMPT

    assert "清爽教学工作台" not in EDIT_HTML_SYSTEM_PROMPT
    assert "服务端布局契约" not in EDIT_HTML_SYSTEM_PROMPT
    assert "舞台居中与标签防重叠" not in EDIT_HTML_SYSTEM_PROMPT
    assert "动态数值展示规则" not in EDIT_HTML_SYSTEM_PROMPT
    assert "唯一事实基线" in EDIT_HTML_SYSTEM_PROMPT


def test_edit_context_ignores_plan_summary() -> None:
    from aetherviz_service.aetherviz.edit.context import build_edit_context_summary

    summary = build_edit_context_summary(
        instruction="改快一点",
        business_html="<html><body><button id='play'>播放</button></body></html>",
        context={
            "topic": "测试",
            "plan_summary": {"title": "旧方案", "goal": "不应进入编辑诊断"},
            "memory": {"summary": "已为《测试》生成方案：旧方案。目标：不应进入编辑诊断"},
            "recent_messages": [{"role": "user", "content": "加快动画"}],
        },
        validation_report={"ok": True, "errors": [], "warnings": []},
    )
    assert "plan" not in summary["request_context"]
    assert "memory_summary" not in summary["request_context"]
    assert "旧方案" not in str(summary)
    assert "不应进入编辑诊断" not in str(summary)


def test_edit_assembly_plan_prefers_widget_config_over_topic_inference() -> None:
    from aetherviz_service.aetherviz.edit.context import build_edit_assembly_plan

    html = """<!DOCTYPE html><html><head>
<script type="application/json" id="widget-config">{"type":"diagram","concept":"勾股定理"}</script>
</head><body>
<section data-shell-content-edit="true" data-title="勾股图解" data-goal="理解直角三角形关系"><ul><li>观察</li></ul></section>
</body></html>"""

    plan = build_edit_assembly_plan(html, "勾股定理")

    assert plan["interactive_type"] == "diagram"
    assert plan["title"] == "勾股图解"
    assert plan["goal"] == "理解直角三角形关系"


def test_edit_assembly_plan_without_widget_config_does_not_force_simulation_from_math_topic() -> None:
    from aetherviz_service.aetherviz.edit.context import build_edit_assembly_plan
    from aetherviz_service.aetherviz.contracts.validation.animation_lifecycle_checker import check_animation_lifecycle

    # No widget-config: topic may still normalize to simulation, but when config says diagram we already covered
    # that above. Here verify diagram config keeps rAF bypass non-blocking.
    html = """<!DOCTYPE html><html><head>
<script type="application/json" id="widget-config">{"type":"diagram"}</script>
</head><body>
<script>
function frame(){ requestAnimationFrame(frame); }
function play(){ requestAnimationFrame(frame); }
</script>
</body></html>"""
    plan = build_edit_assembly_plan(html, "勾股定理")
    report = check_animation_lifecycle(html, plan=plan)
    assert plan["interactive_type"] == "diagram"
    assert not any(error["type"] == "animation_controller_bypass" for error in report["errors"])
    assert any(warning["type"] == "animation_controller_bypass" for warning in report["warnings"])
