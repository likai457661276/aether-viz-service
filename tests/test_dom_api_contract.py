from aetherviz_service.aetherviz.tools.deterministic_repair import deterministic_repair_html
from aetherviz_service.aetherviz.tools.dom_api_contract import (
    find_dom_element_selector_mismatches,
    repair_dom_element_selector_mismatches,
)
from aetherviz_service.aetherviz.tools.validation_report import build_validation_report
from aetherviz_service.aetherviz.workflow.edit_html_workflow import _deterministic_runtime_edit


def _mismatch_html() -> str:
    return """<!DOCTYPE html><html><head></head><body>
<span data-katex="x">x</span>
<script>
function renderFormula(selector, value) {
  const element = document.querySelector(selector);
  element.textContent = value;
}
document.querySelectorAll('[data-katex]').forEach(element => {
  renderFormula(element, element.getAttribute('data-katex'));
});
</script></body></html>"""


def test_detects_and_repairs_dom_element_used_as_selector() -> None:
    html = _mismatch_html()

    assert [item.function_name for item in find_dom_element_selector_mismatches(html)] == ["renderFormula"]

    repaired, applied = repair_dom_element_selector_mismatches(html)

    assert applied == ("renderFormula",)
    assert 'typeof selector === "string"' in repaired
    assert not find_dom_element_selector_mismatches(repaired)


def test_selector_string_call_is_not_reported() -> None:
    html = """<script>
function show(selector) { return document.querySelector(selector); }
show('#target');
</script>"""

    assert not find_dom_element_selector_mismatches(html)


def test_validation_and_deterministic_generation_repair_cover_mismatch() -> None:
    html = _mismatch_html()
    report = build_validation_report(html, model_html=html)

    assert any(error["type"] == "dom_element_used_as_selector" for error in report["errors"])

    repaired = deterministic_repair_html(html, report)
    repaired_report = build_validation_report(repaired, model_html=repaired)
    assert not any(error["type"] == "dom_element_used_as_selector" for error in repaired_report["errors"])


def test_runtime_edit_uses_deterministic_function_patch() -> None:
    result = _deterministic_runtime_edit(
        _mismatch_html(),
        {"message": "Failed to execute 'querySelector': '[object HTMLSpanElement]' is not a valid selector"},
    )

    assert result is not None
    diagnosis, operation = result
    assert diagnosis.targets[0]["function"] == "renderFormula"
    assert operation.strategy == "function_patch"
    assert operation.applied == ("function:renderFormula",)
    assert operation.guard is not None
    assert operation.guard(operation.html) == []


def test_deterministic_runtime_repair_does_not_short_circuit_full_edit(monkeypatch) -> None:
    from aetherviz_service.aetherviz.agents.html_agent import HtmlStreamResult
    from aetherviz_service.aetherviz.workflow import edit_html_workflow

    deterministic = _deterministic_runtime_edit(
        _mismatch_html(),
        {"message": "Failed to execute 'querySelector': '[object HTMLSpanElement]' is not a valid selector"},
    )
    assert deterministic is not None
    diagnosis, operation = deterministic
    captured: dict[str, str] = {}

    def fake_full_edit(**kwargs):
        captured.update(kwargs)
        yield HtmlStreamResult(
            html=kwargs["current_html"].replace("</body>", "<p>动画已改变</p></body>"),
            degraded=False,
            strategy="full_html_regeneration",
        )

    monkeypatch.setattr(edit_html_workflow, "_stream_full_html_edit", fake_full_edit)

    items = list(
        edit_html_workflow._stream_diagnosed_edit(
            topic="联动动画",
            message="修复错误并改变运动轨迹",
            current_html=operation.html,
            diagnosis=diagnosis,
            context_summary={"runtime_error": {"message": "querySelector error"}},
        )
    )

    assert captured["current_html"] == operation.html
    assert "改变运动轨迹" in captured["message"]
    assert any(isinstance(item, HtmlStreamResult) for item in items)


def test_workflow_rebuilds_context_and_calls_llm_after_deterministic_pre_repair(monkeypatch) -> None:
    from aetherviz_service.aetherviz.agents.edit_diagnosis_agent import EditDiagnosis
    from aetherviz_service.aetherviz.agents.html_agent import HtmlStreamResult
    from aetherviz_service.aetherviz.workflow import edit_html_workflow

    captured: dict[str, object] = {}

    def fake_diagnose_edit(**kwargs):
        captured["diagnosis_business_html"] = kwargs["business_html"]
        captured["context_summary"] = kwargs["context_summary"]
        return EditDiagnosis(
            intent="fix_and_change_animation",
            scope="animation_pipeline",
            strategy="full_html_regeneration",
            problem="修复公式渲染错误并改变动画轨迹",
            confidence=0.95,
            resolved_instruction="修复公式渲染错误，并将动画轨迹改为更明显的联动效果",
            change_requirements=("公式正常渲染", "动画轨迹产生明显变化"),
            preserve_requirements=("保持原教学内容",),
            impact_areas=("render", "animation", "runtime"),
            acceptance_criteria=("页面无 querySelector 参数错误", "播放后轨迹变化可观察"),
        )

    def fake_full_edit(**kwargs):
        captured["generation_business_html"] = kwargs["current_html"]
        captured["generation_message"] = kwargs["message"]
        yield HtmlStreamResult(
            html=kwargs["current_html"].replace("</body>", "<p>轨迹已改变</p></body>"),
            degraded=False,
            strategy="full_html_regeneration",
        )

    def fake_pipeline(**kwargs):
        captured["candidate_guard"] = kwargs["candidate_guard"]
        list(kwargs["html_stream_factory"]())
        yield "done"

    monkeypatch.setattr(edit_html_workflow, "diagnose_edit", fake_diagnose_edit)
    monkeypatch.setattr(edit_html_workflow, "_stream_full_html_edit", fake_full_edit)
    monkeypatch.setattr(edit_html_workflow, "run_html_pipeline", fake_pipeline)

    result = list(
        edit_html_workflow._run_edit_html_workflow_impl(
            run_id="runtime-pre-repair",
            current_html=_mismatch_html(),
            message="修复错误并改变动画轨迹",
            context={"topic": "联动动画"},
            runtime_error={
                "message": "Failed to execute 'querySelector': '[object HTMLSpanElement]' is not a valid selector"
            },
        )
    )

    assert result[-1] == "done"
    assert not find_dom_element_selector_mismatches(str(captured["diagnosis_business_html"]))
    assert captured["generation_business_html"] == captured["diagnosis_business_html"]
    assert "deterministic_pre_repair" in captured["context_summary"]
    assert "已编译编辑任务" in str(captured["generation_message"])
    assert callable(captured["candidate_guard"])
