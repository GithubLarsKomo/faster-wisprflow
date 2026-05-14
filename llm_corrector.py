import requests

from config import Config, _build_base_url


class LLMCorrector:
    """Sends transcribed text to a local LLM (Ollama /api/generate) for cleanup."""

    def __init__(self, config: Config) -> None:
        self.config = config

    def correct(self, text: str, vocab: "VocabularyManager") -> str:  # noqa: F821
        if not self.config.correction_enabled or not text.strip():
            return text
        try:
            base = _build_base_url(
                self.config.correction_url,
                self.config.correction_port,
            )
            url = base.rstrip("/") + "/api/generate"
            headers = {}
            if self.config.correction_token:
                headers["Authorization"] = f"Bearer {self.config.correction_token}"
            corr = vocab.all()
            dict_str = (
                "\n".join(f"  {k} \u2192 {v}" for k, v in sorted(corr.items()))
                if corr
                else "(leer)"
            )
            prompt = self.config.correction_system_prompt.replace(
                "{{dictionary}}", dict_str
            ).replace("{{raw_text}}", text)
            payload = {
                "model": self.config.correction_model,
                "prompt": prompt,
                "temperature": self.config.correction_temperature,
                "top_p": self.config.correction_top_p,
                "num_predict": self.config.num_predict,
                "num_ctx": self.config.num_ctx,
                "repeat_penalty": self.config.repeat_penalty,
                "stream": False,
            }
            resp = requests.post(url, json=payload, timeout=30, headers=headers)
            resp.raise_for_status()
            result = resp.json().get("response", "").strip()
            return result if result else text
        except Exception:
            return text
