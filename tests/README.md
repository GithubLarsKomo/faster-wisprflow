# Test Suite

Die Test-Suite deckt Kernmodule und kritische Integrationsgrenzen ab. Die Anzahl der Tests wird bewusst nicht hier festgeschrieben; pytest ist die Quelle der Wahrheit.

## Ausführen

```powershell
uv sync --frozen
uv pip install pytest==8.4.2
uv run pytest tests/ -q
```

Der Windows-CI-Workflow führt zusätzlich Ruff und einen PyInstaller-Smoke-Build aus.

## Struktur

```text
tests/
├── conftest.py
├── test_app_run_lifecycle.py   # Cancel/Restart/Stale-Worker-Races
├── test_config.py
├── test_llm_corrector.py       # Provider, Truncation, Non-Loss
├── test_provider_registry.py   # zentrale Provider-Verträge
├── test_recorder.py            # Audio + eindeutige Temp-Artefakte
├── test_text_inserter.py       # Win32 Clipboard/Cursor
├── test_translations.py        # 8-Sprachen-Vollständigkeit
├── test_vocabulary.py
└── test_whisper_client.py      # STT-Routing und Request-Contracts
```

## Kritische Regression-Gates

- **Run-Lifecycle:** Abgebrochene oder stale Worker dürfen einen neueren Lauf weder überschreiben noch dessen Status ändern.
- **Audio-Artefakte:** Jeder Lauf besitzt eine eigene temporäre WAV-Datei.
- **Provider-Contracts:** Kanonische URLs und provider-spezifische Requestformen sind explizit getestet.
- **LLM Non-Loss:** Truncation oder starke Inhaltsverluste fallen auf das vollständige Rohtranskript zurück.
- **Cursor/Clipboard:** Kontext-Peek und Win32-Paste-Verhalten dürfen die Cursorposition nicht verschieben.
- **Übersetzungen:** Alle acht UI-Sprachen besitzen denselben Schlüsselumfang und keine leeren Werte.
