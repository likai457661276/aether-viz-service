"""Structured validation report aggregation."""

from __future__ import annotations

from typing import Any

from bs4 import BeautifulSoup

from aetherviz_service.aetherviz.tools.discipline_consistency_checker import check_discipline_consistency
from aetherviz_service.aetherviz.tools.html_parser import check_html_structure
from aetherviz_service.aetherviz.tools.js_checker import check_inline_javascript
from aetherviz_service.aetherviz.tools.length_checker import check_length
from aetherviz_service.aetherviz.tools.security_checker import check_security
from aetherviz_service.aetherviz.tools.widget_contract_checker import check_widget_runtime_contract


def build_validation_report(
    html: str,
    *,
    plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    checks = run_validation_checks(html, plan=plan)
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


def run_validation_checks(html: str, *, plan: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    parsed = BeautifulSoup(html or "", "html.parser")
    return {
        "length_checker": check_length(html),
        "html_parser": check_html_structure(html, soup=parsed),
        "js_checker": check_inline_javascript(html, soup=parsed),
        "security_checker": check_security(html, soup=parsed),
        "widget_contract_checker": check_widget_runtime_contract(html, soup=parsed),
        "discipline_consistency_checker": check_discipline_consistency(html, plan=plan, soup=parsed),
    }
