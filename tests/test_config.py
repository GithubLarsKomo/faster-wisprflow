"""Tests for config.py — _build_base_url, load_config, save_config, Config."""

import json
from pathlib import Path

from config import (
    DEFAULT_CONFIG,
    Config,
    _build_base_url,
    auto_elevate_if_needed,
    load_config,
    save_config,
)

# ---------------------------------------------------------------------------
# _build_base_url
# ---------------------------------------------------------------------------


class TestBuildBaseUrl:
    def test_url_and_port(self):
        assert _build_base_url("http://localhost", 8009) == "http://localhost:8009"

    def test_url_with_trailing_slash(self):
        assert _build_base_url("http://localhost/", 8009) == "http://localhost:8009"

    def test_no_port_zero(self):
        assert _build_base_url("http://localhost", 0) == "http://localhost"

    def test_no_port_none(self):
        assert _build_base_url("http://localhost", None) == "http://localhost"

    def test_no_port_empty_string(self):
        assert _build_base_url("http://localhost", "") == "http://localhost"

    def test_port_as_string(self):
        assert _build_base_url("http://host", "11434") == "http://host:11434"

    def test_non_numeric_port_treated_as_zero(self):
        assert _build_base_url("http://host", "abc") == "http://host"

    def test_openrouter_style(self):
        assert _build_base_url("https://openrouter.ai", 0) == "https://openrouter.ai"


# ---------------------------------------------------------------------------
# load_config / save_config
# ---------------------------------------------------------------------------


class TestLoadConfig:
    def test_creates_file_when_missing(self, tmp_config_path):
        assert not tmp_config_path.exists()
        data = load_config()
        assert tmp_config_path.exists()
        assert data["language"] == DEFAULT_CONFIG["language"]

    def test_merges_partial_file(self, tmp_config_path):
        tmp_config_path.write_text(json.dumps({"language": "en"}), encoding="utf-8")
        data = load_config()
        # Custom value
        assert data["language"] == "en"
        # Filled in from defaults
        assert data["sample_rate"] == DEFAULT_CONFIG["sample_rate"]

    def test_unknown_keys_are_kept(self, tmp_config_path):
        tmp_config_path.write_text(
            json.dumps({"my_custom_key": "hello"}), encoding="utf-8"
        )
        data = load_config()
        assert data["my_custom_key"] == "hello"


class TestSaveConfig:
    def test_saves_json(self, tmp_config_path):
        save_config({"language": "fr", "port": 9000})
        raw = json.loads(tmp_config_path.read_text(encoding="utf-8"))
        assert raw["language"] == "fr"
        assert raw["port"] == 9000

    def test_unicode_preserved(self, tmp_config_path):
        save_config({"prompt": "Ärger mit Übergröße"})
        raw = tmp_config_path.read_text(encoding="utf-8")
        assert "Ärger" in raw


# ---------------------------------------------------------------------------
# Config class
# ---------------------------------------------------------------------------


class TestConfigClass:
    def test_reload_reads_values(self, tmp_config_path):
        tmp_config_path.write_text(
            json.dumps({**DEFAULT_CONFIG, "language": "pl"}), encoding="utf-8"
        )
        cfg = Config()
        assert cfg.language == "pl"

    def test_defaults_when_file_missing(self, tmp_config_path):
        cfg = Config()
        assert cfg.sample_rate == DEFAULT_CONFIG["sample_rate"]
        assert cfg.channels == DEFAULT_CONFIG["channels"]

    def test_hotkey_keys_is_list(self, tmp_config_path):
        cfg = Config()
        assert isinstance(cfg.hotkey_keys, list)

    def test_restore_clipboard_is_bool(self, tmp_config_path):
        cfg = Config()
        assert isinstance(cfg.restore_clipboard, bool)

    def test_correction_mode_defaults_to_smart(self, tmp_config_path):
        cfg = Config()
        assert cfg.correction_mode == "smart"

    def test_invalid_correction_mode_falls_back_to_smart(self, tmp_config_path):
        tmp_config_path.write_text(
            json.dumps({**DEFAULT_CONFIG, "correction_mode": "mystery"}),
            encoding="utf-8",
        )
        cfg = Config()
        assert cfg.correction_mode == "smart"

    def test_reload_updates_attributes(self, tmp_config_path):
        cfg = Config()
        tmp_config_path.write_text(
            json.dumps({**DEFAULT_CONFIG, "language": "it"}), encoding="utf-8"
        )
        cfg.reload()
        assert cfg.language == "it"


# ---------------------------------------------------------------------------
# auto_elevate_if_needed is a no-op
# ---------------------------------------------------------------------------


def test_auto_elevate_is_noop():
    """Should not raise or exit regardless of the config value."""
    auto_elevate_if_needed({"auto_elevate": True})
    auto_elevate_if_needed({"auto_elevate": False})
    auto_elevate_if_needed({})


# ---------------------------------------------------------------------------
# repository config contract
# ---------------------------------------------------------------------------


def test_example_config_matches_defaults():
    example_path = Path(__file__).resolve().parents[1] / "config.example.json"
    example = json.loads(example_path.read_text(encoding="utf-8"))
    assert example == DEFAULT_CONFIG


def test_defaults_are_portable_and_do_not_advertise_noop_options():
    assert DEFAULT_CONFIG["whisper_url"] == "http://127.0.0.1"
    assert DEFAULT_CONFIG["correction_url"] == "http://127.0.0.1"
    assert "auto_elevate" not in DEFAULT_CONFIG
    assert "start_with_windows" not in DEFAULT_CONFIG
    assert "whisper_token" not in DEFAULT_CONFIG
    assert "correction_token" not in DEFAULT_CONFIG
