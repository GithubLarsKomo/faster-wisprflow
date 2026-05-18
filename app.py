import ctypes
import queue
import sys
import threading
import time
from tkinter import messagebox

import keyboard

from config import Config, auto_elevate_if_needed, load_config
from llm_corrector import LLMCorrector
from recorder import Recorder
from text_inserter import TextInserter
from tray import Tray
from ui.overlay import Overlay
from ui.popups import _MicLevelPopup
from ui.settings_window import SettingsWindow
from ui.translations import t
from vocabulary import VocabularyManager
from whisper_client import WhisperClient


class App:
    def __init__(self):
        raw_cfg = load_config()
        auto_elevate_if_needed(raw_cfg)

        self.config = Config()
        self.overlay = Overlay()
        self.recorder = Recorder(self.config)
        self.client = WhisperClient(self.config)
        self.inserter = TextInserter(self.config)
        self.vocab = VocabularyManager()
        self.llm = LLMCorrector(self.config)
        self.settings = SettingsWindow(self)
        self.tray = Tray(self)

        self.is_recording = False
        self.is_busy = False
        self.event_queue = queue.Queue()
        self.running = True
        self._rec_popup: _MicLevelPopup | None = None

    def reload_config(self):
        self.config.reload()
        self.recorder = Recorder(self.config)
        self.client = WhisperClient(self.config)
        self.inserter = TextInserter(self.config)
        self.llm = LLMCorrector(self.config)
        self.overlay.update_language(self.config.language)

    def hotkey_pressed(self):
        _ALIASES = {"left windows": "linke windows", "linke windows": "left windows"}

        def is_key_pressed(k):
            try:
                if keyboard.is_pressed(k):
                    return True
            except Exception:
                pass
            try:
                if keyboard.is_pressed(_ALIASES.get(k.lower(), k)):
                    return True
            except Exception:
                pass
            return False

        try:
            return all(is_key_pressed(k) for k in self.config.hotkey_keys)
        except Exception:
            return False

    def monitor_hotkey(self):
        was_pressed = False
        while self.running:
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
            self.overlay.show(f'{t("msg_error", self.config.language)}: {e}')
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
            else:
                lang = self.config.language
                messagebox.showinfo(
                    t("msg_result_title", lang),
                    t("msg_no_speech", lang),
                    parent=self.overlay.root,
                )

        except Exception as e:
            if self._rec_popup:
                self.overlay.root.after(0, self._rec_popup.close)
                self._rec_popup = None
            lang = self.config.language
            err_msg = (
                t("msg_no_audio", lang)
                if str(e) == "no_audio"
                else f'{t("msg_error", lang)}: {e}'
            )
            self.overlay.show(err_msg)

        finally:
            if audio_path and audio_path.exists():
                try:
                    audio_path.unlink()
                except Exception:
                    pass
            self.is_busy = False
            self.overlay.root.after(1500, self.overlay.hide)

    def open_settings(self):
        self.event_queue.put("settings")

    def quit(self):
        self.event_queue.put("quit")

    def _quit_mainthread(self):
        self.running = False
        try:
            self.tray.stop()
        except Exception:
            pass
        self.overlay.root.quit()
        self.overlay.root.destroy()

    def run(self):
        threading.Thread(target=self.monitor_hotkey, daemon=True).start()
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
