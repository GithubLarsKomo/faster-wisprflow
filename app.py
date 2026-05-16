import ctypes
import queue
import sys
import threading
from tkinter import messagebox

from config import Config, load_config
from correction_tracker import CorrectionTracker
from hotkey import HotkeyManager
from llm_corrector import LLMCorrector
from recorder import Recorder
from text_inserter import TextInserter
from tray import Tray
from ui.overlay import Overlay
from ui.popups import _MicLevelPopup
from ui.settings_window import SettingsWindow
from vocabulary import VocabularyManager
from whisper_client import WhisperClient


class App:
    def __init__(self):
        self.config = Config()
        self.overlay = Overlay()
        self.recorder = Recorder(self.config)
        self.client = WhisperClient(self.config)
        self.inserter = TextInserter(self.config)
        self.vocab = VocabularyManager()
        self.llm = LLMCorrector(self.config)
        self.settings = SettingsWindow(self)
        self.tray = Tray(self)
        self._hotkey = HotkeyManager(self.overlay.root)

        self.is_recording = False
        self.is_busy = False
        self.event_queue = queue.Queue()
        self.running = True
        self._rec_popup: _MicLevelPopup | None = None
        self._correction_tracker: CorrectionTracker | None = None

    def reload_config(self):
        self.config.reload()
        self.recorder = Recorder(self.config)
        self.client = WhisperClient(self.config)
        self.inserter = TextInserter(self.config)
        self.llm = LLMCorrector(self.config)
        self.overlay.update_language(self.config.language)
        # Re-register hotkey with potentially new key combo
        self._register_hotkey()

    def _register_hotkey(self) -> None:
        try:
            self._hotkey.register(
                self.config.hotkey_keys,
                on_press=lambda: self.event_queue.put("start"),
                on_release=lambda: self.event_queue.put("stop"),
            )
        except OSError as e:
            from tkinter import messagebox as _mb

            _mb.showwarning(
                "Hotkey",
                f"Hotkey konnte nicht registriert werden:\n{e}",
                parent=self.overlay.root,
            )

    def hotkey_pressed(self):
        # Kept for backwards-compat; always False now (RegisterHotKey handles it).
        return False

    def process_events(self):
        try:
            while True:
                event = self.event_queue.get_nowait()
                if event == "start":
                    self.start_recording()
                elif event == "stop":
                    self.stop_recording()
                elif event == "settings":
                    self.settings.open()
                elif event == "quit":
                    self._quit_mainthread()
        except queue.Empty:
            pass

        if self.running:
            self.overlay.root.after(50, self.process_events)

    def start_recording(self):
        if self.is_recording or self.is_busy:
            return

        if self._correction_tracker:
            self._correction_tracker.stop()
            self._correction_tracker = None

        try:
            self.is_recording = True
            self.recorder.start()
            self._rec_popup = _MicLevelPopup(
                self.overlay.root, llm_enabled=self.config.correction_enabled
            )

            def _poll_rms():
                if self.is_recording and self._rec_popup:
                    self._rec_popup.set_rms(self.recorder.last_rms)
                    self.overlay.root.after(50, _poll_rms)

            self.overlay.root.after(50, _poll_rms)
        except Exception as e:
            self.is_recording = False
            self._rec_popup = None
            self.overlay.show(f"Fehler: {e}")
            self.overlay.root.after(2500, self.overlay.hide)

    def stop_recording(self):
        if not self.is_recording:
            return

        self.is_recording = False
        self.is_busy = True

        if self._rec_popup:
            self._rec_popup.set_rms(0.0)
            self._rec_popup.expand_for_dots()
            dot_count = [1]

            def _animate_dots():
                if (
                    self.is_busy
                    and self._rec_popup
                    and self._rec_popup.top.winfo_exists()
                ):
                    dot_count[0] = dot_count[0] % 3 + 1
                    self._rec_popup.show_dots(dot_count[0])
                    self.overlay.root.after(400, _animate_dots)

            self.overlay.root.after(400, _animate_dots)

        threading.Thread(target=self.transcribe_and_insert, daemon=True).start()

    def transcribe_and_insert(self):
        audio_path = None
        try:
            audio_path = self.recorder.stop()
            text = self.client.transcribe(audio_path)

            if self._rec_popup:
                self.overlay.root.after(0, self._rec_popup.close)
                self._rec_popup = None

            if text:
                text = self.vocab.apply(text)
                text = self.llm.correct(text)
                self.inserter.insert_text(text)
                self._correction_tracker = CorrectionTracker(self.vocab)
                self._correction_tracker.start(
                    text,
                    self.overlay.root.after,
                    self._on_correction_saved,
                )
            else:
                messagebox.showinfo(
                    "Ergebnis", "Keine Sprache erkannt.", parent=self.overlay.root
                )

        except Exception as e:
            if self._rec_popup:
                self.overlay.root.after(0, self._rec_popup.close)
                self._rec_popup = None
            self.overlay.show(f"Fehler: {e}")

        finally:
            if audio_path and audio_path.exists():
                try:
                    audio_path.unlink()
                except Exception:
                    pass
            self.is_busy = False
            self.overlay.root.after(1500, self.overlay.hide)

    def _on_correction_saved(self, msg: str) -> None:
        self.overlay.show(msg)
        self.overlay.root.after(2000, self.overlay.hide)

    def open_settings(self):
        self.event_queue.put("settings")

    def quit(self):
        self.event_queue.put("quit")

    def _quit_mainthread(self):
        self.running = False
        self._hotkey.unregister()
        try:
            self.tray.stop()
        except Exception:
            pass
        self.overlay.root.quit()
        self.overlay.root.destroy()

    def run(self):
        self._register_hotkey()
        threading.Thread(target=self.tray.run, daemon=True).start()
        self.overlay.root.after(50, self.process_events)
        self.overlay.loop()


if __name__ == "__main__":
    _mutex = ctypes.windll.kernel32.CreateMutexW(
        None, True, "FlüsterFee_SingleInstance"
    )
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        import tkinter as _tk
        import tkinter.messagebox as _mb

        _r = _tk.Tk()
        _r.withdraw()
        _mb.showwarning("FlüsterFee", "FlüsterFee läuft bereits.")
        _r.destroy()
        sys.exit(0)
    print("Starte FlüsterFee…")
    App().run()
