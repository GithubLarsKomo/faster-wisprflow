import json
import pathlib

prompt = "\n".join(
    [
        "Du bist ein extrem schneller Speech-to-Text Cleanup-Prozessor.",
        "",
        "AUFGABE:",
        "Korrigiere ausschließlich:",
        "",
        "Orthographie",
        "Zeichensetzung",
        "Groß-/Kleinschreibung",
        "offensichtliche Speech-to-Text Fehler",
        "deutsche Umlaute",
        "Satzstruktur bei Diktatfragmenten",
        "",
        "REGELN:",
        "",
        "KEINE neuen Informationen hinzufügen",
        "Bedeutung NICHT verändern",
        "KEINE Zusammenfassung",
        "KEINE Umformulierungen außer minimal notwendig",
        "Fachbegriffe erhalten",
        "Sprache automatisch erkennen (Deutsch/English)",
        "Ausgabe nur als finaler Text",
        "Kein Markdown",
        "Keine Erklärungen",
        "",
        "",
        "{{raw_text}}",
    ]
)

cfg = {
    "whisper_url": "http://10.4.190.16",
    "port": 8009,
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
    "llm_correction_enabled": True,
    "llm_correction_url": "http://10.4.190.16",
    "llm_correction_port": 11434,
    "llm_correction_model": "qwen3.5:4b",
    "llm_correction_temperature": 0,
    "llm_correction_top_p": 1,
    "llm_correction_max_tokens": 2048,
    "llm_correction_system_prompt": prompt,
}

p = pathlib.Path(__file__).parent / "config.json"
p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), "utf-8")
json.loads(p.read_text("utf-8"))
print("config.json fixed and verified")
