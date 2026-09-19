import ctypes
import os
import queue
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

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


@dataclass
class RunContext:
    """Identity and cancellation state for one dictation run."""

    id: int
    cancel_event: threading.Event = field(default_factory=threading.Event)
    started_at: float = field(default_factory=time.monotonic)
    audio_path: Path | None = None


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
        self.dock.cancel_requested.connect(self.cancel_current_run)
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

        # A dictation run remains identifiable even while a cancelled worker is
        # still returning from a blocking HTTP request.  Shared flags are kept
        # for UI compatibility, but they are never the authority for deciding
        # whether a worker may produce side effects.
        self._run_lock = threading.Lock()
        self._run_counter = 0
        self._active_run: RunContext | None = None

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

    def _begin_run(self) -> RunContext:
        """Create and activate a new run, invalidating any stale predecessor."""
        with self._run_lock:
            if self._active_run is not None:
                self._active_run.cancel_event.set()
            self._run_counter += 1
            run = RunContext(id=self._run_counter)
            self._active_run = run
            return run

    def _get_active_run(self) -> RunContext | None:
        with self._run_lock:
            return self._active_run

    def _is_current_run(self, run: RunContext) -> bool:
        """Return True only while *run* owns the right to create side effects."""
        with self._run_lock:
            return self._active_run is run and not run.cancel_event.is_set()

    def _cancel_active_run(self) -> RunContext | None:
        """Invalidate the current run without waiting for blocked worker I/O."""
        with self._run_lock:
            run = self._active_run
            if run is not None:
                run.cancel_event.set()
                self._active_run = None
            self.is_busy = False
            return run

    def _finish_run_if_current(self, run: RunContext) -> bool:
        """Clear run/busy state only if *run* is still the active owner."""
        with self._run_lock:
            if self._active_run is not run:
                return False
            self._active_run = None
            self.is_busy = False
            return True

    def hotkey_pressed(self):
        """Check if the configured hotkey combination is pressed.

        Uses ``GetAsyncKeyState`` directly instead of the ``keyboard`` library
        because the library's low-level Windows hook (``SetWindowsHookEx``) is
        unreliable in some environments — the internal ``_pressed_events`` dict
        stays empty, so ``keyboard.is_pressed()`` always returns ``False``.
        ``GetAsyncKeyState`` queries the physical key state directly and is
        immune to hook-related issues.
        """
        _user32 = ctypes.windll.user32

        _KEY_NAME_TO_VK = {
            "ctrl": 0x11,  # VK_CONTROL
            "left ctrl": 0xA2,  # VK_LCONTROL
            "right ctrl": 0xA3,  # VK_RCONTROL
            "alt": 0x12,  # VK_MENU
            "shift": 0x10,  # VK_SHIFT
            "left shift": 0xA0,  # VK_LSHIFT
            "right shift": 0xA1,  # VK_RSHIFT
            "linke windows": 0x5B,  # VK_LWIN
            "left windows": 0x5B,  # VK_LWIN
            "rechte windows": 0x5C,  # VK_RWIN
            "right windows": 0x5C,  # VK_RWIN
            "windows": 0x5B,  # VK_LWIN (fallback)
        }

        def is_key_down(key_name: str) -> bool:
            vk = _KEY_NAME_TO_VK.get(key_name.lower())
            if vk is None:
                return False
            # 0x8000 = high-order bit (key is currently down)
            return bool(_user32.GetAsyncKeyState(vk) & 0x8000)

        try:
            return all(is_key_down(k) for k in self.config.hotkey_keys)
        except Exception:
            return False

    def monitor_hotkey(self):
        was_pressed = False
        while self.running:
            _user32 = ctypes.windll.user32
            middle_mouse_down = bool(_user32.GetAsyncKeyState(0x04) & 0x8000)
            pressed = self.hotkey_pressed() or middle_mouse_down

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
                elif event == "cancel":
                    self.cancel_current_run()
                elif event == "quit":
                    # Quit is always allowed — _quit_mainthread calls
                    # QApplication.quit() which terminates the event loop
                    # regardless of any in-flight worker thread. The
                    # os._exit(0) in run() then kills any stubborn
                    # non-daemon helper threads (e.g. urllib3 eviction).
                    self._quit_mainthread()
        except queue.Empty:
            pass

    def cancel_current_run(self) -> None:
        """Invalidate the active run and reset the dock immediately.

        Blocking HTTP calls are allowed to return naturally in their daemon
        workers.  Their RunContext stays cancelled, so stale responses cannot
        insert text or mutate the state of a newer run.
        """
        self._cancel_active_run()

        # If we're still recording, stop the sounddevice stream first.
        if self.is_recording:
            self.is_recording = False
            try:
                if self.recorder and self.recorder.stream is not None:
                    self.recorder.recording = False
                    self.recorder.stream.stop()
                    self.recorder.stream.close()
                    self.recorder.stream = None
            except Exception:
                pass

        # Reset the dock immediately on the main thread. Any stale worker will
        # fail _is_current_run() before emitting a later state transition.
        self.dock.set_idle()

    def start_recording(self):
        if self.is_recording or self.is_busy or self._get_active_run() is not None:
            return

        run = self._begin_run()
        try:
            self.is_recording = True
            self.recorder.start()

            def _start_popup():
                if not self.is_recording or not self._is_current_run(run):
                    return
                self.dock.set_recording(on_timeout=self.stop_recording)

                def _poll_rms():
                    if self.is_recording and self._is_current_run(run):
                        self.dock.set_rms(self.recorder.last_rms)
                        QTimer.singleShot(50, _poll_rms)

                QTimer.singleShot(50, _poll_rms)

            QTimer.singleShot(100, _start_popup)
        except Exception:
            self.is_recording = False
            run.cancel_event.set()
            self._finish_run_if_current(run)
            try:
                self.recorder.recording = False
            except Exception:
                pass
            self.dock.set_idle()

    def stop_recording(self):
        run = self._get_active_run()
        if not self.is_recording or run is None or not self._is_current_run(run):
            return

        self.is_recording = False
        self.is_busy = True

        self.dock.set_rms(0.0)
        self.dock.set_processing()

        threading.Thread(
            target=self._safe_transcribe_and_insert,
            args=(run,),
            daemon=True,
        ).start()

    def _safe_transcribe_and_insert(self, run: RunContext) -> None:
        """Run one worker while preventing stale runs from touching newer state."""
        try:
            self.transcribe_and_insert(run)
        except BaseException as exc:
            # Last-resort guard. A stale/cancelled worker is deliberately
            # silent; only the current owner may report an error or clear state.
            if not self._is_current_run(run):
                return
            try:
                lang = self.config.ui_language
                err_msg = f'{t("msg_error", lang)}: {exc}'
                self.dock.show_error_signal.emit(err_msg)
            except Exception:
                QTimer.singleShot(0, self.dock.set_idle)
            self._finish_run_if_current(run)

    def transcribe_and_insert(self, run: RunContext) -> None:
        audio_path = None
        dock_resolved = False
        cancelled = False
        try:
            if not self._is_current_run(run):
                cancelled = True
                return

            audio_path = self.recorder.stop()
            run.audio_path = audio_path

            if not self._is_current_run(run):
                cancelled = True
                return

            text = self.client.transcribe(audio_path)

            # A blocked request may have returned long after cancellation or
            # after a newer run became active. Revalidate before every side
            # effect rather than relying on the shared is_busy flag.
            if not self._is_current_run(run):
                cancelled = True
                return

            if text:
                raw_text = self.vocab.apply(text)
                if not self._is_current_run(run):
                    cancelled = True
                    return

                if self.config.correction_enabled:
                    self.dock.mark_correcting()

                corrected_text: str | None = None
                llm_failed: Exception | None = None
                if self.config.correction_enabled:
                    try:
                        corrected_text = self.llm.correct(raw_text)
                    except Exception as exc:  # noqa: BLE001
                        llm_failed = exc

                if not self._is_current_run(run):
                    cancelled = True
                    return

                final_text = (
                    corrected_text if (corrected_text and not llm_failed) else raw_text
                )

                # Revalidate immediately before the two user-visible side
                # effects. Once the paste has begun it cannot be retracted, but
                # a cancelled/stale worker can never begin a new paste.
                if not self._is_current_run(run):
                    cancelled = True
                    return
                self.dock.mark_done()

                if not self._is_current_run(run):
                    cancelled = True
                    return
                try:
                    self.inserter.insert_text(final_text)
                except Exception:
                    pass

                if self._is_current_run(run):
                    self.dock.schedule_idle(600)
                    dock_resolved = True
                    if llm_failed is not None:
                        lang = self.config.ui_language
                        self.dock.show_info_signal.emit(
                            t("msg_result_title", lang),
                            t("msg_llm_fallback", lang),
                        )
            else:
                if not self._is_current_run(run):
                    cancelled = True
                    return
                lang = self.config.ui_language
                self.dock.show_info_signal.emit(
                    t("msg_result_title", lang),
                    t("msg_no_speech", lang),
                )
                self.dock.mark_idle()
                dock_resolved = True

        except Exception as e:
            if not self._is_current_run(run):
                cancelled = True
                return
            if str(e) == "no_audio":
                self.dock.mark_idle()
                dock_resolved = True
            else:
                lang = self.config.ui_language
                err_msg = f'{t("msg_error", lang)}: {e}'
                self.dock.show_error_signal.emit(err_msg)
                dock_resolved = True

        finally:
            if audio_path and audio_path.exists():
                try:
                    audio_path.unlink()
                except Exception:
                    pass

            # A stale worker must never clear a newer run's busy state. Only
            # the active owner can complete the shared lifecycle.
            finished_current = self._finish_run_if_current(run)
            if finished_current and not dock_resolved and not cancelled:
                self.dock.mark_idle()

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
        # urllib3 2.x keeps a non-daemon connection-pool eviction thread alive.
        # All cleanup (tray, config) is done before exec() returns, so a hard
        # exit here is safe and is the only reliable way to terminate.
        os._exit(0)


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

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _mutex = _k32.CreateMutexW(None, True, "FlüsterFee_SingleInstance")
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        QMessageBox.warning(None, "FlüsterFee", "FlüsterFee läuft bereits.")
        sys.exit(0)

    print("Starte FlüsterFee…")
    App().run()
