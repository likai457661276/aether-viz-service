"""Hash-guarded replacements for bounded CSS and semantic HTML regions."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from bs4 import BeautifulSoup, Tag

MAX_CONTENT_REPLACEMENTS = 4
MAX_CONTENT_SOURCE_CHARS = 8_000
MAX_CONTENT_REPLACEMENT_CHARS = 12_000

_VISUAL_REQUEST_RE = re.compile(
    r"空白|显示|图像|图形|动画|主视觉|舞台|svg|canvas|visual|render|布局|位置|尺寸",
    re.IGNORECASE,
)
_STYLE_REQUEST_RE = re.compile(
    r"颜色|字号|字体|大小|宽度|高度|间距|边距|样式|主题|对齐|布局|位置|尺寸|css|style",
    re.IGNORECASE,
)
_TEXT_REQUEST_RE = re.compile(r"文案|文字|标题|说明|结论|公式|步骤|caption|formula|title", re.IGNORECASE)


@dataclass(frozen=True)
class ContentSource:
    kind: str
    target_id: str
    source_hash: str
    source: str
    start: int
    end: int
    tag_name: str
    identity: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class ContentPatchResult:
    html: str
    applied: tuple[str, ...]
    errors: tuple[str, ...] = ()


def select_content_descriptions(html: str, instruction: str) -> list[dict[str, Any]]:
    source = html or ""
    soup = BeautifulSoup(source, "html.parser")
    text = instruction or ""
    candidates: list[tuple[str, Tag]] = []

    if _STYLE_REQUEST_RE.search(text) or _VISUAL_REQUEST_RE.search(text):
        candidates.extend(("style", tag) for tag in soup.find_all("style"))

    if _VISUAL_REQUEST_RE.search(text):
        visual = next(
            (
                tag
                for selector in (
                    '[data-role="main-visual"]',
                    '[data-region="main-visual"]',
                    "#aetherviz-stage",
                    "svg",
                    "canvas",
                )
                if isinstance((tag := soup.select_one(selector)), Tag)
            ),
            None,
        )
        if visual is not None:
            candidates.append(("visual", visual))

    if _TEXT_REQUEST_RE.search(text):
        for selector in ('[data-region="caption"]', '[data-region="formula"]', "h1", "h2"):
            tag = soup.select_one(selector)
            if isinstance(tag, Tag):
                candidates.append(("semantic", tag))

    selected: list[ContentSource] = []
    occupied: list[tuple[int, int]] = []
    for kind, tag in candidates:
        block = _describe_tag(source, kind, tag)
        if block is None or len(block.source) > MAX_CONTENT_SOURCE_CHARS:
            continue
        if any(block.start < end and start < block.end for start, end in occupied):
            continue
        selected.append(block)
        occupied.append((block.start, block.end))
        if len(selected) >= MAX_CONTENT_REPLACEMENTS:
            break

    return [
        {
            "kind": item.kind,
            "target_id": item.target_id,
            "source_hash": item.source_hash,
            "source": item.source,
            "tag": item.tag_name,
            "line": source.count("\n", 0, item.start) + 1,
        }
        for item in selected
    ]


def parse_content_replacements(raw_text: str) -> list[dict[str, str]]:
    payload = _parse_json_object(raw_text)
    raw_replacements = payload.get("blocks") if isinstance(payload, dict) else None
    if not isinstance(raw_replacements, list):
        return []
    return [
        {
            "kind": str(item.get("kind") or ""),
            "target_id": str(item.get("target_id") or ""),
            "source_hash": str(item.get("source_hash") or ""),
            "replacement": str(item.get("replacement") or ""),
        }
        for item in raw_replacements[:MAX_CONTENT_REPLACEMENTS]
        if isinstance(item, dict)
    ]


def apply_content_replacements(
    html: str,
    replacements: list[dict[str, str]],
    *,
    allowed_descriptions: list[dict[str, Any]],
) -> ContentPatchResult:
    if not replacements:
        return ContentPatchResult(html=html, applied=())
    if len(replacements) > MAX_CONTENT_REPLACEMENTS:
        return ContentPatchResult(html=html, applied=(), errors=("too_many_content_replacements",))
    if sum(len(item.get("replacement", "")) for item in replacements) > MAX_CONTENT_REPLACEMENT_CHARS:
        return ContentPatchResult(html=html, applied=(), errors=("content_replacement_too_long",))

    allowed = {str(item["target_id"]): item for item in allowed_descriptions}
    patches: list[tuple[int, int, str, str]] = []
    errors: list[str] = []
    seen: set[str] = set()
    for item in replacements:
        target_id = item.get("target_id", "")
        if target_id in seen:
            errors.append(f"duplicate_content_replacement:{target_id}")
            continue
        seen.add(target_id)
        description = allowed.get(target_id)
        if description is None:
            errors.append(f"content_target_not_allowed:{target_id}")
            continue
        if item.get("kind") != description.get("kind"):
            errors.append(f"content_kind_mismatch:{target_id}")
            continue
        if item.get("source_hash") != description.get("source_hash"):
            errors.append(f"content_source_hash_mismatch:{target_id}")
            continue
        original = str(description.get("source") or "")
        start = html.find(original)
        if start < 0 or html.find(original, start + 1) >= 0:
            errors.append(f"content_source_not_unique:{target_id}")
            continue
        replacement = item.get("replacement", "").strip()
        validation_error = _validate_replacement(original, replacement, target_id)
        if validation_error:
            errors.append(validation_error)
            continue
        if replacement == original.strip():
            errors.append(f"unchanged_content_replacement:{target_id}")
            continue
        patches.append((start, start + len(original), replacement, target_id))

    if errors or not patches:
        return ContentPatchResult(html=html, applied=(), errors=tuple(errors or ["no_valid_content_replacements"]))
    updated = html
    for start, end, replacement, _target_id in sorted(patches, reverse=True):
        updated = updated[:start] + replacement + updated[end:]
    return ContentPatchResult(
        html=updated,
        applied=tuple(target_id for _start, _end, _replacement, target_id in patches),
    )


def _describe_tag(html: str, kind: str, tag: Tag) -> ContentSource | None:
    span = _tag_source_span(html, tag)
    if span is None:
        return None
    start, end = span
    source = html[start:end]
    source_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
    identity = tuple(
        (name, str(tag.get(name)))
        for name in ("id", "data-role", "data-region")
        if tag.get(name) is not None
    )
    target_id = f"{kind}:{tag.name}:{start}:{source_hash[:12]}"
    return ContentSource(
        kind=kind,
        target_id=target_id,
        source_hash=source_hash,
        source=source,
        start=start,
        end=end,
        tag_name=tag.name,
        identity=identity,
    )


def _tag_source_span(html: str, tag: Tag) -> tuple[int, int] | None:
    if tag.sourceline is None or tag.sourcepos is None:
        return None
    lines = html.splitlines(keepends=True)
    if tag.sourceline < 1 or tag.sourceline > len(lines):
        return None
    start = sum(len(line) for line in lines[: tag.sourceline - 1]) + tag.sourcepos
    token_re = re.compile(rf"<\s*(/?)\s*{re.escape(tag.name)}\b[^>]*>", re.IGNORECASE)
    depth = 0
    for match in token_re.finditer(html, start):
        if match.start() == start and match.group(1):
            return None
        depth += -1 if match.group(1) else 1
        if depth == 0:
            return start, match.end()
    return None


def _validate_replacement(original: str, replacement: str, target_id: str) -> str | None:
    if not replacement:
        return f"empty_content_replacement:{target_id}"
    if "<script" in replacement.lower() or "</script" in replacement.lower():
        return f"content_script_not_allowed:{target_id}"
    original_root = _single_root(original)
    replacement_root = _single_root(replacement)
    if original_root is None or replacement_root is None or original_root.name != replacement_root.name:
        return f"content_root_mismatch:{target_id}"
    for attribute in ("id", "data-role", "data-region"):
        if original_root.get(attribute) != replacement_root.get(attribute):
            return f"content_identity_mismatch:{target_id}:{attribute}"
    return None


def _single_root(source: str) -> Tag | None:
    soup = BeautifulSoup(source, "html.parser")
    roots = [item for item in soup.contents if isinstance(item, Tag)]
    return roots[0] if len(roots) == 1 else None


def _parse_json_object(raw_text: str) -> dict[str, Any]:
    text = (raw_text or "").strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        text = match.group(0)
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}
