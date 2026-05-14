import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

import numpy as np
import requests
import sounddevice as sd
import soundfile as sf

from config import (
    BASE_DIR,
    DEFAULT_CONFIG,
    Config,
    _build_base_url,
    load_config,
    save_config,
)
from ui.popups import _LLMPopup, _MicLevelPopup
from ui.utils import _center_on_target
from whisper_client import WhisperClient


class SettingsWindow:
    def __init__(self, app):
        self.app = app
        self.win = None

    def open(self):
        if self.win and self.win.winfo_exists():
            self.win.lift()
            return

        cfg = load_config()

        self.win = tk.Toplevel(self.app.overlay.root)
        self.win.title("EuroWisprFlow Einstellungen")
        _center_on_target(self.win, 580, 780)
        self.win.resizable(False, True)
        self.win.attributes("-topmost", True)

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
        self.llm_token_var = tk.StringVar(value=cfg.get("correction_token", ""))

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

        # ── Server ────────────────────────────────────────────
        srv = ttk.LabelFrame(frm, text=" Server ", padding=(10, 6))
        srv.pack(fill="x", pady=(0, 8))
        srv.columnconfigure(1, weight=1)

        ttk.Label(srv, text="URL").grid(row=0, column=0, **LBL)
        ttk.Entry(srv, textvariable=self.url_var).grid(row=0, column=1, **INP)

        ttk.Label(srv, text="Port").grid(row=1, column=0, **LBL)
        ttk.Entry(srv, textvariable=self.port_var, width=8).grid(
            row=1, column=1, sticky="w", pady=3
        )

        ttk.Label(srv, text="Transkriptions-Endpoint").grid(row=2, column=0, **LBL)
        ttk.Entry(srv, textvariable=self.endpoint_var).grid(row=2, column=1, **INP)

        ttk.Label(srv, text="Health-Endpoint").grid(row=3, column=0, **LBL)
        ttk.Entry(srv, textvariable=self.health_var).grid(row=3, column=1, **INP)

        ttk.Label(srv, text="Token (Bearer)").grid(row=4, column=0, **LBL)
        ttk.Entry(srv, textvariable=self.whisper_token_var, show="*").grid(
            row=4, column=1, **INP
        )

        # ── Audio ─────────────────────────────────────────────
        aud = ttk.LabelFrame(frm, text=" Audio ", padding=(10, 6))
        aud.pack(fill="x", pady=(0, 8))
        aud.columnconfigure(1, weight=1)

        ttk.Label(aud, text="Sprache").grid(row=0, column=0, **LBL)
        ttk.Entry(aud, textvariable=self.lang_var, width=8).grid(
            row=0, column=1, sticky="w", pady=3
        )

        ttk.Label(aud, text="Mikrofon").grid(row=1, column=0, **LBL)
        ttk.Combobox(
            aud, textvariable=self.device_var, values=[x[1] for x in devices]
        ).grid(row=1, column=1, **INP)

        ttk.Label(aud, text="Sample Rate").grid(row=2, column=0, **LBL)
        ttk.Entry(aud, textvariable=self.rate_var, width=8).grid(
            row=2, column=1, sticky="w", pady=3
        )

        ttk.Label(aud, text="Kanäle").grid(row=3, column=0, **LBL)
        ttk.Entry(aud, textvariable=self.channels_var, width=4).grid(
            row=3, column=1, sticky="w", pady=3
        )

        # ── Allgemein ─────────────────────────────────────────
        gen = ttk.LabelFrame(frm, text=" Allgemein ", padding=(10, 6))
        gen.pack(fill="x", pady=(0, 8))
        gen.columnconfigure(1, weight=1)

        ttk.Label(gen, text="Hotkey").grid(row=0, column=0, **LBL)
        hk_frm = ttk.Frame(gen)
        hk_frm.grid(row=0, column=1, sticky="w", pady=3)
        ttk.Entry(hk_frm, textvariable=self.hotkey_var, width=22).pack(side="left")
        ttk.Label(hk_frm, text="  z. B. ctrl+linke windows", foreground="gray").pack(
            side="left"
        )

        ttk.Checkbutton(
            gen,
            text="Clipboard nach Einfügen wiederherstellen",
            variable=self.restore_var,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=3)

        ttk.Checkbutton(
            gen,
            text="Beim Start automatisch Admin-Rechte anfordern",
            variable=self.elevate_var,
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=3)

        # ── LLM-Korrektur ─────────────────────────────────────
        llm = ttk.LabelFrame(frm, text=" LLM-Korrektur (Ollama) ", padding=(10, 6))
        llm.pack(fill="x", pady=(0, 8))
        llm.columnconfigure(1, weight=1)

        ttk.Checkbutton(
            llm, text="LLM-Korrektur aktivieren", variable=self.llm_enabled_var
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=3)

        ttk.Label(llm, text="URL").grid(row=1, column=0, **LBL)
        ttk.Entry(llm, textvariable=self.llm_url_var).grid(row=1, column=1, **INP)

        ttk.Label(llm, text="Port").grid(row=2, column=0, **LBL)
        ttk.Entry(llm, textvariable=self.llm_port_var, width=8).grid(
            row=2, column=1, sticky="w", pady=3
        )

        ttk.Label(llm, text="Token (Bearer)").grid(row=3, column=0, **LBL)
        ttk.Entry(llm, textvariable=self.llm_token_var, show="*").grid(
            row=3, column=1, **INP
        )

        ttk.Label(llm, text="Modell").grid(row=4, column=0, **LBL)
        self.llm_model_combo = ttk.Combobox(
            llm, textvariable=self.llm_model_var, state="normal"
        )
        self.llm_model_combo.grid(row=4, column=1, **INP)

        def _refresh_models(*_):
            def _fetch():
                try:
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
                except Exception:
                    names = []
                self.win.after(0, lambda: self.llm_model_combo.configure(values=names))

            threading.Thread(target=_fetch, daemon=True).start()

        ttk.Button(llm, text="\u21bb", width=3, command=_refresh_models).grid(
            row=4, column=2, padx=(4, 0), pady=3
        )
        _refresh_models()

        # ── Buttons ───────────────────────────────────────────
        btns = ttk.Frame(frm)
        btns.pack(fill="x", pady=(4, 0))
        ttk.Button(btns, text="Mikrofon testen", command=self.test_microphone).pack(
            side="left", padx=(0, 4)
        )
        ttk.Button(btns, text="Health Check", command=self.test_health).pack(
            side="left", padx=4
        )
        ttk.Button(btns, text="Whisper testen", command=self.test_whisper).pack(
            side="left", padx=4
        )
        ttk.Button(btns, text="LLM testen", command=self.test_llm).pack(
            side="left", padx=4
        )

        btns2 = ttk.Frame(frm)
        btns2.pack(fill="x", pady=(6, 0))
        ttk.Button(
            btns2, text="Werkseinstellungen", command=self.reset_to_defaults
        ).pack(side="left", padx=(0, 4))
        ttk.Button(btns2, text="Speichern", command=self.save).pack(side="left", padx=4)
        ttk.Button(
            btns2, text="Vokabular verwalten", command=self.open_vocabulary
        ).pack(side="left", padx=4)
        ttk.Button(btns2, text="Schließen", command=self.win.destroy).pack(
            side="left", padx=4
        )

    def selected_device_id(self):
        label = self.device_var.get()
        for device_id, device_label in self.devices:
            if device_label == label:
                return device_id
        return None

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
        cfg["correction_token"] = self.llm_token_var.get().strip()

        save_config(cfg)
        self.app.reload_config()
        messagebox.showinfo(
            "Gespeichert",
            "Einstellungen gespeichert. Hotkey ist sofort aktualisiert.",
            parent=self.win,
        )

    def reset_to_defaults(self):
        if not messagebox.askyesno(
            "Werkseinstellungen",
            "Alle Einstellungen auf Standardwerte zurücksetzen?",
            parent=self.win,
        ):
            return

        save_config(DEFAULT_CONFIG)
        self.app.reload_config()

        self.url_var.set(DEFAULT_CONFIG["whisper_url"])
        default_port = DEFAULT_CONFIG.get("port", None)
        self.port_var.set(str(default_port) if default_port else "")
        self.endpoint_var.set(DEFAULT_CONFIG["whisper_endpoint"])
        self.health_var.set(DEFAULT_CONFIG["health_endpoint"])
        self.lang_var.set(DEFAULT_CONFIG["language"])
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

        messagebox.showinfo(
            "Werkseinstellungen", "Einstellungen wurden zurückgesetzt.", parent=self.win
        )

    def open_vocabulary(self):
        if not self.win or not self.win.winfo_exists():
            return
        vwin = tk.Toplevel(self.win)
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

        def _refresh():
            tree.delete(*tree.get_children())
            for orig, corr in sorted(self.app.vocab.all().items()):
                tree.insert("", "end", values=(orig, corr))

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
            edit_corr_var.set(str(corr))
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
            c = edit_corr_var.get().strip()
            if o and c:
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
            df.columnconfigure(1, weight=1)

            def _ok():
                o = orig_var.get().strip()
                c = corr_var.get().strip()
                if o and c:
                    self.app.vocab.add(o, c)
                    _refresh()
                    dlg.destroy()

            ttk.Button(df, text="OK", command=_ok).grid(
                row=2, column=0, columnspan=2, pady=(10, 0)
            )

        def _remove():
            sel = tree.selection()
            if not sel:
                return
            orig = tree.item(sel[0])["values"][0]
            self.app.vocab.remove(str(orig))
            _refresh()

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

    def test_microphone(self):
        try:
            device_id = self.selected_device_id()
            samplerate = int(self.rate_var.get())
            channels = int(self.channels_var.get())
            sd.check_input_settings(
                device=device_id, samplerate=samplerate, channels=channels
            )
        except Exception as e:
            messagebox.showerror("Mikrofontest fehlgeschlagen", str(e), parent=self.win)
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
                    messagebox.showwarning(
                        "Mikrofontest",
                        f"Sehr niedriger Pegel: {peak:.3f}",
                        parent=self.win,
                    )
                else:
                    messagebox.showinfo(
                        "Mikrofontest",
                        f"Mikrofon funktioniert. Pegel: {peak:.3f}",
                        parent=self.win,
                    )

        self.app.overlay.root.after(50, _poll)

    def test_health(self):
        try:
            base = _build_base_url(
                self.url_var.get().strip(), self.port_var.get().strip()
            )
            url = base + "/" + self.health_var.get().strip().lstrip("/")
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            messagebox.showinfo(
                "Health Check", f"OK (HTTP {response.status_code})", parent=self.win
            )
        except Exception as e:
            messagebox.showerror("Health Check fehlgeschlagen", str(e), parent=self.win)

    def test_whisper(self):
        try:
            device_id = self.selected_device_id()
            samplerate = int(self.rate_var.get())
            channels = int(self.channels_var.get())
            sd.check_input_settings(
                device=device_id, samplerate=samplerate, channels=channels
            )
        except Exception as e:
            messagebox.showerror("Whisper-Test fehlgeschlagen", str(e), parent=self.win)
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
                messagebox.showerror(
                    "Whisper-Test fehlgeschlagen", str(e), parent=self.win
                )
                return

            temp_cfg = Config()
            temp_cfg.whisper_url = self.url_var.get().strip()
            temp_cfg.port = self.port_var.get().strip() or None
            temp_cfg.whisper_endpoint = self.endpoint_var.get().strip()
            temp_cfg.language = self.lang_var.get().strip()
            temp_cfg.response_format = "text"

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
                    try:
                        test_path.unlink()
                    except Exception:
                        pass
                    if isinstance(result_box[0], Exception):
                        messagebox.showerror(
                            "Whisper-Test fehlgeschlagen",
                            str(result_box[0]),
                            parent=self.win,
                        )
                    else:
                        messagebox.showinfo(
                            "Whisper-Test",
                            result_box[0] or "Kein Text erkannt",
                            parent=self.win,
                        )

            self.app.overlay.root.after(100, _poll_transcribe)

        self.app.overlay.root.after(50, _poll_rec)

    def test_llm(self):
        url_str = self.llm_url_var.get().strip()
        port_str = self.llm_port_var.get().strip()
        model = self.llm_model_var.get().strip()
        if not url_str or not model:
            messagebox.showwarning(
                "LLM testen", "Bitte URL und Modell angeben.", parent=self.win
            )
            return
        result_box = [None]

        def _run():
            try:
                base = _build_base_url(url_str, port_str)
                url = base.rstrip("/") + "/api/generate"
                payload = {
                    "model": model,
                    "prompt": "Antworte mit: OK",
                    "stream": False,
                }
                resp = requests.post(url, json=payload, timeout=30)
                resp.raise_for_status()
                result_box[0] = resp.json().get("response", "").strip() or "OK"
            except Exception as exc:
                result_box[0] = exc

        popup = _LLMPopup(self.win)
        threading.Thread(target=_run, daemon=True).start()

        def _poll():
            if result_box[0] is None:
                self.win.after(200, _poll)
            elif isinstance(result_box[0], Exception):
                popup.close()
                messagebox.showerror(
                    "LLM-Test fehlgeschlagen", str(result_box[0]), parent=self.win
                )
            else:
                popup.close()
                messagebox.showinfo(
                    "LLM-Test", f"Antwort: {result_box[0]}", parent=self.win
                )

        self.win.after(200, _poll)
