"""Tests for recorder.py — Recorder callback and stop behaviour."""

import sys
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

# sounddevice and soundfile are optional hardware dependencies — stub before import
sys.modules.setdefault("sounddevice", MagicMock())
sys.modules.setdefault("soundfile", MagicMock())

from recorder import Recorder
from tests.conftest import make_stub_config

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_recorder(**kw):
    cfg = make_stub_config(**kw)
    return Recorder(cfg)


def _fake_indata(value=0.5, shape=(1024, 1)):
    return np.full(shape, value, dtype="float32")


# ---------------------------------------------------------------------------
# _callback
# ---------------------------------------------------------------------------


class TestCallback:
    def test_appends_frame_when_recording(self):
        rec = make_recorder()
        rec.recording = True
        indata = _fake_indata(0.3)

        rec._callback(indata, 1024, None, None)

        assert len(rec.frames) == 1
        np.testing.assert_array_equal(rec.frames[0], indata)

    def test_updates_last_rms(self):
        rec = make_recorder()
        rec.recording = True
        indata = np.ones((1024, 1), dtype="float32")

        rec._callback(indata, 1024, None, None)

        assert rec.last_rms == pytest.approx(1.0)

    def test_skips_when_not_recording(self):
        rec = make_recorder()
        rec.recording = False
        indata = _fake_indata()

        rec._callback(indata, 1024, None, None)

        assert rec.frames == []

    def test_thread_safe_append(self):
        """Multiple threads calling _callback simultaneously must not corrupt frames."""
        rec = make_recorder()
        rec.recording = True

        def worker():
            for _ in range(50):
                rec._callback(_fake_indata(), 1024, None, None)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(rec.frames) == 200


# ---------------------------------------------------------------------------
# stop — raises when no frames
# ---------------------------------------------------------------------------


class TestStop:
    def test_raises_when_no_audio(self, tmp_path):
        rec = make_recorder(audio_filename="rec.wav")
        rec.recording = False
        rec.frames = []

        with patch("recorder.BASE_DIR", tmp_path):
            with pytest.raises(RuntimeError, match="no_audio"):
                rec.stop()

    def test_writes_wav_and_returns_path(self, tmp_path):
        rec = make_recorder(sample_rate=16000, audio_filename="out.wav")
        rec.recording = False
        # Add some fake audio frames
        rec.frames = [np.zeros((512, 1), dtype="float32")]

        import soundfile as sf_mock

        with patch("recorder.BASE_DIR", tmp_path):
            path = rec.stop()

        # soundfile is stubbed — verify sf.write was called with the right path
        sf_mock.write.assert_called_once()
        call_args = sf_mock.write.call_args[0]
        assert call_args[0] == str(tmp_path / "out.wav")
        assert path == tmp_path / "out.wav"
