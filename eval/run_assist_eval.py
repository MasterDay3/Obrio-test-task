"""Evaluate the agent assistant on a labeled subset of tickets.

    python -m eval.run_assist_eval --model gemini-flash-lite --sleep 6

Checks per ticket: retrieval hit (expected article among passages), citation validity (quotes that survived
verification vs invented ones), all three tones present, "short" really short, tones actually different,
reply language matches the ticket, human-required flag matches the label.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import time
from pathlib import Path

import assistant.assist as assist_mod
from assistant.assist import TONES, assist, script_matches
from core.llm import make_client
from eval.run_classifier_eval import load_tickets, write_csv

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "assist_eval.jsonl"
OUT = ROOT / "results" / "assistant"
SHORT_MAX_WORDS = 60
MAX_TONE_SIMILARITY = 0.6  # word-set Jaccard; above this two variants are near-duplicates


def words(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.lower()))


def jaccard(a: str, b: str) -> float:
    wa, wb = words(a), words(b)
    return len(wa & wb) / len(wa | wb) if wa | wb else 1.0


def evaluate(model: str, sleep_s: float) -> dict:
    tickets = {t["id"]: t for t in load_tickets()}
    labels = [json.loads(l) for l in DATA.read_text().splitlines() if l.strip()]
    chain = [make_client(model)]
    rows = []
    for lab in labels:
        t = tickets[lab["ticket_id"]]
        r = assist(t["text"], chain)
        got = [p.article_id for p in r.passages]
        replies = [r.replies.get(tone) for tone in TONES]
        texts = [rep.text if rep else "" for rep in replies]
        proposed = sum(len(rep.citations) + rep.removed_citations for rep in replies if rep)
        verified = sum(len(rep.citations) for rep in replies if rep)
        sims = [jaccard(texts[i], texts[j]) for i in range(3) for j in range(i + 1, 3)] if all(texts) else [1.0]
        expected = lab["expected_articles"]
        rows.append({
            "id": t["id"], "tags": ",".join(t["tags"]), "lang": t["language"],
            "expected_articles": expected, "retrieved": got,
            "retrieval_hit": (not expected and not got) or bool(set(expected) & set(got)),
            "citations_proposed": proposed, "citations_verified": verified,
            "unsupported_numbers": sorted({n for rep in replies if rep for n in rep.unsupported_numbers}),
            "internal_leaks": sorted({x for rep in replies if rep for x in rep.internal_leaks}),
            "claimed_actions": sorted({x for rep in replies if rep for x in rep.claimed_actions}),
            "kb_gap": r.kb_gap,
            "detected_language": r.language,
            "all_tones": all(texts), "short_words": len(texts[2].split()),
            "short_ok": 0 < len(texts[2].split()) <= SHORT_MAX_WORDS,
            "max_tone_similarity": round(max(sims), 2), "tones_distinct": max(sims) <= MAX_TONE_SIMILARITY,
            "language_ok": all(script_matches(t["language"], x) for x in texts if x),
            "exp_human": lab["expected_human_required"], "act_human": r.human_required,
            "human_ok": lab["expected_human_required"] == r.human_required,
            "human_reasons": r.human_reasons, "summary": r.summary,
            "formal": texts[0], "empathetic": texts[1], "short": texts[2],
            "errors": r.errors, "cost": r.cost_usd, "latency_s": r.latency_s,
        })
        x = rows[-1]
        print(f"  {t['id']} hit={x['retrieval_hit']} cites={verified}/{proposed} distinct={x['tones_distinct']} "
              f"lang={x['language_ok']} nums={x['unsupported_numbers']} leaks={x['internal_leaks']} "
              f"human={x['exp_human']}->{x['act_human']} {[e[:90] for e in r.errors[:1]]}")
        if sleep_s:
            time.sleep(sleep_s)

    n = len(rows)
    pct = lambda k: round(100 * sum(1 for r in rows if r[k]) / n, 1)
    proposed = sum(r["citations_proposed"] for r in rows)
    metrics = {
        "tickets": n, "retrieval_hit_rate": pct("retrieval_hit"),
        "citation_validity": round(100 * sum(r["citations_verified"] for r in rows) / proposed, 1) if proposed else None,
        "invented_citations": proposed - sum(r["citations_verified"] for r in rows),
        "all_tones_present": pct("all_tones"), "short_within_limit": pct("short_ok"),
        "tones_distinct": pct("tones_distinct"), "language_match": pct("language_ok"),
        "human_flag_accuracy": pct("human_ok"),
        "tickets_with_unsupported_numbers": sum(1 for r in rows if r["unsupported_numbers"]),
        "tickets_with_internal_leaks": sum(1 for r in rows if r["internal_leaks"]),
        "tickets_with_claimed_actions": sum(1 for r in rows if r["claimed_actions"]),
        "no_kb_answer_detected": sum(1 for r, lab in zip(rows, labels) if not lab["expected_articles"] and
                                     (r["kb_gap"] or not r["retrieved"])),
        "failed_tickets": sum(1 for r in rows if not r["all_tones"] and r["errors"]),
        "latency_avg_s": round(statistics.mean(r["latency_s"] for r in rows), 2),
        "cost_per_ticket_usd": round(sum(r["cost"] for r in rows) / n, 6),
    }
    return {"model": model, "prompts": {"analyze": assist_mod.ANALYZE_PROMPT, "draft": assist_mod.DRAFT_PROMPT,
                                        "classifier": assist_mod.CLASSIFIER_PROMPT},
            "metrics": metrics, "rows": rows}


def write(result: dict) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    stem = f"{result['prompts']['draft']}__{result['model']}"
    (OUT / f"{stem}.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))
    write_csv(OUT / f"{stem}.csv", result["rows"])
    yes = lambda b: "✅" if b else "❌"
    lines = [f"# Assistant eval: draft prompt `{result['prompts']['draft']}`, model `{result['model']}`", "",
             "| metric | value |", "|---|---|", *[f"| {k} | {v} |" for k, v in result["metrics"].items()], "",
             "| id | lang | expected → retrieved | citations ok/proposed | tones distinct (max sim) | lang | human exp→act |",
             "|---|---|---|---|---|---|---|"]
    for r in result["rows"]:
        lines.append(f"| {r['id']} | {r['lang']} | {', '.join(r['expected_articles']) or '(none)'} → "
                     f"{', '.join(dict.fromkeys(r['retrieved'])) or '(none)'} {yes(r['retrieval_hit'])} | "
                     f"{r['citations_verified']}/{r['citations_proposed']} | {yes(r['tones_distinct'])} ({r['max_tone_similarity']}) | "
                     f"{yes(r['language_ok'])} | {'H' if r['exp_human'] else '-'}→{'H' if r['act_human'] else '-'} {yes(r['human_ok'])} |")
    path = OUT / f"{stem}.md"
    path.write_text("\n".join(lines) + "\n")
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="gemini-flash-lite")
    ap.add_argument("--sleep", type=float, default=0.0)
    ap.add_argument("--draft-prompt", default=None, help="e.g. draft_v1 to reproduce the first version")
    args = ap.parse_args()
    if args.draft_prompt:
        assist_mod.DRAFT_PROMPT = args.draft_prompt
    result = evaluate(args.model, args.sleep)
    print(f"-> {write(result)}\n{result['metrics']}")


if __name__ == "__main__":
    main()
