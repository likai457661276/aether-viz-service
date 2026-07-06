"""Theme helpers for dynamic AetherViz generation."""

from __future__ import annotations

import re


DEFAULT_PRIMARY_COLOR = "#22D3EE"


def extract_color_from_topic(topic: str) -> str:
    if not topic:
        return DEFAULT_PRIMARY_COLOR
    match = re.search(r"#[0-9A-Fa-f]{6}", topic)
    if match:
        return match.group(0).upper()

    chinese_colors = [
        ("红色", "#EF4444"), ("橙色", "#F97316"), ("黄色", "#EAB308"), ("绿色", "#22C55E"),
        ("蓝色", "#3B82F6"), ("紫色", "#A855F7"), ("粉色", "#EC4899"), ("青色", "#06B6D4"),
        ("白色", "#F8FAFC"), ("黑色", "#1E293B"),
        ("红", "#EF4444"), ("橙", "#F97316"), ("黄", "#EAB308"), ("绿", "#22C55E"),
        ("蓝", "#3B82F6"), ("紫", "#A855F7"), ("粉", "#EC4899"), ("青", "#06B6D4"),
        ("白", "#F8FAFC"), ("黑", "#1E293B"),
    ]
    for name, hex_value in chinese_colors:
        if name in topic:
            return hex_value

    return DEFAULT_PRIMARY_COLOR
