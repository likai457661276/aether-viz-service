#!/usr/bin/env python3
"""Mine local, desensitized traces for IR-routing disagreement candidates.

This script never writes an authoritative expected backend. Reviewers must set
``outputs.selected_backend`` before merging a candidate into ``ir_routing/``.

It operates only on local files and does not call LangSmith CLI/SDK/API.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

AUTHORITATIVE_ROUTING_DIR = Path(__file__).resolve().parent / "ir_routing"


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _topic_from(payload: dict[str, Any], decision: dict[str, Any]) -> str:
    input_plan = _as_dict(_as_dict(payload.get("inputs")).get("plan"))
    for source in (
        payload.get("topic"),
        _as_dict(payload.get("inputs")).get("topic"),
        input_plan.get("source_topic"),
        _as_dict(decision.get("plan")).get("source_topic"),
        _as_dict(payload.get("metadata")).get("topic"),
    ):
        text = str(source or "").strip()
        if text:
            return text[:240]
    return ""


def _plan_seed(payload: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any] | None:
    for source in (
        payload.get("plan"),
        _as_dict(payload.get("inputs")).get("plan"),
        decision.get("plan"),
    ):
        if isinstance(source, dict) and source:
            return source
    return None


def _decision_from_metadata(metadata: dict[str, Any]) -> dict[str, Any] | None:
    if "selected_backend" in metadata and "llm_invoked" in metadata:
        return {"deterministic_observed": True, **metadata}
    if not metadata.get("generation_route_llm_invoked"):
        return None
    return {
        "selected_backend": metadata.get("generation_backend"),
        "deterministic_observed": True,
        "llm_invoked": True,
        "llm_accepted": bool(metadata.get("generation_route_llm_accepted")),
        "fallback": metadata.get("generation_route_fallback"),
        "llm_selected_backend": metadata.get("generation_route_llm_selected_backend"),
        "llm_confidence": metadata.get("generation_route_llm_confidence"),
        "llm_required_capabilities": metadata.get("generation_route_llm_required_capabilities") or [],
        "candidates": metadata.get("generation_route_candidates") or [],
        "confidence": metadata.get("generation_route_confidence"),
        "source": metadata.get("generation_route_source"),
        "plan_fingerprint": metadata.get("generation_route_plan_fingerprint"),
        "reasons": metadata.get("generation_route_reasons") or [],
    }


def _decisions_from_run(run: dict[str, Any]) -> list[dict[str, Any]]:
    decisions: list[dict[str, Any]] = []
    name = str(run.get("name") or "")
    outputs = _as_dict(run.get("outputs"))
    metadata = _as_dict(run.get("extra")).get("metadata")
    if not isinstance(metadata, dict):
        metadata = _as_dict(run.get("metadata"))
    if name == "aetherviz.ir_routing_judge" or "ir_routing" in name:
        judged = outputs if "selected_backend" in outputs else _as_dict(outputs.get("output"))
        if judged:
            decisions.append(
                {
                    "selected_backend": None,
                    "deterministic_observed": False,
                    "llm_invoked": True,
                    "llm_accepted": False,
                    "fallback": "judge_run_only",
                    "llm_selected_backend": judged.get("selected_backend"),
                    "llm_confidence": judged.get("confidence"),
                    "llm_required_capabilities": judged.get("required_capabilities") or [],
                    "evidence": judged.get("evidence") or [],
                    "source": "llm_judge_run",
                }
            )
    final = _as_dict(outputs.get("final"))
    for candidate in (
        _decision_from_metadata(outputs),
        _decision_from_metadata(final),
        _decision_from_metadata(metadata),
        _decision_from_metadata(_as_dict(outputs.get("metadata"))),
        _decision_from_metadata(_as_dict(_as_dict(outputs.get("data")).get("metadata"))),
    ):
        if candidate:
            decisions.append(candidate)
    return decisions


def _decisions_from_runs(payload: dict[str, Any]) -> list[dict[str, Any]]:
    decisions: list[dict[str, Any]] = []
    for run in _as_list(payload.get("runs")):
        if isinstance(run, dict):
            decisions.extend(_decisions_from_run(run))
    return decisions


def extract_decisions(payload: dict[str, Any]) -> list[dict[str, Any]]:
    decisions: list[dict[str, Any]] = []
    direct = _decision_from_metadata(payload)
    if direct:
        decisions.append(direct)
    nested = _decision_from_metadata(_as_dict(payload.get("metadata")))
    if nested:
        decisions.append(nested)
    route = payload.get("route")
    if isinstance(route, dict):
        decisions.append({"deterministic_observed": True, **route})
    # ``langsmith trace export --full`` writes one run object per JSONL line.
    if "name" in payload and "outputs" in payload:
        decisions.extend(_decisions_from_run(payload))
    decisions.extend(_decisions_from_runs(payload))
    # Prefer richer decision dicts (with candidates / deterministic top) first.
    decisions.sort(key=lambda item: (len(_as_list(item.get("candidates"))), "selected_backend" in item), reverse=True)
    return decisions


def is_disagreement(decision: dict[str, Any]) -> bool:
    if not decision.get("llm_invoked"):
        return False
    if decision.get("deterministic_observed") is False:
        return False
    deterministic = decision.get("selected_backend")
    llm_selected = decision.get("llm_selected_backend")
    fallback = str(decision.get("fallback") or "")
    if fallback == "llm_selection_rejected":
        return True
    if fallback == "shadow_mode":
        return llm_selected != deterministic
    return llm_selected != deterministic and (llm_selected is not None or deterministic is not None)


def candidate_row(payload: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    topic = _topic_from(payload, decision)
    plan = _plan_seed(payload, decision)
    inputs: dict[str, Any] = {"topic": topic}
    if plan is not None:
        inputs["plan"] = plan
    tags = ["pending_review", "trace_candidate"]
    fallback = str(decision.get("fallback") or "")
    if fallback == "shadow_mode":
        tags.append("shadow_disagreement")
    elif fallback == "llm_selection_rejected":
        tags.append("llm_selection_rejected")
    elif decision.get("llm_selected_backend") != decision.get("selected_backend"):
        tags.append("router_disagreement")
    return {
        "inputs": inputs,
        # Deliberately unset: human review must choose the expected backend.
        "outputs": {"selected_backend": None},
        "tags": tags,
        "metadata": {
            "source": "langsmith_trace",
            "dataset_type": "single_step",
            "review_status": "pending",
            "trace_id": payload.get("trace_id") or _as_dict(payload.get("metadata")).get("trace_id"),
            "deterministic_selected": decision.get("selected_backend"),
            "llm_selected_backend": decision.get("llm_selected_backend"),
            "llm_confidence": decision.get("llm_confidence"),
            "llm_required_capabilities": list(decision.get("llm_required_capabilities") or []),
            "fallback": decision.get("fallback"),
            "route_source": decision.get("source"),
            "plan_fingerprint": decision.get("plan_fingerprint"),
            "candidates": decision.get("candidates") or [],
            "reasons": list(decision.get("reasons") or []),
        },
    }


def load_payloads(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    if path.suffix == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    payload = json.loads(text)
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        return [payload]
    return []


def build_candidates(paths: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in paths:
        for payload in load_payloads(path):
            for decision in extract_decisions(payload):
                if not is_disagreement(decision):
                    continue
                row = candidate_row(payload, decision)
                if not row["inputs"]["topic"]:
                    continue
                fingerprint = json.dumps(
                    {
                        "topic": row["inputs"].get("topic"),
                        "deterministic_selected": row["metadata"]["deterministic_selected"],
                        "llm_selected_backend": row["metadata"]["llm_selected_backend"],
                        "fallback": row["metadata"]["fallback"],
                        "trace_id": row["metadata"].get("trace_id"),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                if fingerprint in seen:
                    continue
                seen.add(fingerprint)
                rows.append(row)
                break
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("traces", nargs="+", type=Path, help="Local desensitized trace JSON/JSONL files")
    parser.add_argument("--output", required=True, type=Path, help="Candidate JSONL path (not routing_core)")
    args = parser.parse_args()
    output = args.output.resolve()
    if output == AUTHORITATIVE_ROUTING_DIR or AUTHORITATIVE_ROUTING_DIR in output.parents:
        parser.error("候选样本不能直接写入 datasets/ir_routing；请先输出到本地 pending 文件并人工审核")
    if output.exists():
        parser.error("输出文件已存在；为避免覆盖人工标注，请换用新的 pending 文件")
    rows = build_candidates(args.traces)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "candidates": len(rows),
                "output": str(output),
                "note": "outputs.selected_backend is null until human review",
            },
            ensure_ascii=False,
        )
    )
    return 0 if rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
