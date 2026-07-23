"""Generation pipeline trace unit tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aetherviz_service.aetherviz.contracts.html_stream import HtmlGenerationError, HtmlStreamResult
from aetherviz_service.aetherviz.contracts.layout import assemble_layout_contract
from aetherviz_service.aetherviz.generate import workflow as generate_workflow
from aetherviz_service.aetherviz.ir.registry import GenerationStreamSelection
from aetherviz_service.aetherviz.ir.router.contracts import IRRouteAssessment, IRRouteDecision
from aetherviz_service.aetherviz.tools.trace_manager import TraceManager, classify_generation_error_stage
from aetherviz_service.config import settings


@pytest.fixture(autouse=True)
def _disable_external_side_effects(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "openai_api_key", None)
    monkeypatch.setattr(settings, "langsmith_tracing", False)
    monkeypatch.setattr(settings, "aetherviz_max_repair_attempts", 0)
    monkeypatch.setattr(generate_workflow, "_TRACE_OUTPUT_DIR", tmp_path)


def sample_plan(topic: str = "熵增演示") -> dict:
    return {
        "page_type": "interactive",
        "interactive_type": "simulation",
        "widget_type": "simulation",
        "scene_outline": {
            "id": "scene-main",
            "type": "interactive",
            "title": topic,
            "description": "课堂观察参数变化",
            "keyPoints": ["观察", "比较", "归纳"],
            "order": 1,
            "widgetType": "simulation",
            "widgetOutline": {},
        },
        "subject": "physics",
        "title": f"{topic}互动课件",
        "goal": f"理解{topic}的变化规律。",
        "learner_level": "初中/高中",
        "stage_layout": "顶部目标，中间主舞台，底部控制与结论。",
        "key_points": ["初始状态", "参数变化", "结论归纳"],
        "design_brief": {"main_stage": "中心曲线和运动点"},
        "interactive_spec": {
            "type": "simulation",
            "concept": topic,
            "description": "调节参数观察变化",
            "variables": [{"name": "parameter", "label": "参数", "min": 0, "max": 100, "default": 50}],
            "presets": [{"id": "default", "label": "默认", "values": {"parameter": 50}}],
            "observations": ["观察图形随参数变化"],
        },
        "widget_outline": {"state": "parameter"},
        "widget_actions": [{"type": "SET_WIDGET_STATE", "state": {"parameter": 50}}],
        "teaching_flow": [
            {"id": "observe", "label": "观察", "focus": "初始状态", "caption": "先观察。"},
            {"id": "compare", "label": "比较", "focus": "参数变化", "caption": "再比较。"},
            {"id": "conclude", "label": "归纳", "focus": "结论", "caption": "后归纳。"},
        ],
        "controls": [{"id": "parameter", "label": "参数", "type": "slider", "bind": "parameter"}],
        "formulas": [],
        "runtime": {
            "render_stack": "dom_svg",
            "animation_runtime": "gsap",
            "external_libraries": ["https://cdn.jsdelivr.net/npm/gsap@3/dist/gsap.min.js"],
        },
        "primary_color": "#22D3EE",
    }


def sample_html() -> str:
    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>熵增演示</title>
<style>body{margin:0}#aetherviz-stage{display:grid;place-items:center;min-height:240px}</style>
<script type="application/json" id="widget-config">{"type":"simulation","concept":"熵增"}</script>
</head>
<body>
<main id="aetherviz-stage"><svg viewBox="0 0 100 100"><circle id="dot" cx="20" cy="50" r="8"></circle></svg></main>
<p id="animation-caption">当前步骤：观察。</p>
<button id="play-animation">播放</button>
<button id="pause-animation">暂停</button>
<button id="reset-animation">重置</button>
<script>
const state = { progress: 0 };
const dot = document.getElementById('dot');
const caption = document.getElementById('animation-caption');
function updateVisualization(){
  state.progress = (state.progress + 1) % 100;
  dot.setAttribute('cx', String(20 + state.progress / 2));
  caption.textContent = state.progress > 50 ? '当前步骤：归纳。' : '当前步骤：观察。';
}
function play(){ updateVisualization(); }
function pause(){ state.paused = true; }
function reset(){ state.progress = 0; updateVisualization(); }
document.getElementById('play-animation').addEventListener('click', updateVisualization);
document.getElementById('pause-animation').addEventListener('click', pause);
document.getElementById('reset-animation').addEventListener('click', reset);
window.addEventListener('message', function(event) {
  const type = event.data && event.data.type;
  if (type === 'SET_WIDGET_STATE') Object.assign(state, event.data.state || {});
  if (type === 'HIGHLIGHT_ELEMENT') dot.dataset.highlighted = 'true';
  if (type === 'ANNOTATE_ELEMENT') caption.textContent = event.data.content || '';
  if (type === 'REVEAL_ELEMENT') dot.hidden = false;
});
window.AetherVizRuntime = { play, pause, reset, update: updateVisualization, getState: () => state };
window.__AETHERVIZ_RUNTIME_READY__ = true;
</script>
</body>
</html>"""


def _patch_successful_stream(monkeypatch) -> None:
    business = sample_html()

    def select_for_route(_route, *, topic, plan):
        del topic, plan

        def stream():
            yield HtmlStreamResult(html=business, degraded=False, generation_elapsed_ms=12)

        return GenerationStreamSelection(
            generation_backend="coordinate_graph_scene",
            stream_factory=stream,
        )

    monkeypatch.setattr(generate_workflow.DEFAULT_IR_REGISTRY, "select_for_route", select_for_route)


def _load_latest_trace(tmp_path: Path) -> dict:
    path = tmp_path / "generation_traces.jsonl"
    assert path.exists()
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert lines
    return json.loads(lines[-1])


def test_trace_manager_persists_success_and_failure(tmp_path: Path) -> None:
    manager = TraceManager(output_dir=tmp_path)
    manager.start_trace("run_ok", "demo")
    manager.start_stage("planning")
    manager.finish_stage("planning", {"input_prompt": "demo"})
    manager.start_stage("final_result")
    manager.finish_stage("final_result", {"status": "success"})
    manager.complete_trace()
    saved = manager.save()
    assert saved is not None
    assert saved.exists()

    failed = TraceManager(output_dir=tmp_path)
    failed.start_trace("run_fail", "demo")
    failed.start_stage("ir_generation")
    failed.fail_trace("ir_generation", "boom")
    failed.save()

    rows = [json.loads(line) for line in saved.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) == 2
    assert rows[0]["status"] == "success"
    assert rows[1]["status"] == "failed"
    assert rows[1]["failed_stage"] == "ir_generation"
    assert rows[1]["error"] == "boom"


def test_classify_generation_error_stage() -> None:
    assert classify_generation_error_stage("unsupported_ir_capability") == "ir_routing"
    assert classify_generation_error_stage("ir_generation_failed") == "ir_generation"
    assert classify_generation_error_stage("runtime_error") == "runtime_compile"
    assert classify_generation_error_stage("validation_failed") == "validation"


def test_successful_generation_writes_complete_trace(monkeypatch, tmp_path: Path) -> None:
    _patch_successful_stream(monkeypatch)
    monkeypatch.setattr(
        generate_workflow,
        "resolve_generation_route",
        lambda plan: IRRouteDecision(
            selected_backend="coordinate_graph_scene",
            source="test",
            confidence=0.9,
            plan_fingerprint="fp",
            candidates=(
                IRRouteAssessment(
                    backend_key="coordinate_graph_scene",
                    eligible=True,
                    score=1.0,
                    reasons=("test",),
                ),
            ),
            reasons=("test",),
        ),
    )

    chunks = list(
        generate_workflow.run_generate_workflow(
            run_id="run_trace_ok",
            topic="熵增演示",
            approved_plan=sample_plan(),
        )
    )
    assert any("html.done" in chunk for chunk in chunks)

    payload = _load_latest_trace(tmp_path)
    assert payload["request_id"] == "run_trace_ok"
    assert payload["status"] == "success"
    assert payload["user_prompt"] == "熵增演示"
    stage_names = [stage["name"] for stage in payload["stages"]]
    assert stage_names == [
        "planning",
        "ir_routing",
        "ir_generation",
        "runtime_compile",
        "validation",
        "final_result",
    ]
    assert all(stage["status"] == "success" for stage in payload["stages"])
    routing = next(stage for stage in payload["stages"] if stage["name"] == "ir_routing")
    assert routing["metadata"]["selected_ir"] == "coordinate_graph_scene"
    assert "coordinate_graph_scene" in routing["metadata"]["candidate_ir"]


def test_ir_router_failure_records_failed_stage(monkeypatch, tmp_path: Path) -> None:
    def boom(_plan):
        raise RuntimeError("router unavailable")

    monkeypatch.setattr(generate_workflow, "resolve_generation_route", boom)

    with pytest.raises(RuntimeError, match="router unavailable"):
        list(
            generate_workflow.run_generate_workflow(
                run_id="run_trace_router",
                topic="熵增演示",
                approved_plan=sample_plan(),
            )
        )

    payload = _load_latest_trace(tmp_path)
    assert payload["status"] == "failed"
    assert payload["failed_stage"] == "ir_routing"
    assert "router unavailable" in payload["error"]
    assert any(stage["name"] == "ir_routing" and stage["status"] == "failed" for stage in payload["stages"])


def test_runtime_compile_failure_persists_error_reason(monkeypatch, tmp_path: Path) -> None:
    def select_for_route(_route, *, topic, plan):
        del topic, plan

        def stream():
            yield HtmlStreamResult(html=sample_html(), degraded=False)

        return GenerationStreamSelection(
            generation_backend="coordinate_graph_scene",
            stream_factory=stream,
        )

    monkeypatch.setattr(generate_workflow.DEFAULT_IR_REGISTRY, "select_for_route", select_for_route)
    monkeypatch.setattr(
        generate_workflow,
        "resolve_generation_route",
        lambda plan: IRRouteDecision(
            selected_backend="coordinate_graph_scene",
            source="test",
            confidence=0.9,
            plan_fingerprint="fp",
            candidates=(),
            reasons=("test",),
        ),
    )

    def boom_assemble(html, plan):
        del html, plan
        raise RuntimeError("layout compile exploded")

    monkeypatch.setattr(
        "aetherviz_service.aetherviz.contracts.pipeline.assemble_layout_contract",
        boom_assemble,
    )

    with pytest.raises(RuntimeError, match="layout compile exploded"):
        list(
            generate_workflow.run_generate_workflow(
                run_id="run_trace_runtime",
                topic="熵增演示",
                approved_plan=sample_plan(),
            )
        )

    payload = _load_latest_trace(tmp_path)
    assert payload["status"] == "failed"
    assert payload["failed_stage"] == "runtime_compile"
    assert "layout compile exploded" in payload["error"]
    runtime_stage = next(stage for stage in payload["stages"] if stage["name"] == "runtime_compile")
    assert runtime_stage["status"] == "failed"
    assert runtime_stage["metadata"].get("compile_success") is False


def test_ir_failure_exposes_ir_repair_attempts_separately(monkeypatch, tmp_path: Path) -> None:
    def select_for_route(_route, *, topic, plan):
        del topic, plan

        def stream():
            raise HtmlGenerationError(
                "几何重排 IR 未通过确定性校验，已停止生成",
                code="ir_generation_failed",
                detail="schema:geometry_ir_semantics",
                diagnostics={"ir_repair_attempts": 1},
            )
            yield  # pragma: no cover

        return GenerationStreamSelection(
            generation_backend="recomposition_scene",
            stream_factory=stream,
        )

    monkeypatch.setattr(generate_workflow.DEFAULT_IR_REGISTRY, "select_for_route", select_for_route)
    monkeypatch.setattr(
        generate_workflow,
        "resolve_generation_route",
        lambda plan: IRRouteDecision(
            selected_backend="recomposition_scene",
            source="test",
            confidence=1.0,
            plan_fingerprint="fp",
            candidates=(),
            reasons=("test",),
        ),
    )

    chunks = list(
        generate_workflow.run_generate_workflow(
            run_id="run_trace_ir_repair",
            topic="圆的面积推导",
            approved_plan=sample_plan(),
        )
    )
    error_chunk = next(chunk for chunk in chunks if chunk.startswith("event: error"))
    payload = json.loads(next(line[6:] for line in error_chunk.splitlines() if line.startswith("data: ")))

    assert payload["metadata"]["repair_attempts"] == 0
    assert payload["metadata"]["ir_repair_attempts"] == 1
    trace = _load_latest_trace(tmp_path)
    ir_stage = next(stage for stage in trace["stages"] if stage["name"] == "ir_generation")
    assert ir_stage["metadata"]["diagnostics"]["ir_repair_attempts"] == 1


def test_unsupported_route_marks_ir_routing_failed(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        generate_workflow,
        "resolve_generation_route",
        lambda plan: IRRouteDecision(
            selected_backend=None,
            source="test",
            confidence=0.0,
            plan_fingerprint="fp",
            candidates=(
                IRRouteAssessment(
                    backend_key="coordinate_graph_scene",
                    eligible=False,
                    score=0.0,
                    exclusion_reasons=("missing capability",),
                ),
            ),
            reasons=("unsupported",),
        ),
    )

    def select_for_route(route, *, topic, plan):
        del topic, plan

        def stream():
            raise HtmlGenerationError(
                "当前教学动画超出已验证 IR 的能力范围，已停止生成",
                code="unsupported_ir_capability",
                detail="missing capability",
            )
            yield  # pragma: no cover

        return GenerationStreamSelection(
            generation_backend="unsupported_ir",
            stream_factory=stream,
        )

    monkeypatch.setattr(generate_workflow.DEFAULT_IR_REGISTRY, "select_for_route", select_for_route)

    chunks = list(
        generate_workflow.run_generate_workflow(
            run_id="run_trace_unsupported",
            topic="熵增演示",
            approved_plan=sample_plan(),
        )
    )
    assert any("event: error" in chunk for chunk in chunks)

    payload = _load_latest_trace(tmp_path)
    assert payload["status"] == "failed"
    assert payload["failed_stage"] == "ir_routing"
    assert "missing capability" in payload["error"]


def test_assembled_sample_html_still_validates() -> None:
    html = assemble_layout_contract(sample_html(), sample_plan())
    assert "aetherviz-stage" in html
