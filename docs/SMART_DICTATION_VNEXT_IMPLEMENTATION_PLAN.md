# FlüsterFee Smart Dictation vNext — Implementierungs- und PR-Plan

**Status:** Vorschlag / noch nicht implementiert  
**Stand:** 2026-11-04  
**Projekt:** `GithubLarsKomo/faster-wisprflow` (`master`)  
**Zweck:** Konkreter Ausführungsplan für vier kleine, getrennt prüfbare Feature-PRs. Dieses Dokument enthält **keine** Produktiv-Codeänderung und keinen Nachweis für erfolgreiche Laufzeittests.  
**Bestehende Vorgaben:** [OPTIMIZATION.md](../OPTIMIZATION.md), [Three-Stage Optimization](THREE_STAGE_OPTIMIZATION.md), [ASR Postprocessing v2](ASR_POSTPROCESSING_V2.md), [SPEC.md](../SPEC.md).  
**Externe Lernquelle:** https://github.com/altic-dev/FluidVoice; Quellendigest: https://github.com/GithubLarsKomo/learning-projects/blob/main/docs/learning-sources/altic-fluidvoice-macos-local-asr-meetings-2026-11-03.md

## 0. Verified baseline & no-duplicate gate

Quellensnapshot: `master`-Commit `87dea5d0a38b6ea805b16e1c2c8620d829d73fef` (Merge Hardening/Smart/ASR v2, 2026-09-29). Vor Beginn jedes Feature-PRs neuesten `master`-Stand verifizieren.

| Bereits umgesetzt / dokumentiert | Konsequenz |
| --- | --- |
| `RunContext`, monotone Run-ID, Cancel-Event, run-eigene WAV, stale-result- und GUI-Gates in `app.py` | Unverändert weiterverwenden; neue Callbacks / Streaming-Partials müssen **dieselbe** Autorität prüfen. |
| `WhisperClient` mit `requests.Session`, Provider-Registry, Cloud-/lokale ASR-Pfade | Kein neuer generischer Provider-Layer parallel; Registry nur **erweitern**. |
| `Fast/Smart/Polish` inkl. heuristischem Smart-Gate | Nicht neu implementieren; Routing-/ML-Vorhaben sind in `OPTIMIZATION.md` bereits definiert und **nicht Bestandteil** von vNext. |
| `VocabularyManager` `vocabulary.json`, ASR-v2-Glossar und kurzer vorheriger Prozesskontext | Bestehende Datenform beibehalten; Mehrwort-Ersetzung und profilbezogene Auswahl hinzufügen. |
| Konservative LLM-Korrektur, Nichtverlust-/Truncation-Gates, optional Cloud | Produktvertrag bleibt: **kein Faktenhinzufügen, Zahl-/Negationsverlust, keine semantische Umschreibung im Dictation-Modus**. |
| `TextInserter` mit Clipboard/Ctrl+V, einfaches `_foreground_exe`, Restore-Option | Ziel-Fixierung und zuverlässige Erfolg-/Fehlerausgabe ergänzen, nicht Windows-UI-Schicht neu schreiben. |
| CI `.github/workflows/windows-ci.yml`: `uv sync --frozen` → Ruff → pytest → PyInstaller | Bestehendes Windows-CI erweitern; nicht durch eine zweite Pipeline ersetzen. |

**Gap im aktuellen Code:** `App._context_key()` ermittelt den Vordergrundprozess während der Verarbeitung und `TextInserter.insert_text()` verwendet beim Einfügen den dann aktiven Fokus. Eine Aufnahme ist nicht dauerhaft an das ursprüngliche Ziel gebunden. `VocabularyManager.apply()` arbeitet mit `text.split(" ")` und korrigiert einzelne Token, keine mehrteiligen Ausdrücke. `Recorder.stop()` materialisiert eine WAV erst nach Aufnahmestopp; `WhisperClient` verarbeitet aktuell eine vollständige Audiodatei, kein Live-Partial-Protokoll.

**Abgrenzung:** Diese vier PRs sind die **operative Konkretisierung** von `OPTIMIZATION.md` O0 (Instrumentierung), O3 (Provider-Capabilities), O7 (Realtime), O8 (UI) sowie einer zusätzlichen Ziel-/Vokabular-Sicherheitserweiterung. Nicht duplizieren: O2 (großer Multi-Engine-Benchmark), O4 (neue Defaultmodellwahl), O5 (XLM-R/BGE/Laya/Jev-Routing), O6 (`raw now`), O9 (breite Startup-Optimierung). Diese bleiben eigene spätere Arbeitspakete.

## 1. Zielbild und unveränderliche Invarianten

```text
Push-to-talk start
  -> capture immutable TargetSnapshot + profile id + run id
  -> Recorder (PCM frames)
      -> optional bounded realtime transport -> partial preview only
      -> on stop -> authoritative final ASR OR one batch fallback
  -> vocabulary: phrase-aware + app-specific
  -> existing Fast | Smart | Polish -> optional existing LLM corrector
  -> pre-insertion: run ownership + target identity + focus validation
      -> safe paste via existing inserter OR explicit 'target changed' review
  -> privacy-safe in-memory phase timings (no transcript/audio telemetry)
```

Invarianten (auch in Fehlersituationen):
1. **Nur aktiver `RunContext`** darf GUI-/Clipboard-/Insertion-Side-Effects auslösen. Auch Qt-Queued-Signale, ältere Streaming-Hypothesen, verspätete Netzwerkpakete und Batch-Fallbacks sind an die Run-ID gebunden.
2. **Keine Einfügung in einen anderen Fokus** als die eingefrorene Zielidentität. Bei Zielwechsel/ungültiger Identität: kein automatischer Paste; Text im App-Dialog zur kontrollierten Übernahme bereitstellen. Kein Fokus-Diebstahl.
3. **Partial != final.** Zwischenstände dienen ausschließlich der Vorschau, nicht der Einfügung, nicht dem Korrekturkontext und nicht dem Glossarspeicher.
4. **Exactly one final route:** pro Run entweder bestätigtes Streaming-Final oder ein kontrollierter Batch-Fallback; niemals doppelte Einfügungen.
5. **Keine heimliche Cloud-Weitergabe:** Profile dürfen ASR-/LLM-Cloudprovider nicht selbstständig aktivieren. Bestehende Nutzerentscheidung/Providergrenze gilt; zusätzliche Kontext-/Glossardaten müssen transparent und abschaltbar sein.
6. **Lokale Datenminimierung:** Keine persistierenden Audio-, Rohtext-, Window-Title-, Clipboard-, API-Key- oder Promptideinträge im Performance-Logging. Temporäre Audioartefakte wie bisher im run-eigenen Cleanup.
7. **Fail-safe:** Bei unklarer Korrektur konservativer Rohtext; bei unklarem Einfügeziel **nicht** automatisch einfügen; bei Streaming-Ausfall vorhandenen Batchpfad verwenden oder einen nachvollziehbaren Fehler melden.
8. Feature-Flags und Rückfall auf den bestehenden Batchmodus; alte `config.json`/`vocabulary.json` bleiben lesbar. Die UI-Strings aller acht bestehenden Sprachen müssen vollständig sein.

## 2. Konkreter PR-Schnitt

### PR vNext-01 — Observability + captured target

**Branch-Vorschlag:** `feat/vnext-01-timings-target-binding`  
**Voraussetzung:** aktueller `master`, bestehender Windows-CI-Gate. **Kein Modell-/ASR-Wechsel.**

**Implementierung**
- `app.py`: `RunContext` um `TargetSnapshot` und monotone `perf_counter_ns()`-Marken erweitern; Ziel **beim Hotkey-Start vor/bei `Recorder.start()`** auf dem UI-Thread erfassen: HWND, PID, Prozessname, ggf. Prozess-Erstellungszeit; für verlässliche UI-Automation-Felder nur nach Capability-Prüfung. Niemals Fenstertitel/URLs standardmäßig speichern.
- `text_inserter.py`: `capture_target()`, `validate_target(snapshot)` und explizite strukturierte Resultate für `insert_text(..., expected_target=...)` (z. B. `inserted`, `target_changed`, `clipboard_unavailable`, `dispatch_failed`). Direkt vor `SendInput` erneut prüfen. HWND-Reuse und Prozesswechsel durch zusätzliche PID-/Identity-Prüfung abfangen. Eventuelle Ungewissheit, ob die Zielapp wirklich konsumiert hat, **nicht** als bestätigte erfolgreiche Bearbeitung ausgeben. Non-text clipboard bleibt bekannte Grenze; keine zusätzlichen invasiven UI-Automation-Abhängigkeiten in PR 1.
- `app.py`: Korrekturkontext auf **eingefrorenen Prozess-/Profil-Schlüssel** beziehen, nicht den späteren Vordergrundprozess. Bei Zielwechsel keine Speicherausweitung auf andere Apps.
- `ui/dock.py`: bei `target_changed` deutlich „Zielfenster geändert – Text nicht automatisch eingefügt“ plus bewusstes Kopieren/Einfügen anbieten; kein automatisches Aktivieren/Zurückspringen.
- `metrics.py` (neu): in-memory `RunTimings` mit `run_id`, anonymen Backend-/Modus-IDs, `record_stop`, `audio_ready`, `asr_start/final`, `gate_start/end`, `llm_start/end`, `paste_dispatch/start/end`, `completed`. Korrektur-Skip als `null` markieren, nie als 0 ms. Fehler-/Cancel-Grund enum ohne Payload. Berechnung `record_stop_to_insert`/P50/P95 per reproduzierbarem lokalen Bench-Script; vorerst ausdrücklich **kein** Netztelemetrie- oder Nutzungsarchiv.
- `benchmarks/dictation_latency/` (neu): parsebares lokales JSON mit `schema_version=1`, Umgebung (OS/App/Backend/Modell/Cache-Status), Konfiguration/Commit-SHA und Per-Stage-Dauern; Roh-Audio und Diktattext ausschließlich im privaten Referenzkorpus außerhalb des Git-Repos.

**Tests / Nachweise**
- `tests/test_target_snapshot.py`: Hotkey-Zeitpunkt; Wechsel Word→Browser vor ASR-/LLM-Ende, auch bei identischem EXE und anderem HWND; ungültiges HWND; PID-Reuse; Ausfall der Windows-API → kein Autopaste.
- `tests/test_app_run_lifecycle.py` ergänzen: A wird abgebrochen, B startet, A kommt verspätet zurück → keine fremden Side-Effects, keine B-Statusänderung.
- `tests/test_text_inserter.py`: Clipboard belegt, Write-Failure, Fokuswechsel direkt vor Paste, keine falsche Erfolgsmeldung, keine alte Clipboard-Paste.
- `tests/test_metrics.py`: monotone Zeiten, fehlende optionalen Phasen, Null-Fälle, P50/P95 und datensparsames JSON-Schema.
- Windows-Smoke: Notepad, Word, Edge/Chrome und VS Code bei gleichem Hotkey; Test auch während der LLM-Korrektur und unmittelbar vor Paste.

**Abnahmekriterien (P0)**
- Keine falsche automatische Zieleinfügung in reproduzierbaren Zielwechsel-/stale-run-Tests (**0 Fälle in der vollständigen negativen Testmatrix**).
- Bei allen erfolgreichen Batches vollständige timings; p50/p95 von `record_stop→ASR final`, `ASR final→insert`, `record_stop→insert` getrennt nach Modus/Backend/Länge; fehlende Phasen korrekt dargestellt.
- Baseline aus **mindestens 100 warmen Durchläufen** je ausgewähltem Kern-Backend/Modus, mit je **mindestens 30** kurzen, mittleren und langen/technischen Fällen insgesamt und dokumentiertem Hardware-/Commit-Stand; Cold-Start separat, nicht mit Warm-P95 vermischen. Bei zu kleinem Korpus explizit „vorläufig“, keine SLO-Freigabe.
- Instrumentierung ohne persistente Rohinhalte oder neue ausgehende Verbindungen; zusätzliche Mess-CPU-/Latenzkosten reporten, Ziel **≤ 5 ms P50 Overhead** ggü. instrumentation-off auf gleichem Host, sofern stabil messbar.
- Ruff, pytest, Windows-PyInstaller und manueller Zielwechsel-Smoke PASS.

**Review-Hinweis:** P0-Zielfixierung ist wichtiger als ein gewonnenes Latenzmillisekündchen. Konservatives Blockieren ist hier erwünscht.

### PR vNext-02 — AppProfiles + phrase-aware vocabulary

**Branch-Vorschlag:** `feat/vnext-02-profiles-phrase-vocabulary`  
**Basis:** nach PR 01; bestehende Fast/Smart/Polish und Prompts beibehalten. **Kein neues gelerntes Routing.**

**Implementierung**
- `app_profiles.py` (neu) mit versionierter, expliziter `AppProfile`-Definition und deterministischer Regelauflösung **user-defined > built-in mapping > global defaults**. Profil am Aufnahmestart einfrieren (`RunContext.profile_id`), während der Verarbeitung nicht automatisch wechseln.
- Vorschlagsprofile per EXE: `OUTLOOK.EXE` → E-Mail, `WINWORD.EXE` → Fließtext, `chrome.exe`/`msedge.exe`/`firefox.exe` → generische Browser-Diktate (nicht als Gmail/ChatGPT-Site identifizieren), `Code.exe` → IDE, andere → Default. Keine Verwendung von Titel, URL, selektiertem Dokument, Ordner oder Tab als Standard-Identifikator. App-Profil nur Formatierungs-/Vokabular-/Korrekturmoduswahl; **niemals** automatische Cloud-Freigabe.
- `config.py` und `config.example.json`: optionales `app_profiles`/Mapping mit Migrations-/Validierungspfad, unbekannte IDs fail-safe Default, vollständige Deaktivierbarkeit. Bestehende Nutzerprompts nicht überschreiben.
- `vocabulary.py`: längste passende Mehrwort-Phrase vor kürzerer Phrase; Unicode-/Wortgrenzen und Fallunterscheidung, Zwischenräume/Interpunktion erhalten, deterministische Tie-Breaks; keine Substring-Ersetzung (z. B. `ANA` innerhalb eines anderen Wortes); vorhandenes `vocabulary.json`-Schema `corrections` samt einwortigen Einträgen kompatibel. Begriffe z. B. `p217 tau`→`p217-tau`, `anti PLA2R`→`Anti-PLA2R`, `immun fluoreszenz test`→`Immunfluoreszenztest`; dies sind **Beispiel-Daten, keine automatisch geladene Fachterminologie**.
- `llm_corrector.py`/Orchestrierung: Profil-Guidance und kuratierte Glossar-Teilmengen mit Scope aus frozen target/profile; nur Begriffe aus dem aktiven Profil plus globaler Basis, Bounded-Floor/Size wie bisher. Glossar ist *Hinweis*, kein Mandat zur Textinjektion.
- `ui/settings_dialog.py` und `ui/translations.py`: kleine Profilzuordnung (aktivieren/deaktivieren, Ansicht, Default zurücksetzen), ohne großflächige Settings-Neuschreibung. Alle acht UI-Sprachen.

**Tests**
- `tests/test_app_profiles.py`: Priorität, Unbekanntes, Default, Browser generisch, Konfigurationsmigration, Umschalten der aktiven App mitten in einem Run ohne Profil-/Providerwechsel.
- `tests/test_vocabulary.py`: überlappende Phrasen, Groß-/Kleinschreibung, Bindestriche, Abkürzungen, Leerraum/Absatz, Satzzeichen, Umlaute, JSON-Altformat, No-op und wiederholte Anwendung (Idempotenz), keine Teilwort-Ersetzung, Schutz von Zahlen/Einheiten/Negationen.
- `tests/test_llm_corrector.py`: korrekt begrenzte Profile-/Glossar-Kontexte, keine Aufnahme sensibler fremder App-Daten, keine ungewollte Cloud-Aktivierung.
- Windows-Integration: Word/Outlook/Browser/VS Code bei gleichem gesprochenem Text; beabsichtigte Format-Unterschiede nur gemäß Profil, kein semantischer Wort-/Zahlenverlust.

**Abnahmekriterien**
- Vorhandene Einwort-Einträge und gespeicherte Config/Pompts funktionieren unverändert, Migration automatisiert getestet.
- **100 %** der kuratierten deterministischen Mehrwort-Goldfälle mit korrekter **spangetreuer** Ersetzung; **0** Teilwort-Fehler und **0** unbeabsichtigte Änderungen an Zahlen, Einheiten, Negationen in Negativtestfällen.
- Kein Profile- oder Cloud-Routing-Wechsel während eines Runs; auch bei Profil-Mapping-Fehlern sicherer Default.
- Korrekturqualität auf manuell geprüftem deutschen Fach-Korpus mindestens nicht schlechter als bestehender Stand; sowohl Roh-ASR als auch bereinigtes Endresultat getrennt vergleichen. Bei Konflikt Rollback auf altes `VocabularyManager.apply` via Flag.
- CI + manuelle App-Profil-Smokes PASS.

### PR vNext-03 — optional realtime streaming / preview / batch fallback

**Branch-Vorschlag:** `feat/vnext-03-realtime-preview`  
**Basis:** nach PR 01, parallel zu PR 02 möglich; **Feature standardmäßig aus**.

**Implementierung**
- `provider_registry.py`: am vorhandenen ProviderDefinition-Vertrag optionale `supports_streaming`, `supports_partial_results`, `realtime_transport`, `supports_language_hint`, `supports_prompt`, `engine_family` ergänzen; `false/none` als rückwärtskompatibler Default. Keine falschen Realtime-Fähigkeiten für bestehende Batch-Endpunkte behaupten.
- `transcription_stream.py` (neu) mit typisierten `PartialHypothesis(run_id, sequence, text, is_final)`, dedizierter Transportadapter-Schnittstelle und `BatchTranscriptionAdapter` als bestehende Referenz. Für den ersten Pilot **genau einen** verifizierten, streamingfähigen lokalen WebSocket-Backendadapter implementieren (OpenASR oder Speaches nach reproduziertem Contract-Test; keinen konkreten Server wählen, bevor dessen aktueller Realtime-Handshake geprüft ist).
- `recorder.py`: PCM-Frames aus `sounddevice`-Callback in eine **begrenzte, nicht blockierende Queue** kopieren; keine Netzwerkarbeit im Audio-Callback; Overflow-Bedingung messen und dem User melden; finale WAV nur bei erforderlichem Batch-Fallback oder dokumentierter kompatibler vorhandener Verarbeitung.
- `app.py`: pro Run eindeutige Streaming-Session; Empfangs-Reihenfolge über `sequence`/Run-ID schützen; bei `stop` Finalisierung initiieren und abwarten (gebundenes Deadline-Budget); fehlendes/ungültiges Final → genau ein optionaler Batch-Fallback mit derselben Run-ID; niemals erst Stream-Final einfügen und danach Batch-Ergebnis.
- `ui/dock.py`: vorläufiges Transkript als deutlich markierte Live-Vorschau, finales Transkript ohne Doppelungen; nur finaler Text darf in Smart/Polish und den TextInserter. Qt-Hauptthread über vorhandenen signalisierenden GUI-Gate.
- Streaming-Konfig `streaming_enabled=false`, Timeout und bounded queue. Keine neuen festen Endpunkte in UI/Client, Provider-Capabilities bleiben zentrale Autorität.

**Tests**
- `tests/test_transcription_stream.py`: out-of-order/duplicate/missing partials, kurzer Final, Final vor Timeout, EOF, reconnect/timeout, bad-frame, Queue-Overflow, mehrfaches Stop, stale Run A während Run B, race StreamFinal vs. BatchFinal.
- `tests/test_app_run_lifecycle.py`: `0` doppelte Insertions, keine GUI-Updates von A nach B.
- `tests/test_provider_registry.py`, `tests/test_whisper_client.py`: Batchverhalten unverändert, Capabilities korrekt; Streaming nicht für ungetestete Provider aktiv.
- End-to-End mit lokalem Fake-WebSocket-Server (deterministisch) plus einem **manuell geprüften echten** lokalen Server auf Windows/LAN; keine Cloud-Kosten im CI.

**Abnahmekriterien**
- Run-/Partial-Sicherheit und **Exactly-once Final**: **0** doppelte Einfügungen in vollständiger deterministischer Error-/Race-Matrix.
- Live-Preview erscheint während gesprochener Sätze bei einem realen fähigen Backend; `first_partial`, `final`, `release_to_insert` jeweils P50/P95 erfasst; **erste Zielhypothese** für einen warmen LAN-Stream: P95 `speech_start→first_partial` ≤ 900 ms, erst nach PR-01-Baseline und Backendvalidierung als harte SLO bestätigen oder begründet ersetzen.
- Finale Textqualität auf dem Goldkorpus mindestens nicht schlechter als vorhandener Batchpfad; als anfängliche Evaluationsgrenze **höchstens +0,5 Prozentpunkte absolute WER**, zusätzlich keine Regression kritischer Zahlen/Einheiten/Negationen. Latenz `release_to_insert` P95 soll im Warmbetrieb nicht > 10 % über der Batch-Baseline liegen; bei Nichterfüllung Feature experimentell belassen.
- Aktiviert nur für geprüfte Provider, ansonsten automatischer unveränderter Batchmodus; bei kaputtem Stream sichtbar und nachvollziehbar Fallback (höchstens ein Retry/Batch-Routing), bei abgebrochenem Run **kein** Fallback mit Side-Effects.
- Cloud-/Mikrofonrechte unverändert, kein heimlicher Sendepfad; bestehende CI grün.

### PR vNext-04 — Windows E2E + Security/Privacy Release Gate

**Branch-Vorschlag:** `test/vnext-04-e2e-acceptance`  
**Basis:** PR 01–03 enthalten und manuell smoke-tested; keine zusätzlichen Features in diesen PR.

**Implementierung**
- `tests/e2e/` (neue separate Windows-Suite) plus markierte manuelle Matrix und reproduzierbare Test-Fakes für GUI, Eingabe, ASR/LLM, verlorene Verbindungen, Clipboard und Fokuswechsel. Automatisierte Tests bevorzugt mit dedizierten, disposable Zieltextfeldern; echte Word-/Outlook-/Browser-/VS-Code-Fälle sind **manueller Abnahmebeleg**, nicht unbedingte öffentliche CI-Abhängigkeit.
- `benchmarks/dictation_latency/report.py`: Ergebnisse aus PR 01–03 als versionierten Report `JSON + Markdown` mit Vergleich `batch vs streaming`, `Fast/Smart/Polish`, profilbezogenen Einfügungen, Korpus-Längen und Hardware-/Backendhashes. Keine personenbezogenen Originalaufnahmen committen.
- `docs/SMART_DICTATION_VNEXT_ACCEPTANCE.md`: freizugebende Smokeprotokolle und explizite Risiken/known limitations.
- `.github/workflows/windows-ci.yml`: bestehende Jobs um vollautomatische Fake-ASR-/Target-/Profile-/Streamingtests ergänzen, ohne reales Mikrofon, externe Accounts oder kostenpflichtige Provider vorauszusetzen.

**E2E-Matrix (bewusst **risikobasiert/pairwise**, nicht riesiges Vollkreuzprodukt)**

| Achse | Pflichtfälle |
| --- | --- |
| Ziel-Apps | Notepad, Word, Outlook, Edge oder Chrome, VS Code; Browser-Textfeld vs. andere Tabs ausdrücklich getrennt prüfen |
| Modi | Fast, Smart, Polish, Streaming aus/an (nur wo unterstützt) |
| Deutsch-/Fachsprache | kurze Sätze, 30–120-s-Diktat, gemischte DE/EN-Termini, Acronyme, Zahlen, Einheiten, Datumsangaben, Negationen, gesprochene Interpunktion |
| Audio | ruhig, Bürogeräusch, Sprechpausen, No-Speech/Very-Short, Mikrofonabbruch |
| Störungen | App-/Tab-/Fensterwechsel vor Release/Insert; Minimierung; Fokusverlust; Clipboard gesperrt/anderer Inhalt; Abbruch A→Start B; verspätetes ASR/LLM/Partial; HTTP-/WebSocket-Fehler; Stream ohne Final |
| Sensible Inhalte | keine Persistierung von Raw-Audio/Transkript in Logs; keine Telemetrie/Egress; Cloud nur nach bewusster Nutzerkonfiguration; Kontext-/Glossargrenzen; Transcript und Glossar als **untrusted data**; berechtigungsgebundener Zugriff |
| Compatibility | bestehende `config.json`, `vocabulary.json`, 8 UI-Sprachen, PyInstaller EXE, Windows 10/11 |

**Release-Gates (Go / No-Go):**
1. **Sicherheit:** 0 ungewollte Einfügungen, 0 doppelte Einfügungen, 0 unberechtigte Cloud-Transfers oder Logging sensibler Nutzdaten in der definierten automatisierten Negativmatrix und im dokumentierten Windows-Smoke. Jede bestätigte Verletzung blockiert Merge/Release.
2. **Korrektheit:** 0 kritische Veränderung von Negation, Zahlen oder Einheiten in human-reviewed critical-cases; keine unbeabsichtigte semantische Umschreibung im normalen Dictation-Pfad. WER/CER, Fachtermgenauigkeit und Auslassungen **für ASR roh und final korrigiert getrennt** reporten.
3. **Latenz:** P50/P95 und Konfidenz-/Stichprobengrenzen dokumentiert für alle Phasen, Modi und aktivierten Backends; vNext-Batch darf nicht signifikant schlechter als PR-01-Baseline sein (vorab festgelegte praktische Toleranz: max. +10 % beim Warm-P95, mit gleichem Korpus/Hardware); Realtime-Preview-Ziel nur dann Freigabe als „schneller“, wenn messbar. **Keine ungemessenen Verbesserungsbehauptungen.**
4. **Reliability:** deterministische Streaming-/Cancel-/Targetwechseltests PASS; keine Regression von `RunContext`- und Clipboard-Safety; nach Netzwerkfehler genau ein Batch-Fallback oder klarer Fehler, niemals Doppelinsert.
5. **Compatibility:** `uv sync --frozen`, `uv run ruff check .`, `uv run pytest tests/ -q`, `uv run pyinstaller FlüsterFee.spec` + existierende EXE, alle acht Übersetzungen und dokumentierte manuelle Windows-Matrix PASS.
6. **Privacy:** keine Aufnahmehistorie/Meeting-Feature als Nebenprodukt; keine Telemetrie; optionale Cloud-Nutzung nur im bestehenden Einwilligungs-/Provider-Kontext, verwendete Prompt-Kontexte klar dokumentiert.
7. **Rollback:** per Settings/Flag jederzeit zurück auf Batch + globales Profil + bisherige Vocabulary-Engine, ohne Daten-/Konfigverlust.

## 3. Reihenfolge / Abhängigkeiten

```text
documentation/planning PR (this document; no runtime code)
          |
          v
vNext-01 timings + target snapshot  [P0]
         / \
        v   v
vNext-02   vNext-03
profiles    streaming
        \   /
         v v
vNext-04 E2E + release evidence [Go/No-Go]
```

**PR-Größenregel:** Wenn vNext-01 zu breit wird, in `01a timings` und `01b target binding` teilen, **ohne** die Integrationsverantwortung für `RunContext` zu duplizieren. vNext-02 darf bei Bedarf in unabhängige `02a vocabulary` und `02b app profiles` zerfallen. PR 03 behält genau **einen** funktionsfähigen Backendadapter als Scope, weitere Anbieter folgen einzeln nach Contract- und Benchmarkbeweis. PR 04 nimmt keine weiteren Features an.

## 4. Review- und Prüfprotokoll je PR

Jeder PR liefert:
- Link zu diesem Plan und exakt betroffenen Abschnitt(en) von `OPTIMIZATION.md`;
- Before/After-Evidenz für den abgegrenzten Nutzen; bei fehlender Messbasis ausdrücklich `not measured`;
- Change-Scope, geänderte Config-Schlüssel, Daten-/Netzwerkgrenzen, Rollback;
- reproduzierbare `pytest`-/Ruff-/PyInstaller-CI-Resultate;
- neue und aktualisierte negative/fail-closed Tests;
- manuelle Windows-Smokes mit Windows-Version, App-Versionen, Backend/Model, PC/GPU, Zeitstempel, Testreferenz;
- für ASR-/Streaming-Performance: P50/P95 aus demselben privaten Korpus, getrennt nach warm/cold und Client/Server-Phasen.

**Ergänzende Risiken und Entscheidungen**
- Die lokale `InsertText`-Pipeline kann keine atomare Transaktion mit fremden Windows-Textcontrols garantieren. Der Fokus wird deshalb **unmittelbar vor der Aktion** neu validiert; bei Unklarheit kein Paste. Ein vollständiger UIA-Edit-Transaction-Ansatz ist **nicht** Bestandteil dieses vNext.
- Ein Profil anhand `chrome.exe` darf **nicht** suggerieren, eine bestimmte Website/ein Dokument zu kennen. Zielgebundenes Verhalten bleibt pro-Fenster und mit expliziten Grenzen.
- Profile/Glossare dürfen niemals fachliche Begriffe oder Aussagen allein aufgrund des Kontextes hinzufügen.
- Streaming-Adaptersicherheit benötigt aktuelle Backend-API-Konformität; kein reines README-Claim reicht.
- Private Testaufnahmen, betriebliche Fachdaten und Tokens bleiben außerhalb des öffentlichen Repos.
- **Kein** Mac-/FluidVoice-Codeimport ohne gesonderte GPL-/Abhängigkeitsanalyse. Designmuster adaptieren, nicht die native App portieren.

## 5. Abnahmeevidenz-Template (auszufüllen, keine erfundenen Werte)

```yaml
plan: smart-dictation-vnext
app_commit: "<sha>"
date: "<YYYY-MM-DD>"
windows: "<edition/build>"
target_apps: ["Notepad", "Word", "Outlook", "Edge/Chrome", "VS Code"]
model_and_backend: "<pinned backend / model digest>"
test_corpus_ref: "<private corpus ID/hash only>"
run_counts: {warm: null, cold: null, critical: null}
latency_ms:
  asr_final_p50: null
  asr_final_p95: null
  gate_p50: null
  gate_p95: null
  llm_p50: null
  llm_p95: null
  release_to_insert_p50: null
  release_to_insert_p95: null
  first_partial_p95: null
quality:
  raw_wer: null
  final_wer: null
  critical_number_unit_negation_errors: null
  wrong_target_inserts: null
  duplicate_inserts: null
privacy:
  external_egress_review: not_run
  sensitive_log_audit: not_run
ci:
  ruff: not_run
  pytest: not_run
  pyinstaller: not_run
manual_windows_smoke: not_run
decision: pending
```

## 6. Knowledge and lifecycle boundary

Feature-/Runtimeänderungen gehören ausschließlich in `GithubLarsKomo/faster-wisprflow`. `GithubLarsKomo/coding-brain` übernimmt **erst nach verifizierter Ausführung** die kleinste generalisierbare Engineering-Erkenntnis mit Quellenrevision und Negativbedingungen, falls tatsächlich neu. `GithubLarsKomo/super-second-brain` bleibt nur Routing/Federation. Aktuell: **plan-only / no promotion of untested claims**.
