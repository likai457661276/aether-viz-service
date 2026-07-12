#!/usr/bin/env python3
"""Build a local LangSmith-compatible visual-quality dataset from trace exports."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _message_content(run: dict) -> str:
    try:
        return str(run["outputs"]["generations"][0][0]["message"]["kwargs"]["content"])
    except (KeyError, IndexError, TypeError):
        return ""


def trace_example(path: Path) -> dict | None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    runs = payload.get("runs", []) if isinstance(payload, dict) else []
    llm = next((run for run in runs if run.get("run_type") == "llm" and "<!DOCTYPE html>" in _message_content(run)), None)
    root = next((run for run in runs if not run.get("parent_run_id")), None)
    if not llm:
        return None
    return {
        "trace_id": payload.get("trace_id"),
        "inputs": {
            "html": _message_content(llm),
            "topic": (root or {}).get("inputs", {}).get("topic", ""),
        },
        "outputs": {
            "max_stroke_width_px": 12,
            "max_label_height_px": 48,
            "stage_must_not_clip": True,
            "required_viewports": ["960x540", "1280x720", "390x844"],
        },
        "metadata": {"source": "langsmith_trace", "dataset_type": "single_step"},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("traces", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    examples = [example for path in args.traces if (example := trace_example(path))]
    args.output.write_text(json.dumps(examples, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"examples": len(examples), "output": str(args.output)}, ensure_ascii=False))
    return 0 if examples else 1


if __name__ == "__main__":
    raise SystemExit(main())
