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
