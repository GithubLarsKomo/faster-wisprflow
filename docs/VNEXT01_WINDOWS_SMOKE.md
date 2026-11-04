# vNext-01 — Windows Smoke- und Latenz-Baseline

**Status:** Manuelle Prüfung erforderlich. Keine Behauptung, dass echte Windows-Tests erfolgreich waren.
**Umfang:** Nur PR vNext-01 (Timing und Zielfensterbindung). Keine neuen ASR-Modelle, Streaming-Implementierung oder App-Profile.

## Testvorbereitung

Auf Windows 10/11 mit PowerShell im Repository:

~~~powershell
uv sync --frozen
uv run ruff check .
uv run pytest tests/ -q
uv run pyinstaller FlüsterFee.spec
~~~

Die EXE im lokalen Nutzerprofil starten. Für alle manuell geprüften Fälle Windows- und Ziel-App-Version, Git-SHA, Backend/Modelldigest sowie erwartetes/beobachtetes Einfügeverhalten protokollieren. Keine geheimen Tokens, Unternehmens- oder Patientendaten in das öffentliche Repository committen.

## Manuelle Negativ- und Positivmatrix

1. **Grundfunktion:** Notepad, Word, Outlook-Neue-Mail, Edge/Chrome-Textfeld, VS Code: normal diktieren. Text muss genau einmal im erwarteten Feld landen.
2. **Fensterwechsel:** Diktat beenden und vor Ende von ASR bzw. LLM in eine andere Anwendung wechseln. Keine automatische Einfügung. Stattdessen den Text im lokalen Review-Dialog anzeigen und erst nach bewusstem Klick kopieren.
3. **Gleicher Prozess, anderes Fenster:** Word-Dokument A → B, Browserfenster A → B. Beides darf nicht als identisches Ziel durchgehen.
4. **Gleicher HWND, anderer Tab / Eingabebereich:** Browser-Tab A → B und Eingabefeld A → B. Diese Fälle sind besonders kritisch: HWND und fokussiertes HWND können gleich bleiben. **Wird die Änderung nicht erkannt, ist die Zielbindung für diesen App-Fall nicht vollständig; kein uneingeschränktes Go.**
5. **Race:** Lauf A während ASR oder LLM abbrechen, B starten, A verspätet zurückkommen lassen. Kein Paste, Dock-Wechsel oder Recovery-Dialog für A nach Aktivierung von B.
6. **Clipboard:** Bereits belegte Zwischenablage, durch fremden Prozess blockiertes Clipboard, aktiver Clipboard-Wechsel kurz vor Paste, Rich-Text-Clipboard. Originaleintrag nach bestehenden Restore-Regeln erhalten; keine alte/andere Paste bei Fehler.
7. **Fokus- und Prozessfehler:** Ziel minimieren, schließen, Prozess ersetzen, RDP, administrativ laufendes Ziel. Bei unbekanntem Zustand nie automatisch einfügen.
8. **Diktat-Guidance:** Aktiviert die Cursor-Kontextinspektion. Der ursprüngliche Cursor darf sich nicht verschieben; danach Ziel erneut prüfen.
9. **Mehrsprachigkeit:** Recovery-Dialog in de/en/fr/es/zh/pt/pl/it; Qt-Signal kommt aus dem Hintergrundthread, Anzeige erfolgt auf dem GUI-Thread.

**Grenze:** SendInput bestätigt nur, dass Windows Eingabeereignisse annimmt – nicht, dass die Ziel-App Text verarbeitet. HWND+PID+Prozessstartzeit+fokussiertes HWND kann Browser-Tabs und manche Felder nicht eindeutig unterscheiden; bei fehlendem Beweis zur Feldidentität im Test ist die Freigabe einzuschränken bzw. UI Automation in einem Folge-PR zu ergänzen.

## Optionaler Offline-Latenzexport

In der lokalen, nicht versionierten config.json ergänzen:

~~~json
"latency_export_path": "latency-runs.jsonl"
~~~

Ohne diesen Eintrag bleiben die Messungen flüchtig im RAM; keine Netzwerktelemetrie. Beim **normalen Beenden** exportiert FlüsterFee ausschließlich Daten nach Schema 1: Run-ID, Providerklasse, Modus, Längenklasse, Ergebnis und Phasenintervalle. Kein Audio, Transkript, Windows-Titel, Clipboard oder Prompt. Die Datei ist lokal und nicht für Git bestimmt.

Nach mindestens 100 warmen Diktaten und regulärem Beenden:

~~~powershell
python benchmarks/dictation_latency/report.py --input "D:\FluesterFee\latency-runs.jsonl" --output "D:\Privat\fluesterfee-latency-report.json" --commit "<git-sha>" --environment "Win11; Hardware; LAN" --model-hash "<model-sha>" --warm yes
~~~

Den Wert des Pfads an die eigene Installation anpassen. Für einen echten Vorher/Nachher-Vergleich Baseline aus einer neutralen Instrumentierung des alten Builds oder einem externen Messharness verwenden; **nicht** vNext-01 selbst als unveränderten master-Baselinebuild ausgeben.

**Metriken:** audio_prepare_ms, asr_ms, gate_ms, llm_ms, insertion_ms, record_stop_to_asr_final_ms, asr_final_to_insert_ms, release_to_insert_ms; P50/P95 und Stichprobenzahl n pro Provider/Modus/Längenklasse. Übersprungene Phasen sind null und reduzieren n; keine künstliche Null-Millisekunden-Latenz.

## Release-Gate

- 0 falsche oder doppelte Einfügungen in der definierten Negativmatrix.
- 0 nicht genehmigte Netzwerk-/Cloud-Übertragungen oder Persistierungen sensibler Inhalte.
- Keine Stale-Run-, Cancel-, UI- oder Clipboard-Regressionen.
- Windows CI Ruff, pytest, PyInstaller erfolgreich.
- 100 warme Durchläufe je Core-Backend/Modus sowie dokumentierte P50/P95, Modell-/Hardware-/Git-Revision; fehlende Messungen als NOT MEASURED.
- Manuelle Abnahme für Notepad, Word, Outlook, Browser und VS Code; nicht testbare Felder explizit ausnehmen.

**Stand beim Anlegen:** Alle Windows-Manuelltests und echte Latenzbenchmarks noch nicht durchgeführt.
