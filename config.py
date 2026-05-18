import ctypes
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent
# In a PyInstaller onefile build sys.executable is the .exe itself;
# config.json must live next to it, not inside _MEIPASS.
if getattr(sys, "frozen", False):
    CONFIG_PATH = Path(sys.executable).parent / "config.json"
else:
    CONFIG_PATH = BASE_DIR / "config.json"

VOCAB_PATH = CONFIG_PATH.parent / "vocabulary.json"
PROMPT_PATH = CONFIG_PATH.parent / "system_prompt.txt"

_DEFAULT_SYSTEM_PROMPT = "\n".join(
    [
        "Du bist ein extrem schneller Speech-to-Text Cleanup-Prozessor in der ISO-Sprache {{language}}.",
        "",
        "AUFGABE:",
        "Korrigiere ausschließlich:",
        "",
        "Orthographie",
        "Zeichensetzung",
        "Groß-/Kleinschreibung",
        "offensichtliche Speech-to-Text Fehler",
        "Umlaute in der ISO-Sprache {{language}}",
        "Satzstruktur bei Diktatfragmenten",
        "Selbstkorrekturen des Sprechers: Wenn der Sprecher sich selbst korrigiert (erkennbar an Wörtern wie 'nein', 'also', 'ich meine', 'beziehungsweise', 'äh nein'), behalte ausschließlich die zuletzt genannte Fassung (Beispiel: 'drei, nein, vier Flaschen' → 'vier Flaschen')",
        "Füllwörter wie äh, ähm etc., wenn sie offensichtlich fehl am Platz sind",
        "",
        "REGELN:",
        "",
        "KEINE neuen Informationen hinzufügen",
        "Bedeutung NICHT verändern",
        "KEINE Zusammenfassung",
        "KEINE Umformulierungen außer minimal notwendig",
        "Fachbegriffe erhalten",
        "ISO-Sprache {{language}}",
        "Ausgabe nur als finaler Text",
        "Kein Markdown",
        "Keine Erklärungen",
    ]
)


def load_system_prompt(config_data: dict | None = None) -> str:
    """Return the LLM system prompt.

    Priority: ``system_prompt.txt`` on disk → *config_data*[``system_prompt``]
    (migration path from JSON) → built-in default.
    """
    if PROMPT_PATH.exists():
        try:
            return PROMPT_PATH.read_text(encoding="utf-8")
        except Exception:
            pass
    if config_data and "system_prompt" in config_data:
        return config_data["system_prompt"]
    return _DEFAULT_SYSTEM_PROMPT


def save_system_prompt(text: str) -> None:
    """Persist the LLM system prompt to ``system_prompt.txt``."""
    PROMPT_PATH.write_text(text, encoding="utf-8")


def _resource(filename: str) -> Path:
    """Resolve path to a bundled resource (works in PyInstaller onefile and dev)."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass) / filename
    return BASE_DIR / filename


DEFAULT_CONFIG = {
    "whisper_url": "http://10.4.190.16",
    "port": 8009,
    "whisper_token": "",
    "whisper_model": "whisper-large-v3-turbo",
    "whisper_provider": "lokal",
    "whisper_endpoint": "transcribe",
    "health_endpoint": "health",
    "language": "de",
    "response_format": "text",
    "sample_rate": 16000,
    "channels": 1,
    "input_device": None,
    "hotkey_keys": ["ctrl", "linke windows"],
    "restore_clipboard": True,
    "audio_filename": "recording.wav",
    "auto_elevate": True,
    "start_with_windows": True,
    "correction_enabled": True,
    "correction_url": "http://10.4.190.16",
    "correction_port": 11434,
    "correction_token": "",
    "correction_model": "hf.co/unsloth/Qwen3-4B-Instruct-2507-GGUF:Q4_K_M",
    "llm_provider": "Ollama",
    "temperature": 0,
    "top_p": 1,
    "num_predict": 220,
    "num_ctx": 1024,
    "repeat_penalty": 1.0,
    "max_tokens": 220,
    "proxy": "",
}


def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except BaseException:
        return False


def auto_elevate_if_needed(config):
    """No-op: elevation is no longer required. Kept for config compatibility."""
    pass


def load_config():
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(json.dumps(DEFAULT_CONFIG, indent=2), encoding="utf-8")

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    merged = DEFAULT_CONFIG.copy()
    merged.update(data)
    return merged


def save_config(data):
    CONFIG_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _build_base_url(url: str, port) -> str:
    """Combine base URL with port, omitting port if falsy or zero."""
    url = url.rstrip("/")
    try:
        p = int(port)
    except (TypeError, ValueError):
        p = 0
    if p > 0:
        return f"{url}:{p}"
    return url


class Config:
    def __init__(self):
        self.reload()

    def reload(self):
        data = load_config()
        self.raw = data
        self.whisper_url = data["whisper_url"]
        self.port = data.get("port", None)
        self.whisper_token = data.get("whisper_token", "")
        self.whisper_model = data.get("whisper_model", "")
        self.whisper_provider = data.get("whisper_provider", "lokal")
        self.whisper_endpoint = data.get("whisper_endpoint", "/transcribe")
        self.health_endpoint = data.get("health_endpoint", "/health")
        self.language = data["language"]
        self.response_format = data["response_format"]
        self.sample_rate = int(data["sample_rate"])
        self.channels = int(data["channels"])
        self.input_device = data.get("input_device", None)
        self.hotkey_keys = data["hotkey_keys"]
        self.restore_clipboard = bool(data["restore_clipboard"])
        self.audio_filename = data["audio_filename"]
        self.correction_enabled = bool(data.get("correction_enabled", True))
        self.correction_url = data.get("correction_url", "http://10.4.190.16")
        self.correction_port = data.get("correction_port", 11434)
        self.correction_token = data.get("correction_token", "")
        self.correction_model = data.get(
            "correction_model", "hf.co/unsloth/Qwen3-4B-Instruct-2507-GGUF:Q4_K_M"
        )
        self.llm_provider = data.get("llm_provider", "Ollama")
        self.temperature = data.get("temperature", 0)
        self.top_p = data.get("top_p", 1)
        self.num_predict = data.get("num_predict", 220)
        self.num_ctx = data.get("num_ctx", 1024)
        self.repeat_penalty = data.get("repeat_penalty", 1.0)
        self.max_tokens = data.get("max_tokens", 220)
        self.system_prompt = load_system_prompt(data)
        self.proxy = data.get("proxy", "")
