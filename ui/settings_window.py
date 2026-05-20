import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

import numpy as np
import requests
import sounddevice as sd
import soundfile as sf

from config import (
    _DEFAULT_SYSTEM_PROMPT,
    BASE_DIR,
    DEFAULT_CONFIG,
    Config,
    _build_base_url,
    load_config,
    load_system_prompt,
    save_config,
    save_system_prompt,
)
from llm_corrector import LLMCorrector
from ui.popups import _LLMPopup, _MicLevelPopup
from ui.translations import LANG_CODES as _LANG_CODES
from ui.translations import TRANSLATIONS
from ui.utils import _center_on_target
from whisper_client import WhisperClient


class SettingsWindow:
    def __init__(self, app):
        self.app = app
        self.win = None
        self._testing = False
        self._test_btns: list = []
        self._dialog_parent: tk.Misc | None = None

    def open(self):
        if self.win and self.win.winfo_exists():
            self.win.lift()
            return

        cfg = load_config()

        self.win = tk.Toplevel(self.app.overlay.root)
        self.win.title("FlüsterFee Einstellungen")
        _center_on_target(self.win, 580, 490)
        self.win.resizable(False, True)
        self.win.attributes("-topmost", True)

        # ── Pinned button area at the bottom ──────────────────
        btn_area = ttk.Frame(self.win, padding=(12, 4, 12, 12))
        btn_area.pack(side="bottom", fill="x")

        # ── Content area ─────────────────────────────────────
        frm = ttk.Frame(self.win, padding=12)
        frm.pack(fill="both", expand=True)

        # ── StringVars ────────────────────────────────────────
        self.url_var = tk.StringVar(value=cfg["whisper_url"])
        port_val = cfg.get("port", None)
        self.port_var = tk.StringVar(value=str(port_val) if port_val else "")
        self.endpoint_var = tk.StringVar(
            value=cfg.get("whisper_endpoint", "/transcribe")
        )
        self.health_var = tk.StringVar(value=cfg.get("health_endpoint", "/health"))
        self.lang_var = tk.StringVar(value=cfg["language"])
        self.ui_lang_var = tk.StringVar(value=cfg.get("ui_language", "de"))
        self.rate_var = tk.StringVar(value=str(cfg["sample_rate"]))
        self.channels_var = tk.StringVar(value=str(cfg["channels"]))
        self.hotkey_var = tk.StringVar(value="+".join(cfg["hotkey_keys"]))
        self.restore_var = tk.BooleanVar(value=cfg["restore_clipboard"])
        self.elevate_var = tk.BooleanVar(value=cfg.get("auto_elevate", False))
        self.llm_enabled_var = tk.BooleanVar(value=cfg.get("correction_enabled", False))
        self.llm_url_var = tk.StringVar(value=cfg.get("correction_url", ""))
        llm_port_val = cfg.get("correction_port", None)
        self.llm_port_var = tk.StringVar(
            value=str(llm_port_val) if llm_port_val else ""
        )
        self.llm_model_var = tk.StringVar(value=cfg.get("correction_model", ""))
        self.whisper_token_var = tk.StringVar(value=cfg.get("whisper_token", ""))
        self.whisper_model_var = tk.StringVar(value=cfg.get("whisper_model", ""))
        self.llm_token_var = tk.StringVar(value=cfg.get("correction_token", ""))
        self.whisper_provider_var = tk.StringVar(
            value=cfg.get("whisper_provider", "lokal")
        )
        self.llm_provider_var = tk.StringVar(value=cfg.get("llm_provider", "Ollama"))
        self.proxy_var = tk.StringVar(value=cfg.get("proxy", ""))

        devices = []
        selected_index = 0
        current = cfg.get("input_device", None)
        for i, d in enumerate(sd.query_devices()):
            if d["max_input_channels"] > 0:
                label = f"{i}: {d['name']} ({d['max_input_channels']} ch)"
                devices.append((i, label))
                if current == i:
                    selected_index = len(devices) - 1
        self.devices = devices
        self.device_var = tk.StringVar(
            value=devices[selected_index][1] if devices else ""
        )

        LBL = {"sticky": "e", "padx": (0, 8), "pady": 3}
        INP = {"sticky": "ew", "pady": 3}

        # ── Allgemein ─────────────────────────────────────────
        gen = ttk.LabelFrame(frm, text=" Allgemein ", padding=(10, 6))
        gen.pack(fill="x", pady=(0, 8))
        gen.columnconfigure(1, weight=1)

        _lbl_hotkey = ttk.Label(gen, text="Hotkey")
        _lbl_hotkey.grid(row=0, column=0, **LBL)
        hk_frm = ttk.Frame(gen)
        hk_frm.grid(row=0, column=1, sticky="w", pady=3)
        ttk.Entry(hk_frm, textvariable=self.hotkey_var, width=22).pack(side="left")
        _lbl_hotkey_hint = ttk.Label(
            hk_frm, text="  z. B. ctrl+linke windows", foreground="gray"
        )
        _lbl_hotkey_hint.pack(side="left")

        _chk_restore = ttk.Checkbutton(
            gen,
            text="Clipboard nach Einfügen wiederherstellen",
            variable=self.restore_var,
        )
        _chk_restore.grid(row=1, column=0, columnspan=2, sticky="w", pady=3)

        _chk_elevate = ttk.Checkbutton(
            gen,
            text="Beim Start automatisch Admin-Rechte anfordern",
            variable=self.elevate_var,
        )
        _chk_elevate.grid(row=2, column=0, columnspan=2, sticky="w", pady=3)

        _lbl_sys_lang = ttk.Label(gen, text="Systemsprache")
        _lbl_sys_lang.grid(row=3, column=0, **LBL)
        ttk.Combobox(
            gen,
            textvariable=self.ui_lang_var,
            values=_LANG_CODES,
            state="readonly",
            width=6,
        ).grid(row=3, column=1, sticky="w", pady=3)

        # ── Proxy ─────────────────────────────────────────
        prx = ttk.LabelFrame(frm, text=" Proxy ", padding=(10, 6))
        prx.pack(fill="x", pady=(0, 8))
        prx.columnconfigure(1, weight=1)
        _lbl_proxy_url = ttk.Label(prx, text="Proxy-URL")
        _lbl_proxy_url.grid(row=0, column=0, **LBL)
        ttk.Entry(prx, textvariable=self.proxy_var).grid(row=0, column=1, **INP)
        _lbl_proxy_hint = ttk.Label(
            prx,
            text="z. B. http://proxy.example.com:8080 — leer lassen für keinen Proxy",
            foreground="gray",
        )
        _lbl_proxy_hint.grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 2))

        # ── Audio ─────────────────────────────────────────────
        aud = ttk.LabelFrame(frm, text=" Audio ", padding=(10, 6))
        aud.pack(fill="x", pady=(0, 8))
        aud.columnconfigure(1, weight=1)

        _lbl_lang = ttk.Label(aud, text="Zielsprache")
        _lbl_lang.grid(row=0, column=0, **LBL)
        ttk.Combobox(
            aud,
            textvariable=self.lang_var,
            values=_LANG_CODES,
            state="readonly",
            width=6,
        ).grid(row=0, column=1, sticky="w", pady=3)

        _lbl_mic = ttk.Label(aud, text="Mikrofon")
        _lbl_mic.grid(row=1, column=0, **LBL)
        ttk.Combobox(
            aud, textvariable=self.device_var, values=[x[1] for x in devices]
        ).grid(row=1, column=1, **INP)

        _lbl_rate = ttk.Label(aud, text="Sample Rate")
        _lbl_rate.grid(row=2, column=0, **LBL)
        ttk.Entry(aud, textvariable=self.rate_var, width=8).grid(
            row=2, column=1, sticky="w", pady=3
        )

        _lbl_channels = ttk.Label(aud, text="Kanäle")
        _lbl_channels.grid(row=3, column=0, **LBL)
        ttk.Entry(aud, textvariable=self.channels_var, width=4).grid(
            row=3, column=1, sticky="w", pady=3
        )

        _btn_save_ref: list = [None]
        _btn_whisper_settings_ref: list = [None]
        _btn_llm_settings_ref: list = [None]

        def _apply_lang(*_):
            lang = self.ui_lang_var.get()
            t = TRANSLATIONS.get(lang, TRANSLATIONS["de"])
            self.win.title(t["title"])
            gen.configure(text=t["gen_frame"])
            prx.configure(text=t["prx_frame"])
            aud.configure(text=t["aud_frame"])
            _lbl_hotkey.configure(text=t["hotkey"])
            _lbl_hotkey_hint.configure(text="  " + t["hotkey_hint"].strip())
            _chk_restore.configure(text=t["restore_clipboard"])
            _chk_elevate.configure(text=t["auto_elevate"])
            _lbl_sys_lang.configure(text=t["system_language"])
            _lbl_proxy_url.configure(text=t["proxy_url"])
            _lbl_proxy_hint.configure(text=t["proxy_hint"])
            _lbl_lang.configure(text=t["target_language"])
            _lbl_mic.configure(text=t["microphone"])
            _lbl_rate.configure(text=t["sample_rate"])
            _lbl_channels.configure(text=t["channels"])
            _btn_mic.configure(text=t["btn_mic_test"])
            if _btn_save_ref[0] is not None:
                _btn_save_ref[0].configure(text=t["btn_save"])
            _btn_vocab.configure(text=t["btn_vocab"])
            if _btn_whisper_settings_ref[0] is not None:
                _btn_whisper_settings_ref[0].configure(text=t["srv_frame"] + "\u2026")
            if _btn_llm_settings_ref[0] is not None:
                _btn_llm_settings_ref[0].configure(text=t["llm_frame"] + "\u2026")
            _btn_close.configure(text=t["btn_close"])

        def _validate_save(*_):
            if _btn_save_ref[0] is None:
                return
            whisper_ok = self.whisper_provider_var.get() == "lokal" or bool(
                self.whisper_token_var.get().strip()
            )
            llm_ok = self.llm_provider_var.get() == "Ollama" or bool(
                self.llm_token_var.get().strip()
            )
            _btn_save_ref[0].configure(
                state="normal" if (whisper_ok and llm_ok) else "disabled"
            )

        self.ui_lang_var.trace_add("write", _apply_lang)
        self.whisper_token_var.trace_add("write", _validate_save)
        self.llm_token_var.trace_add("write", _validate_save)

        # ── Buttons ───────────────────────────────────────────
        self._test_btns.clear()

        # Row 1: Mikrofon testen | Transkription… | LLM-Korrektur…
        btns_row1 = ttk.Frame(btn_area)
        btns_row1.pack(fill="x", pady=(0, 4))

        _btn_mic = ttk.Button(
            btns_row1, text="Mikrofon testen", command=self.test_microphone
        )
        _btn_mic.pack(side="left", padx=(0, 4))
        self._test_btns.append(_btn_mic)

        _btn_whisper_settings = ttk.Button(
            btns_row1,
            text="Transkription\u2026",
            command=self.open_transcription_settings,
        )
        _btn_whisper_settings.pack(side="left", padx=(0, 4))
        _btn_whisper_settings_ref[0] = _btn_whisper_settings

        _btn_llm_settings = ttk.Button(
            btns_row1, text="LLM-Korrektur\u2026", command=self.open_llm_settings
        )
        _btn_llm_settings.pack(side="left", padx=(0, 4))
        _btn_llm_settings_ref[0] = _btn_llm_settings

        # Row 2: Vokabular verwalten | Speichern | Schließen
        btns_row2 = ttk.Frame(btn_area)
        btns_row2.pack(fill="x")

        _btn_vocab = ttk.Button(
            btns_row2, text="Vokabular verwalten", command=self.open_vocabulary
        )
        _btn_vocab.pack(side="left", padx=(0, 4))

        _btn_close = ttk.Button(btns_row2, text="Schließen", command=self.win.destroy)
        _btn_close.pack(side="right", padx=(4, 0))

        _btn_save = ttk.Button(btns_row2, text="Speichern", command=self.save)
        _btn_save_ref[0] = _btn_save
        _btn_save.pack(side="right", padx=4)

        _btn_factory = (
            None  # removed from bar; kept for reset_to_defaults via menu if needed
        )

        _apply_lang()

    def _set_testing(self, active: bool) -> None:
        """Enable/disable all test buttons while a test is running."""
        self._testing = active
        state = "disabled" if active else "normal"
        for btn in self._test_btns:
            btn.configure(state=state)

    def selected_device_id(self):
        label = self.device_var.get()
        for device_id, device_label in self.devices:
            if device_label == label:
                return device_id
        return None

    def _tr(self) -> dict:
        """Return the translation dict for the currently selected UI language."""
        lang = getattr(self, "ui_lang_var", None)
        lang = lang.get() if lang else load_config().get("ui_language", "de")
        return TRANSLATIONS.get(lang, TRANSLATIONS["de"])

    def _parent_win(self) -> tk.Misc:
        """Return the currently active sub-window, or the main settings window."""
        p = self._dialog_parent
        if p and p.winfo_exists():
            return p
        return self.win

    def save(self):
        cfg = load_config()
        cfg["whisper_url"] = self.url_var.get().strip()
        port_str = self.port_var.get().strip()
        cfg["port"] = (
            int(port_str) if port_str.isdigit() and int(port_str) > 0 else None
        )
        cfg["whisper_endpoint"] = self.endpoint_var.get().strip()
        cfg["health_endpoint"] = self.health_var.get().strip()
        cfg["language"] = self.lang_var.get().strip()
        cfg["ui_language"] = self.ui_lang_var.get()
        cfg["sample_rate"] = int(self.rate_var.get())
        cfg["channels"] = int(self.channels_var.get())
        cfg["input_device"] = self.selected_device_id()
        cfg["hotkey_keys"] = [
            x.strip() for x in self.hotkey_var.get().split("+") if x.strip()
        ]
        cfg["restore_clipboard"] = bool(self.restore_var.get())
        cfg["auto_elevate"] = bool(self.elevate_var.get())
        cfg["correction_enabled"] = bool(self.llm_enabled_var.get())
        cfg["correction_url"] = self.llm_url_var.get().strip()
        llm_port_str = self.llm_port_var.get().strip()
        cfg["correction_port"] = (
            int(llm_port_str)
            if llm_port_str.isdigit() and int(llm_port_str) > 0
            else None
        )
        cfg["correction_model"] = self.llm_model_var.get().strip()
        cfg["whisper_token"] = self.whisper_token_var.get().strip()
        cfg["whisper_model"] = self.whisper_model_var.get().strip()
        cfg["whisper_provider"] = self.whisper_provider_var.get()
        cfg["correction_token"] = self.llm_token_var.get().strip()
        cfg["llm_provider"] = self.llm_provider_var.get()
        cfg["proxy"] = self.proxy_var.get().strip()

        save_config(cfg)
        self.app.reload_config()
        tr = self._tr()
        messagebox.showinfo(
            tr["msg_saved_title"],
            tr["msg_saved_body"],
            parent=self.win,
        )

    def reset_to_defaults(self):
        tr = self._tr()
        if not messagebox.askyesno(
            tr["msg_factory_title"],
            tr["msg_factory_confirm"],
            parent=self.win,
        ):
            return

        save_config(DEFAULT_CONFIG)
        save_system_prompt(_DEFAULT_SYSTEM_PROMPT)
        self.app.reload_config()

        self.url_var.set(DEFAULT_CONFIG["whisper_url"])
        default_port = DEFAULT_CONFIG.get("port", None)
        self.port_var.set(str(default_port) if default_port else "")
        self.endpoint_var.set(DEFAULT_CONFIG["whisper_endpoint"])
        self.health_var.set(DEFAULT_CONFIG["health_endpoint"])
        self.lang_var.set(DEFAULT_CONFIG["language"])
        self.ui_lang_var.set(DEFAULT_CONFIG.get("ui_language", "de"))
        self.rate_var.set(str(DEFAULT_CONFIG["sample_rate"]))
        self.channels_var.set(str(DEFAULT_CONFIG["channels"]))
        self.hotkey_var.set("+".join(DEFAULT_CONFIG["hotkey_keys"]))
        self.restore_var.set(DEFAULT_CONFIG["restore_clipboard"])
        self.elevate_var.set(DEFAULT_CONFIG["auto_elevate"])
        self.device_var.set("")
        self.llm_enabled_var.set(DEFAULT_CONFIG.get("correction_enabled", False))
        self.llm_url_var.set(DEFAULT_CONFIG.get("correction_url", ""))
        llm_port_def = DEFAULT_CONFIG.get("correction_port", None)
        self.llm_port_var.set(str(llm_port_def) if llm_port_def else "")
        self.llm_model_var.set(DEFAULT_CONFIG.get("correction_model", ""))
        self.whisper_model_var.set(DEFAULT_CONFIG.get("whisper_model", ""))
        self.whisper_provider_var.set(DEFAULT_CONFIG.get("whisper_provider", "lokal"))
        self.llm_provider_var.set(DEFAULT_CONFIG.get("llm_provider", "Ollama"))
        self.proxy_var.set(DEFAULT_CONFIG.get("proxy", ""))

        messagebox.showinfo(
            tr["msg_factory_title"], tr["msg_factory_done"], parent=self.win
        )

    def open_vocabulary(self):
        if not self.win or not self.win.winfo_exists():
            return
        if (
            hasattr(self, "_vocab_win")
            and self._vocab_win
            and self._vocab_win.winfo_exists()
        ):
            self._vocab_win.lift()
            return
        # Andere Unterfenster schließen
        for attr in ("_whisper_win", "_llm_win"):
            w = getattr(self, attr, None)
            if w and w.winfo_exists():
                w.destroy()
        vwin = tk.Toplevel(self.win)
        self._vocab_win = vwin
        vwin.title("Vokabular verwalten")
        _center_on_target(vwin, 480, 430)
        vwin.resizable(True, True)
        vwin.attributes("-topmost", True)

        frm = ttk.Frame(vwin, padding=10)
        frm.pack(fill="both", expand=True)

        cols = ("erkannt", "ersatz")
        tree = ttk.Treeview(frm, columns=cols, show="headings", selectmode="browse")
        tree.heading("erkannt", text="Erkannt als")
        tree.heading("ersatz", text="Ersatz")
        tree.column("erkannt", width=200)
        tree.column("ersatz", width=220)
        vsb = ttk.Scrollbar(frm, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        frm.rowconfigure(0, weight=1)
        frm.columnconfigure(0, weight=1)

        def _esc(s: str) -> str:
            """Escape real control chars to printable literals for display/editing."""
            return s.replace("\n", "\\n").replace("\t", "\\t").replace("\r", "\\r")

        def _unesc(s: str) -> str:
            """Convert typed escape sequences (\\n, \\t) to real control chars."""
            return s.replace("\\n", "\n").replace("\\t", "\t").replace("\\r", "\r")

        def _refresh():
            tree.delete(*tree.get_children())
            for orig, corr in sorted(self.app.vocab.all().items()):
                tree.insert("", "end", values=(orig, _esc(corr)))

        _refresh()

        # ── Inline-Edit-Bereich (row=1, zunächst ausgeblendet) ─────────────
        edit_frm = ttk.LabelFrame(frm, text=" Bearbeiten ", padding=(8, 4))
        ef = ttk.Frame(edit_frm)
        ef.pack(fill="x")
        ttk.Label(ef, text="Erkannt als:").grid(
            row=0, column=0, sticky="e", padx=(0, 6)
        )
        edit_orig_var = tk.StringVar()
        ttk.Entry(ef, textvariable=edit_orig_var, width=18).grid(
            row=0, column=1, sticky="ew", padx=(0, 12)
        )
        ttk.Label(ef, text="Ersatz:").grid(row=0, column=2, sticky="e", padx=(0, 6))
        edit_corr_var = tk.StringVar()
        ttk.Entry(ef, textvariable=edit_corr_var, width=18).grid(
            row=0, column=3, sticky="ew"
        )
        ef.columnconfigure(1, weight=1)
        ef.columnconfigure(3, weight=1)
        ttk.Label(
            edit_frm, text="Tipp: \\n = Zeilenumbruch, \\t = Tab", foreground="gray"
        ).pack(anchor="w", pady=(2, 0))
        # edit_frm starts hidden — gridded only when entering edit mode

        # ── Button-Leiste (row=2) ──────────────────────────────────────────
        btns = ttk.Frame(frm)
        btns.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))

        _editing_orig: list = [None]  # key being edited (mutable cell)

        def _enter_edit_mode():
            sel = tree.selection()
            if not sel:
                return
            orig, corr = tree.item(sel[0])["values"]
            _editing_orig[0] = str(orig)
            edit_orig_var.set(str(orig))
            edit_corr_var.set(_esc(str(corr)))
            # show inline edit frame
            edit_frm.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 0))
            # swap buttons: hide normal set, show save/cancel
            btn_add.pack_forget()
            btn_edit.pack_forget()
            btn_remove.pack_forget()
            btn_close.pack_forget()
            btn_save.pack(side="left", padx=(0, 4))
            btn_cancel.pack(side="left", padx=4)

        def _save_edit():
            o = edit_orig_var.get().strip()
            c = _unesc(edit_corr_var.get())
            if o and c.strip(" "):
                old_key = _editing_orig[0]
                if old_key and old_key.lower() != o.lower():
                    self.app.vocab.remove(old_key)
                self.app.vocab.add(o, c)
                _refresh()
            _exit_edit_mode()

        def _exit_edit_mode():
            _editing_orig[0] = None
            edit_frm.grid_remove()
            btn_save.pack_forget()
            btn_cancel.pack_forget()
            btn_add.pack(side="left", padx=(0, 4))
            btn_edit.pack(side="left", padx=4)
            btn_remove.pack(side="left", padx=4)
            btn_close.pack(side="left", padx=4)

        def _add():
            dlg = tk.Toplevel(vwin)
            dlg.title("Eintrag hinzufügen")
            _center_on_target(dlg, 320, 120)
            dlg.resizable(False, False)
            dlg.attributes("-topmost", True)
            df = ttk.Frame(dlg, padding=10)
            df.pack(fill="both", expand=True)
            ttk.Label(df, text="Erkannt als:").grid(
                row=0, column=0, sticky="e", padx=(0, 6)
            )
            orig_var = tk.StringVar()
            ttk.Entry(df, textvariable=orig_var, width=22).grid(
                row=0, column=1, sticky="ew"
            )
            ttk.Label(df, text="Ersatz:").grid(
                row=1, column=0, sticky="e", padx=(0, 6), pady=(6, 0)
            )
            corr_var = tk.StringVar()
            ttk.Entry(df, textvariable=corr_var, width=22).grid(
                row=1, column=1, sticky="ew", pady=(6, 0)
            )
            ttk.Label(
                df, text="\\n = Zeilenumbruch, \\t = Tab", foreground="gray"
            ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(2, 0))
            df.columnconfigure(1, weight=1)

            def _ok():
                o = orig_var.get().strip()
                c = _unesc(corr_var.get())
                if o and c.strip(" "):
                    self.app.vocab.add(o, c)
                    _refresh()
                    dlg.destroy()

            ttk.Button(df, text="OK", command=_ok).grid(
                row=3, column=0, columnspan=2, pady=(10, 0)
            )

        def _remove():
            sel = tree.selection()
            if not sel:
                return
            orig = tree.item(sel[0])["values"][0]
            self.app.vocab.remove(str(orig))
            _refresh()

        def _on_vocab_destroy(e):
            if e.widget is not vwin:
                return
            self._vocab_win = None

        vwin.bind("<Destroy>", _on_vocab_destroy)

        # Normal-Modus-Buttons
        btn_add = ttk.Button(btns, text="Hinzufügen", command=_add)
        btn_add.pack(side="left", padx=(0, 4))
        btn_edit = ttk.Button(btns, text="Editieren", command=_enter_edit_mode)
        btn_edit.pack(side="left", padx=4)
        btn_remove = ttk.Button(btns, text="Entfernen", command=_remove)
        btn_remove.pack(side="left", padx=4)
        btn_close = ttk.Button(btns, text="Schließen", command=vwin.destroy)
        btn_close.pack(side="left", padx=4)

        # Edit-Modus-Buttons (zunächst unsichtbar)
        btn_save = ttk.Button(btns, text="Speichern", command=_save_edit)
        btn_cancel = ttk.Button(btns, text="Abbrechen", command=_exit_edit_mode)

    def open_transcription_settings(self):
        if not self.win or not self.win.winfo_exists():
            return
        if (
            hasattr(self, "_whisper_win")
            and self._whisper_win
            and self._whisper_win.winfo_exists()
        ):
            self._whisper_win.lift()
            return
        # Andere Unterfenster schließen
        for attr in ("_llm_win", "_vocab_win"):
            w = getattr(self, attr, None)
            if w and w.winfo_exists():
                w.destroy()

        lang = (
            self.ui_lang_var.get()
            if hasattr(self, "ui_lang_var")
            else load_config().get("ui_language", "de")
        )
        tr = TRANSLATIONS.get(lang, TRANSLATIONS["de"])

        twin = tk.Toplevel(self.win)
        self._whisper_win = twin
        self._dialog_parent = twin
        twin.title(tr["srv_frame"])
        _center_on_target(twin, 500, 390)
        twin.resizable(False, True)
        twin.attributes("-topmost", True)

        frm = ttk.Frame(twin, padding=12)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(1, weight=1)

        LBL = {"sticky": "e", "padx": (0, 8), "pady": 3}
        INP = {"sticky": "ew", "pady": 3}

        ttk.Label(frm, text=tr["provider"]).grid(row=0, column=0, **LBL)
        ttk.Combobox(
            frm,
            textvariable=self.whisper_provider_var,
            values=["lokal", "Openrouter", "Groq"],
            state="readonly",
        ).grid(row=0, column=1, **INP)

        _lbl_token = ttk.Label(frm, text=tr["url"])
        _lbl_token.grid(row=1, column=0, **LBL)
        _e_url = ttk.Entry(frm, textvariable=self.url_var)
        _e_url.grid(row=1, column=1, **INP)

        ttk.Label(frm, text=tr["port"]).grid(row=2, column=0, **LBL)
        _e_port = ttk.Entry(frm, textvariable=self.port_var, width=8)
        _e_port.grid(row=2, column=1, sticky="w", pady=3)

        ttk.Label(frm, text=tr["transcription_endpoint"]).grid(row=3, column=0, **LBL)
        _e_endpoint = ttk.Entry(frm, textvariable=self.endpoint_var)
        _e_endpoint.grid(row=3, column=1, **INP)

        ttk.Label(frm, text=tr["health_endpoint"]).grid(row=4, column=0, **LBL)
        _e_health = ttk.Entry(frm, textvariable=self.health_var)
        _e_health.grid(row=4, column=1, **INP)

        _lbl_tok = ttk.Label(frm, text=tr["token"])
        _lbl_tok.grid(row=5, column=0, **LBL)
        ttk.Entry(frm, textvariable=self.whisper_token_var, show="*").grid(
            row=5, column=1, **INP
        )

        ttk.Label(frm, text=tr["model_whisper"]).grid(row=6, column=0, **LBL)
        _e_model = ttk.Entry(frm, textvariable=self.whisper_model_var)
        _e_model.grid(row=6, column=1, **INP)

        def _update_fields(*_):
            is_local = self.whisper_provider_var.get() == "lokal"
            for w in (_e_url, _e_port, _e_endpoint, _e_health):
                w.configure(state="normal" if is_local else "disabled")
            _e_model.configure(state="disabled" if is_local else "normal")
            _btn_health.configure(state="normal" if is_local else "disabled")
            _lbl_tok.configure(foreground="red" if not is_local else "")

        _trace_id = self.whisper_provider_var.trace_add("write", _update_fields)

        def _on_twin_destroy(e):
            if e.widget is not twin:
                return
            self._dialog_parent = None
            try:
                self.whisper_provider_var.trace_remove("write", _trace_id)
            except Exception:
                pass

        twin.bind("<Destroy>", _on_twin_destroy)

        # ── Buttons ──────────────────────────────────────────
        btn_frm = ttk.Frame(frm)
        btn_frm.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        _btn_health = ttk.Button(
            btn_frm, text=tr["btn_health"], command=self.test_health
        )
        _btn_health.pack(side="left", padx=(0, 4))
        ttk.Button(
            btn_frm, text=tr["btn_whisper_test"], command=self.test_whisper
        ).pack(side="left", padx=4)

        def _save_whisper():
            cfg = load_config()
            cfg["whisper_url"] = self.url_var.get().strip()
            port_str = self.port_var.get().strip()
            cfg["port"] = (
                int(port_str) if port_str.isdigit() and int(port_str) > 0 else None
            )
            cfg["whisper_endpoint"] = self.endpoint_var.get().strip()
            cfg["health_endpoint"] = self.health_var.get().strip()
            cfg["whisper_token"] = self.whisper_token_var.get().strip()
            cfg["whisper_model"] = self.whisper_model_var.get().strip()
            cfg["whisper_provider"] = self.whisper_provider_var.get()
            save_config(cfg)
            self.app.reload_config()
            messagebox.showinfo(tr["srv_frame"], tr["msg_saved_body"], parent=twin)

        ttk.Button(btn_frm, text=tr["btn_save"], command=_save_whisper).pack(
            side="left", padx=4
        )
        ttk.Button(btn_frm, text=tr["btn_close"], command=twin.destroy).pack(
            side="left", padx=4
        )

        _update_fields()

    def open_llm_settings(self):
        if not self.win or not self.win.winfo_exists():
            return
        if hasattr(self, "_llm_win") and self._llm_win and self._llm_win.winfo_exists():
            self._llm_win.lift()
            return
        # Andere Unterfenster schließen
        for attr in ("_whisper_win", "_vocab_win"):
            w = getattr(self, attr, None)
            if w and w.winfo_exists():
                w.destroy()

        lang = (
            self.ui_lang_var.get()
            if hasattr(self, "ui_lang_var")
            else load_config().get("ui_language", "de")
        )
        tr = TRANSLATIONS.get(lang, TRANSLATIONS["de"])

        lwin = tk.Toplevel(self.win)
        self._llm_win = lwin
        self._dialog_parent = lwin
        lwin.title(tr["llm_frame"])
        _center_on_target(lwin, 580, 660)
        lwin.resizable(False, True)
        lwin.attributes("-topmost", True)

        # Scrollable content
        _canvas = tk.Canvas(lwin, highlightthickness=0)
        _sb = ttk.Scrollbar(lwin, orient="vertical", command=_canvas.yview)
        _canvas.configure(yscrollcommand=_sb.set)
        _sb.pack(side="right", fill="y")
        _canvas.pack(side="left", fill="both", expand=True)
        outer = ttk.Frame(_canvas, padding=12)
        _fid = _canvas.create_window((0, 0), window=outer, anchor="nw")
        outer.bind(
            "<Configure>", lambda e: _canvas.configure(scrollregion=_canvas.bbox("all"))
        )
        _canvas.bind("<Configure>", lambda e: _canvas.itemconfig(_fid, width=e.width))
        _canvas.bind_all(
            "<MouseWheel>",
            lambda e: _canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"),
        )
        lwin.bind("<Destroy>", lambda e: _canvas.unbind_all("<MouseWheel>"))
        outer.columnconfigure(0, weight=1)

        LBL = {"sticky": "e", "padx": (0, 8), "pady": 3}
        INP = {"sticky": "ew", "pady": 3}

        # ── LLM-Verbindung ────────────────────────────────────
        llm_frm = ttk.LabelFrame(outer, text=f" {tr['llm_frame']} ", padding=(10, 6))
        llm_frm.pack(fill="x", pady=(0, 8))
        llm_frm.columnconfigure(1, weight=1)

        ttk.Checkbutton(
            llm_frm, text=tr["llm_enable"], variable=self.llm_enabled_var
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=3)
        ttk.Label(llm_frm, text=tr["provider"]).grid(row=1, column=0, **LBL)
        ttk.Combobox(
            llm_frm,
            textvariable=self.llm_provider_var,
            values=["Ollama", "Openrouter", "Groq"],
            state="readonly",
        ).grid(row=1, column=1, **INP)

        ttk.Label(llm_frm, text=tr["url"]).grid(row=2, column=0, **LBL)
        _e_url = ttk.Entry(llm_frm, textvariable=self.llm_url_var)
        _e_url.grid(row=2, column=1, **INP)

        ttk.Label(llm_frm, text=tr["port"]).grid(row=3, column=0, **LBL)
        _e_port = ttk.Entry(llm_frm, textvariable=self.llm_port_var, width=8)
        _e_port.grid(row=3, column=1, sticky="w", pady=3)

        _lbl_tok = ttk.Label(llm_frm, text=tr["token"])
        _lbl_tok.grid(row=4, column=0, **LBL)
        ttk.Entry(llm_frm, textvariable=self.llm_token_var, show="*").grid(
            row=4, column=1, **INP
        )

        ttk.Label(llm_frm, text=tr["model"]).grid(row=5, column=0, **LBL)
        self.llm_model_combo = ttk.Combobox(
            llm_frm, textvariable=self.llm_model_var, state="normal"
        )
        self.llm_model_combo.grid(row=5, column=1, **INP)

        def _refresh_models(*_):
            def _fetch():
                provider = self.llm_provider_var.get()
                token = self.llm_token_var.get().strip()
                try:
                    if provider == "Ollama":
                        base = _build_base_url(
                            self.llm_url_var.get().strip(),
                            self.llm_port_var.get().strip(),
                        )
                        url = base.rstrip("/") + "/api/tags"
                        resp = requests.get(url, timeout=5)
                        resp.raise_for_status()
                        names = sorted(
                            [m["name"] for m in resp.json().get("models", [])],
                            key=lambda n: n.rsplit("/", 1)[-1].lower(),
                        )
                    elif provider == "Openrouter":
                        url = "https://openrouter.ai/api/v1/models"
                        headers = {"Authorization": f"Bearer {token}"} if token else {}
                        resp = requests.get(url, timeout=10, headers=headers)
                        resp.raise_for_status()
                        names = sorted(
                            [m["id"] for m in resp.json().get("data", [])],
                            key=lambda n: n.rsplit("/", 1)[-1].lower(),
                        )
                    elif provider == "Groq":
                        url = "https://api.groq.com/openai/v1/models"
                        headers = {"Authorization": f"Bearer {token}"} if token else {}
                        resp = requests.get(url, timeout=10, headers=headers)
                        resp.raise_for_status()
                        names = sorted(
                            [m["id"] for m in resp.json().get("data", [])],
                            key=str.lower,
                        )
                    else:
                        names = []
                except Exception:
                    names = []
                if lwin.winfo_exists():
                    lwin.after(0, lambda: self.llm_model_combo.configure(values=names))

            threading.Thread(target=_fetch, daemon=True).start()

        ttk.Button(llm_frm, text="\u21bb", width=3, command=_refresh_models).grid(
            row=5, column=2, padx=(4, 0), pady=3
        )

        def _update_llm_fields(*_):
            is_ollama = self.llm_provider_var.get() == "Ollama"
            for w in (_e_url, _e_port):
                w.configure(state="normal" if is_ollama else "disabled")
            _lbl_tok.configure(foreground="red" if not is_ollama else "")
            _refresh_models()

        _trace_id = self.llm_provider_var.trace_add("write", _update_llm_fields)

        def _on_lwin_destroy(e):
            if e.widget is not lwin:
                return
            self._dialog_parent = None
            try:
                self.llm_provider_var.trace_remove("write", _trace_id)
            except Exception:
                pass

        lwin.bind("<Destroy>", _on_lwin_destroy)

        _update_llm_fields()

        # ── System-Prompt ─────────────────────────────────────
        prompt_frm = ttk.LabelFrame(outer, text=" System-Prompt ", padding=(10, 6))
        prompt_frm.pack(fill="x", pady=(0, 8))
        prompt_frm.columnconfigure(0, weight=1)

        txt_outer = ttk.Frame(prompt_frm)
        txt_outer.pack(fill="x")
        txt_outer.columnconfigure(0, weight=1)
        txt = tk.Text(txt_outer, wrap="word", width=62, height=12, undo=True)
        txt.grid(row=0, column=0, sticky="ew")
        vsb = ttk.Scrollbar(txt_outer, orient="vertical", command=txt.yview)
        vsb.grid(row=0, column=1, sticky="ns")
        txt.configure(yscrollcommand=vsb.set)
        txt.insert("1.0", load_system_prompt())

        _prompt_btn_frm = ttk.Frame(prompt_frm)
        _prompt_btn_frm.pack(anchor="e", pady=(4, 0))

        def _reset_prompt_only():
            if messagebox.askyesno(
                tr["btn_prompt_factory"],
                tr["msg_prompt_factory_confirm"],
                parent=lwin,
            ):
                txt.delete("1.0", "end")
                txt.insert("1.0", _DEFAULT_SYSTEM_PROMPT)

        ttk.Button(
            _prompt_btn_frm, text=tr["btn_prompt_factory"], command=_reset_prompt_only
        ).pack(side="right")

        # ── Modell-Parameter ──────────────────────────────────
        params_frm = ttk.LabelFrame(outer, text=" Modell-Parameter ", padding=(8, 4))
        params_frm.pack(fill="x", pady=(0, 8))
        params_frm.columnconfigure(1, weight=1)
        params_frm.columnconfigure(3, weight=1)

        cfg = load_config()
        temp_var = tk.StringVar(value=str(cfg.get("temperature", 0)))
        top_p_var = tk.StringVar(value=str(cfg.get("top_p", 1)))
        max_tokens_var = tk.StringVar(value=str(cfg.get("max_tokens", 220)))
        num_ctx_var = tk.StringVar(value=str(cfg.get("num_ctx", 1024)))

        ttk.Label(params_frm, text="Temperature").grid(
            row=0, column=0, sticky="e", padx=(0, 6), pady=2
        )
        _f_temp = ttk.Frame(params_frm)
        _f_temp.grid(row=0, column=1, sticky="w", pady=2)
        ttk.Entry(_f_temp, textvariable=temp_var, width=8).pack(side="left")
        ttk.Label(
            _f_temp,
            text=f"(Standard: {DEFAULT_CONFIG['temperature']})",
            foreground="gray",
        ).pack(side="left", padx=(4, 0))

        ttk.Label(params_frm, text="Top-p").grid(
            row=0, column=2, sticky="e", padx=(12, 6), pady=2
        )
        _f_top_p = ttk.Frame(params_frm)
        _f_top_p.grid(row=0, column=3, sticky="w", pady=2)
        ttk.Entry(_f_top_p, textvariable=top_p_var, width=8).pack(side="left")
        ttk.Label(
            _f_top_p,
            text=f"(Standard: {DEFAULT_CONFIG['top_p']})",
            foreground="gray",
        ).pack(side="left", padx=(4, 0))

        ttk.Label(params_frm, text="Max Tokens").grid(
            row=1, column=0, sticky="e", padx=(0, 6), pady=2
        )
        _f_max_tokens = ttk.Frame(params_frm)
        _f_max_tokens.grid(row=1, column=1, sticky="w", pady=2)
        ttk.Entry(_f_max_tokens, textvariable=max_tokens_var, width=8).pack(side="left")
        ttk.Label(
            _f_max_tokens,
            text=f"(Standard: {DEFAULT_CONFIG['max_tokens']})",
            foreground="gray",
        ).pack(side="left", padx=(4, 0))

        ttk.Label(params_frm, text="Context (num_ctx)").grid(
            row=1, column=2, sticky="e", padx=(12, 6), pady=2
        )
        _f_num_ctx = ttk.Frame(params_frm)
        _f_num_ctx.grid(row=1, column=3, sticky="w", pady=2)
        ttk.Entry(_f_num_ctx, textvariable=num_ctx_var, width=8).pack(side="left")
        ttk.Label(
            _f_num_ctx,
            text=f"(Standard: {DEFAULT_CONFIG['num_ctx']})",
            foreground="gray",
        ).pack(side="left", padx=(4, 0))

        # ── Buttons ───────────────────────────────────────────
        btn_frm = ttk.Frame(outer)
        btn_frm.pack(fill="x", pady=(4, 0))

        def _save_llm():
            save_system_prompt(txt.get("1.0", "end-1c"))
            c = load_config()
            c["correction_enabled"] = bool(self.llm_enabled_var.get())
            c["llm_provider"] = self.llm_provider_var.get()
            c["correction_url"] = self.llm_url_var.get().strip()
            llm_port_str = self.llm_port_var.get().strip()
            c["correction_port"] = (
                int(llm_port_str)
                if llm_port_str.isdigit() and int(llm_port_str) > 0
                else None
            )
            c["correction_model"] = self.llm_model_var.get().strip()
            c["correction_token"] = self.llm_token_var.get().strip()
            try:
                c["temperature"] = float(temp_var.get())
            except ValueError:
                pass
            try:
                c["top_p"] = float(top_p_var.get())
            except ValueError:
                pass
            try:
                c["max_tokens"] = int(max_tokens_var.get())
                c["num_predict"] = c["max_tokens"]
            except ValueError:
                pass
            try:
                c["num_ctx"] = int(num_ctx_var.get())
            except ValueError:
                pass
            save_config(c)
            self.app.reload_config()
            messagebox.showinfo(tr["llm_frame"], tr["msg_saved_body"], parent=lwin)

        def _reset_prompt():
            if messagebox.askyesno(
                "Standard wiederherstellen",
                "System-Prompt und Parameter auf Standardwerte zurücksetzen?",
                parent=lwin,
            ):
                txt.delete("1.0", "end")
                txt.insert("1.0", _DEFAULT_SYSTEM_PROMPT)
                temp_var.set(str(DEFAULT_CONFIG["temperature"]))
                top_p_var.set(str(DEFAULT_CONFIG["top_p"]))
                max_tokens_var.set(str(DEFAULT_CONFIG["max_tokens"]))
                num_ctx_var.set(str(DEFAULT_CONFIG["num_ctx"]))

        ttk.Button(btn_frm, text=tr["btn_llm_test"], command=self.test_llm).pack(
            side="left", padx=(0, 4)
        )
        ttk.Button(btn_frm, text=tr["btn_save"], command=_save_llm).pack(
            side="left", padx=4
        )
        ttk.Button(
            btn_frm, text="Standard wiederherstellen", command=_reset_prompt
        ).pack(side="left", padx=4)
        ttk.Button(btn_frm, text=tr["btn_close"], command=lwin.destroy).pack(
            side="left", padx=4
        )

    # Keep old name as alias for backward compatibility
    def open_prompt_editor(self):
        self.open_llm_settings()

    def test_microphone(self):
        parent = self._parent_win()
        if self._testing:
            return
        self._set_testing(True)
        try:
            device_id = self.selected_device_id()
            samplerate = int(self.rate_var.get())
            channels = int(self.channels_var.get())
            sd.check_input_settings(
                device=device_id, samplerate=samplerate, channels=channels
            )
        except Exception as e:
            self._set_testing(False)
            messagebox.showerror(
                self._tr()["msg_mic_fail_title"], str(e), parent=parent
            )
            return

        frames: list = []
        rms_box = [0.0]
        lock = threading.Lock()

        def _cb(indata, n_frames, time_info, status):
            try:
                with lock:
                    frames.append(indata.copy())
                    rms_box[0] = float(np.sqrt(np.mean(indata**2)))
            except BaseException:
                pass

        popup = _MicLevelPopup(
            self.app.overlay.root, llm_enabled=self.app.config.correction_enabled
        )
        stream = sd.InputStream(
            device=device_id,
            samplerate=samplerate,
            channels=channels,
            dtype="float32",
            callback=_cb,
            blocksize=int(samplerate * 0.05),
        )
        stream.start()
        deadline = time.time() + 3.0

        def _poll():
            with lock:
                popup.set_rms(rms_box[0])
            if time.time() < deadline:
                self.app.overlay.root.after(50, _poll)
            else:
                stream.stop()
                stream.close()
                popup.close()
                self._set_testing(False)
                with lock:
                    audio = (
                        np.concatenate(frames, axis=0)
                        if frames
                        else np.zeros((1, channels))
                    )
                peak = float(np.max(np.abs(audio)))
                self.app.overlay.set_text(f"\u2705 Pegel: {peak:.3f}")
                self.app.overlay.root.after(2000, self.app.overlay.hide)
                if peak < 0.01:
                    tr = self._tr()
                    messagebox.showwarning(
                        tr["msg_mic_title"],
                        f"{tr['msg_mic_low_level']}: {peak:.3f}",
                        parent=parent,
                    )
                else:
                    tr = self._tr()
                    messagebox.showinfo(
                        tr["msg_mic_title"],
                        f"{tr['msg_mic_ok']}: {peak:.3f}",
                        parent=parent,
                    )

        self.app.overlay.root.after(50, _poll)

    def test_health(self):
        parent = self._parent_win()
        if self._testing:
            return
        self._set_testing(True)
        try:
            base = _build_base_url(
                self.url_var.get().strip(), self.port_var.get().strip()
            )
            url = base + "/" + self.health_var.get().strip().lstrip("/")
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            messagebox.showinfo(
                "Health Check", f"OK (HTTP {response.status_code})", parent=parent
            )
        except Exception as e:
            messagebox.showerror(
                self._tr()["msg_health_fail_title"], str(e), parent=parent
            )
        finally:
            self._set_testing(False)

    def test_whisper(self):
        parent = self._parent_win()
        if self._testing:
            return
        if (
            self.whisper_provider_var.get() != "lokal"
            and not self.whisper_token_var.get().strip()
        ):
            return
        self._set_testing(True)
        try:
            device_id = self.selected_device_id()
            samplerate = int(self.rate_var.get())
            channels = int(self.channels_var.get())
            sd.check_input_settings(
                device=device_id, samplerate=samplerate, channels=channels
            )
        except Exception as e:
            self._set_testing(False)
            messagebox.showerror(
                self._tr()["msg_whisper_fail_title"], str(e), parent=parent
            )
            return

        frames: list = []
        rms_box = [0.0]
        lock = threading.Lock()

        def _cb(indata, n_frames, time_info, status):
            try:
                with lock:
                    frames.append(indata.copy())
                    rms_box[0] = float(np.sqrt(np.mean(indata**2)))
            except BaseException:
                pass

        popup = _MicLevelPopup(
            self.app.overlay.root, llm_enabled=self.app.config.correction_enabled
        )
        stream = sd.InputStream(
            device=device_id,
            samplerate=samplerate,
            channels=channels,
            dtype="float32",
            callback=_cb,
            blocksize=int(samplerate * 0.05),
        )
        stream.start()
        deadline = time.time() + 3.0

        def _poll_rec():
            with lock:
                popup.set_rms(rms_box[0])
            if time.time() < deadline:
                self.app.overlay.root.after(50, _poll_rec)
            else:
                stream.stop()
                stream.close()
                with lock:
                    audio = (
                        np.concatenate(frames, axis=0)
                        if frames
                        else np.zeros((1, channels))
                    )
                _start_transcribe(audio)

        def _start_transcribe(audio):
            test_path = BASE_DIR / "mic_test.wav"
            try:
                sf.write(str(test_path), audio, samplerate)
            except Exception as e:
                self._set_testing(False)
                messagebox.showerror(
                    self._tr()["msg_whisper_fail_title"], str(e), parent=parent
                )
                return
            temp_cfg = Config()
            temp_cfg.whisper_provider = self.whisper_provider_var.get()
            temp_cfg.whisper_url = self.url_var.get().strip()
            temp_cfg.port = self.port_var.get().strip() or None
            temp_cfg.whisper_endpoint = self.endpoint_var.get().strip()
            temp_cfg.language = self.lang_var.get().strip()
            temp_cfg.response_format = "text"
            temp_cfg.whisper_token = self.whisper_token_var.get().strip()
            temp_cfg.whisper_model = self.whisper_model_var.get().strip()
            temp_cfg.proxy = self.proxy_var.get().strip()

            result_box = [None]

            def _run():
                try:
                    result_box[0] = WhisperClient(temp_cfg).transcribe(test_path)
                except Exception as exc:
                    result_box[0] = exc

            threading.Thread(target=_run, daemon=True).start()

            dot_count = [1]
            popup.set_rms(0.0)
            popup.expand_for_dots()

            def _poll_transcribe():
                if result_box[0] is None:
                    dot_count[0] = dot_count[0] % 3 + 1
                    popup.show_dots(dot_count[0])
                    self.app.overlay.root.after(100, _poll_transcribe)
                else:
                    popup.close()
                    self._set_testing(False)
                    try:
                        test_path.unlink()
                    except Exception:
                        pass
                    if isinstance(result_box[0], Exception):
                        tr = self._tr()
                        messagebox.showerror(
                            tr["msg_whisper_fail_title"],
                            str(result_box[0]),
                            parent=parent,
                        )
                    else:
                        tr = self._tr()
                        messagebox.showinfo(
                            tr["msg_whisper_title"],
                            result_box[0] or tr["msg_whisper_no_text"],
                            parent=parent,
                        )

            self.app.overlay.root.after(100, _poll_transcribe)

        self.app.overlay.root.after(50, _poll_rec)

    def test_llm(self):
        parent = self._parent_win()
        if self._testing:
            return
        if (
            self.llm_provider_var.get() != "Ollama"
            and not self.llm_token_var.get().strip()
        ):
            return
        url_str = self.llm_url_var.get().strip()
        port_str = self.llm_port_var.get().strip()
        model = self.llm_model_var.get().strip()
        if not url_str or not model:
            tr = self._tr()
            messagebox.showwarning(
                tr["msg_llm_test_title"], tr["msg_llm_test_missing"], parent=parent
            )
            return
        self._set_testing(True)
        result_box = [None]
        tr = self._tr()

        def _run():
            try:
                temp_cfg = Config()
                temp_cfg.correction_enabled = True
                temp_cfg.llm_provider = self.llm_provider_var.get()
                temp_cfg.correction_url = url_str
                temp_cfg.correction_port = int(port_str) if port_str.isdigit() else None
                temp_cfg.correction_model = model
                temp_cfg.correction_token = self.llm_token_var.get().strip()
                temp_cfg.system_prompt = ""
                temp_cfg.proxy = self.proxy_var.get().strip()
                result = LLMCorrector(temp_cfg).probe(tr["llm_probe_prompt"])
                if not result:
                    raise ValueError(tr["msg_llm_empty_response"])
                result_box[0] = result
            except Exception as exc:
                result_box[0] = exc

        popup = _LLMPopup(parent)
        threading.Thread(target=_run, daemon=True).start()

        def _poll():
            if result_box[0] is None:
                parent.after(200, _poll)
            elif isinstance(result_box[0], Exception):
                popup.close()
                self._set_testing(False)
                messagebox.showerror(
                    self._tr()["msg_llm_fail_title"],
                    str(result_box[0]),
                    parent=parent,
                )
            else:
                popup.close()
                self._set_testing(False)
                tr = self._tr()
                messagebox.showinfo(
                    tr["msg_llm_title"],
                    f"{tr['msg_llm_result']}: {result_box[0]}",
                    parent=parent,
                )

        parent.after(200, _poll)
