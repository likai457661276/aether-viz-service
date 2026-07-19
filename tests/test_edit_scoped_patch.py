from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from aetherviz_service.aetherviz.contracts.html_stream import HtmlGenerationError, HtmlStreamResult
from aetherviz_service.aetherviz.edit.diagnosis import EditDiagnosis
from aetherviz_service.aetherviz.edit.intent import IntentCheck
from aetherviz_service.aetherviz.edit.patch.scoped_model import stream_scoped_model_patch
from aetherviz_service.aetherviz.tools.css_patch import extract_named_css_rules
from aetherviz_service.aetherviz.tools.function_patch import extract_named_functions


def _html() -> str:
    return """<!DOCTYPE html><html><head><style>
#play { font-size: 12px; }
</style></head><body>
<button id="play">播放</button>
<script id="widget-config" type="application/json">{"type":"simulation"}</script>
<script>function play(){ return 1; }</script>
</body></html>"""


def _diagnosis() -> EditDiagnosis:
    functions = extract_named_functions(_html())
    css = extract_named_css_rules(_html())
    return EditDiagnosis(
        intent="edit",
        scope="business_html",
        strategy="full_html_regeneration",
        problem="enlarge play",
        confidence=0.9,
        resolved_instruction="把播放按钮字号改为 18px，并更新 play 函数返回值",
        targets=(
            {
                "kind": "function",
                "selector": "",
                "function": "play",
                "source_hash": functions["play"][0].source_hash,
                "evidence": "play function",
                "confidence": 0.9,
            },
            {
                "kind": "css",
                "selector": "#play",
                "function": "",
                "source_hash": css["#play"][0].source_hash,
                "evidence": "#play rule",
                "confidence": 0.9,
            },
        ),
        change_checks=(
            IntentCheck(
                id="c1",
                kind="html_must_differ",
                severity="hard",
                baseline_binding="must_differ",
                group="change",
            ),
        ),
        preserve_checks=(
            IntentCheck(
                id="p1",
                kind="widget_type_unchanged",
                severity="hard",
                baseline_binding="must_match",
                group="preserve",
            ),
        ),
        execution_strategy="scoped_model_patch",
    )


def test_stream_scoped_model_patch_applies_function_and_css(monkeypatch) -> None:
    html = _html()
    functions = extract_named_functions(html)
    css = extract_named_css_rules(html)
    payload = {
        "function_replacements": [
            {
                "function": "play",
                "source_hash": functions["play"][0].source_hash,
                "replacement": "function play(){ return 2; }",
            }
        ],
        "css_rule_replacements": [
            {
                "selector": "#play",
                "source_hash": css["#play"][0].source_hash,
                "replacement": "#play { font-size: 18px; }",
            }
        ],
    }

    class Model:
        def stream(self, _messages):
            chunk = MagicMock()
            chunk.content = __import__("json").dumps(payload)
            chunk.response_metadata = {}
            chunk.usage_metadata = None
            yield chunk

    monkeypatch.setattr(
        "aetherviz_service.aetherviz.edit.patch.scoped_model.has_primary_llm_config",
        lambda: True,
    )
    monkeypatch.setattr(
        "aetherviz_service.aetherviz.edit.patch.scoped_model.create_chat_model",
        lambda *_args, **_kwargs: Model(),
    )

    items = list(
        stream_scoped_model_patch(
            topic="测试",
            message="字号调大",
            current_html=html,
            diagnosis=_diagnosis(),
        )
    )
    result = next(item for item in items if isinstance(item, HtmlStreamResult))
    assert result.strategy == "scoped_model_patch"
    assert "play" in result.patch_functions
    assert "#play" in result.patch_blocks
    assert "font-size: 18px" in result.html
    assert "return 2" in result.html


def test_stream_scoped_model_patch_requires_bindable_targets(monkeypatch) -> None:
    monkeypatch.setattr(
        "aetherviz_service.aetherviz.edit.patch.scoped_model.has_primary_llm_config",
        lambda: True,
    )
    diagnosis = EditDiagnosis(
        intent="edit",
        scope="business_html",
        strategy="full_html_regeneration",
        problem="x",
        confidence=0.5,
        change_checks=(
            IntentCheck(
                id="c1",
                kind="html_must_differ",
                severity="hard",
                baseline_binding="must_differ",
                group="change",
            ),
        ),
        execution_strategy="scoped_model_patch",
    )
    with pytest.raises(HtmlGenerationError) as exc:
        list(
            stream_scoped_model_patch(
                topic="测试",
                message="改一下",
                current_html="<html></html>",
                diagnosis=diagnosis,
            )
        )
    assert exc.value.code == "edit_failed"
