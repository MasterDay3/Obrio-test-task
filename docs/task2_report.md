# Task 2: AI assistant for support agents

The agent pastes a ticket and gets:
- a **short summary** and what the customer wants;
- **three reply drafts** (formal, empathetic, short) in the customer's language;
- **citations from the knowledge base**: exact quotes linked to the article, checked in code;
- the Task 1 classification (category, priority, team, next step);
- a **red "human decision required" banner** with reasons when AI drafts must not be sent as-is.

```bash
source .venv/bin/activate
uvicorn app.main:app            # http://localhost:8000
python -m eval.run_assist_eval --model gemini-flash-lite --sleep 8
```

![Assistant UI](img/assistant_ui.png)

*A $180 purchase by a minor with a bank-dispute threat. The model chain fell over from Groq (daily limit reached) to Gemini automatically. Four reasons block the drafts, the copy buttons stay locked until the agent ticks "I reviewed the case", and each draft shows its verified KB quote.*

---

## 1. Results at a glance (final setup: draft prompt v4, Gemini 3.5 Flash-Lite)

14 labelled tickets in `data/assist_eval.jsonl`, in 4 languages (en, uk, es, de), including 6 that need a human and one with no KB answer.

| Check | Result |
|---|---|
| Expected KB article retrieved | 92.9% (13/14; the miss is "dark mode", which has no article, and the system flags this correctly) |
| Citations that are real quotes from the cited article | **100%** (0 invented) |
| All three tones present; "short" ≤ 60 words | 100% / 100% |
| Tones actually different (word overlap ≤ 0.6) | 100% |
| Reply in the customer's language | **100%** |
| Human flag matches label | **100%** |
| Replies with a number not in the KB passages | 0 tickets |
| Replies leaking internal agent rules | 0 tickets |
| Replies claiming an action is already done ("refund processed") | 0 tickets |
| Cost / latency per ticket | $0.0029 / 3.6 s (3–4 model calls incl. classification) |

---

## 2. Architecture

```
ticket ──┬─► classify (Task 1, prompt v3 + rules) ──────────────► category, priority, rule hits
         │                                     (parallel threads)
         └─► analyze: summary, language, customer_wants,
                      English search query, candidate articles (from the KB title list)
                           │
                           ▼
              BM25 over KB sections (+ boost for model-picked articles)  ──► top-4 passages
                           │
                           ▼
              draft: 3 tones + citations + kb_gap + agent_note   (one call, JSON)
                           │
                           ▼
              code checks: quotes exist in KB · numbers exist in passages/ticket ·
                           no internal agent rules · no "already done" claims ·
                           right language (one re-ask if not)
                           │
                           ▼
              UI: summary, chips, 3 reply cards with warnings and citations, internal agent note,
                  KB passages, red banner + locked copy buttons when a human must decide
```

| Component | File |
|---|---|
| Knowledge base: 18 fictional articles, 42 sections, with concrete numbers and internal agent rules mixed in, as real KBs have | `assistant/kb/*.md` |
| Retrieval (BM25, domain stopwords, KB content hash) | `assistant/retrieval.py` |
| Pipeline, verification, human-judgement reasons | `assistant/assist.py` |
| Prompts | `assistant/prompts/analyze_v1.md`, `draft_v1.md` → `draft_v4.md` |
| Web UI and API | `app/main.py`, `app/templates/index.html` |
| Eval | `eval/run_assist_eval.py` → `results/assistant/*.md/.csv/.json` |

The model chain for the assistant is Gemini Flash-Lite → gpt-oss-120b → gpt-oss-20b (`assistant_chain` in `config/models.yaml`). Gemini comes first here, unlike the classifier, because it is the only model that passed every drafting check with v4. The classification shown in the assistant still uses the classifier's own chain (gpt-oss-120b first), so each job runs on the model that measured best for it. The gpt-oss-120b drafts tested (v1) leaked internal rules. v4 could not be tested on gpt-oss-120b because the Groq free-tier daily token limit was exhausted.

---

## 3. Retrieval: why this approach

**Choice:** keyword search (BM25) over KB **sections**, with three additions that the eval showed were needed.
1. **The model writes the search query in English, using KB vocabulary.** Tickets arrive in Ukrainian, Spanish, German or surzhyk; the KB is in English. Rewriting the query makes a lexical index work for all languages without a multilingual embedding model.
2. **The model also picks candidate articles from the list of KB titles**, and those get a score boost. Pure BM25 missed synonyms: the ticket said "child", the article said "minor". The boost applies only when the article shares at least one word with the query, because without that rule "dark mode please" pulled in refund-policy.
3. **Domain stopwords** ("request", "help", "issue", "app", "nebula"…). These appear in almost every ticket and matched random articles; "feature request" matched the refund policy only through "request".

Plus a **relevance verdict from the model**: the draft step returns `kb_gap: true` when none of the passages answers the question. That triggers "No relevant KB article: write the answer yourself" even when BM25 found loosely related text. A threshold on keyword scores could not make that call reliably.

**Why not embeddings / a vector database?**
- The KB is small (42 sections), so BM25 is instant, needs no infrastructure, and its results are explainable.
- The quality limit was synonyms and languages, and the two LLM steps above fix that more cheaply.
- For a real KB with thousands of articles and frequent updates, I would add a multilingual embedding index and do hybrid retrieval (BM25 + vectors + a reranker). The `retrieve()` interface would stay the same.

**Why sections, not whole articles:** citations must be short, exact and checkable, and the agent sees exactly which paragraph supports each claim.

---

## 4. Prompt design for different tones

The draft prompt evolved through four versions. Each was run on the same 14 tickets.

| Version | Change | What the eval showed |
|---|---|---|
| **draft_v1** | "Write three variants: formal, empathetic, short", use the KB, cite | Gemini: tones near-identical (only **43%** distinct), "short" often as long as the others, each tone returned as a plain string instead of `{text, citations}` (repair retry needed). gpt-oss-120b: tones fine, but **5 of 14 tickets leaked internal agent rules** and 2 had invented numbers (the bad-output example below) |
| **draft_v2** | Explicit **tone specs** (greeting/sign-off, word ranges, "short ≤ 40 words, no greeting"), "do not reuse sentences between variants", paraphrase instead of pasting KB text, internal rules go to `agent_note`, exact JSON shape | Tones became distinct and the JSON valid, but **Ukrainian tickets got English replies** (language match fell to 86%), and "admin panel" still leaked |
| **draft_v3** | The language is named in the request ("Ukrainian", not "uk") and repeated at the end; internal-only facts listed by name ("$100 approval limit", "admin panel"); "copy numbers exactly, if it says 5–10 days do not write 5–7" | Leaks 0, invented numbers fixed, but Ukrainian tickets **still** got English formal and empathetic replies |
| **draft_v4** | Greetings and sign-offs **in the customer's language**, with examples in English and Ukrainian | All checks pass (section 1). **Final.** |
| draft_v5 (tried, not adopted) | v4 + "the agent sends this before acting: never say an action already happened, use the future tense". Added after a live v4 reply said "Ми підтвердили…" ("we confirmed…") | 1 ticket with a leak ("exceeds standard agent approval limits") and 1 with a claimed action ("we have escalated"), vs 0/0 for v4. Single runs on 14 tickets, so this is noise, not an improvement. Kept v4; the code checks catch both cases and warn the agent |

How the tones are produced:
- **One call returns all three variants** in a structured object (`{formal, empathetic, short}`). One call is cheaper and faster than three, and the model sees the variants together, so it can deliberately make them different.
- **Each tone has a measurable spec**, not an adjective:
  - formal: no contractions, emoji or exclamation marks; 70–130 words;
  - empathetic: the first sentence acknowledges the customer's *specific* situation, at most one apology;
  - short: ≤ 40 words, no greeting or sign-off.
- **The facts are the same, the wording is different.** "Same facts and next action, in clearly different styles. Do not reuse sentences between variants." This keeps the agent's choice purely about tone and never about which variant is correct.
- **Distinctness is checked in the eval** by word-set overlap between variants (Jaccard ≤ 0.6). This crude metric caught the v1 Gemini failure (overlap 0.81–0.83).

**What did not work the first time:**
1. **Adjectives alone** ("formal / empathetic / short") gave three versions of the same text with different openings. Explicit specs were needed.
2. **Language.** First an ISO code alone ("uk") was ignored. Then the tone spec itself forced English: "Greeting 'Hello,' and sign-off 'Best regards, Nebula Support'". The model copied the English template and wrote the whole reply in English. The fix was localising the greeting (v4), plus a code check that re-asks once if a reply is in the wrong script.
3. **JSON shape.** The model returned `"formal": "text…"` instead of an object. The fix was an explicit schema in the prompt, plus a validator that accepts a plain string as `{text}`.

---

## 5. A concrete example of bad AI output, and the fix

**Ticket T18 (Ukrainian):** "I was charged twice for the subscription, please return the extra charge." Draft v1 on gpt-oss-120b, formal reply (translated):

> "We found two identical charges for the same period… We will confirm both transaction IDs **in the admin panel** and issue a full refund of the duplicate. **This refund is not subject to the $100 limit.** Expect the money **within 5–7 business days**."

Every citation for this reply was a real quote, so a citation check alone passed it. Three things were wrong anyway:
1. **Invented number.** The KB says refunds take **5–10** business days. "5–7" would set a promise support cannot keep.
2. **Internal rule leaked:** "not subject to the $100 limit" is the *agent* approval limit. The customer should never see it, and it invites "then refund me $300".
3. **Internal tool leaked:** "admin panel".

The same pattern appeared in 5 of 14 tickets on that run, for example "because the amount exceeds the $100 limit that agents can approve" (T40).

**Fixes, in layers:**
- **Prompt (v3/v4):** internal facts are listed by name as agent-only (approval limits, admin tools, what agents may or may not do) and go to `agent_note`; numbers are copied exactly or left out.
- **Code checks on every draft (`assistant/assist.py`, `_verify`):**
  - *Number grounding:* every number or range in a reply ("5-7", "48", "$150") must appear in the retrieved passages or in the ticket. Ranges are compared as a whole, so "5–7" does not pass just because a "7" exists somewhere else. Unsupported numbers show as a warning on that reply.
  - *Internal-rule detector:* phrases like "admin panel", "agents can…", "approval limit", "ліміт" show as a warning.
  - *Citation check:* each quote must appear in the cited article; invented quotes are removed, and the human banner is raised.
  - *Claimed-action detector* (added in the second review): phrases like "we have processed / refunded / escalated", "is being processed" or "I can approve" show as a warning ("send only after you have actually done it"). v1 drafts said "I can approve the $59.99 refund right away… Refund is being processed now" (T03): an agent copying that sends a false promise.
- **Result:** with v4 these warnings fired on 0 of 14 eval tickets. They are still needed: in a later live run the same v4 setup wrote "Ми підтвердили наявність подвійного списання" ("we confirmed the double charge") in a Ukrainian reply, and v5 runs produced one leak and one claimed action. Model output varies between runs; the checks catch it every time. In the v3 run the number check correctly caught T24, where the model wrote "5–10 business days": a true figure, but from an article that was **not** retrieved for that ticket, so it was not backed by the passages the agent sees.

---

## 6. Where the agent must decide (human judgement required)

These scenarios show the red banner. The copy buttons stay locked until the agent ticks "I reviewed the case and will decide the outcome myself".

| Scenario | Why a human must decide | How it is detected |
|---|---|---|
| **Self-harm or threats of violence** | A template reply to a person in crisis can do real harm; needs trained staff and local crisis resources | Classifier `safety_crisis` + multilingual keyword rules (forced, never overridden) |
| **Chargeback, bank dispute, lawyer, regulator** | Every word can become evidence; refunding during a dispute can pay twice; Legal owns the reply | Rules (`chargeback`, `open a dispute`, `call my bank`, `FTC`, `lawyer`…) + category `legal_privacy` |
| **Personal-data requests (GDPR/CCPA, deletion, data copy)** | Legal deadlines, identity verification, Privacy team only | Rules + category |
| **Possible account takeover** | Acting on a chat claim could hand the account to an attacker | Rules (`someone logged in`, `hacked`…) |
| **Refund over $100, refund involving a minor** | Policy requires Billing-specialist approval; fraud risk | Amount parser (handles `$1,299`, `€1.299,00`, `2 000 USD`, `грн`) + minor patterns |
| **Expert misconduct** (rudeness, off-platform contact, harmful advice) | Needs a transcript review and fairness to the expert; no outcome may be promised | Classifier `expert_complaint` with `needs_human` |
| **Repeat contact / escalation** | Earlier answers failed; the agent must read the history | Rules (`third time`, `already wrote`…) |
| **Prompt injection in the ticket** | Adversarial content; drafts may be manipulated | Rules (`ignore previous instructions`, `you are now`…) |
| **No relevant KB article** | The drafts cannot be checked against policy | Empty retrieval or `kb_gap` from the model |
| **A draft cited text that does not exist in the KB** | Possible invented policy | Citation check |
| **AI unavailable / unclassified / low confidence** | Nothing reliable to send | Fallback path, confidence < 0.6 |

**How it is marked in the interface (implemented):**
1. **Blocking banner.** A red banner at the top: "Human decision required: do not send an AI draft as-is", with one plain-language reason per trigger, for example "Amount above $100: refund requires Billing specialist approval".
2. **Locked actions.** The "Copy" buttons are disabled until the agent ticks the confirmation checkbox. A draft cannot be sent by habit.
3. **Per-draft warnings, non-blocking.** Amber notes on individual drafts: invented citation removed, number not in KB, possible internal rule, action stated as already done, wrong language, no verified citation.
4. **Internal note.** A separate grey card "Internal note for the agent (do not send)" holds what the model moved out of the customer text (approval limits, which team to escalate to).
5. **Priority chip.** P1/P2 shown in red/amber next to category, team and sentiment.
6. **Evidence.** The KB passages used are listed with links to the article (`/kb/{id}#section`), so the agent can check any claim in one click.

In a production helpdesk the same `human_required` + reasons would also move the ticket to a "Needs review" queue and disable macros (see Task 1, section 7).

---

## 7. Compromises made because of time and tools

| Compromise | Why | What I would do next |
|---|---|---|
| Simulated KB (18 articles) | No access to the real KB | Index the real help centre and internal macros; keep sections as chunks |
| BM25 + LLM query rewrite instead of embeddings | Small KB, no infrastructure needed | Hybrid retrieval with multilingual embeddings and a reranker for a large KB |
| 14-ticket assistant eval with automatic checks | Time; free-tier quotas | Larger set, plus human ratings of tone and helpfulness (1–5) from 2–3 agents, which no automatic metric replaces |
| Language check by script (Cyrillic vs Latin) | Cheap and dependency-free | A language-ID library, so Spanish vs English is caught too |
| Tone distinctness by word overlap | Cheap proxy | An LLM-as-judge with a rubric, validated against agent ratings |
| 3–4 model calls per ticket (classify, analyze, draft, optional re-ask) | Clear separation, Task 1 reused as-is | Merge classify + analyze into one call (saves about 1/3 of tokens); reuse the classification already made at intake |
| Final draft prompt validated on Gemini only | Groq free-tier **daily** token limit (200k for gpt-oss-120b) was exhausted mid-eval | Re-run v4 on gpt-oss-120b after the reset and compare |
| No authentication on the demo API | Local demo | SSO or API-key header and per-user rate limits before anyone else can reach it (it spends API credits) |
| Synchronous calls, no streaming | Simpler | Stream the drafts so the agent sees text within ~1 s |

---

## 8. Failure handling, cost and caching (assistant-specific)

**Failure handling.** The same core as Task 1 (`core/llm.py`, `core/json_guard.py`): timeout, retry with backoff, `Retry-After`, repair retry for invalid JSON, then the next model. Daily-quota 429s ("exceeded your current quota", Groq "tokens per day") are **not** retried; they fall straight to the next provider. On top of that:

| Situation | Behaviour |
|---|---|
| Empty ticket | No model calls; "ask the customer to describe the issue" |
| Very long ticket (> 6,000 chars) | The head and the tail are kept (context first, the actual request often last); the middle is cut |
| Analysis step fails | Summary falls back to the first 300 characters of the ticket, the search query to the raw ticket text; drafting continues and the model is told to answer in the ticket's own language |
| Drafting fails | The summary, classification and KB passages are still shown; the banner says "AI drafts unavailable: write the reply manually" |
| A tone is missing or returned as a string | Missing → empty card with a warning; string → accepted as `{text}` |
| Wrong language | One targeted re-ask ("rewrite in Ukrainian, same facts and citations"); if it fails, the first draft is shown with a warning |
| Every provider down | The UI shows "AI unavailable" and keeps working as a plain KB viewer |

Seen in practice during the eval: Groq per-minute limits (2 tickets on the v2 run), then the Groq **daily** limit, which made a whole run come back as "write manually" with the banner (`results/assistant/failed_tpd__*`), and a Gemini daily quota. In the UI test the chain fell over from Groq to Gemini automatically.

**Cost.** Measured $0.0029 per ticket on Gemini Flash-Lite (v4, including the classification call), and $0.0014 on gpt-oss-120b (v1). For 10k tickets a month that is **about $29 on Gemini or $14 on gpt-oss-120b**. Agent time saved is worth far more. Ways to reduce it:
1. Merge the classify and analyze calls: about −30%.
2. Reuse the classification made at intake instead of classifying again in the assistant.
3. Provider prompt caching for the static system prompts: Gemini cached input costs 10% of the normal price, Groq applies 50% off automatically.
4. Generate drafts only when the agent opens the ticket, not for every incoming ticket.

**Caching.**
- *Response cache:* keyed by `(analyze prompt, draft prompt, classifier prompt, KB content hash, model, normalized ticket text)`. A change to any prompt, the KB or the model gives a new key. The hit rate is low (tickets are unique), but it makes repeats and retries free. Answers produced on a fallback path or with errors are never cached, so a degraded answer cannot become sticky.
- *KB index:* the BM25 index is built once per KB content hash and rebuilt automatically when any article changes.
- *Not cached:* nothing is stored per customer beyond the ticket text itself. A policy change (KB edit) invalidates every cached draft, because the KB hash is in the key.

---

## 9. All assistant runs

| Run | Retrieval hit | Citation validity | Tones present | Tones distinct | Language match | Human flag | Tickets with invented numbers | Tickets leaking internal rules | Tickets claiming done actions | Cost / ticket |
|---|---|---|---|---|---|---|---|---|---|---|
| draft_v1, Gemini | 85.7 | 100 | 78.6* | **42.9** | 100 | 85.7* | 0 | 1 | 1 | $0.0025 |
| draft_v1, gpt-oss-120b | 92.9 | 97.3 | 100 | 100 | 100 | 100 | 2 | **5** | **3** | $0.0014 |
| draft_v2, gpt-oss-120b | 85.7 | 94.4 | 85.7† | 85.7† | **85.7** | 100 | 1 | 1 | 0 | $0.0016 |
| draft_v3, Gemini | 92.9 | 100 | 100 | 100 | **85.7** | 85.7* | 1 | 0 | 2 | $0.0027 |
| **draft_v4, Gemini** | 92.9 | **100** | **100** | **100** | **100** | **100** | **0** | **0** | **0** | $0.0029 |

\* includes tickets hit by a Gemini rate limit. † 2 tickets failed on the Groq per-minute limit. The invented-number, leak and claimed-action counts were computed on the saved replies with the current checks (the checks were added after those runs).

Per-ticket results for the final run (`results/assistant/draft_v4__gemini-flash-lite.md`):

| id | lang | expected → retrieved | citations ok/proposed | tones distinct (max sim) | lang | human exp→act |
|---|---|---|---|---|---|---|
| T01 | en | double-charge → double-charge, refund-policy ✅ | 3/3 | ✅ (0.32) | ✅ | -→- ✅ |
| T03 | en | trial-terms, refund-policy → trial-terms, refund-policy ✅ | 3/3 | ✅ (0.39) | ✅ | -→- ✅ |
| T05 | en | login-magic-link → login-magic-link, account-security ✅ | 6/6 | ✅ (0.29) | ✅ | -→- ✅ |
| T06 | en | expert-conduct → expert-conduct ✅ | 3/3 | ✅ (0.38) | ✅ | H→H ✅ |
| T09 | en | account-deletion → account-deletion, edit-birth-data ✅ | 3/3 | ✅ (0.28) | ✅ | H→H ✅ |
| T11 | en | reading-disclaimer → reading-disclaimer ✅ | 6/6 | ✅ (0.45) | ✅ | H→H ✅ |
| T18 | uk | double-charge, refund-policy → double-charge, refund-policy ✅ | 3/3 | ✅ (0.36) | ✅ | -→- ✅ |
| T21 | es | edit-birth-data → edit-birth-data, how-horoscopes-work, account-security ✅ | 6/6 | ✅ (0.26) | ✅ | -→- ✅ |
| T22 | de | double-charge, cancel-web → double-charge, refund-policy, trial-terms ✅ | 3/3 | ✅ (0.28) | ✅ | -→- ✅ |
| T23 | uk | app-crash → app-crash, edit-birth-data ✅ | 3/3 | ✅ (0.33) | ✅ | -→- ✅ |
| T24 | en | how-horoscopes-work → how-horoscopes-work, refund-policy ✅ | 6/6 | ✅ (0.51) | ✅ | -→- ✅ |
| T30 | en | expert-conduct → expert-conduct, expert-chat-billing ✅ | 3/3 | ✅ (0.34) | ✅ | H→H ✅ |
| T40 | en | minor-purchases → minor-purchases, refund-policy ✅ | 3/3 | ✅ (0.35) | ✅ | H→H ✅ |
| T08 | en | (none) → payment-failed, refund-policy ❌ | 0/0 | ✅ (0.21) | ✅ | H→H ✅ |

T08 ("add dark mode") has no KB article. BM25 still returned loosely related passages, but the model set `kb_gap`, so the agent is told to write the answer themselves, which is the intended behaviour.
