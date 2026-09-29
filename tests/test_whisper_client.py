"""Tests for whisper_client.py — WhisperClient."""

import json
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest
import requests

from tests.conftest import make_stub_config
from whisper_client import WhisperClient

# ---------------------------------------------------------------------------
# _proxies
# ---------------------------------------------------------------------------


class TestProxies:
    def test_empty_proxy_bypasses(self):
        wc = WhisperClient(make_stub_config(proxy=""))
        assert wc._proxies() == {"http": None, "https": None}

    def test_proxy_url_forwarded(self):
        wc = WhisperClient(make_stub_config(proxy="http://proxy:3128"))
        p = wc._proxies()
        assert p["http"] == "http://proxy:3128"
        assert p["https"] == "http://proxy:3128"


# ---------------------------------------------------------------------------
# transcribe — routing
# ---------------------------------------------------------------------------


class TestTranscribeRouting:
    def test_routes_to_openrouter(self):
        wc = WhisperClient(make_stub_config(whisper_provider="Openrouter"))
        with patch.object(wc, "_transcribe_openrouter", return_value="text") as m:
            result = wc.transcribe(Path("audio.wav"))
        m.assert_called_once_with(Path("audio.wav"))
        assert result == "text"

    def test_routes_to_groq(self):
        wc = WhisperClient(make_stub_config(whisper_provider="Groq"))
        with patch.object(wc, "_transcribe_groq", return_value="text") as m:
            wc.transcribe(Path("audio.wav"))
        m.assert_called_once()

    def test_routes_to_custom_for_local(self):
        wc = WhisperClient(make_stub_config(whisper_provider="local"))
        with patch.object(wc, "_transcribe_custom", return_value="text") as m:
            wc.transcribe(Path("audio.wav"))
        m.assert_called_once()

    def test_routes_to_custom_for_unknown_provider(self):
        wc = WhisperClient(make_stub_config(whisper_provider="whatever"))
        with patch.object(wc, "_transcribe_custom", return_value="text") as m:
            wc.transcribe(Path("audio.wav"))
        m.assert_called_once()

    def test_applies_guidance_when_enabled(self):
        wc = WhisperClient(make_stub_config(transcription_guidance_enabled=True))
        with patch.object(
            wc, "_transcribe_custom", return_value="hallo ende punkt test"
        ):
            result = wc.transcribe(Path("audio.wav"))
        assert result == "hallo. Test"


# ---------------------------------------------------------------------------
# _transcribe_custom
# ---------------------------------------------------------------------------


class TestTranscribeCustom:
    def _make(self, **kw):
        defaults = dict(
            whisper_url="http://localhost",
            port=8009,
            whisper_token="",
            whisper_endpoint="transcribe",
            language="de",
            response_format="text",
        )
        defaults.update(kw)
        return WhisperClient(make_stub_config(**defaults))

    def test_posts_to_correct_url(self):
        wc = self._make()
        audio_path = MagicMock(spec=Path)
        audio_path.name = "audio.wav"

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.text = "  Transcribed text  "

        fake_file = MagicMock()
        m = mock_open()
        m.return_value.__enter__.return_value = fake_file

        with (
            patch("builtins.open", m),
            patch.object(wc.session, "post", return_value=mock_resp) as mock_post,
        ):
            result = wc._transcribe_custom(audio_path)

        url = mock_post.call_args[0][0]
        # language and task are passed as multipart form fields — the
        # standard OpenAI-Whisper contract that faster-whisper-server
        # and most custom Whisper-compatible endpoints honour.
        assert url == "http://localhost:8009/transcribe"
        # Verify the form fields include language=de and task=transcribe
        form_data = mock_post.call_args[1]["data"]
        assert form_data["language"] == "de"
        assert form_data["task"] == "transcribe"
        assert result == "Transcribed text"

    def test_bearer_token_in_header(self):
        wc = self._make(whisper_token="tok-abc")
        audio_path = MagicMock(spec=Path)
        audio_path.name = "audio.wav"

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.text = "text"

        with (
            patch("builtins.open", mock_open()),
            patch.object(wc.session, "post", return_value=mock_resp) as mock_post,
        ):
            wc._transcribe_custom(audio_path)

        headers = mock_post.call_args[1]["headers"]
        assert headers["Authorization"] == "Bearer tok-abc"

    def test_no_auth_header_when_no_token(self):
        wc = self._make(whisper_token="")
        audio_path = MagicMock(spec=Path)
        audio_path.name = "audio.wav"

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.text = "text"

        with (
            patch("builtins.open", mock_open()),
            patch.object(wc.session, "post", return_value=mock_resp) as mock_post,
        ):
            wc._transcribe_custom(audio_path)

        headers = mock_post.call_args[1].get("headers", {})
        assert "Authorization" not in headers

    def test_json_format_uses_json_key(self):
        wc = self._make(response_format="json")
        audio_path = MagicMock(spec=Path)
        audio_path.name = "audio.wav"

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"text": "json text"}

        with (
            patch("builtins.open", mock_open()),
            patch.object(wc.session, "post", return_value=mock_resp),
        ):
            result = wc._transcribe_custom(audio_path)

        assert result == "json text"

    def test_raises_on_http_error(self):
        wc = self._make()
        audio_path = MagicMock(spec=Path)
        audio_path.name = "audio.wav"

        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.HTTPError("503")

        with (
            patch("builtins.open", mock_open()),
            patch.object(wc.session, "post", return_value=mock_resp),
        ):
            with pytest.raises(requests.HTTPError):
                wc._transcribe_custom(audio_path)

    def test_includes_initial_prompt_when_guidance_enabled(self):
        wc = self._make(transcription_guidance_enabled=True)
        audio_path = MagicMock(spec=Path)
        audio_path.name = "audio.wav"

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.text = "text"

        with (
            patch("builtins.open", mock_open()),
            patch.object(wc.session, "post", return_value=mock_resp) as mock_post,
        ):
            wc._transcribe_custom(audio_path)

        data = mock_post.call_args[1]["data"]
        assert "initial_prompt" in data
        assert "dictation" in data["initial_prompt"].lower()


class TestGuidancePostProcessing:
    def test_replaces_spoken_commands(self):
        wc = WhisperClient(make_stub_config(transcription_guidance_enabled=True))
        text = "Das ist ende komma gut ende punkt"
        assert wc._apply_transcription_guidance(text) == "Das ist, gut."

    def test_caps_after_punctuation_and_paragraph(self):
        wc = WhisperClient(make_stub_config(transcription_guidance_enabled=True))
        text = "eins ende punkt zwei einfacher absatz drei"
        assert wc._apply_transcription_guidance(text) == "eins. Zwei\nDrei"


# ---------------------------------------------------------------------------
# _transcribe_openrouter
# ---------------------------------------------------------------------------


class TestTranscribeOpenrouter:
    def test_returns_text(self):
        wc = WhisperClient(
            make_stub_config(whisper_token="t", whisper_model="m", language="de")
        )
        audio_path = MagicMock(spec=Path)
        audio_path.name = "audio.wav"

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"text": "  OpenRouter text  "}

        with (
            patch("builtins.open", mock_open(read_data=b"\x00\x01\x02")),
            patch.object(wc.session, "post", return_value=mock_resp),
        ):
            result = wc._transcribe_openrouter(audio_path)

        assert result == "OpenRouter text"


# ---------------------------------------------------------------------------
# _transcribe_groq
# ---------------------------------------------------------------------------


class TestTranscribeGroq:
    def test_returns_text(self):
        wc = WhisperClient(
            make_stub_config(whisper_token="groq-tok", whisper_model="m", language="de")
        )
        audio_path = MagicMock(spec=Path)
        audio_path.name = "audio.wav"

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"text": "Groq result"}

        with (
            patch("builtins.open", mock_open(read_data=b"\x00")),
            patch.object(wc.session, "post", return_value=mock_resp),
        ):
            result = wc._transcribe_groq(audio_path)

        assert result == "Groq result"


# ---------------------------------------------------------------------------
# provider-specific transcription request contracts
# ---------------------------------------------------------------------------


class TestProviderRequestContracts:
    def test_openrouter_guidance_uses_provider_options_not_invalid_top_level_prompt(self):
        wc = WhisperClient(
            make_stub_config(
                whisper_token="or-token",
                whisper_model="openai/whisper-1",
                language="de",
                transcription_guidance_enabled=True,
                transcription_initial_prompt="Expected vocabulary {{language}}",
            )
        )
        audio_path = MagicMock(spec=Path)
        audio_path.name = "audio.wav"
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"text": "ok"}

        with (
            patch("builtins.open", mock_open(read_data=b"abc")),
            patch.object(wc.session, "post", return_value=mock_resp) as mock_post,
        ):
            wc._transcribe_openrouter(audio_path)

        assert (
            mock_post.call_args.args[0]
            == "https://openrouter.ai/api/v1/audio/transcriptions"
        )
        payload = json.loads(mock_post.call_args.kwargs["data"])
        assert "prompt" not in payload
        assert "initial_prompt" not in payload
        assert payload["provider"]["options"]["groq"]["prompt"] == (
            "Expected vocabulary de"
        )

    def test_groq_guidance_uses_supported_prompt_only(self):
        wc = WhisperClient(
            make_stub_config(
                whisper_token="groq-token",
                whisper_model="whisper-large-v3-turbo",
                language="de",
                transcription_guidance_enabled=True,
                transcription_initial_prompt="Expected vocabulary {{language}}",
            )
        )
        audio_path = MagicMock(spec=Path)
        audio_path.name = "audio.wav"
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"text": "ok"}

        with (
            patch("builtins.open", mock_open(read_data=b"abc")),
            patch.object(wc.session, "post", return_value=mock_resp) as mock_post,
        ):
            wc._transcribe_groq(audio_path)

        assert (
            mock_post.call_args.args[0]
            == "https://api.groq.com/openai/v1/audio/transcriptions"
        )
        form = mock_post.call_args.kwargs["data"]
        assert form["prompt"] == "Expected vocabulary de"
        assert "initial_prompt" not in form
