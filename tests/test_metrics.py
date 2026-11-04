"""Deterministic latency metrics, schema, opt-in export, no payload storage."""

import json

from benchmarks.dictation_latency.report import summarize
from metrics import LatencyCollector, RunTimings, percentile


def test_missing_optional_stage_is_null_not_zero():
    run = RunTimings(1, "local", "smart", started_ns=0)
    run.mark("record_stop", at_ns=2_000_000_000)
    run.mark("audio_ready", at_ns=2_050_000_000)
    run.mark("asr_start", at_ns=2_060_000_000)
    run.mark("asr_final", at_ns=2_160_000_000)
    run.mark("gate_start", at_ns=2_165_000_000)
    run.mark("gate_end", at_ns=2_166_000_000)
    run.mark("insert_start", at_ns=2_170_000_000)
    run.mark("insert_dispatch", at_ns=2_200_000_000)
    run.mark("insert_end", at_ns=2_201_000_000)
    run.finish("dispatched")
    row = run.to_record()
    assert row["duration_bucket"] == "short"
    assert row["duration_ms"]["audio_prepare_ms"] == 50.0
    assert row["duration_ms"]["asr_ms"] == 100.0
    assert row["duration_ms"]["gate_ms"] == 1.0
    assert row["duration_ms"]["llm_ms"] is None
    assert row["duration_ms"]["record_stop_to_asr_final_ms"] == 160.0
    assert row["duration_ms"]["asr_final_to_insert_ms"] == 40.0
    assert row["duration_ms"]["release_to_insert_ms"] == 200.0


def test_invalid_or_backward_marks_have_no_negative_durations():
    run = RunTimings(2, "local", "fast")
    run.mark("record_stop", at_ns=500)
    run.mark("asr_final", at_ns=100)
    assert run.to_record()["duration_ms"]["record_stop_to_asr_final_ms"] is None
    try:
        run.mark("unexpected")
    except ValueError:
        pass
    else:
        raise AssertionError("unexpected mark should raise")


def test_finish_is_idempotent_after_cancellation():
    run = RunTimings(3, "other", "unknown")
    run.finish("cancelled")
    run.finish("dispatched")
    assert run.to_record()["outcome"] == "cancelled"
    assert run.to_record()["provider"] == "other"
    assert run.to_record()["mode"] == "other"


def test_collector_deduplicates_and_export_is_opt_in(tmp_path):
    path = tmp_path / "runs.jsonl"
    collector = LatencyCollector(capacity=10)
    assert not path.exists()
    run = RunTimings(7, "local", "polish", started_ns=0)
    run.mark("record_stop", at_ns=1_000_000_000)
    run.mark("asr_final", at_ns=1_040_000_000)
    run.mark("insert_dispatch", at_ns=1_090_000_000)
    run.finish("dispatched")
    collector.add(run)
    collector.add(run)
    assert len(collector.records()) == 1
    assert collector.export_jsonl(path) == 1
    row = json.loads(path.read_text(encoding="utf-8"))
    assert set(row) == {
        "schema_version", "run_id", "provider", "mode",
        "duration_bucket", "outcome", "duration_ms",
    }
    assert "transcript" not in path.read_text(encoding="utf-8")
    assert collector.summary()["metrics"]["release_to_insert_ms"]["p50_ms"] == 90


def test_percentile_and_grouped_report_with_small_samples():
    assert percentile([], 95) is None
    assert percentile([10.0, 30.0, 20.0], 95) == 30.0
    rows = []
    for i, ms in enumerate([100, 300, 200]):
        run = RunTimings(i, "groq", "fast", started_ns=0)
        run.mark("record_stop", at_ns=1_000_000_000)
        run.mark("insert_dispatch", at_ns=1_000_000_000 + ms * 1_000_000)
        run.finish("dispatched")
        rows.append(run.to_record())
    report = summarize(rows)
    assert not report["baseline_ready"]
    group = report["groups"][0]
    assert group["runs"] == 3
    assert group["phases"]["release_to_insert_ms"]["p50_ms"] == 200.0
    assert group["phases"]["release_to_insert_ms"]["p95_ms"] == 300.0
