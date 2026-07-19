"""Semantic role aliases for edit target resolution.

Maps stable control / region roles onto existing HTML conventions
(#play-animation, data-region, data-role="main-visual") and optional
data-edit-role / data-edit-entity markers.
"""

from __future__ import annotations

from typing import Any

from bs4 import BeautifulSoup, Tag

ROLE_SELECTOR_ALIASES: dict[str, tuple[str, ...]] = {
    "play-control": ("#play-animation", "[data-edit-role='play-control']", "button#play-animation"),
    "pause-control": ("#pause-animation", "[data-edit-role='pause-control']"),
    "reset-control": ("#reset-animation", "[data-edit-role='reset-control']"),
    "primary-visual": (
        "[data-role='main-visual']",
        "#aetherviz-stage > svg",
        "#aetherviz-stage > canvas",
        "[data-edit-role='primary-visual']",
    ),
    "controls": ("[data-region='controls']", ".control-panel"),
    "explanation-panel": ("[data-region='caption']", "[data-edit-role='explanation-panel']"),
    "formula-panel": ("[data-region='formula']", "[data-edit-role='formula-panel']"),
    "teaching-flow": ("[data-region='teaching-flow']", "[data-edit-role='teaching-flow']"),
    "instruction-panel": ("[data-region='caption']", "[data-edit-role='instruction-panel']"),
}

KEYWORD_ROLE_HINTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("播放", "开始动画", "play"), "play-control"),
    (("暂停", "pause"), "pause-control"),
    (("重置", "复位", "reset"), "reset-control"),
    (("主图", "主视觉", "舞台", "图形", "主画面"), "primary-visual"),
    (("控制区", "控件", "控制面板", "按钮区"), "controls"),
    (("说明", "旁白", "caption", "提示框"), "explanation-panel"),
    (("公式", "结论"), "formula-panel"),
    (("教学流程", "步骤", "流程"), "teaching-flow"),
)


def resolve_role_selector(role: str, soup: BeautifulSoup | None = None) -> str:
    """Return the first selector for ``role`` that exists in ``soup``, else the primary alias."""

    candidates = ROLE_SELECTOR_ALIASES.get(role, ())
    if not candidates:
        if role:
            edit_role = f"[data-edit-role='{role}']"
            if soup is None:
                return edit_role
            try:
                if soup.select(edit_role):
                    return edit_role
            except Exception:
                return ""
            return ""
        return ""
    if soup is None:
        return candidates[0]
    for selector in candidates:
        try:
            if soup.select(selector):
                return selector
        except Exception:
            continue
    return candidates[0]


def infer_roles_from_instruction(instruction: str) -> list[str]:
    text = instruction or ""
    roles: list[str] = []
    for keywords, role in KEYWORD_ROLE_HINTS:
        if any(keyword in text for keyword in keywords) and role not in roles:
            roles.append(role)
    return roles


def build_role_hints(soup: BeautifulSoup, *, instruction: str = "") -> list[dict[str, Any]]:
    """Deterministic role inventory for edit diagnosis context."""

    hints: list[dict[str, Any]] = []
    inferred = set(infer_roles_from_instruction(instruction))
    for role, selectors in ROLE_SELECTOR_ALIASES.items():
        matched_selector = ""
        text = ""
        for selector in selectors:
            try:
                elements = soup.select(selector)
            except Exception:
                elements = []
            if not elements:
                continue
            matched_selector = selector
            first = elements[0]
            if isinstance(first, Tag):
                text = " ".join(first.get_text(" ", strip=True).split())[:100]
            break
        edit_role_nodes = []
        try:
            edit_role_nodes = soup.select(f"[data-edit-role='{role}']")
        except Exception:
            edit_role_nodes = []
        if not matched_selector and not edit_role_nodes and role not in inferred:
            continue
        if not matched_selector and edit_role_nodes:
            matched_selector = f"[data-edit-role='{role}']"
            text = " ".join(edit_role_nodes[0].get_text(" ", strip=True).split())[:100]
        hints.append(
            {
                "role": role,
                "selector": matched_selector,
                "text": text,
                "present": bool(matched_selector),
                "instruction_match": role in inferred,
                "edit_role_count": len(edit_role_nodes),
            }
        )
    # Also surface any extra data-edit-role markers not in the alias table.
    seen_roles = {item["role"] for item in hints}
    for element in soup.select("[data-edit-role]"):
        if not isinstance(element, Tag):
            continue
        role = str(element.get("data-edit-role") or "").strip()
        if not role or role in seen_roles:
            continue
        seen_roles.add(role)
        entity = str(element.get("data-edit-entity") or "").strip()
        hints.append(
            {
                "role": role,
                "selector": f"[data-edit-role='{role}']",
                "text": " ".join(element.get_text(" ", strip=True).split())[:100],
                "present": True,
                "instruction_match": role in inferred,
                "edit_role_count": 1,
                "entity": entity,
            }
        )
    return hints[:40]
