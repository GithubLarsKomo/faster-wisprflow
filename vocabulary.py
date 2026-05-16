import json

from config import VOCAB_PATH


class VocabularyManager:
    """Persists word-level correction pairs and applies them to transcription output."""

    _PUNCT = ".,!?;:\"'()[]{}\u2026\u2013\u2014-"

    def __init__(self) -> None:
        self._data: dict = {"corrections": {}}
        self.load()

    def load(self) -> None:
        if not VOCAB_PATH.exists():
            VOCAB_PATH.write_text(
                json.dumps({"corrections": {}}, indent=2), encoding="utf-8"
            )
        try:
            with open(VOCAB_PATH, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded.get("corrections"), dict):
                self._data = loaded
        except Exception:
            self._data = {"corrections": {}}

    def save(self) -> None:
        VOCAB_PATH.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def apply(self, text: str) -> str:
        if not text or not self._data["corrections"]:
            return text
        corrections = self._data["corrections"]
        tokens = text.split(" ")
        result = []
        for token in tokens:
            stripped = token.strip(self._PUNCT)
            prefix_len = len(token) - len(token.lstrip(self._PUNCT))
            suffix_len = len(token) - len(token.rstrip(self._PUNCT))
            prefix = token[:prefix_len]
            suffix = token[len(token) - suffix_len :] if suffix_len else ""
            key = stripped.lower()
            if key in corrections:
                result.append(prefix + corrections[key] + suffix)
            else:
                result.append(token)
        return " ".join(result)

    def add(self, original: str, corrected: str) -> None:
        key = original.strip().lower()
        # strip only spaces (not \n \t) so control-char replacements are preserved
        value = corrected.strip(" ")
        if key and value:
            self._data["corrections"][key] = value
            self.save()

    def remove(self, original: str) -> None:
        key = original.strip().lower()
        if key in self._data["corrections"]:
            del self._data["corrections"][key]
            self.save()

    def all(self) -> dict:
        return dict(self._data["corrections"])
