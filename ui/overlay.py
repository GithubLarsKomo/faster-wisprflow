import tkinter as tk

from config import _resource, load_config
from ui.translations import TRANSLATIONS
from ui.utils import _target_monitor

# ── Pill appearance ──────────────────────────────────────────────────────────
# _KEY_COLOR is used as the transparency key: every pixel of this exact colour
# becomes fully transparent.  It must not appear in the pill itself.
_KEY_COLOR = "#010101"  # near-black — imperceptible if it ever leaks
_PILL_BG = "white"
_PILL_FG = "#2a671b"
_PILL_FONT = ("Segoe UI", 18)
_PAD_X = 24  # horizontal padding inside the pill
_PAD_Y = 14  # vertical padding inside the pill
_RADIUS = 22  # corner radius (pixels)


def _draw_rounded_rect(canvas: tk.Canvas, w: int, h: int, r: int, fill: str) -> None:
    """Fill *canvas* with a rounded rectangle of size w×h, corner radius r."""
    canvas.delete("all")
    r = min(r, h // 2, w // 2)
    # Four corner arcs
    canvas.create_arc(
        0, 0, 2 * r, 2 * r, start=90, extent=90, style="pieslice", fill=fill, outline=""
    )
    canvas.create_arc(
        w - 2 * r,
        0,
        w,
        2 * r,
        start=0,
        extent=90,
        style="pieslice",
        fill=fill,
        outline="",
    )
    canvas.create_arc(
        0,
        h - 2 * r,
        2 * r,
        h,
        start=180,
        extent=90,
        style="pieslice",
        fill=fill,
        outline="",
    )
    canvas.create_arc(
        w - 2 * r,
        h - 2 * r,
        w,
        h,
        start=270,
        extent=90,
        style="pieslice",
        fill=fill,
        outline="",
    )
    # Fill body
    canvas.create_rectangle(r, 0, w - r, h, fill=fill, outline="")
    canvas.create_rectangle(0, r, w, h - r, fill=fill, outline="")


class Overlay:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("FlüsterFee")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        # Transparent-color approach: root bg = key colour → rendered transparent.
        # This avoids the black-corners / blurry-edge artifacts caused by
        # combining -alpha with SetWindowRgn on a DWM layered window.
        self.root.configure(bg=_KEY_COLOR)
        self.root.attributes("-transparentcolor", _KEY_COLOR)

        self._canvas = tk.Canvas(
            self.root, bg=_KEY_COLOR, highlightthickness=0, bd=0, width=1, height=1
        )
        self._canvas.pack()
        self._text_id: int | None = None

        _lang = load_config().get("language", "de")
        self._ready_text = TRANSLATIONS.get(_lang, TRANSLATIONS["de"])["status_ready"]

        icon_path = _resource("tray_icon.png")
        if icon_path.exists():
            try:
                img = tk.PhotoImage(file=str(icon_path))
                self.root.iconphoto(True, img)
            except Exception:
                pass

        self.root.withdraw()

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _render(self, text: str) -> tuple[int, int]:
        """Redraw the pill with *text*; return (pixel_width, pixel_height)."""
        # Measure text extent using a temporary canvas item
        tmp = self._canvas.create_text(0, 0, text=text, font=_PILL_FONT, anchor="nw")
        x0, y0, x1, y1 = self._canvas.bbox(tmp)
        self._canvas.delete(tmp)
        tw, th = x1 - x0, y1 - y0

        w = tw + _PAD_X * 2
        h = th + _PAD_Y * 2
        self._canvas.config(width=w, height=h)

        _draw_rounded_rect(self._canvas, w, h, _RADIUS, _PILL_BG)
        self._text_id = self._canvas.create_text(
            w // 2, h // 2, text=text, font=_PILL_FONT, fill=_PILL_FG, anchor="center"
        )
        return w, h

    def _position(self, w: int, h: int) -> None:
        ml, mt, mr, mb = _target_monitor()
        x = ml + (mr - ml - w) // 2
        y = mb - h - 60
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    # ── Public API ───────────────────────────────────────────────────────────

    def show(self, text: str) -> None:
        w, h = self._render(text)
        self.root.update_idletasks()
        self._position(w, h)
        self.root.deiconify()
        self.root.update()

    def set_text(self, text: str) -> None:
        w, h = self._render(text)
        self.root.update_idletasks()
        self._position(w, h)
        self.root.update()

    def hide(self) -> None:
        self.root.withdraw()
        self.root.update()

    def update_language(self, lang: str) -> None:
        self._ready_text = TRANSLATIONS.get(lang, TRANSLATIONS["de"])["status_ready"]

    def loop(self) -> None:
        self.root.mainloop()
