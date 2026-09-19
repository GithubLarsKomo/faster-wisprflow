"""Tests for text_inserter.py — clipboard helpers and TextInserter."""

import ctypes
from unittest.mock import MagicMock, call, patch

import pytest

from tests.conftest import make_stub_config
from text_inserter import (
    TextInserter,
    _foreground_exe,
    _get_clipboard_text,
    _set_clipboard_text,
)

# ---------------------------------------------------------------------------
# _foreground_exe
# ---------------------------------------------------------------------------


class TestForegroundExe:
    def test_returns_exe_name_lowercased(self):
        mock_u32 = MagicMock()
        mock_u32.GetForegroundWindow.return_value = 1
        mock_u32.GetWindowThreadProcessId.return_value = 0

        mock_k32 = MagicMock()
        mock_k32.OpenProcess.return_value = 1  # non-zero → success

        buf_instance = ctypes.create_unicode_buffer("C:\\Windows\\winword.EXE")

        def fake_create_unicode_buffer(n):
            return buf_instance

        with (
            patch("text_inserter._u32", mock_u32),
            patch("text_inserter._k32", mock_k32),
            patch("ctypes.create_unicode_buffer", fake_create_unicode_buffer),
        ):
            # Simulate GetModuleFileNameExW writing into the buffer
            mock_k32.GetModuleFileNameExW.side_effect = lambda h, m, b, n: None
            buf_instance.value = "C:\\Windows\\WINWORD.EXE"
            result = _foreground_exe()

        assert result == "winword.exe"

    def test_returns_empty_on_null_process_handle(self):
        mock_u32 = MagicMock()
        mock_u32.GetForegroundWindow.return_value = 1
        mock_k32 = MagicMock()
        mock_k32.OpenProcess.return_value = 0  # null handle

        with (
            patch("text_inserter._u32", mock_u32),
            patch("text_inserter._k32", mock_k32),
        ):
            assert _foreground_exe() == ""

    def test_returns_empty_on_exception(self):
        with patch("text_inserter._u32") as m:
            m.GetForegroundWindow.side_effect = OSError("fail")
            assert _foreground_exe() == ""


# ---------------------------------------------------------------------------
# _set_clipboard_text
# ---------------------------------------------------------------------------


class TestSetClipboardText:
    def _mock_win32(self, open_returns=True):
        u32 = MagicMock()
        k32 = MagicMock()
        u32.OpenClipboard.return_value = 1 if open_returns else 0
        k32.GlobalAlloc.return_value = 1
        k32.GlobalLock.return_value = ctypes.c_void_p(1)
        return u32, k32

    def test_returns_true_on_success(self):
        u32, k32 = self._mock_win32()
        with patch("text_inserter._u32", u32), patch("text_inserter._k32", k32):
            with patch("ctypes.memmove"):
                assert _set_clipboard_text("hello") is True
        u32.EmptyClipboard.assert_called_once()
        u32.SetClipboardData.assert_called_once()
        u32.CloseClipboard.assert_called()

    def test_returns_false_when_clipboard_wont_open(self):
        u32, k32 = self._mock_win32(open_returns=False)
        with (
            patch("text_inserter._u32", u32),
            patch("text_inserter._k32", k32),
            patch("text_inserter.time.sleep"),
        ):
            assert _set_clipboard_text("hello", retries=2) is False

    def test_returns_false_when_global_alloc_fails(self):
        u32, k32 = self._mock_win32()
        k32.GlobalAlloc.return_value = 0  # failure
        with patch("text_inserter._u32", u32), patch("text_inserter._k32", k32):
            assert _set_clipboard_text("hello") is False


# ---------------------------------------------------------------------------
# _get_clipboard_text
# ---------------------------------------------------------------------------


class TestGetClipboardText:
    def test_returns_text_on_success(self):
        u32 = MagicMock()
        k32 = MagicMock()
        u32.OpenClipboard.return_value = 1
        u32.GetClipboardData.return_value = 1  # non-null handle
        k32.GlobalLock.return_value = ctypes.c_void_p(1)

        with (
            patch("text_inserter._u32", u32),
            patch("text_inserter._k32", k32),
            patch("ctypes.wstring_at", return_value="clipboard content"),
        ):
            result = _get_clipboard_text()

        assert result == "clipboard content"

    def test_returns_none_when_no_data(self):
        u32 = MagicMock()
        u32.OpenClipboard.return_value = 1
        u32.GetClipboardData.return_value = 0  # null → no CF_UNICODETEXT

        with patch("text_inserter._u32", u32), patch("text_inserter._k32", MagicMock()):
            result = _get_clipboard_text()

        assert result is None

    def test_returns_none_when_clipboard_closed(self):
        u32 = MagicMock()
        u32.OpenClipboard.return_value = 0  # can't open
        with (
            patch("text_inserter._u32", u32),
            patch("text_inserter._k32", MagicMock()),
            patch("text_inserter.time.sleep"),
        ):
            assert _get_clipboard_text() is None


# ---------------------------------------------------------------------------
# TextInserter.insert_text
# ---------------------------------------------------------------------------


class TestTextInserter:
    def _make(self, **kw):
        return TextInserter(make_stub_config(**kw))

    def test_early_return_on_empty(self):
        ti = self._make()
        with patch("text_inserter._set_clipboard_text") as mock_set:
            ti.insert_text("")
            mock_set.assert_not_called()

    def test_calls_set_clipboard(self):
        ti = self._make(restore_clipboard=False)
        with (
            patch("text_inserter._set_clipboard_text", return_value=True) as mock_set,
            patch("text_inserter._send_ctrl_v"),
            patch("text_inserter._foreground_exe", return_value="notepad.exe"),
            patch("text_inserter.time.sleep"),
        ):
            ti.insert_text("hello world")
            mock_set.assert_called_once_with("hello world")

    def test_restores_clipboard_when_enabled(self):
        ti = self._make(restore_clipboard=True)
        set_calls = []
        get_calls = [0]

        def fake_set(text, *args, **kwargs):
            set_calls.append(text)
            return True

        # First _get_clipboard_text call returns the original "old" clipboard;
        # second call (after the paste, used as a guard before restoring)
        # returns the text we just wrote — so the inserter knows nothing
        # else copied over our text in the meantime and proceeds to restore.
        def fake_get():
            get_calls[0] += 1
            return "new text" if get_calls[0] > 1 else "old"

        with (
            patch("text_inserter._get_clipboard_text", side_effect=fake_get),
            patch("text_inserter._set_clipboard_text", side_effect=fake_set),
            patch("text_inserter._send_ctrl_v"),
            patch("text_inserter._foreground_exe", return_value="notepad.exe"),
            patch("text_inserter.time.sleep"),
        ):
            ti.insert_text("new text")

        assert set_calls[0] == "new text"
        assert set_calls[1] == "old"  # restored

    def test_no_restore_when_disabled(self):
        ti = self._make(restore_clipboard=False)
        set_calls = []

        with (
            patch("text_inserter._get_clipboard_text", return_value="old") as mock_get,
            patch(
                "text_inserter._set_clipboard_text",
                side_effect=lambda t, *a, **kw: set_calls.append(t) or True,
            ),
            patch("text_inserter._send_ctrl_v"),
            patch("text_inserter._foreground_exe", return_value="notepad.exe"),
            patch("text_inserter.time.sleep"),
        ):
            ti.insert_text("new text")
            mock_get.assert_not_called()

        # Only one set call: the text to paste
        assert set_calls == ["new text"]

    def test_word_extra_delay_applied(self):
        ti = self._make(restore_clipboard=False)
        sleep_calls = []

        with (
            patch("text_inserter._set_clipboard_text", return_value=True),
            patch("text_inserter._send_ctrl_v"),
            patch("text_inserter._foreground_exe", return_value="winword.exe"),
            patch(
                "text_inserter.time.sleep", side_effect=lambda d: sleep_calls.append(d)
            ),
        ):
            ti.insert_text("test")

        total_sleep = sum(sleep_calls)
        assert total_sleep >= 0.15 + TextInserter.WORD_EXTRA_DELAY

    def test_no_word_extra_delay_for_notepad(self):
        ti = self._make(restore_clipboard=False)
        sleep_calls = []

        with (
            patch("text_inserter._set_clipboard_text", return_value=True),
            patch("text_inserter._send_ctrl_v"),
            patch("text_inserter._foreground_exe", return_value="notepad.exe"),
            patch(
                "text_inserter.time.sleep", side_effect=lambda d: sleep_calls.append(d)
            ),
        ):
            ti.insert_text("test")

        total_sleep = sum(sleep_calls)
        # New timing: 0.12s pre-paste + 0.25s post-paste (+ WORD_EXTRA_DELAY
        # if Word is the foreground app). 0.37s total for non-Word targets.
        assert total_sleep < 0.12 + 0.25 + TextInserter.WORD_EXTRA_DELAY + 0.05

    def test_guidance_capitalizes_after_sentence_punctuation(self):
        ti = self._make(
            restore_clipboard=False,
            transcription_guidance_enabled=True,
        )
        with (
            patch.object(ti, "_peek_previous_non_space_char", return_value="."),
            patch("text_inserter._set_clipboard_text", return_value=True) as mock_set,
            patch("text_inserter._send_ctrl_v"),
            patch("text_inserter._foreground_exe", return_value="notepad.exe"),
            patch("text_inserter.time.sleep"),
        ):
            ti.insert_text("hallo welt")

        mock_set.assert_called_once_with("Hallo welt")

    def test_guidance_keeps_case_after_non_sentence_context(self):
        ti = self._make(
            restore_clipboard=False,
            transcription_guidance_enabled=True,
        )
        with (
            patch.object(ti, "_peek_previous_non_space_char", return_value=","),
            patch("text_inserter._set_clipboard_text", return_value=True) as mock_set,
            patch("text_inserter._send_ctrl_v"),
            patch("text_inserter._foreground_exe", return_value="notepad.exe"),
            patch("text_inserter.time.sleep"),
        ):
            ti.insert_text("hallo welt")

        mock_set.assert_called_once_with("hallo welt")

    def test_guidance_disabled_skips_cursor_probe(self):
        ti = self._make(
            restore_clipboard=False,
            transcription_guidance_enabled=False,
        )
        with (
            patch.object(ti, "_peek_previous_non_space_char") as mock_probe,
            patch("text_inserter._set_clipboard_text", return_value=True),
            patch("text_inserter._send_ctrl_v"),
            patch("text_inserter._foreground_exe", return_value="notepad.exe"),
            patch("text_inserter.time.sleep"),
        ):
            ti.insert_text("hallo welt")

        mock_probe.assert_not_called()


# ---------------------------------------------------------------------------
# cursor-context probe
# ---------------------------------------------------------------------------


class TestCursorContextProbe:
    def test_peek_restores_caret_with_single_right_collapse(self):
        ti = TextInserter(make_stub_config(transcription_guidance_enabled=True))

        with (
            patch(
                "text_inserter._get_clipboard_text",
                side_effect=["saved clipboard", "abc"],
            ),
            patch("text_inserter._set_clipboard_text", return_value=True),
            patch("text_inserter._send_shift_left") as mock_shift_left,
            patch("text_inserter._send_ctrl_c") as mock_copy,
            patch("text_inserter._send_right") as mock_right,
            patch("text_inserter.time.sleep"),
        ):
            result = ti._peek_previous_non_space_char(lookback=3)

        assert result == "c"
        assert mock_shift_left.call_count == 3
        mock_copy.assert_called_once_with()
        mock_right.assert_called_once_with()
