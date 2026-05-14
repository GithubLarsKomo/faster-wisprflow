import threading

import numpy as np
import sounddevice as sd
import soundfile as sf

from config import BASE_DIR, Config


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

        audio_path = BASE_DIR / self.config.audio_filename

        with self.lock:
            if not self.frames:
                raise RuntimeError("Keine Audiodaten aufgenommen")
            audio = np.concatenate(self.frames, axis=0)

        sf.write(str(audio_path), audio, self.config.sample_rate)
        return audio_path
