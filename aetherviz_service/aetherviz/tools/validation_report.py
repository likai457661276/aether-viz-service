"""Structured validation report aggregation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

from aetherviz_service.aetherviz.tools.html_parser import check_html_structure
from aetherviz_service.aetherviz.tools.js_checker import check_inline_javascript
from aetherviz_service.aetherviz.tools.length_checker import check_length
from aetherviz_service.aetherviz.tools.security_checker import check_security


def build_validation_report(
    html: str,
    *,
    html_path: Path | None = None,
    report_path: Path | None = None,
) -> dict[str, Any]:
    checks = run_validation_checks(html)
    errors = [error for check in checks.values() for error in check["errors"]]
    warnings = [warning for check in checks.values() for warning in check["warnings"]]
    report = {
        "ok": not errors,
        "severity": "error" if errors else "warning" if warnings else "info",
        "summary": "检查通过" if not errors else f"发现 {len(errors)} 个硬性错误",
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
        "artifacts": {
            "html_path": str(html_path) if html_path else None,
            "report_path": str(report_path) if report_path else None,
        },
    }
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def run_validation_checks(html: str) -> dict[str, dict[str, Any]]:
    parsed = BeautifulSoup(html or "", "html.parser")
    return {
        "length_checker": check_length(html),
        "html_parser": check_html_structure(html, soup=parsed),
        "js_checker": check_inline_javascript(html, soup=parsed),
        "security_checker": check_security(html, soup=parsed),
    }
