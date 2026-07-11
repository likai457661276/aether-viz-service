"""HTML agent streaming and extraction helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from aetherviz_service.aetherviz.agents import html_agent
from aetherviz_service.aetherviz.tools.deterministic_repair import deterministic_repair_html
from aetherviz_service.aetherviz.tools.validation_report import build_validation_report
from tests.test_aetherviz import sample_html, sample_plan

SAMPLE_HTML = sample_html()
from aetherviz_service.aetherviz.agents.html_agent import (
    HtmlGenerationError,
    HtmlStreamResult,
    build_html_progress_payload,
    stream_generate_html,
)
from aetherviz_service.aetherviz.agents.instructions import build_interactive_generation_prompt


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


def test_generation_prompt_compacts_plan_json_without_dropping_content() -> None:
    plan = sample_plan("勾股定理")

    prompt = build_interactive_generation_prompt("勾股定理", plan)

    assert '"scene_outline":{"id":"scene-main","type":"interactive"' in prompt
    assert '"type":"simulation","concept":"勾股定理"' in prompt
    assert '"render_stack":"dom_svg","animation_runtime":"gsap"' in prompt
    assert '\n  "id": "scene-main"' not in prompt
    assert '"widgetOutline"' not in prompt
    assert prompt.count('"interactive_spec"') == 1
    assert "连续计算状态与可见展示状态分离" in prompt
    assert "描述符驱动的统一格式化入口" in prompt
    assert "共享边只绘制一次" in prompt


def test_deterministic_repair_inserts_body_close_before_html_close() -> None:
    repaired = deterministic_repair_html("<!DOCTYPE html><html><script>const ok = true;</script></html>")

    assert repaired.endswith("</body>\n</html>")


def test_deterministic_repair_restores_static_widget_contract() -> None:
    broken = SAMPLE_HTML.replace(
        '<script type="application/json" id="widget-config">{"type":"simulation","concept":"熵增"}</script>',
        "",
    )
    for control_id in ("play-animation", "pause-animation", "reset-animation"):
        broken = broken.replace(f'<button id="{control_id}">', f'<button id="legacy-{control_id}">')
    report = build_validation_report(broken)

    repaired = deterministic_repair_html(
        broken,
        report,
        plan={
            "interactive_type": "simulation",
            "interactive_spec": {"type": "simulation", "concept": "熵增"},
        },
    )
    repaired_report = build_validation_report(repaired)

    assert repaired_report["ok"] is True
    assert '<script type="application/json" id="widget-config">' in repaired
    assert all(
        f'id="{control_id}"' in repaired
        for control_id in ("play-animation", "pause-animation", "reset-animation")
    )


def test_deterministic_repair_moves_inline_events_without_model_rewrite() -> None:
    broken = SAMPLE_HTML.replace(
        '<button id="play-animation">',
        '<button id="play-animation" onclick="window.AetherVizRuntime.play()">',
    )
    report = build_validation_report(broken)

    repaired = deterministic_repair_html(broken, report)
    repaired_report = build_validation_report(repaired)

    assert repaired_report["ok"] is True
    assert "onclick=" not in repaired
    assert "addEventListener(\"click\"" in repaired
    assert "window.AetherVizRuntime.play()" in repaired


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
    assert result.first_chunk_elapsed_ms >= 1
    assert result.generation_elapsed_ms >= 0
    assert "aetherviz-stage" in result.html
    assert "play-animation" in result.html
    assert any(item.get("first_chunk_elapsed_ms", 0) >= 1 for item in progress)


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


def test_stream_generate_html_propagates_generator_exit(monkeypatch) -> None:
    class GeneratorExitModel:
        def stream(self, messages):
            yield MagicMock(content=SAMPLE_HTML, additional_kwargs={})
            raise GeneratorExit()

    monkeypatch.setattr(html_agent, "has_primary_llm_config", lambda: True)
    monkeypatch.setattr(html_agent, "create_chat_model", lambda kind: GeneratorExitModel())

    with pytest.raises(GeneratorExit):
        list(stream_generate_html("测试主题", {"title": "测试", "goal": "目标", "interactive_type": "diagram"}))


def test_stream_generate_html_closes_without_yielding_after_generator_exit(monkeypatch) -> None:
    class StreamingModel:
        def stream(self, messages):
            yield MagicMock(content=SAMPLE_HTML, additional_kwargs={})
            yield MagicMock(content="", additional_kwargs={})

    monkeypatch.setattr(html_agent, "has_primary_llm_config", lambda: True)
    monkeypatch.setattr(html_agent, "create_chat_model", lambda kind: StreamingModel())

    stream = stream_generate_html("测试主题", {"title": "测试", "goal": "目标", "interactive_type": "diagram"})
    next(stream)
    next(stream)
    stream.close()


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
