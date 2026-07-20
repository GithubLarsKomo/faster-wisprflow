import ctypes
import os
import queue
import sys
import threading
import time

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
        """Abort the in-flight recording/processing run and reset the dock.

        Called when the user clicks the ✕ button while the dock is in
        RECORDING or PROCESSING state. This guarantees the user is never
        stuck — even if the underlying HTTP request to the LLM or Whisper
        backend is hanging, the dock returns to IDLE immediately and any
        subsequent API response is ignored.
        """
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
        # Flip the busy flag so any in-flight worker exits its critical
        # sections promptly (and so a new hotkey press is accepted).
        self.is_busy = False
        # Reset the dock immediately on the main thread.
        self.dock.set_idle()

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
            self.dock.set_idle()

    def stop_recording(self):
        if not self.is_recording:
            return

        self.is_recording = False
        self.is_busy = True

        self.dock.set_rms(0.0)
        self.dock.set_processing()

        threading.Thread(target=self._safe_transcribe_and_insert, daemon=True).start()

    def _safe_transcribe_and_insert(self) -> None:
        """Run transcribe_and_insert but guarantee the dock returns to idle
        and the busy flag is cleared even on any unexpected exception."""
        try:
            self.transcribe_and_insert()
        except BaseException as exc:
            # Last-resort guard: log and ensure the dock is reset so the
            # user is never stuck in RECORDING/PROCESSING state.
            try:
                lang = self.config.ui_language
                err_msg = f'{t("msg_error", lang)}: {exc}'
                self.dock.show_error_signal.emit(err_msg)
            except Exception:
                QTimer.singleShot(0, self.dock.set_idle)
            self.is_busy = False

    def transcribe_and_insert(self):
        audio_path = None
        # Track whether a dock-state transition was scheduled. If not (e.g. an
        # exception path that didn't emit a signal), force the dock to IDLE in
        # the finally block so the recording indicator is never left stuck.
        dock_resolved = False
        cancelled = False
        try:
            audio_path = self.recorder.stop()
            text = self.client.transcribe(audio_path)

            # If the user clicked ✕ during the API call, the dock has already
            # been reset to IDLE by cancel_current_run(). Skip all downstream
            # work and don't try to insert text.
            if not self.is_busy:
                cancelled = True
                return

            if text:
                raw_text = self.vocab.apply(text)
                if not self.is_busy:
                    cancelled = True
                    return
                # Tell the user the LLM step is in progress so the dock
                # indicator doesn't look frozen during a slow correction.
                if self.config.correction_enabled:
                    self.dock.mark_correcting()

                # LLM correction is best-effort. If it fails for any reason
                # (timeout, HTTP error, model refused, reasoning-only model,
                # user cancelled, …) we still insert the raw, vocab-applied
                # transcript so the user is never left without their text.
                #
                # Also important: a slow LLM (e.g. local Ollama on CPU) can
                # take 30+ s, during which the user might keep typing or
                # copying in the foreground app. We poll is_busy *during*
                # the wait so a cancel aborts the loop promptly, AND we
                # check it again *after* correct() returns so a paste from
                # a long-cancelled run is never sent.
                corrected_text: str | None = None
                llm_failed: Exception | None = None
                if self.config.correction_enabled:
                    try:
                        corrected_text = self.llm.correct(raw_text)
                    except Exception as exc:  # noqa: BLE001
                        llm_failed = exc

                # Re-check after the (potentially long) LLM call.
                if not self.is_busy:
                    cancelled = True
                    return

                final_text = (
                    corrected_text if (corrected_text and not llm_failed) else raw_text
                )
                # Switch the dock to DONE *before* the slow insert_text call
                # so the user sees the green ✓ (transcription succeeded,
                # text is being pasted) instead of the purple ●●● "correcting"
                # dots for the full ~400 ms the paste takes. Also guarantees
                # the dock resolves even if insert_text raises.
                #
                # All dock-state transitions from the worker thread are
                # routed through the dock's signals (which are Qt signals
                # and therefore thread-safe) instead of QTimer.singleShot
                # to guarantee the main thread picks them up reliably — even
                # if the worker thread is in a weird state at the moment
                # the event would fire.
                self.dock.mark_done()
                try:
                    self.inserter.insert_text(final_text)
                except Exception:
                    # insert_text already handles its own clipboard errors
                    # internally; this is a true last-resort catch so the
                    # dock's set_done → set_idle chain still fires.
                    pass
                # Force a short IDLE transition regardless of any pending
                # singleShot from set_done. The default DONE_HOLD_MS is
                # too long — the user sees the green ✓ for over a second
                # after the paste already completed, which they perceive
                # as "the indicator is still running".
                self.dock.schedule_idle(600)
                dock_resolved = True
                # If the LLM failed, briefly notify the user that we fell
                # back to the raw transcript. This is a non-blocking info
                # toast, not a hard error — the text is already inserted.
                if llm_failed is not None:
                    lang = self.config.ui_language
                    self.dock.show_info_signal.emit(
                        t("msg_result_title", lang),
                        t("msg_llm_fallback", lang),
                    )
            else:
                lang = self.config.ui_language
                self.dock.show_info_signal.emit(
                    t("msg_result_title", lang),
                    t("msg_no_speech", lang),
                )
                self.dock.mark_idle()
                dock_resolved = True

        except Exception as e:
            if str(e) == "no_audio":
                self.dock.mark_idle()
                dock_resolved = True
            else:
                lang = self.config.ui_language
                err_msg = f'{t("msg_error", lang)}: {e}'
                self.dock.show_error_signal.emit(err_msg)
                # show_error queues its own set_idle after T.ERROR_HOLD_MS.
                dock_resolved = True

        finally:
            if audio_path and audio_path.exists():
                try:
                    audio_path.unlink()
                except Exception:
                    pass
            self.is_busy = False
            # Safety net: if an exception escaped even the inner handlers
            # (e.g. an error in the dock signal emit), make absolutely sure
            # the dock returns to IDLE so the user is never stuck in
            # RECORDING or PROCESSING.
            if not dock_resolved and not cancelled:
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
