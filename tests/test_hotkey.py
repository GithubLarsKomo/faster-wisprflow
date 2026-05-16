"""Tests for hotkey.py — _parse_hotkey, _any_pressed, _VK_MAP."""

from unittest.mock import patch

import pytest

from hotkey import (
    _VK_MAP,
    MOD_ALT,
    MOD_CONTROL,
    MOD_NOREPEAT,
    MOD_SHIFT,
    MOD_WIN,
    _any_pressed,
    _parse_hotkey,
)

# ---------------------------------------------------------------------------
# _VK_MAP sanity checks
# ---------------------------------------------------------------------------


class TestVkMap:
    def test_letters_map_to_uppercase_ord(self):
        assert _VK_MAP["a"] == ord("A")
        assert _VK_MAP["z"] == ord("Z")

    def test_digits(self):
        assert _VK_MAP["0"] == ord("0")
        assert _VK_MAP["9"] == ord("9")

    def test_function_keys(self):
        assert _VK_MAP["f1"] == 0x70
        assert _VK_MAP["f12"] == 0x7B
        assert _VK_MAP["f24"] == 0x87

    def test_special_keys_present(self):
        for name in ("space", "tab", "return", "enter", "escape", "backspace"):
            assert name in _VK_MAP, f"Missing VK for '{name}'"


# ---------------------------------------------------------------------------
# _parse_hotkey
# ---------------------------------------------------------------------------


class TestParseHotkey:
    def _mods(self, keys):
        mods, _ = _parse_hotkey(keys)
        # Mask out MOD_NOREPEAT to test only functional mods
        return mods & ~MOD_NOREPEAT

    def _vk(self, keys):
        _, vk = _parse_hotkey(keys)
        return vk

    def test_ctrl_sets_mod_control(self):
        assert self._mods(["ctrl"]) == MOD_CONTROL

    def test_control_alias(self):
        assert self._mods(["control"]) == MOD_CONTROL

    def test_shift(self):
        assert self._mods(["shift"]) == MOD_SHIFT

    def test_alt(self):
        assert self._mods(["alt"]) == MOD_ALT

    def test_win(self):
        assert self._mods(["win"]) == MOD_WIN

    def test_linke_windows(self):
        assert self._mods(["linke windows"]) == MOD_WIN

    def test_left_windows(self):
        assert self._mods(["left windows"]) == MOD_WIN

    def test_rechte_windows(self):
        assert self._mods(["rechte windows"]) == MOD_WIN

    def test_ctrl_plus_linke_windows(self):
        mods = self._mods(["ctrl", "linke windows"])
        assert mods & MOD_CONTROL
        assert mods & MOD_WIN

    def test_ctrl_shift_alt(self):
        mods = self._mods(["ctrl", "shift", "alt"])
        assert mods & MOD_CONTROL
        assert mods & MOD_SHIFT
        assert mods & MOD_ALT

    def test_regular_letter_as_vk(self):
        assert self._vk(["ctrl", "a"]) == ord("A")

    def test_f5_as_vk(self):
        assert self._vk(["ctrl", "f5"]) == 0x74

    def test_unknown_key_vk_zero(self):
        assert self._vk(["ctrl", "xyzunknown"]) == 0

    def test_mod_norepeat_always_set(self):
        mods, _ = _parse_hotkey(["ctrl"])
        assert mods & MOD_NOREPEAT

    def test_no_keys_returns_zero_vk(self):
        _, vk = _parse_hotkey([])
        assert vk == 0

    def test_whitespace_trimmed(self):
        assert self._mods(["  ctrl  "]) == MOD_CONTROL


# ---------------------------------------------------------------------------
# _any_pressed (mocked GetAsyncKeyState)
# ---------------------------------------------------------------------------


class TestAnyPressed:
    def test_returns_true_when_key_down(self):
        with patch("hotkey.ctypes.windll.user32.GetAsyncKeyState", return_value=0x8000):
            assert _any_pressed([0x11]) is True

    def test_returns_false_when_key_up(self):
        with patch("hotkey.ctypes.windll.user32.GetAsyncKeyState", return_value=0x0000):
            assert _any_pressed([0x11]) is False

    def test_returns_true_if_any_in_list(self):
        def side(vk):
            return 0x8000 if vk == 0xA2 else 0x0000

        with patch("hotkey.ctypes.windll.user32.GetAsyncKeyState", side_effect=side):
            assert _any_pressed([0x11, 0xA2, 0xA3]) is True

    def test_empty_list_returns_false(self):
        assert _any_pressed([]) is False
