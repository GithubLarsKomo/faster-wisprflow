"""Tests for correction_tracker.py — _word_diff and CorrectionTracker lifecycle."""

from unittest.mock import MagicMock, patch

import pytest

from correction_tracker import CorrectionTracker, _shift_select_left, _ctrl_c, _press_right
from vocabulary import VocabularyManager


# ---------------------------------------------------------------------------
# _word_diff (pure, no I/O)
# ---------------------------------------------------------------------------

class TestWordDiff:
    def test_simple_substitution(self):
        # Different words (not just different case) must be captured
        pairs = CorrectionTracker._word_diff("hallo welt", "hello welt")
        assert ("hallo", "hello") in pairs

    def test_no_diff_when_same(self):
        pairs = CorrectionTracker._word_diff("same text here", "same text here")
        assert pairs == []

    def test_ignores_insertions(self):
        # Insertion is not a 1:1 replace
        pairs = CorrectionTracker._word_diff("one two", "one extra two")
        assert pairs == []

    def test_ignores_deletions(self):
        pairs = CorrectionTracker._word_diff("one two three", "one three")
        assert pairs == []

    def test_punctuation_stripped_from_pair(self):
        # Punctuation is stripped; the underlying words must differ in lowercase
        pairs = CorrectionTracker._word_diff("hallo,", "hello,")
        assert ("hallo", "hello") in pairs

    def test_case_only_changes_filtered(self):
        # _word_diff ignores pairs that differ only in case (orig.lower() == corr.lower())
        pairs = CorrectionTracker._word_diff("hello world", "Hello world")
        assert pairs == []

    def test_multiple_substitutions(self):
        pairs = CorrectionTracker._word_diff("alpha beta", "ALPHA BETA")
        # both lowercase the same → filtered → empty
        assert pairs == []

    def test_multiple_real_substitutions(self):
        # Surrounding common words give SequenceMatcher enough context
        # to produce individual 1:1 replace opcodes for each changed word
        pairs = CorrectionTracker._word_diff(
            "one foo two bar three",
            "one baz two qux three",
        )
        assert len(pairs) == 2
        assert ("foo", "baz") in pairs
        assert ("bar", "qux") in pairs

    def test_empty_strings(self):
        assert CorrectionTracker._word_diff("", "") == []


# ---------------------------------------------------------------------------
# CorrectionTracker.start / stop
# ---------------------------------------------------------------------------

class TestCorrectionTrackerLifecycle:
    def _vm(self, tmp_vocab_path) -> VocabularyManager:
        return VocabularyManager()

    def test_start_with_empty_text_does_nothing(self, tmp_vocab_path):
        vm = self._vm(tmp_vocab_path)
        ct = CorrectionTracker(vm)
        after_fn = MagicMock()

        with patch("correction_tracker._KeyboardActivityMonitor") as mock_mon:
            ct.start("   ", after_fn)
            mock_mon.assert_not_called()

        after_fn.assert_not_called()

    def test_start_installs_monitor(self, tmp_vocab_path):
        vm = self._vm(tmp_vocab_path)
        ct = CorrectionTracker(vm)
        after_fn = MagicMock()

        with patch("correction_tracker._KeyboardActivityMonitor") as mock_mon_cls:
            mock_mon = MagicMock()
            mock_mon_cls.return_value = mock_mon
            ct.start("some text", after_fn)

        mock_mon.start.assert_called_once()
        after_fn.assert_called_once()  # schedules _capture_baseline

    def test_stop_releases_monitor(self, tmp_vocab_path):
        vm = self._vm(tmp_vocab_path)
        ct = CorrectionTracker(vm)
        after_fn = MagicMock()

        with patch("correction_tracker._KeyboardActivityMonitor") as mock_mon_cls:
            mock_mon = MagicMock()
            mock_mon_cls.return_value = mock_mon
            ct.start("some text", after_fn)
            ct.stop()

        mock_mon.stop.assert_called_once()
        assert ct._monitor is None
        assert ct._alive is False

    def test_double_stop_is_safe(self, tmp_vocab_path):
        vm = self._vm(tmp_vocab_path)
        ct = CorrectionTracker(vm)
        ct.stop()  # stop without start → must not raise
        ct.stop()


# ---------------------------------------------------------------------------
# CorrectionTracker._poll — deadline expiry
# ---------------------------------------------------------------------------

class TestPoll:
    def test_poll_stops_on_deadline(self, tmp_vocab_path):
        import time as _time
        vm = VocabularyManager()
        ct = CorrectionTracker(vm)
        ct._alive = True
        ct._baseline_ok = True
        ct._deadline = _time.time() - 1  # already expired
        after_fn = MagicMock()
        ct._after_fn = after_fn

        with patch("correction_tracker._KeyboardActivityMonitor"):
            ct._poll()

        assert ct._alive is False
        after_fn.assert_not_called()


# ---------------------------------------------------------------------------
# SendInput helpers — only check they don't raise with mocked SendInput
# ---------------------------------------------------------------------------

class TestSendInputHelpers:
    def _patch_send(self):
        return patch("correction_tracker._u32")

    def test_shift_select_left_n_zero_is_noop(self):
        with self._patch_send() as mock_u32:
            _shift_select_left(0)
            mock_u32.SendInput.assert_not_called()

    def test_shift_select_left_sends_inputs(self):
        with self._patch_send() as mock_u32:
            _shift_select_left(3)
            assert mock_u32.SendInput.call_count == 1
            # First arg is the count: 1 Shift-down + 3*(Left-dn+Left-up) + 1 Shift-up = 8
            args = mock_u32.SendInput.call_args[0]
            assert args[0] == 8

    def test_ctrl_c_sends_4_inputs(self):
        with self._patch_send() as mock_u32:
            _ctrl_c()
            args = mock_u32.SendInput.call_args[0]
            assert args[0] == 4

    def test_press_right_sends_2_inputs(self):
        with self._patch_send() as mock_u32:
            _press_right()
            args = mock_u32.SendInput.call_args[0]
            assert args[0] == 2
