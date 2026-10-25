"""FastAPI app: agent assistant UI + JSON APIs for both tasks.

    uv run uvicorn app.main:app --reload
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from assistant.assist import AssistResult, assist
from assistant.retrieval import get_kb
from classifier.classify import classify
from classifier.schema import TicketResult
from core.cache import Cache
from core.llm import LLMClient, load_config, make_chain

ROOT = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=Path(__file__).resolve().parent / "templates")
app = FastAPI(title="Nebula support AI")
cache = Cache(ROOT / "cache.sqlite")


class TicketIn(BaseModel):
    text: str = Field(max_length=10_000)
    model: str | None = None


def chain_for(model: str | None) -> list[LLMClient]:
    """Selected model first, then the configured fallback chain (minus duplicates and models without keys)."""
    config = load_config()
    if model and model not in config["models"]:
        raise HTTPException(422, f"unknown model {model!r}")
    order = ([model] if model else []) + [m for m in config["fallback_chain"] if m != model]
    return make_chain(order)


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.get("/api/models")
def models():
    config = load_config()
    available = {c.alias for c in make_chain(list(config["models"]))}
    return [{"alias": a, "model": m["model"], "available": a in available} for a, m in config["models"].items()]


@app.post("/api/assist", response_model=AssistResult)
def api_assist(ticket: TicketIn):
    return assist(ticket.text, chain_for(ticket.model), cache=cache)


@app.post("/api/classify", response_model=TicketResult)
def api_classify(ticket: TicketIn):
    return classify(ticket.text, chain_for(ticket.model), cache=cache)


@app.get("/kb/{article_id}", response_class=HTMLResponse)
def kb_article(request: Request, article_id: str):
    chunks = get_kb().by_article.get(article_id)
    if not chunks:
        raise HTTPException(404, "article not found")
    return templates.TemplateResponse(request, "kb.html", {"article_id": article_id, "chunks": chunks})
