"""
Kleine SQLite-opslag:
1. voorkomt dat dezelfde advertentie twee keer een melding oplevert;
2. logt ALLE evaluaties (ook afgewezen deals), zodat je achteraf kunt
   controleren of de score-logica goed staat afgesteld.
"""
import json
import sqlite3
import time
from contextlib import contextmanager

DB_PATH = "dealhunter.db"


@contextmanager
def _connect():
    conn = sqlite3.connect(DB_PATH)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS listings (
                url TEXT PRIMARY KEY,
                seen_at REAL,
                should_notify INTEGER,
                score INTEGER,
                category TEXT,
                raw_eval TEXT
            )
            """
        )


def already_seen(url: str) -> bool:
    with _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM listings WHERE url = ?", (url,)
        ).fetchone()
        return row is not None


def record(url: str, evalresult: dict):
    with _connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO listings (url, seen_at, should_notify, score, category, raw_eval)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                url,
                time.time(),
                1 if evalresult.get("should_notify") else 0,
                evalresult.get("score", 0),
                evalresult.get("category", "geen"),
                json.dumps(evalresult, ensure_ascii=False),
            ),
        )
