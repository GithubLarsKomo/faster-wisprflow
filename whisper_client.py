import base64
import json
import re

import requests

from config import _DEFAULT_TRANSCRIPTION_INITIAL_PROMPT, Config, _build_base_url
from provider_registry import get_provider, normalize_provider


class WhisperClient:
    """Transcribes audio through the provider contract registry.

    Local/custom endpoints remain configurable; fixed public cloud endpoints are
    defined once in ``provider_registry.py``.
    """

    def __init__(self, config: Config):
        self.config = config
        # Reuse TCP/TLS connections across dictation runs. This matters for
        # cloud endpoints and is harmless for local HTTP servers.
        self.session = requests.Session()

    def close(self) -> None:
        """Release pooled HTTP connections owned by this client."""
        self.session.close()

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
        from pathlib import Path as _Path

        audio_path = _Path(audio_path)
        provider_id = normalize_provider(
            getattr(self.config, "whisper_provider", "local")
        )
        if provider_id == "openrouter":
            text = self._transcribe_openrouter(audio_path)
            return self._apply_transcription_guidance(text)
        if provider_id == "groq":
            text = self._transcribe_groq(audio_path)
            return self._apply_transcription_guidance(text)
        if provider_id == "openai":
            text = self._transcribe_openai(audio_path)
            return self._apply_transcription_guidance(text)
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
            # OpenRouter exposes provider-specific transcription options under
            # the provider block. A Groq-routed Whisper request accepts the
            # vocabulary/style hint here; unsupported upstreams simply do not
            # receive an invalid top-level prompt field.
            prompt = self._initial_prompt()
            data["provider"] = {
                "options": {
                    "groq": {
                        "prompt": prompt,
                    }
                }
            }
        payload = json.dumps(data)
        provider = get_provider("openrouter")
        response = self.session.post(
            provider.transcription_url,
            headers=headers,
            data=payload,
            timeout=(5, 30),
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
                data["prompt"] = self._initial_prompt()
            provider = get_provider("groq")
            response = self.session.post(
                provider.transcription_url,
                headers=headers,
                files={"file": (audio_path.name, f, "audio/wav")},
                data=data,
                timeout=(5, 30),
                proxies=self._proxies(),
            )
        response.raise_for_status()
        return response.json().get("text", "").strip()

    def _transcribe_openai(self, audio_path):
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
            provider = get_provider("openai")
            response = self.session.post(
                provider.transcription_url,
                headers=headers,
                files={"file": (audio_path.name, f, "audio/wav")},
                data=data,
                timeout=(5, 30),
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
                "task": "transcribe",  # never translate by default
                "response_format": self.config.response_format,
            }
            if self._guidance_enabled():
                prompt = self._initial_prompt()
                data["prompt"] = prompt
                data["initial_prompt"] = prompt
            response = self.session.post(
                f"{base}/{self.config.whisper_endpoint.lstrip('/')}",
                files={"file": (audio_path.name, f, "audio/wav")},
                data=data,
                timeout=(5, 30),
                headers=headers,
            )
        response.raise_for_status()
        if self.config.response_format == "text":
            return response.text.strip()
        return response.json().get("text", "").strip()
