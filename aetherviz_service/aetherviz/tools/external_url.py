"""Canonical external-resource URL validation shared by config and HTML checks."""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit


def normalize_allowed_external_url(url: str) -> str:
    """Return the canonical form accepted by the generated-HTML allowlist."""
    normalized = (url or "").strip()
    parsed = urlsplit(normalized)
    if parsed.scheme.lower() != "https" or not parsed.netloc:
        raise ValueError("external URL must be absolute HTTPS")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("external URL must not contain credentials, query, or fragment")
    host = (parsed.hostname or "").lower()
    port = f":{parsed.port}" if parsed.port and parsed.port != 443 else ""
    return urlunsplit(("https", f"{host}{port}", parsed.path or "/", "", ""))
