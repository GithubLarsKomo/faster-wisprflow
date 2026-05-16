import ctypes
import ctypes.wintypes as wt
import difflib
import threading
import time

from text_inserter import (
    _INPUT,
    _INPUT_UNION,
    _KEYBDINPUT,
    INPUT_KEYBOARD,
    KEYEVENTF_KEYUP,
    VK_CONTROL,
    _get_clipboard_text,
    _set_clipboard_text,
)
from vocabulary import VocabularyManager

# ── Key codes used for snapshot ──────────────────────────────────────────────
VK_LEFT = 0x25
VK_RIGHT = 0x27
VK_C = 0x43
VK_SHIFT = 0x10
KEYEVENTF_EXTENDEDKEY = 0x0001

_u32 = ctypes.windll.user32


def _send_inputs(*vk_sequence) -> None:
    """Send a sequence of (vk, flags) tuples via SendInput."""
    n = len(vk_sequence)
    inputs = (_INPUT * n)()
    for i, (vk, flags) in enumerate(vk_sequence):
        inputs[i] = _INPUT(
            type=INPUT_KEYBOARD,
            _input=_INPUT_UNION(
                ki=_KEYBDINPUT(wVk=vk, wScan=0, dwFlags=flags, time=0, dwExtraInfo=None)
            ),
        )
    _u32.SendInput(n, inputs, ctypes.sizeof(_INPUT))


def _shift_select_left(n: int) -> None:
    """Hold Shift, press Left n times, release Shift."""
    if n <= 0:
        return
    seq = [(VK_SHIFT, 0)]
    for _ in range(n):
        seq.append((VK_LEFT, KEYEVENTF_EXTENDEDKEY))
        seq.append((VK_LEFT, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP))
    seq.append((VK_SHIFT, KEYEVENTF_KEYUP))
    _send_inputs(*seq)


def _ctrl_c() -> None:
    _send_inputs(
        (VK_CONTROL, 0),
        (VK_C, 0),
        (VK_C, KEYEVENTF_KEYUP),
        (VK_CONTROL, KEYEVENTF_KEYUP),
    )


def _press_right() -> None:
    _send_inputs(
        (VK_RIGHT, KEYEVENTF_EXTENDEDKEY),
        (VK_RIGHT, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP),
    )


# ── Low-level keyboard hook (WH_KEYBOARD_LL) — no elevation needed ───────────
WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104

HOOKPROC = ctypes.CFUNCTYPE(ctypes.c_long, ctypes.c_int, wt.WPARAM, wt.LPARAM)


class _KeyboardActivityMonitor:
    """Installs a WH_KEYBOARD_LL hook that records the last key-press time."""

    def __init__(self) -> None:
        self.last_activity: float = 0.0
        self._hook_id = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._cb_ref = None  # keep CFUNCTYPE alive

    def start(self) -> None:
        self._running = True
        self.last_activity = time.time()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="kb-activity-hook"
        )
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def _run(self) -> None:
        def _hook_cb(nCode, wParam, lParam):
            if nCode >= 0 and wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                self.last_activity = time.time()
            return _u32.CallNextHookEx(None, nCode, wParam, lParam)

        self._cb_ref = HOOKPROC(_hook_cb)
        self._hook_id = _u32.SetWindowsHookExW(WH_KEYBOARD_LL, self._cb_ref, None, 0)

        msg = wt.MSG()
        while self._running:
            if _u32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                _u32.TranslateMessage(ctypes.byref(msg))
                _u32.DispatchMessageW(ctypes.byref(msg))
            else:
                time.sleep(0.02)

        if self._hook_id:
            _u32.UnhookWindowsHookEx(self._hook_id)
            self._hook_id = None


# ── Public class ─────────────────────────────────────────────────────────────


class CorrectionTracker:
    """Watches for user corrections after text insertion and learns word replacements."""

    _WINDOW = 20.0  # seconds to watch after insert
    _IDLE = 3.0  # seconds of keyboard silence before finalising
    _MAX_N = 200  # max chars to snapshot
    _PUNCT = ".,!?;:\"'()[]{}\u2026\u2013\u2014-"

    def __init__(self, vocab: VocabularyManager) -> None:
        self._vocab = vocab
        self._original: str = ""
        self._alive = False
        self._deadline: float = 0.0
        self._monitor: _KeyboardActivityMonitor | None = None
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
        self._after_fn = after_fn
        self._notify_fn = notify_fn
        self._monitor = _KeyboardActivityMonitor()
        self._monitor.start()
        after_fn(500, self._capture_baseline)

    def stop(self) -> None:
        self._alive = False
        if self._monitor is not None:
            self._monitor.stop()
            self._monitor = None

    def _capture_snapshot(self, n: int) -> str:
        n = min(max(n, 0), self._MAX_N)
        if n == 0:
            return ""
        try:
            old = _get_clipboard_text() or ""
            _set_clipboard_text("")
            _shift_select_left(n)
            time.sleep(0.06)
            _ctrl_c()
            time.sleep(0.09)
            result = _get_clipboard_text() or ""
            _press_right()
            time.sleep(0.03)
            if old:
                _set_clipboard_text(old)
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
        last = self._monitor.last_activity if self._monitor else 0.0
        if self._baseline_ok and (time.time() - last) >= self._IDLE:
            self._alive = False
            if self._monitor:
                self._monitor.stop()
                self._monitor = None
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
