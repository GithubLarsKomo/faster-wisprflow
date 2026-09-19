import json
import sys
from pathlib import Path

import keyring as _keyring

BASE_DIR = Path(__file__).parent
# In a PyInstaller onefile build sys.executable is the .exe itself;
# config.json must live next to it, not inside _MEIPASS.
if getattr(sys, "frozen", False):
    CONFIG_PATH = Path(sys.executable).parent / "config.json"
else:
    CONFIG_PATH = BASE_DIR / "config.json"

VOCAB_PATH = CONFIG_PATH.parent / "vocabulary.json"
PROMPT_PATH = CONFIG_PATH.parent / "system_prompt.txt"
TRANSCRIPTION_PROMPT_PATH = CONFIG_PATH.parent / "transcription_initial_prompt.txt"
CORRECTOR_PROMPTS_DIR = CONFIG_PATH.parent / "corrector_prompts"
DEFAULT_CORRECTOR_PROMPT_FILE = "default.md"

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
        "When spoken arithmetic appears, convert number words to digits and 'mal' to 'x'.",
        "Example: 'klammer auf sieben mal vier klammer zu' -> '(7x4)'.",
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

_DEFAULT_TRANSCRIPTION_INITIAL_PROMPT = "\n".join(
    [
        "Output strict clean dictation text in ISO-language {{language}}.",
        "Keep punctuation consistent and natural.",
        "Treat spoken punctuation commands as symbols:",
        "einfacher absatz => newline",
        "ende punkt => .",
        "ende fragezeichen => ?",
        "klammer auf => (",
        "klammer zu => )",
        "ende komma => ,",
        "ende semikolon => ;",
        "If a sentence starts after punctuation or a paragraph break, capitalize the next word when written in latin letters.",
        "When spoken arithmetic appears, convert number words to digits and 'mal' to 'x'.",
        "Example: 'klammer auf sieben mal vier klammer zu' -> '(7x4)'.",
        "Keep punctuation and brackets as symbols.",
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


def load_transcription_initial_prompt(config_data: dict | None = None) -> str:
    """Return the transcription initial prompt.

    Priority: ``transcription_initial_prompt.txt`` on disk →
    *config_data*[``transcription_initial_prompt``] (migration path from JSON) →
    built-in default.
    """
    if TRANSCRIPTION_PROMPT_PATH.exists():
        try:
            return TRANSCRIPTION_PROMPT_PATH.read_text(encoding="utf-8")
        except Exception:
            pass
    if config_data and "transcription_initial_prompt" in config_data:
        return config_data["transcription_initial_prompt"]
    return _DEFAULT_TRANSCRIPTION_INITIAL_PROMPT


def save_transcription_initial_prompt(text: str) -> None:
    """Persist the transcription initial prompt to ``transcription_initial_prompt.txt``."""
    TRANSCRIPTION_PROMPT_PATH.write_text(text, encoding="utf-8")


# ── Corrector-Prompt helpers ──────────────────────────────────────────────────


def _parse_corrector_prompt_file(path: Path) -> tuple[str, str]:
    """Parse a corrector prompt markdown file into (title, body)."""
    try:
        content = path.read_text(encoding="utf-8")
    except Exception:
        return path.stem, ""
    lines = content.splitlines()
    title = path.stem
    body_start = 0
    if lines and lines[0].startswith("# "):
        title = lines[0][2:].strip()
        body_start = 1
        while body_start < len(lines) and lines[body_start].strip() == "":
            body_start += 1
    body = "\n".join(lines[body_start:])
    return title, body


def _ensure_corrector_prompts_dir() -> None:
    """Create corrector_prompts dir and migrate system_prompt.txt on first run."""
    CORRECTOR_PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    default_file = CORRECTOR_PROMPTS_DIR / DEFAULT_CORRECTOR_PROMPT_FILE
    if not default_file.exists():
        if PROMPT_PATH.exists():
            try:
                body = PROMPT_PATH.read_text(encoding="utf-8")
            except Exception:
                body = _DEFAULT_SYSTEM_PROMPT
        else:
            body = _DEFAULT_SYSTEM_PROMPT
        save_corrector_prompt(DEFAULT_CORRECTOR_PROMPT_FILE, "Werkseinstellung", body)


def list_corrector_prompts() -> list[dict]:
    """Return all corrector prompts as list of {filename, title, text} sorted by filename."""
    _ensure_corrector_prompts_dir()
    result = []
    for path in sorted(CORRECTOR_PROMPTS_DIR.glob("*.md")):
        title, text = _parse_corrector_prompt_file(path)
        result.append({"filename": path.name, "title": title, "text": text})
    return result


def load_corrector_prompt(filename: str) -> tuple[str, str]:
    """Return (title, text) for the given corrector prompt filename."""
    _ensure_corrector_prompts_dir()
    path = CORRECTOR_PROMPTS_DIR / filename
    if path.exists():
        return _parse_corrector_prompt_file(path)
    return "", ""


def save_corrector_prompt(filename: str, title: str, text: str) -> None:
    """Write a corrector prompt as a markdown file."""
    CORRECTOR_PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    content = f"# {title}\n\n{text}"
    (CORRECTOR_PROMPTS_DIR / filename).write_text(content, encoding="utf-8")


def delete_corrector_prompt(filename: str) -> None:
    """Delete a corrector prompt file."""
    path = CORRECTOR_PROMPTS_DIR / filename
    if path.exists():
        path.unlink()


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
    "whisper_provider": "local",
    "transcription_guidance_enabled": False,
    "whisper_endpoint": "transcribe",
    "health_endpoint": "health",
    "language": "de",
    "ui_language": "de",
    "response_format": "text",
    "sample_rate": 16000,
    "channels": 1,
    "max_recording": 60,
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
    "active_corrector_prompt": "default.md",
    "temperature": 0,
    "top_p": 1,
    "num_ctx": 1024,
    "max_tokens": 220,
    "proxy": "",
}


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


_KEYRING_APP = "Fl\u00fcsterFee"


def get_token(service: str, provider: str) -> str:
    """Retrieve an API token from the system keyring.

    *service* is ``'whisper'`` or ``'correction'``; *provider* is the
    provider name (e.g. ``'Groq'``, ``'Openrouter'``, ``'Ollama'``).
    Returns an empty string if no token is stored or keyring is unavailable.
    """
    try:
        return _keyring.get_password(f"{_KEYRING_APP}/{service}", provider) or ""
    except Exception:
        return ""


def set_token(service: str, provider: str, token: str) -> None:
    """Store or clear an API token in the system keyring."""
    try:
        if token:
            _keyring.set_password(f"{_KEYRING_APP}/{service}", provider, token)
        else:
            try:
                _keyring.delete_password(f"{_KEYRING_APP}/{service}", provider)
            except Exception:
                pass
    except Exception:
        pass


class Config:
    def __init__(self):
        self.reload()

    def reload(self):
        data = load_config()
        self.raw = data
        # One-time migration: move plaintext tokens from config.json to keyring
        _changed = False
        # Migrate legacy provider name
        if data.get("whisper_provider") == "lokal":
            data["whisper_provider"] = "local"
            _changed = True
        _wt = data.get("whisper_token", "")
        if _wt:
            set_token("whisper", data.get("whisper_provider", "local"), _wt)
            data.pop("whisper_token")
            _changed = True
        _ct = data.get("correction_token", "")
        if _ct:
            set_token("correction", data.get("llm_provider", "Ollama"), _ct)
            data.pop("correction_token")
            _changed = True
        if _changed:
            save_config(data)
        self.whisper_url = data["whisper_url"]
        self.port = data.get("port", None)
        self.whisper_token = get_token("whisper", data.get("whisper_provider", "local"))
        self.whisper_model = data.get("whisper_model", "")
        self.whisper_provider = data.get("whisper_provider", "local")
        self.transcription_guidance_enabled = bool(
            data.get("transcription_guidance_enabled", False)
        )
        self.transcription_initial_prompt = load_transcription_initial_prompt(data)
        self.whisper_endpoint = data.get("whisper_endpoint", "/transcribe")
        self.health_endpoint = data.get("health_endpoint", "/health")
        self.language = data["language"]
        self.ui_language = data.get("ui_language", "de")
        self.response_format = data["response_format"]
        self.sample_rate = int(data["sample_rate"])
        self.channels = int(data["channels"])
        self.max_recording = int(data.get("max_recording", 60))
        self.input_device = data.get("input_device", None)
        self.hotkey_keys = data["hotkey_keys"]
        self.restore_clipboard = bool(data["restore_clipboard"])
        self.audio_filename = data["audio_filename"]
        self.correction_enabled = bool(data.get("correction_enabled", True))
        self.correction_url = data.get("correction_url", "http://10.4.190.16")
        self.correction_port = data.get("correction_port", 11434)
        self.correction_token = get_token(
            "correction", data.get("llm_provider", "Ollama")
        )
        self.correction_model = data.get(
            "correction_model", "hf.co/unsloth/Qwen3-4B-Instruct-2507-GGUF:Q4_K_M"
        )
        self.llm_provider = data.get("llm_provider", "Ollama")
        self.temperature = data.get("temperature", 0)
        self.top_p = data.get("top_p", 1)
        self.num_ctx = data.get("num_ctx", 1024)
        self.max_tokens = data.get("max_tokens", 220)
        self.active_corrector_prompt = data.get(
            "active_corrector_prompt", DEFAULT_CORRECTOR_PROMPT_FILE
        )
        _ensure_corrector_prompts_dir()
        _, prompt_text = load_corrector_prompt(self.active_corrector_prompt)
        if not prompt_text:
            _, prompt_text = load_corrector_prompt(DEFAULT_CORRECTOR_PROMPT_FILE)
        self.system_prompt = prompt_text or load_system_prompt(data)
        self.proxy = data.get("proxy", "")
