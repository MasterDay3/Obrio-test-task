# Task 2: answers to the grading criteria

The same five criteria as Task 1, applied to the agent assistant. Details: [`docs/task2_report.md`](../docs/task2_report.md); raw results: `results/assistant/`.

---

## Evaluation

**Fixed test set:** `data/assist_eval.jsonl`, 14 tickets in 4 languages (en, uk, es, de). Each has:
- **expected KB articles** (one ticket, "dark mode", has none on purpose);
- **expected human-required flag** (6 tickets need a human).

**Automatic checks per ticket** (`eval/run_assist_eval.py`):

| Check | How it is measured |
|---|---|
| Retrieval hit | An expected article is among the retrieved passages |
| Citation validity | Quotes that really appear in the cited article ÷ all quotes proposed |
| All tones present / short is short | 3 non-empty replies; "short" ≤ 60 words |
| Tones distinct | Word overlap (Jaccard) between any two variants ≤ 0.6 |
| Language match | Reply script matches the ticket (Cyrillic for uk/ru, Latin otherwise) |
| Human flag | `human_required` equals the label |
| Grounding | No number missing from the passages; no internal agent rule; no "already done" claim |

**Table input → expected → actual → pass/fail** (final run, draft_v4 + Gemini Flash-Lite; full file `results/assistant/draft_v4__gemini-flash-lite.md`):

| id | lang | expected → retrieved | citations ok/proposed | tones distinct | lang | human exp→act |
|---|---|---|---|---|---|---|
| T01 | en | double-charge → double-charge ✅ | 3/3 | ✅ | ✅ | -→- ✅ |
| T03 | en | trial-terms, refund-policy → same ✅ | 3/3 | ✅ | ✅ | -→- ✅ |
| T05 | en | login-magic-link ✅ | 6/6 | ✅ | ✅ | -→- ✅ |
| T06 | en | expert-conduct ✅ | 3/3 | ✅ | ✅ | H→H ✅ |
| T09 | en | account-deletion ✅ | 3/3 | ✅ | ✅ | H→H ✅ |
| T11 | en | reading-disclaimer ✅ | 6/6 | ✅ | ✅ | H→H ✅ |
| T18 | uk | double-charge, refund-policy ✅ | 3/3 | ✅ | ✅ | -→- ✅ |
| T21 | es | edit-birth-data ✅ | 6/6 | ✅ | ✅ | -→- ✅ |
| T22 | de | double-charge ✅ | 3/3 | ✅ | ✅ | -→- ✅ |
| T23 | uk | app-crash ✅ | 3/3 | ✅ | ✅ | -→- ✅ |
| T24 | en | how-horoscopes-work ✅ | 6/6 | ✅ | ✅ | -→- ✅ |
| T30 | en | expert-conduct ✅ | 3/3 | ✅ | ✅ | H→H ✅ |
| T40 | en | minor-purchases ✅ | 3/3 | ✅ | ✅ | H→H ✅ |
| T08 | en | (none) → loosely related passages ❌ | 0/0 | ✅ | ✅ | H→H ✅ (model set `kb_gap`, so the agent is told to write it) |

**Overall (final setup):**
- retrieval 92.9% (the only miss is the intended no-KB ticket, handled correctly);
- citations 100% real;
- tones present, short and distinct: 100%;
- language 100%;
- human flags 100%;
- 0 tickets with invented numbers, internal-rule leaks or "already done" claims.

**Error analysis across prompt versions:**

| Run | Tones distinct | Language | Human flag | Invented numbers | Internal-rule leaks | Claimed actions |
|---|---|---|---|---|---|---|
| draft_v1, Gemini | **42.9%** | 100% | 85.7%* | 0 | 1 | 1 |
| draft_v1, gpt-oss-120b | 100% | 100% | 100% | 2 | **5** | **3** |
| draft_v2, gpt-oss-120b | 85.7%† | **85.7%** | 100% | 1 | 1 | 0 |
| draft_v3, Gemini | 100% | **85.7%** | 85.7%* | 1 | 0 | 2 |
| **draft_v4, Gemini (final)** | **100%** | **100%** | **100%** | **0** | **0** | **0** |

\* affected by Gemini rate limits. † 2 tickets failed on the Groq per-minute limit.

Main failure modes found and fixed:
1. near-identical tones (fixed with measurable specs);
2. English replies to Ukrainian tickets, caused by an English greeting template in the prompt (localised greetings + one automatic re-ask);
3. internal agent rules and wrong numbers in customer replies, even with valid citations (prompt rules + code checks).

*Caveat:* single runs on 14 tickets; outputs vary between runs (a live v4 run once wrote "we confirmed…" in Ukrainian, which the check flagged).

---

## Comparison of models

| Model | Drafting quality (best run) | Avg latency | Cost per ticket | Verdict |
|---|---|---|---|---|
| **Gemini 3.5 Flash-Lite** | draft_v4: **every check passed** | 3.6 s | $0.0029 | **Chosen for drafting** |
| gpt-oss-120b (Groq) | draft_v1: tones good, but internal-rule leaks in 5/14, invented numbers in 2/14, claimed actions in 3/14 | 3.6 s | $0.0014 | Classifier primary; drafting fallback. v4 not tested on it (Groq daily limit) |
| gpt-oss-20b (Groq) | Not used for drafting | — | — | Last fallback |

**Why each task uses a different primary model:**
- **gpt-oss-120b** measured best at **classification** (Task 1).
- **Gemini Flash-Lite** measured best at **drafting**: it follows tone and language specs well and does not leak internal rules with v4.

The assistant therefore drafts with Gemini (`assistant_chain`) and classifies with gpt-oss-120b (`fallback_chain`). Each chain falls back to the other provider. gpt-oss-120b is half the price per ticket, so re-testing it with draft_v4 is the first next step.

---

## Failure handling

The same core as Task 1 (`core/llm.py`, `core/json_guard.py`):
- timeout → retry with backoff → next model;
- 429 per minute → wait for `Retry-After` → next model;
- **429 daily quota → straight to the next provider**;
- invalid JSON → one repair retry → next model;
- empty response → next model.

Assistant-specific:

| Situation | What happens |
|---|---|
| Empty ticket | No model calls; "ask the customer to describe the issue" |
| Very long ticket | Head + tail kept (6,000 characters) |
| Analysis step fails | Summary = first 300 characters, search query = ticket text; drafting continues in the ticket's own language |
| Drafting fails | Summary, classification and KB passages still shown; banner "AI drafts unavailable: write the reply manually" |
| A tone missing / returned as a string | Missing → empty card with a warning; string → accepted as `{text}` |
| Reply in the wrong language | One targeted re-ask; if it fails too, the first draft is shown with a warning |
| Invented quote / number / internal rule / claimed action | Quote removed + banner; the others shown as warnings on that draft |
| All providers down | "AI unavailable"; the page still shows retrieved KB passages |

**Seen for real:**
- Groq per-minute limits;
- the Groq **daily** limit, which made a whole eval run come back as "write manually" with the banner (`results/assistant/failed_tpd__*`), with nothing breaking;
- the Gemini daily quota;
- in the live UI test, an automatic fallover from Groq to Gemini ("2 recovered errors").

---

## Cost

**Price of one ticket (measured):** **$0.0029** on Gemini Flash-Lite with draft_v4; $0.0014 on gpt-oss-120b with draft_v1. Each ticket needs 3–4 model calls: classify, analyze, draft, and a re-ask only when the language is wrong.

**Forecast for 10k tickets/month:** **~$29** with Gemini drafting, ~$14 with gpt-oss-120b drafting. This already includes the classification call made inside the assistant, so if every ticket goes through the assistant, the whole system costs about **$29 per 10k tickets** (classifier-only routing is ~$4). If drafts save an agent even one minute per ticket, that is ~170 agent-hours a month.

**How to cut cost without losing quality:**
1. **Merge the classify and analyze calls** into one: ≈ −30% tokens.
2. **Reuse the classification made at intake** (Task 1) instead of classifying again in the assistant.
3. **Generate drafts on demand,** when the agent opens the ticket, not for every incoming ticket (many are closed by automation or are spam).
4. **Provider prompt caching** of the static system prompts: Gemini cached input costs 10% of the normal price, Groq applies 50% off automatically.
5. **A cheaper drafting model** (gpt-oss-120b at half the price) once draft_v4 passes the same eval on it.

---

## Caching

**Needed?** Partly. Tickets are mostly unique, so a response cache rarely hits. It helps with duplicates, retries and repeat runs. The BM25 index cache and provider prompt caching matter more.

| What is cached | Key | Invalidated when |
|---|---|---|
| Full assistant answer (SQLite) | analyze prompt + draft prompt + classifier prompt (content) + **KB content hash** + drafting model + classifier model + normalized ticket | Any prompt edit, **any KB edit** (a policy change must invalidate drafts), a model change, or the 7-day TTL |
| BM25 index of the KB | KB content hash | Any article changes; the index is rebuilt automatically |
| Static prompt prefix at the provider | Provider-side | Prompt change |

**Deliberately not cached:**
- answers produced on a fallback path or with errors, so a degraded answer never becomes "sticky";
- anything per customer beyond the ticket text itself. The key is the full normalized text, so a cross-customer hit only happens for an identical message, and the drafts contain no personal data beyond what is in that text.

**Why the KB hash is in the key:** if the refund window changes from 14 to 30 days, every cached draft that mentions it must disappear at once, not after the TTL.
