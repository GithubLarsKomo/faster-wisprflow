import ctypes
import queue
import sys
import threading
import time

import keyboard
import mouse
from PySide6.QtCore import QTimer, QtMsgType, qInstallMessageHandler
from PySide6.QtWidgets import QApplication, QMessageBox

# ── SSL must be patched before any HTTP import is used ────────────────────────
import ssl_setup  # noqa: E402  (intentionally first)
from config import Config, auto_elevate_if_needed, load_config, save_config
from llm_corrector import LLMCorrector
from recorder import Recorder
from text_inserter import TextInserter
from tray import Tray
from ui.dock import DockWindow
from ui.settings_dialog import SettingsWindow
from ui.translations import t
from vocabulary import VocabularyManager
from whisper_client import WhisperClient


class App:
    def __init__(self):
        raw_cfg = load_config()
        auto_elevate_if_needed(raw_cfg)

        self.config = Config()
        self.dock = DockWindow(
            self.config.raw,
            on_open_settings=self.open_settings,
            on_quit=self.quit,
            on_config_saved=self.reload_config,
            on_llm_toggled=self.toggle_llm,
        )
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

        # Initialise dock badges from config
        self.dock.set_llm_enabled(self.config.correction_enabled)
        self.dock.set_max_seconds(self.config.max_recording)
        self.dock.set_provider(self.config.whisper_provider)
        self.dock.set_target_language(self.config.language)
        self.dock.set_ui_language(self.config.ui_language)

    def toggle_llm(self, enabled: bool) -> None:
        self.config.correction_enabled = enabled
        self.config.raw["correction_enabled"] = enabled
        save_config(self.config.raw)
        self.llm = LLMCorrector(self.config)

    def reload_config(self):
        self.config.reload()
        self.recorder = Recorder(self.config)
        self.client = WhisperClient(self.config)
        self.inserter = TextInserter(self.config)
        self.llm = LLMCorrector(self.config)

        def _update_dock() -> None:
            self.dock.set_llm_enabled(self.config.correction_enabled)
            self.dock.set_max_seconds(self.config.max_recording)
            self.dock.set_provider(self.config.whisper_provider)
            self.dock.set_target_language(self.config.language)
            self.dock.set_ui_language(self.config.ui_language)
            self.settings.sync_from_config()

        QTimer.singleShot(0, _update_dock)

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
            pressed = self.hotkey_pressed() or mouse.is_pressed(button="middle")

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

    def start_recording(self):
        if self.is_recording or self.is_busy:
            return

        try:
            self.is_recording = True
            self.recorder.start()

            def _start_popup():
                if not self.is_recording:
                    return
                self.dock.set_recording(on_timeout=self.stop_recording)

                def _poll_rms():
                    if self.is_recording:
                        self.dock.set_rms(self.recorder.last_rms)
                        QTimer.singleShot(50, _poll_rms)

                QTimer.singleShot(50, _poll_rms)

            QTimer.singleShot(100, _start_popup)
        except Exception:
            self.is_recording = False
            try:
                self.recorder.recording = False
            except Exception:
                pass
            QTimer.singleShot(0, self.dock.set_idle)

    def stop_recording(self):
        if not self.is_recording:
            return

        self.is_recording = False
        self.is_busy = True

        self.dock.set_rms(0.0)
        self.dock.set_processing()

        threading.Thread(target=self.transcribe_and_insert, daemon=True).start()

    def transcribe_and_insert(self):
        audio_path = None
        try:
            audio_path = self.recorder.stop()
            text = self.client.transcribe(audio_path)

            if text:
                text = self.vocab.apply(text)
                text = self.llm.correct(text)
                self.inserter.insert_text(text)
                QTimer.singleShot(0, self.dock.set_done)
            else:
                lang = self.config.ui_language
                self.dock.show_info_signal.emit(
                    t("msg_result_title", lang),
                    t("msg_no_speech", lang),
                )
                QTimer.singleShot(0, self.dock.set_idle)

        except Exception as e:
            if str(e) == "no_audio":
                QTimer.singleShot(0, self.dock.set_idle)
            else:
                lang = self.config.ui_language
                err_msg = f'{t("msg_error", lang)}: {e}'
                self.dock.show_error_signal.emit(err_msg)

        finally:
            if audio_path and audio_path.exists():
                try:
                    audio_path.unlink()
                except Exception:
                    pass
            self.is_busy = False

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
        QApplication.instance().quit()

    def run(self):
        threading.Thread(target=self.monitor_hotkey, daemon=True).start()
        threading.Thread(target=self.tray.run, daemon=True).start()

        # poll event queue every 50 ms on the Qt main thread
        self._event_timer = QTimer()
        self._event_timer.setInterval(50)
        self._event_timer.timeout.connect(self.process_events)
        self._event_timer.start()

        QApplication.instance().exec()


if __name__ == "__main__":
    # ── SSL bootstrap (before any HTTP traffic) ───────────────────────────
    ssl_setup.init()

    # ── CLI: --ssl-diagnose ───────────────────────────────────────────────
    if "--ssl-diagnose" in sys.argv:
        import json
        import logging

        logging.basicConfig(
            level=logging.DEBUG, format="%(levelname)-8s %(name)s: %(message)s"
        )
        result = ssl_setup.diagnose()
        print(json.dumps(result, indent=2, default=str))
        sys.exit(0)

    _qapp = QApplication(sys.argv)
    _qapp.setQuitOnLastWindowClosed(False)

    # Suppress benign Qt6 warning triggered when a widget's stylesheet uses
    # "font-size: Npx" and Qt's internal style engine reads pointSize() = -1.
    def _qt_msg_handler(msg_type, _ctx, msg: str) -> None:
        if msg_type == QtMsgType.QtWarningMsg and "setPointSize" in msg:
            return
        # Preserve default behavior for everything else
        if msg_type in (QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
            print(msg, file=sys.stderr)

    qInstallMessageHandler(_qt_msg_handler)

    _mutex = ctypes.windll.kernel32.CreateMutexW(
        None, True, "FlüsterFee_SingleInstance"
    )
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        QMessageBox.warning(None, "FlüsterFee", "FlüsterFee läuft bereits.")
        sys.exit(0)

    print("Starte FlüsterFee…")
    App().run()
