from __future__ import annotations

import json
from unittest.mock import MagicMock

from aetherviz_service.aetherviz.agents import edit_patch_agent
from aetherviz_service.aetherviz.agents.edit_patch_agent import EditPatchResult
from aetherviz_service.aetherviz.tools.content_patch import (
    apply_content_replacements,
    select_content_descriptions,
)

SOURCE = """<!DOCTYPE html><html><head><style>#stage{display:none;color:red}</style></head>
<body><main id="stage" data-role="main-visual"><svg><circle r="4"></circle></svg></main>
<p data-region="caption">旧说明</p></body></html>"""


def test_select_content_descriptions_for_blank_visual() -> None:
    descriptions = select_content_descriptions(SOURCE, "动画图像默认空白，请正确显示")

    assert {item["kind"] for item in descriptions} == {"style", "visual"}


def test_apply_content_replacement_requires_hash_and_preserves_identity() -> None:
    descriptions = select_content_descriptions(SOURCE, "动画图像默认空白，请正确显示")
    style = next(item for item in descriptions if item["kind"] == "style")
    result = apply_content_replacements(
        SOURCE,
        [
            {
                "kind": "style",
                "target_id": style["target_id"],
                "source_hash": style["source_hash"],
                "replacement": "<style>#stage{display:grid;color:red}</style>",
            }
        ],
        allowed_descriptions=descriptions,
    )

    assert result.errors == ()
    assert result.applied == (style["target_id"],)
    assert "display:grid" in result.html


def test_content_replacement_rejects_identity_change_and_script() -> None:
    descriptions = select_content_descriptions(SOURCE, "动画图像默认空白，请正确显示")
    visual = next(item for item in descriptions if item["kind"] == "visual")
    result = apply_content_replacements(
        SOURCE,
        [
            {
                "kind": "visual",
                "target_id": visual["target_id"],
                "source_hash": visual["source_hash"],
                "replacement": '<main id="other" data-role="main-visual"><script>alert(1)</script></main>',
            }
        ],
        allowed_descriptions=descriptions,
    )

    assert result.html == SOURCE
    assert result.applied == ()
    assert result.errors[0].startswith("content_script_not_allowed:")


def test_edit_agent_applies_structured_style_patch(monkeypatch) -> None:
    descriptions = select_content_descriptions(SOURCE, "动画图像默认空白，请正确显示")
    style = next(item for item in descriptions if item["kind"] == "style")
    response = json.dumps(
        {
            "replacements": [],
            "blocks": [
                {
                    "kind": "style",
                    "target_id": style["target_id"],
                    "source_hash": style["source_hash"],
                    "replacement": "<style>#stage{display:grid;color:red}</style>",
                }
            ],
        }
    )

    class PatchModel:
        def stream(self, messages):
            yield MagicMock(
                content=response,
                response_metadata={"finish_reason": "stop"},
                usage_metadata={"input_tokens": 800, "output_tokens": 120},
            )

    monkeypatch.setattr(edit_patch_agent, "create_chat_model", lambda kind: PatchModel())
    result = next(
        item
        for item in edit_patch_agent._stream_edit_patch_impl(
            raw_html=SOURCE,
            instruction="动画图像默认空白，请正确显示",
            topic="动画",
        )
        if isinstance(item, EditPatchResult)
    )

    assert result.strategy == "structured_patch"
    assert result.applied_blocks == (style["target_id"],)
    assert result.output_tokens == 120
    assert "display:grid" in result.html
