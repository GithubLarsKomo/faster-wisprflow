import ctypes
import tkinter as tk

from config import _resource, load_config
from ui.translations import TRANSLATIONS
from ui.utils import _target_monitor

# ── Pill appearance ──────────────────────────────────────────────────────────
_PILL_BG = "white"
_PILL_FG = "#2a671b"

_PILL_FONT = ("Segoe UI", 18)
_PAD_X = 24  # horizontal padding inside the pill
_PAD_Y = 14  # vertical padding inside the pill


class Overlay:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("FlüsterFee")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=_PILL_BG)

        self._canvas = tk.Canvas(
            self.root, bg=_PILL_BG, highlightthickness=0, bd=0, width=1, height=1
        )
        self._canvas.pack()
        self._text_id: int | None = None
        self._border_id: int | None = None

        _lang = load_config().get("ui_language", "de")
        self._ready_text = TRANSLATIONS.get(_lang, TRANSLATIONS["de"])["status_ready"]
        self._recording_text = TRANSLATIONS.get(_lang, TRANSLATIONS["de"])[
            "status_recording"
        ]

        icon_path = _resource("tray_icon.png")
        if icon_path.exists():
            try:
                img = tk.PhotoImage(file=str(icon_path))
                self.root.iconphoto(True, img)
            except Exception:
                pass

        self.root.withdraw()

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _apply_region(self, w: int, h: int) -> None:
        """Clip the window to a pill/stadium shape via SetWindowRgn."""
        try:
            hwnd = self.root.winfo_id()
            hrgn = ctypes.windll.gdi32.CreateRoundRectRgn(0, 0, w + 1, h + 1, h, h)
            ctypes.windll.user32.SetWindowRgn(hwnd, hrgn, True)
        except Exception:
            pass

    def _render(
        self, text: str, bg: str = _PILL_BG, fg: str = _PILL_FG
    ) -> tuple[int, int]:
        """Redraw the pill with *text* and colors; return (pixel_width, pixel_height)."""
        self.root.configure(bg=bg)
        self._canvas.configure(bg=bg)

        # Measure text extent using a temporary canvas item
        tmp = self._canvas.create_text(0, 0, text=text, font=_PILL_FONT, anchor="nw")
        x0, y0, x1, y1 = self._canvas.bbox(tmp)
        self._canvas.delete(tmp)
        tw, th = x1 - x0, y1 - y0

        w = tw + _PAD_X * 2
        h = th + _PAD_Y * 2
        self._canvas.config(width=w, height=h)

        if self._text_id is not None:
            self._canvas.delete(self._text_id)
        self._text_id = self._canvas.create_text(
            w // 2, h // 2, text=text, font=_PILL_FONT, fill=fg, anchor="center"
        )
        if self._border_id is not None:
            self._canvas.delete(self._border_id)
        self._border_id = self._canvas.create_rectangle(
            0, 0, w - 1, h - 1, outline="black", fill=""
        )
        self._canvas.tag_raise(self._text_id)
        return w, h

    def _position(self, w: int, h: int) -> None:
        ml, mt, mr, mb = _target_monitor()
        x = ml + (mr - ml - w) // 2
        y = mb - h - 60
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    # ── Public API ───────────────────────────────────────────────────────────

    def show(self, text: str) -> None:
        w, _h = self._render(text)
        # Ensure the OK button exists and is packed
        if self._ok_btn is None:
            self._ok_btn = tk.Button(
                self.root,
                text="OK",
                font=("Segoe UI", 12, "bold"),
                command=self.hide,
                bg="#d9534f",
                fg="white",
                activebackground="#c9302c",
                activeforeground="white",
                relief="flat",
                padx=20,
                pady=4,
                cursor="hand2",
            )
        self._ok_btn.pack(pady=(0, 10))
        self.root.update_idletasks()
        total_h = self.root.winfo_reqheight()
        self._position(w, total_h)
        self.root.deiconify()
        self.root.update()

    def set_text(self, text: str) -> None:
        w, h = self._render(text)
        self.root.update_idletasks()
        self._position(w, h)
        self._apply_region(w, h)
        self.root.update()

    def hide(self) -> None:
        if self._ok_btn is not None:
            self._ok_btn.pack_forget()
        self.root.withdraw()
        self.root.update()

    def update_language(self, lang: str) -> None:
        self._ready_text = TRANSLATIONS.get(lang, TRANSLATIONS["de"])["status_ready"]
        self._recording_text = TRANSLATIONS.get(lang, TRANSLATIONS["de"])[
            "status_recording"
        ]

    def loop(self) -> None:
        self.root.mainloop()
