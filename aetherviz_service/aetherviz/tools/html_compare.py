"""Shared normalization for detecting transport-only HTML changes."""

from __future__ import annotations


def normalize_html_for_compare(html: str) -> str:
    normalized = (html or "").strip().replace("\r\n", "\n")
    if normalized.startswith("```"):
        newline = normalized.find("\n")
        normalized = normalized[newline + 1 :] if newline >= 0 else ""
    if normalized.endswith("```"):
        normalized = normalized[:-3]
    return "".join(normalized.split())
