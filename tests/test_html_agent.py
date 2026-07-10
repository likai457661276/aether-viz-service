"""HTML agent streaming and extraction helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

from tests.test_aetherviz import sample_html

from aetherviz_service.aetherviz.agents import html_agent
from aetherviz_service.aetherviz.agents.repair_agent import deterministic_repair_html

SAMPLE_HTML = sample_html()
from aetherviz_service.aetherviz.agents.html_agent import (
    HtmlGenerationError,
    HtmlStreamResult,
    build_html_progress_payload,
    stream_generate_html,
)


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


def test_deterministic_repair_inserts_body_close_before_html_close() -> None:
    repaired = deterministic_repair_html("<!DOCTYPE html><html><script>const ok = true;</script></html>")

    assert repaired.endswith("</body>\n</html>")


def test_stream_generate_html_emits_progress_and_result_without_llm(monkeypatch) -> None:
    monkeypatch.setattr(html_agent, "has_primary_llm_config", lambda: False)

    items = list(stream_generate_html("勾股定理", {"title": "勾股定理", "interactive_type": "diagram"}))

    assert any(isinstance(item, dict) and item.get("html_steps") for item in items)
    result = next(item for item in items if isinstance(item, HtmlStreamResult))
    assert result.degraded is True
    assert result.html.startswith("<!DOCTYPE html>")


def test_stream_generate_html_collects_direct_model_output(monkeypatch) -> None:
    class FakeModel:
        def stream(self, messages):
            yield MagicMock(content=SAMPLE_HTML, additional_kwargs={})

    monkeypatch.setattr(html_agent, "has_primary_llm_config", lambda: True)
    monkeypatch.setattr(html_agent, "create_chat_model", lambda kind: FakeModel())

    items = list(stream_generate_html("测试主题", {"title": "测试", "goal": "目标", "interactive_type": "diagram"}))
    progress = [item for item in items if isinstance(item, dict)]
    result = next(item for item in items if isinstance(item, HtmlStreamResult))

    assert progress[0]["html_steps"][0]["status"] == "in_progress"
    assert progress[-1]["html_steps"][-1]["status"] == "completed"
    assert progress[-1]["bytes"] == len(SAMPLE_HTML.encode("utf-8"))
    assert progress[-1]["chars"] == len(SAMPLE_HTML)
    assert result.degraded is False
    assert "aetherviz-stage" in result.html
    assert "play-animation" in result.html


def test_stream_generate_html_reports_reasoning_duration_without_content(monkeypatch) -> None:
    class FakeModel:
        def stream(self, messages):
            yield MagicMock(content="", additional_kwargs={"reasoning_content": "private reasoning"})
            yield MagicMock(content=SAMPLE_HTML, additional_kwargs={})

    monkeypatch.setattr(html_agent, "has_primary_llm_config", lambda: True)
    monkeypatch.setattr(html_agent, "create_chat_model", lambda kind: FakeModel())
    monkeypatch.setattr(html_agent.settings, "aetherviz_html_enable_thinking", True)

    items = list(stream_generate_html("测试主题", {"title": "测试", "goal": "目标", "interactive_type": "diagram"}))
    reasoning_events = [item for item in items if isinstance(item, dict) and "reasoning_elapsed_ms" in item]
    result = next(item for item in items if isinstance(item, HtmlStreamResult))

    assert reasoning_events
    assert reasoning_events[-1]["reasoning_active"] is False
    assert all("private reasoning" not in str(item) for item in items)
    assert result.reasoning_elapsed_ms >= 0


def test_stream_generate_html_reports_accumulated_size_while_streaming(monkeypatch) -> None:
    midpoint = len(SAMPLE_HTML) // 2

    class FakeModel:
        def stream(self, messages):
            yield MagicMock(content=SAMPLE_HTML[:midpoint], additional_kwargs={})
            yield MagicMock(content=SAMPLE_HTML[midpoint:], additional_kwargs={})

    monkeypatch.setattr(html_agent, "has_primary_llm_config", lambda: True)
    monkeypatch.setattr(html_agent, "create_chat_model", lambda kind: FakeModel())

    items = list(stream_generate_html("测试主题", {"title": "测试", "goal": "目标", "interactive_type": "diagram"}))
    size_events = [item for item in items if isinstance(item, dict) and item.get("bytes")]

    assert len(size_events) >= 2
    assert size_events[0]["bytes"] < size_events[-1]["bytes"]
    assert size_events[-1]["bytes"] == len(SAMPLE_HTML.encode("utf-8"))


def test_stream_generate_html_uses_valid_partial_output_after_stream_failure(monkeypatch) -> None:
    class FailingModel:
        def stream(self, messages):
            yield MagicMock(content=SAMPLE_HTML, additional_kwargs={})
            raise RuntimeError("boom")

    monkeypatch.setattr(html_agent, "has_primary_llm_config", lambda: True)
    monkeypatch.setattr(html_agent, "create_chat_model", lambda kind: FailingModel())

    result = next(
        item
        for item in stream_generate_html("测试主题", {"title": "测试", "goal": "目标", "interactive_type": "diagram"})
        if isinstance(item, HtmlStreamResult)
    )

    assert result.degraded is True
    assert "aetherviz-stage" in result.html


def test_stream_generate_html_raises_on_complete_failure(monkeypatch) -> None:
    class EmptyFailingModel:
        def stream(self, messages):
            raise RuntimeError("boom")

    monkeypatch.setattr(html_agent, "has_primary_llm_config", lambda: True)
    monkeypatch.setattr(html_agent, "create_chat_model", lambda kind: EmptyFailingModel())

    try:
        list(stream_generate_html("测试主题", {"title": "测试", "goal": "目标", "interactive_type": "diagram"}))
        raised = False
    except HtmlGenerationError as exc:
        raised = True
        assert exc.code == "generation_failed"
        assert "未获得可用页面" in exc.message

    assert raised
