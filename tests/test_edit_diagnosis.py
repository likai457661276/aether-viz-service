from __future__ import annotations

import json
from unittest.mock import MagicMock

from aetherviz_service.aetherviz.agents import runtime as agent_runtime
from aetherviz_service.aetherviz.edit.context import build_edit_context_summary
from aetherviz_service.aetherviz.edit.diagnosis import _diagnose_edit_impl
from aetherviz_service.aetherviz.tools.function_patch import extract_named_functions


def _html() -> str:
    return """<!DOCTYPE html><html><head><style>#play{font-size:12px}.label{color:#fff}</style></head>
    <body><main data-role="main-visual"><button id="play">播放</button><span class="label">旧说明</span></main>
    <script id="widget-config" type="application/json">{"type":"simulation","concept":"测试"}</script>
    <script>function play(){window.started=true}document.addEventListener('click',play)</script></body></html>"""


def _compiled_fields(instruction: str) -> dict[str, object]:
    return {
        "resolved_instruction": instruction,
        "change_requirements": [instruction],
        "preserve_requirements": ["保持教学内容和播放交互"],
        "impact_areas": ["dom", "css", "render"],
        "acceptance_criteria": ["修改结果在页面中可观察"],
        "ambiguities": [],
        "change_checks": [
            {
                "id": "c1",
                "kind": "css_declaration",
                "selector": "#play",
                "function": "",
                "property": "font-size",
                "expected": "16px",
                "baseline_binding": "absolute",
                "severity": "hard",
                "rationale": "按钮字号应变为 16px",
            }
        ],
        "preserve_checks": [
            {
                "id": "p1",
                "kind": "widget_type_unchanged",
                "selector": "",
                "function": "",
                "property": "",
                "expected": "",
                "baseline_binding": "must_match",
                "severity": "hard",
                "rationale": "保持 widget type",
            }
        ],
    }


def test_edit_context_extracts_bounded_dom_css_function_and_runtime_evidence() -> None:
    summary = build_edit_context_summary(
        instruction="点击播放后报错",
        business_html=_html(),
        context={
            "topic": "测试",
            "recent_messages": [{"role": "user", "content": "请修复播放"}],
        },
        validation_report={"ok": False, "errors": [{"type": "js_syntax", "message": "语法错误"}]},
        edit_target={"selector": "#play", "computed_styles": {"font-size": "12px"}},
        runtime_error={"message": "play failed", "stack": "at play (inline:1:1)", "action": "play"},
    )

    assert any(item["selector"] == "#play" for item in summary["document"]["dom_targets"])
    assert any(item["selector"] == "#play" for item in summary["document"]["css_rules"])
    assert any(item["name"] == "play" and item["unique"] for item in summary["document"]["functions"])
    assert summary["runtime_error"]["message"] == "play failed"
    assert summary["edit_target"]["computed_styles"]["font-size"] == "12px"
    assert summary["validation"]["errors"][0]["type"] == "js_syntax"
    assert len(json.dumps(summary, ensure_ascii=False, separators=(",", ":"))) <= 24_200


def test_v4_flash_diagnosis_returns_verified_css_target(monkeypatch) -> None:
    payload = {
        "intent": "increase_button_font",
        "scope": "business_css",
        "strategy": "full_html_regeneration",
        "problem": "播放按钮字号偏小",
        "confidence": 0.96,
        "targets": [
            {
                "kind": "css",
                "selector": "#play",
                "function": "",
                "source_hash": "",
                "evidence": "DOM 和 CSS 摘要都包含 #play",
                "confidence": 0.96,
            }
        ],
        "requires_clarification": False,
        "clarification_question": "",
        **_compiled_fields("将播放按钮字号调整为 16px，并保持播放行为不变"),
    }

    class AnalysisModel:
        def invoke(self, messages):
            assert "increase_button_font" not in messages[1].content
            return MagicMock(content=json.dumps(payload, ensure_ascii=False))

    monkeypatch.setattr(
        "aetherviz_service.aetherviz.edit.diagnosis.create_chat_model",
        lambda kind, response_schema=None: AnalysisModel(),
    )
    monkeypatch.setattr(
        "aetherviz_service.aetherviz.edit.diagnosis.has_primary_llm_config",
        lambda: True,
    )

    diagnosis = _diagnose_edit_impl(
        instruction="把播放按钮字号改为 16px",
        business_html=_html(),
        context_summary={"instruction": "把播放按钮字号改为 16px"},
    )

    assert diagnosis.strategy == "full_html_regeneration"
    assert diagnosis.targets[0]["selector"] == "#play"
    assert diagnosis.confidence == 0.96
    assert diagnosis.resolved_instruction == "将播放按钮字号调整为 16px，并保持播放行为不变"
    assert diagnosis.change_requirements == ("将播放按钮字号调整为 16px，并保持播放行为不变",)
    assert diagnosis.change_checks[0].kind == "css_declaration"
    assert diagnosis.change_checks[0].expected == "16px"
    assert diagnosis.preserve_checks[0].kind == "widget_type_unchanged"


def test_v4_flash_interprets_layout_wording_as_business_visual_problem(monkeypatch) -> None:
    payload = {
        "intent": "repair_oversized_animation_content",
        "scope": "business_visual_and_animation",
        "strategy": "full_html_regeneration",
        "problem": "主视觉图形尺寸异常并超出舞台可视范围",
        "confidence": 0.97,
        "targets": [],
        "requires_clarification": False,
        "clarification_question": "",
        "resolved_instruction": "修复动画主视觉尺寸与自适应映射，使完整函数图像始终在舞台内清晰显示",
        "change_requirements": ["完整函数图像不得被异常放大或裁切"],
        "preserve_requirements": ["保持参数控制与函数变换教学关系"],
        "impact_areas": ["css", "svg_canvas", "render", "animation"],
        "acceptance_criteria": ["初始状态和参数边界下均能看到完整图像"],
        "ambiguities": [],
        "change_checks": [],
        "preserve_checks": [],
    }

    class AnalysisModel:
        def invoke(self, messages):
            assert "控制面板" in messages[1].content
            return MagicMock(content=json.dumps(payload, ensure_ascii=False))

    monkeypatch.setattr(
        "aetherviz_service.aetherviz.edit.diagnosis.create_chat_model",
        lambda kind, response_schema=None: AnalysisModel(),
    )
    monkeypatch.setattr(
        "aetherviz_service.aetherviz.edit.diagnosis.has_primary_llm_config",
        lambda: True,
    )

    diagnosis = _diagnose_edit_impl(
        instruction="控制面板旁边的动画内容尺寸显示错误，请修复",
        business_html=_html(),
        context_summary={"instruction": "控制面板旁边的动画内容尺寸显示错误，请修复"},
    )

    assert diagnosis.strategy == "full_html_regeneration"
    assert diagnosis.scope == "business_visual_and_animation"
    assert "主视觉尺寸" in diagnosis.resolved_instruction
    assert diagnosis.change_checks[0].kind == "html_must_differ"
    assert diagnosis.change_checks[0].id == "auto_html_must_differ"


def test_v4_flash_can_authorize_redesign_of_all_business_content(monkeypatch) -> None:
    payload = {
        "intent": "redesign_all_business_content",
        "scope": "all_business_html",
        "strategy": "full_html_regeneration",
        "problem": "用户要求整体重做课件内容与交互",
        "confidence": 0.99,
        "targets": [],
        "requires_clarification": False,
        "clarification_question": "",
        "resolved_instruction": "重新设计全部教学文案、主视觉、业务控件、状态、渲染、事件和动画运行时",
        "change_requirements": ["全部业务内容采用新的教学与视觉方案"],
        "preserve_requirements": ["保持核心 Widget 运行契约"],
        "impact_areas": [
            "shell_content",
            "dom",
            "css",
            "svg_canvas",
            "state",
            "render",
            "events",
            "animation",
            "runtime",
        ],
        "acceptance_criteria": ["新课件完整可运行且各项交互可观察"],
        "ambiguities": [],
        "change_checks": [
            {
                "id": "c_all",
                "kind": "html_must_differ",
                "selector": "",
                "function": "",
                "property": "",
                "expected": "",
                "baseline_binding": "must_differ",
                "severity": "hard",
                "rationale": "整体重做必须可见变化",
            }
        ],
        "preserve_checks": [
            {
                "id": "p_widget",
                "kind": "widget_type_unchanged",
                "selector": "",
                "function": "",
                "property": "",
                "expected": "",
                "baseline_binding": "must_match",
                "severity": "hard",
                "rationale": "保持契约",
            }
        ],
    }

    class AnalysisModel:
        def invoke(self, messages):
            return MagicMock(content=json.dumps(payload, ensure_ascii=False))

    monkeypatch.setattr(
        "aetherviz_service.aetherviz.edit.diagnosis.create_chat_model",
        lambda kind, response_schema=None: AnalysisModel(),
    )
    monkeypatch.setattr(
        "aetherviz_service.aetherviz.edit.diagnosis.has_primary_llm_config",
        lambda: True,
    )

    diagnosis = _diagnose_edit_impl(
        instruction="把所有内容都重新设计，包括动画和控件",
        business_html=_html(),
        context_summary={"instruction": "把所有内容都重新设计，包括动画和控件"},
    )

    assert diagnosis.scope == "all_business_html"
    assert diagnosis.impact_areas == (
        "shell_content",
        "dom",
        "css",
        "svg_canvas",
        "state",
        "render",
        "events",
        "animation",
        "runtime",
    )
    assert diagnosis.preserve_requirements == ("保持核心 Widget 运行契约",)


def test_function_diagnosis_uses_server_verified_source_hash(monkeypatch) -> None:
    payload = {
        "intent": "fix_play",
        "scope": "business_runtime",
        "strategy": "full_html_regeneration",
        "problem": "播放函数报错",
        "confidence": 0.95,
        "targets": [{"kind": "function", "function": "play", "source_hash": "invented"}],
        "requires_clarification": False,
        "clarification_question": "",
        **_compiled_fields("修复播放报错，并保持当前动画内容和控制方式"),
    }
    payload["change_checks"] = [
        {
            "id": "c_fn",
            "kind": "function_body_changed",
            "selector": "",
            "function": "play",
            "property": "",
            "expected": "",
            "baseline_binding": "must_differ",
            "severity": "hard",
            "rationale": "play 函数体必须变化",
        }
    ]

    class AnalysisModel:
        def invoke(self, messages):
            return MagicMock(content=json.dumps(payload))

    monkeypatch.setattr(
        "aetherviz_service.aetherviz.edit.diagnosis.create_chat_model",
        lambda kind, response_schema=None: AnalysisModel(),
    )
    monkeypatch.setattr(
        "aetherviz_service.aetherviz.edit.diagnosis.has_primary_llm_config",
        lambda: True,
    )

    diagnosis = _diagnose_edit_impl(
        instruction="修复播放报错",
        business_html=_html(),
        context_summary={"runtime_error": {"message": "play failed"}},
    )

    expected = extract_named_functions(_html())["play"][0].source_hash
    assert diagnosis.strategy == "full_html_regeneration"
    assert diagnosis.targets[0]["source_hash"] == expected
    function_check = next(check for check in diagnosis.change_checks if check.id == "c_fn")
    assert function_check.kind == "function_body_changed"
    assert function_check.severity == "soft"
    assert "c_fn" in diagnosis.degraded_checks


def test_diagnosis_resolves_conversational_reference_into_self_contained_instruction(monkeypatch) -> None:
    payload = {
        "intent": "speed_up_animation",
        "scope": "animation_pipeline",
        "strategy": "full_html_regeneration",
        "problem": "当前单位圆联动动画节奏偏慢",
        "confidence": 0.93,
        "targets": [],
        "requires_clarification": False,
        "clarification_question": "",
        "resolved_instruction": "缩短单位圆与正弦曲线联动动画的总时长，使播放节奏明显加快，同时保持轨迹、暂停、重置和重播行为正确",
        "change_requirements": ["动画总时长明显缩短", "单位圆动点与正弦曲线继续同步"],
        "preserve_requirements": ["保持教学内容、暂停、重置和重播行为"],
        "impact_areas": ["state", "render", "events", "animation", "runtime"],
        "acceptance_criteria": ["播放后联动画面更快完成", "暂停后画面稳定且重播可用"],
        "ambiguities": [],
        "change_checks": [
            {
                "id": "c_num",
                "kind": "numeric_changed",
                "selector": "",
                "function": "",
                "property": "",
                "expected": "",
                "baseline_binding": "must_differ",
                "severity": "soft",
                "rationale": "时长相关数值应变化",
            }
        ],
        "preserve_checks": [],
    }

    class AnalysisModel:
        def invoke(self, messages):
            assert "再快一点" in messages[1].content
            assert "单位圆与正弦曲线联动" in messages[1].content
            return MagicMock(content=json.dumps(payload, ensure_ascii=False))

    monkeypatch.setattr(
        "aetherviz_service.aetherviz.edit.diagnosis.create_chat_model",
        lambda kind, response_schema=None: AnalysisModel(),
    )
    monkeypatch.setattr(
        "aetherviz_service.aetherviz.edit.diagnosis.has_primary_llm_config",
        lambda: True,
    )

    diagnosis = _diagnose_edit_impl(
        instruction="再快一点",
        business_html=_html(),
        context_summary={
            "instruction": "再快一点",
            "request_context": {"recent_messages": [{"role": "user", "content": "加快单位圆与正弦曲线联动"}]},
        },
    )

    assert diagnosis.resolved_instruction.startswith("缩短单位圆与正弦曲线联动动画")
    assert diagnosis.impact_areas == ("state", "render", "events", "animation", "runtime")
    assert len(diagnosis.acceptance_criteria) == 2
    # soft numeric + auto hard html_must_differ
    assert any(check.kind == "html_must_differ" for check in diagnosis.change_checks)


def test_diagnosis_downgrades_unknown_strategy_to_full_regeneration(monkeypatch) -> None:
    payload = {
        "intent": "edit",
        "scope": "business_css",
        "strategy": "css_declaration",
        "problem": "未知目标",
        "confidence": 0.9,
        "targets": [{"selector": "#missing", "kind": "css"}],
        "requires_clarification": False,
        "clarification_question": "",
        "change_checks": [
            {
                "id": "c_bad",
                "kind": "css_declaration",
                "selector": "#missing",
                "function": "",
                "property": "color",
                "expected": "red",
                "baseline_binding": "absolute",
                "severity": "hard",
                "rationale": "假 selector",
            }
        ],
        "preserve_checks": [],
    }

    class AnalysisModel:
        def invoke(self, messages):
            return MagicMock(content=json.dumps(payload))

    monkeypatch.setattr(
        "aetherviz_service.aetherviz.edit.diagnosis.create_chat_model",
        lambda kind, response_schema=None: AnalysisModel(),
    )
    monkeypatch.setattr(
        "aetherviz_service.aetherviz.edit.diagnosis.has_primary_llm_config",
        lambda: True,
    )

    diagnosis = _diagnose_edit_impl(
        instruction="调整目标",
        business_html=_html(),
        context_summary={},
    )

    assert diagnosis.strategy == "full_html_regeneration"
    assert "c_bad" in diagnosis.degraded_checks
    assert diagnosis.change_checks[0].severity == "soft" or any(
        check.kind == "html_must_differ" for check in diagnosis.change_checks
    )


def test_runtime_dispatch_passes_structured_edit_target_and_error(monkeypatch) -> None:
    captured = {}

    def fake_edit_workflow(**kwargs):
        captured.update(kwargs)
        yield "done"

    monkeypatch.setattr(agent_runtime, "run_edit_html_workflow", fake_edit_workflow)

    result = list(
        agent_runtime._agent_runtime_stream_impl(
            phase="edit_html",
            current_html=_html(),
            message="修复播放",
            context={"topic": "测试"},
            edit_target={"selector": "#play"},
            runtime_error={"message": "play failed", "action": "play"},
            langsmith_trace_id=None,
        )
    )

    assert result == ["done"]
    assert captured["edit_target"] == {"selector": "#play"}
    assert captured["runtime_error"] == {"message": "play failed", "action": "play"}
