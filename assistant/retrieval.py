"""BM25 over KB sections. The query is an English rewrite made by the LLM, so non-English tickets still match."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from functools import cache as memo
from pathlib import Path

from rank_bm25 import BM25Okapi

KB_DIR = Path(__file__).resolve().parent / "kb"
MIN_SCORE = 4.0  # BM25 hits below this are dropped as noise (tuned on sample queries)

_STOP = set("""a an the and or but if of to in on at for from by with without is are was were be been being it its this that
these those i me my you your we our they them their he she his her can could should would will do does did not no yes
so as than then there here what which who how when where why please hi hello thanks thank just also very any all""".split())


def tokenize(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return [_stem(w) for w in words if w not in _STOP and len(w) > 1]


def _stem(w: str) -> str:
    for suffix in ("ations", "ation", "ings", "ing", "ies", "ied", "led", "ed", "es", "s"):
        if w.endswith(suffix) and len(w) - len(suffix) >= 3:
            return w[: -len(suffix)] + ("y" if suffix in ("ies", "ied") else "")
    return w


@dataclass(frozen=True)
class Chunk:
    article_id: str
    title: str
    section: str
    text: str

    @property
    def ref(self) -> str:
        return f"{self.article_id}#{re.sub(r'[^a-z0-9]+', '-', self.section.lower()).strip('-')}"


@dataclass(frozen=True)
class Hit:
    chunk: Chunk
    score: float


def load_chunks(kb_dir: Path = KB_DIR) -> list[Chunk]:
    chunks = []
    for path in sorted(kb_dir.glob("*.md")):
        lines = path.read_text().splitlines()
        title = lines[0].removeprefix("# ").strip()
        section, body = None, []
        for line in lines[1:] + ["## "]:
            if line.startswith("## "):
                if section and body:
                    chunks.append(Chunk(path.stem, title, section, " ".join(body).strip()))
                section, body = line[3:].strip(), []
            elif line.strip():
                body.append(line.strip())
    return chunks


def kb_version(kb_dir: Path = KB_DIR) -> str:
    """Content hash of the KB: part of every cache key, so editing an article invalidates cached answers."""
    h = hashlib.sha256()
    for path in sorted(kb_dir.glob("*.md")):
        h.update(path.name.encode() + path.read_bytes())
    return h.hexdigest()[:12]


class KnowledgeBase:
    def __init__(self, chunks: list[Chunk]):
        self.chunks = chunks
        self.by_article: dict[str, list[Chunk]] = {}
        for c in chunks:
            self.by_article.setdefault(c.article_id, []).append(c)
        self._bm25 = BM25Okapi([tokenize(f"{c.title} {c.section} {c.text}") for c in chunks])

    def search(self, query: str, k: int = 3) -> list[Hit]:
        scores = self._bm25.get_scores(tokenize(query))
        ranked = sorted(zip(self.chunks, scores), key=lambda x: x[1], reverse=True)[:k]
        return [Hit(c, float(s)) for c, s in ranked if s > 0]

    def article_text(self, article_id: str) -> str:
        return " ".join(c.text for c in self.by_article.get(article_id, []))

    def verify_quote(self, article_id: str, quote: str) -> bool:
        """A citation is valid only if the quote appears (whitespace/case-insensitive) in that article."""
        q = _norm(quote)
        return len(q) >= 15 and q in _norm(self.article_text(article_id))


def _norm(s: str) -> str:
    s = s.replace("’", "'").replace("“", '"').replace("”", '"').replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", s).strip().strip('."\'').lower()


@memo
def _load(version: str) -> KnowledgeBase:
    return KnowledgeBase(load_chunks())


def get_kb() -> KnowledgeBase:
    # Keyed by content hash: the index is rebuilt only when an article changes.
    return _load(kb_version())
