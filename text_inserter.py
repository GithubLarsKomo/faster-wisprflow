"""
Windows-native text insertion — no elevation required.

Strategy
--------
1. Copy text to clipboard via Win32 OpenClipboard/SetClipboardData
   (avoids pyperclip's subprocess dependency in frozen builds).
2. Send Ctrl+V via SendInput (not keybd_event, not the keyboard package).
3. Wait for Word/target to process the paste, then restore the clipboard.

Why this works on Word 365
--------------------------
- SendInput posts synthetic INPUT records at UIPI user-level; no admin needed.
- We detect WINWORD.EXE in the foreground and add an extra stabilisation delay
  so Word's protected-paste path has time to finish before clipboard restoration.
- Clipboard is opened with a retry loop because Word briefly holds it.

Thread safety
-------------
insert_text() is designed to be called from a background thread.
All Win32 calls are thread-safe (clipboard is mutex-guarded by the OS).
"""

import ctypes
import ctypes.wintypes as wt
import re
import time

# ── Win32 types / constants ──────────────────────────────────────────────────
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

VK_CONTROL = 0x11
VK_SHIFT = 0x10
VK_V = 0x56
VK_C = 0x43
VK_LEFT = 0x25
VK_RIGHT = 0x27

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002

_u32 = ctypes.windll.user32
_k32 = ctypes.windll.kernel32

# Fix 64-bit handle/pointer truncation on 64-bit Windows.
# ctypes defaults restype=c_int (32-bit) and argtypes=None (defaults to c_int).
# Handles / pointers returned or accepted by these functions can exceed 2 GB,
# so both restype AND argtypes must be declared with c_void_p / c_size_t.
_k32.GlobalAlloc.restype = ctypes.c_void_p
_k32.GlobalAlloc.argtypes = [wt.UINT, ctypes.c_size_t]
_k32.GlobalLock.restype = ctypes.c_void_p
_k32.GlobalLock.argtypes = [ctypes.c_void_p]
_k32.GlobalUnlock.restype = ctypes.c_bool
_k32.GlobalUnlock.argtypes = [ctypes.c_void_p]
_k32.OpenProcess.restype = ctypes.c_void_p
_k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
_k32.CloseHandle.restype = ctypes.c_bool
_k32.CloseHandle.argtypes = [ctypes.c_void_p]
_u32.GetClipboardData.restype = ctypes.c_void_p
_u32.GetClipboardData.argtypes = [wt.UINT]
_u32.SetClipboardData.restype = ctypes.c_void_p
_u32.SetClipboardData.argtypes = [wt.UINT, ctypes.c_void_p]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wt.WORD),
        ("wScan", wt.WORD),
        ("dwFlags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("ki", _KEYBDINPUT),
        # Pad to MOUSEINPUT size (32 bytes) so _INPUT matches the real Win32
        # INPUT struct (40 bytes on 64-bit). SendInput checks cbSize strictly.
        ("_pad", ctypes.c_byte * 32),
    ]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("_input", _INPUT_UNION)]


# ── Helpers ──────────────────────────────────────────────────────────────────


def _foreground_exe() -> str:
    """Return the exe name of the foreground window's process (lower-case)."""
    try:
        hwnd = _u32.GetForegroundWindow()
        pid = wt.DWORD(0)
        _u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        h = _k32.OpenProcess(0x0410, False, pid.value)  # PROCESS_QUERY_INFO|VM_READ
        if not h:
            return ""
        buf = ctypes.create_unicode_buffer(260)
        _k32.GetModuleFileNameExW(h, None, buf, 260)
        _k32.CloseHandle(h)
        return buf.value.lower().split("\\")[-1]
    except Exception:
        return ""


def _set_clipboard_text(text: str, retries: int = 8) -> bool:
    """Write *text* to the clipboard as CF_UNICODETEXT. Returns True on success."""
    encoded = (text + "\0").encode("utf-16-le")
    for attempt in range(retries):
        if _u32.OpenClipboard(None):
            try:
                _u32.EmptyClipboard()
                h = _k32.GlobalAlloc(GMEM_MOVEABLE, len(encoded))
                if not h:
                    return False
                ptr = _k32.GlobalLock(h)
                ctypes.memmove(ptr, encoded, len(encoded))
                _k32.GlobalUnlock(h)
                _u32.SetClipboardData(CF_UNICODETEXT, h)
                return True
            finally:
                _u32.CloseClipboard()
        time.sleep(0.04 * (attempt + 1))
    return False


def _get_clipboard_text() -> str | None:
    """Read current clipboard text (CF_UNICODETEXT). Returns None on failure."""
    for attempt in range(6):
        if _u32.OpenClipboard(None):
            try:
                h = _u32.GetClipboardData(CF_UNICODETEXT)
                if not h:
                    return None
                ptr = _k32.GlobalLock(h)
                if not ptr:
                    return None
                raw = ctypes.wstring_at(ptr)
                _k32.GlobalUnlock(h)
                return raw
            finally:
                _u32.CloseClipboard()
        time.sleep(0.03 * (attempt + 1))
    return None


def _send_ctrl_v() -> None:
    """Post a Ctrl+V key-down/up pair via SendInput."""
    inputs = (_INPUT * 4)(
        _INPUT(
            type=INPUT_KEYBOARD,
            _input=_INPUT_UNION(
                ki=_KEYBDINPUT(
                    wVk=VK_CONTROL, wScan=0, dwFlags=0, time=0, dwExtraInfo=None
                )
            ),
        ),
        _INPUT(
            type=INPUT_KEYBOARD,
            _input=_INPUT_UNION(
                ki=_KEYBDINPUT(wVk=VK_V, wScan=0, dwFlags=0, time=0, dwExtraInfo=None)
            ),
        ),
        _INPUT(
            type=INPUT_KEYBOARD,
            _input=_INPUT_UNION(
                ki=_KEYBDINPUT(
                    wVk=VK_V, wScan=0, dwFlags=KEYEVENTF_KEYUP, time=0, dwExtraInfo=None
                )
            ),
        ),
        _INPUT(
            type=INPUT_KEYBOARD,
            _input=_INPUT_UNION(
                ki=_KEYBDINPUT(
                    wVk=VK_CONTROL,
                    wScan=0,
                    dwFlags=KEYEVENTF_KEYUP,
                    time=0,
                    dwExtraInfo=None,
                )
            ),
        ),
    )
    _u32.SendInput(4, inputs, ctypes.sizeof(_INPUT))


def _send_ctrl_c() -> None:
    """Post a Ctrl+C key-down/up pair via SendInput."""
    inputs = (_INPUT * 4)(
        _INPUT(
            type=INPUT_KEYBOARD,
            _input=_INPUT_UNION(
                ki=_KEYBDINPUT(
                    wVk=VK_CONTROL, wScan=0, dwFlags=0, time=0, dwExtraInfo=None
                )
            ),
        ),
        _INPUT(
            type=INPUT_KEYBOARD,
            _input=_INPUT_UNION(
                ki=_KEYBDINPUT(wVk=VK_C, wScan=0, dwFlags=0, time=0, dwExtraInfo=None)
            ),
        ),
        _INPUT(
            type=INPUT_KEYBOARD,
            _input=_INPUT_UNION(
                ki=_KEYBDINPUT(
                    wVk=VK_C, wScan=0, dwFlags=KEYEVENTF_KEYUP, time=0, dwExtraInfo=None
                )
            ),
        ),
        _INPUT(
            type=INPUT_KEYBOARD,
            _input=_INPUT_UNION(
                ki=_KEYBDINPUT(
                    wVk=VK_CONTROL,
                    wScan=0,
                    dwFlags=KEYEVENTF_KEYUP,
                    time=0,
                    dwExtraInfo=None,
                )
            ),
        ),
    )
    _u32.SendInput(4, inputs, ctypes.sizeof(_INPUT))


def _send_shift_left() -> None:
    """Select one character to the left."""
    inputs = (_INPUT * 4)(
        _INPUT(
            type=INPUT_KEYBOARD,
            _input=_INPUT_UNION(
                ki=_KEYBDINPUT(
                    wVk=VK_SHIFT, wScan=0, dwFlags=0, time=0, dwExtraInfo=None
                )
            ),
        ),
        _INPUT(
            type=INPUT_KEYBOARD,
            _input=_INPUT_UNION(
                ki=_KEYBDINPUT(
                    wVk=VK_LEFT, wScan=0, dwFlags=0, time=0, dwExtraInfo=None
                )
            ),
        ),
        _INPUT(
            type=INPUT_KEYBOARD,
            _input=_INPUT_UNION(
                ki=_KEYBDINPUT(
                    wVk=VK_LEFT,
                    wScan=0,
                    dwFlags=KEYEVENTF_KEYUP,
                    time=0,
                    dwExtraInfo=None,
                )
            ),
        ),
        _INPUT(
            type=INPUT_KEYBOARD,
            _input=_INPUT_UNION(
                ki=_KEYBDINPUT(
                    wVk=VK_SHIFT,
                    wScan=0,
                    dwFlags=KEYEVENTF_KEYUP,
                    time=0,
                    dwExtraInfo=None,
                )
            ),
        ),
    )
    _u32.SendInput(4, inputs, ctypes.sizeof(_INPUT))


def _send_right() -> None:
    """Move caret one character to the right."""
    inputs = (_INPUT * 2)(
        _INPUT(
            type=INPUT_KEYBOARD,
            _input=_INPUT_UNION(
                ki=_KEYBDINPUT(
                    wVk=VK_RIGHT, wScan=0, dwFlags=0, time=0, dwExtraInfo=None
                )
            ),
        ),
        _INPUT(
            type=INPUT_KEYBOARD,
            _input=_INPUT_UNION(
                ki=_KEYBDINPUT(
                    wVk=VK_RIGHT,
                    wScan=0,
                    dwFlags=KEYEVENTF_KEYUP,
                    time=0,
                    dwExtraInfo=None,
                )
            ),
        ),
    )
    _u32.SendInput(2, inputs, ctypes.sizeof(_INPUT))


# ── Public API ───────────────────────────────────────────────────────────────


class TextInserter:
    # Extra delay (seconds) added when the foreground window is Word 365
    WORD_EXTRA_DELAY = 0.12

    def __init__(self, config) -> None:
        self.config = config

    @staticmethod
    def _capitalize_first_latin_word(text: str) -> str:
        """Uppercase first latin letter in the chunk, preserving surrounding text."""
        if not text:
            return text
        return re.sub(
            r"([a-z\u00e0-\u00f6\u00f8-\u00ff])",
            lambda m: m.group(1).upper(),
            text,
            count=1,
        )

    @staticmethod
    def _needs_sentence_capitalization(prev_char: str | None) -> bool:
        """Return True if previous context indicates a new sentence/paragraph start."""
        if prev_char is None:
            return True
        return prev_char in ".!?;:\n\r"

    def _peek_previous_non_space_char(self, lookback: int = 8) -> str | None:
        """Try to read a short left context by selecting/copying text before the caret."""
        sentinel = "__FWF_PREV_CHAR_SENTINEL__"
        if not _set_clipboard_text(sentinel):
            return None

        time.sleep(0.02)
        for _ in range(max(1, int(lookback))):
            _send_shift_left()
        time.sleep(0.03)
        _send_ctrl_c()
        time.sleep(0.04)
        snippet = _get_clipboard_text()
        for _ in range(max(1, int(lookback))):
            _send_right()

        if not snippet or snippet == sentinel:
            return None
        stripped = snippet.rstrip()
        if not stripped:
            return None
        return stripped[-1]

    def _apply_cursor_context_case(self, text: str) -> str:
        if not bool(getattr(self.config, "transcription_guidance_enabled", False)):
            return text
        prev_char = self._peek_previous_non_space_char()
        if self._needs_sentence_capitalization(prev_char):
            return self._capitalize_first_latin_word(text)
        return text

    def insert_text(self, text: str) -> None:
        if not text:
            return

        text = self._apply_cursor_context_case(text)

        # 1. Save existing clipboard if requested
        old_text: str | None = None
        if self.config.restore_clipboard:
            old_text = _get_clipboard_text()

        # 2. Is Word in the foreground?
        is_word = _foreground_exe() == "winword.exe"

        # 3. Write our text to clipboard
        if not _set_clipboard_text(text):
            # Fallback: pyperclip (shouldn't normally be needed)
            try:
                import pyperclip

                pyperclip.copy(text)
            except Exception:
                return
        time.sleep(0.06)

        # 4. Send Ctrl+V
        _send_ctrl_v()

        # 5. Wait for paste to be processed
        delay = 0.15 + (self.WORD_EXTRA_DELAY if is_word else 0.0)
        time.sleep(delay)

        # 6. Restore clipboard
        if self.config.restore_clipboard and old_text is not None:
            _set_clipboard_text(old_text)
