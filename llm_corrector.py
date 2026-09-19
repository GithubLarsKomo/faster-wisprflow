import requests

from config import Config, _build_base_url
from provider_registry import get_provider, normalize_provider


class LLMCorrector:
    """Sends transcribed text to a LLM via the OpenAI-compatible chat completions endpoint.

    Provider routing comes from ``provider_registry.py``. Local/OpenAI-compatible
    servers use ``<correction_url>:<correction_port>/v1/chat/completions``.

    The system prompt is sent as the ``system`` role; the raw text as the ``user`` role.
    """

    def __init__(self, config: Config) -> None:
        self.config = config

    def _chat_url(self) -> str:
        provider = get_provider(getattr(self.config, "llm_provider", "Ollama"))
        if provider is not None and provider.chat_url:
            return provider.chat_url
        base = _build_base_url(self.config.correction_url, self.config.correction_port)
        return base.rstrip("/") + "/v1/chat/completions"

    def _is_anthropic(self) -> bool:
        return (
            normalize_provider(getattr(self.config, "llm_provider", "Ollama"))
            == "anthropic"
        )

    def _build_anthropic_request(self, text: str) -> tuple[dict, dict]:
        """Return (headers, payload) for an Anthropic Messages API request."""
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.config.correction_token,
            "anthropic-version": "2023-06-01",
        }
        system_prompt = self.config.system_prompt.strip().replace(
            "{{language}}", self.config.language
        )
        user_content = (
            f"<text_to_correct>\n"
            f"{text.strip().replace('{{language}}', self.config.language)}\n"
            f"</text_to_correct>"
        )
        payload = {
            "model": self.config.correction_model,
            "max_tokens": self.config.max_tokens,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_content}],
        }
        return headers, payload

    def _proxies(self) -> dict | None:
        """Return a proxies dict based on config.proxy.
        Empty string  → no proxy (bypass system proxy).
        Non-empty str → use that proxy URL.
        """
        proxy = getattr(self.config, "proxy", "")
        if proxy:
            return {"http": proxy, "https": proxy}
        return {"http": None, "https": None}

    def _build_payload(self, text: str) -> tuple[dict, dict]:
        """Return (headers, payload) for a chat-completions request."""
        headers = {"Content-Type": "application/json"}
        if self.config.correction_token:
            headers["Authorization"] = f"Bearer {self.config.correction_token}"
        system_prompt = self.config.system_prompt.strip().replace(
            "{{language}}", self.config.language
        )
        user_prompt = (
            f"<text_to_correct>\n"
            f"{text.strip().replace('{{language}}', self.config.language)}\n"
            f"</text_to_correct>"
        )
        payload = {
            "model": self.config.correction_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.config.temperature,
            "top_p": self.config.top_p,
            "max_tokens": self.config.max_tokens,
            "stream": False,
        }
        # Disable reasoning tokens on providers that support the field.
        # Reasoning models return content=None when reasoning consumes the whole
        # response — turning it off ensures a plain-text reply is always returned.
        provider_id = normalize_provider(
            getattr(self.config, "llm_provider", "Ollama")
        )
        if provider_id == "openrouter":
            payload["reasoning"] = {"effort": "none"}
        return headers, payload

    def _post_openai_compat(self, headers: dict, payload: dict) -> "requests.Response":
        """POST to the chat-completions URL; if the server rejects the
        ``reasoning`` suppression flag (400 + 'mandatory'), retry once
        without it.

        The timeout is a ``(connect, read)`` tuple — 5 s to establish the
        socket, 30 s to receive the full response. This is critical for
        Ollama: a slow local model can legitimately take >30 s for the
        first token, so we want to give it a chance to respond while
        still bounding the wait.
        """
        timeout = (5, 30)
        resp = requests.post(
            self._chat_url(),
            json=payload,
            timeout=timeout,
            headers=headers,
            proxies=self._proxies(),
        )
        if (
            resp.status_code == 400
            and "reasoning" in payload
            and "mandatory" in resp.text.lower()
        ):
            payload = {k: v for k, v in payload.items() if k != "reasoning"}
            resp = requests.post(
                self._chat_url(),
                json=payload,
                timeout=timeout,
                headers=headers,
                proxies=self._proxies(),
            )
        return resp

    @staticmethod
    def _looks_like_correction(original: str, result: str) -> bool:
        """Return False if result looks like a meta-response rather than a corrected text."""
        orig_words = original.split()
        if not orig_words:
            return True
        # A correction should not be dramatically longer than the original
        if len(result.split()) > len(orig_words) * 3 + 15:
            return False
        return True

    def probe(self, text: str) -> str:
        """Like correct(), but raises on any HTTP or API error (used for testing)."""
        if self._is_anthropic():
            headers, payload = self._build_anthropic_request(text)
            resp = requests.post(
                self._chat_url(),
                json=payload,
                timeout=(5, 30),
                headers=headers,
                proxies=self._proxies(),
            )
            if not resp.ok:
                raise RuntimeError(f"HTTP {resp.status_code} — {resp.text}")
            data = resp.json()
            if "error" in data:
                err = data["error"]
                msg = (
                    err.get("message", str(err)) if isinstance(err, dict) else str(err)
                )
                raise ValueError(msg)
            content = data.get("content") or []
            if not content:
                raise ValueError(f"Empty response from Anthropic: {data}")
            return (content[0].get("text") or "").strip()
        headers, payload = self._build_payload(text)
        resp = self._post_openai_compat(headers, payload)
        if not resp.ok:
            raise RuntimeError(f"HTTP {resp.status_code} — {resp.text}")
        data = resp.json()
        if "error" in data:
            err = data["error"]
            msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            raise ValueError(msg)
        choices = data.get("choices") or []
        if not choices:
            raise ValueError(f"Empty response from API: {data}")
        message = choices[0].get("message", {})
        content = message.get("content")
        if content is None:
            if message.get("refusal"):
                raise ValueError(f"Model refused: {message['refusal']}")
            if message.get("tool_calls"):
                raise ValueError(
                    "Model returned tool_calls instead of text content. "
                    "Try a non-reasoning model or adjust the system prompt."
                )
            if message.get("reasoning_details") or message.get("reasoning"):
                raise ValueError(
                    "Model returned only encrypted reasoning data and no text content. "
                    "This is a reasoning-only model that does not produce a plain-text reply. "
                    "Choose a different model (e.g. one without 'thinking' or 'reasoning' in its name)."
                )
            snippet = str(message)[:300]
            raise ValueError(f"Model returned null content. Raw message: {snippet}")
        return content.strip()

    def correct(self, text: str) -> str:
        if not self.config.correction_enabled or not text.strip():
            return text
        if self._is_anthropic():
            headers, payload = self._build_anthropic_request(text)
            resp = requests.post(
                self._chat_url(),
                json=payload,
                timeout=(5, 30),
                headers=headers,
                proxies=self._proxies(),
            )
            if not resp.ok:
                raise RuntimeError(f"HTTP {resp.status_code} — {resp.text}")
            content = resp.json().get("content") or []
            result = (content[0].get("text") or "").strip() if content else ""
            result = (
                result.removeprefix("<text_to_correct>")
                .removesuffix("</text_to_correct>")
                .strip()
            )
            if result and self._looks_like_correction(text, result):
                return result
            return text
        headers, payload = self._build_payload(text)
        resp = self._post_openai_compat(headers, payload)
        if not resp.ok:
            raise RuntimeError(f"HTTP {resp.status_code} — {resp.text}")
        result = (resp.json()["choices"][0]["message"]["content"] or "").strip()
        # Strip XML tags echoed back by some models
        result = (
            result.removeprefix("<text_to_correct>")
            .removesuffix("</text_to_correct>")
            .strip()
        )
        if result and self._looks_like_correction(text, result):
            return result
        return text
