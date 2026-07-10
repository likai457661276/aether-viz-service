"""HTML agent streaming and extraction helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

from tests.test_aetherviz import sample_html

from aetherviz_service.aetherviz.agents import html_agent

SAMPLE_HTML = sample_html()
from aetherviz_service.aetherviz.agents.html_agent import (
    HtmlGenerationError,
    HtmlStreamResult,
    _extract_html_from_agent_state,
    _extract_ready_html_from_files,
    _is_ready_html_document,
    build_html_progress_payload,
    stream_generate_html,
)


def test_extract_html_from_agent_state_prefers_widget_file() -> None:
    state = {
        "files": {
            "/notes.txt": "not html",
            "/widget.html": "<!DOCTYPE html><html><body>ok</body></html>",
        }
    }

    assert _extract_html_from_agent_state(state).startswith("<!DOCTYPE html>")


def test_extract_ready_html_from_files_requires_complete_document() -> None:
    short_html = "<!DOCTYPE html><html><body>ok</body></html>"
    assert _extract_ready_html_from_files({"/widget.html": short_html}) == ""
    assert _is_ready_html_document(SAMPLE_HTML)


def test_build_html_progress_payload_marks_active_step() -> None:
    payload = build_html_progress_payload(
        [
            {"content": "写入完整 HTML 初稿", "status": "completed"},
            {"content": "输出最终 HTML 文档", "status": "in_progress"},
        ]
    )

    assert payload["active_step_index"] == 1
    assert payload["html_steps"][1]["status"] == "in_progress"
    assert payload["delta"].startswith("正在")


def test_stream_generate_html_emits_progress_and_result_without_llm(monkeypatch) -> None:
    monkeypatch.setattr(html_agent, "has_primary_llm_config", lambda: False)

    items = list(stream_generate_html("勾股定理", {"title": "勾股定理", "interactive_type": "diagram"}))

    assert any(isinstance(item, dict) and item.get("html_steps") for item in items)
    result = next(item for item in items if isinstance(item, HtmlStreamResult))
    assert result.degraded is True
    assert result.html.startswith("<!DOCTYPE html>")


def test_stream_generate_html_exits_early_after_widget_file_write(monkeypatch) -> None:
    class FakeAgent:
        def stream(self, input, stream_mode=None, config=None):
            yield (
                "updates",
                {"tools": {"files": {"/widget.html": SAMPLE_HTML}}},
            )

    monkeypatch.setattr(html_agent, "has_primary_llm_config", lambda: True)
    monkeypatch.setattr(html_agent, "create_agent_app", lambda *args, **kwargs: FakeAgent())

    items = list(stream_generate_html("测试主题", {"title": "测试", "goal": "目标", "interactive_type": "diagram"}))
    progress = [item for item in items if isinstance(item, dict)]
    result = next(item for item in items if isinstance(item, HtmlStreamResult))

    assert progress[0]["html_steps"][0]["status"] == "in_progress"
    assert progress[-1]["html_steps"][-1]["status"] == "completed"
    assert result.degraded is False
    assert "aetherviz-stage" in result.html
    assert "play-animation" in result.html


def test_stream_generate_html_returns_early_when_values_contain_ready_html(monkeypatch) -> None:
    class FailingAgent:
        def stream(self, input, stream_mode=None, config=None):
            yield (
                "values",
                {
                    "files": {
                        "/widget.html": SAMPLE_HTML,
                    },
                    "messages": [MagicMock(content="")],
                },
            )
            raise RuntimeError("boom")

    monkeypatch.setattr(html_agent, "has_primary_llm_config", lambda: True)
    monkeypatch.setattr(html_agent, "create_agent_app", lambda *args, **kwargs: FailingAgent())

    result = next(
        item
        for item in stream_generate_html("测试主题", {"title": "测试", "goal": "目标", "interactive_type": "diagram"})
        if isinstance(item, HtmlStreamResult)
    )

    assert result.degraded is False
    assert "aetherviz-stage" in result.html


def test_stream_generate_html_raises_on_complete_failure(monkeypatch) -> None:
    class EmptyFailingAgent:
        def stream(self, input, stream_mode=None, config=None):
            raise RuntimeError("boom")

    monkeypatch.setattr(html_agent, "has_primary_llm_config", lambda: True)
    monkeypatch.setattr(html_agent, "create_agent_app", lambda *args, **kwargs: EmptyFailingAgent())

    try:
        list(stream_generate_html("测试主题", {"title": "测试", "goal": "目标", "interactive_type": "diagram"}))
        raised = False
    except HtmlGenerationError as exc:
        raised = True
        assert exc.code == "generation_failed"
        assert "未获得可用页面" in exc.message

    assert raised
