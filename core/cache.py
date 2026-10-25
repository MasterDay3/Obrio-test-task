"""Exact-match response cache in SQLite. Keys include prompt version and model, so changing either invalidates."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import time
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "cache.sqlite"


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def make_key(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


class Cache:
    def __init__(self, path: Path | str = DEFAULT_PATH, ttl_s: float | None = 7 * 24 * 3600):
        self.ttl_s = ttl_s
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.Lock()  # shared by FastAPI worker threads
        self.db.execute("CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value TEXT, created REAL)")

    def get(self, key: str) -> dict | None:
        with self.lock:
            row = self.db.execute("SELECT value, created FROM cache WHERE key = ?", (key,)).fetchone()
            if row is None:
                return None
            if self.ttl_s is not None and time.time() - row[1] > self.ttl_s:
                self.db.execute("DELETE FROM cache WHERE key = ?", (key,))
                self.db.commit()
                return None
            return json.loads(row[0])

    def set(self, key: str, value: dict) -> None:
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO cache VALUES (?, ?, ?)", (key, json.dumps(value), time.time()))
            self.db.commit()
