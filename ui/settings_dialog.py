"""PySide6 settings dialog — drop-in replacement for settings_window.py."""

from __future__ import annotations

import os
import tempfile
import threading
import time

import numpy as np
import requests
import sounddevice as sd
import soundfile as sf
from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog,
                               QFormLayout, QFrame, QGridLayout, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QMessageBox, QProgressBar, QPushButton,
                               QScrollArea, QSplitter, QStyle,
                               QTableWidget, QTableWidgetItem, QTextEdit,
                               QVBoxLayout, QWidget)

from config import (_DEFAULT_SYSTEM_PROMPT,
                    _DEFAULT_TRANSCRIPTION_INITIAL_PROMPT, DEFAULT_CONFIG,
                    DEFAULT_CORRECTOR_PROMPT_FILE, Config, _build_base_url,
                    delete_corrector_prompt, get_token, list_corrector_prompts,
                    load_config, load_corrector_prompt,
                    load_transcription_initial_prompt, save_config,
                    save_corrector_prompt,
                    save_transcription_initial_prompt, set_token)
from llm_corrector import LLMCorrector
from provider_registry import (
    get_provider,
    llm_provider_labels,
    normalize_provider,
    transcription_provider_labels,
)
from ui.theme import SETTINGS_STYLESHEET
from ui.translations import LANG_CODES, TRANSLATIONS
from ui.utils import _target_monitor
from whisper_client import WhisperClient

# ── helpers ───────────────────────────────────────────────────────────────────


def _center_dialog(dlg: QDialog, w: int, h: int) -> None:
    ml, mt, mr, mb = _target_monitor()
    x = ml + (mr - ml - w) // 2
    y = mt + (mb - mt - h) // 2
    dlg.setGeometry(x, y, w, h)


def _make_dialog(parent: QWidget | None, title: str, w: int, h: int) -> QDialog:
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setStyleSheet(SETTINGS_STYLESHEET)
    dlg.setWindowFlags(dlg.windowFlags() & ~Qt.WindowContextHelpButtonHint)
    dlg.setWindowModality(Qt.WindowModal)
    _center_dialog(dlg, w, h)
    return dlg


def _lbl(text: str, muted: bool = False) -> QLabel:
    lbl = QLabel(text)
    if muted:
        lbl.setObjectName("muted")
    return lbl


def _edit(text: str = "", width: int | None = None) -> QLineEdit:
    e = QLineEdit(text)
    if width:
        e.setFixedWidth(width)
    return e


def _btn(text: str, primary: bool = False) -> QPushButton:
    b = QPushButton(text)
    if primary:
        b.setObjectName("primary")
    return b


def _hbox(*widgets, spacing: int = 6) -> QWidget:
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(spacing)
    for item in widgets:
        if item == "stretch":
            lay.addStretch()
        else:
            lay.addWidget(item)
    return w


# ── Microphone level dialog (replaces _MicLevelPopup in tests) ────────────────


class _MicLevelDlg(QDialog):
    """Simple recording level meter dialog for mic/whisper tests."""

    def __init__(self, parent: QWidget | None = None, tr: dict | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
        )
        self.setStyleSheet(SETTINGS_STYLESHEET)
        self.setFixedSize(260, 72)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        if tr is None:
            tr = TRANSLATIONS["de"]
        self._lbl = QLabel(tr.get("mic_test_active", "Aufnahme läuft… (3s)"))
        self._lbl.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._lbl)
        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(12)
        layout.addWidget(self._bar)

        # centre on screen
        ml, mt, mr, mb = _target_monitor()
        x = ml + (mr - ml - 260) // 2
        y = mt + (mb - mt - 72) // 2
        self.move(x, y)

    def set_rms(self, rms: float) -> None:
        val = min(int(rms * 800), 100)
        self._bar.setValue(val)

    def set_label(self, text: str) -> None:
        self._lbl.setText(text)


# ── Main SettingsWindow ───────────────────────────────────────────────────────


class SettingsWindow:
    """Qt settings window — same public interface as the old tkinter version."""

    def __init__(self, app) -> None:
        self.app = app
        self.win: QDialog | None = None
        self._testing = False
        # Reference to the LLM-enabled checkbox in the open LLM sub-dialog (or None)
        self._llm_enabled_chk: QCheckBox | None = None

    # ── tr helpers ─────────────────────────────────────────────────────────
    @property
    def _tr(self) -> dict:
        lang = load_config().get("ui_language", "de")
        return TRANSLATIONS.get(lang, TRANSLATIONS["de"])

    def _t(self, key: str) -> str:
        return self._tr.get(key, key)

    # ── open ───────────────────────────────────────────────────────────────
    def open(self) -> None:
        if self.win and not self.win.isHidden():
            self.win.raise_()
            self.win.activateWindow()
            return
        self.win = _make_dialog(None, self._t("title"), 720, 660)
        self.win.setMinimumWidth(680)
        self.win.setMinimumHeight(640)
        self._build_main_window()
        self.win.show()

    def _build_main_window(self) -> None:
        assert self.win is not None
        cfg = load_config()
        tr = self._tr
        win = self.win

        outer = QVBoxLayout(win)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── scroll area for form ───────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        form_widget = QWidget()
        form_widget.setObjectName("formWidget")
        form_widget.setStyleSheet("QWidget#formWidget { background-color: #1c1c22; }")
        form_layout = QVBoxLayout(form_widget)
        form_layout.setContentsMargins(16, 12, 16, 12)
        form_layout.setSpacing(10)
        scroll.setWidget(form_widget)
        outer.addWidget(scroll)

        # ── General ───────────────────────────────────────────────────────
        gen_box = QGroupBox(tr["gen_frame"])
        gen_form = QFormLayout(gen_box)
        gen_form.setLabelAlignment(Qt.AlignRight)
        gen_form.setSpacing(6)

        self._hotkey_edit = _edit("+".join(cfg["hotkey_keys"]))
        gen_form.addRow(tr["hotkey"], self._hotkey_edit)

        self._restore_chk = QCheckBox(tr["restore_clipboard"])
        self._restore_chk.setChecked(cfg["restore_clipboard"])
        gen_form.addRow("", self._restore_chk)

        self._elevate_chk = QCheckBox(tr["auto_elevate"])
        self._elevate_chk.setChecked(cfg.get("auto_elevate", False))
        gen_form.addRow("", self._elevate_chk)

        self._ui_lang_combo = QComboBox()
        self._ui_lang_combo.addItems(LANG_CODES)
        cur_ui_lang = cfg.get("ui_language", "de")
        if cur_ui_lang in LANG_CODES:
            self._ui_lang_combo.setCurrentText(cur_ui_lang)
        gen_form.addRow(tr["system_language"], self._ui_lang_combo)

        form_layout.addWidget(gen_box)

        # ── Proxy ─────────────────────────────────────────────────────────
        prx_box = QGroupBox(tr["prx_frame"])
        prx_form = QFormLayout(prx_box)
        prx_form.setLabelAlignment(Qt.AlignRight)

        self._proxy_edit = _edit(cfg.get("proxy", ""))
        prx_form.addRow(tr["proxy_url"], self._proxy_edit)
        hint = _lbl(tr["proxy_hint"], muted=True)
        hint.setWordWrap(True)
        prx_form.addRow("", hint)
        form_layout.addWidget(prx_box)

        # ── Audio ─────────────────────────────────────────────────────────
        aud_box = QGroupBox(tr["aud_frame"])
        aud_form = QFormLayout(aud_box)
        aud_form.setLabelAlignment(Qt.AlignRight)
        aud_form.setSpacing(6)

        self._lang_combo = QComboBox()
        for code in LANG_CODES:
            self._lang_combo.addItem(code)
        cur_lang = cfg.get("language", "de")
        if cur_lang in LANG_CODES:
            self._lang_combo.setCurrentText(cur_lang)

        def _autosave_lang(idx: int) -> None:
            c = load_config()
            c["language"] = self._lang_combo.itemText(idx)
            save_config(c)
            self.app.reload_config()

        self._lang_combo.currentIndexChanged.connect(_autosave_lang)
        aud_form.addRow(tr["target_language"], self._lang_combo)

        self._devices: list[tuple[int | None, str]] = []
        selected_idx = 0
        current_dev = cfg.get("input_device", None)
        for i, d in enumerate(sd.query_devices()):
            if d["max_input_channels"] > 0:
                label = f"{i}: {d['name']} ({d['max_input_channels']} ch)"
                self._devices.append((i, label))
                if current_dev == i:
                    selected_idx = len(self._devices) - 1
        self._device_combo = QComboBox()
        self._device_combo.addItems([x[1] for x in self._devices])
        if self._devices:
            self._device_combo.setCurrentIndex(selected_idx)
        aud_form.addRow(tr["microphone"], self._device_combo)

        self._rate_edit = _edit(str(cfg["sample_rate"]), width=80)
        aud_form.addRow(tr["sample_rate"], self._rate_edit)

        self._channels_edit = _edit(str(cfg["channels"]), width=50)
        aud_form.addRow(tr["channels"], self._channels_edit)

        self._max_rec_edit = _edit(str(cfg.get("max_recording", 60)), width=60)
        aud_form.addRow(tr["max_recording"], self._max_rec_edit)

        form_layout.addWidget(aud_box)
        form_layout.addStretch()

        # ── Button bar ────────────────────────────────────────────────────
        btn_bar = QWidget()
        btn_bar.setStyleSheet(
            "QWidget { background-color: #16161c; "
            "border-top: 1px solid rgba(255,255,255,12); }"
        )
        btn_outer = QVBoxLayout(btn_bar)
        btn_outer.setContentsMargins(16, 10, 16, 10)
        btn_outer.setSpacing(6)

        # ── Row 1: sub-dialog launchers ───────────────────────────────────
        row1 = QHBoxLayout()
        row1.setSpacing(8)

        mic_btn = _btn(tr["btn_mic_test"])
        mic_btn.clicked.connect(self.test_microphone)
        row1.addWidget(mic_btn)

        self._btn_whisper = _btn(tr["srv_frame"].strip() + "…")
        self._btn_whisper.clicked.connect(self.open_transcription_settings)
        row1.addWidget(self._btn_whisper)

        self._btn_llm = _btn(tr["llm_frame"].strip() + "…")
        self._btn_llm.clicked.connect(self.open_llm_settings)
        row1.addWidget(self._btn_llm)

        row1.addStretch()

        vocab_btn = _btn(tr["btn_vocab"])
        vocab_btn.clicked.connect(self.open_vocabulary)
        row1.addWidget(vocab_btn)

        ssl_btn = _btn(tr.get("btn_ssl_diagnose", "SSL…"))
        ssl_btn.clicked.connect(self._open_ssl_diagnose)
        row1.addWidget(ssl_btn)

        btn_outer.addLayout(row1)

        # ── Row 2: action buttons (right-aligned) ─────────────────────────
        row2 = QHBoxLayout()
        row2.setSpacing(8)
        row2.addStretch()

        factory_btn = _btn(tr["btn_factory"])
        factory_btn.clicked.connect(self.reset_to_defaults)
        row2.addWidget(factory_btn)

        save_btn = _btn(tr["btn_save"], primary=True)
        save_btn.clicked.connect(self.save)
        row2.addWidget(save_btn)

        close_btn = _btn(tr["btn_close"])
        close_btn.clicked.connect(win.close)
        row2.addWidget(close_btn)

        btn_outer.addLayout(row2)

        outer.addWidget(btn_bar)

    def _selected_device_id(self) -> int | None:
        idx = self._device_combo.currentIndex()
        if 0 <= idx < len(self._devices):
            return self._devices[idx][0]
        return None

    # ── sync from external config changes ─────────────────────────────────
    def sync_from_config(self) -> None:
        """Update open settings widgets when config changes externally (e.g. dock)."""
        if not self.win or self.win.isHidden():
            return
        cfg = load_config()
        if hasattr(self, "_lang_combo"):
            lang = cfg.get("language", "de")
            self._lang_combo.blockSignals(True)
            self._lang_combo.setCurrentText(lang)
            self._lang_combo.blockSignals(False)
        if self._llm_enabled_chk is not None:
            self._llm_enabled_chk.blockSignals(True)
            self._llm_enabled_chk.setChecked(cfg.get("correction_enabled", False))
            self._llm_enabled_chk.blockSignals(False)

    # ── save ───────────────────────────────────────────────────────────────
    def save(self) -> None:
        tr = self._tr
        cfg = load_config()
        old_lang = cfg.get("ui_language", "de")
        hotkey_raw = self._hotkey_edit.text().strip()
        cfg["hotkey_keys"] = [k.strip() for k in hotkey_raw.split("+") if k.strip()]
        cfg["restore_clipboard"] = self._restore_chk.isChecked()
        cfg["auto_elevate"] = self._elevate_chk.isChecked()
        cfg["ui_language"] = self._ui_lang_combo.currentText()
        cfg["proxy"] = self._proxy_edit.text().strip()
        cfg["language"] = self._lang_combo.currentText()
        dev_id = self._selected_device_id()
        if dev_id is not None:
            cfg["input_device"] = dev_id
        try:
            cfg["sample_rate"] = int(self._rate_edit.text())
        except ValueError:
            pass
        try:
            cfg["channels"] = int(self._channels_edit.text())
        except ValueError:
            pass
        try:
            cfg["max_recording"] = int(self._max_rec_edit.text())
        except ValueError:
            pass
        save_config(cfg)
        self.app.reload_config()
        QMessageBox.information(self.win, tr["msg_saved_title"], tr["msg_saved_body"])
        # Rebuild the window when the UI language changed so all labels update.
        if cfg.get("ui_language", "de") != old_lang:
            self.win.close()
            self.open()

    # ── reset ──────────────────────────────────────────────────────────────
    def reset_to_defaults(self) -> None:
        tr = self._tr
        reply = QMessageBox.question(
            self.win,
            tr["msg_factory_title"],
            tr["msg_factory_confirm"],
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        save_config(dict(DEFAULT_CONFIG))
        self.app.reload_config()
        QMessageBox.information(
            self.win, tr["msg_factory_title"], tr["msg_factory_done"]
        )
        if self.win:
            self.win.close()
            self.win = None
        self.open()

    # ── SSL / TLS diagnosis dialog ─────────────────────────────────────────
    def _open_ssl_diagnose(self) -> None:
        import ssl_setup

        tr = self._tr
        dlg = _make_dialog(self.win, tr.get("ssl_diag_title", "SSL-Diagnose"), 560, 460)
        outer = QVBoxLayout(dlg)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(10)

        info = QTextEdit()
        info.setReadOnly(True)
        info.setFontFamily("Consolas")
        info.setFontPointSize(9)
        outer.addWidget(info)

        btn_row = QHBoxLayout()
        run_btn = _btn(tr.get("ssl_diag_run", "Diagnose starten"), primary=True)
        close_btn = _btn(tr["btn_close"])
        btn_row.addWidget(run_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        outer.addLayout(btn_row)
        close_btn.clicked.connect(dlg.close)

        result_box: list = [None]

        def _run_diag() -> None:
            run_btn.setEnabled(False)
            info.setPlainText(tr.get("ssl_diag_running", "Läuft…"))
            result_box[0] = None

            def _bg():
                result_box[0] = ssl_setup.diagnose()

            threading.Thread(target=_bg, daemon=True).start()

            def _poll():
                if result_box[0] is None:
                    QTimer.singleShot(200, _poll)
                    return
                run_btn.setEnabled(True)
                r = result_box[0]
                lines: list[str] = []
                lines.append(f"Active methods  : {r['active_methods']}")
                lines.append(f"certifi.where() : {r['certifi_where']}")
                lines.append(f"REQUESTS_CA_BUNDLE: {r['requests_ca_bundle']}")
                lines.append(f"SSL_CERT_FILE   : {r['ssl_cert_file']}")
                lines.append(f"Proxy env       : {r['proxy_env'] or '(none)'}")
                lines.append(f"Frozen EXE      : {r['frozen']}")
                lines.append("")
                ct = r["connection_test"]
                if "error" in ct:
                    lines.append(f"Connection FAILED: {ct['error']}")
                else:
                    lines.append(
                        f"Connection OK   : HTTP {ct.get('status')} "
                        f"({ct.get('url')})"
                    )
                lines.append("")
                issuer = r.get("cert_issuer") or {}
                lines.append(f"Cert issuer     : {issuer.get('organizationName','?')}")
                if r["tls_inspection_detected"]:
                    lines.append("⚠  TLS INSPECTION DETECTED (corporate proxy)")
                else:
                    lines.append("✓  No TLS inspection detected")
                info.setPlainText("\n".join(lines))

            QTimer.singleShot(200, _poll)

        run_btn.clicked.connect(_run_diag)
        dlg.show()
        _run_diag()  # start immediately

    # ── test microphone ────────────────────────────────────────────────────
    def test_microphone(self) -> None:
        if self._testing:
            return
        tr = self._tr
        device_id = self._selected_device_id()
        try:
            rate = int(self._rate_edit.text())
            channels = int(self._channels_edit.text())
        except ValueError:
            return

        try:
            sd.check_input_settings(
                device=device_id, samplerate=rate, channels=channels
            )
        except Exception:
            # Configured sample rate unsupported — fall back to device default
            try:
                rate = int(sd.query_devices(device_id)["default_samplerate"])
                sd.check_input_settings(
                    device=device_id, samplerate=rate, channels=channels
                )
            except Exception as exc:
                QMessageBox.critical(self.win, tr["msg_mic_fail_title"], str(exc))
                return

        self._testing = True
        level_dlg = _MicLevelDlg(self.win, tr)
        level_dlg.show()

        frames: list = []
        rms_box = [0.0]
        import threading as _t

        lock = _t.Lock()

        def _cb(indata, _n, _t2, _st):
            with lock:
                frames.append(indata.copy())
                rms_box[0] = float(np.sqrt(np.mean(indata**2)))

        try:
            stream = sd.InputStream(
                device=device_id,
                samplerate=rate,
                channels=channels,
                dtype="float32",
                callback=_cb,
                blocksize=int(rate * 0.05),
            )
            stream.start()
        except Exception as exc:
            level_dlg.close()
            self._testing = False
            QMessageBox.critical(self.win, tr["msg_mic_fail_title"], str(exc))
            return

        deadline = time.monotonic() + 3.0

        def _poll():
            with lock:
                rms = rms_box[0]
            level_dlg.set_rms(rms)
            if time.monotonic() < deadline:
                QTimer.singleShot(50, _poll)
            else:
                stream.stop()
                stream.close()
                level_dlg.close()
                self._testing = False
                with lock:
                    audio = (
                        np.concatenate(frames, axis=0)
                        if frames
                        else np.zeros((1, channels))
                    )
                peak = float(np.max(np.abs(audio)))
                if peak < 0.01:
                    QMessageBox.warning(
                        self.win,
                        tr["msg_mic_title"],
                        f"{tr['msg_mic_low_level']}: {peak:.4f}",
                    )
                else:
                    QMessageBox.information(
                        self.win, tr["msg_mic_title"], f"{tr['msg_mic_ok']}: {peak:.4f}"
                    )

        QTimer.singleShot(50, _poll)

    # ── transcription sub-dialog ───────────────────────────────────────────
    def open_transcription_settings(self) -> None:
        tr = self._tr
        cfg = load_config()
        dlg = _make_dialog(self.win, tr["srv_frame"].strip(), 720, 680)

        outer = QVBoxLayout(dlg)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        form_w = QWidget()
        form_w.setObjectName("fw")
        form_w.setStyleSheet("QWidget#fw { background: #1c1c22; }")
        form_lay = QVBoxLayout(form_w)
        form_lay.setContentsMargins(16, 12, 16, 12)
        form_lay.setSpacing(10)
        scroll.setWidget(form_w)
        outer.addWidget(scroll)

        box = QGroupBox(tr["srv_frame"])
        form = QFormLayout(box)
        form.setLabelAlignment(Qt.AlignRight)
        form.setSpacing(6)

        providers = transcription_provider_labels()
        prov_combo = QComboBox()
        prov_combo.addItems(providers)
        cur_prov = cfg.get("whisper_provider", "local")
        if cur_prov not in providers:
            cur_prov = "local"
        prov_combo.setCurrentText(cur_prov)
        form.addRow(tr["provider"], prov_combo)

        _url_row = form.rowCount()
        url_edit = _edit(cfg.get("whisper_url", ""))
        form.addRow(tr["url"], url_edit)

        _port_row = form.rowCount()
        port_val = cfg.get("port", None)
        port_edit = _edit(str(port_val) if port_val else "", width=80)
        form.addRow(tr["port"], port_edit)

        _ep_row = form.rowCount()
        ep_edit = _edit(cfg.get("whisper_endpoint", "/transcribe"))
        form.addRow(tr["transcription_endpoint"], ep_edit)

        _health_row = form.rowCount()
        health_edit = _edit(cfg.get("health_endpoint", "/health"))
        form.addRow(tr["health_endpoint"], health_edit)

        _token_row = form.rowCount()
        token_edit = _edit(get_token("whisper", cur_prov))
        token_edit.setEchoMode(QLineEdit.Password)
        form.addRow(tr["token"], token_edit)

        _model_row = form.rowCount()
        model_edit = _edit(cfg.get("whisper_model", ""))
        form.addRow(tr["model_whisper"], model_edit)

        guidance_chk = QCheckBox(tr["transcription_guidance"])
        guidance_chk.setChecked(cfg.get("transcription_guidance_enabled", False))
        form.addRow("", guidance_chk)

        _http_rows = [_url_row, _port_row, _ep_row, _health_row]
        _cloud_rows = [_token_row, _model_row]

        def _on_prov_change(prov: str) -> None:
            is_local = normalize_provider(prov) == "local"
            for r in _http_rows:
                form.setRowVisible(r, is_local)
            for r in _cloud_rows:
                form.setRowVisible(r, True)
            token_edit.setText(get_token("whisper", prov))

        prov_combo.currentTextChanged.connect(_on_prov_change)
        _on_prov_change(prov_combo.currentText())

        form_lay.addWidget(box)

        prompt_box = QGroupBox(tr["transcription_prompt_frame"])
        prompt_lay = QVBoxLayout(prompt_box)
        prompt_edit = QTextEdit()
        prompt_edit.setPlainText(load_transcription_initial_prompt(cfg))
        prompt_edit.setMinimumHeight(100)
        prompt_lay.addWidget(prompt_edit)

        reset_prompt_btn = _btn(tr["btn_prompt_factory"])
        reset_prompt_btn.clicked.connect(
            lambda: _confirm_reset_prompt(prompt_edit, False)
        )
        prompt_lay.addWidget(reset_prompt_btn)
        form_lay.addWidget(prompt_box)
        form_lay.addStretch()

        # ── button bar ─────────────────────────────────────────────────────
        btn_bar = QWidget()
        btn_bar.setStyleSheet(
            "QWidget { background: #16161c; "
            "border-top: 1px solid rgba(255,255,255,12); }"
        )
        bb_lay = QHBoxLayout(btn_bar)
        bb_lay.setContentsMargins(16, 10, 16, 10)
        bb_lay.setSpacing(8)

        health_btn = _btn(tr["btn_health"])
        test_btn = _btn(tr["btn_whisper_test"])
        save_btn = _btn(tr["btn_save"], primary=True)
        close_btn = _btn(tr["btn_close"])
        bb_lay.addWidget(health_btn)
        bb_lay.addWidget(test_btn)
        bb_lay.addStretch()
        bb_lay.addWidget(save_btn)
        bb_lay.addWidget(close_btn)
        outer.addWidget(btn_bar)

        def _confirm_reset_prompt(edit: QTextEdit, is_system: bool) -> None:
            key = (
                "msg_prompt_factory_confirm"
                if is_system
                else "msg_transcription_prompt_factory_confirm"
            )
            if (
                QMessageBox.question(
                    dlg,
                    tr["btn_prompt_factory"],
                    tr[key],
                    QMessageBox.Yes | QMessageBox.No,
                )
                == QMessageBox.Yes
            ):
                default = (
                    _DEFAULT_SYSTEM_PROMPT
                    if is_system
                    else _DEFAULT_TRANSCRIPTION_INITIAL_PROMPT
                )
                edit.setPlainText(default)

        def _cur_prov() -> str:
            return prov_combo.currentText()

        def _save_whisper() -> None:
            c = load_config()
            c["whisper_url"] = url_edit.text().strip()
            raw_port = port_edit.text().strip()
            c["port"] = int(raw_port) if raw_port else None
            c["whisper_endpoint"] = ep_edit.text().strip()
            c["health_endpoint"] = health_edit.text().strip()
            c["whisper_model"] = model_edit.text().strip()
            c["whisper_provider"] = _cur_prov()
            c["transcription_guidance_enabled"] = guidance_chk.isChecked()
            tok = token_edit.text().strip()
            if tok:
                set_token("whisper", _cur_prov(), tok)
            save_transcription_initial_prompt(prompt_edit.toPlainText())
            save_config(c)
            self.app.reload_config()
            QMessageBox.information(dlg, tr["msg_saved_title"], tr["msg_saved_body"])

        def _do_health() -> None:
            prov = _cur_prov()
            tok = token_edit.text().strip()
            headers = {"Authorization": f"Bearer {tok}"} if tok else {}
            raw_port = port_edit.text().strip()
            base = _build_base_url(
                url_edit.text().strip(),
                int(raw_port) if raw_port else None,
            )
            provider = get_provider(prov)
            if normalize_provider(prov) == "local":
                ep = health_edit.text().strip().lstrip("/")
                url = base.rstrip("/") + "/" + ep
            elif provider is not None and provider.transcription_models_url:
                url = provider.transcription_models_url
            else:
                return
            result_box: list = [None]
            health_btn.setEnabled(False)

            def _run():
                try:
                    r = requests.get(url, headers=headers, timeout=5)
                    result_box[0] = (r.status_code, r.text[:300])
                except Exception as exc:
                    result_box[0] = exc

            threading.Thread(target=_run, daemon=True).start()

            def _check():
                if result_box[0] is None:
                    QTimer.singleShot(200, _check)
                    return
                health_btn.setEnabled(True)
                res = result_box[0]
                if isinstance(res, Exception):
                    QMessageBox.critical(dlg, tr["msg_health_fail_title"], str(res))
                else:
                    status, body = res
                    QMessageBox.information(dlg, tr["btn_health"], f"{status}: {body}")

            QTimer.singleShot(200, _check)

        def _do_whisper_test() -> None:
            if self._testing:
                return
            device_id = self._selected_device_id()
            try:
                rate = int(self._rate_edit.text())
                channels = int(self._channels_edit.text())
            except ValueError:
                return
            try:
                sd.check_input_settings(
                    device=device_id, samplerate=rate, channels=channels
                )
            except Exception:
                # Configured sample rate unsupported — fall back to device default
                try:
                    rate = int(sd.query_devices(device_id)["default_samplerate"])
                    sd.check_input_settings(
                        device=device_id, samplerate=rate, channels=channels
                    )
                except Exception as exc:
                    QMessageBox.critical(dlg, tr["msg_whisper_fail_title"], str(exc))
                    return

            self._testing = True
            test_btn.setEnabled(False)
            level_dlg = _MicLevelDlg(dlg, tr)
            level_dlg.set_label(tr.get("whisper_test_active", "Aufnahme… (3s)"))
            level_dlg.show()

            frames: list = []
            rms_box = [0.0]
            import threading as _thr

            lock = _thr.Lock()

            def _cb(indata, _n, _t2, _st):
                with lock:
                    frames.append(indata.copy())
                    rms_box[0] = float(np.sqrt(np.mean(indata**2)))

            try:
                stream = sd.InputStream(
                    device=device_id,
                    samplerate=rate,
                    channels=channels,
                    dtype="float32",
                    callback=_cb,
                    blocksize=int(rate * 0.05),
                )
                stream.start()
            except Exception as exc:
                level_dlg.close()
                self._testing = False
                test_btn.setEnabled(True)
                QMessageBox.critical(dlg, tr["msg_whisper_fail_title"], str(exc))
                return

            deadline = time.monotonic() + 3.0

            def _poll():
                with lock:
                    rms = rms_box[0]
                level_dlg.set_rms(rms)
                if time.monotonic() < deadline:
                    QTimer.singleShot(50, _poll)
                else:
                    stream.stop()
                    stream.close()
                    level_dlg.set_label(
                        tr.get("whisper_test_transcribing", "Transkribiere…")
                    )
                    with lock:
                        audio = (
                            np.concatenate(frames, axis=0)
                            if frames
                            else np.zeros((1, channels))
                        )
                        audio_rms = float(np.sqrt(np.mean(audio**2)))
                        if audio_rms < 0.005:
                            level_dlg.close()
                            self._testing = False
                            test_btn.setEnabled(True)
                            QMessageBox.warning(
                                dlg, tr["msg_whisper_title"], tr["msg_whisper_no_text"]
                            )
                            return

                    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
                    tmp.close()
                    try:
                        sf.write(tmp.name, audio, rate)
                    except Exception as exc:
                        level_dlg.close()
                        self._testing = False
                        test_btn.setEnabled(True)
                        QMessageBox.critical(
                            dlg, tr["msg_whisper_fail_title"], str(exc)
                        )
                        return

                    result_box: list[str | Exception | None] = [None]

                    # Use the target language from the live UI combo if
                    # available, otherwise fall back to the saved config.
                    # This ensures the test transcription uses the language
                    # the user currently has selected, not whatever was last
                    # persisted to disk.
                    try:
                        _cur_lang = (
                            self._lang_combo.currentText()
                            if hasattr(self, "_lang_combo")
                            and self._lang_combo.currentText()
                            else load_config().get("language", "de")
                        )
                    except Exception:
                        _cur_lang = "de"

                    def _run():
                        try:
                            cfg_obj = Config()
                            cfg_obj.whisper_url = url_edit.text().strip()
                            raw_port = port_edit.text().strip()
                            cfg_obj.port = int(raw_port) if raw_port else None
                            cfg_obj.whisper_endpoint = ep_edit.text().strip()
                            cfg_obj.whisper_model = model_edit.text().strip()
                            cfg_obj.whisper_provider = _cur_prov()
                            cfg_obj.whisper_token = token_edit.text().strip()
                            cfg_obj.transcription_guidance_enabled = (
                                guidance_chk.isChecked()
                            )
                            cfg_obj.transcription_initial_prompt = (
                                prompt_edit.toPlainText()
                            )
                            cfg_obj.language = _cur_lang
                            result_box[0] = WhisperClient(cfg_obj).transcribe(tmp.name)
                        except Exception as exc:
                            result_box[0] = exc
                        finally:
                            try:
                                os.unlink(tmp.name)
                            except OSError:
                                pass

                    threading.Thread(target=_run, daemon=True).start()

                    def _check_result():
                        if result_box[0] is None:
                            QTimer.singleShot(200, _check_result)
                            return
                        level_dlg.close()
                        self._testing = False
                        test_btn.setEnabled(True)
                        res = result_box[0]
                        if isinstance(res, Exception):
                            QMessageBox.critical(
                                dlg, tr["msg_whisper_fail_title"], str(res)
                            )
                        elif not res:
                            QMessageBox.warning(
                                dlg, tr["msg_whisper_title"], tr["msg_whisper_no_text"]
                            )
                        else:
                            # Show the language that was sent so the user can
                            # verify their server actually honoured it.
                            lang_label = tr.get("target_language", "Zielsprache")
                            body = f"[{lang_label}: {_cur_lang}]\n\n{res}"
                            QMessageBox.information(dlg, tr["msg_whisper_title"], body)

                    QTimer.singleShot(200, _check_result)

            QTimer.singleShot(50, _poll)

        health_btn.clicked.connect(_do_health)
        test_btn.clicked.connect(_do_whisper_test)
        save_btn.clicked.connect(_save_whisper)
        close_btn.clicked.connect(dlg.close)

        dlg.show()

    # ── LLM sub-dialog ─────────────────────────────────────────────────────
    def open_llm_settings(self) -> None:
        tr = self._tr
        cfg = load_config()
        dlg = _make_dialog(self.win, tr["llm_frame"].strip(), 800, 720)

        outer = QVBoxLayout(dlg)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        form_w = QWidget()
        form_w.setObjectName("fw2")
        form_w.setStyleSheet("QWidget#fw2 { background: #1c1c22; }")
        form_lay = QVBoxLayout(form_w)
        form_lay.setContentsMargins(16, 12, 16, 12)
        form_lay.setSpacing(10)
        scroll.setWidget(form_w)
        outer.addWidget(scroll)

        # ── LLM connection ─────────────────────────────────────────────────
        llm_box = QGroupBox(tr["llm_frame"])
        llm_form = QFormLayout(llm_box)
        llm_form.setLabelAlignment(Qt.AlignRight)
        llm_form.setSpacing(6)

        enabled_chk = QCheckBox(tr["llm_enable"])
        enabled_chk.setChecked(cfg.get("correction_enabled", False))
        self._llm_enabled_chk = enabled_chk
        dlg.finished.connect(lambda _: setattr(self, "_llm_enabled_chk", None))
        llm_form.addRow("", enabled_chk)

        llm_providers = llm_provider_labels()
        prov_combo = QComboBox()
        prov_combo.addItems(llm_providers)
        cur_prov = cfg.get("llm_provider", "Ollama")
        if cur_prov in llm_providers:
            prov_combo.setCurrentText(cur_prov)
        llm_form.addRow(tr["provider"], prov_combo)

        url_edit = _edit(cfg.get("correction_url", ""))
        llm_port_val = cfg.get("correction_port", None)
        port_edit = _edit(str(llm_port_val) if llm_port_val else "", width=80)
        url_port_w = _hbox(url_edit, _lbl(tr["port"]), port_edit)
        _llm_url_row = llm_form.rowCount()
        llm_form.addRow(tr["url"] + " / " + tr["port"], url_port_w)

        token_edit = _edit(get_token("correction", cur_prov))
        token_edit.setEchoMode(QLineEdit.Password)
        llm_form.addRow(tr["token"], token_edit)

        _CLOUD_LLM_PROVIDERS = {
            label
            for label in llm_providers
            if (get_provider(label) is not None and get_provider(label).chat_url)
        }

        # model row with refresh button (editable combobox populated from provider)
        # NOTE: must be created before _on_llm_prov_change, which triggers a refresh.
        model_combo = QComboBox()
        model_combo.setEditable(True)
        model_combo.setInsertPolicy(QComboBox.NoInsert)
        _initial_model = cfg.get("correction_model", "")
        if _initial_model:
            model_combo.addItem(_initial_model)
            model_combo.setCurrentText(_initial_model)
        refresh_btn = _btn("↻")
        refresh_btn.setFixedWidth(36)
        refresh_btn.setToolTip(tr.get("model_reload", "Modelle neu laden"))
        model_row = _hbox(model_combo, refresh_btn)
        llm_form.addRow(tr["model"], model_row)

        # ── model-listing helpers (must be defined before _on_llm_prov_change) ──
        def _models_url_and_headers(
            prov: str, base: str, tok: str
        ) -> tuple[str, dict] | None:
            """Return the (url, headers) for listing models of *prov*, or None."""
            provider_id = normalize_provider(prov)
            provider = get_provider(prov)
            if provider_id == "ollama":
                return base.rstrip("/") + "/api/tags", {}
            if provider_id in ("lm_studio", "azure_openai"):
                return base.rstrip("/") + "/v1/models", (
                    {"Authorization": f"Bearer {tok}"} if tok else {}
                )
            if provider is None or not provider.models_url:
                return None
            if provider.auth_style == "anthropic":
                return provider.models_url, {
                    "x-api-key": tok,
                    "anthropic-version": "2023-06-01",
                }
            return provider.models_url, (
                {"Authorization": f"Bearer {tok}"} if tok else {}
            )

        def _parse_models(prov: str, data: dict) -> list[str]:
            """Extract a list of model names/ids from a provider's JSON response."""
            try:
                if prov == "Ollama":
                    return [m.get("name", "") for m in data.get("models", []) if m.get("name")]
                # OpenAI-compatible (LM Studio, OpenAI, Groq, OpenRouter, Azure)
                return [m.get("id", "") for m in data.get("data", []) if m.get("id")]
            except Exception:
                return []

        def _populate_model_combo(names: list[str]) -> None:
            cur = model_combo.currentText().strip()
            # Build a single sorted list (case-insensitive) including the
            # currently selected/typed value so it sits at its alphabetical
            # position rather than always being prepended.
            all_names = [n for n in names if n]
            if cur and cur not in all_names:
                all_names.append(cur)
            sorted_items = sorted(set(all_names), key=lambda s: s.casefold())
            model_combo.blockSignals(True)
            model_combo.clear()
            model_combo.addItems(sorted_items)
            # Always make sure the selected model is what the combobox displays
            # in its line-edit area.
            if cur:
                idx = model_combo.findText(cur)
                if idx >= 0:
                    model_combo.setCurrentIndex(idx)
                else:
                    model_combo.setEditText(cur)
            elif sorted_items:
                model_combo.setCurrentIndex(0)
            model_combo.blockSignals(False)

        def _refresh_models(silent: bool = False) -> None:
            prov = prov_combo.currentText()
            tok = token_edit.text().strip()
            raw_port = port_edit.text().strip()
            try:
                port_val = int(raw_port) if raw_port else None
            except ValueError:
                port_val = None
            base = _build_base_url(url_edit.text().strip(), port_val)

            # Cloud providers need a token to even attempt the listing.
            if prov in _CLOUD_LLM_PROVIDERS and not tok:
                if not silent:
                    QMessageBox.warning(
                        dlg, tr["model"], tr.get("model_need_token", "Bitte Token angeben.")
                    )
                return

            target = _models_url_and_headers(prov, base, tok)
            if target is None:
                return
            url, headers = target

            refresh_btn.setEnabled(False)
            prev_text = model_combo.currentText()
            # While loading, keep the previously selected model visible in the
            # line-edit area (don't clear/repopulate the dropdown yet).
            model_combo.blockSignals(True)
            model_combo.setEditText(prev_text)
            model_combo.setEnabled(False)
            model_combo.blockSignals(False)

            result_box: list = [None]

            def _run():
                try:
                    r = requests.get(url, headers=headers, timeout=5)
                    r.raise_for_status()
                    result_box[0] = r.json()
                except Exception as exc:
                    result_box[0] = exc

            threading.Thread(target=_run, daemon=True).start()

            def _check():
                if result_box[0] is None:
                    QTimer.singleShot(200, _check)
                    return
                refresh_btn.setEnabled(True)
                res = result_box[0]
                if isinstance(res, Exception):
                    model_combo.blockSignals(True)
                    model_combo.clear()
                    if prev_text:
                        model_combo.addItem(prev_text)
                    model_combo.setEditText(prev_text)
                    model_combo.setEnabled(True)
                    model_combo.blockSignals(False)
                    if not silent:
                        QMessageBox.warning(
                            dlg,
                            tr["model"],
                            tr.get("model_load_failed", "Modelle konnten nicht geladen werden")
                            + f":\n{res}",
                        )
                    return
                names = _parse_models(prov, res)
                _populate_model_combo(names)
                model_combo.setEnabled(True)
                if not silent and not names:
                    QMessageBox.information(
                        dlg, tr["model"], tr.get("model_none_found", "Keine Modelle gefunden.")
                    )

            QTimer.singleShot(200, _check)

        def _on_llm_prov_change(prov: str) -> None:
            is_cloud = prov in _CLOUD_LLM_PROVIDERS
            llm_form.setRowVisible(_llm_url_row, not is_cloud)
            tok = get_token("correction", prov)
            token_edit.setText(tok)
            # Cloud providers (and Azure) need a token before we can list models,
            # so we auto-trigger the load here.
            _refresh_models(silent=True)

        prov_combo.currentTextChanged.connect(_on_llm_prov_change)
        _on_llm_prov_change(prov_combo.currentText())

        form_lay.addWidget(llm_box)

        # ── Model parameters ───────────────────────────────────────────────
        params_box = QGroupBox(" Model Parameters ")
        params_grid = QGridLayout(params_box)
        params_grid.setSpacing(6)
        params_grid.setColumnMinimumWidth(1, 80)
        params_grid.setColumnMinimumWidth(3, 80)
        params_grid.setColumnStretch(1, 0)
        params_grid.setColumnStretch(3, 0)

        temp_edit = _edit(str(cfg.get("temperature", "")), width=80)
        top_p_edit = _edit(str(cfg.get("top_p", "")), width=80)
        max_tok_edit = _edit(str(cfg.get("max_tokens", "")), width=80)
        num_ctx_edit = _edit(str(cfg.get("num_ctx", "")), width=80)

        params_grid.addWidget(_lbl("temperature"), 0, 0, Qt.AlignRight)
        params_grid.addWidget(temp_edit, 0, 1)
        params_grid.addWidget(_lbl("top_p"), 0, 2, Qt.AlignRight)
        params_grid.addWidget(top_p_edit, 0, 3)
        params_grid.addWidget(_lbl("max_tokens"), 1, 0, Qt.AlignRight)
        params_grid.addWidget(max_tok_edit, 1, 1)
        params_grid.addWidget(_lbl("num_ctx (Ollama)"), 1, 2, Qt.AlignRight)
        params_grid.addWidget(num_ctx_edit, 1, 3)

        params_reset_btn = _btn(tr.get("param_reset", "Standard wiederherstellen"))
        params_grid.addWidget(params_reset_btn, 2, 0, 1, 4)

        form_lay.addWidget(params_box)

        # ── Corrector prompts manager ──────────────────────────────────────
        prompts_box = QGroupBox(tr["corrector_prompts_frame"])
        prompts_outer = QVBoxLayout(prompts_box)
        prompts_outer.setContentsMargins(8, 8, 8, 8)
        prompts_outer.setSpacing(6)

        active_prompt = cfg.get(
            "active_corrector_prompt", DEFAULT_CORRECTOR_PROMPT_FILE
        )

        splitter = QSplitter(Qt.Horizontal)
        splitter.setStyleSheet("QSplitter::handle { background: #3f3f50; width: 4px; }")

        # left: list + vertical icon buttons
        left_w = QWidget()
        left_lay = QHBoxLayout(left_w)
        left_lay.setContentsMargins(0, 0, 4, 0)
        left_lay.setSpacing(4)

        prompt_list = QListWidget()
        prompt_list.setMinimumWidth(120)
        prompt_list.setMaximumWidth(220)
        left_lay.addWidget(prompt_list)

        _sty = prompt_list.style()

        def _icon_btn(pixmap_enum: QStyle.StandardPixmap, tooltip: str) -> QPushButton:
            b = QPushButton()
            b.setIcon(_sty.standardIcon(pixmap_enum))
            b.setIconSize(QSize(16, 16))
            b.setFixedSize(28, 28)
            b.setToolTip(tooltip)
            return b

        new_btn = _icon_btn(QStyle.SP_FileDialogNewFolder, tr["corrector_prompt_new"])
        dup_btn = _icon_btn(QStyle.SP_FileLinkIcon, tr["corrector_prompt_duplicate"])
        del_btn = _icon_btn(QStyle.SP_TrashIcon, tr["corrector_prompt_delete"])
        set_act_btn = _icon_btn(
            QStyle.SP_DialogApplyButton, tr["corrector_prompt_set_active"]
        )

        btn_col = QVBoxLayout()
        btn_col.setSpacing(6)
        btn_col.setContentsMargins(2, 2, 2, 2)
        btn_col.addWidget(new_btn)
        btn_col.addWidget(dup_btn)
        btn_col.addWidget(del_btn)
        btn_col.addStretch()
        btn_col.addWidget(set_act_btn)
        left_lay.addLayout(btn_col)
        splitter.addWidget(left_w)

        # right: editor
        right_w = QWidget()
        right_lay = QVBoxLayout(right_w)
        right_lay.setContentsMargins(6, 0, 0, 0)
        right_lay.setSpacing(6)

        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        title_lbl = _lbl(tr["corrector_prompt_title_label"])
        title_edit = _edit()
        title_row.addWidget(title_lbl)
        title_row.addWidget(title_edit)
        right_lay.addLayout(title_row)

        body_edit = QTextEdit()
        body_edit.setMinimumHeight(120)
        right_lay.addWidget(body_edit)

        save_prompt_btn = _btn(tr["corrector_prompt_save"])
        right_lay.addWidget(save_prompt_btn)
        splitter.addWidget(right_w)

        # list narrow (180), editor wide (rest)
        splitter.setSizes([180, 9999])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        prompts_outer.addWidget(splitter)
        form_lay.addWidget(prompts_box)
        form_lay.addStretch()

        # ── populate list ──────────────────────────────────────────────────
        def _reload_list():
            prompt_list.clear()
            for p in list_corrector_prompts():
                item_text = p["title"]
                if p["filename"] == active_prompt:
                    item_text += " ✓"
                prompt_list.addItem(item_text)
                prompt_list.item(prompt_list.count() - 1).setData(
                    Qt.UserRole, p["filename"]
                )

        _reload_list()

        def _on_list_select():
            item = prompt_list.currentItem()
            if not item:
                return
            fn = item.data(Qt.UserRole)
            _title, _body = load_corrector_prompt(fn)
            title_edit.setText(_title)
            body_edit.setPlainText(_body)

        def _save_prompt():
            item = prompt_list.currentItem()
            if not item:
                return
            fn = item.data(Qt.UserRole)
            save_corrector_prompt(
                fn, title_edit.text().strip(), body_edit.toPlainText()
            )
            _reload_list()
            QMessageBox.information(
                dlg,
                tr["corrector_prompt_title_label"],
                tr["msg_corrector_prompt_saved"],
            )

        def _new_prompt():
            import uuid

            fn = f"prompt_{uuid.uuid4().hex[:8]}.md"
            save_corrector_prompt(fn, "New prompt", "")
            _reload_list()
            for i in range(prompt_list.count()):
                if prompt_list.item(i).data(Qt.UserRole) == fn:
                    prompt_list.setCurrentRow(i)
                    break

        def _duplicate_prompt():
            item = prompt_list.currentItem()
            if not item:
                return
            fn = item.data(Qt.UserRole)
            _title, _body = load_corrector_prompt(fn)
            import uuid

            new_fn = f"prompt_{uuid.uuid4().hex[:8]}.md"
            save_corrector_prompt(new_fn, _title + " (copy)", _body)
            _reload_list()

        def _delete_prompt():
            item = prompt_list.currentItem()
            if not item:
                return
            fn = item.data(Qt.UserRole)
            if fn == DEFAULT_CORRECTOR_PROMPT_FILE:
                return
            if (
                QMessageBox.question(
                    dlg,
                    tr["corrector_prompt_delete"],
                    tr["msg_corrector_prompt_delete_confirm"],
                    QMessageBox.Yes | QMessageBox.No,
                )
                != QMessageBox.Yes
            ):
                return
            delete_corrector_prompt(fn)
            _reload_list()

        def _set_active():
            item = prompt_list.currentItem()
            if not item:
                return
            nonlocal active_prompt
            fn = item.data(Qt.UserRole)
            active_prompt = fn
            c = load_config()
            c["active_corrector_prompt"] = fn
            save_config(c)
            _reload_list()

        prompt_list.currentItemChanged.connect(lambda *_: _on_list_select())
        save_prompt_btn.clicked.connect(_save_prompt)
        new_btn.clicked.connect(_new_prompt)
        dup_btn.clicked.connect(_duplicate_prompt)
        del_btn.clicked.connect(_delete_prompt)
        set_act_btn.clicked.connect(_set_active)

        # ── model refresh (function defined earlier; just wire the button) ─
        refresh_btn.clicked.connect(lambda: _refresh_models(silent=False))

        # ── param reset ────────────────────────────────────────────────────
        def _reset_params():
            if (
                QMessageBox.question(
                    dlg,
                    tr.get("param_reset", "Standard"),
                    tr.get("param_reset_confirm", "Reset?"),
                    QMessageBox.Yes | QMessageBox.No,
                )
                != QMessageBox.Yes
            ):
                return
            temp_edit.setText(str(DEFAULT_CONFIG.get("temperature", "")))
            top_p_edit.setText(str(DEFAULT_CONFIG.get("top_p", "")))
            max_tok_edit.setText(str(DEFAULT_CONFIG.get("max_tokens", "")))
            num_ctx_edit.setText(str(DEFAULT_CONFIG.get("num_ctx", "")))

        params_reset_btn.clicked.connect(_reset_params)

        # ── button bar ─────────────────────────────────────────────────────
        btn_bar = QWidget()
        btn_bar.setStyleSheet(
            "QWidget { background: #16161c; "
            "border-top: 1px solid rgba(255,255,255,12); }"
        )
        bb_lay = QHBoxLayout(btn_bar)
        bb_lay.setContentsMargins(16, 10, 16, 10)
        bb_lay.setSpacing(8)

        health_btn = _btn(tr["btn_health"])
        test_btn = _btn(tr["btn_llm_test"])
        save_btn = _btn(tr["btn_save"], primary=True)
        close_btn = _btn(tr["btn_close"])
        bb_lay.addWidget(health_btn)
        bb_lay.addWidget(test_btn)
        bb_lay.addStretch()
        bb_lay.addWidget(save_btn)
        bb_lay.addWidget(close_btn)
        outer.addWidget(btn_bar)

        def _do_llm_health() -> None:
            prov = prov_combo.currentText()
            tok = token_edit.text().strip()
            raw_port = port_edit.text().strip()
            base = _build_base_url(
                url_edit.text().strip(),
                int(raw_port) if raw_port else None,
            )
            target = _models_url_and_headers(prov, base, tok)
            if target is None:
                return
            url, headers = target
            result_box: list = [None]
            health_btn.setEnabled(False)

            def _run():
                try:
                    r = requests.get(url, headers=headers, timeout=5)
                    result_box[0] = (r.status_code, r.text[:300])
                except Exception as exc:
                    result_box[0] = exc

            threading.Thread(target=_run, daemon=True).start()

            def _check():
                if result_box[0] is None:
                    QTimer.singleShot(200, _check)
                    return
                health_btn.setEnabled(True)
                res = result_box[0]
                if isinstance(res, Exception):
                    QMessageBox.critical(dlg, tr["msg_health_fail_title"], str(res))
                else:
                    status, body = res
                    QMessageBox.information(dlg, tr["btn_health"], f"{status}: {body}")

            QTimer.singleShot(200, _check)

        def _save_llm() -> None:
            c = load_config()
            c["correction_enabled"] = enabled_chk.isChecked()
            c["llm_provider"] = prov_combo.currentText()
            c["correction_url"] = url_edit.text().strip()
            raw_port = port_edit.text().strip()
            c["correction_port"] = int(raw_port) if raw_port else None
            c["correction_model"] = model_combo.currentText().strip()
            tok = token_edit.text().strip()
            if tok:
                set_token("correction", prov_combo.currentText(), tok)

            def _safe_float(s: str) -> float | None:
                try:
                    return float(s)
                except ValueError:
                    return None

            def _safe_int(s: str) -> int | None:
                try:
                    return int(s)
                except ValueError:
                    return None

            v = _safe_float(temp_edit.text().strip())
            if v is not None:
                c["temperature"] = v
            v = _safe_float(top_p_edit.text().strip())
            if v is not None:
                c["top_p"] = v
            v = _safe_int(max_tok_edit.text().strip())
            if v is not None:
                c["max_tokens"] = v
            v = _safe_int(num_ctx_edit.text().strip())
            if v is not None:
                c["num_ctx"] = v

            save_config(c)
            self.app.reload_config()
            QMessageBox.information(dlg, tr["msg_saved_title"], tr["msg_saved_body"])

        def _test_llm() -> None:
            if self._testing:
                return
            model = model_combo.currentText().strip()
            is_cloud = prov_combo.currentText() in _CLOUD_LLM_PROVIDERS
            url = url_edit.text().strip()
            if not model or (not is_cloud and not url):
                QMessageBox.warning(
                    dlg, tr["msg_llm_test_title"], tr["msg_llm_test_missing"]
                )
                return
            self._testing = True
            test_btn.setEnabled(False)

            result_box: list[str | Exception | None] = [None]
            probe_prompt = tr.get("llm_probe_prompt", "Respond with: OK")

            def _run():
                try:
                    cfg_obj = Config()
                    cfg_obj.correction_enabled = True
                    cfg_obj.llm_provider = prov_combo.currentText()
                    cfg_obj.correction_url = url
                    raw_port = port_edit.text().strip()
                    cfg_obj.correction_port = int(raw_port) if raw_port else None
                    cfg_obj.correction_model = model
                    cfg_obj.correction_token = token_edit.text().strip()
                    cfg_obj.language = "de"
                    # active system prompt
                    cfg_obj.active_corrector_prompt = cfg.get(
                        "active_corrector_prompt", DEFAULT_CORRECTOR_PROMPT_FILE
                    )
                    result_box[0] = LLMCorrector(cfg_obj).probe(probe_prompt)
                except Exception as exc:
                    result_box[0] = exc

            threading.Thread(target=_run, daemon=True).start()

            def _check():
                if result_box[0] is None:
                    QTimer.singleShot(200, _check)
                    return
                self._testing = False
                test_btn.setEnabled(True)
                res = result_box[0]
                if isinstance(res, Exception):
                    QMessageBox.critical(dlg, tr["msg_llm_fail_title"], str(res))
                elif not res:
                    QMessageBox.warning(
                        dlg, tr["msg_llm_title"], tr["msg_llm_empty_response"]
                    )
                else:
                    QMessageBox.information(
                        dlg, tr["msg_llm_title"], f"{tr['msg_llm_result']}: {res}"
                    )

            QTimer.singleShot(200, _check)

        health_btn.clicked.connect(_do_llm_health)
        test_btn.clicked.connect(_test_llm)
        save_btn.clicked.connect(_save_llm)
        close_btn.clicked.connect(dlg.close)

        # select first prompt item
        if prompt_list.count():
            prompt_list.setCurrentRow(0)

        dlg.show()

    # ── vocabulary sub-dialog ───────────────────────────────────────────────
    def open_vocabulary(self) -> None:
        tr = self._tr
        dlg = _make_dialog(self.win, tr["btn_vocab"], 560, 480)

        outer = QVBoxLayout(dlg)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(8)

        table = QTableWidget(0, 2)
        table.setHorizontalHeaderLabels(
            [tr.get("vocab_col_src", "Erkannt als"), tr.get("vocab_col_dst", "Ersatz")]
        )
        table.horizontalHeader().setStretchLastSection(True)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        outer.addWidget(table)

        # edit panel (hidden by default)
        edit_panel = QGroupBox(tr.get("vocab_edit_frame", "Bearbeiten"))
        edit_form = QFormLayout(edit_panel)
        src_edit = _edit()
        dst_edit = _edit()
        tip_lbl = _lbl(tr.get("vocab_tip", r"\n = newline, \t = tab"), muted=True)
        edit_form.addRow(tr.get("vocab_src_lbl", "Erkannt als:"), src_edit)
        edit_form.addRow(tr.get("vocab_dst_lbl", "Ersatz:"), dst_edit)
        edit_form.addRow("", tip_lbl)
        edit_panel.setVisible(False)
        outer.addWidget(edit_panel)

        # buttons
        btn_row = QHBoxLayout()
        add_btn = _btn(tr.get("vocab_btn_add", "Hinzufügen"), primary=True)
        edit_btn = _btn(tr.get("vocab_btn_edit", "Editieren"))
        remove_btn = _btn(tr.get("vocab_btn_remove", "Entfernen"))
        close_btn = _btn(tr["btn_close"])
        btn_row.addWidget(add_btn)
        btn_row.addWidget(edit_btn)
        btn_row.addWidget(remove_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        outer.addLayout(btn_row)

        # ── populate table ─────────────────────────────────────────────────
        def _refresh():
            table.setRowCount(0)
            for key, val in self.app.vocab.all().items():
                row = table.rowCount()
                table.insertRow(row)
                display_val = val.replace("\n", "\\n").replace("\t", "\\t")
                table.setItem(row, 0, QTableWidgetItem(key))
                table.setItem(row, 1, QTableWidgetItem(display_val))

        _refresh()

        _editing_mode = [False]  # track add vs edit

        def _start_add():
            _editing_mode[0] = False
            src_edit.clear()
            dst_edit.clear()
            edit_panel.setVisible(True)
            src_edit.setFocus()

        def _start_edit():
            rows = table.selectedItems()
            if not rows:
                return
            row = table.currentRow()
            key = table.item(row, 0).text()
            _editing_mode[0] = True
            src_edit.setText(key)
            raw_val = self.app.vocab.all().get(key, "")
            dst_edit.setText(raw_val.replace("\n", "\\n").replace("\t", "\\t"))
            edit_panel.setVisible(True)
            dst_edit.setFocus()

        def _apply_edit():
            src = src_edit.text().strip()
            dst = dst_edit.text()
            if not src:
                return
            dst_real = dst.replace("\\n", "\n").replace("\\t", "\t")
            if _editing_mode[0]:
                # editing: remove old key first if different
                old_key = src  # src shouldn't change in edit mode
                self.app.vocab.remove(old_key)
            self.app.vocab.add(src, dst_real)
            edit_panel.setVisible(False)
            _refresh()

        def _remove():
            rows = table.selectedItems()
            if not rows:
                return
            row = table.currentRow()
            key = table.item(row, 0).text()
            self.app.vocab.remove(key)
            _refresh()

        add_btn.clicked.connect(_start_add)
        edit_btn.clicked.connect(_start_edit)
        remove_btn.clicked.connect(_remove)

        # when enter pressed in edit fields, apply
        src_edit.returnPressed.connect(_apply_edit)
        dst_edit.returnPressed.connect(_apply_edit)

        close_btn.clicked.connect(dlg.close)
        dlg.show()
