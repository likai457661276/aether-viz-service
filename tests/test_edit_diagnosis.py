from __future__ import annotations

import json
from unittest.mock import MagicMock

from aetherviz_service.aetherviz.agents import runtime as agent_runtime
from aetherviz_service.aetherviz.agents.edit_diagnosis_agent import EditDiagnosis, _diagnose_edit_impl
from aetherviz_service.aetherviz.agents.edit_function_agent import stream_edit_functions
from aetherviz_service.aetherviz.agents.html_agent import HtmlStreamResult
from aetherviz_service.aetherviz.tools.edit_context import build_edit_context_summary
from aetherviz_service.aetherviz.tools.edit_operations import apply_diagnosed_operations, build_diagnosis_guard
from aetherviz_service.aetherviz.tools.function_patch import extract_named_functions


def _html() -> str:
    return """<!DOCTYPE html><html><head><style>#play{font-size:12px}.label{color:#fff}</style></head>
    <body><main data-role="main-visual"><button id="play">播放</button><span class="label">旧说明</span></main>
    <script id="widget-config" type="application/json">{"type":"simulation","concept":"测试"}</script>
    <script>function play(){window.started=true}document.addEventListener('click',play)</script></body></html>"""


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
        "strategy": "css_declaration",
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
        "operations": [
            {
                "op": "set_css",
                "selector": "#play",
                "property": "font-size",
                "value": "16px",
                "old_text": "",
                "new_text": "",
                "attribute": "",
            }
        ],
        "assertions": [
            {"type": "selector_exists", "selector": "#play", "property": "", "expected": ""}
        ],
        "allowed_scope": ["style:#play"],
        "requires_clarification": False,
        "clarification_question": "",
    }

    class AnalysisModel:
        def invoke(self, messages):
            assert "increase_button_font" not in messages[1].content
            return MagicMock(content=json.dumps(payload, ensure_ascii=False))

    monkeypatch.setattr(
        "aetherviz_service.aetherviz.agents.edit_diagnosis_agent.create_chat_model",
        lambda kind, response_schema=None: AnalysisModel(),
    )
    monkeypatch.setattr(
        "aetherviz_service.aetherviz.agents.edit_diagnosis_agent.has_primary_llm_config",
        lambda: True,
    )

    diagnosis = _diagnose_edit_impl(
        instruction="把播放按钮字号改为 16px",
        business_html=_html(),
        context_summary={"instruction": "把播放按钮字号改为 16px"},
    )

    assert diagnosis.strategy == "css_declaration"
    assert diagnosis.targets[0]["selector"] == "#play"
    assert diagnosis.confidence == 0.96


def test_function_diagnosis_uses_server_verified_source_hash(monkeypatch) -> None:
    payload = {
        "intent": "fix_play",
        "scope": "business_runtime",
        "strategy": "function_repair",
        "problem": "播放函数报错",
        "confidence": 0.95,
        "targets": [{"kind": "function", "function": "play", "source_hash": "invented"}],
        "operations": [],
        "assertions": [{"type": "runtime_error_absent", "selector": "", "property": "", "expected": ""}],
        "allowed_scope": ["function:play"],
        "requires_clarification": False,
        "clarification_question": "",
    }

    class AnalysisModel:
        def invoke(self, messages):
            return MagicMock(content=json.dumps(payload))

    monkeypatch.setattr(
        "aetherviz_service.aetherviz.agents.edit_diagnosis_agent.create_chat_model",
        lambda kind, response_schema=None: AnalysisModel(),
    )
    monkeypatch.setattr(
        "aetherviz_service.aetherviz.agents.edit_diagnosis_agent.has_primary_llm_config",
        lambda: True,
    )

    diagnosis = _diagnose_edit_impl(
        instruction="修复播放报错",
        business_html=_html(),
        context_summary={"runtime_error": {"message": "play failed"}},
    )

    expected = extract_named_functions(_html())["play"][0].source_hash
    assert diagnosis.strategy == "function_repair"
    assert diagnosis.targets[0]["source_hash"] == expected


def test_diagnosis_downgrades_invented_local_selector_to_full_regeneration(monkeypatch) -> None:
    payload = {
        "intent": "edit",
        "scope": "business_css",
        "strategy": "css_declaration",
        "problem": "未知目标",
        "confidence": 0.9,
        "targets": [{"selector": "#missing", "kind": "css"}],
        "operations": [],
        "assertions": [],
        "allowed_scope": [],
        "requires_clarification": False,
        "clarification_question": "",
    }

    class AnalysisModel:
        def invoke(self, messages):
            return MagicMock(content=json.dumps(payload))

    monkeypatch.setattr(
        "aetherviz_service.aetherviz.agents.edit_diagnosis_agent.create_chat_model",
        lambda kind, response_schema=None: AnalysisModel(),
    )
    monkeypatch.setattr(
        "aetherviz_service.aetherviz.agents.edit_diagnosis_agent.has_primary_llm_config",
        lambda: True,
    )

    diagnosis = _diagnose_edit_impl(
        instruction="调整目标",
        business_html=_html(),
        context_summary={},
    )

    assert diagnosis.strategy == "full_html_regeneration"


def test_local_css_operation_applies_minimal_override_and_guard() -> None:
    diagnosis = EditDiagnosis(
        intent="increase_button_font",
        scope="business_css",
        strategy="css_declaration",
        problem="字号偏小",
        confidence=0.95,
        targets=({"kind": "css", "selector": "#play"},),
        operations=(
            {
                "op": "set_css",
                "selector": "#play",
                "property": "font-size",
                "value": "16px",
                "old_text": "",
                "new_text": "",
                "attribute": "",
            },
        ),
    )

    result = apply_diagnosed_operations(_html(), diagnosis)

    assert result.applied == ("set_css:#play",)
    assert "#play{font-size:16px;}" in result.html
    assert result.html.replace("\n/* aetherviz-edit */\n#play{font-size:16px;}\n", "") == _html()
    assert result.guard is not None
    assert result.guard(result.html) == []
    assert result.guard(_html()) == ["edit_css_operation_lost"]


def test_local_text_operation_requires_unique_exact_source() -> None:
    diagnosis = EditDiagnosis(
        intent="rename_label",
        scope="business_dom",
        strategy="text_or_attribute",
        problem="修改说明",
        confidence=0.9,
        targets=({"kind": "dom", "selector": ".label"},),
        operations=(
            {
                "op": "replace_text",
                "selector": ".label",
                "old_text": "旧说明",
                "new_text": "新说明",
                "property": "",
                "value": "",
                "attribute": "",
            },
        ),
    )

    result = apply_diagnosed_operations(_html(), diagnosis)

    assert result.applied == ("replace_text:.label",)
    assert "新说明" in result.html
    assert "旧说明" not in result.html


def test_runtime_diagnosis_applies_hash_guarded_function_patch(monkeypatch) -> None:
    function = extract_named_functions(_html())["play"][0]
    diagnosis = EditDiagnosis(
        intent="fix_runtime_error",
        scope="business_runtime",
        strategy="function_repair",
        problem="play 没有更新播放状态",
        confidence=0.94,
        targets=(
            {
                "kind": "function",
                "function": "play",
                "source_hash": function.source_hash,
                "evidence": "运行时堆栈指向 play",
                "confidence": 0.94,
            },
        ),
        allowed_scope=("function:play",),
    )
    replacement = {
        "replacements": [
            {
                "function": "play",
                "source_hash": function.source_hash,
                "replacement": "function play(){window.started=true;window.playState='playing'}",
            }
        ]
    }

    class RepairModel:
        def stream(self, messages):
            yield MagicMock(content=json.dumps(replacement))

    monkeypatch.setattr(
        "aetherviz_service.aetherviz.agents.edit_function_agent.create_chat_model",
        lambda kind: RepairModel(),
    )
    monkeypatch.setattr(
        "aetherviz_service.aetherviz.agents.edit_function_agent.has_primary_llm_config",
        lambda: True,
    )

    result = next(
        item
        for item in stream_edit_functions(
            raw_html=_html(),
            instruction="修复播放",
            diagnosis=diagnosis,
            runtime_error={"message": "play failed", "stack": "at play"},
        )
        if isinstance(item, HtmlStreamResult)
    )

    assert result.strategy == "function_patch"
    assert result.patch_functions == ("play",)
    assert "window.playState='playing'" in result.html
    guard = build_diagnosis_guard(diagnosis, _html())
    assert guard(_html()) == ["edit_function_not_changed:play"]
    assert guard(result.html) == []


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
