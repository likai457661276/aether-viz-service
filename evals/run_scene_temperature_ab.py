"""Offline A/B harness for IR candidate-generation temperature exploration.

Production Scene IR temperature stays 0. This script only monkeypatches the scene
model for local live-model runs, comparing first-pass eligibility and candidate
fingerprint diversity. It never uploads LangSmith datasets.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from aetherviz_service.aetherviz.agents import model_factory
from aetherviz_service.aetherviz.ir.recomposition import agent as recomposition_agent
from aetherviz_service.aetherviz.workflow.plan_contract import normalize_plan
from aetherviz_service.config import settings

DEFAULT_TOPICS = Path(__file__).parent / "datasets" / "recomposition" / "dataset.jsonl"


def _load_topics(path: Path, *, limit: int) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    topics: list[dict[str, Any]] = []
    for row in rows:
        topic = str(row.get("topic") or row.get("inputs", {}).get("topic") or "").strip()
        if not topic:
            continue
        plan = row.get("plan") or row.get("inputs", {}).get("plan") or {}
        topics.append({"topic": topic, "plan": plan if isinstance(plan, dict) else {}})
        if len(topics) >= limit:
            break
    return topics


def _patch_scene_temperature(monkey_temperature: float, captured: list[float]):
    original = model_factory.create_chat_model

    def wrapped(kind: str, *, response_schema: dict[str, Any] | None = None):
        if kind != "scene":
            return original(kind, response_schema=response_schema)
        from langchain_openai import ChatOpenAI

        captured.append(monkey_temperature)
        kwargs = model_factory._html_model_kwargs(max_tokens=settings.aetherviz_scene_max_tokens)
        kwargs["temperature"] = monkey_temperature
        kwargs["extra_body"] = {"enable_thinking": False}
        kwargs.pop("reasoning_effort", None)
        kwargs["model_kwargs"] = {
            "response_format": (
                {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "aetherviz_geometry_ir",
                        "strict": True,
                        "schema": response_schema,
                    },
                }
                if response_schema
                else {"type": "json_object"}
            )
        }
        return ChatOpenAI(**kwargs)

    return wrapped


def _run_one(topic: str, plan: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_plan(plan, topic)
    started = time.monotonic()
    try:
        _source, degraded, ranking = recomposition_agent._generate_ranked_scene_source(topic, normalized)
        fingerprints = [
            str(item.get("fingerprint") or "")
            for item in ranking.get("candidates", [])
            if isinstance(item, dict)
        ]
        return {
            "ok": True,
            "topic": topic,
            "ranking_ok": bool(ranking.get("ok")),
            "degraded": bool(degraded),
            "candidate_count": len(ranking.get("candidates", [])),
            "eligible_count": sum(1 for item in ranking.get("candidates", []) if item.get("eligible")),
            "unique_fingerprints": len({item for item in fingerprints if item}),
            "strategy": ranking.get("strategy"),
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }
    except Exception as exc:  # noqa: BLE001 - collect live-model failures into report
        return {
            "ok": False,
            "topic": topic,
            "ranking_ok": False,
            "degraded": True,
            "error": type(exc).__name__,
            "detail": str(exc)[:240],
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }


def summarize(runs: list[dict[str, Any]], *, temperature: float) -> dict[str, Any]:
    total = len(runs)
    ranking_ok = sum(1 for item in runs if item.get("ranking_ok"))
    unique_fp = [int(item.get("unique_fingerprints") or 0) for item in runs if item.get("ok")]
    return {
        "temperature": temperature,
        "total": total,
        "first_pass_ok": ranking_ok,
        "first_pass_rate": round(ranking_ok / total, 4) if total else 0.0,
        "mean_unique_fingerprints": round(sum(unique_fp) / len(unique_fp), 4) if unique_fp else 0.0,
        "error_count": sum(1 for item in runs if not item.get("ok")),
        "runs": runs,
    }


def run_ab(
    *,
    topics: list[dict[str, Any]],
    temperatures: list[float],
    live_model: bool,
) -> dict[str, Any]:
    if not live_model:
        return {
            "ok": True,
            "dry_run": True,
            "temperatures": temperatures,
            "topic_count": len(topics),
            "note": "Pass --live-model to execute Scene IR generation A/B locally.",
        }
    if not settings.openai_api_key:
        raise SystemExit("OPENAI_API_KEY is required for --live-model temperature A/B")

    arms = []
    original = model_factory.create_chat_model
    try:
        for temperature in temperatures:
            captured: list[float] = []
            model_factory.create_chat_model = _patch_scene_temperature(temperature, captured)  # type: ignore[assignment]
            recomposition_agent.create_chat_model = model_factory.create_chat_model  # type: ignore[attr-defined]
            runs = [_run_one(item["topic"], item["plan"]) for item in topics]
            arms.append({**summarize(runs, temperature=temperature), "scene_patches": len(captured)})
    finally:
        model_factory.create_chat_model = original  # type: ignore[assignment]
        if hasattr(recomposition_agent, "create_chat_model"):
            recomposition_agent.create_chat_model = original  # type: ignore[attr-defined]

    baseline = next((arm for arm in arms if arm["temperature"] == 0.0), arms[0] if arms else None)
    comparisons = []
    for arm in arms:
        if baseline is None or arm is baseline:
            continue
        comparisons.append(
            {
                "temperature": arm["temperature"],
                "first_pass_rate_delta": round(arm["first_pass_rate"] - baseline["first_pass_rate"], 4),
                "mean_unique_fingerprints_delta": round(
                    arm["mean_unique_fingerprints"] - baseline["mean_unique_fingerprints"], 4
                ),
            }
        )
    return {
        "ok": True,
        "dry_run": False,
        "production_default_temperature": 0.0,
        "arms": arms,
        "comparisons_vs_zero": comparisons,
        "decision_note": (
            "Keep production Scene IR temperature at 0 unless offline A/B shows clear "
            "first-pass gains without raising hard-failure / repair rates."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_TOPICS)
    parser.add_argument("--max-topics", type=int, default=3)
    parser.add_argument(
        "--temperatures",
        default="0,0.05",
        help="Comma-separated temperatures to compare (include 0 as baseline)",
    )
    parser.add_argument("--live-model", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    temperatures = [float(part.strip()) for part in args.temperatures.split(",") if part.strip()]
    topics = _load_topics(args.dataset, limit=max(args.max_topics, 1))
    report = run_ab(topics=topics, temperatures=temperatures, live_model=args.live_model)
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    print(rendered, end="")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
