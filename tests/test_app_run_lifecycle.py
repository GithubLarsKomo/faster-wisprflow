"""Regression tests for App run identity and stale-worker cancellation."""

from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import MagicMock

from app import App
from tests.conftest import make_stub_config


class _FakeRecorder:
    def __init__(self, tmp_path: Path):
        self._tmp_path = tmp_path
        self._counter = 0
        self._lock = threading.Lock()
        self.stream = None
        self.recording = False

    def stop(self) -> Path:
        with self._lock:
            idx = self._counter
            self._counter += 1
        path = self._tmp_path / f"run-{idx}.wav"
        path.write_bytes(b"fake")
        return path


class _SequencedTranscriber:
    """Two-call transcriber whose calls can be released independently."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.entered = [threading.Event() for _ in self.outcomes]
        self.release = [threading.Event() for _ in self.outcomes]
        self._counter = 0
        self._lock = threading.Lock()

    def transcribe(self, _audio_path: Path) -> str:
        with self._lock:
            idx = self._counter
            self._counter += 1
        self.entered[idx].set()
        assert self.release[idx].wait(2), f"transcriber call {idx} was not released"
        outcome = self.outcomes[idx]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class _ImmediateTranscriber:
    def __init__(self, results):
        self.results = list(results)
        self._counter = 0
        self._lock = threading.Lock()

    def transcribe(self, _audio_path: Path) -> str:
        with self._lock:
            idx = self._counter
            self._counter += 1
        return self.results[idx]


class _SequencedCorrector:
    def __init__(self, results):
        self.results = list(results)
        self.entered = [threading.Event() for _ in self.results]
        self.release = [threading.Event() for _ in self.results]
        self._counter = 0
        self._lock = threading.Lock()

    def correct(self, _text: str) -> str:
        with self._lock:
            idx = self._counter
            self._counter += 1
        self.entered[idx].set()
        assert self.release[idx].wait(2), f"corrector call {idx} was not released"
        return self.results[idx]


def _make_app(tmp_path: Path, *, correction_enabled: bool = False) -> App:
    """Build App without constructing Qt windows, audio devices or tray state."""
    app = App.__new__(App)
    app.config = make_stub_config(
        correction_enabled=correction_enabled,
        ui_language="de",
    )
    app.recorder = _FakeRecorder(tmp_path)
    app.client = MagicMock()
    app.vocab = MagicMock()
    app.vocab.apply.side_effect = lambda text: text
    app.llm = MagicMock()
    app.inserter = MagicMock()
    app.dock = MagicMock()
    app.is_recording = False
    app.is_busy = False
    app._run_lock = threading.Lock()
    app._run_counter = 0
    app._active_run = None
    return app


def _start_worker(app: App, run) -> threading.Thread:
    thread = threading.Thread(
        target=app._safe_transcribe_and_insert,
        args=(run,),
        daemon=True,
    )
    thread.start()
    return thread


def test_stale_whisper_response_cannot_clear_or_paste_into_new_run(tmp_path):
    app = _make_app(tmp_path, correction_enabled=False)
    client = _SequencedTranscriber(["old transcript", "new transcript"])
    app.client = client

    run_a = app._begin_run()
    app.is_busy = True
    thread_a = _start_worker(app, run_a)
    assert client.entered[0].wait(1)

    app.cancel_current_run()
    assert run_a.cancel_event.is_set()

    run_b = app._begin_run()
    app.is_busy = True
    thread_b = _start_worker(app, run_b)
    assert client.entered[1].wait(1)

    # Let stale A return while B is still processing.
    client.release[0].set()
    thread_a.join(1)
    assert not thread_a.is_alive()

    assert app._get_active_run() is run_b
    assert app.is_busy is True
    app.inserter.insert_text.assert_not_called()

    client.release[1].set()
    thread_b.join(1)
    assert not thread_b.is_alive()

    app.inserter.insert_text.assert_called_once_with("new transcript")
    assert app._get_active_run() is None
    assert app.is_busy is False


def test_stale_llm_response_cannot_clear_or_paste_into_new_run(tmp_path):
    app = _make_app(tmp_path, correction_enabled=True)
    app.client = _ImmediateTranscriber(["old raw", "new raw"])
    corrector = _SequencedCorrector(["old corrected", "new corrected"])
    app.llm = corrector

    run_a = app._begin_run()
    app.is_busy = True
    thread_a = _start_worker(app, run_a)
    assert corrector.entered[0].wait(1)

    app.cancel_current_run()
    run_b = app._begin_run()
    app.is_busy = True
    thread_b = _start_worker(app, run_b)
    assert corrector.entered[1].wait(1)

    corrector.release[0].set()
    thread_a.join(1)
    assert not thread_a.is_alive()

    assert app._get_active_run() is run_b
    assert app.is_busy is True
    app.inserter.insert_text.assert_not_called()

    corrector.release[1].set()
    thread_b.join(1)
    assert not thread_b.is_alive()

    app.inserter.insert_text.assert_called_once_with("new corrected")
    assert app._get_active_run() is None
    assert app.is_busy is False


def test_stale_transcription_error_is_silent_after_new_run_starts(tmp_path):
    app = _make_app(tmp_path, correction_enabled=False)
    client = _SequencedTranscriber([RuntimeError("stale failure"), "new transcript"])
    app.client = client

    run_a = app._begin_run()
    app.is_busy = True
    thread_a = _start_worker(app, run_a)
    assert client.entered[0].wait(1)

    app.cancel_current_run()
    run_b = app._begin_run()
    app.is_busy = True
    thread_b = _start_worker(app, run_b)
    assert client.entered[1].wait(1)

    client.release[0].set()
    thread_a.join(1)

    # The error belongs to stale A and must not overwrite B's UI.
    app.dock.show_error_signal.emit.assert_not_called()
    assert app._get_active_run() is run_b
    assert app.is_busy is True

    client.release[1].set()
    thread_b.join(1)

    app.inserter.insert_text.assert_called_once_with("new transcript")
    app.dock.show_error_signal.emit.assert_not_called()


def test_cancel_during_recording_invalidates_run_and_closes_stream(tmp_path):
    app = _make_app(tmp_path, correction_enabled=False)
    run = app._begin_run()
    app.is_recording = True
    app.is_busy = False

    stream = MagicMock()
    app.recorder.stream = stream
    app.recorder.recording = True

    app.cancel_current_run()

    assert run.cancel_event.is_set()
    assert app._get_active_run() is None
    assert app.is_busy is False
    assert app.is_recording is False
    assert app.recorder.recording is False
    assert app.recorder.stream is None
    stream.stop.assert_called_once_with()
    stream.close.assert_called_once_with()
    app.dock.set_idle.assert_called_once_with()


def test_begin_run_invalidates_previous_identity(tmp_path):
    app = _make_app(tmp_path)

    first = app._begin_run()
    second = app._begin_run()

    assert first.id == 1
    assert second.id == 2
    assert first.cancel_event.is_set()
    assert not app._is_current_run(first)
    assert app._is_current_run(second)
