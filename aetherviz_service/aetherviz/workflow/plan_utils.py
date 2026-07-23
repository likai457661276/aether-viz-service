"""Shared helpers for teaching-plan and generation-spec normalization."""

from __future__ import annotations

import re
from typing import Any

DEFAULT_PRIMARY_COLOR = "#22D3EE"
HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def safe_str(value: object) -> str:
    return str(value).strip() if value is not None else ""


def string_list(value: object, default: list[str], max_items: int, max_len: int = 60) -> list[str]:
    if not isinstance(value, list):
        return list(default[:max_items])
    items = [str(item).strip()[:max_len] for item in value if str(item).strip()]
    return items[:max_items] or list(default[:max_items])


def normalize_primary_color(value: object, default: str) -> str:
    normalized = safe_str(value)
    return normalized.upper() if HEX_COLOR_RE.fullmatch(normalized) else default.upper()


def safe_number(value: object, default: int | float) -> int | float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return value
    try:
        parsed = float(str(value))
    except (TypeError, ValueError):
        return default
    return int(parsed) if parsed.is_integer() else parsed


def clamp(value: int | float, minimum: int | float, maximum: int | float) -> int | float:
    clamped = min(max(float(value), float(minimum)), float(maximum))
    return int(clamped) if clamped.is_integer() else clamped
