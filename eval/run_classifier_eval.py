"""Run the labeled ticket set through (prompt version x model) and write per-run reports + a summary table.

    uv run python -m eval.run_classifier_eval --models gemini-flash-lite --prompts v1
    uv run python -m eval.run_classifier_eval --models all --prompts v1 v2 v3 --sleep 4
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import time
from pathlib import Path

from classifier.classify import classify
from classifier.schema import Priority
from core.cache import Cache
from core.llm import LLMError, load_config, make_client

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "tickets_eval.jsonl"
# "holdout" was written after prompt tuning and never used to change a prompt: it checks for overfitting.
DATASETS = {"main": DATA, "holdout": ROOT / "data" / "tickets_holdout.jsonl"}
RUNS = ROOT / "results" / "classifier" / "runs"
_PRI = [p.value for p in Priority]


def load_tickets(path: Path = DATA) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def score(rows: list[dict]) -> dict:
    n = len(rows)
    called = [r for r in rows if r["model"]]
    lat = sorted(r["latency_s"] for r in called) or [0.0]
    gold_h = [r for r in rows if r["exp_human"]]
    pred_h = [r for r in rows if r["act_human"]]
    tp = sum(1 for r in rows if r["exp_human"] and r["act_human"])
    pct = lambda k: round(100 * sum(1 for r in rows if r[k]) / n, 1)
    return {
        "tickets": n,
        "category_acc": pct("cat_ok"),
        "priority_acc": pct("pri_ok"),
        "priority_within_1": pct("pri_near"),
        "pass_rate": pct("pass"),
        "raw_category_acc": pct("raw_cat_ok"),
        "human_recall": round(100 * tp / len(gold_h), 1) if gold_h else None,
        "human_precision": round(100 * tp / len(pred_h), 1) if pred_h else None,
        "raw_human_recall": round(100 * sum(1 for r in gold_h if r["raw_human"]) / len(gold_h), 1) if gold_h else None,
        "invalid_or_failed": sum(1 for r in rows if r["errors"]),
        "unclassified": sum(1 for r in rows if r["act_cat"] == "unclassified"),
        "latency_avg_s": round(statistics.mean(lat), 2),
        "latency_p95_s": round(lat[min(len(lat) - 1, int(0.95 * len(lat)))], 2),
        "avg_input_tokens": round(statistics.mean([r["in_tok"] for r in called]), 0) if called else 0,
        "avg_output_tokens": round(statistics.mean([r["out_tok"] for r in called]), 0) if called else 0,
        "avg_cached_input_tokens": round(statistics.mean([r.get("cached_tok", 0) for r in called]), 0) if called else 0,
        "cost_total_usd": round(sum(r["cost"] for r in rows), 6),
        "cost_per_ticket_usd": round(sum(r["cost"] for r in rows) / n, 7),
    }


def run(model: str, prompt: str, tickets: list[dict], cache: Cache | None, use_rules: bool, sleep_s: float,
        dataset: str = "main") -> dict:
    chain = [make_client(model)]  # no fallback: we measure the model itself
    rows = []
    for t in tickets:
        r = classify(t["text"], chain, prompt, cache=cache, use_rules=use_rules)
        c, raw = r.classification, r.raw_classification or r.classification
        exp_p, act_p = _PRI.index(t["expected_priority"]), _PRI.index(c.priority.value)
        cat_ok = c.category.value == t["expected_category"]
        rows.append({
            "id": t["id"], "tags": ",".join(t["tags"]), "text": t["text"],
            "exp_cat": t["expected_category"], "act_cat": c.category.value,
            "exp_pri": t["expected_priority"], "act_pri": c.priority.value,
            "exp_human": t["expected_needs_human"], "act_human": c.needs_human, "raw_human": raw.needs_human,
            "cat_ok": cat_ok, "pri_ok": exp_p == act_p, "pri_near": abs(exp_p - act_p) <= 1,
            "pass": cat_ok and exp_p == act_p, "raw_cat_ok": raw.category.value == t["expected_category"],
            "secondary": [s.value for s in c.secondary_categories], "lang": c.language,
            "next_step": c.next_step, "confidence": c.confidence, "reason": c.reason,
            "rule_hits": r.rule_hits, "model": r.model, "cached": r.cached, "errors": r.errors,
            "latency_s": r.latency_s, "cost": r.cost_usd, "in_tok": r.input_tokens, "out_tok": r.output_tokens, "cached_tok": r.cached_input_tokens,
        })
        status = "ok " if rows[-1]["pass"] else "XX "
        print(f"  {status}{t['id']} exp={t['expected_category']}/{t['expected_priority']} "
              f"got={c.category.value}/{c.priority.value} {'(cached)' if r.cached else ''}{r.errors[:1] or ''}")
        if sleep_s and r.model and not r.cached:
            time.sleep(sleep_s)  # stay under free-tier RPM limits
    if all(r["errors"] for r in rows if r["text"].strip()):
        raise LLMError(f"{model}: every call failed ({rows[0]['errors'][:1]}); is the provider reachable?")
    return {"model": model, "prompt": prompt, "rules": use_rules, "dataset": dataset, "metrics": score(rows), "rows": rows}


def write_csv(path: Path, rows: list[dict]) -> None:
    """utf-8-sig so Excel / Google Sheets show Cyrillic and emoji correctly; lists are joined with '; '."""
    if not rows:
        return
    flat = [{k: "; ".join(map(str, v)) if isinstance(v, list) else v for k, v in r.items()} for r in rows]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(flat[0]))
        writer.writeheader()
        writer.writerows(flat)


def write_run(result: dict) -> Path:
    suffix = ("" if result["rules"] else "__norules") + ("" if result.get("dataset", "main") == "main" else f"__{result['dataset']}")
    stem = f"{result['prompt']}__{result['model']}{suffix}"
    RUNS.mkdir(parents=True, exist_ok=True)
    (RUNS / f"{stem}.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))
    write_csv(RUNS / f"{stem}.csv", result["rows"])

    yes = lambda b: "✅" if b else "❌"
    lines = [f"# Classifier eval — prompt `{result['prompt']}`, model `{result['model']}`, rules {'on' if result['rules'] else 'off'}",
             "", "## Metrics", "", "| metric | value |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in result["metrics"].items()]
    lines += ["", "## Per ticket", "",
              "| id | tags | ticket | expected | actual | cat | pri | human exp→act | rules |",
              "|---|---|---|---|---|---|---|---|---|"]
    for r in result["rows"]:
        snippet = (r["text"][:70] + "…" if len(r["text"]) > 70 else r["text"]).replace("|", "/").replace("\n", " ") or "(empty)"
        lines.append(f"| {r['id']} | {r['tags']} | {snippet} | {r['exp_cat']} / {r['exp_pri']} | "
                     f"{r['act_cat']} / {r['act_pri']} | {yes(r['cat_ok'])} | {yes(r['pri_ok'])} | "
                     f"{'H' if r['exp_human'] else '-'}→{'H' if r['act_human'] else '-'} | {', '.join(r['rule_hits'])} |")
    path = RUNS / f"{stem}.md"
    path.write_text("\n".join(lines) + "\n")
    return path


def write_summary() -> Path:
    RUNS.mkdir(parents=True, exist_ok=True)
    runs = sorted((json.loads(p.read_text()) for p in RUNS.glob("*.json")),
                  key=lambda r: (r.get("dataset", "main"), r["prompt"], r["model"], not r["rules"]))
    cols = ["category_acc", "priority_acc", "priority_within_1", "pass_rate", "human_recall", "human_precision",
            "invalid_or_failed", "latency_avg_s", "latency_p95_s", "cost_per_ticket_usd"]
    lines = ["# Classifier eval summary", "", "| dataset | prompt | model | rules | " + " | ".join(cols) + " |",
             "|---|---|---|---|" + "---|" * len(cols)]
    for r in runs:
        m = r["metrics"]
        lines.append(f"| {r.get('dataset', 'main')} | {r['prompt']} | {r['model']} | {'on' if r['rules'] else 'off'} | "
                     + " | ".join(str(m[c]) for c in cols) + " |")
    write_csv(RUNS.parent / "summary.csv",
              [{"dataset": r.get("dataset", "main"), "prompt": r["prompt"], "model": r["model"], "rules": r["rules"], **r["metrics"]} for r in runs])
    path = RUNS.parent / "summary.md"
    path.write_text("\n".join(lines) + "\n")
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", default=["gemini-flash-lite"], help="model aliases or 'all'")
    ap.add_argument("--prompts", nargs="+", default=["v1"])
    ap.add_argument("--no-rules", action="store_true")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--sleep", type=float, default=0.0, help="seconds between model calls (free-tier RPM)")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dataset", choices=list(DATASETS), default="main")
    args = ap.parse_args()

    models = list(load_config()["models"]) if args.models == ["all"] else args.models
    tickets = load_tickets(DATASETS[args.dataset])[: args.limit or None]
    cache = None if args.no_cache else Cache(ROOT / "results" / "eval_cache.sqlite")
    for prompt in args.prompts:
        for model in models:
            print(f"== prompt {prompt} / model {model}")
            try:
                result = run(model, prompt, tickets, cache, not args.no_rules, args.sleep, args.dataset)
            except LLMError as exc:
                print(f"  skipped: {exc}")
                continue
            print(f"  -> {write_run(result)}  {result['metrics']}")
    print(f"summary: {write_summary()}")


if __name__ == "__main__":
    main()
