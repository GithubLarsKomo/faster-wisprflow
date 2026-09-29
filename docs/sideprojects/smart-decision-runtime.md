# Smart Decision Runtime

Status: planned post-hardening side project  
Consumer: future FlüsterFee Smart mode

## Purpose

Provide a single lightweight, production inference service for FlüsterFee's non-generative decisions without launching an additional PyTorch process or CUDA context.

Training/export environments may use PyTorch. The production runtime must not require it.

## Design principles

The design adopts the useful parts of the open System-One/Jev-style model ecosystem:

- typed decisions instead of generated prose;
- native logits/probabilities instead of JSON generation/parsing;
- one compact transcript state evaluated against several decision heads;
- one encoder pass where possible;
- shared-state reuse when multiple criteria inspect the same transcript;
- persistent warm serving;
- explicit calibration;
- explicit abstention;
- hard request deadlines;
- stale-result rejection through FlüsterFee run identity;
- deterministic code for deterministic transformations.

## Target architecture

```text
FlüsterFee
   │
   │  one SmartDecisionRequest
   ▼
smart-decision-runtime
   ├─ deterministic feature builder
   ├─ tokenizer
   ├─ ONNX Runtime SmartRouter session
   │      ├─ route
   │      ├─ likely_asr_error
   │      ├─ needs_semantic_correction
   │      ├─ formatting_only
   │      └─ meaning_change_risk
   │
   └─ optional ONNX Runtime BGE session
          └─ prototype rerank only on low confidence
```

Default execution provider: CPU.

Optional providers to benchmark:

- ONNX Runtime CPU;
- ONNX Runtime CUDA only if it does not create unacceptable VRAM pressure;
- OpenVINO on suitable x86 CPUs;
- reuse of an already-running shared BGE service during migration.

## Hard constraints

1. **No additional production PyTorch instance.**
2. **No mandatory GPU residency.**
3. **No model load per request.**
4. **No autoregressive output decoding for routing.**
5. **No separate encoder call for every auxiliary decision if a multi-head graph can return them together.**
6. **No Smart result may be applied after its run/deadline is stale.**
7. **Resource pressure degrades performance, not correctness.**

## Request contract

Proposed request:

```json
{
  "run_id": 123,
  "deadline_ms": 150,
  "transcript": "...",
  "features": {
    "word_count": 17,
    "spoken_punctuation_hits": 1,
    "vocabulary_substitutions": 0,
    "language_hint": "de",
    "asr_confidence": null
  },
  "allow_bge_fallback": true
}
```

The deadline is a budget, not a promise. If the runtime cannot return a useful result in time, it returns `abstain` or FlüsterFee ignores the late response.

## Response contract

```json
{
  "run_id": 123,
  "route": "local_cleanup",
  "route_probabilities": {
    "raw": 0.08,
    "local_cleanup": 0.84,
    "light_corrector": 0.07,
    "full_corrector": 0.01
  },
  "aux": {
    "likely_asr_error": 0.12,
    "needs_semantic_correction": 0.09,
    "formatting_only": 0.91,
    "meaning_change_risk": {
      "low": 0.94,
      "medium": 0.05,
      "high": 0.01
    }
  },
  "confidence": 0.84,
  "margin": 0.76,
  "abstain": false,
  "bge_used": false,
  "latency_ms": 24.3,
  "model_version": "fluesterfee-router-...",
  "runtime": "onnxruntime-cpu-int8"
}
```

## SmartRouter export pipeline

Development/training environment:

```text
PyTorch / Transformers
→ train + calibrate
→ export ONNX
→ validate ONNX parity
→ quantize candidate
→ validate quality + calibration again
→ publish versioned inference artifact
```

Production receives only:

- ONNX graph/weights;
- tokenizer files;
- calibration/threshold metadata;
- model manifest/checksum.

PyTorch is not installed in the production runtime image.

## BGE export/migration

The current BGE service remains valid for existing workloads.

For FlüsterFee:

1. first benchmark reuse of the already-running service;
2. create our own reproducible ONNX export from the pinned upstream revision;
3. benchmark fp32 and INT8 CPU variants;
4. validate ranking/prototype-routing parity against the current PyTorch reference;
5. only include BGE in the shared runtime if the incremental routing benefit justifies its memory footprint.

Do not depend on an unpinned third-party community export for production, even if community ONNX/INT8 artifacts are useful feasibility references.

## Memory strategy

Primary goal:

- SmartRouter resident on CPU;
- BGE loaded only if its measured benefit warrants the additional RAM;
- **0 MB additional mandatory VRAM**;
- **0 additional production PyTorch processes**.

Candidate optimization options:

- INT8 dynamic quantization;
- reduced max sequence length for dictation routing;
- a smaller distilled/specialist encoder if XLM-R remains unnecessarily large;
- memory-mapped model files where supported;
- shared tokenizer assets where architecture permits;
- process-level memory limits and health reporting.

## Benchmark matrix

Compare:

1. deterministic rules only;
2. XLM-R PyTorch reference;
3. XLM-R ONNX fp32 CPU;
4. XLM-R ONNX INT8 CPU;
5. smaller specialist/NLI encoder if needed;
6. XLM-R ONNX → BGE PyTorch existing shared service;
7. XLM-R ONNX → BGE ONNX fp32;
8. XLM-R ONNX → BGE ONNX INT8;
9. Laya;
10. Jev/OpenRouter;
11. always-correct baseline.

Measure:

- routing accuracy / macro-F1;
- Brier / ECE;
- selective-risk / abstention;
- P50/P95 latency;
- process RSS;
- model-file size;
- CPU utilization;
- additional VRAM;
- avoided LLM calls;
- end-to-end release-to-insert latency.

## Acceptance gate

The shared runtime can ship only if:

- production image contains no PyTorch dependency;
- CPU mode meets the latency budget;
- calibration is stable on the held-out German dictation corpus;
- memory is acceptable alongside the rest of the local stack;
- deadlines and stale-result handling are tested;
- FlüsterFee still works when the runtime is offline;
- BGE remains optional.
