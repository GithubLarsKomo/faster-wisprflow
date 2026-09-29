import os
import tempfile
import threading
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf

from config import Config


class Recorder:
    def __init__(self, config: Config):
        self.config = config
        self.frames = []
        self.stream = None
        self.recording = False
        self.lock = threading.Lock()
        self.last_rms: float = 0.0

    def _callback(self, indata, frames, time_info, status):
        try:
            with self.lock:
                if self.recording:
                    self.frames.append(indata.copy())
                    self.last_rms = float(np.sqrt(np.mean(indata**2)))
        except BaseException:
            pass

    def start(self):
        with self.lock:
            self.frames = []
            self.recording = True

        self.stream = sd.InputStream(
            device=self.config.input_device,
            samplerate=self.config.sample_rate,
            channels=self.config.channels,
            dtype="float32",
            callback=self._callback,
        )
        self.stream.start()

    def stop(self):
        with self.lock:
            self.recording = False

        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None

        with self.lock:
            if not self.frames:
                raise RuntimeError("no_audio")
            audio = np.concatenate(self.frames, axis=0)

        # Every dictation run owns a distinct temporary artifact. A cancelled
        # worker may outlive a newer run while blocked in HTTP I/O, so sharing
        # one fixed recording.wav path would allow stale cleanup or reads to
        # interfere with the newer run.
        configured_suffix = Path(self.config.audio_filename).suffix
        suffix = configured_suffix if configured_suffix else ".wav"
        fd, tmp_name = tempfile.mkstemp(
            prefix="fluesterfee-",
            suffix=suffix,
            dir=tempfile.gettempdir(),
        )
        os.close(fd)
        audio_path = Path(tmp_name)

        try:
            sf.write(str(audio_path), audio, self.config.sample_rate)
        except Exception:
            try:
                audio_path.unlink(missing_ok=True)
            except Exception:
                pass
            raise
        return audio_path
