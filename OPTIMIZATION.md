# FlüsterFee Optimization Roadmap

Date: 2026-09-20  
Status: **post-hardening / next development cycle**

This roadmap starts only after the current hardening branch has passed its manual Windows smoke gate and is merged. It deliberately keeps ASR engine experiments out of the correctness PR.

## Goals

Optimize four things together:

1. release-to-text latency and perceived responsiveness;
2. transcription and correction quality for German and mixed technical vocabulary;
3. local/private operation with predictable cloud fallback;
4. API and compute cost without sacrificing text completeness.

## Architecture decision

FlüsterFee remains the Windows interaction and UX layer. ASR is treated as an interchangeable capability rather than a fixed Whisper implementation.

The application must support:

- OpenAI-compatible file transcription;
- optional streaming/realtime transcription;
- capability discovery per backend;
- local Windows, local-network GPU and cloud targets;
- clean fallback from streaming to non-streaming;
- model/provider changes without UI-specific routing logic.

Extend the provider registry with capabilities such as:

- `supports_streaming`
- `supports_partial_results`
- `supports_prompt`
- `supports_language_hint`
- `supports_usage`
- `supports_model_listing`
- `local_only`
- `realtime_transport` (`none`, `sse`, `websocket`)
- `engine_family`

Do not bake OpenASR-, Speaches-, Whisper- or Qwen-specific behavior into the dock or orchestration layer.

## Open-source candidates

### OpenASR — primary multi-engine candidate

Why evaluate it first:

- Apache-2.0 open core;
- Windows, Linux and macOS engine/server support;
- local OpenAI-compatible transcription endpoint;
- realtime WebSocket path;
- broad model catalog beyond Whisper, including Qwen3-ASR, Parakeet, Moonshine and other families;
- explicit local-first/offline design.

Risk:

- pre-v1 and under active development; API/pack formats can still change.

Use it as a candidate backend, not as a hard dependency.

### Speaches / faster-whisper — primary Whisper baseline

Why evaluate it:

- MIT-licensed;
- OpenAI-compatible API;
- faster-whisper/CTranslate2 backend;
- CPU and GPU support;
- streaming transcription and realtime API;
- Docker deployment fits a dedicated local GPU server well.

This is the reference backend for answering: “How fast and accurate can a mature optimized Whisper stack be on our hardware?”

### whisper.cpp — lightweight fallback/reference

Use as a low-dependency native reference and possible packaged fallback. It is valuable for CPU/quantized Whisper measurements, but should not define the overall architecture because it narrows model choice to the Whisper family.

### sherpa-onnx — embedded/offline candidate

Evaluate if a later goal is to embed ASR directly into a cross-platform application without a separate server. It supports Windows and streaming/non-streaming ASR with ONNX Runtime and has a broad speech feature set.

Do not make it the first FlüsterFee backend unless the benchmark shows a clear advantage; model licensing must be reviewed separately from the Apache-2.0 engine license.

### WhisperLiveKit / SimulStreaming — streaming reference

Use as a research/reference implementation for low-latency incremental Whisper-style transcription. It is useful for evaluating streaming UX and commit policies, but is more complex than needed for the first production optimization pass.

### WhisperX

Do not prioritize for push-to-talk dictation. Its alignment and diarization strengths are useful for meetings/subtitles, but add capabilities and complexity that are not central to FlüsterFee’s single-speaker insertion workflow.

## Model candidates

Do not select a default from public leaderboard numbers alone.

Initial local benchmark set:

- Whisper large-v3-turbo through faster-whisper/Speaches;
- Whisper large-v3-turbo through OpenASR where available;
- Qwen3-ASR-0.6B;
- Qwen3-ASR-1.7B if hardware permits;
- Parakeet-TDT-0.6B-v3 for German/European dictation;
- one small/quantized local fallback model suitable for CPU-only operation.

Moonshine can be added if the available German-capable pack is competitive in the same test harness.

## Benchmark corpus

Create a private, reproducible corpus of real dictation patterns instead of relying only on generic WER sets.

Include at least:

- short commands: 2–8 words;
- normal sentences: 10–30 words;
- long dictation: 30–120 seconds;
- German technical/medical vocabulary;
- German with English product/model names;
- numbers, units, dates and abbreviations;
- spoken punctuation/dictation commands;
- quiet room and realistic office noise;
- several natural speaking rates.

Keep exact reference transcripts.

## Metrics

Quality:

- normalized WER/CER;
- domain-term recall;
- number/date/unit accuracy;
- punctuation-command accuracy;
- capitalization/punctuation quality;
- hallucination / omitted-text rate.

Responsiveness:

- cold model load;
- warm request latency;
- release-to-first-partial;
- release-to-final-transcript;
- release-to-insert;
- realtime factor;
- P50/P95, not only averages.

Resources:

- CPU;
- RAM;
- GPU utilization;
- VRAM;
- model size;
- idle memory;
- power where practical.

Economics:

- local compute time/power estimate;
- cloud cost per audio minute;
- LLM correction cost;
- percentage of runs requiring cloud fallback.

## Selection rule

There is no predetermined winning engine.

Select:

- **default local backend** by German domain quality + warm release-to-final latency;
- **realtime backend** by stable partial/final behavior and P95 latency;
- **CPU fallback** by acceptable accuracy at low resource use;
- **cloud fallback** by quality/latency/cost and availability.

A backend must not become the default merely because it wins a batch-throughput benchmark.

## UX modes

After the ASR baseline is measured, implement three user-facing profiles:

### Fast

`ASR → vocabulary/local rules → insert`

- no LLM unless explicitly requested;
- lowest latency and cost.

### Smart — intended default

`ASR → vocabulary/local rules → conditional LLM → insert`

- local heuristic decides whether correction adds value;
- cloud/local LLM is skipped for short or already-clean text;
- user can choose “insert raw now” while correction is running.

### Polish

`ASR → vocabulary → LLM correction → insert`

- maximum cleanup;
- higher latency is explicit.

## Implementation sequence

### O0 — instrumentation

Add per-run timings to `RunContext`:

- recording stopped;
- audio ready;
- first partial;
- ASR final;
- LLM start/end;
- insert start/end.

Record backend/model and usage/cost metadata when available.

### O1 — transport efficiency

- persistent HTTP sessions / connection reuse;
- remove avoidable fixed UI delays;
- move remaining event polling toward Qt signals where practical.

### O2 — ASR benchmark harness

Build one runner capable of sending the same corpus to:

1. current local endpoint;
2. OpenASR;
3. Speaches/faster-whisper;
4. selected cloud baselines;
5. optional whisper.cpp/sherpa/WhisperLiveKit experiments.

Emit machine-readable JSON/CSV with quality, timing and resource fields.

### O3 — capability-based ASR adapters

Extend `provider_registry.py` and `WhisperClient` into a generic transcription adapter layer.

Keep existing provider behavior compatible.

### O4 — choose local defaults

Run the corpus on the actual target hardware. Store benchmark date, model hashes/versions and engine versions with the result.

Only then choose the default local/realtime/CPU fallback models.

### O5 — Smart mode

Implement Fast / Smart / Polish and conditional LLM correction.

### O6 — “raw now”

Once the final raw ASR text is available, allow immediate insertion while an optional correction is still running. Cancelling or superseding the correction must reuse existing run-identity gates.

### O7 — realtime

Add realtime audio transport only for backends that advertise it.

Partial text is preview-only until committed. Never paste unstable partial hypotheses into the target application.

### O8 — UI/settings simplification

Daily settings first:

- microphone;
- language;
- hotkey;
- mode;
- ASR target/model;
- correction target/model.

Move sample rate, channels, proxy, TLS and manual endpoints under Advanced.

Use non-modal save/status feedback.

### O9 — insertion/startup optimization

Evaluate:

- direct Unicode insertion with clipboard fallback;
- full clipboard preservation if feasible;
- onedir + installer versus onefile startup;
- dev-only dependency separation.

## Current working hypothesis

The first practical comparison should be:

- **Speaches/faster-whisper** on the local GPU server as a strong, mature Whisper baseline;
- **OpenASR** on the same server and/or Windows as the broader multi-model/realtime candidate;
- current Groq/OpenAI paths as cloud controls.

OpenASR is strategically attractive because it prevents the local architecture from becoming Whisper-only. Speaches is the safer benchmark baseline because it is narrowly focused on a well-established faster-whisper stack.

The final default remains benchmark-driven.
