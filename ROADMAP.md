# FlüsterFee Hardening Roadmap

Branch: `fix/run-isolation-provider-hardening`  
Specification: [SPEC.md](SPEC.md)  
Post-merge optimization: [OPTIMIZATION.md](OPTIMIZATION.md)  
Date: 2026-09-19

## Implementation status

- Phases 0–8 are implemented on `fix/run-isolation-provider-hardening`.
- Windows CI is the authoritative automated merge gate for Ruff, pytest and the PyInstaller smoke build.
- Phase 9 (settings-dialog modularization) remains intentionally deferred; it is not required for this hardening merge.
- A final manual Windows smoke matrix on real desktop applications remains required before merge.
- Latency/UI/cost optimization and the OpenASR/Speaches/alternative-ASR benchmark are explicitly post-merge work and must not expand the current correctness merge gate.

## Delivery strategy

Work in small verifiable increments. Do not mix broad UI refactoring into the correctness fixes.

Each phase should leave the branch runnable and testable.

---

## Phase 0 — Baseline and safety net

### Work

- confirm current `master` baseline;
- run the existing test suite on Windows;
- record the exact baseline result;
- add targeted orchestration test scaffolding for `App` without requiring real audio/network;
- add a deterministic fake/blocking Whisper client and LLM corrector for race tests.

### Exit gate

- existing behavior is reproducibly testable;
- new race-condition tests can express stale-run scenarios;
- no production behavior changed yet.

---

## Phase 1 — Run isolation

Priority: **P0**

### Work

- add `RunContext`;
- add monotonically increasing run IDs;
- add per-run `cancel_event`;
- make side effects conditional on active run identity;
- ensure stale workers cannot clear newer state;
- ensure stale workers cannot emit UI state changes;
- retain immediate user-visible cancellation.

### Regression tests

- A cancelled run returning after B starts cannot paste;
- A cannot clear B's busy state;
- A cannot overwrite B's dock state;
- B completes normally;
- cancellation during both transcription and correction is covered.

### Exit gate

All stale-run regression tests pass.

---

## Phase 2 — Unique recording artifacts

Priority: **P0**

### Work

- create a unique temp WAV for each run;
- attach it to the run context;
- remove dependence on one shared runtime filename;
- ensure ownership-aware cleanup.

### Exit gate

Concurrent/stale runs cannot read, overwrite, or delete one another's audio.

---

## Phase 3 — Provider contract correction

Priority: **P0/P1**

### Work

- correct Groq chat-completions URL;
- introduce provider registry/adapter definitions;
- normalize provider IDs;
- migrate existing persisted labels;
- move chat/transcription/models URLs into the provider layer;
- encode provider-specific auth and request capabilities;
- stop sending unsupported transcription parameters indiscriminately.

### Tests

Exact endpoint and payload tests for every provider.

### Exit gate

No provider endpoint is duplicated as an independent literal across UI/runtime modules except where technically unavoidable.

---

## Phase 4 — LLM non-loss guard

Priority: **P1**

### Work

- capture and inspect `finish_reason`;
- detect truncation;
- detect suspicious content loss;
- use dynamic or safer output budget;
- fall back to raw vocabulary-adjusted transcript on uncertainty;
- retain non-blocking fallback notification.

### Exit gate

A truncated correction can never replace the complete raw transcript.

---

## Phase 5 — Cursor and clipboard correctness

Priority: **P1/P2**

### Work

- fix cursor-context caret restoration;
- expand automated tests;
- manually verify Notepad, Word, browser, VS Code;
- document limits of text-only clipboard restoration;
- decide whether to implement full clipboard preservation or rename/reframe the existing option.

### Exit gate

Context probing does not move the caret in the agreed smoke matrix.

---

## Phase 6 — Build consolidation

Priority: **P1**

### Work

- make `pyproject.toml` + `uv.lock` canonical;
- update `build.bat` to use `uv sync --frozen` and `uv run pyinstaller`;
- remove or generate `requirements.txt`;
- remove unused legacy dependencies only after successful build verification.

### Exit gate

A clean Windows checkout can build the EXE using only the documented uv workflow.

---

## Phase 7 — Windows CI

Priority: **P1**

### Work

Create GitHub Actions workflow:

```text
Windows
→ uv sync --frozen
→ ruff check
→ pytest
→ pyinstaller
→ assert dist/FlüsterFee.exe
```

### Exit gate

CI is green on the branch and produces a successful build smoke result.

---

## Phase 8 — Config, documentation, i18n cleanup

Priority: **P2**

### Work

- add `config.example.json`;
- ignore runtime `.env`;
- decide treatment of runtime `config.json`;
- remove private/local environment defaults from portable examples;
- reconcile `DEFAULT_CONFIG`, README, UI, and tests;
- remove or deprecate no-op options;
- update `tests/README.md`;
- remove stale NeMo/internal-provider documentation unless intentionally restored;
- translate remaining hard-coded visible strings.

### Exit gate

Documentation and configuration describe the code that actually ships.

---

## Phase 9 — Optional settings refactor

Priority: **P2, after correctness**

### Work

Split the large settings dialog into focused modules only after the provider registry is stable.

### Exit gate

No provider/config logic is duplicated by the refactor and all existing behavior remains covered.

---

# Merge gate

Before merging to `master`:

1. Windows CI green.
2. Full pytest suite green.
3. Ruff green.
4. PyInstaller EXE built.
5. Manual cancellation race smoke test passed.
6. Manual insertion smoke matrix passed.
7. Provider URLs checked against current official documentation.
8. README and example config refreshed.
9. No credentials, tokens, or environment-specific secrets committed.
10. Final diff reviewed specifically for new shared mutable state.

# Suggested commit sequence

```text
test: add run lifecycle race harness
fix: isolate dictation runs with run context
fix: use unique temporary audio files
refactor: centralize provider contracts
fix: correct provider endpoints and request capabilities
fix: reject truncated llm corrections
fix: preserve caret during cursor context probe
build: make uv lockfile the dependency source of truth
ci: add windows verification workflow
docs: align configuration providers tests and i18n
```

This sequence is intentionally reversible and keeps correctness changes separate from cleanup.
