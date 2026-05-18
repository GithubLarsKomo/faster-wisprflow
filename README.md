# FlüsterFee

Spracheingabe-Tool für Windows. Hotkey halten → sprechen → loslassen — der transkribierte Text wird automatisch an der Cursorposition eingefügt.

Unterstützt lokale Whisper-Server sowie Cloud-Dienste (Groq, OpenRouter). Optional korrigiert ein lokales oder cloudbasiertes LLM den transkribierten Text automatisch.

---

## Features

- **Hotkey-Diktat** — Hotkey halten = aufnehmen, loslassen = transkribieren und einfügen
- **Animiertes Mic-Level-Popup** — Pill-förmiges Popup mit Pegelbalken während der Aufnahme, Punkte-Animation während der Transkription
- **LLM-Korrektur** — OpenAI-kompatibler Endpunkt (Ollama, Groq, OpenRouter) korrigiert Rechtschreibung, Zeichensetzung und Sprachfehler; Prompt vollständig anpassbar
- **Vokabular-Substitution** — Bekannte Wort-Ersetzungen aus `vocabulary.json` werden vor dem Einfügen automatisch angewendet; über das Einstellungsfenster verwaltbar
- **Multi-Monitor-Unterstützung** — Overlay und Popup erscheinen auf dem mittleren Monitor
- **System-Tray-Integration** — Läuft im Hintergrund, Rechtsklick für Menü
- **Admin-Auto-Elevation** — Optional beim Start automatisch Administratorrechte anfordern

---

## Voraussetzungen

- Windows 10/11
- Laufender Whisper-HTTP-Server, z. B. [`faster-whisper-server`](https://github.com/fedirz/faster-whisper-server) (lokal), oder ein Cloud-Dienst (Groq, OpenRouter)
- Python 3.12+ mit [uv](https://github.com/astral-sh/uv) — nur für die Entwicklung

---

## Schnellstart (EXE)

1. `FlüsterFee.exe` und `config.json` in denselben Ordner legen
2. `config.json` anpassen (Whisper-URL, Mikrofon, Hotkey)
3. Optional: `system_prompt.txt` neben der EXE ablegen, um den LLM-Prompt zu überschreiben
4. EXE starten — das Icon erscheint im System-Tray

---

## Konfiguration (`config.json`)

### Allgemein

| Schlüssel | Standard | Beschreibung |
|---|---|---|
| `hotkey_keys` | `["ctrl", "linke windows"]` | Hotkey-Kombination (gedrückt halten zum Aufnehmen) |
| `language` | `"de"` | Sprache (ISO-639-1); beeinflusst Transkription und LLM-Prompt |
| `restore_clipboard` | `true` | Clipboard-Inhalt nach dem Einfügen wiederherstellen |
| `auto_elevate` | `true` | Beim Start automatisch Administratorrechte anfordern |
| `proxy` | `""` | HTTP-Proxy-URL (leer = kein Proxy) |

> `hotkey_keys` akzeptiert sowohl `"left windows"` als auch `"linke windows"`.

### Whisper-Transkription

| Schlüssel | Standard | Beschreibung |
|---|---|---|
| `whisper_url` | `"http://10.4.190.16"` | Basis-URL des Whisper-Servers |
| `port` | `8009` | Port (0 oder leer = keinen Port anhängen) |
| `whisper_provider` | `"lokal"` | `"lokal"`, `"Openrouter"` oder `"Groq"` |
| `whisper_endpoint` | `"transcribe"` | Endpunkt-Pfad |
| `whisper_model` | `"whisper-large-v3-turbo"` | Modellname (für Openrouter/Groq) |
| `whisper_token` | `""` | Bearer-Token (Openrouter/Groq) |
| `health_endpoint` | `"health"` | Health-Check-Endpunkt |
| `response_format` | `"text"` | `"text"` oder `"json"` |
| `sample_rate` | `16000` | Abtastrate in Hz |
| `channels` | `1` | Audiokanäle (1 = Mono) |
| `input_device` | `0` | Mikrofon-Index (0 = System-Standard) |

### LLM-Korrektur

| Schlüssel | Standard | Beschreibung |
|---|---|---|
| `correction_enabled` | `true` | LLM-Korrektur aktivieren |
| `correction_url` | `"http://10.4.190.16"` | Basis-URL des LLM-Servers |
| `correction_port` | `11434` | Port des LLM-Servers |
| `llm_provider` | `"Ollama"` | `"Ollama"`, `"Openrouter"` oder `"Groq"` |
| `correction_model` | `"hf.co/unsloth/Qwen3-4B-Instruct-2507-GGUF:Q4_K_M"` | Modellname |
| `correction_token` | `""` | Bearer-Token (Openrouter/Groq) |
| `temperature` | `0` | Sampling-Temperatur |
| `top_p` | `1` | Top-p-Wert |
| `max_tokens` | `220` | Maximale Ausgabelänge in Tokens |
| `num_ctx` | `1024` | Kontextfenstergröße (Ollama: `num_ctx`) |

---

## LLM-Korrektur

FlüsterFee sendet den transkribierten Text an einen OpenAI-kompatiblen Chat-Endpunkt und gibt den korrigierten Text zurück. Fehler beim LLM-Aufruf werden still ignoriert — der Originaltext wird dann unverändert eingefügt.

### System-Prompt

Der Prompt wird aus `system_prompt.txt` geladen (neben `config.json`). Existiert die Datei nicht, wird der eingebaute Standardprompt verwendet.

**Bearbeiten:**
- Direkt in `system_prompt.txt` (beliebiger Texteditor)
- Oder über **Einstellungen → LLM-Prompt bearbeiten** in der App

Im Prompt wird `{{language}}` automatisch durch den konfigurierten ISO-Sprachcode ersetzt.

### Unterstützte Backends

| Provider | URL |
|---|---|
| Ollama (Standard) | `<correction_url>:<correction_port>/v1/chat/completions` |
| OpenRouter | `https://openrouter.ai/api/v1/chat/completions` |
| Groq | `https://api.groq.com/v1/chat/completions` |

---

## Vokabular

`vocabulary.json` enthält Wort-Ersetzungen, die nach der Transkription und vor dem LLM-Aufruf angewendet werden (z. B. häufig falsch erkannte Eigennamen). Das Vokabular wird **nicht** automatisch gelernt — Einträge werden ausschließlich manuell über **Einstellungen → Vokabular verwalten** oder durch direktes Bearbeiten der JSON-Datei hinzugefügt.

---

## Einstellungsfenster

| Button | Funktion |
|---|---|
| **Mikrofon testen** | 3-Sekunden-Aufnahme mit Pegelanzeige |
| **Health Check** | Erreichbarkeit des Whisper-Servers prüfen |
| **Whisper testen** | 3-Sekunden-Aufnahme mit sofortiger Transkription |
| **Testkorrektur** | LLM-Verbindung testen |
| **Vokabular verwalten** | Einträge in `vocabulary.json` ansehen, hinzufügen und entfernen |
| **LLM-Prompt bearbeiten** | System-Prompt und Modell-Parameter (Temperature, Top-p, Max Tokens, Context) bearbeiten |
| **Speichern** | Einstellungen sichern und Hotkey sofort aktualisieren |
| **Werkseinstellungen** | Alle Einstellungen auf Standardwerte zurücksetzen |

---

## Build (EXE erstellen)

```powershell
.venv\Scripts\pyinstaller.exe FlüsterFee.spec
```

Die fertige EXE liegt unter `dist\FlüsterFee.exe`. Folgende Dateien müssen **neben** der EXE liegen:

| Datei | Pflicht | Beschreibung |
|---|---|---|
| `config.json` | ✅ | Konfiguration |
| `vocabulary.json` | optional | Wort-Ersetzungen |
| `system_prompt.txt` | optional | Überschreibt den eingebauten LLM-Prompt |

---

## Tray-Icon anpassen

1. `tray_icon.png` (PNG, empfohlen 256×256, RGBA) ins Projektverzeichnis legen
2. `tray_icon.ico` (ICO) für das EXE-Datei-Icon
3. Neu bauen

---

## Entwicklung

```powershell
uv sync
uv run python app.py
```

Tests ausführen:

```powershell
.venv\Scripts\python.exe -m pytest tests/ -q
```
