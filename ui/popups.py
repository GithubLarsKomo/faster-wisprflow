import ctypes
import tkinter as tk

from config import load_config
from ui.translations import TRANSLATIONS
from ui.utils import _target_monitor


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
        _lang = load_config().get("language", "de")
        _text = TRANSLATIONS.get(_lang, TRANSLATIONS["de"])["llm_request_sent"]
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
        tmp = tk.Label(self.top, text=_text, font=self._FONT)
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
            text=_text,
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
