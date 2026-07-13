"""Structured validation report aggregation."""

from __future__ import annotations

from typing import Any

from bs4 import BeautifulSoup

from aetherviz_service.aetherviz.tools.animation_lifecycle_checker import check_animation_lifecycle
from aetherviz_service.aetherviz.tools.discipline_consistency_checker import check_discipline_consistency
from aetherviz_service.aetherviz.tools.html_parser import check_html_structure
from aetherviz_service.aetherviz.tools.js_checker import check_inline_javascript
from aetherviz_service.aetherviz.tools.layout_contract_checker import check_layout_contract
from aetherviz_service.aetherviz.tools.length_checker import check_length
from aetherviz_service.aetherviz.tools.security_checker import check_security
from aetherviz_service.aetherviz.tools.widget_contract_checker import check_widget_runtime_contract


def build_validation_report(
    html: str,
    *,
    plan: dict[str, Any] | None = None,
    model_html: str | None = None,
) -> dict[str, Any]:
    checks = run_validation_checks(html, plan=plan, model_html=model_html)
    errors = [error for check in checks.values() for error in check["errors"]]
    warnings = [warning for check in checks.values() for warning in check["warnings"]]
    report = {
        "ok": not errors,
        "severity": "error" if errors else "warning" if warnings else "info",
        "summary": "检查通过" if not errors else f"发现 {len(errors)} 个硬性错误",
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
    }
    return report


def run_validation_checks(
    html: str,
    *,
    plan: dict[str, Any] | None = None,
    model_html: str | None = None,
) -> dict[str, dict[str, Any]]:
    parsed = BeautifulSoup(html or "", "html.parser")
    return {
        "layout_contract": check_layout_contract(html, soup=parsed),
        "length_checker": check_length(model_html if model_html is not None else html, scope="model"),
        "assembled_length_checker": check_length(html, scope="assembled"),
        "html_parser": check_html_structure(html, soup=parsed),
        "js_checker": check_inline_javascript(html, soup=parsed),
        "security_checker": check_security(html, soup=parsed),
        "widget_contract_checker": check_widget_runtime_contract(html, soup=parsed),
        "animation_lifecycle_checker": check_animation_lifecycle(html, soup=parsed),
        "discipline_consistency_checker": check_discipline_consistency(html, plan=plan, soup=parsed),
    }
