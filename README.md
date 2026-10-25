# Nebula support AI: ticket classifier + agent assistant

OBRIO AI Ops test task.

- **Task 1:** an AI classifier that returns category, priority and the recommended next step.
- **Task 2:** an internal assistant that returns a summary, three reply variants in different tones and verified knowledge-base citations.

Detailed write-ups: [`docs/task1_report.md`](docs/task1_report.md) and [`docs/task2_report.md`](docs/task2_report.md).

## Quick start

```bash
uv sync
cp .env.example .env          # add GEMINI_API_KEY and GROQ_API_KEY (both free, no card)
brew install ollama && ollama serve &   # optional local model
ollama pull qwen2.5:7b

uv run pytest                                   # unit tests, no network
uv run python -m eval.run_classifier_eval --models all --prompts v1 v2 v3 --sleep 4
uv run uvicorn app.main:app --reload            # UI at http://localhost:8000
```

## Architecture

```
ticket ─┬─> classifier (Task 1) ─> rules safety net ─> category / priority / next step / needs_human
        │
        └─> analyze (summary, language, English search query, candidate articles)
                 └─> BM25 over KB sections (+ boost for model-picked articles)
                          └─> draft 3 tones with citations ─> citation verifier ─> human-review gate (UI)
```

| Layer | File | Notes |
|---|---|---|
| Provider adapter | `core/llm.py` | Gemini, Groq and Ollama through their OpenAI-compatible APIs. Timeout, retry with backoff (honours `Retry-After`), cost accounting per call |
| Structured output | `core/json_guard.py` | Parse, validate (Pydantic), one repair retry, next model in the chain, then a safe default |
| Cache | `core/cache.py` | SQLite exact-match cache. The key includes the prompt hash, model and KB version |
| Classifier | `classifier/` | Taxonomy in `schema.py`, prompts in `prompts/v*.md`, deterministic overrides in `rules.py` |
| Assistant | `assistant/` | KB in `kb/*.md`, `retrieval.py` (BM25), `assist.py` (pipeline), prompts |
| Web | `app/` | FastAPI and one HTML page; `/api/assist`, `/api/classify`, `/kb/{id}` |
| Eval | `eval/`, `data/`, `results/` | Labeled ticket set, runner, per-run tables and summary |

Model list, fallback order and prices: `config/models.yaml`.
