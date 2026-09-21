# FlüsterFee

Push-to-talk-Spracheingabe für Windows: Hotkey oder mittlere Maustaste halten, sprechen, loslassen – FlüsterFee transkribiert, korrigiert optional und fügt den Text an der Cursorposition ein.

## Funktionen

- Push-to-talk per konfigurierbarem Hotkey oder mittlerer Maustaste
- Qt-Dock mit Aufnahmepegel, Verarbeitungsstatus und Abbruch
- Transkription über lokalen OpenAI-/Whisper-kompatiblen HTTP-Endpunkt, Groq, OpenRouter oder OpenAI
- optionale Transkriptions-Guidance für Diktatkommandos und Interpunktion
- Vokabular-Ersetzungen aus `vocabulary.json`
- Fast / Smart / Polish für die Korrektur: Smart nutzt zunächst ein lokales heuristisches Gate
- optionale LLM-Korrektur über Ollama, LM Studio, Groq, OpenRouter, OpenAI, Anthropic oder Azure-OpenAI-kompatible Endpunkte
- mehrere editierbare Korrektur-Prompts
- API-Token im Windows Credential Manager statt in `config.json`
- Proxy- und Enterprise-TLS-Unterstützung
- mehrsprachige UI: de, en, fr, es, zh, pt, pl, it
- laufbezogene Abbruchlogik: Ergebnisse abgebrochener oder überholter Requests werden verworfen

## Voraussetzungen

Für die fertige EXE:
- Windows 10/11
- ein konfigurierter Transkriptionsanbieter
- optional ein LLM-Anbieter für die Korrektur

Für Entwicklung und Build:
- Python 3.12+
- `uv`

## Erster Start

`config.json` ist eine lokale Runtime-Datei und wird nicht versioniert. Fehlt sie, erzeugt FlüsterFee sie beim Start aus portablen Defaults.

Als Referenz liegt `config.example.json` im Repository. Cloud-API-Token werden über die Einstellungen im Windows Credential Manager gespeichert und gehören nicht in die JSON-Datei.

## Pipeline

```text
Hotkey / mittlere Maustaste
        ↓
Recorder
        ↓
WhisperClient
        ↓
VocabularyManager
        ↓
Fast / Smart heuristic / Polish
        ↓
LLMCorrector (nur falls erforderlich)
        ↓
TextInserter
```

Jeder Diktat-Lauf besitzt eine eigene Run-ID, ein Cancel-Event und eine eigene temporäre WAV-Datei. Nur der aktuell aktive Lauf darf UI-Zustand oder Clipboard verändern.

## Konfiguration

| Schlüssel | Standard | Zweck |
|---|---:|---|
| `whisper_provider` | `local` | `local`, `Groq`, `Openrouter`, `OpenAI` |
| `whisper_url` | `http://127.0.0.1` | Basis-URL für lokalen STT-Endpunkt |
| `port` | `8009` | lokaler STT-Port |
| `whisper_endpoint` | `transcribe` | Transkriptionspfad |
| `language` | `de` | Zielsprache |
| `transcription_guidance_enabled` | `false` | Diktat-Guidance/Postprocessing |
| `correction_enabled` | `true` | Korrektur-Pipeline aktivieren |
| `correction_mode` | `smart` | `fast`, `smart` oder `polish` |
| `llm_provider` | `Ollama` | Korrekturanbieter |
| `correction_url` | `http://127.0.0.1` | Basis-URL für lokalen LLM-Endpunkt |
| `correction_port` | `11434` | lokaler LLM-Port |
| `max_tokens` | `220` | Mindestbudget; wächst bei längeren Diktaten dynamisch |
| `num_ctx` | `1024` | Kontextbudget |
| `restore_clipboard` | `true` | Text-Clipboard nach dem Einfügen wiederherstellen |

Die tatsächlich unterstützten Provider und deren feste öffentliche Endpunkte werden zentral in `provider_registry.py` definiert.

## Entwicklung

```powershell
uv sync --frozen
uv run python app.py
```

Tests:

```powershell
uv pip install pytest==8.4.2
uv run pytest tests/ -q
```

Lint:

```powershell
uv run ruff check .
```

## Build

```powershell
build.bat
```

oder direkt:

```powershell
uv sync --frozen
uv run pyinstaller FlüsterFee.spec
```

Die fertige Anwendung liegt unter `dist\FlüsterFee.exe`.

## Windows CI

`.github/workflows/windows-ci.yml` prüft auf Windows:

```text
uv sync --frozen
→ Ruff
→ pytest
→ PyInstaller
→ Existenz von dist/FlüsterFee.exe
```

## Projektstruktur

```text
app.py                    # Orchestrierung, RunContext, Pipeline
config.py                 # Defaults, Config, Keyring, Prompt-Dateien
provider_registry.py      # kanonische Provider-Verträge
recorder.py               # Audioaufnahme und run-eigene Temp-WAV
whisper_client.py         # Transkriptionsadapter
llm_corrector.py          # LLM-Korrektur + Non-Loss-Gates
text_inserter.py          # Clipboard-/Cursor-basiertes Einfügen
vocabulary.py             # Vokabular-Ersetzungen
tray.py                   # System-Tray
ui/
  dock.py
  settings_dialog.py
  theme.py
  translations.py
  utils.py
tests/
  test_app_run_lifecycle.py
  test_provider_registry.py
  ...
```

## Hardening

Technische Spezifikation und Fahrplan: `SPEC.md` und `ROADMAP.md`.
