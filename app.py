import json
import queue
import threading
import time
import tkinter as tk
from pathlib import Path

import keyboard
import numpy as np
import pyperclip
import requests
import sounddevice as sd
import soundfile as sf

BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.json"


class Config:
    def __init__(self):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.whisper_url = data.get("whisper_url", "http://localhost:8008/transcribe")
        self.language = data.get("language", "de")
        self.response_format = data.get("response_format", "text")
        self.sample_rate = int(data.get("sample_rate", 16000))
        self.channels = int(data.get("channels", 1))
        self.input_device = data.get("input_device", None)
        self.hotkey_keys = data.get("hotkey_keys", ["ctrl", "windows"])
        self.restore_clipboard = bool(data.get("restore_clipboard", True))
        self.audio_filename = data.get("audio_filename", "recording.wav")


class Overlay:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Whisper Dictate")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.92)

        self.label = tk.Label(
            self.root,
            text="Bereit",
            font=("Segoe UI", 18),
            bg="#222222",
            fg="white",
            padx=24,
            pady=14,
        )
        self.label.pack()

        self.root.withdraw()

    def show(self, text: str):
        self.label.config(text=text)

        self.root.update_idletasks()
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        screen_w = self.root.winfo_screenwidth()

        x = screen_w - width - 40
        y = 40

        self.root.geometry(f"+{x}+{y}")
        self.root.deiconify()
        self.root.update()

    def hide(self):
        self.root.withdraw()
        self.root.update()

    def set_text(self, text: str):
        self.label.config(text=text)
        self.root.update()

    def loop(self):
        self.root.mainloop()


class Recorder:
    def __init__(self, config: Config):
        self.config = config
        self.frames = []
        self.stream = None
        self.recording = False
        self.lock = threading.Lock()

    def _callback(self, indata, frames, time_info, status):
        if status:
            print(status)
        with self.lock:
            if self.recording:
                self.frames.append(indata.copy())

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

    def stop(self) -> Path:
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


class WhisperClient:
    def __init__(self, config: Config):
        self.config = config

    def transcribe(self, audio_path: Path) -> str:
        with open(audio_path, "rb") as f:
            files = {"file": (audio_path.name, f, "audio/wav")}
            data = {
                "language": self.config.language,
                "response_format": self.config.response_format,
            }

            response = requests.post(
                self.config.whisper_url,
                files=files,
                data=data,
                timeout=600,
            )

        response.raise_for_status()

        if self.config.response_format == "text":
            return response.text.strip()

        payload = response.json()
        return payload.get("text", "").strip()


class TextInserter:
    def __init__(self, config: Config):
        self.config = config

    def insert_text(self, text: str):
        if not text:
            return

        old_clipboard = None

        if self.config.restore_clipboard:
            try:
                old_clipboard = pyperclip.paste()
            except Exception:
                old_clipboard = None

        pyperclip.copy(text)
        time.sleep(0.08)
        keyboard.press_and_release("ctrl+v")
        time.sleep(0.15)

        if self.config.restore_clipboard and old_clipboard is not None:
            pyperclip.copy(old_clipboard)


class App:
    def __init__(self):
        self.config = Config()
        self.overlay = Overlay()
        self.recorder = Recorder(self.config)
        self.client = WhisperClient(self.config)
        self.inserter = TextInserter(self.config)

        self.is_recording = False
        self.is_busy = False
        self.event_queue = queue.Queue()

    def hotkey_pressed(self) -> bool:
        return all(keyboard.is_pressed(k) for k in self.config.hotkey_keys)

    def monitor_hotkey(self):
        was_pressed = False

        while True:
            pressed = self.hotkey_pressed()

            if pressed and not was_pressed:
                self.event_queue.put("start")

            if not pressed and was_pressed:
                self.event_queue.put("stop")

            was_pressed = pressed
            time.sleep(0.03)

    def process_events(self):
        try:
            while True:
                event = self.event_queue.get_nowait()

                if event == "start":
                    self.start_recording()

                elif event == "stop":
                    self.stop_recording()

        except queue.Empty:
            pass

        self.overlay.root.after(50, self.process_events)

    def start_recording(self):
        if self.is_recording or self.is_busy:
            return

        try:
            self.is_recording = True
            self.recorder.start()
            self.overlay.show("🎙 Aufnahme läuft…")
        except Exception as e:
            self.is_recording = False
            self.overlay.show(f"Fehler: {e}")
            self.overlay.root.after(2500, self.overlay.hide)

    def stop_recording(self):
        if not self.is_recording:
            return

        self.is_recording = False
        self.is_busy = True
        self.overlay.set_text("⏳ Transkribiere…")

        threading.Thread(target=self.transcribe_and_insert, daemon=True).start()

    def transcribe_and_insert(self):
        try:
            audio_path = self.recorder.stop()
            text = self.client.transcribe(audio_path)

            if text:
                self.overlay.set_text("✅ Füge Text ein…")
                time.sleep(0.1)
                self.inserter.insert_text(text)
                self.overlay.set_text("✅ Fertig")
            else:
                self.overlay.set_text("⚠ Kein Text erkannt")

        except Exception as e:
            self.overlay.set_text(f"Fehler: {e}")

        finally:
            self.is_busy = False
            self.overlay.root.after(1500, self.overlay.hide)

    def run(self):
        threading.Thread(target=self.monitor_hotkey, daemon=True).start()
        self.overlay.root.after(50, self.process_events)
        self.overlay.loop()


if __name__ == "__main__":
    print("WhisperDictate gestartet. Hotkey aktiv.")
    App().run()
