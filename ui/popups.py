import time
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
    _MAX_SECONDS = 30.0  # recording hard limit

    _IDLE_BG = "#ffffff"
    _IDLE_LLM_BG = "#99cc99"  # green when LLM correction is enabled
    _IDLE_FG = "#006600"
    _REC_BG = "#cc9999"  # same HSL luminosity as #99cc99 green
    _REC_FG = "#661b1b"
    _REC_PROG_TRACK = "#ccaaaa"

    def __init__(
        self,
        parent: tk.Misc,
        llm_enabled: bool = False,
        on_timeout=None,
        idle: bool = False,
    ) -> None:
        self._idle_bg = self._IDLE_LLM_BG if llm_enabled else self._IDLE_BG
        if idle:
            pill_bg = self._idle_bg
            fg = self._IDLE_FG
        else:
            pill_bg = "#99cc99" if llm_enabled else self._REC_BG
            fg = self._IDLE_FG if llm_enabled else self._REC_FG
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
        self._dots_w = dots_w
        self._dots_x0 = self._PX + bars_w + self._D_PAD
        self._on_timeout = on_timeout
        self._timeout_fired = idle  # suppress progress updates while idle
        self._start_time = time.monotonic()

        self.top = tk.Toplevel(parent)
        self.top.overrideredirect(True)
        self.top.attributes("-topmost", True)
        self.top.configure(bg=pill_bg)

        ml, mt, mr, mb = _target_monitor()
        self._mon = (ml, mt, mr, mb)
        w = self._bars_only_w if idle else self._full_w
        self.top.geometry(f"{w}x{h}+{ml + (mr - ml - w) // 2}+{mb - h - 70}")

        self._cv = tk.Canvas(
            self.top,
            width=self._bars_only_w if idle else self._full_w,
            height=h,
            bg=pill_bg,
            highlightthickness=0,
        )
        self._cv.pack()

        # pill background (drawn first so bars/dots sit on top)
        self._pill = self._cv.create_rectangle(
            0, 0, self._full_w, h, fill=pill_bg, outline=""
        )

        cy = h // 2
        self._cy = cy
        self._bars: list = []
        for i in range(self._N):
            x = self._PX + i * (self._BW + self._BG)
            bar = self._cv.create_rectangle(
                x, cy - 1, x + self._BW, cy + 1, fill=fg, outline=""
            )
            self._bars.append(bar)

        # 3 dots (hidden initially, revealed by show_dots() during conversion)
        dots_x0 = self._dots_x0
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

        # progress bar: drawn on top of dots so it is fully visible during recording
        _prog_bg = "#aaccaa"
        by0 = cy - self._MH // 2
        by1 = cy + self._MH // 2
        self._prog_track = self._cv.create_rectangle(
            dots_x0, by0, dots_x0 + dots_w, by1, fill=_prog_bg, outline=""
        )
        self._prog_fill = self._cv.create_rectangle(
            dots_x0, by0, dots_x0, by1, fill=fg, outline=""
        )

        # hide progress bar in idle mode
        if idle:
            self._cv.itemconfig(self._prog_track, fill=pill_bg)
            self._cv.itemconfig(self._prog_fill, fill=pill_bg)

        self._history: list = [0.0] * self._N
        self._rms: float = 0.0
        self._alive = True

        init_w = self._bars_only_w if idle else self._full_w
        self._border = self._cv.create_rectangle(
            0, 0, init_w - 1, h - 1, outline="black", fill=""
        )

        self.top.after(50, self._tick)

    def set_rms(self, rms: float) -> None:
        self._rms = rms

    def show_dots(self, n: int) -> None:
        """Show n filled dots (0–3); rest invisible."""
        if not self.top.winfo_exists():
            return
        for i, dot in enumerate(self._dots):
            self._cv.itemconfig(dot, fill=self._fg if i < n else self._dot_hidden)

    def expand_for_dots(self) -> None:
        """Hide the progress bar and raise dots for the conversion animation."""
        if not self.top.winfo_exists():
            return
        self._timeout_fired = True  # prevent double-stop if timeout fires later
        self._cv.itemconfig(self._prog_track, fill=self._pill_bg)
        self._cv.itemconfig(self._prog_fill, fill=self._pill_bg)
        # Raise dots above the now-invisible progress bar items
        for dot in self._dots:
            self._cv.tag_raise(dot)

    def _tick(self) -> None:
        if not self._alive or not self.top.winfo_exists():
            return
        # Waveform bars
        self._history = self._history[1:] + [min(self._rms * 5.0, 1.0)]
        for bar, rel in zip(self._bars, self._history):
            bh = max(2, int(rel * self._MH))
            x0, _, x1, _ = self._cv.coords(bar)
            self._cv.coords(bar, x0, self._cy - bh // 2, x1, self._cy + bh // 2)
        # Progress bar (only during recording, before expand_for_dots is called)
        if not self._timeout_fired:
            elapsed = time.monotonic() - self._start_time
            progress = min(elapsed / self._MAX_SECONDS, 1.0)
            fill_w = progress * self._dots_w
            dx0 = self._dots_x0
            by0 = self._cy - self._MH // 2
            by1 = self._cy + self._MH // 2
            self._cv.coords(self._prog_fill, dx0, by0, dx0 + fill_w, by1)
            if progress >= 1.0 and self._on_timeout:
                self._timeout_fired = True
                self._on_timeout()
        self.top.after(50, self._tick)

    def set_recording(self, on_timeout=None) -> None:
        """Transition to recording state: red bg, progress bar visible."""
        if not self.top.winfo_exists():
            return
        new_bg = self._REC_BG
        fg = self._REC_FG
        self._pill_bg = new_bg
        self._fg = fg
        self._dot_hidden = new_bg
        self._timeout_fired = False
        self._on_timeout = on_timeout
        self._start_time = time.monotonic()
        self._history = [0.0] * self._N
        self._rms = 0.0

        self.top.configure(bg=new_bg)
        self._cv.configure(bg=new_bg)
        self._cv.itemconfig(self._pill, fill=new_bg)
        for bar in self._bars:
            self._cv.itemconfig(bar, fill=fg)
        for dot in self._dots:
            self._cv.itemconfig(dot, fill=new_bg)  # keep dots hidden
        self._cv.itemconfig(self._prog_track, fill=self._REC_PROG_TRACK)
        self._cv.itemconfig(self._prog_fill, fill=fg)
        # Ensure progress bar is drawn above dots
        self._cv.tag_raise(self._prog_track)
        self._cv.tag_raise(self._prog_fill)

        ml, mt, mr, mb = self._mon
        w = self._full_w
        h = self._h
        self.top.geometry(f"{w}x{h}+{ml + (mr - ml - w) // 2}+{mb - h - 70}")
        self._cv.config(width=w)
        self._cv.coords(self._border, 0, 0, w - 1, h - 1)
        self._cv.tag_raise(self._border)

    def set_llm_enabled(self, llm_enabled: bool) -> None:
        """Update idle background to reflect LLM correction state."""
        self._idle_bg = self._IDLE_LLM_BG if llm_enabled else self._IDLE_BG
        # Only repaint immediately if currently in idle (timeout suppressed)
        if self._timeout_fired:
            self.set_idle()

    def set_idle(self) -> None:
        """Return to idle state: white/green bg, quiet bars, progress hidden."""
        if not self.top.winfo_exists():
            return
        new_bg = getattr(self, "_idle_bg", self._IDLE_BG)
        fg = self._IDLE_FG
        self._pill_bg = new_bg
        self._fg = fg
        self._dot_hidden = new_bg
        self._timeout_fired = True
        self._rms = 0.0
        self._history = [0.0] * self._N

        self.top.configure(bg=new_bg)
        self._cv.configure(bg=new_bg)
        self._cv.itemconfig(self._pill, fill=new_bg)
        for bar in self._bars:
            self._cv.itemconfig(bar, fill=fg)
            x0, _, x1, _ = self._cv.coords(bar)
            self._cv.coords(bar, x0, self._cy - 1, x1, self._cy + 1)
        for dot in self._dots:
            self._cv.itemconfig(dot, fill=new_bg)
        self._cv.itemconfig(self._prog_track, fill=new_bg)
        self._cv.itemconfig(self._prog_fill, fill=new_bg)

        ml, mt, mr, mb = self._mon
        w = self._bars_only_w
        h = self._h
        self.top.geometry(f"{w}x{h}+{ml + (mr - ml - w) // 2}+{mb - h - 70}")
        self._cv.config(width=w)
        self._cv.coords(self._border, 0, 0, w - 1, h - 1)
        self._cv.tag_raise(self._border)

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
        self.top.configure(bg=pill_bg)

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
            self.top, width=w, height=h, bg=pill_bg, highlightthickness=0
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

        self._cv.create_rectangle(0, 0, w - 1, h - 1, outline="black", fill="")

        self._alive = True
        self._dot_count = 0
        self.top.after(300, self._tick)

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
