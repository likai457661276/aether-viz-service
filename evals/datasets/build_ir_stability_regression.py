#!/usr/bin/env python3
"""Mine local, desensitized traces into IR stability failure-mode candidates.

Never writes authoritative expectations. Reviewers must set outputs before merging
into ``failure_modes.jsonl``. Operates only on local files; does not call LangSmith
CLI/SDK/API or upload remote datasets.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from evals.datasets.ir_stability.taxonomy import classify_failure_mode

_SECRET_RE = re.compile(r"(?i)(api[_-]?key|token|authorization|bearer|sk-[a-z0-9]+)")
_URL_RE = re.compile(r"https?://[^\s\"']+")


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _scrub(text: str) -> str:
    cleaned = _SECRET_RE.sub("[redacted]", text)
    return _URL_RE.sub("[redacted-url]", cleaned)[:500]


def _load_json_blob(path: Path) -> list[dict[str, Any]]:
    raw = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl":
        return [json.loads(line) for line in raw.splitlines() if line.strip()]
    payload = json.loads(raw)
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("runs", "failures", "records", "traces"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return [payload]
    return []


def _signals(record: dict[str, Any]) -> list[str]:
    signals: list[str] = []
    signals.extend(str(item) for item in record.get("failed_metrics", []) if item)
    signals.extend(str(item) for item in record.get("initial_hard_failures", []) if item)
    signals.extend(str(item) for item in record.get("final_hard_failures", []) if item)
    if record.get("generation_error"):
        signals.append(str(record["generation_error"]))
    if record.get("error"):
        signals.append(str(record["error"]))
    if record.get("code"):
        signals.append(str(record["code"]))
    detail = record.get("detail") or record.get("error_detail")
    if detail:
        signals.append(str(detail))
    for stage in _as_list(record.get("stages")):
        if isinstance(stage, dict) and stage.get("error"):
            signals.append(str(stage["error"]))
        metadata = _as_dict(stage.get("metadata") if isinstance(stage, dict) else {})
        if metadata.get("code"):
            signals.append(str(metadata["code"]))
    ranking = _as_dict(record.get("candidate_ranking_report"))
    for candidate in _as_list(ranking.get("candidates")):
        if isinstance(candidate, dict):
            signals.extend(str(item) for item in candidate.get("hard_failures", []) if item)
    return signals


def build_candidates(paths: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        for index, record in enumerate(_load_json_blob(path)):
            signals = _signals(record)
            if not signals and not record.get("fallback") and record.get("ok") is not False:
                continue
            failure_mode = classify_failure_mode(signals)
            plan = _as_dict(record.get("plan")) or _as_dict(_as_dict(record.get("inputs")).get("plan"))
            profile = _as_dict(plan.get("knowledge_profile"))
            metadata = _as_dict(record.get("metadata"))
            topic = str(
                record.get("topic")
                or _as_dict(record.get("inputs")).get("topic")
                or metadata.get("topic")
                or ""
            )[:240]
            case_id = str(record.get("id") or record.get("case_id") or f"{path.stem}-{index}")
            rows.append(
                {
                    "inputs": {
                        "case_id": case_id,
                        "topic": topic,
                        "mode": "pending_review",
                        "backend": metadata.get("generation_backend")
                        or record.get("generation_backend")
                        or record.get("backend"),
                        "plan": {
                            "interactive_type": plan.get("interactive_type"),
                            "knowledge_profile": {
                                "representation_type": profile.get("representation_type"),
                                "concept_family": profile.get("concept_family"),
                            }
                            if profile
                            else {},
                        },
                        "signal_preview": [_scrub(str(item)) for item in signals[:8]],
                    },
                    "outputs": {},
                    "metadata": {
                        "interactive_type": plan.get("interactive_type")
                        or metadata.get("interactive_type")
                        or "unknown",
                        "representation_type": profile.get("representation_type")
                        or metadata.get("representation_type")
                        or "unknown",
                        "failure_mode": failure_mode,
                        "source": "trace_candidate",
                        "pending_review": True,
                        "origin_path": str(path),
                    },
                    "tags": ["ir_stability", "pending_review", failure_mode],
                }
            )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("traces", nargs="+", type=Path, help="Local failures/runs/trace JSON or JSONL files")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = build_candidates(args.traces)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    summary = {
        "candidates": len(rows),
        "output": str(args.output),
        "note": "outputs remain empty until human review; do not upload to LangSmith",
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
