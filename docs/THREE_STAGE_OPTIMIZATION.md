# Three-Stage Optimization Plan

Status: active  
Scope: FlüsterFee plus the existing local classification / hybrid-search reranking stack

The stages are deliberately sequential. A later stage must not become a prerequisite for shipping a useful earlier stage.

## Stage 1 — optimize FlüsterFee with the current stack

Goal: improve latency, responsiveness and correction cost without adding a new model or inference runtime.

### Runtime

\`\`\`text
ASR
→ vocabulary / deterministic rules
→ Fast | Smart | Polish
→ existing LLM corrector only when required
→ insert
\`\`\`

### Smart v1

Smart v1 is heuristic and intentionally conservative.

It may bypass the existing generative corrector for short, structurally clean transcripts. It routes uncertain cases to the existing corrector.

Signals include:

- utterance length;
- terminal punctuation;
- sentence-start capitalization;
- adjacent repetition;
- self-correction markers;
- unbalanced delimiters.

It does **not** attempt semantic classification.

### Stage-1 work

1. Fast / Smart / Polish modes.
2. Heuristic Smart gate with unit tests.
3. Per-run instrumentation:
   - ASR final;
   - gate decision/reason;
   - LLM start/end;
   - insertion;
   - release-to-insert.
4. Reuse HTTP connections where safe.
5. Remove avoidable fixed UI delays after measurement.
6. Keep run-identity cancellation guarantees.
7. Collect a real dictation corpus and gate outcomes for later stages.

### Stage-1 exit gate

Before moving Smart routing to a learned model:

- Windows CI green;
- manual Windows smoke gate green;
- no stale-run regression;
- measured LLM-call reduction;
- measured release-to-insert improvement;
- review false-bypass cases on the private corpus;
- Polish remains an explicit rollback/reference mode.

Stage 1 ships independently if useful.

---

## Stage 2 — make the existing XLM-R + BGE stack resource-efficient

Goal: reuse and optimize the incumbent classifier/reranker for **both**:

1. FlüsterFee Smart routing;
2. the existing classification and hybrid-search/reranking applications.

This stage does not yet introduce a new System-One model family.

### Shared production constraint

**No additional production PyTorch instance should be required.**

Training/export may use PyTorch. Production should prefer:

- ONNX Runtime CPU;
- INT8 where quality permits;
- optional OpenVINO benchmark;
- zero mandatory additional VRAM;
- reuse of an already-running shared service where appropriate.

### XLM-R workstream

Preserve the existing classifier as the incumbent.

For FlüsterFee add task-specific heads such as:

- route: raw / local_cleanup / light_corrector / full_corrector;
- likely ASR error;
- semantic-correction need;
- formatting-only;
- meaning-change risk.

For the existing classifier application:

- preserve current labels/contracts;
- export the existing classifier to the same torch-free runtime family;
- benchmark FP32 versus INT8;
- calibrate probabilities separately per task;
- measure memory and latency at batch=1.

Prefer one reusable serving package/runtime, with separate versioned model artifacts rather than separate Python/Torch stacks.

### BGE workstream

Preserve the existing hybrid-search reranking role.

For hybrid search:

- keep the current reranking contract;
- export the pinned BGE checkpoint to ONNX;
- evaluate INT8 CPU;
- compare ranking parity and quality against the current CUDA/PyTorch reference;
- retain GPU service only when it is already useful for other workloads.

For FlüsterFee:

- BGE remains optional;
- use only for low-confidence prototype/route reranking;
- never keep it on the hot path unless the benchmark proves value.

### Stage-2 metrics

FlüsterFee:

- routing macro-F1;
- Brier / ECE;
- false bypass rate;
- P50/P95 decision latency;
- process RSS;
- additional VRAM;
- avoided LLM calls;
- release-to-insert.

Existing classifier:

- task-specific F1/accuracy;
- calibration;
- latency;
- RSS.

Hybrid retrieval:

- unchanged candidate retrieval;
- reranking MRR / nDCG / Recall@k on the existing validation set;
- ranking parity against incumbent;
- P50/P95 reranker latency;
- RSS and VRAM.

### Stage-2 exit gate

- torch-free production path demonstrated;
- no unacceptable quality regression;
- shared/runtime memory materially lower than incumbent deployment;
- FlüsterFee works with zero mandatory GPU allocation;
- existing classifier and hybrid-search behavior remain backward compatible;
- optimized incumbent becomes the reference baseline for Stage 3.

---

## Stage 3 — establish modern System-One / JEV-style methods

Goal: introduce newer decision architectures only if they beat the optimized Stage-2 incumbent.

Candidate concepts from the JEV/open-model analysis:

- typed decisions instead of generated prose;
- direct logits/probabilities;
- one state, many decisions;
- shared encoder/prefill state;
- compact specialist reader before a large generalist;
- calibrated abstention;
- hard decision deadlines;
- late-result rejection;
- deterministic code for deterministic transformations.

Candidate implementations/benchmarks may include:

- Laya;
- SemIf-style shared-state decision reading;
- NanoJev-style multi-question forward passes;
- compact multilingual NLI/specialist encoders;
- Jev/OpenRouter as cloud reference;
- future open typed-decision models.

### Rollout method

1. benchmark against the optimized Stage-2 XLM-R/BGE reference;
2. run in shadow mode;
3. compare quality, calibration, latency and memory;
4. introduce behind a provider/runtime capability interface;
5. retain rollback to Stage-2 incumbent;
6. promote only if end-to-end product metrics improve.

### Stage-3 acceptance

A modern method replaces part of Stage 2 only if it delivers a meaningful improvement in at least one of:

- decision quality/calibration;
- P95 latency;
- CPU/RAM/VRAM footprint;
- operational simplicity;
- cloud cost/privacy;

without materially regressing the others.

The preferred production runtime remains torch-free unless a clearly superior alternative justifies changing that constraint.
