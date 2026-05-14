import ctypes
import difflib
import json
import queue
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

import keyboard
import numpy as np
import pyperclip
import pystray
import requests
import sounddevice as sd
import soundfile as sf
from PIL import Image, ImageDraw

BASE_DIR = Path(__file__).parent
# In a PyInstaller onefile build sys.executable is the .exe itself;
# config.json must live next to it, not inside _MEIPASS.
if getattr(sys, "frozen", False):
    CONFIG_PATH = Path(sys.executable).parent / "config.json"
else:
    CONFIG_PATH = BASE_DIR / "config.json"

VOCAB_PATH = CONFIG_PATH.parent / "vocabulary.json"

_DEFAULT_LLM_PROMPT = "\n".join(
    [
        "Du bist ein extrem schneller Speech-to-Text Cleanup-Prozessor.",
        "",
        "AUFGABE:",
        "Korrigiere ausschließlich:",
        "",
        "Orthographie",
        "Zeichensetzung",
        "Groß-/Kleinschreibung",
        "offensichtliche Speech-to-Text Fehler",
        "deutsche Umlaute",
        "Satzstruktur bei Diktatfragmenten",
        "",
        "REGELN:",
        "",
        "KEINE neuen Informationen hinzufügen",
        "Bedeutung NICHT verändern",
        "KEINE Zusammenfassung",
        "KEINE Umformulierungen außer minimal notwendig",
        "Fachbegriffe erhalten",
        "Sprache automatisch erkennen (Deutsch/English)",
        "Ausgabe nur als finaler Text",
        "Kein Markdown",
        "Keine Erklärungen",
        "",
        "",
        "{{raw_text}}",
    ]
)


def _resource(filename: str) -> Path:
    """Resolve path to a bundled resource (works in PyInstaller onefile and dev)."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass) / filename
    return BASE_DIR / filename


DEFAULT_CONFIG = {
    "whisper_url": "http://10.4.190.16",
    "port": 8009,
    "whisper_token": "",
    "whisper_endpoint": "transcribe",
    "health_endpoint": "health",
    "language": "de",
    "response_format": "text",
    "sample_rate": 16000,
    "channels": 1,
    "input_device": None,
    "hotkey_keys": ["ctrl", "linke windows"],
    "restore_clipboard": True,
    "audio_filename": "recording.wav",
    "auto_elevate": True,
    "start_with_windows": True,
    "correction_enabled": True,
    "correction_url": "http://10.4.190.16",
    "correction_port": 11434,
    "correction_token": "",
    "correction_model": "hf.co/unsloth/Qwen3-4B-GGUF:Q4_K_XL",
    "temperature": 0,
    "top_p": 1,
    "num_predict": 220,
    "num_ctx": 1024,
    "repeat_penalty": 1.0,
    "system_prompt": _DEFAULT_LLM_PROMPT,
}


def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except BaseException:
        return False


def auto_elevate_if_needed(config):
    if not config.get("auto_elevate", False):
        return

    if is_admin():
        return

    exe = sys.executable
    args = " ".join([f'"{a}"' for a in sys.argv])
    ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, args, None, 1)
    sys.exit(0)


def load_config():
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(json.dumps(DEFAULT_CONFIG, indent=2), encoding="utf-8")

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    merged = DEFAULT_CONFIG.copy()
    merged.update(data)
    return merged


def save_config(data):
    CONFIG_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _build_base_url(url: str, port) -> str:
    """Combine base URL with port, omitting port if falsy or zero."""
    url = url.rstrip("/")
    try:
        p = int(port)
    except (TypeError, ValueError):
        p = 0
    if p > 0:
        return f"{url}:{p}"
    return url


def _target_monitor() -> tuple:
    """Return (left, top, right, bottom) of the target monitor.

    Selects monitors[n // 2] sorted by left coordinate:
    1 monitor → 0, 2 → 1 (right), 3 → 1 (middle), 4 → 2 (right of centre).
    """
    try:
        from ctypes import wintypes

        monitors: list = []

        def _cb(hmon, hdc, lprect, lparam):
            r = lprect.contents
            monitors.append((r.left, r.top, r.right, r.bottom))
            return 1

        PROC = ctypes.WINFUNCTYPE(
            ctypes.c_bool,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.POINTER(wintypes.RECT),
            ctypes.c_double,
        )
        ctypes.windll.user32.EnumDisplayMonitors(None, None, PROC(_cb), 0)
        if monitors:
            monitors.sort(key=lambda m: m[0])
            return monitors[len(monitors) // 2]
    except Exception:
        pass
    w = ctypes.windll.user32.GetSystemMetrics(0)
    h = ctypes.windll.user32.GetSystemMetrics(1)
    return (0, 0, w, h)


def _center_on_target(win: tk.Toplevel, w: int, h: int) -> None:
    """Position win (w×h) centered on the target monitor."""
    ml, mt, mr, mb = _target_monitor()
    x = ml + (mr - ml - w) // 2
    y = mt + (mb - mt - h) // 2
    win.geometry(f"{w}x{h}+{x}+{y}")


class Config:
    def __init__(self):
        self.reload()

    def reload(self):
        data = load_config()
        self.raw = data
        self.whisper_url = data["whisper_url"]
        self.port = data.get("port", None)
        self.whisper_token = data.get("whisper_token", "")
        self.whisper_endpoint = data.get("whisper_endpoint", "/transcribe")
        self.health_endpoint = data.get("health_endpoint", "/health")
        self.language = data["language"]
        self.response_format = data["response_format"]
        self.sample_rate = int(data["sample_rate"])
        self.channels = int(data["channels"])
        self.input_device = data.get("input_device", None)
        self.hotkey_keys = data["hotkey_keys"]
        self.restore_clipboard = bool(data["restore_clipboard"])
        self.audio_filename = data["audio_filename"]
        self.correction_enabled = bool(data.get("correction_enabled", True))
        self.correction_url = data.get("correction_url", "http://10.4.190.16")
        self.correction_port = data.get("correction_port", 11434)
        self.correction_token = data.get("correction_token", "")
        self.correction_model = data.get(
            "correction_model", "hf.co/unsloth/Qwen3-4B-GGUF:Q4_K_XL"
        )
        self.temperature = data.get("temperature", 0)
        self.top_p = data.get("top_p", 1)
        self.num_predict = data.get("num_predict", 220)
        self.num_ctx = data.get("num_ctx", 1024)
        self.repeat_penalty = data.get("repeat_penalty", 1.0)
        self.system_prompt = data.get("system_prompt", _DEFAULT_LLM_PROMPT)


class Overlay:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("EuroWisprFlow")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.92)

        self.label = tk.Label(
            self.root,
            text="Bereit",
            font=("Segoe UI", 18),
            bg="white",
            fg="#2a671b",
            padx=24,
            pady=14,
        )
        self.root.configure(bg="white")
        self.label.pack()

        icon_path = _resource("tray_icon.png")
        if icon_path.exists():
            try:
                img = tk.PhotoImage(file=str(icon_path))
                self.root.iconphoto(True, img)
            except Exception:
                pass

        self.root.withdraw()

    def show(self, text):
        self.label.config(text=text)
        self.root.update_idletasks()
        width = self.root.winfo_reqwidth()
        height = self.root.winfo_reqheight()
        ml, mt, mr, mb = _target_monitor()
        x = ml + (mr - ml - width) // 2
        y = mb - height - 60
        self.root.geometry(f"+{x}+{y}")
        self.root.deiconify()
        self.root.update()

    def set_text(self, text):
        self.label.config(text=text)
        self.root.update()

    def hide(self):
        self.root.withdraw()
        self.root.update()

    def loop(self):
        self.root.mainloop()


class Recorder:
    def __init__(self, config):
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


class WhisperClient:
    def __init__(self, config):
        self.config = config

    def transcribe(self, audio_path):
        with open(audio_path, "rb") as f:
            base = _build_base_url(self.config.whisper_url, self.config.port)
            headers = {}
            if self.config.whisper_token:
                headers["Authorization"] = f"Bearer {self.config.whisper_token}"
            response = requests.post(
                base + "/" + self.config.whisper_endpoint.lstrip("/"),
                files={"file": (audio_path.name, f, "audio/wav")},
                data={
                    "language": self.config.language,
                    "response_format": self.config.response_format,
                },
                timeout=600,
                headers=headers,
            )

        response.raise_for_status()

        if self.config.response_format == "text":
            return response.text.strip()

        return response.json().get("text", "").strip()


class LLMCorrector:
    """Sends transcribed text to a local LLM (Ollama /api/generate) for cleanup."""

    def __init__(self, config: Config) -> None:
        self.config = config

    def correct(self, text: str, vocab: "VocabularyManager") -> str:
        if not self.config.correction_enabled or not text.strip():
            return text
        try:
            base = _build_base_url(
                self.config.correction_url,
                self.config.correction_port,
            )
            url = base.rstrip("/") + "/api/generate"
            headers = {}
            if self.config.correction_token:
                headers["Authorization"] = f"Bearer {self.config.correction_token}"
            corr = vocab.all()
            dict_str = (
                "\n".join(f"  {k} \u2192 {v}" for k, v in sorted(corr.items()))
                if corr
                else "(leer)"
            )
            prompt = self.config.correction_system_prompt.replace(
                "{{dictionary}}", dict_str
            ).replace("{{raw_text}}", text)
            payload = {
                "model": self.config.correction_model,
                "prompt": prompt,
                "temperature": self.config.correction_temperature,
                "top_p": self.config.correction_top_p,
                "num_predict": self.config.num_predict,
                "num_ctx": self.config.num_ctx,
                "repeat_penalty": self.config.repeat_penalty,
                "stream": False,
            }
            resp = requests.post(url, json=payload, timeout=30, headers=headers)
            resp.raise_for_status()
            result = resp.json().get("response", "").strip()
            return result if result else text
        except Exception:
            return text


class TextInserter:
    def __init__(self, config):
        self.config = config

    def insert_text(self, text):
        if not text:
            return

        old_clipboard = None
        if self.config.restore_clipboard:
            try:
                old_clipboard = pyperclip.paste()
            except Exception:
                pass

        pyperclip.copy(text)
        time.sleep(0.08)
        keyboard.press_and_release("ctrl+v")
        time.sleep(0.15)

        if self.config.restore_clipboard and old_clipboard is not None:
            pyperclip.copy(old_clipboard)


class VocabularyManager:
    """Persists word-level correction pairs and applies them to transcription output."""

    _PUNCT = ".,!?;:\"'()[]{}\u2026\u2013\u2014-"

    def __init__(self) -> None:
        self._data: dict = {"corrections": {}}
        self.load()

    def load(self) -> None:
        if not VOCAB_PATH.exists():
            VOCAB_PATH.write_text(
                json.dumps({"corrections": {}}, indent=2), encoding="utf-8"
            )
        try:
            with open(VOCAB_PATH, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded.get("corrections"), dict):
                self._data = loaded
        except Exception:
            self._data = {"corrections": {}}

    def save(self) -> None:
        VOCAB_PATH.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def apply(self, text: str) -> str:
        if not text or not self._data["corrections"]:
            return text
        corrections = self._data["corrections"]
        tokens = text.split(" ")
        result = []
        for token in tokens:
            stripped = token.strip(self._PUNCT)
            prefix_len = len(token) - len(token.lstrip(self._PUNCT))
            suffix_len = len(token) - len(token.rstrip(self._PUNCT))
            prefix = token[:prefix_len]
            suffix = token[len(token) - suffix_len :] if suffix_len else ""
            key = stripped.lower()
            if key in corrections:
                result.append(prefix + corrections[key] + suffix)
            else:
                result.append(token)
        return " ".join(result)

    def add(self, original: str, corrected: str) -> None:
        key = original.strip().lower()
        if key and corrected.strip():
            self._data["corrections"][key] = corrected.strip()
            self.save()

    def remove(self, original: str) -> None:
        key = original.strip().lower()
        if key in self._data["corrections"]:
            del self._data["corrections"][key]
            self.save()

    def all(self) -> dict:
        return dict(self._data["corrections"])


class CorrectionTracker:
    """Watches for user corrections after text insertion and learns word replacements."""

    _WINDOW = 20.0  # seconds to watch after insert
    _IDLE = 3.0  # seconds of keyboard silence before finalising
    _MAX_N = 200  # max chars to snapshot via Shift+Left
    _PUNCT = ".,!?;:\"'()[]{}\u2026\u2013\u2014-"

    def __init__(self, vocab: VocabularyManager) -> None:
        self._vocab = vocab
        self._original: str = ""
        self._alive = False
        self._deadline: float = 0.0
        self._last_activity: float = 0.0
        self._kb_hook = None
        self._after_fn = None
        self._notify_fn = None
        self._baseline_ok = False

    def start(self, text: str, after_fn, notify_fn=None) -> None:
        self.stop()
        if not text.strip():
            return
        self._original = text
        self._alive = True
        self._baseline_ok = False
        self._deadline = time.time() + self._WINDOW
        self._last_activity = time.time()
        self._after_fn = after_fn
        self._notify_fn = notify_fn
        try:
            self._kb_hook = keyboard.on_release(self._on_key)
        except Exception:
            self._kb_hook = None
        after_fn(500, self._capture_baseline)

    def stop(self) -> None:
        self._alive = False
        if self._kb_hook is not None:
            try:
                keyboard.unhook(self._kb_hook)
            except Exception:
                pass
            self._kb_hook = None

    def _on_key(self, _event) -> None:
        self._last_activity = time.time()

    def _capture_snapshot(self, n: int) -> str:
        n = min(max(n, 0), self._MAX_N)
        if n == 0:
            return ""
        try:
            old = ""
            try:
                old = pyperclip.paste()
            except Exception:
                pass
            pyperclip.copy("")
            for _ in range(n):
                keyboard.send("shift+left")
            time.sleep(0.06)
            keyboard.send("ctrl+c")
            time.sleep(0.09)
            result = pyperclip.paste()
            keyboard.send("right")
            time.sleep(0.03)
            try:
                pyperclip.copy(old)
            except Exception:
                pass
            return result
        except Exception:
            return ""

    def _capture_baseline(self) -> None:
        if not self._alive:
            return

        def _bg() -> None:
            snapshot = self._capture_snapshot(len(self._original))
            if self._original in snapshot or snapshot == self._original:
                self._baseline_ok = True
            if self._alive and self._after_fn:
                self._after_fn(500, self._poll)

        threading.Thread(target=_bg, daemon=True).start()

    def _poll(self) -> None:
        if not self._alive:
            return
        if time.time() > self._deadline:
            self.stop()
            return
        if self._baseline_ok and (time.time() - self._last_activity) >= self._IDLE:
            self._alive = False
            if self._kb_hook is not None:
                try:
                    keyboard.unhook(self._kb_hook)
                except Exception:
                    pass
                self._kb_hook = None
            self._after_fn(0, self._finalize)
            return
        self._after_fn(500, self._poll)

    def _finalize(self) -> None:
        def _bg() -> None:
            n = min(len(self._original) + 30, self._MAX_N)
            after_snapshot = self._capture_snapshot(n)
            pairs = self._word_diff(self._original, after_snapshot)
            saved = 0
            for orig_word, new_word in pairs:
                self._vocab.add(orig_word, new_word)
                saved += 1
            if saved > 0 and self._notify_fn and self._after_fn:
                label = "Korrektur" if saved == 1 else "Korrekturen"
                msg = f"\U0001f4da {saved} {label} gespeichert"
                self._after_fn(0, lambda m=msg: self._notify_fn(m))

        threading.Thread(target=_bg, daemon=True).start()

    @staticmethod
    def _word_diff(original: str, corrected: str) -> list:
        orig_words = original.split()
        corr_words = corrected.split()
        _PUNCT = ".,!?;:\"'()[]{}\u2026\u2013\u2014-"
        matcher = difflib.SequenceMatcher(None, orig_words, corr_words, autojunk=False)
        pairs = []
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "replace" and (i2 - i1) == 1 and (j2 - j1) == 1:
                orig_w = orig_words[i1].strip(_PUNCT)
                corr_w = corr_words[j1].strip(_PUNCT)
                if orig_w and corr_w and orig_w.lower() != corr_w.lower():
                    pairs.append((orig_w, corr_w))
        return pairs


class _MicLevelPopup:
    """Animated waveform bar popup that reacts to microphone loudness."""

    _N = 10  # number of bars
    _BW = 3  # bar width (px)
    _BG = 2  # gap between bars (px)
    _MH = 15  # max bar height (px)
    _PX = 10  # horizontal padding
    _PY = 6  # vertical padding
    _D_R = 2  # dot radius (px)
    _D_GAP = 3  # gap between dots (px)
    _D_PAD = 5  # gap between bars and dots (px)
    _TRANS = "#fefefe"  # transparent corner sentinel

    def __init__(self, parent: tk.Misc, llm_enabled: bool = False) -> None:
        pill_bg = "#99cc99" if llm_enabled else "#ffffff"
        fg = "#006600"
        dot_hidden = pill_bg

        bars_w = self._N * (self._BW + self._BG) - self._BG
        dots_w = 3 * (self._D_R * 2) + 2 * self._D_GAP
        self._bars_only_w = self._PX + bars_w + self._PX
        self._full_w = self._PX + bars_w + self._D_PAD + dots_w + self._PX
        h = self._MH + self._PY * 2
        self._h = h
        self._pill_bg = pill_bg
        self._fg = fg
        self._dot_hidden = dot_hidden

        self.top = tk.Toplevel(parent)
        self.top.overrideredirect(True)
        self.top.attributes("-topmost", True)
        self.top.attributes("-alpha", 0.93)
        self.top.configure(bg=self._TRANS)
        self.top.attributes("-transparentcolor", self._TRANS)

        ml, mt, mr, mb = _target_monitor()
        self._mon = (ml, mt, mr, mb)
        w = self._bars_only_w
        self.top.geometry(f"{w}x{h}+{ml + (mr - ml - w) // 2}+{mb - h - 70}")

        self._cv = tk.Canvas(
            self.top, width=self._full_w, height=h, bg=self._TRANS, highlightthickness=0
        )
        self._cv.pack()

        # pill background (drawn first so bars/dots sit on top)
        self._pill = self._cv.create_rectangle(0, 0, w, h, fill=pill_bg, outline="")

        cy = h // 2
        self._cy = cy
        self._bars: list = []
        for i in range(self._N):
            x = self._PX + i * (self._BW + self._BG)
            bar = self._cv.create_rectangle(
                x, cy - 1, x + self._BW, cy + 1, fill=fg, outline=""
            )
            self._bars.append(bar)

        # 3 dots to the right of the bars (clipped until expand_for_dots() is called)
        dots_x0 = self._PX + bars_w + self._D_PAD
        self._dots: list = []
        for i in range(3):
            dx = dots_x0 + i * (self._D_R * 2 + self._D_GAP)
            dot = self._cv.create_oval(
                dx,
                cy - self._D_R,
                dx + self._D_R * 2,
                cy + self._D_R,
                fill=dot_hidden,
                outline="",
            )
            self._dots.append(dot)

        self._history: list = [0.0] * self._N
        self._rms: float = 0.0
        self._alive = True
        self.top.after(10, lambda: self._apply_rounded_region(self._bars_only_w))
        self.top.after(50, self._tick)

    def _apply_rounded_region(self, w: int) -> None:
        """Apply a pill-shaped (stadium) window clip region."""
        if not self.top.winfo_exists():
            return
        h = self._h
        try:
            hwnd = self.top.winfo_id()
            hrgn = ctypes.windll.gdi32.CreateRoundRectRgn(0, 0, w + 1, h + 1, h, h)
            ctypes.windll.user32.SetWindowRgn(hwnd, hrgn, True)
        except Exception:
            pass

    def set_rms(self, rms: float) -> None:
        self._rms = rms

    def show_dots(self, n: int) -> None:
        """Show n filled dots (0–3); rest invisible."""
        if not self.top.winfo_exists():
            return
        for i, dot in enumerate(self._dots):
            self._cv.itemconfig(dot, fill=self._fg if i < n else self._dot_hidden)

    def expand_for_dots(self) -> None:
        """Widen the window to reveal the dots area."""
        if not self.top.winfo_exists():
            return
        w = self._full_w
        ml, mt, mr, mb = self._mon
        x = ml + (mr - ml - w) // 2
        y = mb - self._h - 70
        self.top.geometry(f"{w}x{self._h}+{x}+{y}")
        self._cv.itemconfig(self._pill, fill=self._pill_bg)
        self._cv.coords(self._pill, 0, 0, w, self._h)
        self.top.after(10, lambda: self._apply_rounded_region(self._full_w))

    def _tick(self) -> None:
        if not self._alive or not self.top.winfo_exists():
            return
        self._history = self._history[1:] + [min(self._rms * 5.0, 1.0)]
        for bar, rel in zip(self._bars, self._history):
            bh = max(2, int(rel * self._MH))
            x0, _, x1, _ = self._cv.coords(bar)
            self._cv.coords(bar, x0, self._cy - bh // 2, x1, self._cy + bh // 2)
        self.top.after(50, self._tick)

    def close(self) -> None:
        self._alive = False
        if self.top.winfo_exists():
            self.top.destroy()


class _LLMPopup:
    """Small pill-shaped popup showing 'Anfrage gesendet' with animated dots."""

    _PX = 10
    _PY = 6
    _D_R = 3
    _D_GAP = 5
    _FONT = ("Segoe UI", 9)
    _TRANS = "#fefefe"

    def __init__(self, parent: tk.Misc) -> None:
        pill_bg = "#99cc99"  # LLM popup always shown when LLM is in use
        fg = "#006600"
        dot_hidden = pill_bg

        self._fg = fg
        self._dot_hidden = dot_hidden

        self.top = tk.Toplevel(parent)
        self.top.overrideredirect(True)
        self.top.attributes("-topmost", True)
        self.top.attributes("-alpha", 0.93)
        self.top.configure(bg=self._TRANS)
        self.top.attributes("-transparentcolor", self._TRANS)

        # Measure text width via a temporary label
        tmp = tk.Label(self.top, text="Anfrage gesendet", font=self._FONT)
        tmp.update_idletasks()
        tw = tmp.winfo_reqwidth()
        tmp.destroy()

        dots_w = 3 * (self._D_R * 2) + 2 * self._D_GAP
        w = self._PX + tw + self._D_GAP * 2 + dots_w + self._PX
        h = max(24, self._D_R * 2 + self._PY * 2 + 4)
        self._w = w
        self._h = h

        ml, mt, mr, mb = _target_monitor()
        x = ml + (mr - ml - w) // 2
        y = mb - h - 70
        self.top.geometry(f"{w}x{h}+{x}+{y}")

        self._cv = tk.Canvas(
            self.top, width=w, height=h, bg=self._TRANS, highlightthickness=0
        )
        self._cv.pack()

        # pill background
        self._cv.create_rectangle(0, 0, w, h, fill=pill_bg, outline="")

        cy = h // 2
        self._cv.create_text(
            self._PX,
            cy,
            anchor="w",
            text="Anfrage gesendet",
            font=self._FONT,
            fill=fg,
        )

        dots_x0 = self._PX + tw + self._D_GAP * 2
        self._dots: list = []
        for i in range(3):
            dx = dots_x0 + i * (self._D_R * 2 + self._D_GAP)
            dot = self._cv.create_oval(
                dx,
                cy - self._D_R,
                dx + self._D_R * 2,
                cy + self._D_R,
                fill=dot_hidden,
                outline="",
            )
            self._dots.append(dot)

        self._alive = True
        self._dot_count = 0
        self.top.after(10, self._apply_rounded)
        self.top.after(300, self._tick)

    def _apply_rounded(self) -> None:
        if not self.top.winfo_exists():
            return
        try:
            hwnd = self.top.winfo_id()
            h = self._h
            hrgn = ctypes.windll.gdi32.CreateRoundRectRgn(
                0, 0, self._w + 1, h + 1, h, h
            )
            ctypes.windll.user32.SetWindowRgn(hwnd, hrgn, True)
        except Exception:
            pass

    def _tick(self) -> None:
        if not self._alive or not self.top.winfo_exists():
            return
        self._dot_count = (self._dot_count % 3) + 1
        for i, dot in enumerate(self._dots):
            self._cv.itemconfig(
                dot, fill=self._fg if i < self._dot_count else self._dot_hidden
            )
        self.top.after(400, self._tick)

    def close(self) -> None:
        self._alive = False
        if self.top.winfo_exists():
            self.top.destroy()


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

        ttk.Button(llm, text="↻", width=3, command=_refresh_models).grid(
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
                self.app.overlay.set_text(f"✅ Pegel: {peak:.3f}")
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


class Tray:
    def __init__(self, app):
        self.app = app
        self.icon = None

    def make_image(self):
        icon_path = _resource("tray_icon.png")
        if icon_path.exists():
            return Image.open(icon_path).convert("RGBA")
        # Fallback: generiertes Icon
        image = Image.new("RGB", (64, 64), "black")
        draw = ImageDraw.Draw(image)
        draw.ellipse((12, 8, 52, 48), fill="white")
        draw.rectangle((28, 42, 36, 56), fill="white")
        draw.rectangle((20, 54, 44, 60), fill="white")
        return image

    def run(self):
        menu = pystray.Menu(
            pystray.MenuItem("Einstellungen", lambda: self.app.open_settings()),
            pystray.MenuItem("Beenden", lambda: self.app.quit()),
        )
        self.icon = pystray.Icon(
            "EuroWisprFlow", self.make_image(), "EuroWisprFlow", menu
        )
        self.icon.run()

    def stop(self):
        if self.icon:
            self.icon.stop()


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
        self._correction_tracker: CorrectionTracker | None = None

    def reload_config(self):
        self.config.reload()
        self.recorder = Recorder(self.config)
        self.client = WhisperClient(self.config)
        self.inserter = TextInserter(self.config)
        self.llm = LLMCorrector(self.config)

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
                text = self.llm.correct(text, self.vocab)
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
        None, True, "EuroWisprFlow_SingleInstance"
    )
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        import tkinter as _tk
        import tkinter.messagebox as _mb

        _r = _tk.Tk()
        _r.withdraw()
        _mb.showwarning("EuroWisprFlow", "EuroWisprFlow läuft bereits.")
        _r.destroy()
        sys.exit(0)
    print("Starte EuroWisprFlow…")
    App().run()
