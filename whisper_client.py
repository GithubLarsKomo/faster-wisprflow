import base64
import json

import requests

from config import Config, _build_base_url

_OPENROUTER_HOST = "openrouter.ai"
_GROQ_HOST = "groq.com"


class WhisperClient:
    """Transcribes audio via one of three backends, auto-detected from ``whisper_url``:

    - Custom (default): multipart POST to ``<whisper_url>:<port>/<whisper_endpoint>``
    - Groq  (URL contains "groq.com"): multipart POST to
      ``https://api.groq.com/openai/v1/audio/transcriptions``
    - OpenRouter (URL contains "openrouter.ai"): JSON POST with base64 audio to
      ``https://openrouter.ai/api/v1/audio/transcriptions``
    """

    def __init__(self, config: Config):
        self.config = config

    def _proxies(self) -> dict | None:
        """Return a proxies dict based on config.proxy.
        Empty string  → no proxy (bypass system proxy).
        Non-empty str → use that proxy URL.
        """
        proxy = getattr(self.config, "proxy", "")
        if proxy:
            return {"http": proxy, "https": proxy}
        return {"http": None, "https": None}

    def transcribe(self, audio_path):
        provider = getattr(self.config, "whisper_provider", "lokal")
        if provider == "Openrouter":
            return self._transcribe_openrouter(audio_path)
        if provider == "Groq":
            return self._transcribe_groq(audio_path)
        return self._transcribe_custom(audio_path)

    def _transcribe_openrouter(self, audio_path):
        with open(audio_path, "rb") as f:
            audio_b64 = base64.b64encode(f.read()).decode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.config.whisper_token}",
            "Content-Type": "application/json",
        }
        payload = json.dumps(
            {
                "model": self.config.whisper_model,
                "language": self.config.language,
                "input_audio": {
                    "data": audio_b64,
                    "format": "wav",
                },
            }
        )
        response = requests.post(
            "https://openrouter.ai/api/v1/audio/transcriptions",
            headers=headers,
            data=payload,
            timeout=600,
            proxies=self._proxies(),
        )
        response.raise_for_status()
        return response.json().get("text", "").strip()

    def _transcribe_groq(self, audio_path):
        with open(audio_path, "rb") as f:
            headers = {"Authorization": f"Bearer {self.config.whisper_token}"}
            response = requests.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers=headers,
                files={"file": (audio_path.name, f, "audio/wav")},
                data={
                    "model": self.config.whisper_model,
                    "language": self.config.language,
                    "response_format": "json",
                },
                timeout=600,
                proxies=self._proxies(),
            )
        response.raise_for_status()
        return response.json().get("text", "").strip()

    def _transcribe_custom(self, audio_path):
        with open(audio_path, "rb") as f:
            base = _build_base_url(self.config.whisper_url, self.config.port)
            headers = {}
            if self.config.whisper_token:
                headers["Authorization"] = f"Bearer {self.config.whisper_token}"
            response = requests.post(
                base + "/" + self.config.whisper_endpoint.lstrip("/"),
                files={"file": (audio_path.name, f, "audio/wav")},
                data={
                    "language": self.config.language,
                    "response_format": self.config.response_format,
                },
                timeout=600,
                headers=headers,
            )
        response.raise_for_status()
        if self.config.response_format == "text":
            return response.text.strip()
        return response.json().get("text", "").strip()
