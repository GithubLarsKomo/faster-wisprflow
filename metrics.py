"""Data-minimized, per-run monotonic latency marks and bounded local summaries.

No audio, transcript, prompts, clipboard, window titles or network telemetry.
JSONL export is opt-in via the local latency_export_path configuration key.
"""

from __future__ import annotations

import json
import math
import statistics
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path


MARKS = frozenset({
    "record_stop", "audio_ready", "asr_start", "asr_final",
    "gate_start", "gate_end", "llm_start", "llm_end",
    "insert_start", "insert_dispatch", "insert_end", "completed",
})
PHASE_PAIRS = {
    "audio_prepare_ms": ("record_stop", "audio_ready"),
    "asr_ms": ("asr_start", "asr_final"),
    "gate_ms": ("gate_start", "gate_end"),
    "llm_ms": ("llm_start", "llm_end"),
    "insertion_ms": ("insert_start", "insert_end"),
    "record_stop_to_asr_final_ms": ("record_stop", "asr_final"),
    "asr_final_to_insert_ms": ("asr_final", "insert_dispatch"),
    "release_to_insert_ms": ("record_stop", "insert_dispatch"),
}
_ALLOWED_PROVIDERS = {"local", "groq", "openrouter", "openai"}
_ALLOWED_MODES = {"fast", "smart", "polish"}
_ALLOWED_OUTCOMES = {
    "dispatched", "target_changed", "no_audio", "no_speech",
    "cancelled", "error", "insertion_failed",
}


def _public_label(value: str, allowed: set[str]) -> str:
    return value if value in allowed else "other"


def percentile(values: list[float], percent: float) -> float | None:
    """Nearest-rank quantile (documented for reproducible small-sample P95)."""
    if not values:
        return None
    ordered = sorted(values)
    idx = max(0, math.ceil(percent / 100 * len(ordered)) - 1)
    return round(ordered[idx], 3)


@dataclass
class RunTimings:
    run_id: int
    provider: str
    mode: str
    started_ns: int = field(default_factory=time.perf_counter_ns)
    marks: dict[str, int] = field(default_factory=dict)
    outcome: str = "error"
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def mark(self, name: str, at_ns: int | None = None) -> None:
        if name not in MARKS:
            raise ValueError("Unknown timing mark")
        with self._lock:
            self.marks.setdefault(
                name, int(at_ns) if at_ns is not None else time.perf_counter_ns()
            )

    def finish(self, outcome: str) -> None:
        with self._lock:
            if "completed" in self.marks:
                return
            self.outcome = _public_label(outcome, _ALLOWED_OUTCOMES)
            self.marks["completed"] = time.perf_counter_ns()

    def to_record(self) -> dict:
        with self._lock:
            marks = dict(self.marks)
            outcome = self.outcome
        durations = {}
        for key, (start, end) in PHASE_PAIRS.items():
            left, right = marks.get(start), marks.get(end)
            durations[key] = (
                round(max(0, right - left) / 1_000_000, 3)
                if left is not None and right is not None and right >= left
                else None
            )
        stopped = marks.get("record_stop")
        seconds = (
            (stopped - self.started_ns) / 1_000_000_000
            if stopped is not None and stopped >= self.started_ns
            else None
        )
        bucket = (
            "unknown" if seconds is None else
            "short" if seconds < 8 else
            "medium" if seconds < 30 else "long"
        )
        return {
            "schema_version": 1,
            "run_id": self.run_id,
            "provider": _public_label(self.provider, _ALLOWED_PROVIDERS),
            "mode": _public_label(self.mode, _ALLOWED_MODES),
            "duration_bucket": bucket,
            "outcome": outcome,
            "duration_ms": durations,
        }


class LatencyCollector:
    """Bounded in-memory records; no disk I/O except explicit export()."""

    def __init__(self, capacity: int = 10_000) -> None:
        self._records: deque[dict] = deque(maxlen=capacity)
        self._seen: set[int] = set()
        self._lock = threading.Lock()

    def add(self, run: RunTimings) -> None:
        record = run.to_record()
        with self._lock:
            if run.run_id in self._seen:
                return
            if len(self._records) == self._records.maxlen:
                self._seen.discard(self._records[0]["run_id"])
            self._records.append(record)
            self._seen.add(run.run_id)

    def records(self) -> list[dict]:
        with self._lock:
            return list(self._records)

    def summary(self) -> dict:
        rows = self.records()
        return {
            "schema_version": 1,
            "count": len(rows),
            "metrics": {
                phase: {
                    "n": len(values),
                    "p50_ms": round(statistics.median(values), 3) if values else None,
                    "p95_ms": percentile(values, 95),
                }
                for phase in PHASE_PAIRS
                for values in [[
                    row["duration_ms"][phase]
                    for row in rows
                    if row["duration_ms"][phase] is not None
                ]]
            },
        }

    def export_jsonl(self, path: str | Path) -> int:
        """User-requested local-only export; never called by default."""
        dest = Path(path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        rows = self.records()
        with dest.open("w", encoding="utf-8", newline="\n") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        return len(rows)
