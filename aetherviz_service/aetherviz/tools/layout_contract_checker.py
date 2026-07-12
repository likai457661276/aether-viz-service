"""Static validation for the server-owned page shell."""

from __future__ import annotations

from bs4 import BeautifulSoup

from aetherviz_service.aetherviz.tools.layout_contract import LAYOUT_CONTRACT_VERSION


def check_layout_contract(html: str, *, soup: BeautifulSoup | None = None) -> dict:
    parsed = soup or BeautifulSoup(html or "", "html.parser")
    errors: list[dict] = []
    body = parsed.body
    shell = parsed.select_one("#aetherviz-app-shell")
    if body is None or body.get("data-layout-contract") != LAYOUT_CONTRACT_VERSION:
        errors.append(_error("missing_layout_contract", "页面未声明服务端布局契约"))
    if shell is None or shell.get("data-layout-version") != LAYOUT_CONTRACT_VERSION:
        errors.append(_error("missing_layout_shell", "缺少服务端标准布局骨架"))
    else:
        required = {
            "stage": '#aetherviz-stage[data-layout-slot="stage"]',
            "inspector": '[data-layout-slot="inspector"]',
            "primary-controls": '[data-layout-slot="primary-controls"]',
            "status": '[data-layout-slot="status"]',
            "details": '[data-layout-slot="details"]',
        }
        for name, selector in required.items():
            nodes = shell.select(selector)
            if len(nodes) != 1:
                errors.append(_error("invalid_layout_slot", f"布局槽位 {name} 必须且只能出现一次"))
    styles = parsed.select(f'style[data-aetherviz-layout-contract="{LAYOUT_CONTRACT_VERSION}"]')
    if len(styles) != 1:
        errors.append(_error("invalid_layout_styles", "服务端布局样式必须且只能出现一次"))
    return {
        "ok": not errors,
        "severity": "error" if errors else "info",
        "summary": "服务端布局契约检查完成",
        "errors": errors,
        "warnings": [],
    }


def _error(kind: str, message: str) -> dict:
    return {
        "type": kind,
        "message": message,
        "line": None,
        "expected": {"phase": "server_assembly", "layout_version": LAYOUT_CONTRACT_VERSION},
    }
