"""HTML revision indexing, patching and validation helpers."""

from __future__ import annotations

import hashlib
import html as html_lib
import json
import re
from dataclasses import dataclass
from typing import Any

from bs4 import BeautifulSoup, Tag

from aetherviz_service.aetherviz.validator import (
    AetherVizHtmlValidationError,
    sanitize_aetherviz_html,
    validate_aetherviz_html,
)

REVISION_INDEX_VERSION = "revision-index-v1"
MAX_DOM_EXCERPT_CHARS = 2400
MAX_STYLE_EXCERPT_CHARS = 2600
MAX_SCRIPT_EXCERPT_CHARS = 5200


class AetherVizRevisionError(ValueError):
    pass


@dataclass(frozen=True)
class RevisionAnalysis:
    normalized_html: str
    revision_index: dict[str, Any]
    intent: dict[str, Any]
    targets: list[dict[str, Any]]
    index_status: dict[str, Any]


def normalize_revision_html_input(html: str) -> tuple[str, dict[str, Any]]:
    """Return the standalone HTML to revise and normalization metadata."""
    raw = (html or "").strip()
    metadata: dict[str, Any] = {"source": "html_document", "partial_document": False}
    if not raw:
        raise AetherVizRevisionError("current_html 不能为空")

    soup = BeautifulSoup(raw, "html.parser")
    iframe = soup.find("iframe")
    srcdoc = iframe.get("srcdoc") if isinstance(iframe, Tag) else None
    if isinstance(srcdoc, str) and srcdoc.strip():
        decoded = html_lib.unescape(srcdoc).strip()
        metadata["source"] = "iframe_srcdoc"
        raw = decoded

    lower = raw.lower()
    if "<html" not in lower:
        metadata["partial_document"] = True
        raw = f"<!DOCTYPE html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\"><title>AetherViz</title></head><body>{raw}</body></html>"
    elif not lower.startswith("<!doctype html>"):
        raw = "<!DOCTYPE html>\n" + raw

    return raw.strip(), metadata


def html_revision_hash(html: str) -> str:
    return "sha256:" + hashlib.sha256(html.encode("utf-8")).hexdigest()


def build_revision_index(html: str) -> dict[str, Any]:
    normalized_html, normalization = normalize_revision_html_input(html)
    soup = BeautifulSoup(normalized_html, "html.parser")
    style_blocks = _extract_style_blocks(soup)
    script_blocks = _extract_script_blocks(soup)
    scripts = _index_scripts(script_blocks)
    styles = _index_styles(style_blocks)
    regions = _index_regions(soup, styles, scripts)
    return {
        "version": REVISION_INDEX_VERSION,
        "html_hash": html_revision_hash(normalized_html),
        "document": {
            "title": soup.title.get_text(" ", strip=True) if soup.title else "",
            "external_resources": _external_resources(soup),
            "body_root": _body_root_selector(soup),
            "normalization": normalization,
        },
        "regions": regions,
        "styles": styles,
        "scripts": scripts,
        "dynamic_writes": _dynamic_write_index(script_blocks),
        "protected_regions": _protected_regions(normalized_html, soup),
    }


def analyze_revision(
    current_html: str,
    instruction: str,
    provided_index: dict[str, Any] | None = None,
) -> RevisionAnalysis:
    normalized_html, _normalization = normalize_revision_html_input(current_html)
    fresh_index = build_revision_index(normalized_html)
    index_status = validate_provided_revision_index(provided_index, normalized_html)
    revision_index = provided_index if index_status["usable"] and provided_index else fresh_index
    intent = classify_revision_intent(instruction)
    targets = select_revision_targets(revision_index, intent)
    if not targets:
        targets = select_revision_targets(fresh_index, intent)
    return RevisionAnalysis(
        normalized_html=normalized_html,
        revision_index=revision_index,
        intent=intent,
        targets=targets,
        index_status=index_status,
    )


def validate_provided_revision_index(index: dict[str, Any] | None, html: str) -> dict[str, Any]:
    if not isinstance(index, dict):
        return {"usable": False, "reason": "missing"}
    if index.get("version") != REVISION_INDEX_VERSION:
        return {"usable": False, "reason": "version_mismatch"}
    expected_hash = html_revision_hash(html)
    if index.get("html_hash") == expected_hash:
        return {"usable": True, "reason": "hash_match"}

    soup = BeautifulSoup(html, "html.parser")
    selectors = [
        str(region.get("selector") or "")
        for region in index.get("regions", [])
        if isinstance(region, dict) and region.get("selector")
    ][:8]
    existing = 0
    for selector in selectors:
        try:
            if soup.select_one(selector):
                existing += 1
        except Exception:
            continue
    if selectors and existing >= max(1, len(selectors) // 2):
        return {
            "usable": True,
            "reason": "selector_match_hash_mismatch",
            "expected_html_hash": expected_hash,
            "provided_html_hash": index.get("html_hash"),
        }
    return {
        "usable": False,
        "reason": "hash_mismatch",
        "expected_html_hash": expected_hash,
        "provided_html_hash": index.get("html_hash"),
    }


def classify_revision_intent(instruction: str) -> dict[str, Any]:
    text = (instruction or "").strip().lower()
    matched: list[str] = []
    patterns: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("caption_copy", ("文案", "说明", "旁白", "caption", "讲解", "描述", "小学生", "清楚")),
        ("formula", ("公式", "推导", "数值", "计算", "等式", "katex")),
        ("layout", ("布局", "居中", "放大", "缩小", "位置", "底部", "顶部", "舞台", "遮挡")),
        ("color_style", ("颜色", "主色", "蓝", "绿", "红", "字号", "字体", "样式", "背景")),
        ("control", ("按钮", "滑块", "控件", "重置", "播放", "暂停", "速度", "拖动")),
        ("animation_timing", ("动画", "慢", "快", "速度", "分步", "节奏", "时间线", "timeline")),
        ("interaction", ("交互", "同步", "拖动", "更新", "联动", "点击")),
        ("responsive", ("手机", "移动端", "响应式", "挤", "换行", "屏幕")),
    )
    for intent_type, keywords in patterns:
        if any(keyword in text for keyword in keywords):
            matched.append(intent_type)
    if not matched:
        matched.append("general")
    risk = "high" if any(item in matched for item in ("interaction", "animation_timing", "control")) else "medium"
    if matched == ["caption_copy"]:
        risk = "low"
    return {
        "types": matched,
        "risk": risk,
        "instruction_summary": _compact_text(instruction, 260),
    }


def select_revision_targets(index: dict[str, Any], intent: dict[str, Any]) -> list[dict[str, Any]]:
    types = set(intent.get("types") or [])
    preferred_region_types: set[str] = set()
    if "caption_copy" in types:
        preferred_region_types.update({"step_caption", "learning_goal"})
    if "formula" in types:
        preferred_region_types.add("formula_panel")
    if "layout" in types or "color_style" in types:
        preferred_region_types.update({"visual_stage", "app_shell", "responsive_style"})
    if "control" in types:
        preferred_region_types.add("control_panel")
    if "animation_timing" in types:
        preferred_region_types.update({"animation_timeline", "runtime_script", "step_caption"})
    if "interaction" in types:
        preferred_region_types.update({"runtime_script", "control_panel", "formula_panel", "visual_stage"})
    if "responsive" in types:
        preferred_region_types.update({"responsive_style", "control_panel", "app_shell"})
    if not preferred_region_types:
        preferred_region_types.update({"visual_stage", "step_caption", "control_panel"})

    targets: list[dict[str, Any]] = []
    for region in index.get("regions", []):
        if not isinstance(region, dict):
            continue
        region_type = str(region.get("type") or "")
        score = 0
        if region_type in preferred_region_types:
            score += 5
        if any(ref in preferred_region_types for ref in region.get("semantic_refs", [])):
            score += 2
        if score > 0:
            targets.append({"kind": "region", "score": score, **region})

    if "layout" in types or "color_style" in types or "responsive" in types:
        for style in index.get("styles", [])[:8]:
            if isinstance(style, dict):
                targets.append({"kind": "style", "score": 4, **style})

    if {"animation_timing", "interaction", "control", "formula"} & types:
        for script in index.get("scripts", [])[:10]:
            if isinstance(script, dict):
                targets.append({"kind": "script", "score": 4, **script})

    return sorted(targets, key=lambda item: int(item.get("score", 0)), reverse=True)[:10]


def build_revision_patch_prompt(
    *,
    topic: str,
    instruction: str,
    analysis: RevisionAnalysis,
    context: dict[str, Any] | None = None,
) -> str:
    llm_context = {
        "topic": topic,
        "instruction": instruction.strip(),
        "revision_intent": analysis.intent,
        "index_status": analysis.index_status,
        "targets": analysis.targets,
        "document": analysis.revision_index.get("document", {}),
        "protected_regions": analysis.revision_index.get("protected_regions", []),
        "plan_summary": (context or {}).get("plan_summary") if isinstance(context, dict) else None,
        "memory_summary": ((context or {}).get("memory") or {}).get("summary") if isinstance(context, dict) else None,
        "constraints": [
            "只返回 JSON，不返回完整 HTML。",
            "优先使用 replace_region、upsert_css_rule、replace_js_function、replace_script_block。",
            "不要删除 window.AetherVizRuntime、ready/error 运行时标记或已有白名单 CDN。",
            "只修改与用户指令直接相关的目标区域。",
            "保持当前选中文件的教学主题和主要结构。",
        ],
    }
    return f"""请根据以下结构化上下文生成 AetherViz 局部修改补丁。

输出必须是严格 JSON，格式：
{{
  "patch_plan": "一句话说明补丁策略",
  "patches": [
    {{
      "type": "replace_region",
      "target": {{"kind": "dom", "selector": "#animation-caption"}},
      "content": "<p id=\\"animation-caption\\" class=\\"animation-caption\\">...</p>"
    }},
    {{
      "type": "upsert_css_rule",
      "selector": "#aetherviz-stage",
      "declarations": {{"min-height": "420px"}}
    }},
    {{
      "type": "replace_js_function",
      "name": "updateVisualization",
      "content": "function updateVisualization() {{ ... }}"
    }},
    {{
      "type": "replace_script_block",
      "index": 0,
      "content": "const state = ...;"
    }}
  ]
}}

结构化上下文：
{json.dumps(llm_context, ensure_ascii=False, indent=2)}
"""


def build_revision_patch_repair_prompt(
    *,
    topic: str,
    instruction: str,
    analysis: RevisionAnalysis,
    failed_patch: str,
    error_detail: str,
    context: dict[str, Any] | None = None,
) -> str:
    return f"""上一次 AetherViz 局部补丁失败，请只修复补丁 JSON。

教学主题：{topic}
用户修改意见：{instruction.strip()}
失败原因：{error_detail}

失败补丁：
{_compact_text(failed_patch, 5000)}

请重新输出严格 JSON 补丁，不要输出完整 HTML。

可用上下文：
{build_revision_patch_prompt(topic=topic, instruction=instruction, analysis=analysis, context=context)}
"""


def build_adjusted_plan_fallback_prompt(
    *,
    topic: str,
    instruction: str,
    analysis: RevisionAnalysis,
    error_detail: str,
    context: dict[str, Any] | None = None,
) -> str:
    summary = summarize_revision_index(analysis.revision_index)
    return f"""局部补丁两次失败，请进入方案级兜底，但不要使用完整 HTML。

任务：根据用户修改意见、原方案摘要、当前页面结构摘要和失败原因，重新规划并生成完整独立 AetherViz HTML。

教学主题：{topic}
用户修改意见：{instruction.strip()}
失败原因：{error_detail}
原方案摘要：
{json.dumps((context or {}).get("plan_summary") if isinstance(context, dict) else None, ensure_ascii=False, indent=2)}
当前结构摘要：
{json.dumps(summary, ensure_ascii=False, indent=2)}

要求：
- 先在内部调整教学方案，再输出完整 <!DOCTYPE html>...</html>。
- 不要依赖完整旧 HTML。
- 保留结构摘要中明确存在且与修改无关的主要控件、公式、caption、运行时约束。
- 保留 window.AetherVizRuntime 和 ready/error 标记。
- 只输出完整 HTML，不输出 Markdown 或解释。
"""


def parse_revision_patch(raw_patch: str) -> dict[str, Any]:
    text = (raw_patch or "").strip()
    if not text:
        raise AetherVizRevisionError("补丁为空")
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise AetherVizRevisionError("补丁不是 JSON 对象")
    try:
        payload = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise AetherVizRevisionError(f"补丁 JSON 解析失败：{exc}") from exc
    patches = payload.get("patches")
    if not isinstance(patches, list) or not patches:
        raise AetherVizRevisionError("补丁缺少 patches 数组")
    return payload


def apply_revision_patch(html: str, patch_payload: dict[str, Any]) -> str:
    normalized_html, _ = normalize_revision_html_input(html)
    soup = BeautifulSoup(normalized_html, "html.parser")
    for patch in patch_payload.get("patches", []):
        if not isinstance(patch, dict):
            raise AetherVizRevisionError("补丁项必须是对象")
        patch_type = patch.get("type")
        if patch_type == "replace_region":
            _apply_replace_region(soup, patch)
        elif patch_type == "upsert_css_rule":
            _apply_upsert_css_rule(soup, patch)
        elif patch_type == "replace_js_function":
            _apply_replace_js_function(soup, patch)
        elif patch_type == "replace_script_block":
            _apply_replace_script_block(soup, patch)
        else:
            raise AetherVizRevisionError(f"不支持的补丁类型：{patch_type}")
    return str(soup)


def validate_revised_html(
    html: str,
    *,
    original_html: str,
    topic: str,
) -> tuple[str, list[str]]:
    cleaned = sanitize_aetherviz_html(html)
    warnings = validate_aetherviz_html(cleaned, topic=topic, strict=False)
    original_has_runtime = "window.AetherVizRuntime" in original_html
    original_has_ready = "__AETHERVIZ_RUNTIME_READY__" in original_html
    original_has_error = "__AETHERVIZ_RUNTIME_ERROR__" in original_html
    errors: list[str] = []
    if original_has_runtime and "window.AetherVizRuntime" not in cleaned:
        errors.append("runtime_missing: window.AetherVizRuntime 被删除")
    if original_has_ready and "__AETHERVIZ_RUNTIME_READY__" not in cleaned:
        errors.append("ready_bridge_missing: ready 标记被删除")
    if original_has_error and "__AETHERVIZ_RUNTIME_ERROR__" not in cleaned:
        errors.append("error_bridge_missing: error 标记被删除")
    if errors:
        raise AetherVizHtmlValidationError("；".join(errors))
    return cleaned, warnings


def summarize_revision_index(index: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": index.get("version"),
        "document": index.get("document", {}),
        "regions": [
            {
                "id": region.get("id"),
                "type": region.get("type"),
                "selector": region.get("selector"),
                "summary": region.get("summary"),
                "style_refs": region.get("style_refs", [])[:6],
                "script_refs": region.get("script_refs", [])[:6],
            }
            for region in index.get("regions", [])
            if isinstance(region, dict)
        ][:12],
        "scripts": [
            {
                "name": script.get("name"),
                "kind": script.get("kind"),
                "summary": script.get("summary"),
                "event_sources": script.get("event_sources", [])[:6],
            }
            for script in index.get("scripts", [])
            if isinstance(script, dict)
        ][:10],
        "protected_regions": index.get("protected_regions", []),
    }


def _extract_style_blocks(soup: BeautifulSoup) -> list[str]:
    return [style.get_text("\n", strip=False) for style in soup.find_all("style")]


def _extract_script_blocks(soup: BeautifulSoup) -> list[str]:
    blocks: list[str] = []
    for script in soup.find_all("script"):
        if script.get("src"):
            continue
        blocks.append(script.get_text("\n", strip=False))
    return blocks


def _external_resources(soup: BeautifulSoup) -> list[str]:
    resources: list[str] = []
    for tag in soup.find_all(["script", "link"]):
        url = tag.get("src") or tag.get("href")
        if isinstance(url, str) and re.match(r"https?://", url):
            resources.append(url)
    return resources


def _body_root_selector(soup: BeautifulSoup) -> str:
    body = soup.body
    if not body:
        return "body"
    for child in body.find_all(recursive=False):
        if isinstance(child, Tag):
            return _selector_for_tag(child)
    return "body"


def _index_styles(style_blocks: list[str]) -> list[dict[str, Any]]:
    styles: list[dict[str, Any]] = []
    rule_pattern = re.compile(r"(?P<selector>[^{}@][^{}]*)\{(?P<body>[^{}]*)\}", re.DOTALL)
    for block_index, css in enumerate(style_blocks):
        for match in rule_pattern.finditer(css):
            selector = " ".join(match.group("selector").split())
            body = match.group("body")
            if not selector:
                continue
            declarations: dict[str, str] = {}
            for item in body.split(";"):
                if ":" not in item:
                    continue
                key, value = item.split(":", 1)
                declarations[key.strip()] = value.strip()
            styles.append(
                {
                    "selector": selector,
                    "summary": _style_summary(selector, declarations),
                    "properties": declarations,
                    "source_range": {"style_block": block_index},
                    "css_excerpt": _compact_text(match.group(0), MAX_STYLE_EXCERPT_CHARS),
                }
            )
    return styles[:80]


def _index_scripts(script_blocks: list[str]) -> list[dict[str, Any]]:
    scripts: list[dict[str, Any]] = []
    for block_index, script in enumerate(script_blocks):
        ids = _script_dom_ids(script)
        event_sources = _script_event_sources(script)
        for name, content in _script_functions(script):
            scripts.append(
                {
                    "name": name,
                    "kind": "function",
                    "summary": _script_summary(name, content, ids, event_sources),
                    "reads": sorted(set(re.findall(r"state\.([A-Za-z0-9_]+)", content))),
                    "writes": sorted(set(_script_dom_ids(content))),
                    "event_sources": [source for source in event_sources if source in content][:8],
                    "source_range": {"script_block": block_index},
                    "js_excerpt": _compact_text(content, MAX_SCRIPT_EXCERPT_CHARS),
                }
            )
        if "window.AetherVizRuntime" in script:
            scripts.append(
                {
                    "name": "AetherVizRuntime",
                    "kind": "runtime_api",
                    "summary": "页面运行时 API，负责 play/pause/reset/setSpeed/update/getState。",
                    "event_sources": event_sources[:8],
                    "source_range": {"script_block": block_index},
                    "js_excerpt": _compact_text(script, MAX_SCRIPT_EXCERPT_CHARS),
                }
            )
        if "gsap.timeline" in script:
            scripts.append(
                {
                    "name": "gsap_timeline",
                    "kind": "animation_timeline",
                    "summary": "GSAP 时间线动画，包含 label、tween 与播放控制。",
                    "timeline_labels": re.findall(r"\.addLabel\(\s*['\"]([^'\"]+)['\"]", script),
                    "event_sources": event_sources[:8],
                    "source_range": {"script_block": block_index},
                    "js_excerpt": _compact_text(script, MAX_SCRIPT_EXCERPT_CHARS),
                }
            )
    return scripts[:80]


def _index_regions(soup: BeautifulSoup, styles: list[dict[str, Any]], scripts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[Tag] = []
    selectors = [
        "#aetherviz-stage",
        ".control-panel",
        ".learning-objectives",
        "#animation-caption",
        ".animation-caption",
        "#step-caption",
        "[data-region]",
        "main",
        "section",
    ]
    for selector in selectors:
        try:
            candidates.extend(tag for tag in soup.select(selector) if isinstance(tag, Tag))
        except Exception:
            continue

    seen: set[int] = set()
    regions: list[dict[str, Any]] = []
    for tag in candidates:
        tag_id = id(tag)
        if tag_id in seen:
            continue
        seen.add(tag_id)
        selector = _selector_for_tag(tag)
        region_type = _infer_region_type(tag, selector)
        text = _compact_text(tag.get_text(" ", strip=True), 520)
        style_refs = _style_refs_for_selector(selector, tag, styles)
        script_refs = _script_refs_for_tag(tag, scripts)
        regions.append(
            {
                "id": str(tag.get("id") or tag.get("data-region") or f"{region_type}-{len(regions) + 1}"),
                "type": region_type,
                "selector": selector,
                "summary": _region_summary(region_type, text),
                "text": text,
                "dom_excerpt": _compact_text(str(tag), MAX_DOM_EXCERPT_CHARS),
                "style_refs": style_refs,
                "script_refs": script_refs,
                "semantic_refs": _semantic_refs(region_type),
            }
        )
    return regions[:40]


def _dynamic_write_index(script_blocks: list[str]) -> dict[str, list[str]]:
    writes: dict[str, list[str]] = {}
    for script in script_blocks:
        variables: dict[str, str] = {}
        for var_name, dom_id in re.findall(
            r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*document\.getElementById\(\s*['\"]([^'\"]+)['\"]\s*\)",
            script,
        ):
            variables[var_name] = dom_id
        for function_name, content in _script_functions(script):
            for var_name, dom_id in variables.items():
                if re.search(rf"\b{re.escape(var_name)}\.(?:textContent|innerHTML|setAttribute|style|value)\b", content):
                    writes.setdefault(dom_id, []).append(function_name)
    return {key: sorted(set(value)) for key, value in writes.items()}


def _protected_regions(html: str, soup: BeautifulSoup) -> list[str]:
    protected: list[str] = []
    if "__AETHERVIZ_RUNTIME_READY__" in html or "__AETHERVIZ_RUNTIME_ERROR__" in html:
        protected.append("runtime_error_bridge")
    if soup.find("script", src=True) or soup.find("link", href=True):
        protected.append("external_resource_loader")
    if "window.AetherVizRuntime" in html:
        protected.append("aetherviz_runtime_api")
    return protected


def _apply_replace_region(soup: BeautifulSoup, patch: dict[str, Any]) -> None:
    target = patch.get("target") if isinstance(patch.get("target"), dict) else {}
    selector = str(target.get("selector") or patch.get("selector") or "").strip()
    content = str(patch.get("content") or "").strip()
    if not selector or not content:
        raise AetherVizRevisionError("replace_region 缺少 selector 或 content")
    try:
        element = soup.select_one(selector)
    except Exception as exc:
        raise AetherVizRevisionError(f"replace_region selector 无效：{selector}") from exc
    if element is None:
        raise AetherVizRevisionError(f"replace_region 未找到目标：{selector}")
    fragment = BeautifulSoup(content, "html.parser")
    replacements = [node for node in fragment.contents if str(node).strip()]
    if not replacements:
        raise AetherVizRevisionError("replace_region content 为空")
    element.replace_with(*replacements)


def _apply_upsert_css_rule(soup: BeautifulSoup, patch: dict[str, Any]) -> None:
    selector = str(patch.get("selector") or "").strip()
    declarations = patch.get("declarations")
    if not selector or not isinstance(declarations, dict) or not declarations:
        raise AetherVizRevisionError("upsert_css_rule 缺少 selector 或 declarations")
    style = soup.find("style")
    if style is None:
        head = soup.head or soup.new_tag("head")
        if soup.head is None and soup.html:
            soup.html.insert(0, head)
        style = soup.new_tag("style")
        head.append(style)
    declaration_text = " ".join(f"{key}: {value};" for key, value in declarations.items())
    style.string = f"{style.get_text('', strip=False)}\n{selector} {{ {declaration_text} }}\n"


def _apply_replace_js_function(soup: BeautifulSoup, patch: dict[str, Any]) -> None:
    name = str(patch.get("name") or "").strip()
    content = str(patch.get("content") or "").strip()
    if not name or not content:
        raise AetherVizRevisionError("replace_js_function 缺少 name 或 content")
    pattern = re.compile(rf"function\s+{re.escape(name)}\s*\([^)]*\)\s*\{{", re.MULTILINE)
    for script in soup.find_all("script"):
        if script.get("src"):
            continue
        code = script.get_text("", strip=False)
        match = pattern.search(code)
        if not match:
            continue
        end = _find_matching_brace(code, match.end() - 1)
        if end < 0:
            raise AetherVizRevisionError(f"无法定位函数结尾：{name}")
        script.string = code[: match.start()] + content + code[end + 1 :]
        return
    raise AetherVizRevisionError(f"未找到函数：{name}")


def _apply_replace_script_block(soup: BeautifulSoup, patch: dict[str, Any]) -> None:
    index = int(patch.get("index") or 0)
    content = str(patch.get("content") or "")
    scripts = [script for script in soup.find_all("script") if not script.get("src")]
    if index < 0 or index >= len(scripts):
        raise AetherVizRevisionError(f"replace_script_block index 超出范围：{index}")
    scripts[index].string = content


def _find_matching_brace(code: str, open_index: int) -> int:
    depth = 0
    in_single = in_double = in_template = False
    escape = False
    for index in range(open_index, len(code)):
        char = code[index]
        if escape:
            escape = False
            continue
        if char == "\\" and (in_single or in_double or in_template):
            escape = True
            continue
        if in_single:
            if char == "'":
                in_single = False
            continue
        if in_double:
            if char == '"':
                in_double = False
            continue
        if in_template:
            if char == "`":
                in_template = False
            continue
        if char == "'":
            in_single = True
            continue
        if char == '"':
            in_double = True
            continue
        if char == "`":
            in_template = True
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    return -1


def _selector_for_tag(tag: Tag) -> str:
    if tag.get("id"):
        return f"#{tag.get('id')}"
    if tag.get("data-region"):
        return f"[data-region=\"{tag.get('data-region')}\"]"
    classes = tag.get("class") or []
    if classes:
        return f"{tag.name}." + ".".join(str(item) for item in classes[:3])
    return tag.name


def _infer_region_type(tag: Tag, selector: str) -> str:
    token = " ".join(
        [
            selector,
            str(tag.get("id") or ""),
            str(tag.get("class") or ""),
            str(tag.get("data-region") or ""),
            str(tag.get("role") or ""),
            tag.get_text(" ", strip=True)[:220],
        ]
    ).lower()
    if "caption" in token or "旁白" in token or "步骤" in token:
        return "step_caption"
    if "learning" in token or "目标" in token:
        return "learning_goal"
    if "control" in token or tag.find(["button", "input", "select"]):
        return "control_panel"
    if "formula" in token or "公式" in token or "katex" in token:
        return "formula_panel"
    if "aetherviz-stage" in token or tag.find(["svg", "canvas"]):
        return "visual_stage"
    if "runtime" in token:
        return "runtime_script"
    return "app_shell" if tag.name in {"main", "body"} else "content_region"


def _style_refs_for_selector(selector: str, tag: Tag, styles: list[dict[str, Any]]) -> list[str]:
    signals = {selector, tag.name}
    if tag.get("id"):
        signals.add(f"#{tag.get('id')}")
    for cls in tag.get("class") or []:
        signals.add(f".{cls}")
    refs: list[str] = []
    for style in styles:
        style_selector = str(style.get("selector") or "")
        if any(signal and signal in style_selector for signal in signals):
            refs.append(style_selector)
    return refs[:10]


def _script_refs_for_tag(tag: Tag, scripts: list[dict[str, Any]]) -> list[str]:
    signals: set[str] = set()
    if tag.get("id"):
        signals.add(str(tag.get("id")))
    for child in tag.find_all(True):
        if child.get("id"):
            signals.add(str(child.get("id")))
    refs: list[str] = []
    for script in scripts:
        excerpt = str(script.get("js_excerpt") or "")
        if any(signal and signal in excerpt for signal in signals):
            refs.append(str(script.get("name") or script.get("kind") or "script"))
    return refs[:12]


def _semantic_refs(region_type: str) -> list[str]:
    mapping = {
        "step_caption": ["caption_copy", "animation_timing"],
        "learning_goal": ["caption_copy"],
        "control_panel": ["control", "interaction"],
        "formula_panel": ["formula", "interaction"],
        "visual_stage": ["layout", "animation_timing", "interaction"],
        "runtime_script": ["animation_timing", "interaction"],
    }
    return mapping.get(region_type, [])


def _region_summary(region_type: str, text: str) -> str:
    labels = {
        "step_caption": "步骤旁白或分镜说明区域",
        "learning_goal": "学习目标区域",
        "control_panel": "播放、参数或速度控制区域",
        "formula_panel": "公式、推导或结论展示区域",
        "visual_stage": "主视觉舞台区域",
        "runtime_script": "运行时脚本区域",
        "app_shell": "页面整体布局容器",
    }
    base = labels.get(region_type, "内容区域")
    return f"{base}：{_compact_text(text, 180)}" if text else base


def _style_summary(selector: str, declarations: dict[str, str]) -> str:
    important = [
        key
        for key in declarations
        if key.startswith(("display", "grid", "flex", "width", "height", "min-", "max-", "overflow", "font", "color", "background"))
    ][:8]
    return f"{selector} 控制 {', '.join(important) if important else '局部视觉样式'}"


def _script_summary(name: str, content: str, ids: list[str], event_sources: list[str]) -> str:
    verbs: list[str] = []
    if "setAttribute" in content or ".style" in content:
        verbs.append("更新图形属性或样式")
    if "textContent" in content or "innerHTML" in content:
        verbs.append("更新文案或公式")
    if "requestAnimationFrame" in content:
        verbs.append("驱动连续动画")
    if "gsap" in content:
        verbs.append("驱动 GSAP 时间线")
    if not verbs:
        verbs.append("处理页面逻辑")
    dom_hint = f"；关联 DOM：{', '.join(ids[:6])}" if ids else ""
    event_hint = f"；事件来源：{', '.join(event_sources[:6])}" if event_sources else ""
    return f"{name}：{'、'.join(verbs)}{dom_hint}{event_hint}"


def _script_dom_ids(script: str) -> list[str]:
    ids = re.findall(r"getElementById\(\s*['\"]([^'\"]+)['\"]\s*\)", script)
    ids.extend(re.findall(r"querySelector\(\s*['\"]#([^'\"]+)['\"]\s*\)", script))
    return sorted(set(ids))


def _script_event_sources(script: str) -> list[str]:
    sources: list[str] = []
    direct = re.findall(
        r"getElementById\(\s*['\"]([^'\"]+)['\"]\s*\)\.addEventListener\(\s*['\"]([^'\"]+)['\"]",
        script,
    )
    sources.extend(f"{dom_id}:{event}" for dom_id, event in direct)
    variable_map = dict(
        re.findall(
            r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*document\.getElementById\(\s*['\"]([^'\"]+)['\"]\s*\)",
            script,
        )
    )
    for var_name, event_name in re.findall(r"([A-Za-z_$][\w$]*)\.addEventListener\(\s*['\"]([^'\"]+)['\"]", script):
        dom_id = variable_map.get(var_name, var_name)
        sources.append(f"{dom_id}:{event_name}")
    return sorted(set(sources))


def _script_functions(script: str) -> list[tuple[str, str]]:
    functions: list[tuple[str, str]] = []
    pattern = re.compile(r"function\s+([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{", re.MULTILINE)
    for match in pattern.finditer(script):
        end = _find_matching_brace(script, match.end() - 1)
        if end > match.start():
            functions.append((match.group(1), script[match.start() : end + 1]))
    return functions


def _compact_text(value: str, max_length: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= max_length:
        return text
    return text[: max_length - 1] + "…"
