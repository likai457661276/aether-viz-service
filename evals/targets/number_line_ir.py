"""Local targets for deterministic number-line IR and Runtime regression."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from playwright.sync_api import sync_playwright

from aetherviz_service.aetherviz.contracts.layout import assemble_layout_contract
from aetherviz_service.aetherviz.ir.number_line.contract import repair_number_line_ir, validate_number_line_ir
from aetherviz_service.aetherviz.ir.number_line.runtime import assemble_number_line_business_html


def run_number_line_ir_repair(inputs: dict[str, Any]) -> dict[str, Any]:
    plan = inputs.get("plan") if isinstance(inputs.get("plan"), dict) else {}
    candidate = inputs.get("candidate")
    before = validate_number_line_ir(candidate, plan)
    repaired = repair_number_line_ir(candidate, plan)
    after = validate_number_line_ir(repaired, plan)
    return {
        "before_ok": before["ok"],
        "after_ok": after["ok"],
        "before_error_types": [item.get("type") for item in before["errors"]],
        "after_error_types": [item.get("type") for item in after["errors"]],
        "interval_count": len(repaired.get("intervals", [])) if isinstance(repaired, dict) else 0,
        "derived_set_count": len(repaired.get("derived_sets", [])) if isinstance(repaired, dict) else 0,
    }


def run_number_line_ir_case(inputs: dict[str, Any]) -> dict[str, Any]:
    if inputs.get("mode") == "runtime":
        return _run_derived_set_runtime(inputs)
    return run_number_line_ir_repair(inputs)


def _run_derived_set_runtime(inputs: dict[str, Any]) -> dict[str, Any]:
    plan = inputs.get("plan") if isinstance(inputs.get("plan"), dict) else {}
    candidate = inputs.get("candidate") if isinstance(inputs.get("candidate"), dict) else {}
    report = validate_number_line_ir(candidate, plan)
    if not report["ok"]:
        return {"validation_errors": [item.get("type") for item in report["errors"]], "segment_counts": []}
    html = assemble_layout_contract(
        assemble_number_line_business_html(candidate, plan, str(inputs.get("case_id") or "数轴集合运算")),
        plan,
    )
    errors: list[str] = []
    segment_counts: list[dict[str, int]] = []
    with TemporaryDirectory(prefix="aetherviz-number-line-") as temporary_directory:
        html_path = Path(temporary_directory) / "case.html"
        html_path.write_text(html, encoding="utf-8")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(html_path.resolve().as_uri(), wait_until="load")
            page.wait_for_function("window.__AETHERVIZ_RUNTIME_READY__ === true")
            for state in inputs.get("states", []):
                page.evaluate("state => window.AetherVizRuntime.update(state)", state)
                segment_counts.append(
                    page.eval_on_selector_all(
                        '[data-kind="derived_set"]',
                        "nodes => Object.fromEntries(nodes.map(node => [node.dataset.object, Number(node.dataset.segmentCount)]))",
                    )
                )
            browser.close()
    return {"validation_errors": [], "runtime_errors": errors, "segment_counts": segment_counts}
