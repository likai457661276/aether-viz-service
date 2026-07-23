"""Tests for shared IR streaming retries and candidate envelopes."""

from __future__ import annotations

import json

import pytest
from langchain_core.messages import HumanMessage

from aetherviz_service.aetherviz.contracts.html_stream import HtmlGenerationError
from aetherviz_service.aetherviz.ir.candidates import (
    IR_CANDIDATE_MAX_ITEMS,
    candidates_envelope_schema,
    validate_candidate_count,
)
from aetherviz_service.aetherviz.ir.coordinate_graph.contract import (
    coordinate_graph_ir_candidates_response_schema,
)
from aetherviz_service.aetherviz.ir.data_distribution.contract import (
    data_distribution_ir_candidates_response_schema,
    parse_data_distribution_ir_candidates,
)
from aetherviz_service.aetherviz.ir.linked_coordinate.contract import (
    linked_coordinate_ir_candidates_response_schema,
    parse_linked_coordinate_ir_candidates,
)
from aetherviz_service.aetherviz.ir import stream as ir_stream
from aetherviz_service.aetherviz.ir.stream import (
    looks_like_incomplete_json,
    stream_ir_json,
    uses_strong_ir_repair_model,
)


def test_high_frequency_candidate_schemas_allow_three() -> None:
    for schema in (
        coordinate_graph_ir_candidates_response_schema(),
        linked_coordinate_ir_candidates_response_schema(),
        data_distribution_ir_candidates_response_schema(),
    ):
        props = schema["properties"]["candidates"]
        assert props["minItems"] == 2
        assert props["maxItems"] == IR_CANDIDATE_MAX_ITEMS == 3


def test_validate_candidate_count_accepts_two_or_three() -> None:
    assert len(validate_candidate_count([{"a": 1}, {"b": 2}])) == 2
    assert len(validate_candidate_count([{"a": 1}, {"b": 2}, {"c": 3}])) == 3
    with pytest.raises(ValueError):
        validate_candidate_count([{"a": 1}])


def test_parse_helpers_accept_three_candidates() -> None:
    payload = {"candidates": [{"version": "x"}, {"version": "y"}, {"version": "z"}]}
    raw = json.dumps(payload)
    assert len(parse_linked_coordinate_ir_candidates(raw)) == 3
    assert len(parse_data_distribution_ir_candidates(raw)) == 3


def test_candidates_envelope_schema_preserves_defs() -> None:
    item = {
        "type": "object",
        "additionalProperties": False,
        "$defs": {"point": {"type": "object"}},
        "properties": {"id": {"type": "string"}},
        "required": ["id"],
    }
    schema = candidates_envelope_schema(item, max_items=3)
    assert "$defs" in schema
    assert schema["properties"]["candidates"]["maxItems"] == 3


def test_looks_like_incomplete_json() -> None:
    assert looks_like_incomplete_json("")
    assert looks_like_incomplete_json('{"candidates":[')
    assert not looks_like_incomplete_json('{"candidates":[]}')


def test_stream_ir_json_retries_incomplete_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ir_stream.settings, "aetherviz_html_stream_max_retries", 1)
    calls = {"n": 0}

    class FakeModel:
        def stream(self, _messages):
            calls["n"] += 1
            if calls["n"] == 1:
                yield {"content": '{"candidates":['}
                return
            yield {"content": json.dumps({"candidates": [{"ok": True}, {"ok": True}]})}

    monkeypatch.setattr(ir_stream, "create_chat_model", lambda *_args, **_kwargs: FakeModel())
    result = stream_ir_json(
        [HumanMessage(content="x")],
        response_schema={"type": "object"},
        max_chars=10_000,
        label="test IR",
    )
    assert calls["n"] == 2
    assert result.attempt == 2
    assert json.loads(result.text)["candidates"]


def test_stream_ir_json_raises_after_retries_exhausted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ir_stream.settings, "aetherviz_html_stream_max_retries", 1)

    class FakeModel:
        def stream(self, _messages):
            yield {"content": '{"candidates":['}

    monkeypatch.setattr(ir_stream, "create_chat_model", lambda *_args, **_kwargs: FakeModel())
    with pytest.raises(HtmlGenerationError) as exc:
        stream_ir_json(
            [HumanMessage(content="x")],
            response_schema={"type": "object"},
            max_chars=10_000,
            label="test IR",
        )
    assert exc.value.code == "ir_stream_interrupted"


def test_complex_ir_backends_use_strong_repair_model() -> None:
    assert uses_strong_ir_repair_model("recomposition_scene")
    assert uses_strong_ir_repair_model("constraint_geometry_scene")
    assert not uses_strong_ir_repair_model("coordinate_graph_scene")
