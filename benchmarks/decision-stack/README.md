# FlüsterFee Decision Stack Benchmark

This directory is the evidence gate for replacing XLM-R and BGE.

## Classifier dataset

JSONL, one object per line:

```json
{"id":"c-001","text":"...","label":"light_corrector","language":"de","critical":false}
```

Labels: `raw`, `local_cleanup`, `light_corrector`, `full_corrector`.

Use real or de-identified FlüsterFee transcripts with human-reviewed labels. Do not commit private production transcripts; keep the real dataset outside Git and pass its local path.

## Reranker dataset

```json
{"id":"r-001","query":"...","documents":[{"id":"a","text":"...","relevance":2},{"id":"b","text":"...","relevance":0}]}
```

Relevance may be binary or graded.

## Endpoint contracts

Classifier: `POST /classify` with `{"text":"..."}` and response containing either `label` or a `scores` object, plus optional `abstain`.

Reranker: `POST /rerank` with `{"query":"...","documents":["...","..."]}` and response `{"scores":[...]}`.

`GET /health` should expose model/runtime/quantization and resource metadata where available.

## Run

```powershell
python benchmarks/decision-stack/benchmark.py classifier --dataset C:\secure\classifier-v1.jsonl --endpoint http://host:port/classify --health http://host:port/health --name mmbert-small-int8 --output results/mmbert-small-int8.json
```

```powershell
python benchmarks/decision-stack/benchmark.py reranker --dataset C:\secure\reranker-v1.jsonl --endpoint http://host:port/rerank --health http://host:port/health --name gte-int8 --output results/gte-int8.json
```

## Required comparisons

Router:

1. incumbent XLM-R;
2. mmBERT-small reference;
3. mmBERT-small ONNX INT8;
4. EuroBERT-210m;
5. mmBERT-base only if needed.

Reranker:

1. BGE-v2-m3 incumbent;
2. GTE multilingual reranker reference;
3. GTE ONNX INT8;
4. optional Qwen3-0.6B quality ceiling.

Selection criteria are defined in `docs/DECISION_STACK_REPLACEMENT_PLAN.md`.