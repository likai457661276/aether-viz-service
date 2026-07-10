"""Low-cost runtime contract checks for generated interactive HTML."""

from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup

REQUIRED_CONTROL_IDS = ("play-animation", "pause-animation", "reset-animation")
REQUIRED_RUNTIME_METHODS = ("play", "pause", "reset", "update", "getState")
REQUIRED_WIDGET_ACTIONS = (
    "SET_WIDGET_STATE",
    "HIGHLIGHT_ELEMENT",
    "ANNOTATE_ELEMENT",
    "REVEAL_ELEMENT",
)
ALLOWED_WIDGET_TYPES = {"simulation", "diagram", "game"}


def check_widget_runtime_contract(html: str, *, soup: BeautifulSoup | None = None) -> dict:
    parsed = soup or BeautifulSoup(html or "", "html.parser")
    errors: list[dict] = []
    warnings: list[dict] = []

    _check_widget_config(parsed, errors)
    _check_stage(parsed, errors)
    _check_controls(parsed, errors)

    script_text = "\n".join(
        script.get_text("\n", strip=False)
        for script in parsed.find_all("script")
        if not script.get("src") and str(script.get("type", "")).lower() != "application/json"
    )
    if not re.search(r"\bAetherVizRuntime\s*=", script_text):
        errors.append(_error("missing_runtime", "缺少 window.AetherVizRuntime 运行时对象"))
    else:
        for method in REQUIRED_RUNTIME_METHODS:
            if not re.search(rf"\b{re.escape(method)}\b", script_text):
                errors.append(_error("missing_runtime_method", f"AetherVizRuntime 缺少 {method} 方法"))

    if not re.search(r"__AETHERVIZ_RUNTIME_READY__\s*=\s*true", script_text):
        errors.append(_error("missing_runtime_ready", "缺少运行时就绪标记"))
    if not re.search(r"addEventListener\s*\(\s*['\"]message['\"]", script_text):
        errors.append(_error("missing_message_listener", "缺少 iframe widget action 消息监听器"))

    for action in REQUIRED_WIDGET_ACTIONS:
        if action not in script_text:
            warnings.append(_warning("missing_widget_action", f"未显式处理 widget action：{action}"))

    external_gsap = any("gsap" in str(script.get("src") or "").lower() for script in parsed.find_all("script"))
    if external_gsap and not re.search(r"window\.gsap|typeof\s+gsap|typeof\s+window\.gsap", script_text):
        warnings.append(_warning("missing_gsap_fallback_guard", "使用 GSAP CDN，但未检测到 native fallback 判断"))

    return {
        "ok": not errors,
        "severity": "error" if errors else "warning" if warnings else "info",
        "summary": "Widget 最小运行契约检查完成",
        "errors": errors,
        "warnings": warnings,
    }


def _check_widget_config(parsed: BeautifulSoup, errors: list[dict]) -> None:
    config = parsed.find("script", id="widget-config")
    if config is None or str(config.get("type") or "").lower() != "application/json":
        errors.append(_error("missing_widget_config", "缺少 script#widget-config[type=application/json]"))
        return
    try:
        payload = json.loads(config.get_text(strip=False))
    except (TypeError, ValueError):
        errors.append(_error("invalid_widget_config", "widget-config 不是有效 JSON"))
        return
    if not isinstance(payload, dict) or payload.get("type") not in ALLOWED_WIDGET_TYPES:
        errors.append(_error("invalid_widget_type", "widget-config.type 必须是 simulation、diagram 或 game"))


def _check_stage(parsed: BeautifulSoup, errors: list[dict]) -> None:
    stage = parsed.find(id="aetherviz-stage")
    if stage is None:
        errors.append(_error("missing_stage", "缺少 #aetherviz-stage 主舞台"))
        return
    if stage.find(["svg", "canvas"]) is None and stage.select_one("[data-role='main-visual']") is None:
        errors.append(_error("missing_stage_visual", "主舞台缺少 SVG、Canvas 或 main-visual 主体"))


def _check_controls(parsed: BeautifulSoup, errors: list[dict]) -> None:
    for control_id in REQUIRED_CONTROL_IDS:
        if parsed.find(id=control_id) is None:
            errors.append(_error("missing_control", f"缺少核心控件 #{control_id}"))


def _error(error_type: str, message: str) -> dict:
    return {"type": error_type, "message": message, "line": None}


def _warning(warning_type: str, message: str) -> dict:
    return {"type": warning_type, "message": message, "line": None}
