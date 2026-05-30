import time
import tkinter as tk
from tkinter import ttk

from config import load_config, save_config
from ui.translations import LANG_CODES, TRANSLATIONS
from ui.utils import _target_monitor


class _MicLevelPopup:
    """Animated waveform bar popup that reacts to microphone loudness."""

    _N = 10  # number of bars
    _BW = 3  # bar width (px)
    _BG = 2  # gap between bars (px)
    _MH = 13  # max bar height (px)
    _PX = 10  # horizontal padding
    _PY = 5  # vertical padding
    _D_R = 2  # dot radius (px)
    _D_GAP = 3  # gap between dots (px)
    _D_PAD = 5  # gap between bars and dots (px)
    _DEFAULT_MAX_SECONDS = 60.0  # recording hard limit fallback
    _IDLE_COLLAPSE_FACTOR = 0.25

    _IDLE_BG = "#ffffff"
    _IDLE_LLM_BG = "#99cc99"  # green when LLM correction is enabled
    _IDLE_FG = "#006600"
    _REC_BG = "#cc9999"  # same HSL luminosity as #99cc99 green
    _REC_FG = "#661b1b"
    _REC_PROG_TRACK = "#ccaaaa"
    _TRANSPARENT_BG = "#ff00ff"

    def __init__(
        self,
        parent: tk.Misc,
        llm_enabled: bool = False,
        on_timeout=None,
        idle: bool = False,
        max_seconds: float | int | None = None,
        target_language: str | None = None,
        ui_language: str | None = None,
        whisper_provider: str | None = None,
        on_open_settings=None,
        on_quit=None,
        on_config_saved=None,
    ) -> None:
        self._max_seconds = self._sanitize_max_seconds(max_seconds)
        self._on_open_settings = on_open_settings
        self._on_quit = on_quit
        self._on_config_saved = on_config_saved
        self._provider = whisper_provider or "lokal"
        self._ui_language = ui_language or load_config().get("ui_language", "de")
        self._suspend_lang_save = False
        self._collapsed_idle = False
        self._side_controls_visible = True
        self._is_hovered = False
        self._outer_pad_x = 1
        self._outer_pad_y = 2

        self._lang_combo_style = "PopupLang.TCombobox"
        self._icon_button_style = "PopupIcon.TButton"

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
        self._collapsed_h = max(1, int(self._h * self._IDLE_COLLAPSE_FACTOR))
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
        self.top.configure(bg=self._TRANSPARENT_BG)
        try:
            self.top.attributes("-transparentcolor", self._TRANSPARENT_BG)
        except tk.TclError:
            # Fallback on platforms where transparentcolor is unsupported.
            pass

        style = ttk.Style(self.top)
        style.configure(
            self._lang_combo_style,
            padding=(5, 4, 5, 4),
            arrowsize=14,
            font=("Segoe UI", 10),
        )
        style.configure(self._icon_button_style, padding=(1, 3, 1, 3))

        self._root = tk.Frame(
            self.top,
            bg=self._TRANSPARENT_BG,
            padx=self._outer_pad_x,
            pady=self._outer_pad_y,
        )
        self._root.pack(fill="both", expand=True)

        self._left = tk.Frame(
            self._root,
            bg=self._TRANSPARENT_BG,
            width=52,
            height=self._h,
        )
        self._left.pack_propagate(False)

        self._middle = tk.Frame(
            self._root,
            bg=self._TRANSPARENT_BG,
            width=self._full_w,
            height=self._h,
        )
        self._middle.pack(side="left", fill="y")
        self._middle.pack_propagate(False)

        self._right = tk.Frame(
            self._root,
            bg=self._TRANSPARENT_BG,
            height=self._h,
        )
        self._right.pack_propagate(True)

        self._lang_var = tk.StringVar(value=target_language or "de")
        self._lang_combo = ttk.Combobox(
            self._left,
            textvariable=self._lang_var,
            values=LANG_CODES,
            state="readonly",
            width=5,
            style=self._lang_combo_style,
        )
        self._lang_combo.pack(side="left", anchor="w", ipady=7)
        self._lang_combo.bind("<<ComboboxSelected>>", self._on_target_language_change)

        self._right_row = tk.Frame(self._right, bg=self._TRANSPARENT_BG)
        self._right_row.pack(side="left", anchor="w")

        self._menu_btn = ttk.Button(
            self._right_row,
            text="☰",
            width=3,
            command=self._handle_open_settings,
            style=self._icon_button_style,
        )
        self._menu_btn.pack(side="left", padx=(0, 0))

        self._quit_btn = ttk.Button(
            self._right_row,
            text="✕",
            width=3,
            command=self._handle_quit,
            style=self._icon_button_style,
        )
        self._quit_btn.pack(side="left", padx=(1, 0))

        # Keep all controls and the indicator on one exact row height.
        self.top.update_idletasks()
        row_h = max(
            self._lang_combo.winfo_reqheight(),
            self._menu_btn.winfo_reqheight(),
            self._quit_btn.winfo_reqheight(),
        )
        self._h = max(self._h, row_h)
        self._collapsed_h = max(1, int(self._h * self._IDLE_COLLAPSE_FACTOR))
        self._left.configure(height=self._h)
        self._middle.configure(height=self._h)
        self._right.configure(height=self._h)
        h = self._h

        ml, mt, mr, mb = _target_monitor()
        self._mon = (ml, mt, mr, mb)

        self._content_h = self._h
        self._content_holder = tk.Frame(
            self._middle, width=self._full_w, height=self._h
        )
        self._content_holder.pack(fill="both", expand=False)
        self._content_holder.pack_propagate(False)

        self._cv = tk.Canvas(
            self._content_holder,
            width=self._bars_only_w if idle else self._full_w,
            height=h,
            bg=self._TRANSPARENT_BG,
            highlightthickness=0,
        )
        self._cv.pack(fill="both", expand=True)

        # pill background (drawn first so bars/dots sit on top)
        self._pill = self._cv.create_rectangle(
            0,
            0,
            self._full_w,
            h,
            fill=pill_bg,
            outline="",
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
        self._cv.itemconfig(self._prog_track, state="hidden")
        self._cv.itemconfig(self._prog_fill, state="hidden")

        # hide progress bar in idle mode
        if idle:
            self._cv.itemconfig(self._prog_track, fill=pill_bg)
            self._cv.itemconfig(self._prog_fill, fill=pill_bg)

        self._history: list = [0.0] * self._N
        self._rms: float = 0.0
        self._alive = True

        init_w = self._bars_only_w if idle else self._full_w
        self._border = self._cv.create_rectangle(
            0,
            0,
            init_w - 1,
            h - 1,
            outline="" if idle else self._provider_border_color(),
            fill="",
        )

        self._bind_hover_events()

        self._set_content_collapsed(idle)
        self._reposition_window(init_w)

        self.top.after(50, self._tick)

    @classmethod
    def _sanitize_max_seconds(cls, value: float | int | None) -> float:
        try:
            seconds = float(value)
            if seconds > 0:
                return seconds
        except (TypeError, ValueError):
            pass
        return cls._DEFAULT_MAX_SECONDS

    def set_max_seconds(self, max_seconds: float | int | None) -> None:
        self._max_seconds = self._sanitize_max_seconds(max_seconds)

    def set_provider(self, provider: str | None) -> None:
        self._provider = provider or "lokal"
        if self.top.winfo_exists():
            self._cv.itemconfig(self._border, outline=self._provider_border_color())

    def set_target_language(self, lang_code: str) -> None:
        self._suspend_lang_save = True
        try:
            self._lang_var.set(lang_code)
        finally:
            self._suspend_lang_save = False

    def set_ui_language(self, ui_language: str) -> None:
        self._ui_language = ui_language

    def _provider_border_color(self) -> str:
        if self._provider in {"Openrouter", "Groq"}:
            return "#FF0000"
        return ""

    def _handle_open_settings(self) -> None:
        if callable(self._on_open_settings):
            self._on_open_settings()

    def _handle_quit(self) -> None:
        if callable(self._on_quit):
            self._on_quit()

    def _on_target_language_change(self, _evt=None) -> None:
        if self._suspend_lang_save:
            return
        lang = self._lang_var.get().strip()
        if not lang:
            return
        cfg = load_config()
        if cfg.get("language") == lang:
            return
        cfg["language"] = lang
        save_config(cfg)
        if callable(self._on_config_saved):
            self._on_config_saved()

    def _bind_hover_events(self) -> None:
        for widget in (
            self.top,
            self._root,
            self._left,
            self._middle,
            self._right,
            self._right_row,
            self._cv,
            self._menu_btn,
            self._quit_btn,
            self._lang_combo,
        ):
            widget.bind("<Enter>", self._on_hover_enter, add="+")
            widget.bind("<Leave>", self._on_hover_leave, add="+")

    def _show_side_controls(self, show: bool) -> None:
        if self._side_controls_visible == show:
            return
        self._side_controls_visible = show
        if show:
            self._left.pack(side="left", before=self._middle, padx=(0, 1), fill="y")
            self._right.pack(side="left", after=self._middle, padx=(1, 0), fill="y")
        else:
            self._left.pack_forget()
            self._right.pack_forget()

    def _on_hover_enter(self, _evt=None) -> None:
        self._is_hovered = True
        if self._timeout_fired:
            self._set_content_collapsed(False)
        else:
            self._show_side_controls(True)

    def _on_hover_leave(self, _evt=None) -> None:
        self.top.after(60, self._collapse_if_pointer_outside)

    def _collapse_if_pointer_outside(self) -> None:
        if not self.top.winfo_exists() or not self._timeout_fired:
            return
        px, py = self.top.winfo_pointerxy()
        widget = self.top.winfo_containing(px, py)
        if widget is None or widget.winfo_toplevel() is not self.top:
            self._is_hovered = False
            self._show_side_controls(False)
            if not self._timeout_fired:
                return
            self._set_content_collapsed(True)

    def _set_content_collapsed(self, collapsed: bool) -> None:
        self._collapsed_idle = collapsed
        self._show_side_controls(self._is_hovered)
        if collapsed:
            self._root.configure(pady=0)
        else:
            self._root.configure(pady=self._outer_pad_y)
        target_h = self._collapsed_h if collapsed else self._h
        self._content_h = target_h
        self._middle.configure(height=target_h)
        self._content_holder.configure(height=target_h)
        self._cv.configure(height=target_h)
        if self._timeout_fired and collapsed:
            current_w = self._bars_only_w
            self._cv.configure(bg=self._TRANSPARENT_BG)
            self._cv.itemconfig(self._pill, fill=self._pill_bg)
            self._cv.itemconfig(self._prog_track, fill=self._TRANSPARENT_BG)
            self._cv.itemconfig(self._prog_fill, fill=self._TRANSPARENT_BG)
            self._cv.itemconfig(self._border, outline="")
        else:
            prog_track_state = str(self._cv.itemcget(self._prog_track, "state"))
            current_w = (
                self._full_w if prog_track_state != "hidden" else self._bars_only_w
            )
            self._cv.configure(bg=self._pill_bg)
            self._cv.itemconfig(self._pill, fill=self._pill_bg)
            self._cv.itemconfig(self._border, outline=self._provider_border_color())
        self._middle.configure(width=current_w)
        self._cv.coords(self._border, 0, 0, current_w - 1, max(1, target_h) - 1)
        self._cv.tag_raise(self._border)
        self._reposition_window(current_w)

    def _reposition_window(self, content_w: int) -> None:
        self._content_holder.configure(width=content_w)
        self._cv.configure(width=content_w)
        self.top.update_idletasks()
        ml, mt, mr, mb = self._mon
        total_w = max(1, self.top.winfo_reqwidth())
        total_h = max(1, self.top.winfo_reqheight())
        x = ml + (mr - ml - total_w) // 2
        y = mb - total_h - 70
        self.top.geometry(f"{total_w}x{total_h}+{x}+{y}")

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
            progress = min(elapsed / self._max_seconds, 1.0)
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

        self.top.configure(bg=self._TRANSPARENT_BG)
        self._cv.configure(bg=self._TRANSPARENT_BG)
        self._cv.itemconfig(self._pill, fill=new_bg)
        for bar in self._bars:
            self._cv.itemconfig(bar, fill=fg)
        for dot in self._dots:
            self._cv.itemconfig(dot, fill=new_bg)  # keep dots hidden
        self._cv.itemconfig(self._prog_track, fill=self._REC_PROG_TRACK)
        self._cv.itemconfig(self._prog_fill, fill=fg)
        self._cv.itemconfig(self._prog_track, state="normal")
        self._cv.itemconfig(self._prog_fill, state="normal")
        # Ensure progress bar is drawn above dots
        self._cv.tag_raise(self._prog_track)
        self._cv.tag_raise(self._prog_fill)

        self._cv.itemconfig(self._border, outline=self._provider_border_color())

        w = self._full_w
        h = self._h
        self._set_content_collapsed(False)
        self._cv.config(width=w)
        self._cv.coords(self._border, 0, 0, w - 1, h - 1)
        self._cv.tag_raise(self._border)
        self._reposition_window(w)

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

        self.top.configure(bg=self._TRANSPARENT_BG)
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
        self._cv.itemconfig(self._prog_track, state="hidden")
        self._cv.itemconfig(self._prog_fill, state="hidden")
        self._cv.itemconfig(self._border, outline=self._provider_border_color())

        w = self._bars_only_w
        self._set_content_collapsed(True)
        self._cv.config(width=w)
        self._cv.coords(self._border, 0, 0, w - 1, self._h - 1)
        self._cv.tag_raise(self._border)
        self._reposition_window(w)

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
