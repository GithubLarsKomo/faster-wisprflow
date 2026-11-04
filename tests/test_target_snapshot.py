"""Fail-closed target binding; no real foreground Windows changes in tests."""

from unittest.mock import patch

from target_window import TargetSnapshot, capture_target, validate_target


BASE = TargetSnapshot(
    hwnd=101, pid=202, process_created_100ns=303,
    focus_hwnd=404, exe_name="winword.exe",
)


def test_equal_capture_matches_without_window_title_or_document():
    with patch("target_window._read_foreground", return_value=BASE):
        assert capture_target() == BASE
        assert validate_target(BASE)


def test_fail_closed_if_target_missing_or_uninspectable():
    assert not validate_target(None)
    with patch("target_window._read_foreground", return_value=None):
        assert not validate_target(BASE)
    with patch("target_window._read_foreground", side_effect=OSError("access denied")):
        assert capture_target() is None
        assert not validate_target(BASE)


def test_hwnd_changes_even_with_same_exe():
    after = TargetSnapshot(102, 202, 303, 404, "winword.exe")
    with patch("target_window._read_foreground", return_value=after):
        assert not validate_target(BASE)


def test_process_reuse_is_rejected():
    after = TargetSnapshot(101, 202, 304, 404, "winword.exe")
    with patch("target_window._read_foreground", return_value=after):
        assert not validate_target(BASE)


def test_same_window_different_focused_control_rejected():
    after = TargetSnapshot(101, 202, 303, 405, "winword.exe")
    with patch("target_window._read_foreground", return_value=after):
        assert not validate_target(BASE)


def test_changed_process_pid_rejected():
    after = TargetSnapshot(101, 203, 303, 404, "winword.exe")
    with patch("target_window._read_foreground", return_value=after):
        assert not validate_target(BASE)


def test_context_key_keeps_process_birth_identity_no_title():
    assert BASE.context_key == "202:303:winword.exe"
