import difflib
import threading
import time

import keyboard
import pyperclip

from vocabulary import VocabularyManager


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
