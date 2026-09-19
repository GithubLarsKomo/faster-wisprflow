"""Tests for llm_corrector.py — LLMCorrector."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from llm_corrector import LLMCorrector
from tests.conftest import make_stub_config

# ---------------------------------------------------------------------------
# _chat_url
# ---------------------------------------------------------------------------


class TestChatUrl:
    def test_ollama_default(self):
        cfg = make_stub_config(
            llm_provider="Ollama",
            correction_url="http://localhost",
            correction_port=11434,
        )
        llm = LLMCorrector(cfg)
        assert llm._chat_url() == "http://localhost:11434/v1/chat/completions"

    def test_openrouter(self):
        cfg = make_stub_config(llm_provider="Openrouter")
        llm = LLMCorrector(cfg)
        assert llm._chat_url() == "https://openrouter.ai/api/v1/chat/completions"

    def test_groq(self):
        cfg = make_stub_config(llm_provider="Groq")
        llm = LLMCorrector(cfg)
        assert llm._chat_url() == "https://api.groq.com/openai/v1/chat/completions"

    def test_ollama_no_port(self):
        cfg = make_stub_config(
            llm_provider="Ollama",
            correction_url="http://localhost",
            correction_port=0,
        )
        llm = LLMCorrector(cfg)
        assert llm._chat_url() == "http://localhost/v1/chat/completions"


# ---------------------------------------------------------------------------
# _proxies
# ---------------------------------------------------------------------------


class TestProxies:
    def test_empty_proxy_bypasses(self):
        cfg = make_stub_config(proxy="")
        llm = LLMCorrector(cfg)
        p = llm._proxies()
        assert p == {"http": None, "https": None}

    def test_proxy_set(self):
        cfg = make_stub_config(proxy="http://proxy.example.com:8080")
        llm = LLMCorrector(cfg)
        p = llm._proxies()
        assert p["http"] == "http://proxy.example.com:8080"
        assert p["https"] == "http://proxy.example.com:8080"


# ---------------------------------------------------------------------------
# _build_payload
# ---------------------------------------------------------------------------


class TestBuildPayload:
    def test_headers_no_token(self):
        cfg = make_stub_config(correction_token="")
        llm = LLMCorrector(cfg)
        headers, _ = llm._build_payload("hello")
        assert "Authorization" not in headers

    def test_headers_with_token(self):
        cfg = make_stub_config(correction_token="tok123")
        llm = LLMCorrector(cfg)
        headers, _ = llm._build_payload("hello")
        assert headers["Authorization"] == "Bearer tok123"

    def test_payload_structure(self):
        cfg = make_stub_config(
            correction_model="my-model",
            temperature=0.5,
            top_p=0.9,
            max_tokens=100,
        )
        llm = LLMCorrector(cfg)
        _, payload = llm._build_payload("test text")
        assert payload["model"] == "my-model"
        assert payload["stream"] is False
        assert payload["temperature"] == 0.5
        assert payload["max_tokens"] == 100
        msgs = payload["messages"]
        assert msgs[0]["role"] == "system"
        assert msgs[1]["role"] == "user"
        assert "test text" in msgs[1]["content"]

    def test_language_placeholder_substituted(self):
        cfg = make_stub_config(
            system_prompt="Lang: {{language}}",
            language="de",
        )
        llm = LLMCorrector(cfg)
        # placeholder is in the user prompt, not system; but system is passed as-is
        _, payload = llm._build_payload("{{language}} check")
        # user content has the placeholder replaced
        assert "de" in payload["messages"][1]["content"]


# ---------------------------------------------------------------------------
# correct()
# ---------------------------------------------------------------------------


class TestCorrect:
    def _make(self, **kw):
        return LLMCorrector(make_stub_config(**kw))

    def test_returns_text_when_disabled(self):
        llm = self._make(correction_enabled=False)
        assert llm.correct("hello") == "hello"

    def test_returns_text_on_empty_input(self):
        llm = self._make(correction_enabled=True)
        assert llm.correct("   ") == "   "

    def test_returns_corrected_text(self):
        llm = self._make()
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "Corrected text"}}]
        }
        with patch("llm_corrector.requests.post", return_value=mock_resp):
            result = llm.correct("original text")
        assert result == "Corrected text"

    def test_raises_on_http_error(self):
        llm = self._make()
        with patch(
            "llm_corrector.requests.post",
            side_effect=requests.HTTPError("500"),
        ):
            with pytest.raises(requests.HTTPError):
                llm.correct("original")

    def test_raises_on_connection_error(self):
        llm = self._make()
        with patch(
            "llm_corrector.requests.post",
            side_effect=requests.ConnectionError(),
        ):
            with pytest.raises(requests.ConnectionError):
                llm.correct("original")

    def test_returns_original_when_response_empty(self):
        llm = self._make()
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"choices": [{"message": {"content": ""}}]}
        with patch("llm_corrector.requests.post", return_value=mock_resp):
            assert llm.correct("original") == "original"


# ---------------------------------------------------------------------------
# probe()
# ---------------------------------------------------------------------------


class TestProbe:
    def _make(self, **kw):
        return LLMCorrector(make_stub_config(**kw))

    def test_returns_result_on_success(self):
        llm = self._make()
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "  Probed  "}}]
        }
        with patch("llm_corrector.requests.post", return_value=mock_resp):
            assert llm.probe("test") == "Probed"

    def test_raises_on_http_error(self):
        llm = self._make()
        mock_resp = MagicMock()
        mock_resp.ok = False
        mock_resp.status_code = 401
        mock_resp.text = "Unauthorized"
        with patch("llm_corrector.requests.post", return_value=mock_resp):
            with pytest.raises(RuntimeError, match="HTTP 401"):
                llm.probe("test")

    def test_raises_on_api_error_in_body(self):
        llm = self._make()
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"error": {"message": "model not found"}}
        with patch("llm_corrector.requests.post", return_value=mock_resp):
            with pytest.raises(ValueError, match="model not found"):
                llm.probe("test")

    def test_raises_on_empty_choices(self):
        llm = self._make()
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"choices": []}
        with patch("llm_corrector.requests.post", return_value=mock_resp):
            with pytest.raises(ValueError, match="Empty response"):
                llm.probe("test")

    def test_raises_on_missing_choices_key(self):
        llm = self._make()
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {}
        with patch("llm_corrector.requests.post", return_value=mock_resp):
            with pytest.raises(ValueError):
                llm.probe("test")


# ---------------------------------------------------------------------------
# non-loss / truncation guards
# ---------------------------------------------------------------------------


class TestCorrectionIntegrity:
    def test_output_budget_grows_for_long_dictation_but_respects_context(self):
        llm = LLMCorrector(
            make_stub_config(max_tokens=220, num_ctx=1024)
        )
        long_text = "wort " * 300
        budget = llm._max_output_tokens(long_text)

        assert budget > 220
        assert budget <= 512

    def test_finish_reason_length_falls_back_to_complete_raw_text(self):
        llm = LLMCorrector(make_stub_config())
        raw = "dies ist der vollständige rohe text der nicht verloren gehen darf"
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "choices": [
                {
                    "finish_reason": "length",
                    "message": {"content": "dies ist der"},
                }
            ]
        }

        with patch("llm_corrector.requests.post", return_value=mock_resp):
            assert llm.correct(raw) == raw

    def test_suspiciously_short_correction_falls_back_to_raw_text(self):
        llm = LLMCorrector(make_stub_config())
        raw = "eins zwei drei vier fünf sechs sieben acht neun zehn elf zwölf"
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": "eins zwei drei"},
                }
            ]
        }

        with patch("llm_corrector.requests.post", return_value=mock_resp):
            assert llm.correct(raw) == raw

    def test_anthropic_max_tokens_falls_back_to_raw_text(self):
        llm = LLMCorrector(
            make_stub_config(
                llm_provider="Anthropic",
                correction_token="secret",
            )
        )
        raw = "vollständiger diktierter text"
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "stop_reason": "max_tokens",
            "content": [{"type": "text", "text": "vollständiger"}],
        }

        with patch("llm_corrector.requests.post", return_value=mock_resp):
            assert llm.correct(raw) == raw

    def test_probe_reports_truncation_explicitly(self):
        llm = LLMCorrector(make_stub_config())
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "choices": [
                {
                    "finish_reason": "length",
                    "message": {"content": "partial"},
                }
            ]
        }

        with patch("llm_corrector.requests.post", return_value=mock_resp):
            with pytest.raises(ValueError, match="truncated"):
                llm.probe("test text")
