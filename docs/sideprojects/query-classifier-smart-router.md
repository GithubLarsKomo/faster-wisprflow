# Query Classifier → FlüsterFee SmartRouter

Status: planned side project  
Source project: local `~/query-classifier`  
Consumer: future FlüsterFee Smart mode

## Objective

Reuse the existing `xlm-roberta-base` MultiTaskRouter architecture, training workflow and FastAPI serving pattern as a specialized low-cost decision model for FlüsterFee.

Do not reuse the former query-intent labels as-is.

## Target tasks

Primary route head:

- `raw`
- `local_cleanup`
- `light_corrector`
- `full_corrector`

Auxiliary heads:

- `likely_asr_error` — binary;
- `needs_semantic_correction` — binary;
- `formatting_only` — binary;
- `meaning_change_risk` — low / medium / high;
- optional `domain_term_risk` — binary;
- optional route-weight head compatible with the existing multi-task pattern.

## Training variants

Benchmark at least:

1. fresh `xlm-roberta-base` → FlüsterFee fine-tune;
2. existing `router_encoder` checkpoint → FlüsterFee fine-tune.

Keep the better held-out result. Do not assume transfer learning from retrieval/query intent is beneficial.

## Dataset

Build a reproducible labelled corpus from realistic dictation:

- short clean dictation;
- spoken punctuation;
- German technical/medical terms;
- German/English mixed names;
- ASR substitutions;
- grammar-only issues;
- genuine semantic ambiguity;
- cases where a generative corrector damages meaning.

Keep train/validation/test splits stable and versioned.

## Calibration

Confidence is part of the API contract.

Evaluate:

- accuracy / macro-F1;
- confusion matrix;
- Brier score;
- expected calibration error;
- confidence margin;
- selective-risk / abstention curve.

Apply temperature scaling or another explicit calibration method if required.

## Deployment targets

Required:

1. PyTorch reference for training/export and benchmarking only;
2. ONNX Runtime CPU production target;
3. INT8 CPU candidate if quality/calibration remain acceptable;
4. optional OpenVINO benchmark on the target CPU;
5. production image/process must run without importing `torch`.

The preferred production target is CPU/INT8 or another compact torch-free CPU path because the shared RTX A4000 is already used by larger workloads.

GPU is an optional acceleration path only and must not require another PyTorch/CUDA process.

## Memory policy

Targets are provisional until measured:

- preferred permanent GPU allocation: **0 MB**;
- preferred additional PyTorch processes: **0**;
- avoid keeping the SmartRouter resident on CUDA by default;
- if GPU mode is used, measure actual resident and peak VRAM;
- FlüsterFee correctness must never depend on GPU availability;
- expose backend/device/dtype and process memory through `/health`.

## Runtime architecture

Preferred deployment is a shared lightweight service:

```text
smart-decision-runtime
  ├─ ONNX SmartRouter session
  └─ optional ONNX BGE session
```

The transcript/state should be tokenized/encoded once where the exported graph allows it, and all FlüsterFee decision heads should be returned in one request. Avoid one HTTP request or one encoder pass per question.

The runtime must support explicit per-request deadlines. If the result is late, FlüsterFee discards it and applies the configured deterministic/conservative fallback.

## Serving contract

Preserve the existing FastAPI model where practical.

Proposed:

- `GET /health`
- `POST /predict`

Prediction payload should include:

- route probabilities;
- auxiliary-task probabilities;
- calibrated confidence;
- top-1/top-2 margin;
- abstain flag;
- model version;
- backend/device/dtype;
- inference latency.

## Acceptance for integration

A checkpoint is eligible for FlüsterFee only if:

- German dictation routing passes the held-out quality gate;
- calibration supports meaningful thresholds;
- CPU mode is operational;
- P95 warm latency is small compared with ASR finalization;
- one-pass multi-head output is benchmarked against separate calls;
- production inference works without PyTorch;
- memory use is measured and documented;
- failure/unavailability returns a clean fallback instead of blocking dictation.

## Future FlüsterFee role

```text
deterministic rules
→ SmartRouter
→ if confident: route
→ if uncertain: optional BGE prototype fallback
→ if still uncertain: Jev/cloud or conservative corrector
```
