"""Evidence-ranked, hash-guarded replacements for bounded HTML and CSS regions."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from typing import Any

from bs4 import BeautifulSoup, Tag

from aetherviz_service.aetherviz.tools.css_patch import (
    apply_declaration_edit,
    parse_css_rules,
    stylesheet_validation_error,
)
from aetherviz_service.aetherviz.tools.edit_targeting import (
    EditEvidence,
    extract_edit_evidence,
    selector_identity,
)

MAX_CONTENT_REPLACEMENTS = 4
MAX_CONTENT_SOURCE_CHARS = 8_000
MAX_CONTENT_REPLACEMENT_CHARS = 12_000
MAX_CSS_RULE_REPLACEMENTS = 2

_VISUAL_SELECTORS = (
    '[data-role="main-visual"]',
    '[data-region="main-visual"]',
    "#aetherviz-stage",
    '[data-region="stage"]',
    "svg",
    "canvas",
)
_SEMANTIC_SELECTORS = (
    '[data-region="controls"]',
    '[data-region="caption"]',
    '[data-region="formula"]',
    '[data-region="teaching-flow"]',
    "h1",
    "h2",
)
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
    selector: str = ""
    region: str = ""
    score: int = 0
    evidence: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()
    parse_status: str = "not_applicable"
    at_rule_path: tuple[str, ...] = ()


@dataclass(frozen=True)
class ContentPatchResult:
    html: str
    applied: tuple[str, ...]
    errors: tuple[str, ...] = ()
    operations: tuple[str, ...] = ()


def select_content_descriptions(
    html: str,
    instruction: str,
    context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    source = html or ""
    soup = BeautifulSoup(source, "html.parser")
    edit_evidence = extract_edit_evidence(instruction, context)
    candidates: dict[tuple[int, int], ContentSource] = {}

    for selector in edit_evidence.explicit_selectors:
        _add_selector_candidates(candidates, source, soup, selector, score=100, reason=f"explicit_selector:{selector}")
    for selector in edit_evidence.report_selectors:
        _add_selector_candidates(candidates, source, soup, selector, score=90, reason=f"report_selector:{selector}")

    if _has_issue(edit_evidence, "visual_not_visible", "visual_change", "layout_issue"):
        for selector in _VISUAL_SELECTORS:
            _add_selector_candidates(candidates, source, soup, selector, score=50, reason=f"semantic_visual:{selector}")
    semantic_selectors = _semantic_selectors_for_intent(edit_evidence)
    for selector in semantic_selectors:
        _add_selector_candidates(candidates, source, soup, selector, score=40, reason=f"semantic_region:{selector}")

    _add_javascript_dependency_evidence(candidates, soup)
    css_candidates = _css_rule_candidates(source, soup, candidates, edit_evidence)
    for candidate in css_candidates:
        _merge_candidate(candidates, candidate)

    if _has_issue(
        edit_evidence, "style_change", "layout_issue", "visual_not_visible", "visual_change"
    ):
        for tag in soup.find_all("style"):
            block = _describe_tag(source, "style", tag)
            if block is None or len(block.source) > MAX_CONTENT_SOURCE_CHARS:
                continue
            css = tag.get_text()
            parse_status = parse_css_rules(css).status
            if not css_candidates or parse_status != "exact":
                _merge_candidate(
                    candidates,
                    replace(
                        block,
                        score=30 if parse_status != "exact" else 20,
                        evidence=(f"style_block_fallback:{parse_status}",),
                        parse_status=parse_status,
                    ),
                )

    selected = _select_ranked_candidates(tuple(candidates.values()), edit_evidence)
    return [_description_payload(item, source) for item in selected]


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


def parse_css_declaration_edits(raw_text: str) -> list[dict[str, Any]]:
    payload = _parse_json_object(raw_text)
    raw_edits = payload.get("css_edits") if isinstance(payload, dict) else None
    if not isinstance(raw_edits, list):
        return []
    result: list[dict[str, Any]] = []
    for item in raw_edits[:MAX_CSS_RULE_REPLACEMENTS]:
        if not isinstance(item, dict):
            continue
        set_values = item.get("set")
        remove = item.get("remove")
        result.append(
            {
                "target_id": str(item.get("target_id") or ""),
                "source_hash": str(item.get("source_hash") or ""),
                "set": (
                    {str(key): str(value) for key, value in set_values.items()}
                    if isinstance(set_values, dict)
                    else {}
                ),
                "remove": [str(value) for value in remove] if isinstance(remove, list) else [],
            }
        )
    return result


def apply_content_replacements(
    html: str,
    replacements: list[dict[str, str]],
    *,
    allowed_descriptions: list[dict[str, Any]],
    declaration_edits: list[dict[str, Any]] | None = None,
) -> ContentPatchResult:
    css_edits = declaration_edits or []
    if not replacements and not css_edits:
        return ContentPatchResult(html=html, applied=())
    if len(replacements) > MAX_CONTENT_REPLACEMENTS:
        return ContentPatchResult(html=html, applied=(), errors=("too_many_content_replacements",))
    edit_chars = len(json.dumps(css_edits, ensure_ascii=False, separators=(",", ":")))
    if sum(len(item.get("replacement", "")) for item in replacements) + edit_chars > MAX_CONTENT_REPLACEMENT_CHARS:
        return ContentPatchResult(html=html, applied=(), errors=("content_replacement_too_long",))

    allowed = {str(item["target_id"]): item for item in allowed_descriptions}
    patches: list[tuple[int, int, str, str]] = []
    errors: list[str] = []
    seen: set[str] = set()
    operations: list[str] = []
    combined_items: list[tuple[str, dict[str, Any]]] = [
        ("replace", item) for item in replacements
    ] + [("declarations", item) for item in css_edits]
    for operation, item in combined_items:
        target_id = item.get("target_id", "")
        if target_id in seen:
            errors.append(f"duplicate_content_replacement:{target_id}")
            continue
        seen.add(target_id)
        description = allowed.get(target_id)
        if description is None:
            errors.append(f"content_target_not_allowed:{target_id}")
            continue
        kind = str(description.get("kind") or "")
        if operation == "replace" and item.get("kind") != kind:
            errors.append(f"content_kind_mismatch:{target_id}")
            continue
        if operation == "declarations" and kind != "css_rule":
            errors.append(f"css_declaration_target_kind_mismatch:{target_id}")
            continue
        if item.get("source_hash") != description.get("source_hash"):
            errors.append(f"content_source_hash_mismatch:{target_id}")
            continue
        original = str(description.get("source") or "")
        start = int(description.get("start", -1))
        end = int(description.get("end", -1))
        if start < 0 or end < start or html[start:end] != original:
            errors.append(f"content_source_span_mismatch:{target_id}")
            continue
        if operation == "declarations":
            replacement, declaration_error = apply_declaration_edit(
                original,
                set_values=item.get("set") if isinstance(item.get("set"), dict) else {},
                remove=item.get("remove") if isinstance(item.get("remove"), list) else [],
            )
            if declaration_error or replacement is None:
                errors.append(f"{declaration_error or 'css_declaration_invalid'}:{target_id}")
                continue
        else:
            replacement = str(item.get("replacement", "")).strip()
        validation_error = _validate_replacement(original, replacement, target_id, kind)
        if validation_error:
            errors.append(validation_error)
            continue
        if replacement == original.strip():
            errors.append(f"unchanged_content_replacement:{target_id}")
            continue
        patches.append((start, end, replacement, target_id))
        operations.append("css_declarations" if operation == "declarations" else kind)

    if errors or not patches:
        return ContentPatchResult(html=html, applied=(), errors=tuple(errors or ["no_valid_content_replacements"]))
    updated = html
    for start, end, replacement, _target_id in sorted(patches, reverse=True):
        updated = updated[:start] + replacement + updated[end:]
    transaction_error = _html_stylesheet_validation_error(updated)
    css_changed = any(operation in {"css_declarations", "css_rule", "style"} for operation in operations)
    if transaction_error and (css_changed or _html_stylesheet_validation_error(html) is None):
        return ContentPatchResult(html=html, applied=(), errors=(transaction_error,))
    return ContentPatchResult(
        html=updated,
        applied=tuple(target_id for _start, _end, _replacement, target_id in patches),
        operations=tuple(operations),
    )


def content_patch_causal_error(
    before: str,
    after: str,
    instruction: str,
    *,
    context: dict[str, Any] | None,
    applied_descriptions: list[dict[str, Any]],
    function_changed: bool,
) -> str | None:
    """Reject patches that do not touch a region capable of causing the reported issue."""
    if before == after:
        return "content_patch_unchanged"
    evidence = extract_edit_evidence(instruction, context)
    kinds = {str(item.get("kind") or "") for item in applied_descriptions}
    regions = {str(item.get("region") or "") for item in applied_descriptions}
    if "visual_not_visible" in evidence.issue_types:
        if not function_changed and not kinds.intersection({"css_rule", "style", "visual"}):
            return "visual_issue_cause_not_modified"
        visual = BeautifulSoup(after, "html.parser").select_one(
            '[data-role="main-visual"], #aetherviz-stage svg, #aetherviz-stage canvas'
        )
        if visual is None:
            return "visual_target_missing_after_patch"
    content_only_text_change = (
        "text_change" in evidence.issue_types
        and "style_change" not in evidence.issue_types
        and "layout_issue" not in evidence.issue_types
    )
    if content_only_text_change and not function_changed:
        if "semantic" not in kinds and not regions.intersection({"caption", "formula", "teaching-flow"}):
            return "text_issue_cause_not_modified"
    behavior_control_issue = (
        "control_issue" in evidence.issue_types
        and "style_change" not in evidence.issue_types
        and "layout_issue" not in evidence.issue_types
    )
    if behavior_control_issue and not function_changed:
        if "controls" not in regions and "semantic" not in kinds:
            return "control_issue_cause_not_modified"
    if "style_change" in evidence.issue_types and not kinds.intersection({"css_rule", "style", "visual", "semantic"}):
        return "style_issue_cause_not_modified"
    return None


def _add_selector_candidates(
    candidates: dict[tuple[int, int], ContentSource],
    html: str,
    soup: BeautifulSoup,
    selector: str,
    *,
    score: int,
    reason: str,
) -> None:
    try:
        tags = soup.select(selector)
    except Exception:
        return
    for tag in tags[:8]:
        if not isinstance(tag, Tag) or tag.name in {"html", "body", "script", "style"}:
            continue
        block = _describe_tag(html, _kind_for_tag(tag), tag)
        if block is None or len(block.source) > MAX_CONTENT_SOURCE_CHARS:
            continue
        identities = selector_identity(tag)
        candidate = replace(
            block,
            selector=identities[0] if identities else selector,
            region=_region_for_tag(tag),
            score=score,
            evidence=(reason,),
            dependencies=identities,
        )
        _merge_candidate(candidates, candidate)


def _add_javascript_dependency_evidence(candidates: dict[tuple[int, int], ContentSource], soup: BeautifulSoup) -> None:
    script_text = "\n".join(tag.get_text("\n") for tag in soup.find_all("script"))
    if not script_text:
        return
    for span, candidate in tuple(candidates.items()):
        matched = next(
            (
                selector
                for selector in candidate.dependencies
                if selector in script_text or (selector.startswith("#") and selector[1:] in script_text)
            ),
            None,
        )
        if matched:
            candidates[span] = replace(
                candidate,
                score=max(candidate.score, 70),
                evidence=(*candidate.evidence, f"javascript_reference:{matched}"),
            )


def _css_rule_candidates(
    html: str,
    soup: BeautifulSoup,
    dom_candidates: dict[tuple[int, int], ContentSource],
    evidence: EditEvidence,
) -> list[ContentSource]:
    result: list[ContentSource] = []
    for tag in soup.find_all("style"):
        span = _tag_source_span(html, tag)
        if span is None:
            continue
        opening_end = html.find(">", span[0], span[1])
        closing_start = html.rfind("</", opening_end, span[1])
        if opening_end < 0 or closing_start < 0:
            continue
        css = html[opening_end + 1 : closing_start]
        parsed = parse_css_rules(css)
        if parsed.status != "exact":
            continue
        style_hash = hashlib.sha256(css.encode("utf-8")).hexdigest()[:12]
        for rule in parsed.rules:
            start = opening_end + 1 + rule.start
            end = opening_end + 1 + rule.end
            selector = rule.selector
            rule_source = html[start:end]
            if len(rule_source) > MAX_CONTENT_SOURCE_CHARS:
                continue
            score = 0
            reasons: list[str] = []
            dependencies: list[str] = []
            for anchor in evidence.explicit_selectors:
                if _selector_mentions(selector, anchor):
                    score = max(score, 100)
                    reasons.append(f"explicit_selector:{anchor}")
                    dependencies.append(anchor)
            for anchor in evidence.report_selectors:
                if _selector_mentions(selector, anchor):
                    score = max(score, 90)
                    reasons.append(f"report_selector:{anchor}")
                    dependencies.append(anchor)
            matched_dom = _matched_dom_candidates(soup, selector, dom_candidates)
            if matched_dom:
                score = max(score, max(60, max(item.score for item in matched_dom) - 20))
                reasons.extend(f"css_dependency:{item.selector}" for item in matched_dom[:3])
                dependencies.extend(item.selector for item in matched_dom[:3] if item.selector)
            if score == 0 and _has_issue(
                evidence, "style_change", "layout_issue", "visual_not_visible", "visual_change"
            ):
                score = 25
                reasons.append("generic_style_intent")
            if score == 0:
                continue
            source_hash = hashlib.sha256(rule_source.encode("utf-8")).hexdigest()
            path_key = ">".join(rule.at_rule_path) or "root"
            identity_hash = hashlib.sha256(
                f"{style_hash}|{path_key}|{_normalize_css_selector(selector)}|{rule.occurrence}".encode()
            ).hexdigest()[:16]
            target_id = f"css_rule:{identity_hash}:{source_hash[:12]}"
            result.append(
                ContentSource(
                    kind="css_rule",
                    target_id=target_id,
                    source_hash=source_hash,
                    source=rule_source,
                    start=start,
                    end=end,
                    tag_name="css-rule",
                    identity=(),
                    selector=selector,
                    region=_region_from_selectors(dependencies),
                    score=score,
                    evidence=tuple(dict.fromkeys(reasons)),
                    dependencies=tuple(dict.fromkeys(dependencies)),
                    parse_status=parsed.status,
                    at_rule_path=rule.at_rule_path,
                )
            )
    return result


def _matched_dom_candidates(
    soup: BeautifulSoup,
    selector: str,
    candidates: dict[tuple[int, int], ContentSource],
) -> list[ContentSource]:
    try:
        matched_tags = {id(tag) for tag in soup.select(selector)}
    except Exception:
        return []
    if not matched_tags:
        return []
    result: list[ContentSource] = []
    for candidate in candidates.values():
        if not candidate.dependencies:
            continue
        for identity in candidate.dependencies:
            try:
                if any(id(tag) in matched_tags for tag in soup.select(identity)):
                    result.append(candidate)
                    break
            except Exception:
                continue
    return result


def _select_ranked_candidates(candidates: tuple[ContentSource, ...], evidence: EditEvidence) -> list[ContentSource]:
    ranked = sorted(candidates, key=lambda item: (-item.score, len(item.source), item.start))
    selected: list[ContentSource] = []

    def add(item: ContentSource) -> bool:
        if len(selected) >= MAX_CONTENT_REPLACEMENTS:
            return False
        if item.kind == "css_rule" and sum(x.kind == "css_rule" for x in selected) >= MAX_CSS_RULE_REPLACEMENTS:
            return False
        if item.kind == "semantic" and sum(x.kind == "semantic" for x in selected) >= 1:
            return False
        if any(item.start < other.end and other.start < item.end for other in selected):
            return False
        selected.append(item)
        return True

    if _has_issue(evidence, "visual_not_visible", "visual_change", "layout_issue"):
        visual = next((item for item in ranked if item.kind == "visual"), None)
        if visual is not None:
            add(visual)
    for item in ranked:
        if item.kind == "css_rule":
            add(item)
    if _has_issue(evidence, "text_change", "control_issue"):
        semantic = next((item for item in ranked if item.kind == "semantic"), None)
        if semantic is not None:
            add(semantic)
    for item in ranked:
        add(item)
    return sorted(selected, key=lambda item: item.start)


def _describe_tag(html: str, kind: str, tag: Tag) -> ContentSource | None:
    span = _tag_source_span(html, tag)
    if span is None:
        return None
    start, end = span
    source = html[start:end]
    source_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
    identity = tuple(
        (name, str(tag.get(name))) for name in ("id", "data-role", "data-region") if tag.get(name) is not None
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


def _find_css_token(text: str, token: str, start: int) -> int | None:
    quote: str | None = None
    escaped = False
    comment = False
    index = start
    while index < len(text):
        char = text[index]
        next_char = text[index + 1] if index + 1 < len(text) else ""
        if comment:
            if char == "*" and next_char == "/":
                comment = False
                index += 2
            else:
                index += 1
            continue
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            index += 1
            continue
        if char == "/" and next_char == "*":
            comment = True
            index += 2
            continue
        if char in {"'", '"'}:
            quote = char
        elif char == token:
            return index
        index += 1
    return None


def _matching_css_brace(text: str, opening: int) -> int | None:
    depth = 0
    cursor = opening
    while cursor < len(text):
        next_opening = _find_css_token(text, "{", cursor)
        next_closing = _find_css_token(text, "}", cursor)
        if next_closing is None:
            return None
        if next_opening is not None and next_opening < next_closing:
            depth += 1
            cursor = next_opening + 1
            continue
        depth -= 1
        if depth == 0:
            return next_closing
        cursor = next_closing + 1
    return None


def _validate_replacement(original: str, replacement: str, target_id: str, kind: str) -> str | None:
    if not replacement:
        return f"empty_content_replacement:{target_id}"
    lowered = replacement.lower()
    if "<script" in lowered or "</script" in lowered:
        return f"content_script_not_allowed:{target_id}"
    if kind == "css_rule":
        if "@import" in lowered or re.search(r"url\s*\(\s*['\"]?https?://", lowered):
            return f"content_external_css_not_allowed:{target_id}"
        original_selector = _css_rule_selector(original)
        replacement_selector = _css_rule_selector(replacement)
        if not original_selector or _normalize_css_selector(original_selector) != _normalize_css_selector(
            replacement_selector
        ):
            return f"content_css_selector_mismatch:{target_id}"
        if _matching_css_brace(replacement, replacement.find("{")) != len(replacement) - 1:
            return f"content_css_rule_invalid:{target_id}"
        parsed = parse_css_rules(replacement)
        if parsed.status != "exact" or len(parsed.rules) != 1:
            return f"content_css_rule_invalid:{target_id}"
        return None
    if kind == "style":
        original_root = _single_root(original)
        replacement_root = _single_root(replacement)
        if original_root is None or replacement_root is None or replacement_root.name != "style":
            return f"content_root_mismatch:{target_id}"
        if dict(original_root.attrs) != dict(replacement_root.attrs):
            return f"content_style_identity_mismatch:{target_id}"
        css_error = stylesheet_validation_error(replacement_root.get_text())
        if css_error:
            return f"{css_error}:{target_id}"
        return None
    original_root = _single_root(original)
    replacement_root = _single_root(replacement)
    if original_root is None or replacement_root is None or original_root.name != replacement_root.name:
        return f"content_root_mismatch:{target_id}"
    for attribute in ("id", "data-role", "data-region"):
        if original_root.get(attribute) != replacement_root.get(attribute):
            return f"content_identity_mismatch:{target_id}:{attribute}"
    return None


def _css_rule_selector(source: str) -> str:
    opening = _find_css_token(source, "{", 0)
    return source[:opening].strip() if opening is not None else ""


def _normalize_css_selector(selector: str) -> str:
    return re.sub(r"\s+", " ", selector.strip())


def _selector_mentions(selector: str, anchor: str) -> bool:
    return _normalize_css_selector(anchor) in _normalize_css_selector(selector)


def _single_root(source: str) -> Tag | None:
    soup = BeautifulSoup(source, "html.parser")
    roots = [item for item in soup.contents if isinstance(item, Tag)]
    return roots[0] if len(roots) == 1 else None


def _kind_for_tag(tag: Tag) -> str:
    if tag.name in {"svg", "canvas"} or tag.get("data-role") == "main-visual":
        return "visual"
    if tag.get("data-region") in {"stage", "main-visual"} or tag.get("id") == "aetherviz-stage":
        return "visual"
    return "semantic"


def _region_for_tag(tag: Tag) -> str:
    if tag.get("data-region"):
        return str(tag.get("data-region"))
    if tag.get("data-role") == "main-visual" or tag.name in {"svg", "canvas"}:
        return "main-visual"
    if tag.get("id") == "aetherviz-stage":
        return "stage"
    return tag.name


def _region_from_selectors(selectors: list[str]) -> str:
    for selector in selectors:
        for region in ("main-visual", "stage", "controls", "caption", "formula", "teaching-flow"):
            if region in selector:
                return region
    return "style"


def _semantic_selectors_for_intent(evidence: EditEvidence) -> tuple[str, ...]:
    selected: list[str] = []
    if "control_issue" in evidence.issue_types:
        selected.append('[data-region="controls"]')
    if "text_change" in evidence.issue_types:
        selected.extend(_SEMANTIC_SELECTORS[1:])
    if "layout_issue" in evidence.issue_types:
        selected.extend(('[data-region="controls"]', '[data-region="caption"]', '[data-region="formula"]'))
    return tuple(dict.fromkeys(selected))


def _has_issue(evidence: EditEvidence, *issues: str) -> bool:
    return any(issue in evidence.issue_types for issue in issues)


def _merge_candidate(candidates: dict[tuple[int, int], ContentSource], candidate: ContentSource) -> None:
    key = (candidate.start, candidate.end)
    existing = candidates.get(key)
    if existing is None:
        candidates[key] = candidate
        return
    candidates[key] = replace(
        existing,
        score=max(existing.score, candidate.score),
        evidence=tuple(dict.fromkeys((*existing.evidence, *candidate.evidence))),
        dependencies=tuple(dict.fromkeys((*existing.dependencies, *candidate.dependencies))),
        selector=existing.selector or candidate.selector,
        region=existing.region or candidate.region,
    )


def _description_payload(item: ContentSource, html: str) -> dict[str, Any]:
    return {
        "kind": item.kind,
        "target_id": item.target_id,
        "source_hash": item.source_hash,
        "source": item.source,
        "tag": item.tag_name,
        "line": html.count("\n", 0, item.start) + 1,
        "selector": item.selector,
        "region": item.region,
        "score": item.score,
        "evidence": list(item.evidence),
        "dependencies": list(item.dependencies),
        "parse_status": item.parse_status,
        "at_rule_path": list(item.at_rule_path),
        "start": item.start,
        "end": item.end,
    }


def _html_stylesheet_validation_error(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    for index, tag in enumerate(soup.find_all("style")):
        error = stylesheet_validation_error(tag.get_text())
        if error:
            return f"{error}:style:{index}"
    return None


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
