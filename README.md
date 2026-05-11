# EuroWisprFlow

Spracheingabe-Tool für Windows. Drücke den Hotkey, sprich, lasse los — der transkribierte Text wird automatisch an der Cursorposition eingefügt.

Basiert auf einem lokalen [Faster-Whisper](https://github.com/SYSTRAN/faster-whisper)-Server.

---

## Voraussetzungen

- Windows 10/11
- Laufender Whisper-HTTP-Server (z. B. `faster-whisper-server`)
- Python 3.12+ mit [uv](https://github.com/astral-sh/uv) (nur für Entwicklung)

---

## Schnellstart (EXE)

1. `EuroWisprFlow.exe` und `config.json` in denselben Ordner legen
2. `config.json` anpassen (Whisper-URL, Mikrofon, Hotkey)
3. EXE starten — das Icon erscheint im System-Tray

---

## Konfiguration (`config.json`)

| Schlüssel | Standard | Beschreibung |
|---|---|---|
| `whisper_url` | `http://localhost:8008/transcribe` | URL des Whisper-Servers |
| `language` | `de` | Sprache der Transkription |
| `response_format` | `text` | `text` oder `json` |
| `sample_rate` | `16000` | Abtastrate in Hz |
| `channels` | `1` | Audiokanäle (1 = Mono) |
| `input_device` | `null` | Mikrofon-Index (null = System-Standard) |
| `hotkey_keys` | `["ctrl", "linke windows"]` | Hotkey-Kombination (gedrückt halten zum Aufnehmen) |
| `restore_clipboard` | `true` | Clipboard nach Einfügen wiederherstellen |
| `auto_elevate` | `false` | Beim Start automatisch Admin-Rechte anfordern |

> **Hinweis:** `hotkey_keys` akzeptiert sowohl `"left windows"` (englisch) als auch `"linke windows"` (deutsch).

---

## Bedienung

| Aktion | Beschreibung |
|---|---|
| Hotkey **halten** | Aufnahme starten |
| Hotkey **loslassen** | Aufnahme stoppen, Transkription starten, Text einfügen |
| Tray-Icon Rechtsklick → **Einstellungen** | Einstellungsfenster öffnen |
| Tray-Icon Rechtsklick → **Beenden** | App beenden |

Das Overlay erscheint unten mittig auf dem Bildschirm und zeigt den aktuellen Status an.

---

## Einstellungsfenster

- Whisper-URL, Sprache, Mikrofon, Sample Rate, Kanäle, Hotkey konfigurieren
- **Mikrofon testen** — 3-Sekunden-Aufnahme mit Pegelanzeige
- **Whisper testen** — 3-Sekunden-Aufnahme mit sofortiger Transkription

---

## Build (EXE erstellen)

```powershell
uv run pyinstaller --clean --onefile --noconsole --name EuroWisprFlow --add-data "tray_icon.png;." --icon tray_icon.ico app.py
```

Die fertige EXE liegt unter `dist\EuroWisprFlow.exe`. Die `config.json` muss **neben** der EXE liegen.

---

## Tray-Icon anpassen

1. Icon als `tray_icon.png` (PNG, empfohlen 256×256, RGBA) ins Projektverzeichnis legen
2. Icon als `tray_icon.ico` (ICO) für das EXE-Datei-Icon
3. Neu bauen

---

## Entwicklung

```powershell
uv sync
uv run python app.py
```
