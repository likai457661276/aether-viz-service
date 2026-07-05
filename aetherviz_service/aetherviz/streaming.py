"""LLM streaming normalization and SSE conversion."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Iterator
from typing import Any

from aetherviz_service.aetherviz.constants import HTML_ENABLE_THINKING
from aetherviz_service.aetherviz.sse import sse_event
from aetherviz_service.llm_service import LLMStreamChunk

LLMStreamCallable = Callable[..., Iterable[Any]]


def estimate_output_tokens(value: str) -> int:
    cjk_count = len(re.findall(r"[\u4e00-\u9fff]", value))
    word_count = len(re.findall(r"[A-Za-z0-9_]+(?:[-'][A-Za-z0-9_]+)?", value))
    symbol_count = len(re.sub(r"[\u4e00-\u9fffA-Za-z0-9_\s'-]", "", value))
    return max(0, cjk_count + word_count + (symbol_count + 1) // 2)


def trim_after_html_end(value: str) -> str:
    end_index = value.lower().find("</html>")
    if end_index < 0:
        return value
    return value[: end_index + len("</html>")]


def compact_html_for_revision(html: str) -> str:
    compacted = trim_after_html_end(html).strip()
    if len(compacted) <= 22000:
        return compacted
    return (
        compacted[:11000]
        + "\n\n<!-- 中间过长内容已省略，修订时请保留原有页面结构并按修改意见更新 -->\n\n"
        + compacted[-11000:]
    )


def coerce_llm_stream_chunk(chunk: object) -> LLMStreamChunk:
    if isinstance(chunk, LLMStreamChunk):
        return chunk
    if isinstance(chunk, str):
        return LLMStreamChunk(kind="content", delta=chunk)
    if isinstance(chunk, dict):
        return LLMStreamChunk(kind=str(chunk.get("kind") or "content"), delta=str(chunk.get("delta") or ""))
    return LLMStreamChunk(
        kind=str(getattr(chunk, "kind", "content") or "content"),
        delta=str(getattr(chunk, "delta", "") or ""),
    )


def to_user_readable_thinking(delta: str, *, stage: str) -> str:
    text = re.sub(r"\s+", " ", (delta or "").strip())
    if not text:
        return ""
    cjk_count = len(re.findall(r"[\u4e00-\u9fff]", text))
    latin_count = len(re.findall(r"[A-Za-z]", text))
    if cjk_count >= 4 or latin_count < 12:
        return delta

    normalized = text.lower()
    points: list[str] = []
    keyword_points = (
        (("timeline", "scene", "storyboard", "label"), "梳理分镜时间线和关键镜头顺序"),
        (("layout", "stage", "responsive", "viewport", "screen"), "压缩单屏响应式舞台，避免 iframe 出现滚动条"),
        (("slider", "button", "control", "interactive", "speed"), "规划播放、暂停、重置、速度和教学参数控件"),
        (("caption", "narration", "explain", "description"), "整理中文旁白说明，让学生知道每一步观察重点"),
        (("svg", "canvas", "dom", "html", "css", "code", "script"), "组织 HTML、样式和动画脚本结构"),
        (("formula", "equation", "math", "value", "parameter"), "同步公式、数值和图形变化"),
        (("repair", "fix", "error", "validate", "validation"), "根据校验问题修复结构、交互和运行时契约"),
    )
    for keywords, point in keyword_points:
        if any(keyword in normalized for keyword in keywords):
            points.append(point)

    if not points:
        stage_points = {
            "html_generating": "正在把确认后的教学方案转成可运行的互动 HTML 页面",
            "html_repairing": "正在根据校验结果修复页面结构、交互绑定和动画运行逻辑",
            "html_revising": "正在根据修改意见调整当前页面，同时保持动画和交互可用",
        }
        points.append(stage_points.get(stage, "正在整理页面生成思路，并准备输出可运行 HTML"))

    unique_points = list(dict.fromkeys(points))[:3]
    return "；".join(unique_points) + "。"


def stream_llm_output(
    prompt: str,
    *,
    system_prompt: str,
    max_tokens: int,
    temperature: float,
    stage: str,
    phase: str,
    message_prefix: str,
    progress_start: int,
    progress_end: int,
    llm_stream: LLMStreamCallable,
    enable_thinking: bool = HTML_ENABLE_THINKING,
) -> Iterator[str]:
    raw_text = ""
    output_tokens_total = 0
    chunk_index = 0

    for raw_chunk in llm_stream(
        prompt,
        system_prompt=system_prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        enable_thinking=enable_thinking,
    ):
        chunk = coerce_llm_stream_chunk(raw_chunk)
        if not chunk.delta:
            continue
        if chunk.kind == "reasoning":
            thinking_delta = to_user_readable_thinking(chunk.delta, stage=stage)
            if not thinking_delta:
                continue
            output_tokens = estimate_output_tokens(thinking_delta)
            yield sse_event(
                "thinking_delta",
                {
                    "success": True,
                    "stage": stage,
                    "message": f"{message_prefix}，正在推理",
                    "progress": progress_start,
                    "phase": phase,
                    "delta": thinking_delta,
                    "output_tokens": output_tokens,
                    "output_tokens_total": output_tokens_total,
                    "chunk_index": chunk_index,
                },
            )
            continue

        delta = chunk.delta
        raw_text += delta
        chunk_index += 1
        output_tokens = estimate_output_tokens(delta)
        output_tokens_total += output_tokens
        progress = min(
            progress_end,
            progress_start + max(1, round((progress_end - progress_start) * min(output_tokens_total, max_tokens) / max_tokens)),
        )
        yield sse_event(
            "generation_delta",
            {
                "success": True,
                "stage": stage,
                "message": f"{message_prefix}，已输出约 {output_tokens_total} Token",
                "progress": progress,
                "phase": phase,
                "delta": delta,
                "output_tokens": output_tokens,
                "output_tokens_total": output_tokens_total,
                "chunk_index": chunk_index,
            },
        )
        if "</html>" in raw_text.lower():
            break

    return trim_after_html_end(raw_text)
