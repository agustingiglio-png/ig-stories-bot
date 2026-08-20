"""Capa de estado en SQLite: runs, stories (por imagen), skips y metadata.

El estado es la fuente de verdad para la idempotencia:
- runs.status: PENDING / RUNNING / COMPLETED / SKIPPED / FAILED
- stories.status: PENDING / PUBLISHED / FAILED   (una fila por imagen y por dia)
Si un run del dia ya esta COMPLETED, no se vuelve a publicar.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Iterator, Optional

from .config import DB_PATH, STATE_DIR, TZ

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    date        TEXT PRIMARY KEY,      -- YYYY-MM-DD (hora Argentina)
    status      TEXT NOT NULL,         -- PENDING/RUNNING/COMPLETED/SKIPPED/FAILED
    started_at  TEXT,
    finished_at TEXT,
    reason      TEXT,                  -- p.ej. "skip configurado para hoy"
    error       TEXT
);

CREATE TABLE IF NOT EXISTS stories (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date    TEXT NOT NULL,
    seq         INTEGER NOT NULL,      -- orden 1..N
    filename    TEXT NOT NULL,
    sha256      TEXT NOT NULL,         -- huella del contenido publicado
    ig_media_id TEXT,                  -- id devuelto por media_publish
    status      TEXT NOT NULL,         -- PENDING/PUBLISHED/FAILED
    error       TEXT,
    published_at TEXT,
    UNIQUE(run_date, seq)
);

CREATE TABLE IF NOT EXISTS skips (
    date       TEXT PRIMARY KEY,       -- YYYY-MM-DD a saltear
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def _now() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


# --- skips -------------------------------------------------------------------
def add_skip(day: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO skips(date, created_at) VALUES (?, ?)",
            (day, _now()),
        )


def remove_skip(day: str) -> bool:
    with connect() as conn:
        cur = conn.execute("DELETE FROM skips WHERE date = ?", (day,))
        return cur.rowcount > 0


def is_skipped(day: str) -> bool:
    with connect() as conn:
        row = conn.execute("SELECT 1 FROM skips WHERE date = ?", (day,)).fetchone()
        return row is not None


def list_skips() -> list[str]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT date FROM skips WHERE date >= date('now','-1 day') ORDER BY date"
        ).fetchall()
        return [r["date"] for r in rows]


# --- runs --------------------------------------------------------------------
def get_run(day: str) -> Optional[sqlite3.Row]:
    with connect() as conn:
        return conn.execute("SELECT * FROM runs WHERE date = ?", (day,)).fetchone()


def start_run(day: str) -> None:
    """Marca el run como RUNNING (o lo crea)."""
    with connect() as conn:
        conn.execute(
            """INSERT INTO runs(date, status, started_at)
               VALUES (?, 'RUNNING', ?)
               ON CONFLICT(date) DO UPDATE SET status='RUNNING', started_at=COALESCE(started_at, ?)""",
            (day, _now(), _now()),
        )


def set_run_status(day: str, status: str, reason: str | None = None,
                   error: str | None = None, finished: bool = False) -> None:
    with connect() as conn:
        conn.execute(
            """INSERT INTO runs(date, status, reason, error, finished_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(date) DO UPDATE SET
                 status=excluded.status,
                 reason=COALESCE(excluded.reason, runs.reason),
                 error=excluded.error,
                 finished_at=excluded.finished_at""",
            (day, status, reason, error, _now() if finished else None),
        )


# --- stories -----------------------------------------------------------------
def ensure_story_rows(day: str, items: list[tuple[int, str, str]]) -> None:
    """items = [(seq, filename, sha256)]. Crea filas PENDING si no existen.

    Si una fila ya existe pero su sha256 cambio (usuario cambio la foto ese
    mismo dia antes de completar), la reinicia a PENDING para no publicar viejo.
    """
    with connect() as conn:
        for seq, filename, sha in items:
            row = conn.execute(
                "SELECT status, sha256 FROM stories WHERE run_date=? AND seq=?",
                (day, seq),
            ).fetchone()
            if row is None:
                conn.execute(
                    """INSERT INTO stories(run_date, seq, filename, sha256, status)
                       VALUES (?, ?, ?, ?, 'PENDING')""",
                    (day, seq, filename, sha),
                )
            elif row["status"] != "PUBLISHED" and row["sha256"] != sha:
                conn.execute(
                    """UPDATE stories SET filename=?, sha256=?, status='PENDING', error=NULL
                       WHERE run_date=? AND seq=?""",
                    (filename, sha, day, seq),
                )


def get_stories(day: str) -> list[sqlite3.Row]:
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM stories WHERE run_date=? ORDER BY seq", (day,)
        ).fetchall()


def mark_story_published(day: str, seq: int, ig_media_id: str) -> None:
    with connect() as conn:
        conn.execute(
            """UPDATE stories SET status='PUBLISHED', ig_media_id=?, error=NULL, published_at=?
               WHERE run_date=? AND seq=?""",
            (ig_media_id, _now(), day, seq),
        )


def mark_story_failed(day: str, seq: int, error: str) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE stories SET status='FAILED', error=? WHERE run_date=? AND seq=?",
            (error[:500], day, seq),
        )


# --- meta --------------------------------------------------------------------
def set_meta(key: str, value: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO meta(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


def get_meta(key: str) -> Optional[str]:
    with connect() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None


def history(limit: int = 30) -> list[sqlite3.Row]:
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM runs ORDER BY date DESC LIMIT ?", (limit,)
        ).fetchall()
