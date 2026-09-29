# FlüsterFee Optimization Roadmap

Date: 2026-09-20  
Status: **post-hardening / next development cycle**

This roadmap starts only after the current hardening branch has passed its manual Windows smoke gate and is merged. It deliberately keeps ASR engine experiments out of the correctness PR.

## Execution order

Implementation follows the explicit three-stage plan in `docs/THREE_STAGE_OPTIMIZATION.md`:

1. optimize FlüsterFee with the current stack and a heuristic Smart gate;
2. optimize the incumbent XLM-R classifier and BGE reranker for low-resource shared use across FlüsterFee and the existing classification/hybrid-search applications;
3. only then benchmark and establish newer System-One/JEV-style methods.

A later stage must not block shipping a useful earlier stage.

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

Preferred decision pipeline:

`ASR → vocabulary/local rules → deterministic gate → optional decision model (Laya/Jev) → conditional corrector → insert`

Rules:

- trivial/short/obviously clean text bypasses all model-based routing;
- ambiguous runs may be sent to a structured decision model such as local Laya or cloud TypeSafe Jev;
- the decision model is a router/judge only, never the prose corrector;
- only a generative correction model may rewrite arbitrary text;
- a Jev decision can route to raw insert, local cleanup, lightweight corrector, full corrector, or user-review/fallback;
- user can choose “insert raw now” while correction is running;
- if Jev is unavailable or exceeds its latency budget, fall back to deterministic routing rather than blocking insertion.

Recommended Jev questions for one transcript can be evaluated together:

- `needs_semantic_correction`: yes/no probability;
- `likely_asr_error`: yes/no probability;
- `formatting_only`: yes/no probability;
- `meaning_change_risk`: low/medium/high choice;
- `recommended_path`: raw/local_cleanup/light_corrector/full_corrector;
- optional `domain_term_risk`: yes/no probability.

Use calibrated probabilities and explicit thresholds rather than a single opaque “smart” answer.

### Reuse existing local classifier and BGE reranker

Before adding a new model family, benchmark the user's existing local routing stack.

#### Existing multi-task classifier — primary reuse candidate

The existing query-classifier architecture is already very close to a System-One router:

- multilingual `xlm-roberta-base` encoder;
- non-autoregressive single-pass inference;
- one intent classification head;
- one softmax weighting head;
- local FastAPI deployment pattern on GPU;
- existing training/export workflow.

Do not reuse the old task labels directly. Reuse the architecture, training harness and serving pattern.

Recommended FlüsterFee heads:

- `route`: raw / local_cleanup / light_corrector / full_corrector;
- `likely_asr_error`: binary;
- `needs_semantic_correction`: binary;
- `formatting_only`: binary;
- `meaning_change_risk`: low / medium / high;
- optional continuous or softmax route-weight head.

Train a fresh FlüsterFee checkpoint from `xlm-roberta-base` and benchmark a second run initialized from the existing router encoder. Keep whichever transfers better. Do not assume the old query-routing weights transfer to dictation cleanup.

Treat calibration as a release requirement:

- held-out FlüsterFee routing set;
- temperature scaling or another explicit calibration step;
- report accuracy/F1, Brier score/ECE, confidence margin and selective-risk curves;
- thresholds chosen from the measured cost of false bypass vs unnecessary correction.

This model is the leading candidate for the local Smart router because it can be specialized to German/multilingual dictation without introducing another runtime family.

#### Existing BGE reranker — secondary/prototype decision layer

The existing `BAAI/bge-reranker-v2-m3` FastAPI service already produces normalized cross-encoder scores for `[query, document]` pairs. Reuse it first as an experimental prototype scorer, not as a calibrated classifier.

Two benchmark modes:

1. **Route-description scoring**
   - query = ASR transcript;
   - candidate documents = natural-language descriptions of `raw`, `local_cleanup`, `light_corrector`, `full_corrector`;
   - batch the four pairs in one request.

2. **Prototype-example scoring**
   - maintain labelled real examples per route;
   - score the new transcript against representative examples;
   - aggregate top-k scores per route;
   - use score margin/entropy to decide whether the result is confident enough.

The prototype approach is preferred because BGE is trained for relevance ranking rather than route-label probability estimation. Its sigmoid-normalized scores are relevance scores, not calibrated mutually exclusive class probabilities.

Use BGE only after the deterministic gate and preferably only when the primary classifier is uncertain; otherwise the ~568M cross-encoder is unnecessary work for a four-way decision.

#### Proposed local cascade

```text
ASR
 ↓
Vocabulary + deterministic rules
 ↓
obvious clean/format-only case?
 ├─ yes → raw/local cleanup → insert
 └─ no
     ↓
FlüsterFee MultiTaskRouter (XLM-R)
     ↓
high calibrated confidence?
 ├─ yes → selected route
 └─ no
     ↓
optional BGE prototype rerank
     ↓
still ambiguous?
 ├─ no → selected route
 └─ yes → Jev/OpenRouter or conservative full corrector
```

This preserves a zero-cloud path while keeping Jev as an external reference/fallback rather than a mandatory hop.

Benchmark variants:

1. deterministic rules only;
2. existing-architecture XLM-R classifier, fresh fine-tune;
3. XLM-R classifier initialized from the existing router checkpoint;
4. BGE route-description scoring;
5. BGE prototype-example scoring;
6. XLM-R → BGE uncertainty cascade;
7. Laya multilingual zero-shot;
8. Laya FlüsterFee fine-tuned/calibrated;
9. Jev/OpenRouter;
10. always correct.

Selection is based on end-to-end release-to-insert latency, routing error cost, calibration, GPU residency cost and avoided generative-correction calls — not headline classifier accuracy alone.

### Laya / Jev System One evaluation

Jev and Laya are strong candidates for Smart-mode routing because their output spaces are predefined and typed, with probabilities/confidence rather than free-form strings. This matches the routing problem much better than asking another generative LLM whether a generative LLM is needed.

Laya is the preferred local candidate to benchmark. It is Apache-2.0, non-autoregressive, small enough for local deployment, supports typed `choice` / `score` / boolean-style decisions, and can be fine-tuned on the exact FlüsterFee routing task. Treat its published Jev comparison cautiously: the Laya project itself states that Jev numbers were not measured on identical samples/prompts; the base checkpoints are weak zero-shot on typed decisions and the strongest reported typed-decision result comes from task-specific fine-tuning. For German, benchmark the multilingual checkpoint and a FlüsterFee-specific fine-tune with explicit temperature calibration before trusting confidence thresholds.

Current integration targets:

- local Laya service/SDK on the GPU host as the preferred local decision-provider experiment;
- direct TypeSafe API where appropriate;
- OpenRouter Decisions API as the preferred cloud integration because FlüsterFee already supports OpenRouter credentials/routing.

OpenRouter currently exposes TypeSafe Jev models including `typesafe/jev-1.13` and an always-latest alias. For reproducible benchmarks and production thresholds, pin a concrete Jev version; use the latest alias only for exploratory testing.

Important architectural constraint: Jev does not belong in `LLMCorrector` as a chat-completion model. Introduce a separate `DecisionProvider` / `SmartRouter` abstraction. OpenRouter’s current Jev examples use its Decisions API, so treat this as a distinct provider capability rather than assuming ordinary chat-completions behavior.

Benchmark decision routing against:

1. deterministic rules only;
2. local Laya multilingual zero-shot;
3. local Laya fine-tuned/calibrated for FlüsterFee routing;
4. a small/fast generative classifier through OpenRouter/local inference;
5. Jev through OpenRouter;
6. no routing (always correct).

Measure end-to-end Smart-mode latency and total saved correction calls, not just Jev inference speed.

A learned decision provider is adopted only if it reduces correction cost/latency at equal or better routing quality. Laya has the architectural advantage of a local zero-network round trip; Jev has the operational advantage of no local model management and a much larger context window. Deterministic rules remain first in the cascade.

### Polish

`ASR → vocabulary → LLM correction → insert`

- maximum cleanup;
- higher latency is explicit.

## System-One concepts adopted from the open-model ecosystem

The open Jev-style ecosystem reinforces several design principles that are directly useful for FlüsterFee. These ideas are adopted independently of any one model implementation.

1. **No generation for routing.** Smart routing should read declared logits/probabilities directly. No prose answer, JSON repair loop or token-by-token decoder is needed.
2. **One state, many decisions.** The transcript plus local features form one compact state. Route, ASR-error risk, formatting-only and semantic-risk outputs should be produced in one encoder pass / multi-head call where possible.
3. **Reuse the shared state.** When several criteria inspect the same transcript, encode/prefill the transcript once and fan out decision heads/criteria rather than recomputing the full state. SemIf reports a large speedup from state reuse on repeated criteria; NanoJev similarly evaluates many questions in one forward pass.
4. **Small specialist before large generalist.** Benchmark our existing XLM-R router against smaller specialist/NLI-style encoders instead of assuming larger models are better.
5. **Rerankers stay rerankers.** BGE remains a strong retrieval/prototype scorer, but it should not be treated as the primary typed-decision reader unless our corpus proves otherwise.
6. **State representation is part of the model.** Prefer a compact structured state over arbitrary prompt prose. Candidate fields: transcript, word count, spoken-punctuation hits, vocabulary substitutions, detected language mix, ASR confidence/metadata when available, and deterministic error flags.
7. **Decision deadlines are first-class.** A late routing result is stale. Reuse FlüsterFee run identity gates: results arriving beyond their latency budget are discarded and can never delay or overwrite a newer run.
8. **Fail open to a deterministic policy.** If the decision runtime is unavailable, overloaded or low-confidence, continue with raw/local cleanup or the configured conservative corrector.
9. **Persistent lightweight serving.** Load the selected compact model once and reuse it; never load a model per dictation.
10. **Calibration is separate from accuracy.** Confidence thresholds are calibrated on FlüsterFee data, not inferred from raw logits or headline benchmark accuracy.
11. **Code handles deterministic work.** Vocabulary replacement, punctuation commands and simple formatting remain code. The learned model resolves ambiguity only.

### Hard production-runtime rule: no additional PyTorch instance

Training and model export may use PyTorch. **Production Smart inference must not require launching another PyTorch process or CUDA context.**

Preferred end state:

```text
FlüsterFee
   ↓ HTTP/IPC
smart-decision-runtime
   ├─ ONNX Runtime session: FlüsterFee SmartRouter
   └─ ONNX Runtime session: optional BGE prototype reranker
```

Design goals:

- one small process;
- CPU default;
- INT8 where quality/calibration permit;
- no `torch` import in the production image/process;
- no CUDA context by default;
- tokenizer/runtime dependencies shared where practical;
- optional OpenVINO or ONNX execution provider benchmarking;
- optional GPU execution only if it can reuse an already-running shared service or remains within a strict free-VRAM policy;
- model training/export stays in a separate development environment or CI artifact pipeline.

If the existing PyTorch BGE service is already running for other workloads, FlüsterFee may reuse that service during migration, but **must not launch a second BGE/PyTorch instance**.

## GPU/Memory policy

The target GPU is shared with other local AI workloads. Smart mode must therefore improve latency/cost without reserving several additional gigabytes of VRAM permanently.

### Budget principles

- **do not add another production PyTorch instance for Smart routing**;
- do not require both decision models to remain GPU-resident;
- prefer one shared CPU/ONNX Runtime service for the SmartRouter and optional BGE fallback;
- prefer a CPU/INT8 or otherwise compact deployment for the primary XLM-R SmartRouter;
- keep BGE as an uncertainty fallback, not on the hot path for every dictation;
- GPU acceleration is opportunistic, not required for correctness;
- expose per-service memory/device status through `/health`;
- record model resident memory and peak VRAM in the benchmark harness;
- never evict a larger production model merely to speed up Smart routing.

Current upstream weight sizes underline the need for this policy: `xlm-roberta-base` ships roughly 1.12 GB of full-precision PyTorch/safetensors weights, while `BAAI/bge-reranker-v2-m3` ships roughly 2.27 GB of full-precision model weights. Runtime memory depends on dtype, backend, sequence length and allocator overhead, so selection must use measured resident/peak memory rather than file-size estimates.

### SmartRouter side project

Goal: turn the existing `~/query-classifier` architecture into a compact FlüsterFee decision service without making the shared GPU a hard dependency.

Work:

1. preserve the existing XLM-R multi-head/FastAPI training pattern;
2. train fresh FlüsterFee routing heads and compare transfer from the existing router checkpoint;
3. export at least:
   - PyTorch reference for training/benchmark only;
   - ONNX Runtime CPU production candidate;
   - INT8 CPU production candidate if quality/calibration remain acceptable;
4. require the production runtime/container to operate without importing PyTorch;
5. benchmark batch=1, short sequences representative of dictation;
6. benchmark one-pass multi-head outputs against separate decision calls;
7. measure P50/P95 latency, RSS, model load time, CPU utilization and VRAM;
8. add `/health` fields for backend, dtype, device and measured/estimated resident memory;
9. target a CPU-capable default so the service can remain available even when the GPU is occupied.

Acceptance for FlüsterFee integration:

- routing quality/calibration meets the held-out corpus gate;
- warm P95 routing latency remains small compared with ASR completion latency;
- CPU mode is usable;
- GPU mode has a configurable VRAM ceiling and is optional.

### BGE reranker side project

Goal: preserve the existing BGE service for retrieval while adding an optional low-memory Smart-routing mode.

Do not replace the existing `/rerank` contract. Add a separate versioned endpoint or mode for prototype routing.

Work:

1. add labelled-prototype batching/aggregation;
2. benchmark the current FP16 CUDA/PyTorch path only as the migration reference;
3. export/serve BGE through ONNX Runtime as the preferred production path;
4. evaluate CPU INT8/dynamic quantization and a torch-free runtime image;
5. consider a smaller multilingual reranker only if `bge-reranker-v2-m3` remains too expensive for the marginal routing gain;
6. add lazy/on-demand model initialization only for non-interactive paths; do not accept multi-second cold starts in the FlüsterFee hot path;
7. expose device/dtype/model and memory statistics through `/health`;
8. make GPU use policy-driven:
   - use GPU only when configured and sufficient free VRAM is available;
   - otherwise use CPU or skip BGE and fall back to the next Smart policy.

Acceptance:

- FlüsterFee does not start a new PyTorch process for BGE;
- the preferred production path is ONNX Runtime or reuse of an already-running shared service;
- no permanent GPU residency is required for normal FlüsterFee operation;
- BGE is invoked only for low-confidence primary-router cases;
- its incremental routing benefit justifies its measured latency and memory cost.

### Runtime cascade under GPU pressure

```text
Rules
  ↓
CPU/INT8 XLM-R SmartRouter
  ↓ high confidence
route
  ↓ low confidence
BGE available within memory/latency budget?
  ├─ yes → BGE prototype rerank
  └─ no  → Jev/OpenRouter or conservative corrector
```

This makes GPU pressure a performance concern rather than a correctness failure.

## Implementation sequence

### O0 — instrumentation

Add per-run timings to `RunContext`:

- recording stopped;
- audio ready;
- first partial;
- ASR final;
- routing start/end;
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

### O5 — Smart mode and decision routing

Implement Fast / Smart / Polish.

For Smart:

1. deterministic zero-cost gate;
2. torch-free shared `SmartRouter` runtime (ONNX Runtime preferred);
3. existing XLM-R-derived router as the primary local decision model;
4. optional BGE prototype scorer inside the same runtime or reuse of an already-running shared BGE service;
5. Laya/Jev adapters remain benchmark/fallback providers rather than required runtime dependencies;
6. domain-calibrated confidence thresholds and explicit decision deadlines;
7. conditional generative LLM correction;
8. fallback to deterministic policy on decision-provider errors/timeouts.

Do not use Jev to generate corrected prose.

### O6 — “raw now”

Once the final raw ASR text is available, allow immediate insertion while an optional routing/correction request is still running. Cancelling or superseding the correction must reuse existing run-identity gates.

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

The first practical ASR comparison should be:

- **Speaches/faster-whisper** on the local GPU server as a strong, mature Whisper baseline;
- **OpenASR** on the same server and/or Windows as the broader multi-model/realtime candidate;
- current Groq/OpenAI paths as cloud controls.

For Smart-mode routing, the working hypothesis is:

- deterministic local rules handle obvious cases;
- **the existing XLM-R MultiTaskRouter architecture, retrained for FlüsterFee, is the primary local candidate**;
- the existing BGE reranker is tested as an uncertainty/prototype fallback rather than the main classifier;
- Laya remains a clean external open-source benchmark for a purpose-built System-One architecture;
- **Jev through OpenRouter Decisions** is the cloud comparator/fallback and may be preferable where local deployment is undesirable;
- the existing local/cloud generative corrector remains responsible for actual rewriting.

Working preference for FlüsterFee: deterministic rules → calibrated retrained XLM-R router → optional BGE prototype fallback → conditional corrector, with Laya and Jev as benchmark comparators. This preference remains provisional until the German FlüsterFee routing corpus is measured.

OpenASR is strategically attractive because it prevents the local architecture from becoming Whisper-only. Speaches is the safer benchmark baseline because it is narrowly focused on a well-established faster-whisper stack.

The final defaults remain benchmark-driven.
