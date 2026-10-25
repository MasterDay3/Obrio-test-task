# Design decisions

Short records of the choices made while building this, and why. Each entry: **decision**, the alternative, the reasoning.

## Data formats

### JSON for model output, not CSV
- **Decision:** the model returns one JSON object per ticket, validated by Pydantic (`classifier/schema.py`).
- **Alternative:** ask for CSV / delimited text.
- **Why:** all three providers (Gemini, Groq, Ollama) support a JSON mode; none has a CSV mode. The output has lists (`secondary_categories`), numbers, booleans and free text containing commas and line breaks, which break a flat CSV row. Pydantic validation of JSON is what drives the failure handling: invalid output → repair retry → next model → safe default.

### JSONL for the labeled dataset
- **Decision:** `data/tickets_eval.jsonl`, one ticket per line.
- **Alternative:** CSV.
- **Why:** ticket text contains commas, quotes, emoji and Cyrillic, and `tags` is a list. JSONL keeps one format end to end with no quoting issues. This is a preference, not a hard requirement.

### CSV for results, alongside Markdown and JSON
- **Decision:** every eval run writes `.json` (full data), `.md` (for the report) and `.csv` (for Excel / Google Sheets), plus `summary.csv`.
- **Why:** reviewers want to sort and filter results in a spreadsheet. Files are written as `utf-8-sig` so Excel shows Cyrillic correctly, and list fields are joined with `; `.

### No pandas in the pipeline
- **Decision:** metrics are computed with plain Python in `eval/run_classifier_eval.py`.
- **Alternative:** pandas.
- **Why:** 42 tickets and about ten metrics don't justify a heavy dependency. pandas fits the analysis step (confusion matrix, accuracy per edge-case tag, pivoting model comparisons) if that is added.

## Models and providers

### One OpenAI-compatible adapter instead of LiteLLM or per-provider SDKs
- **Decision:** `core/llm.py` uses the `openai` SDK with a different `base_url` per provider.
- **Why:** Gemini, Groq and Ollama all expose OpenAI-compatible endpoints, so one small adapter covers them. Retry, timeout and fallback behaviour stay explicit and testable. The SDK's own retries are disabled (`max_retries=0`) so that every retry is ours and visible.

### Model IDs and prices live in config, not code
- **Decision:** `config/models.yaml` holds model IDs, prices and the fallback order.
- **Why:** this paid off immediately. The Gemini 2.5 models and Groq's Llama 3.3 70B had been retired for new users by the time the keys were created (2026-10-25). Swapping models was a config change. Prices were checked against the provider pages on the same date; Gemini 3.8 Flash prices double on 2027-01-01.

### Eval runs one model at a time, without fallback
- **Decision:** the eval runner builds a chain of one model.
- **Why:** with fallback on, a failing model would be silently replaced by another and its accuracy would be inflated. In production (UI, API) the fallback chain is on.

## Classifier

### Categories follow the team that owns the ticket, not the topic
- **Decision:** 10 categories in `classifier/schema.py`, each mapped to a team in `ROUTING`.
- **Why:** the purpose of classification is routing. Boundary rule: "refund_request" means the customer explicitly asks for money or credits back; a charge problem without that ask is "billing_subscription".

### Rules can only make a ticket more cautious
- **Decision:** `classifier/rules.py` runs after the model and may raise priority, force human review or force the safety category, but never lowers anything.
- **Why:** the costs are asymmetric. A false positive costs an agent a minute; a missed suicide note or chargeback costs far more. Keywords are multilingual (EN, UK, RU, ES, DE, PL).

### Empty tickets never reach the model
- **Decision:** tickets under 3 characters get an "ask for details" result with no model call.
- **Why:** zero cost, zero hallucination risk, deterministic.

### Cache keys use the prompt's content hash, not its version label
- **Decision:** `make_key("classify", prompt_hash, model, normalized_text)`.
- **Why:** editing a prompt file without renaming it still invalidates cached answers. Only clean answers from the primary model are cached; a fallback answer is retried next time.

### Cache stores the raw model answer; rules are re-applied on every hit
- **Decision:** on a cache hit, the classifier takes the cached raw model output and runs the current rules on it.
- **Alternative:** cache the final result (with rules applied).
- **Why:** found during the eval. After the bank-dispute pattern was added to the rules, cached results would have kept serving the old, unsafe answer until they expired. Rules are deterministic and cost nothing, so re-running them is free, and a rule fix takes effect immediately.

## Evaluation

### A held-out set separate from the tuning set
- **Decision:** `data/tickets_eval.jsonl` (42 tickets) was used to iterate prompts v1 → v3. `data/tickets_holdout.jsonl` (15 new tickets) was written after v3 and never used to change a prompt.
- **Why:** v3 was written by looking at v1/v2 errors on the main set, so its main-set score is optimistic. The held-out score is the honest estimate. Gemini v3 scored 95.2% fully correct on the main set and 86.7% on the held-out set.
- **Caveat:** the held-out set exposed a rules gap (H10, "I call my bank and open a dispute", a chargeback threat the model labelled as a plain refund). The fix (new legal patterns) was informed by the held-out set, so for that one pattern the held-out set is no longer blind.

## Assistant

### BM25 plus an LLM-written English query, instead of a vector database
- **Decision:** `assistant/retrieval.py` runs BM25 over KB sections. The query is an English rewrite produced by the model, and the articles the model picks from a title list get a score boost.
- **Why:** the KB is small (18 articles, 42 sections), so a vector database adds infrastructure without benefit. Tickets come in many languages, and the English rewrite makes lexical search work for all of them. The title-picking boost fixes synonym misses found in testing ("child" in the ticket vs "minor" in the article).

### Citations are verified in code
- **Decision:** every quote must appear in the cited article (whitespace- and case-insensitive). Unverified quotes are removed, the reply is flagged, and human review is required.
- **Why:** an invented refund policy sent to a customer is the most damaging failure mode of a support assistant.

### Classification and analysis run in parallel
- **Decision:** the Task 1 classifier and the assistant's analysis step run in two threads.
- **Why:** they are independent, so latency is the slower of the two rather than their sum. The classifier's rule hits feed the human-review banner.

## Failure handling observed in practice
- Gemini returned real **503 "model experiencing high demand"** errors on `gemini-3.1-flash-lite` and `gemini-3.8-flash` during setup. These are retried with backoff and then fall through to the next model in the chain.
- Groq free tier has an **8,000 tokens-per-minute** limit. With the longer v2/v3 prompts (~1,000–1,450 input tokens) this allows about 5–7 requests per minute. 429 responses include `Retry-After`, which the adapter honours. The measured Groq latency for v2/v3 therefore includes rate-limit waits and overstates the model's own speed. One v1 ticket (T39 on gpt-oss-20b) exhausted its retries and went to the manual queue as `unclassified`, the intended degraded behaviour.

## Assistant (added after the Task 2 eval)

### The assistant has its own model chain
- **Decision:** `assistant_chain: [gemini-flash-lite, groq-gpt-oss-120b, groq-gpt-oss-20b]`; the classifier keeps `fallback_chain` with gpt-oss-120b first.
- **Why:** each task gets the model that measured best for it. gpt-oss-120b classifies best; Gemini Flash-Lite with draft_v4 passed every drafting check, while gpt-oss-120b drafts (v1) leaked internal rules in 5 of 14 tickets.

### Drafts are checked in code, not only the citations
- **Decision:** every reply is checked for numbers that do not appear in the retrieved passages or the ticket, for internal agent rules (approval limits, admin tools), and for the wrong language.
- **Why:** a reply with valid citations still said "5–7 business days" where the KB says 5–10, and told the customer about the agents' $100 approval limit. Citation validity alone would have scored that reply 100%.

### One targeted re-ask when the language is wrong
- **Decision:** if any draft is in the wrong script for the customer's language, the drafting call is repeated once with "rewrite in <language>, same facts and citations".
- **Why:** prompt fixes alone (v2, v3) still produced English replies to Ukrainian tickets, because the formal greeting template was in English. One extra call only when needed is cheaper than an agent rewriting the reply.

### Daily-quota 429s are not retried
- **Decision:** 429s that mention a daily quota ("exceeded your current quota", "tokens per day") fail over to the next provider immediately.
- **Why:** observed on both providers. Retrying for up to ~90 s cannot help with a limit that resets tomorrow, and it blocks the agent.

### Money rules also apply to legal tickets
- **Decision:** the high-amount and minor rules run when billing/refund is the primary *or a secondary* category, and for `legal_privacy`.
- **Why:** found in the UI test. "My 14-year-old bought $180 of credits, reverse it or I contact my bank" was routed to legal, and the banner lost "amount above $100" and "minor involved", both of which matter to Billing.

## Second review (fixes and additions)

### Drafts must not claim an action is already done
- **Decision:** a check flags "we have processed / refunded / escalated", "is being processed", "I can approve" (plus Ukrainian and Russian equivalents).
- **Why:** the AI drafts the reply *before* the agent acts. v1 drafts said "I can approve the refund right away… Refund is being processed now". An agent copying that sends a promise nobody has kept yet.

### Long tickets keep their head and tail
- **Decision:** tickets over 6,000 characters keep the first and last 3,000.
- **Why:** the earlier version kept only the head, but the classifier prompt itself says the actual request is usually near the end of a long story (T38).

### The assistant's classification uses the classifier's chain
- **Decision:** `assist(..., classify_chain=...)`; the app passes the classifier chain (gpt-oss-120b first) and drafts with the assistant chain (Gemini first).
- **Why:** before this, the banner's classification silently ran on the drafting model, not on the model chosen for classification.

### The internal-rule check is narrow on purpose
- **Decision:** flag "admin panel", "agents can…", "approval limit", "$100 limit", not the word "limit" alone.
- **Why:** some limits are customer-facing (birth data can be changed 3 times a month). Re-scoring the saved runs gave the same leak counts with the narrow pattern, so precision improved without losing recall.

### A prompt change is adopted only if the eval shows a gain
- **Decision:** draft_v5 (explicit "never use the past tense for actions") was evaluated and **not** adopted; v4 stays the default.
- **Why:** v5 scored 1 leak + 1 claimed action vs 0/0 for v4 on the same 14 tickets. With single runs that is noise, and adding rules to a prompt is not free (longer prompt, rules can conflict). The code checks already catch these cases.

### Empty tickets get no drafts
- **Decision:** the assistant, like the classifier, makes no model calls for an empty ticket and asks the agent to request details.
- **Why:** three model calls on an empty string cost money and produce invented content.

