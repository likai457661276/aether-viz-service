"""Deterministic edit intent and evidence extraction for bounded HTML patches."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_EXPLICIT_SELECTOR_RE = re.compile(
    r"(?:#[A-Za-z_][\w-]*|\.[A-Za-z_][\w-]*|"
    r"\[data-(?:role|region|layout-slot)\s*=\s*['\"][^'\"]+['\"]\])"
)
_QUERY_SELECTOR_RE = re.compile(r"querySelector(?:All)?\(\s*(['\"])(?P<selector>[^'\"]+)\1\s*\)", re.IGNORECASE)
_GET_BY_ID_RE = re.compile(r"getElementById\(\s*(['\"])(?P<identifier>[^'\"]+)\1\s*\)", re.IGNORECASE)
_REPORT_KEYS = (
    "quality_report",
    "validation_report",
    "check_report",
    "report",
    "latest_validation_report",
)
_REPORT_EVIDENCE_FIELDS = {
    "type",
    "scope",
    "selector",
    "target",
    "failing_expression",
    "call_chain",
    "expected",
}


@dataclass(frozen=True)
class EditEvidence:
    issue_types: tuple[str, ...]
    explicit_selectors: tuple[str, ...]
    report_selectors: tuple[str, ...]
    runtime_anchors: tuple[str, ...]
    report_hints: tuple[str, ...]

    def as_prompt_payload(self) -> dict[str, list[str]]:
        return {
            "issue_types": list(self.issue_types),
            "explicit_selectors": list(self.explicit_selectors),
            "report_selectors": list(self.report_selectors),
            "runtime_anchors": list(self.runtime_anchors),
            "report_hints": list(self.report_hints),
        }


def extract_edit_evidence(instruction: str, context: dict[str, Any] | None = None) -> EditEvidence:
    text = instruction or ""
    report_values = _extract_report_values(context)
    report_text = "\n".join(report_values)
    combined = f"{text}\n{report_text}"
    explicit_selectors = _dedupe([*_selectors_from_text(text), *_selectors_from_dom_calls(text)])
    report_selectors = _dedupe([*_selectors_from_text(report_text), *_selectors_from_dom_calls(report_text)])
    runtime_anchors = _dedupe(
        match.group(1).replace(" ", "")
        for match in re.finditer(
            r"(?<![\w$])([A-Za-z_$][\w$]*(?:\s*\.\s*[A-Za-z_$][\w$]*)*)"
            r"\s+is not a function",
            combined,
            re.IGNORECASE,
        )
    )
    return EditEvidence(
        issue_types=_classify_issue_types(combined),
        explicit_selectors=explicit_selectors,
        report_selectors=report_selectors,
        runtime_anchors=runtime_anchors,
        report_hints=tuple(report_values[:12]),
    )


def compact_report_context(context: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return only bounded targeting evidence, never arbitrary conversation context."""
    if not isinstance(context, dict):
        return None
    compact: dict[str, Any] = {}
    for key in _REPORT_KEYS:
        if key in context:
            compact[key] = _compact_report_value(context[key], depth=0)
    return compact or None


def selector_identity(tag: Any) -> tuple[str, ...]:
    selectors: list[str] = []
    identifier = tag.get("id") if hasattr(tag, "get") else None
    if identifier:
        selectors.append(f"#{identifier}")
    for attribute in ("data-role", "data-region", "data-layout-slot"):
        value = tag.get(attribute) if hasattr(tag, "get") else None
        if value:
            selectors.append(f'[{attribute}="{value}"]')
    classes = tag.get("class") if hasattr(tag, "get") else None
    if isinstance(classes, list):
        selectors.extend(f".{item}" for item in classes[:3] if item)
    return tuple(selectors)


def _classify_issue_types(text: str) -> tuple[str, ...]:
    patterns = (
        (
            "visual_not_visible",
            r"空白|不显示|未显示|看不见|不可见|没有正确显示|empty_main_visual|"
            r"display\s*:\s*none|visibility\s*:\s*hidden|zero.?size",
        ),
        ("runtime_error", r"is not a function|报错|异常|runtime|TypeError|ReferenceError"),
        ("control_issue", r"按钮|控件|滑块|播放|暂停|重置|点击|无响应|没反应|control|button"),
        ("text_change", r"文案|文字|标题|说明|结论|公式|步骤|caption|formula|title"),
        ("layout_issue", r"布局|位置|尺寸|宽度|高度|间距|边距|对齐|溢出|遮挡|layout|overflow"),
        ("style_change", r"颜色|字号|字体|样式|主题|背景|css|style"),
        (
            "visual_change",
            r"图像|图形|动画|主视觉|舞台|圆点|点位|半径|svg|canvas|circle|radius|dot|point|visual|render",
        ),
    )
    return tuple(name for name, pattern in patterns if re.search(pattern, text, re.IGNORECASE))


def _extract_report_values(context: dict[str, Any] | None) -> list[str]:
    compact = compact_report_context(context)
    if not compact:
        return []
    values: list[str] = []

    def visit(value: Any, key: str | None = None) -> None:
        if len(values) >= 24:
            return
        if isinstance(value, dict):
            for child_key, child in value.items():
                if child_key in _REPORT_EVIDENCE_FIELDS or key in {"errors", "warnings"}:
                    visit(child, child_key)
        elif isinstance(value, list):
            for child in value[:8]:
                visit(child, key)
        elif isinstance(value, (str, int, float, bool)):
            text = str(value).strip()
            if text and text not in values:
                values.append(text[:500])

    for report in compact.values():
        if isinstance(report, dict):
            for key in ("errors", "warnings", *_REPORT_EVIDENCE_FIELDS):
                if key in report:
                    visit(report[key], key)
        else:
            visit(report)
    return values


def _compact_report_value(value: Any, *, depth: int) -> Any:
    if depth >= 4:
        return None
    if isinstance(value, dict):
        return {
            str(key): compact
            for key, child in list(value.items())[:24]
            if (key in _REPORT_EVIDENCE_FIELDS or key in {"errors", "warnings", "summary", "message", "detail", "ok"})
            and (compact := _compact_report_value(child, depth=depth + 1)) is not None
        }
    if isinstance(value, list):
        return [
            compact for child in value[:12] if (compact := _compact_report_value(child, depth=depth + 1)) is not None
        ]
    if isinstance(value, (str, int, float, bool)):
        return str(value)[:500]
    return None


def _selectors_from_text(text: str) -> tuple[str, ...]:
    return _dedupe(match.group(0) for match in _EXPLICIT_SELECTOR_RE.finditer(text or ""))


def _selectors_from_dom_calls(text: str) -> tuple[str, ...]:
    selectors = [match.group("selector") for match in _QUERY_SELECTOR_RE.finditer(text or "")]
    selectors.extend(f"#{match.group('identifier')}" for match in _GET_BY_ID_RE.finditer(text or ""))
    return _dedupe(selectors)


def _dedupe(values: Any) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        normalized = str(value or "").strip()
        if normalized and normalized not in result:
            result.append(normalized)
    return tuple(result)
