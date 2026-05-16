# Test Suite

166 tests across 9 modules. Run with:

```bash
uv run pytest tests/
```

---

## Structure

```
tests/
├── conftest.py                  # Shared fixtures and helpers
├── test_config.py               # config.py
├── test_correction_tracker.py   # correction_tracker.py
├── test_hotkey.py               # hotkey.py
├── test_llm_corrector.py        # llm_corrector.py
├── test_recorder.py             # recorder.py
├── test_text_inserter.py        # text_inserter.py
├── test_translations.py         # ui/translations.py
├── test_vocabulary.py           # vocabulary.py
└── test_whisper_client.py       # whisper_client.py
```

---

## Shared infrastructure (`conftest.py`)

| Symbol | Type | Description |
|---|---|---|
| `tmp_config_path` | fixture | Redirects `config.CONFIG_PATH` to a temp file so tests never touch `config.json` on disk |
| `tmp_vocab_path` | fixture | Redirects `vocabulary.VOCAB_PATH` (and `config.VOCAB_PATH`) to a temp file |
| `tmp_paths` | fixture | Redirects both config and vocabulary paths at once |
| `make_stub_config(**overrides)` | helper | Returns a `SimpleNamespace`-like object with all `Config` attributes set to sensible defaults; accepts keyword overrides; no disk I/O |

---

## `test_config.py` — 19 tests

Tests `_build_base_url`, `load_config`, `save_config`, the `Config` class, and the `auto_elevate_if_needed` no-op.

| Class / test | What it checks |
|---|---|
| `TestBuildBaseUrl` (8) | Port appended correctly; port `0`/`None`/`""` omitted; numeric string ports; trailing slash stripped |
| `TestLoadConfig` (3) | Creates file when missing; merges partial JSON with defaults; preserves unknown keys |
| `TestSaveConfig` (2) | Writes valid JSON; preserves non-ASCII/Unicode characters |
| `TestConfigClass` (5) | Reads values on init; falls back to defaults; `hotkey_keys` is a list; `restore_clipboard` is a bool; `reload()` updates attributes |
| `test_auto_elevate_is_noop` (1) | `auto_elevate_if_needed()` returns without doing anything |

---

## `test_correction_tracker.py` — 18 tests

Tests the pure `_word_diff` static method, the `CorrectionTracker` start/stop lifecycle, deadline-based polling, and the low-level Win32 `SendInput` helpers.

| Class | What it checks |
|---|---|
| `TestWordDiff` (9) | Simple word substitutions detected; identical text yields no pairs; insertions and deletions (non-equal-length diffs) ignored; punctuation stripped before comparison; case-only changes filtered; multiple simultaneous substitutions with surrounding context |
| `TestCorrectionTrackerLifecycle` (4) | Empty text skips monitor installation; non-empty text installs `_KeyboardActivityMonitor` and calls the after-callback; `stop()` releases the monitor; double `stop()` is safe |
| `TestPoll` (1) | `_poll` exits when its deadline passes |
| `TestSendInputHelpers` (4) | `_shift_select_left(0)` is a no-op; `_shift_select_left(n)` sends the right number of inputs; `_ctrl_c` sends 4 inputs; `_press_right` sends 2 inputs |

**Note:** `sounddevice` and `soundfile` are stubbed via `sys.modules.setdefault` at the top of relevant test files because they require hardware.

---

## `test_hotkey.py` — 21 tests

Tests `_VK_MAP`, `_parse_hotkey`, and `_any_pressed`.

| Class | What it checks |
|---|---|
| `TestVkMap` (4) | Letters map to their uppercase `ord`; digits map correctly; F1–F24 virtual key codes; named keys present (`space`, `tab`, `return`, `enter`, `escape`, `backspace`) |
| `TestParseHotkey` (14) | `ctrl`/`control`, `shift`, `alt`, `win` set the correct modifier bit; German aliases `"linke windows"` and `"rechte windows"` map to `MOD_WIN`; combined modifiers; letter and function key VK resolution; unknown keys yield VK `0`; `MOD_NOREPEAT` is always set; empty list handled; whitespace trimmed |
| `TestAnyPressed` (3) | Returns `True` when a key is held; `False` when not; `True` if any key in a list is held; empty list returns `False` |

---

## `test_llm_corrector.py` — 21 tests

Tests `LLMCorrector` URL routing, proxy configuration, payload construction, the `correct()` method, and the `probe()` method.

| Class | What it checks |
|---|---|
| `TestChatUrl` (4) | Ollama builds `http://<host>:<port>/v1/chat/completions`; Openrouter and Groq use their fixed cloud URLs; zero port omitted |
| `TestProxies` (2) | Empty proxy string sets `None` (bypass); non-empty string forwarded to both `http` and `https` keys |
| `TestBuildPayload` (4) | No `Authorization` header when token is empty; `Bearer` header present when token set; payload contains required OpenAI chat fields; `{{language}}` placeholder substituted in the system prompt |
| `TestCorrect` (6) | Returns original text when LLM is disabled or input is empty; returns corrected text on success; swallows `HTTPError` and `ConnectionError` returning original text; returns original when response content is empty |
| `TestProbe` (5) | Returns result on success; raises on HTTP error; raises when body contains an `error` key; raises on empty `choices`; raises when `choices` key is missing |

---

## `test_recorder.py` — 6 tests

Tests the `Recorder` audio callback and the `stop()` method. `sounddevice` and `soundfile` are stubbed.

| Class | What it checks |
|---|---|
| `TestCallback` (4) | Frame appended when `recording=True`; `last_rms` updated correctly; frame not appended when `recording=False`; concurrent callbacks from multiple threads do not corrupt `frames` |
| `TestStop` (2) | Raises `ValueError` when `frames` is empty; calls `sf.write` with the correct path and returns a `Path` object pointing to the configured filename |

---

## `test_text_inserter.py` — 16 tests

Tests `_foreground_exe`, `_set_clipboard_text`, `_get_clipboard_text`, and `TextInserter.insert_text` by mocking Win32 ctypes calls.

| Class | What it checks |
|---|---|
| `TestForegroundExe` (3) | Returns lowercased basename; returns `""` when `OpenProcess` returns a null handle; returns `""` on any exception |
| `TestSetClipboardText` (3) | Returns `True` on full success; returns `False` when `OpenClipboard` fails; returns `False` when `GlobalAlloc` fails |
| `TestGetClipboardText` (3) | Returns the clipboard string; returns `None` when no text data; returns `None` when clipboard cannot be opened |
| `TestTextInserter` (7) | Early-returns on empty string; calls `_set_clipboard_text` with the given text; restores previous clipboard content when `restore_clipboard=True`; does not restore when `restore_clipboard=False`; applies extra delay for Word; does not apply extra delay for other apps; sends Ctrl+V |

---

## `test_translations.py` — 27 tests

Tests `ui/translations.py` for structural completeness across all 8 supported languages.

| Test | What it checks |
|---|---|
| `test_all_lang_codes_have_entry` | Every entry in `LANG_CODES` has a corresponding dict in `TRANSLATIONS` |
| `test_no_extra_keys_missing_in_other_langs` | All languages have exactly the same keys as German (the reference) |
| `test_no_empty_translations` | No translation value is an empty string |
| `test_lang_codes_list_matches_translations_keys` | `LANG_CODES` list is in sync with `TRANSLATIONS` keys |
| `test_required_key_present_in_all_langs` (parametrized × 21 keys) | 21 UI keys are present in every language |
| `test_de_save_button`, `test_en_save_button`, `test_de_title` | Spot-checks for specific German and English strings |

---

## `test_vocabulary.py` — 21 tests

Tests `VocabularyManager` load/save, add/remove, and the `apply()` substitution method.

| Class | What it checks |
|---|---|
| `TestLoadSave` (4) | Creates file when missing; loads existing JSON; corrupt file yields empty dict; `add()` persists to disk |
| `TestAddRemove` (9) | Keys are lowercased; leading/trailing spaces stripped from values; `\n` and `\t` in values preserved; empty key ignored; whitespace-only value ignored; `remove()` deletes existing entry; `remove()` on missing key is silent; `all()` returns a copy |
| `TestApply` (8) | Simple replacement; case-insensitive key lookup; surrounding punctuation preserved; no correction when word not in dict; empty input string; multiple tokens; unchanged word left alone; empty corrections dict |

---

## `test_whisper_client.py` — 13 tests

Tests `WhisperClient` proxy configuration, provider routing, custom-endpoint transcription, and the Openrouter/Groq adapters.

| Class | What it checks |
|---|---|
| `TestProxies` (2) | Empty proxy bypasses; non-empty proxy forwarded |
| `TestTranscribeRouting` (4) | Openrouter provider calls `_transcribe_openrouter`; Groq calls `_transcribe_groq`; `"lokal"` and any unknown provider call `_transcribe_custom` |
| `TestTranscribeCustom` (5) | POSTs to `<url>:<port>/<endpoint>`; `Authorization: Bearer` header sent when token set; no auth header when token empty; `response_format="json"` sends `response_format` field in body; raises `HTTPError` on bad status |
| `TestTranscribeOpenrouter` (1) | Returns transcribed text from response JSON |
| `TestTranscribeGroq` (1) | Returns transcribed text from response JSON |
