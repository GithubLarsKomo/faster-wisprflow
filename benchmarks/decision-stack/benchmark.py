from __future__ import annotations

import argparse
import json
import math
import statistics
import time
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open('r', encoding='utf-8') as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f'{path}:{line_no}: invalid JSON: {exc}') from exc
    return rows


def post_json(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    body = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=body, method='POST', headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode('utf-8'))


def get_json(url: str | None, timeout: float) -> dict[str, Any] | None:
    if not url:
        return None
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode('utf-8'))


def percentile(values: list[float], p: float) -> float:
    if not values:
        return float('nan')
    ordered = sorted(values)
    return ordered[max(0, math.ceil(p * len(ordered)) - 1)]


def classifier_metrics(rows: list[dict[str, Any]], preds: list[dict[str, Any]]) -> dict[str, Any]:
    labels = sorted({str(r['label']) for r in rows})
    per_class = defaultdict(lambda: Counter(tp=0, fp=0, fn=0, support=0))
    correct = 0
    abstained = 0
    covered_errors = 0
    critical_total = 0
    critical_correct = 0

    for row, pred in zip(rows, preds):
        truth = str(row['label'])
        label = str(pred['label'])
        abstain = bool(pred.get('abstain', False))
        per_class[truth]['support'] += 1

        if bool(row.get('critical', False)):
            critical_total += 1
            if label == truth and not abstain:
                critical_correct += 1

        if abstain:
            abstained += 1
            continue
        if label == truth:
            correct += 1
            per_class[truth]['tp'] += 1
        else:
            covered_errors += 1
            per_class[truth]['fn'] += 1
            per_class[label]['fp'] += 1

    f1s: list[float] = []
    recalls: dict[str, float] = {}
    precisions: dict[str, float] = {}
    for label in labels:
        c = per_class[label]
        precision = c['tp'] / (c['tp'] + c['fp']) if c['tp'] + c['fp'] else 0.0
        recall = c['tp'] / c['support'] if c['support'] else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        f1s.append(f1)
        precisions[label] = precision
        recalls[label] = recall

    total = len(rows)
    covered = total - abstained
    return {
        'accuracy_all': correct / total if total else 0.0,
        'macro_f1': statistics.mean(f1s) if f1s else 0.0,
        'balanced_accuracy': statistics.mean(recalls.values()) if recalls else 0.0,
        'per_class_precision': precisions,
        'per_class_recall': recalls,
        'abstention_rate': abstained / total if total else 0.0,
        'covered_error_rate': covered_errors / covered if covered else 0.0,
        'critical_accuracy': critical_correct / critical_total if critical_total else None,
        'n': total,
    }


def dcg(relevances: list[float], k: int) -> float:
    return sum((2 ** rel - 1) / math.log2(i + 2) for i, rel in enumerate(relevances[:k]))


def reranker_metrics(rows: list[dict[str, Any]], all_scores: list[list[float]]) -> dict[str, Any]:
    ndcgs: list[float] = []
    mrrs: list[float] = []
    recalls5: list[float] = []
    recalls10: list[float] = []

    for row, scores in zip(rows, all_scores):
        docs = row['documents']
        if len(docs) != len(scores):
            raise ValueError(f"{row.get('id')}: score count does not match documents")
        ranked = [doc for _, doc in sorted(zip(scores, docs), key=lambda p: p[0], reverse=True)]
        rels = [float(doc.get('relevance', 0)) for doc in ranked]
        ideal = sorted((float(doc.get('relevance', 0)) for doc in docs), reverse=True)
        denom = dcg(ideal, 10)
        ndcgs.append(dcg(rels, 10) / denom if denom else 1.0)

        rr = 0.0
        for idx, rel in enumerate(rels[:10], 1):
            if rel > 0:
                rr = 1.0 / idx
                break
        mrrs.append(rr)

        total_relevant = sum(1 for doc in docs if float(doc.get('relevance', 0)) > 0)
        if total_relevant:
            recalls5.append(sum(1 for rel in rels[:5] if rel > 0) / total_relevant)
            recalls10.append(sum(1 for rel in rels[:10] if rel > 0) / total_relevant)

    return {
        'ndcg_at_10': statistics.mean(ndcgs) if ndcgs else 0.0,
        'mrr_at_10': statistics.mean(mrrs) if mrrs else 0.0,
        'recall_at_5': statistics.mean(recalls5) if recalls5 else 0.0,
        'recall_at_10': statistics.mean(recalls10) if recalls10 else 0.0,
        'n_queries': len(rows),
    }


def latency_summary(values: list[float]) -> dict[str, float]:
    return {
        'p50': percentile(values, 0.50),
        'p95': percentile(values, 0.95),
        'mean': statistics.mean(values) if values else 0.0,
    }


def run_classifier(args: argparse.Namespace) -> dict[str, Any]:
    rows = read_jsonl(args.dataset)
    preds: list[dict[str, Any]] = []
    latencies: list[float] = []
    for row in rows:
        started = time.perf_counter()
        result = post_json(args.endpoint, {'text': row['text']}, args.timeout)
        latencies.append((time.perf_counter() - started) * 1000)
        label = result.get('label')
        scores = result.get('scores')
        if label is None and isinstance(scores, dict) and scores:
            label = max(scores, key=scores.get)
        if label is None:
            raise ValueError('classifier response needs label or scores')
        preds.append({'label': label, 'scores': scores, 'abstain': result.get('abstain', False)})
    return {
        'task': 'classifier',
        'name': args.name,
        'metrics': classifier_metrics(rows, preds),
        'latency_ms': latency_summary(latencies),
        'health': get_json(args.health, args.timeout),
    }


def run_reranker(args: argparse.Namespace) -> dict[str, Any]:
    rows = read_jsonl(args.dataset)
    all_scores: list[list[float]] = []
    latencies: list[float] = []
    for row in rows:
        documents = [doc['text'] for doc in row['documents']]
        started = time.perf_counter()
        result = post_json(args.endpoint, {'query': row['query'], 'documents': documents}, args.timeout)
        latencies.append((time.perf_counter() - started) * 1000)
        all_scores.append([float(x) for x in result['scores']])
    return {
        'task': 'reranker',
        'name': args.name,
        'metrics': reranker_metrics(rows, all_scores),
        'latency_ms': latency_summary(latencies),
        'health': get_json(args.health, args.timeout),
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description='Benchmark FlüsterFee decision services')
    p.add_argument('task', choices=['classifier', 'reranker'])
    p.add_argument('--dataset', type=Path, required=True)
    p.add_argument('--endpoint', required=True)
    p.add_argument('--health')
    p.add_argument('--name', required=True)
    p.add_argument('--output', type=Path)
    p.add_argument('--timeout', type=float, default=30.0)
    return p


def main() -> None:
    args = build_parser().parse_args()
    result = run_classifier(args) if args.task == 'classifier' else run_reranker(args)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + '\n', encoding='utf-8')
    print(rendered)


if __name__ == '__main__':
    main()
