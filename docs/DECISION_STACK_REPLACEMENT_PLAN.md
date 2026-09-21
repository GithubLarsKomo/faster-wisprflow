# Decision Stack Replacement Plan

Status: proposed / benchmark-gated  
Date: 2026-09-21

## Goal

Replace the planned/current heavyweight local decision components with lower-cost models while preserving or improving task quality.

Target replacements:

- classifier/router: XLM-R -> mmBERT-small or EuroBERT-210m;
- reranker: BAAI/bge-reranker-v2-m3 -> Alibaba-NLP/gte-multilingual-reranker-base.

The replacement is accepted only after a non-inferiority benchmark on FlüsterFee data.

## Design principles

1. No production regression is accepted for critical routing decisions.
2. Production inference should not require another persistent PyTorch process.
3. CPU/ONNX Runtime is the preferred steady-state path.
4. GPU use is optional and must respect a free-VRAM guard.
5. The incumbent remains available behind a rollback switch until the replacement has survived shadow mode.
6. Scores are not treated as calibrated probabilities unless calibration is measured on held-out local data.

## Candidate stack

### Router

Primary candidate: `jhu-clsp/mmBERT-small`

- 140M parameters;
- 8K context;
- MIT license;
- ONNX artifacts exist, including INT8;
- target runtime: ONNX Runtime CPU;
- candidate role: fine-tuned 4-way SmartRouter.

Secondary candidate: `EuroBERT/EuroBERT-210m`

- 210M parameters;
- 8K context;
- Apache-2.0;
- especially relevant for German/English/European-language traffic;
- target runtime: ONNX Runtime/OpenVINO if export passes parity tests.

Reference candidate: `jhu-clsp/mmBERT-base`

- use only if small variants fail the quality gate.

### Reranker

Primary candidate: `Alibaba-NLP/gte-multilingual-reranker-base`

- 306M parameters;
- 75 languages;
- 8K context;
- Apache-2.0;
- encoder-only;
- prebuilt ONNX variants exist, including INT8;
- target runtime: ONNX Runtime CPU.

Incumbent: `BAAI/bge-reranker-v2-m3`

- remains the comparison baseline and rollback implementation.

Optional quality ceiling: Qwen3-Reranker-0.6B.

## Target cascade

```text
transcript
  -> deterministic rules
  -> SmartRouter (mmBERT-small or EuroBERT-210m)
  -> if uncertain: GTE multilingual reranker over route prototypes
  -> if still uncertain: Jev/cloud or conservative full-corrector policy
```

The reranker remains an escalation stage rather than a mandatory pass for every transcript.

## Benchmark gate

Benchmark harness: `benchmarks/decision-stack/`

### Router metrics

- macro-F1;
- balanced accuracy;
- per-route recall;
- confusion matrix;
- abstention coverage and error rate;
- p50/p95 latency;
- process RSS;
- optional GPU resident/peak VRAM;
- model-load time.

Acceptance target:

- macro-F1 >= incumbent - 0.005;
- no critical-route recall regression > 0.01;
- and either >= 35% lower RSS or >= 1.5x better p95 latency;
- INT8 parity delta <= 0.005 macro-F1 versus FP32/FP16 candidate.

### Reranker metrics

- nDCG@10;
- MRR@10;
- Recall@5/10;
- p50/p95 latency;
- throughput;
- process RSS / GPU VRAM;
- model-load time.

Acceptance target:

- nDCG@10 >= BGE - 0.005;
- MRR@10 >= BGE - 0.005;
- and either >= 30% lower peak memory or >= 1.5x higher throughput;
- no material loss on German queries or long-context examples.

## Evaluation data

Do not manufacture benchmark labels from model outputs.

Required classifier set:

- real or de-identified FlüsterFee transcripts;
- route label: raw | local_cleanup | light_corrector | full_corrector;
- language;
- optional ambiguity flag;
- human-reviewed ground truth.

Required reranker set:

- real query / candidate-document or transcript / route-prototype groups;
- graded relevance labels where possible;
- German-heavy subset reported separately.

Data must remain local if it contains company/private content.

## Rollout

1. Freeze benchmark dataset v1.
2. Benchmark incumbent XLM-R/BGE runtime.
3. Fine-tune/evaluate mmBERT-small and EuroBERT-210m.
4. Export winning router to ONNX and evaluate INT8.
5. Benchmark GTE ONNX against BGE.
6. Run both replacements in shadow mode.
7. Enable via configuration only after acceptance gate.
8. Keep rollback switch for at least one stable release cycle.

## Exit criteria

This plan is complete when one router and one reranker candidate have reproducible benchmark results, passed the quality/resource gates, a torch-free production artifact, a shadow-mode report, rollback documentation, and a consumer integration PR in FlüsterFee.