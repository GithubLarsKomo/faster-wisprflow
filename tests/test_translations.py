"""Tests for ui/translations.py — completeness and consistency."""

import pytest

from ui.translations import LANG_CODES, TRANSLATIONS

# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------


def test_all_lang_codes_have_entry():
    for code in LANG_CODES:
        assert code in TRANSLATIONS, f"Missing language dict for '{code}'"


def test_no_extra_keys_missing_in_other_langs():
    """Every language must have the same set of keys as German (the reference)."""
    reference_keys = set(TRANSLATIONS["de"].keys())
    for code in LANG_CODES:
        if code == "de":
            continue
        lang_keys = set(TRANSLATIONS[code].keys())
        missing = reference_keys - lang_keys
        extra = lang_keys - reference_keys
        assert not missing, f"[{code}] missing keys: {sorted(missing)}"
        assert not extra, f"[{code}] unexpected extra keys: {sorted(extra)}"


def test_no_empty_translations():
    for code, d in TRANSLATIONS.items():
        for key, value in d.items():
            assert value, f"[{code}][{key}] is empty"


def test_lang_codes_list_matches_translations_keys():
    assert set(LANG_CODES) == set(TRANSLATIONS.keys())


# ---------------------------------------------------------------------------
# Required keys exist
# ---------------------------------------------------------------------------

_REQUIRED_KEYS = [
    # General UI
    "title",
    "btn_save",
    "btn_close",
    "btn_factory",
    # Messagebox translations
    "msg_saved_title",
    "msg_saved_body",
    "msg_factory_title",
    "msg_factory_confirm",
    "msg_factory_done",
    "msg_mic_fail_title",
    "msg_mic_title",
    "msg_mic_low_level",
    "msg_mic_ok",
    "msg_health_fail_title",
    "msg_whisper_fail_title",
    "msg_whisper_title",
    "msg_whisper_no_text",
    "msg_llm_test_title",
    "msg_llm_test_missing",
    "msg_llm_fail_title",
    "msg_llm_title",
    "msg_llm_result",
    # Runtime error messages
    "msg_error",
    "msg_no_audio",
    "msg_no_speech",
    "msg_result_title",
    # Tray / startup
    "tray_settings",
    "tray_quit",
    "msg_already_running",
]


@pytest.mark.parametrize("key", _REQUIRED_KEYS)
def test_required_key_present_in_all_langs(key):
    for code in LANG_CODES:
        assert key in TRANSLATIONS[code], f"[{code}] missing required key '{key}'"


# ---------------------------------------------------------------------------
# Spot-check: German reference values
# ---------------------------------------------------------------------------


def test_de_save_button():
    assert TRANSLATIONS["de"]["btn_save"] == "Speichern"


def test_en_save_button():
    assert TRANSLATIONS["en"]["btn_save"] == "Save"


def test_de_title():
    assert "FlüsterFee" in TRANSLATIONS["de"]["title"]
