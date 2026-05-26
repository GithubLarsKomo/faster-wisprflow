"""Shared fixtures for all test modules."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Config / Vocabulary path isolation
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_config_path(tmp_path, monkeypatch):
    """Redirect config.CONFIG_PATH to a temp file so tests never touch config.json."""
    cfg_path = tmp_path / "config.json"
    monkeypatch.setattr("config.CONFIG_PATH", cfg_path)
    return cfg_path


@pytest.fixture()
def tmp_vocab_path(tmp_path, monkeypatch):
    """Redirect vocabulary.VOCAB_PATH (and config.VOCAB_PATH) to a temp file."""
    vp = tmp_path / "vocabulary.json"
    monkeypatch.setattr("config.VOCAB_PATH", vp)
    monkeypatch.setattr("vocabulary.VOCAB_PATH", vp)
    return vp


@pytest.fixture()
def tmp_paths(tmp_path, monkeypatch):
    """Redirect BOTH config and vocabulary paths at once."""
    cfg_path = tmp_path / "config.json"
    vp = tmp_path / "vocabulary.json"
    monkeypatch.setattr("config.CONFIG_PATH", cfg_path)
    monkeypatch.setattr("config.VOCAB_PATH", vp)
    monkeypatch.setattr("vocabulary.VOCAB_PATH", vp)
    return cfg_path, vp


# ---------------------------------------------------------------------------
# Minimal stub Config (no disk I/O)
# ---------------------------------------------------------------------------


def make_stub_config(**overrides):
    """Return a simple namespace that mimics Config attributes."""
    defaults = dict(
        whisper_url="http://localhost",
        port=8009,
        whisper_token="",
        whisper_model="whisper-large-v3-turbo",
        whisper_provider="lokal",
        transcription_guidance_enabled=False,
        whisper_endpoint="transcribe",
        health_endpoint="health",
        language="de",
        response_format="text",
        sample_rate=16000,
        channels=1,
        input_device=None,
        hotkey_keys=["ctrl", "linke windows"],
        restore_clipboard=True,
        audio_filename="recording.wav",
        correction_enabled=True,
        correction_url="http://localhost",
        correction_port=11434,
        correction_token="",
        correction_model="my-model",
        llm_provider="Ollama",
        temperature=0,
        top_p=1,
        num_predict=220,
        num_ctx=1024,
        repeat_penalty=1.0,
        max_tokens=220,
        system_prompt="You are a helper in {{language}}.",
        proxy="",
    )
    defaults.update(overrides)
    cfg = MagicMock()
    for k, v in defaults.items():
        setattr(cfg, k, v)
    return cfg
