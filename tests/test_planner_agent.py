"""Planning agent streaming and progress helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

from aetherviz_service.aetherviz.agents import planner_agent
from aetherviz_service.aetherviz.agents.planner_agent import (
    PlanningStreamResult,
    build_planning_progress_payload,
    extract_todos_from_stream_chunk,
    format_planning_progress_delta,
    normalize_planning_steps,
    stream_create_plan,
)

SAMPLE_PLAN_JSON = (
    '{"page_type":"interactive","interactive_type":"simulation","title":"测试","goal":"目标",'
    '"subject":"math","teaching_flow":[],"controls":[],"formulas":[],'
    '"runtime":{"render_stack":"svg","animation_runtime":"gsap","external_libraries":[]}}'
)


def test_normalize_planning_steps_filters_invalid_entries() -> None:
    steps = normalize_planning_steps(
        [
            {"content": "分析教学目标", "status": "in_progress"},
            {"task": "设计互动规格", "status": "pending"},
            {"content": "", "status": "pending"},
            "invalid",
        ]
    )

    assert steps == [
        {"content": "分析教学目标", "status": "in_progress"},
        {"content": "设计互动规格", "status": "pending"},
    ]


def test_format_planning_progress_delta_prefers_active_step() -> None:
    delta = format_planning_progress_delta(
        [
            {"content": "分析教学目标与互动类型", "status": "completed"},
            {"content": "设计互动规格", "status": "in_progress"},
            {"content": "检查 JSON 字段完整性", "status": "pending"},
        ]
    )

    assert delta == "正在设计互动规格…"


def test_extract_todos_from_stream_chunk_reads_node_updates() -> None:
    chunk = {"tools": {"todos": [{"content": "检查 JSON", "status": "completed"}]}}
    assert extract_todos_from_stream_chunk(chunk) == [{"content": "检查 JSON", "status": "completed"}]


def test_build_planning_progress_payload_includes_active_index() -> None:
    payload = build_planning_progress_payload(
        [
            {"content": "分析教学目标", "status": "completed"},
            {"content": "设计互动规格", "status": "in_progress"},
        ]
    )

    assert payload["active_step_index"] == 1
    assert payload["planning_steps"][1]["status"] == "in_progress"
    assert payload["delta"].startswith("正在")


def test_stream_create_plan_emits_progress_and_result_without_llm(monkeypatch) -> None:
    monkeypatch.setattr(planner_agent, "has_planning_llm_config", lambda: False)

    items = list(stream_create_plan("勾股定理"))

    assert any(isinstance(item, dict) and item.get("planning_steps") for item in items)
    result = next(item for item in items if isinstance(item, PlanningStreamResult))
    assert result.degraded is True
    assert result.plan["status"] == "draft"
    assert result.plan["page_type"] == "interactive"


def test_stream_create_plan_streams_single_llm_progress(monkeypatch) -> None:
    class FakeModel:
        def stream(self, messages):
            yield MagicMock(content=SAMPLE_PLAN_JSON, additional_kwargs={})

    monkeypatch.setattr(planner_agent, "has_planning_llm_config", lambda: True)
    monkeypatch.setattr(planner_agent, "create_chat_model", lambda kind: FakeModel())

    items = list(stream_create_plan("测试主题"))
    progress = [item for item in items if isinstance(item, dict)]
    result = next(item for item in items if isinstance(item, PlanningStreamResult))

    assert progress[0]["planning_steps"][0]["status"] == "in_progress"
    assert result.degraded is False
    assert result.plan["interactive_type"] == "simulation"


def test_stream_create_plan_streams_reasoning_delta(monkeypatch) -> None:
    class FakeModel:
        def stream(self, messages):
            yield MagicMock(
                content="",
                additional_kwargs={"reasoning_content": "先判断更适合互动仿真，再组织教学流程。"},
            )
            yield MagicMock(content=SAMPLE_PLAN_JSON, additional_kwargs={})

    monkeypatch.setattr(planner_agent, "has_planning_llm_config", lambda: True)
    monkeypatch.setattr(planner_agent, "create_chat_model", lambda kind: FakeModel())

    items = list(stream_create_plan("测试主题"))
    reasoning_delta = next(
        item for item in items if isinstance(item, dict) and "互动仿真" in str(item.get("delta", ""))
    )

    assert "互动仿真" in reasoning_delta["delta"]
