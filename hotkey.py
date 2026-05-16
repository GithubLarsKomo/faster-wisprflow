"""
Global hotkey via Win32 RegisterHotKey — no elevation required.

Win32 RegisterHotKey works from user-space and supports any combination of
MOD_ALT / MOD_CONTROL / MOD_SHIFT / MOD_WIN.  We register the hotkey on the
Tkinter main-thread message loop so no separate thread is needed.

Supported key names (config "hotkey_keys"):
  Modifiers : ctrl, shift, alt, win, left windows, linke windows, right windows
  Regular   : a-z, 0-9, f1-f24, space, tab, return, escape, ...

Usage
-----
    hk = HotkeyManager(overlay_root)
    hk.register(["ctrl", "linke windows"], on_press, on_release)
    # ... later ...
    hk.unregister()
"""

import ctypes
import ctypes.wintypes
import threading
from typing import Callable

# ── Win32 constants ──────────────────────────────────────────────────────────
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

WM_HOTKEY = 0x0312
WM_APP_HOTKEY_UP = 0x8001  # custom message for key-up

_HOTKEY_ID = 0xBEEF  # arbitrary unique ID

# Virtual key codes for non-modifier keys
_VK_MAP: dict[str, int] = {
    "space": 0x20,
    "tab": 0x09,
    "return": 0x0D,
    "enter": 0x0D,
    "escape": 0x1B,
    "esc": 0x1B,
    "backspace": 0x08,
    "delete": 0x2E,
    "insert": 0x2D,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "page up": 0x21,
    "pagedown": 0x22,
    "page down": 0x22,
    "up": 0x26,
    "down": 0x28,
    "left": 0x25,
    "right": 0x27,
    **{f"f{i}": 0x6F + i for i in range(1, 25)},  # F1-F24: 0x70-0x87
    **{chr(c): ord(chr(c).upper()) for c in range(ord("a"), ord("z") + 1)},
    **{str(d): ord(str(d)) for d in range(0, 10)},
}
# Fix F1 base: F1=0x70, so f{i} → 0x6F+i is wrong for i=1 → 0x70 ✓ (0x6F+1=0x70)

_MOD_NAMES = {
    "ctrl",
    "control",
    "shift",
    "alt",
    "win",
    "windows",
    "left windows",
    "linke windows",
    "right windows",
    "rechte windows",
}


def _parse_hotkey(keys: list[str]) -> tuple[int, int]:
    """Parse a key list into (mods, vk) for RegisterHotKey."""
    mods = MOD_NOREPEAT
    vk = 0
    for k in keys:
        kl = k.strip().lower()
        if kl in ("ctrl", "control"):
            mods |= MOD_CONTROL
        elif kl == "shift":
            mods |= MOD_SHIFT
        elif kl == "alt":
            mods |= MOD_ALT
        elif kl in (
            "win",
            "windows",
            "left windows",
            "linke windows",
            "right windows",
            "rechte windows",
        ):
            mods |= MOD_WIN
        else:
            vk = _VK_MAP.get(kl, 0)
            if not vk and len(kl) == 1:
                vk = ord(kl.upper())
    return mods, vk


# ── Key-up detection via raw WM_KEYUP in a dedicated thread ─────────────────
# RegisterHotKey only fires on key-down. To detect release we use GetAsyncKeyState
# sampled from the same background thread that posts WM_APP_HOTKEY_UP.

VK_LWIN = 0x5B
VK_RWIN = 0x5C
VK_CONTROL = 0x11
VK_LCONTROL = 0xA2
VK_RCONTROL = 0xA3

_VK_FOR_MOD: dict[int, list[int]] = {
    MOD_CONTROL: [VK_CONTROL, VK_LCONTROL, VK_RCONTROL],
    MOD_WIN: [VK_LWIN, VK_RWIN],
    MOD_ALT: [0x12],  # VK_MENU
    MOD_SHIFT: [0x10],  # VK_SHIFT
}


def _any_pressed(vk_list: list[int]) -> bool:
    for vk in vk_list:
        if ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000:
            return True
    return False


class HotkeyManager:
    """
    Registers a global hotkey with RegisterHotKey and polls for release.

    The press callback fires on the system hotkey message.
    The release callback fires when all modifier keys are physically released.
    Both callbacks are dispatched via Tkinter's `after` so they run safely on
    the main thread.
    """

    def __init__(self, tk_root) -> None:
        self._root = tk_root
        self._mods: int = 0
        self._vk: int = 0
        self._on_press: Callable | None = None
        self._on_release: Callable | None = None
        self._registered = False
        self._hwnd: int = 0
        self._active = False  # True while hotkey is physically held
        self._poll_thread: threading.Thread | None = None
        self._running = False

    # ── Public API ───────────────────────────────────────────────────────────

    def register(
        self,
        keys: list[str],
        on_press: Callable,
        on_release: Callable,
    ) -> None:
        self.unregister()
        self._on_press = on_press
        self._on_release = on_release
        self._mods, self._vk = _parse_hotkey(keys)

        # Tkinter HWND: we need the hidden Tk message-only window handle.
        # winfo_id() returns the handle of the root window which is on the
        # same thread and receives WM_HOTKEY.
        self._hwnd = self._root.winfo_id()

        ok = ctypes.windll.user32.RegisterHotKey(None, _HOTKEY_ID, self._mods, self._vk)
        if not ok:
            err = ctypes.windll.kernel32.GetLastError()
            raise OSError(
                f"RegisterHotKey failed (err={err}). "
                "Another app may have the same hotkey registered."
            )
        self._registered = True
        self._running = True
        self._poll_thread = threading.Thread(
            target=self._poll_loop, daemon=True, name="hotkey-poll"
        )
        self._poll_thread.start()

        # Hook into Tkinter's message pump via the WM_HOTKEY binding.
        # Tkinter exposes raw WM messages through the internal `_root.bind`
        # on <<HotkeyPress>> which we synthesise from the poll thread.
        self._root.bind("<<HotkeyPress>>", self._tk_press, add=False)
        self._root.bind("<<HotkeyRelease>>", self._tk_release, add=False)

    def unregister(self) -> None:
        self._running = False
        if self._registered:
            ctypes.windll.user32.UnregisterHotKey(None, _HOTKEY_ID)
            self._registered = False
        try:
            self._root.unbind("<<HotkeyPress>>")
            self._root.unbind("<<HotkeyRelease>>")
        except Exception:
            pass

    # ── Internal ─────────────────────────────────────────────────────────────

    def _tk_press(self, _event=None) -> None:
        if self._on_press:
            self._on_press()

    def _tk_release(self, _event=None) -> None:
        if self._on_release:
            self._on_release()

    def _all_mods_released(self) -> bool:
        """Return True when every modifier in the registered combo is up."""
        for mod_flag, vk_list in _VK_FOR_MOD.items():
            if self._mods & mod_flag:
                if _any_pressed(vk_list):
                    return False
        # Also check the non-modifier key if there is one
        if self._vk and ctypes.windll.user32.GetAsyncKeyState(self._vk) & 0x8000:
            return False
        return True

    def _poll_loop(self) -> None:
        """
        Message-pump thread:
        - Drains WM_HOTKEY from the thread queue → fires <<HotkeyPress>>
        - Polls for key release → fires <<HotkeyRelease>>
        """
        import ctypes.wintypes as wt

        msg = wt.MSG()
        while self._running:
            # Non-blocking PeekMessage
            if ctypes.windll.user32.PeekMessageW(
                ctypes.byref(msg), None, WM_HOTKEY, WM_HOTKEY, 1  # PM_REMOVE=1
            ):
                if msg.message == WM_HOTKEY and msg.wParam == _HOTKEY_ID:
                    if not self._active:
                        self._active = True
                        self._root.event_generate("<<HotkeyPress>>", when="tail")

            # Detect release
            if self._active and self._all_mods_released():
                self._active = False
                self._root.event_generate("<<HotkeyRelease>>", when="tail")

            import time as _time

            _time.sleep(0.015)
