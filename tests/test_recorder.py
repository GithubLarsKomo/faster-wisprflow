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

        with patch("recorder.tempfile.gettempdir", return_value=str(tmp_path)):
            with pytest.raises(RuntimeError, match="no_audio"):
                rec.stop()

    def test_writes_wav_and_returns_unique_temp_path(self, tmp_path):
        rec = make_recorder(sample_rate=16000, audio_filename="out.wav")
        rec.recording = False
        rec.frames = [np.zeros((512, 1), dtype="float32")]

        with (
            patch("recorder.tempfile.gettempdir", return_value=str(tmp_path)),
            patch("recorder.sf.write") as mock_write,
        ):
            path = rec.stop()

        mock_write.assert_called_once()
        call_args = mock_write.call_args[0]
        assert call_args[0] == str(path)
        assert path.parent == tmp_path
        assert path.name.startswith("fluesterfee-")
        assert path.suffix == ".wav"

    def test_two_stops_use_distinct_paths(self, tmp_path):
        rec = make_recorder(sample_rate=16000, audio_filename="recording.wav")
        rec.recording = False
        rec.frames = [np.zeros((128, 1), dtype="float32")]

        with (
            patch("recorder.tempfile.gettempdir", return_value=str(tmp_path)),
            patch("recorder.sf.write"),
        ):
            first = rec.stop()
            second = rec.stop()

        assert first != second
        assert first.parent == second.parent == tmp_path

    def test_write_failure_removes_owned_temp_file(self, tmp_path):
        rec = make_recorder(sample_rate=16000, audio_filename="recording.wav")
        rec.recording = False
        rec.frames = [np.zeros((128, 1), dtype="float32")]
        created = []

        real_mkstemp = __import__("tempfile").mkstemp

        def tracking_mkstemp(*args, **kwargs):
            fd, name = real_mkstemp(*args, **kwargs)
            created.append(Path(name))
            return fd, name

        with (
            patch("recorder.tempfile.gettempdir", return_value=str(tmp_path)),
            patch("recorder.tempfile.mkstemp", side_effect=tracking_mkstemp),
            patch("recorder.sf.write", side_effect=OSError("disk full")),
        ):
            with pytest.raises(OSError, match="disk full"):
                rec.stop()

        assert len(created) == 1
        assert not created[0].exists()
