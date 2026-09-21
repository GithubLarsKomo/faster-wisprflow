# FlüsterFee Hardening Specification

Status: implemented on hardening branch; pending final merge gate  
Branch: `fix/run-isolation-provider-hardening`  
Repository: `GithubLarsKomo/faster-wisprflow`  
Target branch: `master`  
Date: 2026-09-19

## 1. Purpose

This specification defines the next hardening increment for FlüsterFee.

The goal is not a rewrite. The existing component boundaries remain valid:

```text
Hotkey / middle mouse
        ↓
Recorder
        ↓
WhisperClient
        ↓
VocabularyManager
        ↓
LLMCorrector
        ↓
TextInserter
```

The work focuses on correctness under cancellation/concurrency, provider-contract consistency, insertion safety, bounded LLM behavior, reproducible builds, CI, and configuration/documentation cleanup.

## 2. Goals

The increment is complete when:

1. A cancelled or stale transcription/correction run can never insert text or change the state of a newer run.
2. Every recording uses its own temporary audio artifact.
3. Provider endpoint construction and capabilities are centralized and tested.
4. The Groq chat-completions endpoint is corrected.
5. Cursor-context probing cannot move the user's caret accidentally.
6. Truncated or structurally suspicious LLM corrections fall back safely to the raw transcript.
7. The project has one authoritative dependency/build path based on `pyproject.toml` + `uv.lock`.
8. Windows CI verifies lint, tests, and a PyInstaller smoke build.
9. Configuration, README, test documentation, and visible UI strings match actual runtime behavior.

## 3. Non-goals

This increment does not:

- redesign the visual language of the dock;
- replace PySide6;
- replace the current transcription or correction backends;
- introduce a new persistence/database layer;
- implement background job persistence;
- perform a broad rewrite of `settings_dialog.py`;
- introduce telemetry;
- add new cloud providers solely for feature expansion.

UI modularization may follow after correctness and provider contracts are stable.

---

# 4. P0 — Run isolation and cancellation safety

## 4.1 Problem

The current lifecycle uses shared flags such as `is_busy` and `is_recording`.

A cancelled run can remain blocked inside a synchronous HTTP request. If a new run begins before the old request returns, the old worker may observe the new run's shared state and incorrectly continue. A stale worker may also reset global state in its `finally` block.

This can cause:

- insertion of stale text;
- incorrect dock state transitions;
- a newer run being marked idle/cancelled by an older worker;
- race conditions around shared temporary audio files.

## 4.2 Required design

Introduce a run-scoped execution object.

Suggested model:

```python
@dataclass
class RunContext:
    id: int
    cancel_event: threading.Event
    audio_path: Path | None = None
    started_at: float = 0.0
```

`App` owns:

```python
self._run_counter: int
self._active_run: RunContext | None
self._run_lock: threading.Lock
```

A UUID is also acceptable, but a monotonically increasing integer is sufficient and easier to test.

## 4.3 Invariants

The following invariants are mandatory:

- Only the current active run may update the dock.
- Only the current active run may insert text.
- Only the current active run may clear busy/processing state.
- Cancelling a run sets its `cancel_event`.
- Starting a new run invalidates every older run.
- A worker returning from a blocking HTTP request must revalidate its run identity before every side effect.
- Cleanup of a stale run may delete only artifacts owned by that run.

A helper should centralize the identity check, for example:

```python
def _is_current_run(self, run: RunContext) -> bool:
    return (
        self._active_run is run
        and not run.cancel_event.is_set()
    )
```

Do not use `is_busy` as the sole validity test.

## 4.4 Cancellation behavior

Cancellation must be cooperative.

The current synchronous `requests` calls do not need to be forcibly interrupted in this increment. It is acceptable for an HTTP request to finish in its worker thread after cancellation, provided the stale result is discarded.

Required user-facing behavior:

- dock returns to idle immediately after cancellation;
- a new recording can start immediately;
- stale responses are ignored;
- no stale toast/error may override the state of the new run.

## 4.5 Tests

Add orchestration-focused tests for at least:

1. cancel run A while Whisper request is blocked;
2. start run B;
3. allow A to return;
4. assert A does not call `insert_text`;
5. assert A does not clear B's active state;
6. allow B to return;
7. assert only B is inserted.

Also cover:

- stale LLM response after a new run starts;
- stale error notification;
- cancel during recording;
- cancel during transcription;
- cancel during correction.

---

# 5. P0 — Run-scoped temporary audio files

## 5.1 Problem

`Recorder.stop()` currently derives one fixed path from `audio_filename`.

Overlapping workers can therefore read, overwrite, or delete the same temporary WAV.

## 5.2 Required change

Each recording must receive a unique path.

Preferred options:

- `tempfile.NamedTemporaryFile(delete=False, suffix=".wav")`;
- `tempfile.mkstemp(...)`;
- a run-ID-derived filename in the OS temp directory.

The generated path becomes part of the current `RunContext`.

## 5.3 Compatibility

`audio_filename` may be retained temporarily for backward compatibility, but it must no longer define a shared runtime path.

If retained, document it as deprecated.

## 5.4 Tests

Verify:

- two runs receive different paths;
- one run cannot delete another run's WAV;
- cleanup happens after success, failure, and cancellation;
- no WAV remains after normal completion.

---

# 6. P0/P1 — Provider registry and endpoint correctness

## 6.1 Problem

Provider-specific behavior is duplicated across:

- `whisper_client.py`;
- `llm_corrector.py`;
- `ui/settings_dialog.py`;
- configuration defaults;
- README;
- tests.

This has already produced provider drift.

A concrete defect is the Groq LLM runtime endpoint, which currently uses:

```text
https://api.groq.com/v1/chat/completions
```

It must use the OpenAI-compatible Groq path:

```text
https://api.groq.com/openai/v1/chat/completions
```

Provider contracts must be checked against current official documentation when implemented.

## 6.2 Required design

Introduce a small provider definition layer rather than expanding scattered `if provider == ...` branches.

Suggested shape:

```python
@dataclass(frozen=True)
class ProviderDefinition:
    id: str
    display_name: str
    api_style: str
    requires_token: bool
    supports_model_listing: bool
    chat_url: str | None = None
    transcription_url: str | None = None
    models_url: str | None = None
```

A more explicit strategy/adapter class hierarchy is acceptable if it stays small.

The provider layer should become authoritative for:

- provider IDs;
- display names;
- cloud/local classification;
- auth style;
- chat endpoint;
- transcription endpoint;
- model-list endpoint;
- endpoint construction for local/OpenAI-compatible servers;
- supported request options.

## 6.3 Provider IDs

Use stable normalized IDs internally. Suggested values:

```text
local
ollama
lm_studio
groq
openrouter
openai
anthropic
azure_openai
```

Display labels remain independent.

Migration must accept existing persisted labels such as `Openrouter`, `Ollama`, and `Groq`.

## 6.4 Transcription-specific parameters

Provider-specific fields must be sent only when supported.

Do not send both `prompt` and `initial_prompt` to every provider by default.

The adapter must decide which request fields are legal.

## 6.5 Tests

Add provider-contract tests that assert exact URLs and key payload differences for every supported provider.

Do not let a unit test simply freeze an incorrect endpoint.

---

# 7. P1 — Cursor-context insertion correctness

## 7.1 Problem

`_peek_previous_non_space_char()` selects several characters left of the caret and then sends `Right` repeatedly to restore position.

In ordinary Windows edit controls, the first right-arrow often collapses the selection to its right edge. Further right-arrow presses can then move the caret beyond its original position.

## 7.2 Required behavior

Cursor-context inspection must be observational: it must not change the final caret position or text selection.

## 7.3 Implementation options

Preferred order:

1. keep the selection/copy approach but restore the caret with one deterministic collapse action;
2. use an accessibility/text API if a simple Win32 solution is reliable across target applications;
3. disable context probing for known-incompatible targets rather than risking cursor movement.

The implementation must preserve clipboard semantics.

## 7.4 Tests

Extend unit tests for caret restoration logic and add at least a manual smoke matrix for:

- Notepad;
- Word;
- browser textarea/input;
- VS Code;
- terminal-like text control if supported.

---

# 8. P1 — LLM correction integrity and truncation guard

## 8.1 Problem

The correction response is currently accepted mainly based on non-emptiness and a generous maximum-length heuristic.

A response that is truncated because of `max_tokens` may still be inserted.

## 8.2 Required behavior

The correction stage is best-effort and must never cause loss of dictated content.

If correction integrity is uncertain, insert the vocabulary-adjusted raw transcript.

## 8.3 Required validation

For OpenAI-compatible providers inspect at least:

- `finish_reason`;
- missing/null content;
- obvious refusal/tool-only/reasoning-only responses;
- suspiciously short output;
- suspiciously long output.

At minimum:

- `finish_reason == "length"` => raw-text fallback;
- empty/null content => raw-text fallback;
- significant content loss => raw-text fallback.

## 8.4 Output budget

Replace the fixed 220-token assumption with either:

- an input-length-dependent output budget bounded by a configurable maximum; or
- a sufficiently large default plus explicit truncation handling.

Correctness takes priority over shaving a few tokens.

## 8.5 Observability

A fallback may show a short non-blocking notice, but the user must still receive the raw transcript.

---

# 9. P1 — Dependency and build source of truth

## 9.1 Problem

The repository currently has both:

- `pyproject.toml` / `uv.lock`;
- `requirements.txt`;
- a `build.bat` that installs through `pip` but invokes PyInstaller from `.venv`.

These sources can drift.

## 9.2 Required change

Make:

```text
pyproject.toml + uv.lock
```

the sole dependency authority.

Preferred developer flow:

```powershell
uv sync --frozen
uv run pytest -q
uv run pyinstaller FlüsterFee.spec
```

Update `build.bat` accordingly.

`requirements.txt` should either:

- be removed; or
- be generated from the canonical dependency set and clearly marked generated.

It must not remain an independent handwritten authority.

## 9.3 Dependency cleanup

Review direct dependencies.

Candidates for removal if no runtime/build usage remains include legacy libraries left behind after the Win32 input rewrite.

Removal requires code-search and a successful Windows build.

---

# 10. P1 — Windows CI

## 10.1 Required workflow

Add a GitHub Actions workflow using a Windows runner.

Minimum gate:

```text
checkout
→ install uv
→ uv sync --frozen
→ ruff check
→ pytest
→ PyInstaller smoke build
```

The smoke build must verify that `dist/FlüsterFee.exe` exists.

Optional later step:

- launch with a non-GUI diagnostic flag such as `--ssl-diagnose`.

## 10.2 Branch protection

Branch-protection changes are outside this spec unless explicitly requested, but the CI workflow must be suitable for becoming a required status check.

---

# 11. P2 — Configuration hygiene

## 11.1 Required change

Introduce:

```text
config.example.json
```

containing safe portable defaults.

The actual user/runtime `config.json` should be excluded from source control unless there is a deliberate reason to keep it canonical.

Add `.env` to `.gitignore` and remove the tracked empty file.

## 11.2 Defaults

Eliminate drift between:

- `DEFAULT_CONFIG`;
- example configuration;
- README.

Private/internal network addresses must not become general application defaults in the example configuration.

## 11.3 Legacy options

Review:

- `auto_elevate`;
- `start_with_windows`;
- `audio_filename`.

If functionality is intentionally inactive, either remove the visible option or mark it deprecated. Do not present a no-op switch as an operational setting.

---

# 12. P2 — Documentation and UI-string consistency

## 12.1 README

Update the provider and configuration tables to match the actual supported runtime.

Remove stale references to removed implementations unless they are intentionally restored.

## 12.2 Test documentation

Generate or manually refresh `tests/README.md` after the test suite changes.

Do not treat test-count documentation as an authority over the tests themselves.

## 12.3 i18n

The repository rule remains:

> Every user-visible string is available in all supported UI languages.

Fix remaining hard-coded user-visible strings, including tray actions and the single-instance message.

Supported UI languages remain:

```text
de en fr es zh pt pl it
```

---

# 13. P2 — Settings UI modularization

This is intentionally deferred until the correctness work is stable.

After the previous phases, consider splitting `ui/settings_dialog.py` into focused panels:

```text
ui/settings/
  general.py
  audio.py
  transcription.py
  correction.py
  vocabulary.py
  diagnostics.py
```

The split should reuse the provider registry and must not duplicate provider definitions.

---

# 14. Test strategy

## 14.1 Unit tests

Required new unit coverage:

- run identity;
- cancellation/stale-worker behavior;
- unique audio paths;
- provider URL contracts;
- provider-specific payloads;
- LLM truncation fallback;
- cursor-context restoration.

## 14.2 Integration-style tests

Use mocks/fakes to drive complete orchestration paths without real audio or internet:

```text
record → transcribe → vocabulary → correct → insert
```

Cover success and every fallback point.

## 14.3 Manual Windows smoke tests

Before merge:

- hotkey start/stop;
- middle-mouse start/stop;
- cancel while recording;
- cancel while transcription is deliberately delayed;
- cancel while LLM correction is deliberately delayed;
- immediately start another run after cancellation;
- Word insertion;
- browser insertion;
- clipboard restoration;
- local transcription endpoint;
- at least one cloud transcription provider if credentials are available;
- local LLM;
- at least one cloud LLM if credentials are available;
- packaged EXE launch;
- settings persistence;
- keyring token retrieval.

---

# 15. Acceptance criteria

The branch is merge-ready only when all of the following are true:

- no stale run can paste text;
- no stale run can change the current run's dock state;
- every run owns a unique temporary audio path;
- Groq chat URL is correct;
- provider behavior comes from one authoritative registry/adapter layer;
- LLM truncation falls back to raw text;
- cursor probing does not shift the caret in the defined smoke matrix;
- `uv sync --frozen` succeeds on Windows;
- tests pass;
- Ruff passes;
- PyInstaller produces `FlüsterFee.exe`;
- README and example configuration match runtime behavior;
- all visible strings satisfy the existing 8-language rule;
- no secrets or private API tokens are committed.

## 16. Delivery principle

Correctness and non-loss of dictated text take precedence over aggressive correction, lowest possible latency, or adding new providers.

When uncertain, preserve the raw transcript and keep the UI usable.
