import requests

from config import Config, _build_base_url


class WhisperClient:
    def __init__(self, config: Config):
        self.config = config

    def transcribe(self, audio_path):
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
