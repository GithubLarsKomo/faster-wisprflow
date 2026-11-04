"""Summarize explicitly exported FlüsterFee vNext-01 JSONL measurements.

Example:
    python benchmarks/dictation_latency/report.py --input latency-runs.jsonl \
        --output latency-report.json --commit <git-sha> --environment "Win11 A4000"
The input must contain sanitized RunTimings records only; no audio or text.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[math.ceil(0.95 * len(ordered)) - 1], 3)


def summarize(rows: list[dict]) -> dict:
    """Report sample size and P50/P95 by provider, mode and duration bucket."""
    groups = defaultdict(list)
    for row in rows:
        if row.get("schema_version") != 1:
            raise ValueError("Unsupported metrics schema")
        key = (
            row.get("provider", "other"),
            row.get("mode", "other"),
            row.get("duration_bucket", "unknown"),
        )
        groups[key].append(row)
    report = []
    for (provider, mode, duration_bucket), samples in sorted(groups.items()):
        durations = set().union(*(
            sample.get("duration_ms", {}).keys() for sample in samples
        ))
        phases = {}
        for phase in sorted(durations):
            values = [
                sample.get("duration_ms", {}).get(phase)
                for sample in samples
            ]
            nums = [float(value) for value in values if isinstance(value, (int, float))]
            phases[phase] = {
                "n": len(nums),
                "p50_ms": round(statistics.median(nums), 3) if nums else None,
                "p95_ms": _p95(nums),
            }
        report.append({
            "provider": provider,
            "mode": mode,
            "duration_bucket": duration_bucket,
            "runs": len(samples),
            "outcomes": {
                status: sum(1 for sample in samples if sample["outcome"] == status)
                for status in sorted({s["outcome"] for s in samples})
            },
            "phases": phases,
        })
    return {
        "schema_version": 1,
        "total_runs": len(rows),
        "groups": report,
        "baseline_ready": all(g["runs"] >= 100 for g in report) if report else False,
        "note": "Compare warm/cold separately; real Windows hardware tests required.",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--commit", default="unknown")
    parser.add_argument("--environment", default="not-recorded")
    parser.add_argument("--model-hash", default="not-recorded")
    parser.add_argument("--warm", choices=["yes", "no", "mixed"], default="mixed")
    args = parser.parse_args()
    with Path(args.input).open(encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle if line.strip()]
    report = summarize(rows)
    report["provenance"] = {
        "app_commit": args.commit,
        "environment": args.environment,
        "model_hash": args.model_hash,
        "warm_cache": args.warm,
    }
    Path(args.output).write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
