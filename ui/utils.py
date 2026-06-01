import ctypes
from ctypes import wintypes


def _target_monitor() -> tuple:
    """Return (left, top, right, bottom) of the target monitor.

    Selects monitors[n // 2] sorted by left coordinate:
    1 monitor → 0, 2 → 1 (right), 3 → 1 (middle), 4 → 2 (right of centre).
    """
    try:
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
