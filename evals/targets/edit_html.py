"""Local targets for Edit HTML single-step and end-to-end evaluation."""

from __future__ import annotations

import hashlib
import json
import tempfile
import uuid
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from aetherviz_service.aetherviz.agents.model_factory import create_chat_model, extract_llm_text
from aetherviz_service.aetherviz.contracts.layout import assemble_layout_contract, extract_business_html
from aetherviz_service.aetherviz.contracts.validation.report import build_validation_report
from aetherviz_service.aetherviz.edit.context import build_edit_assembly_plan, build_edit_context_summary
from aetherviz_service.aetherviz.edit.diagnosis import diagnose_edit
from aetherviz_service.aetherviz.edit.workflow import _run_edit_html_workflow_impl
from evals.targets.visual import evaluate_html

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_JUDGE_CACHE = ROOT / "evals/reports/edit-html/judge-cache.jsonl"

JUDGE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["teaching_semantics", "visual_quality", "edit_relevance", "reasoning"],
    "properties": {
        "teaching_semantics": {"type": "number", "minimum": 0, "maximum": 1},
        "visual_quality": {"type": "number", "minimum": 0, "maximum": 1},
        "edit_relevance": {"type": "number", "minimum": 0, "maximum": 1},
        "reasoning": {"type": "string", "maxLength": 500},
    },
}


def load_examples(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _fixture(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def run_diagnosis_case(example: dict[str, Any], *, live_model: bool) -> dict[str, Any]:
    inputs = example["inputs"]
    baseline_html = _fixture(str(inputs["baseline_fixture"]))
    if live_model:
        context_summary = build_edit_context_summary(
            instruction=str(inputs["instruction"]),
            business_html=baseline_html,
            context=inputs.get("context"),
            validation_report=build_validation_report(baseline_html),
            edit_target=inputs.get("edit_target"),
            runtime_error=inputs.get("runtime_error"),
        )
        diagnosis = diagnose_edit(
            instruction=str(inputs["instruction"]),
            business_html=baseline_html,
            context_summary=context_summary,
        ).public_dict()
    else:
        diagnosis = _diagnosis_scaffold(example)
    return {"diagnosis": diagnosis, "baseline_html": baseline_html}


def _diagnosis_scaffold(example: dict[str, Any]) -> dict[str, Any]:
    expected = example["outputs"]
    checks = []
    for index, kind in enumerate(expected.get("required_hard_change_kinds", []), 1):
        check: dict[str, Any] = {
            "id": f"scaffold_change_{index}",
            "kind": kind,
            "selector": "",
            "function": "",
            "property": "",
            "expected": "",
            "baseline_binding": "must_differ",
            "severity": "hard",
            "rationale": "deterministic evaluator scaffold",
            "group": "change",
        }
        check.update(expected.get("claim_bindings", {}).get(kind, {}))
        checks.append(check)
    return {
        "strategy": expected.get("strategy", "full_html_regeneration"),
        "resolved_instruction": example["inputs"]["instruction"],
        "impact_areas": expected.get("required_impact_areas", []),
        "change_requirements": [example["inputs"]["instruction"]],
        "preserve_requirements": expected.get("preserve_requirements", []),
        "change_checks": checks,
        "preserve_checks": [],
        "requires_clarification": expected.get("strategy") == "clarification_required",
    }


def run_end_to_end_case(
    example: dict[str, Any],
    *,
    live_model: bool,
    browser: bool,
    judge: bool,
) -> dict[str, Any]:
    inputs = example["inputs"]
    baseline_html = _fixture(str(inputs["baseline_fixture"]))
    if live_model:
        candidate_html, metadata, events = _run_live_edit(inputs, baseline_html)
    else:
        candidate_html = _fixture(str(inputs["candidate_fixture"]))
        expected = example["outputs"]
        metadata = {
            "intent_passed": True,
            "intent_check_count": len(expected.get("change_checks", [])) + len(expected.get("preserve_checks", [])),
            "intent_summary": "intent_ok",
        }
        events = ["deterministic.fixture"]
    business_html = extract_business_html(candidate_html)
    plan = build_edit_assembly_plan(business_html, str(inputs.get("topic") or "Edit HTML Eval"))
    assembled_html = assemble_layout_contract(business_html, plan)
    output: dict[str, Any] = {
        "baseline_html": extract_business_html(baseline_html),
        "candidate_html": business_html,
        "metadata": metadata,
        "events": events,
        "validation": build_validation_report(assembled_html, plan=plan, model_html=business_html),
    }
    if browser:
        with tempfile.TemporaryDirectory(prefix="aetherviz-edit-eval-") as temp_dir:
            path = Path(temp_dir) / "candidate.html"
            path.write_text(assembled_html, encoding="utf-8")
            output["browser"] = evaluate_html(path, Path(temp_dir) / "browser")
    if judge:
        output["judge"] = _judge_edit(inputs, output["baseline_html"], business_html)
    return output


def _run_live_edit(inputs: dict[str, Any], baseline_html: str) -> tuple[str, dict[str, Any], list[str]]:
    chunks = list(
        _run_edit_html_workflow_impl(
            run_id=f"local-edit-eval-{uuid.uuid4().hex[:12]}",
            current_html=baseline_html,
            message=str(inputs["instruction"]),
            context={"topic": inputs.get("topic"), **(inputs.get("context") or {})},
            edit_target=inputs.get("edit_target"),
            runtime_error=inputs.get("runtime_error"),
        )
    )
    events: list[str] = []
    candidate_html = ""
    metadata: dict[str, Any] = {}
    for chunk in chunks:
        event = next((line[7:] for line in chunk.splitlines() if line.startswith("event: ")), "")
        data_line = next((line[6:] for line in chunk.splitlines() if line.startswith("data: ")), "")
        if event:
            events.append(event)
        if event != "html.done" or not data_line:
            continue
        payload = json.loads(data_line)
        data = payload.get("data") or {}
        candidate_html = str(data.get("html") or "")
        metadata = data.get("metadata") or {}
    if not candidate_html:
        raise RuntimeError(f"edit_workflow_failed:events={events}")
    return candidate_html, metadata, events


def _judge_edit(inputs: dict[str, Any], baseline_html: str, candidate_html: str) -> dict[str, Any]:
    cache_key = hashlib.sha256(
        json.dumps(
            {
                "instruction": inputs["instruction"],
                "baseline_html": baseline_html,
                "candidate_html": candidate_html,
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    cached = _cached_judge_grade(cache_key)
    if cached is not None:
        return cached
    prompt = {
        "instruction": inputs["instruction"],
        "baseline_html": baseline_html,
        "candidate_html": candidate_html,
        "rubric": {
            "teaching_semantics": "教学事实、表征关系与交互反馈正确",
            "visual_quality": "层级清楚、内容可读且主视觉适合教学",
            "edit_relevance": "准确完成要求且没有无关重做",
        },
    }
    model = create_chat_model("edit_analysis", response_schema=JUDGE_SCHEMA)
    response = model.invoke(
        [
            SystemMessage(content="你是离线 Edit HTML 质量评审。每个维度给出 0 到 1 分，只输出 schema JSON。"),
            HumanMessage(content=json.dumps(prompt, ensure_ascii=False)),
        ]
    )
    value = json.loads(extract_llm_text(response))
    grade = value if isinstance(value, dict) else {}
    DEFAULT_JUDGE_CACHE.parent.mkdir(parents=True, exist_ok=True)
    with DEFAULT_JUDGE_CACHE.open("a", encoding="utf-8") as cache:
        cache.write(json.dumps({"key": cache_key, "grade": grade}, ensure_ascii=False) + "\n")
    return grade


def _cached_judge_grade(cache_key: str) -> dict[str, Any] | None:
    if not DEFAULT_JUDGE_CACHE.exists():
        return None
    for line in DEFAULT_JUDGE_CACHE.read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if item.get("key") == cache_key and isinstance(item.get("grade"), dict):
            return item["grade"]
    return None
