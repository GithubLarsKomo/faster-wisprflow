# FlüsterFee

Push-to-talk Spracheingabe fuer Windows: Hotkey halten -> sprechen -> loslassen -> Text wird automatisch an der Cursorposition eingefuegt.

## Funktionsuebersicht

| Feature | Details |
|---|---|
| Hotkey-Diktat | Hotkey gedrueckt halten = aufnehmen, loslassen = transkribieren und einfuegen |
| Animiertes Popup | Pill-Overlay mit Pegelbalken (Aufnahme) und Punkte-Animation (Transkription) |
| Transkription | Lokaler Whisper-Endpunkt, Groq oder OpenRouter |
| Transkriptions-Guidance | Optionales Prompting + Normalisierung fuer Satzzeichen/Befehle |
| Editierbarer Initial Prompt | Eigener Prompt fuer Transkription in den Einstellungen, persistiert in Datei |
| LLM-Korrektur | Ollama, Groq oder OpenRouter fuer Textkorrektur |
| Multi-Prompt-Manager | Mehrere Korrektur-Prompts als Markdown-Dateien, aktiver Prompt per Klick waehlbar |
| Vokabular | Ersetzungen aus `vocabulary.json`, im UI verwaltbar |
| Cursor-Kontext-Grossschreibung | Optional: erster Buchstabe wird am Cursor-Kontext ausgerichtet |
| Mehrsprachige UI | de, en, fr, es, zh, pt, pl, it |
| Proxy-Support | Optionaler HTTP-Proxy fuer ausgehende Requests |
| System-Tray | Laeuft im Hintergrund mit Tray-Menue |

## Voraussetzungen

- Windows 10/11
- Laufender Whisper-Endpunkt (lokal) oder Zugang zu Groq/OpenRouter
- Python 3.12+ mit `uv` (nur fuer Entwicklung)

## Schnellstart (EXE)

1. `FlüsterFee.exe` und `config.json` in denselben Ordner legen.
2. `config.json` mindestens fuer Whisper-URL/Port und Hotkey konfigurieren.
3. EXE starten, ueber Tray/Einstellungen Feintuning vornehmen.

Optionale Dateien neben der EXE:

- `corrector_prompts/` Ordner mit `*.md`-Dateien fuer LLM-Korrektur-Prompts (wird beim ersten Start automatisch angelegt)
- `transcription_initial_prompt.txt` fuer Transkriptions-Initial-Prompt

## Konfiguration (`config.json`)

### Allgemein

| Schluessel | Standard | Beschreibung |
|---|---|---|
| `hotkey_keys` | `['ctrl', 'linke windows']` | Hotkey-Kombination |
| `language` | `'de'` | Zielsprache (ISO-639-1) |
| `ui_language` | `'de'` | UI-Sprache |
| `restore_clipboard` | `true` | Clipboard nach Einfuegen wiederherstellen |
| `auto_elevate` | `true` | Beim Start Admin-Rechte anfordern |
| `proxy` | `''` | HTTP-Proxy-URL (leer = kein Proxy) |

### Audio

| Schluessel | Standard | Beschreibung |
|---|---|---|
| `sample_rate` | `16000` | Abtastrate in Hz |
| `channels` | `1` | Audiokanaele |
| `max_recording` | `60` | Maximale Aufnahmezeit pro Aufnahme (Sekunden) |
| `input_device` | `null` | Mikrofon-Index (`null` = System-Standard) |

### Whisper-Transkription

| Schluessel | Standard | Beschreibung |
|---|---|---|
| `whisper_provider` | `'lokal'` | `'lokal'`, `'Openrouter'`, `'Groq'` |
| `whisper_url` | `'http://10.4.190.16'` | Basis-URL (lokal) |
| `port` | `8009` | Port (0/leer = kein Portanhaengen) |
| `whisper_endpoint` | `'transcribe'` | Endpunkt-Pfad |
| `health_endpoint` | `'health'` | Health-Check-Endpunkt |
| `whisper_model` | `'whisper-large-v3-turbo'` | Modellname |
| `whisper_token` | `''` | Bearer-Token (Cloud-Provider) |
| `response_format` | `'text'` | `'text'` oder `'json'` |
| `transcription_guidance_enabled` | `false` | Aktiviert Guidance inkl. Initial Prompt |

### LLM-Korrektur

| Schluessel | Standard | Beschreibung |
|---|---|---|
| `correction_enabled` | `true` | LLM-Korrektur aktivieren |
| `llm_provider` | `'Ollama'` | `'Ollama'`, `'Openrouter'`, `'Groq'` |
| `correction_url` | `'http://10.4.190.16'` | Basis-URL (Ollama) |
| `correction_port` | `11434` | Port (Ollama) |
| `correction_model` | `hf.co/unsloth/Qwen3-4B-Instruct-2507-GGUF:Q4_K_M` | Modellname |
| `correction_token` | `''` | Bearer-Token (Cloud-Provider) |
| `temperature` | `0` | Sampling-Temperatur |
| `top_p` | `1` | Top-p |
| `max_tokens` | `220` | Maximale Ausgabelaenge |
| `num_ctx` | `1024` | Kontextfenster |
| `active_corrector_prompt` | `'default.md'` | Aktiver Korrektur-Prompt (Dateiname in `corrector_prompts/`) |

## Prompt-Dateien

### LLM-Korrektur-Prompts

- Ordner: `corrector_prompts/` neben der EXE (wird beim ersten Start automatisch erstellt)
- Jeder Prompt ist eine Markdown-Datei: erste Zeile `# Titel`, danach Prompt-Text
- Platzhalter: `{{language}}`
- Im Einstellungsfenster (LLM-Korrektur) koennen Prompts erstellt, bearbeitet, dupliziert, geloescht und der aktive Prompt gesetzt werden
- Bei Migration wird `system_prompt.txt` automatisch als `default.md` uebernommen

### Transkriptions-Initial-Prompt

- Datei: `transcription_initial_prompt.txt`
- Wird bei aktivierter Transkriptions-Guidance verwendet.
- Platzhalter: `{{language}}`
- Kann im Fenster Transkription bearbeitet und auf Standard zurueckgesetzt werden.

## Pipeline-Reihenfolge

1. Transkription (`WhisperClient`)
2. Vokabular-Ersetzungen (`VocabularyManager`)
3. LLM-Korrektur (`LLMCorrector`, falls aktiv)
4. Einfuegen am Cursor (`TextInserter`)

## Einstellungsfenster

| Bereich | Funktion |
|---|---|
| Mikrofon testen | 3-Sekunden-Aufnahme mit Pegelanzeige |
| Transkription | Provider, URL, Port, Modell, Token, Guidance-Checkbox, Initial-Prompt-Editor |
| LLM-Korrektur | Provider, URL, Port, Modell, Token, Korrektur-Prompt-Manager (Neu/Duplizieren/Loeschen/Aktiv setzen/Speichern), Modellparameter |
| Vokabular verwalten | Eintraege ansehen, hinzufuegen, bearbeiten, entfernen |
| Speichern | Einstellungen speichern und sofort uebernehmen |

## Build (EXE)

```powershell
.venv\Scripts\pyinstaller.exe FlüsterFee.spec
```

Die fertige EXE liegt unter `dist\FlüsterFee.exe`. Diese Dateien sollten neben der EXE liegen:

| Datei | Pflicht | Beschreibung |
|---|---|---|
| `config.json` | ja | Hauptkonfiguration |
| `vocabulary.json` | optional | Wort-/Phrasen-Ersetzungen |
| `corrector_prompts/` | optional | Ordner mit LLM-Korrektur-Prompts (`*.md`); wird beim ersten Start auto-erstellt |
| `transcription_initial_prompt.txt` | optional | Initial-Prompt fuer Transkription |

## Tray-Icon anpassen

1. `tray_icon.png` ins Projektverzeichnis legen (empfohlen 256x256, RGBA)
2. Optional `tray_icon.ico` fuer EXE-Icon
3. Neu bauen

## Entwicklung

```powershell
uv sync
uv run python app.py
```

Tests:

```powershell
.venv\Scripts\python.exe -m pytest tests/ -q
```

### Projektstruktur

```text
app.py               # Einstiegspunkt und Pipeline
config.py            # Defaults, Laden/Speichern, Prompt-Dateien
recorder.py          # Audioaufnahme
whisper_client.py    # Transkriptions-Client + Guidance
llm_corrector.py     # LLM-Korrektur
text_inserter.py     # Clipboard-/Cursor-basiertes Einfuegen
vocabulary.py        # Vokabular-Ersetzungen
tray.py              # System-Tray
ui/
  overlay.py
  popups.py
  settings_window.py
  translations.py
  utils.py
```
