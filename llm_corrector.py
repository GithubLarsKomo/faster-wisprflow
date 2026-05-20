import requests

from config import Config, _build_base_url

_OPENROUTER_HOST = "openrouter.ai"
_GROQ_HOST = "groq.com"


class LLMCorrector:
    """Sends transcribed text to a LLM via the OpenAI-compatible chat completions endpoint.

    Supported backends (auto-detected from ``correction_url``):
    - Ollama      (default): ``<correction_url>:<correction_port>/v1/chat/completions``
    - OpenRouter  (URL contains "openrouter.ai"): ``https://openrouter.ai/api/v1/chat/completions``
    - Groq        (URL contains "groq.com"): ``https://api.groq.com/v1/chat/completions``

    The system prompt is sent as the ``system`` role; the raw text as the ``user`` role.
    """

    def __init__(self, config: Config) -> None:
        self.config = config

    def _chat_url(self) -> str:
        provider = getattr(self.config, "llm_provider", "Ollama")
        if provider == "Openrouter":
            return "https://openrouter.ai/api/v1/chat/completions"
        if provider == "Groq":
            return "https://api.groq.com/v1/chat/completions"
        base = _build_base_url(self.config.correction_url, self.config.correction_port)
        return base.rstrip("/") + "/v1/chat/completions"

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
        return headers, payload

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
        headers, payload = self._build_payload(text)
        resp = requests.post(
            self._chat_url(),
            json=payload,
            timeout=30,
            headers=headers,
            proxies=self._proxies(),
        )
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
        result = (choices[0]["message"]["content"] or "").strip()
        return result

    def correct(self, text: str) -> str:
        if not self.config.correction_enabled or not text.strip():
            return text
        headers, payload = self._build_payload(text)
        resp = requests.post(
            self._chat_url(),
            json=payload,
            timeout=30,
            headers=headers,
            proxies=self._proxies(),
        )
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
