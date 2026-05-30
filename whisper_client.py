import base64
import json
import re

import requests

from config import _DEFAULT_TRANSCRIPTION_INITIAL_PROMPT, Config, _build_base_url

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
        provider = getattr(self.config, "whisper_provider", "local")
        if provider == "Openrouter":
            text = self._transcribe_openrouter(audio_path)
            return self._apply_transcription_guidance(text)
        if provider == "Groq":
            text = self._transcribe_groq(audio_path)
            return self._apply_transcription_guidance(text)
        if provider == "internal":
            return self._transcribe_internal(audio_path)
        text = self._transcribe_custom(audio_path)
        return self._apply_transcription_guidance(text)

    def _guidance_enabled(self) -> bool:
        return bool(getattr(self.config, "transcription_guidance_enabled", False))

    def _initial_prompt(self) -> str:
        language = getattr(self.config, "language", "de")
        prompt = getattr(self.config, "transcription_initial_prompt", "")
        if not isinstance(prompt, str) or not prompt.strip():
            prompt = _DEFAULT_TRANSCRIPTION_INITIAL_PROMPT
        return prompt.replace("{{language}}", language)

    def _replace_spoken_punctuation(self, text: str) -> str:
        if not text:
            return ""
        out = text
        replacements = [
            (r"\beinfacher\s+absatz\b", "\n"),
            (r"\bende\s+fragezeichen\b", "?"),
            (r"\bende\s+semikolon\b", ";"),
            (r"\bende\s+komma\b", ","),
            (r"\bende\s+punkt\b", "."),
            (r"\bklammer\s+auf\b", "("),
            (r"\bklammer\s+zu\b", ")"),
        ]
        for pattern, repl in replacements:
            out = re.sub(pattern + r"(?:\s*[.,;:!?])?", repl, out, flags=re.IGNORECASE)

        out = re.sub(r"[ \t]*\n[ \t]*", "\n", out)
        out = re.sub(r"[ \t]+", " ", out)
        out = re.sub(r"\s+([,.;:!?])", r"\1", out)
        out = re.sub(r"([({\[])[ \t]+", r"\1", out)
        out = re.sub(r"[ \t]+([)}\]])", r"\1", out)
        out = re.sub(r"\n{3,}", "\n\n", out)
        return out.strip()

    def _capitalize_after_breaks(self, text: str) -> str:
        if not text:
            return ""

        def _upper(m: re.Match) -> str:
            prefix = m.group(1)
            letter = m.group(2)
            return prefix + letter.upper()

        return re.sub(r"([\.!?]\s+|\n+)([a-z\u00e0-\u00f6\u00f8-\u00ff])", _upper, text)

    def _apply_transcription_guidance(self, text: str) -> str:
        out = (text or "").strip()
        if not self._guidance_enabled():
            return out
        out = self._replace_spoken_punctuation(out)
        out = self._capitalize_after_breaks(out)
        return out

    def _transcribe_internal(self, audio_path):
        from parakeet_engine import transcribe_file

        model_name = getattr(
            self.config, "parakeet_model", "nvidia/parakeet-tdt-0.6b-v3"
        )
        language = getattr(self.config, "language", "de")
        text = transcribe_file(audio_path, model_name, language)
        return self._apply_transcription_guidance(text)

    def _transcribe_openrouter(self, audio_path):
        with open(audio_path, "rb") as f:
            audio_b64 = base64.b64encode(f.read()).decode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.config.whisper_token}",
            "Content-Type": "application/json",
        }
        data = {
            "model": self.config.whisper_model,
            "language": self.config.language,
            "input_audio": {
                "data": audio_b64,
                "format": "wav",
            },
        }
        if self._guidance_enabled():
            prompt = self._initial_prompt()
            data["prompt"] = prompt
            data["initial_prompt"] = prompt
        payload = json.dumps(data)
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
            data = {
                "model": self.config.whisper_model,
                "language": self.config.language,
                "response_format": "json",
            }
            if self._guidance_enabled():
                prompt = self._initial_prompt()
                data["prompt"] = prompt
                data["initial_prompt"] = prompt
            response = requests.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers=headers,
                files={"file": (audio_path.name, f, "audio/wav")},
                data=data,
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
            data = {
                "language": self.config.language,
                "response_format": self.config.response_format,
            }
            if self._guidance_enabled():
                prompt = self._initial_prompt()
                data["prompt"] = prompt
                data["initial_prompt"] = prompt
            response = requests.post(
                base + "/" + self.config.whisper_endpoint.lstrip("/"),
                files={"file": (audio_path.name, f, "audio/wav")},
                data=data,
                timeout=600,
                headers=headers,
            )
        response.raise_for_status()
        if self.config.response_format == "text":
            return response.text.strip()
        return response.json().get("text", "").strip()
