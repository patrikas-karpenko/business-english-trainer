"""SQLite storage for the pilot. One file (DATABASE_PATH, default data/trainer.db).

Tables: users, progress (per lesson and drill), phrase_cards (one FSRS item per
phrase per user) and attempts (every answer, with paste and timing data).
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS progress (
  user_id INTEGER NOT NULL,
  lesson_id TEXT NOT NULL,
  current_session INTEGER NOT NULL DEFAULT 1,
  current_drill INTEGER NOT NULL DEFAULT 0,
  drill_status TEXT NOT NULL DEFAULT '{}',
  session1_completed_at TEXT,
  lesson_completed_at TEXT,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (user_id, lesson_id)
);
CREATE TABLE IF NOT EXISTS phrase_cards (
  user_id INTEGER NOT NULL,
  phrase_id TEXT NOT NULL,
  fsrs TEXT NOT NULL,
  due TEXT NOT NULL,
  success_days TEXT NOT NULL DEFAULT '[]',
  fill_reviews INTEGER NOT NULL DEFAULT 0,
  recent_variants TEXT NOT NULL DEFAULT '{}',
  first_use_success_at TEXT,
  owned INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (user_id, phrase_id)
);
CREATE TABLE IF NOT EXISTS attempts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  lesson_id TEXT,
  drill_no INTEGER,
  item TEXT,
  response TEXT,
  pasted INTEGER NOT NULL DEFAULT 0,
  response_ms INTEGER,
  result TEXT,
  is_revision INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
"""


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None = None) -> str:
    return (dt or now()).isoformat()


def db_path() -> Path:
    return Path(os.environ.get("DATABASE_PATH", Path(__file__).resolve().parent.parent / "data" / "trainer.db"))


@contextmanager
def connect():
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init() -> None:
    with connect() as con:
        con.executescript(SCHEMA)


# ---------------------------------------------------------------- users
def get_or_create_user(name: str) -> int:
    with connect() as con:
        row = con.execute("SELECT id FROM users WHERE name = ?", (name,)).fetchone()
        if row:
            return row["id"]
        cur = con.execute("INSERT INTO users (name, created_at) VALUES (?, ?)", (name, iso()))
        return cur.lastrowid


def user(user_id: int) -> sqlite3.Row | None:
    with connect() as con:
        return con.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


# ---------------------------------------------------------------- progress
def get_progress(user_id: int, lesson_id: str) -> dict:
    with connect() as con:
        row = con.execute("SELECT * FROM progress WHERE user_id = ? AND lesson_id = ?", (user_id, lesson_id)).fetchone()
    if not row:
        return {"user_id": user_id, "lesson_id": lesson_id, "current_session": 1, "current_drill": 0,
                "drill_status": {}, "session1_completed_at": None, "lesson_completed_at": None}
    d = dict(row)
    d["drill_status"] = json.loads(d["drill_status"])
    return d


def all_progress(user_id: int) -> dict[str, dict]:
    with connect() as con:
        rows = con.execute("SELECT * FROM progress WHERE user_id = ?", (user_id,)).fetchall()
    out = {}
    for r in rows:
        d = dict(r)
        d["drill_status"] = json.loads(d["drill_status"])
        out[d["lesson_id"]] = d
    return out


def mark_drill_done(user_id: int, lesson_id: str, drill_no: int) -> dict:
    p = get_progress(user_id, lesson_id)
    p["drill_status"][str(drill_no)] = "done"
    p["current_drill"] = min(drill_no + 1, 6) if drill_no < 6 else 6
    if drill_no == 3 and not p["session1_completed_at"]:
        p["session1_completed_at"] = iso()
        p["current_session"] = 2
    if drill_no == 6 and not p["lesson_completed_at"]:
        p["lesson_completed_at"] = iso()
    with connect() as con:
        con.execute(
            """INSERT INTO progress (user_id, lesson_id, current_session, current_drill, drill_status,
                 session1_completed_at, lesson_completed_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT (user_id, lesson_id) DO UPDATE SET
                 current_session = excluded.current_session, current_drill = excluded.current_drill,
                 drill_status = excluded.drill_status, session1_completed_at = excluded.session1_completed_at,
                 lesson_completed_at = excluded.lesson_completed_at, updated_at = excluded.updated_at""",
            (user_id, lesson_id, p["current_session"], p["current_drill"], json.dumps(p["drill_status"]),
             p["session1_completed_at"], p["lesson_completed_at"], iso()))
    return p


# ---------------------------------------------------------------- phrase cards
def get_card(user_id: int, phrase_id: str) -> dict | None:
    with connect() as con:
        row = con.execute("SELECT * FROM phrase_cards WHERE user_id = ? AND phrase_id = ?", (user_id, phrase_id)).fetchone()
    if not row:
        return None
    d = dict(row)
    for k in ("fsrs", "success_days", "recent_variants"):
        d[k] = json.loads(d[k])
    return d


def save_card(user_id: int, c: dict) -> None:
    with connect() as con:
        con.execute(
            """INSERT INTO phrase_cards (user_id, phrase_id, fsrs, due, success_days, fill_reviews, recent_variants,
                 first_use_success_at, owned)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT (user_id, phrase_id) DO UPDATE SET
                 fsrs = excluded.fsrs, due = excluded.due, success_days = excluded.success_days,
                 fill_reviews = excluded.fill_reviews, recent_variants = excluded.recent_variants,
                 first_use_success_at = excluded.first_use_success_at, owned = excluded.owned""",
            (user_id, c["phrase_id"], json.dumps(c["fsrs"]), c["due"], json.dumps(c["success_days"]),
             c["fill_reviews"], json.dumps(c["recent_variants"]), c.get("first_use_success_at"), int(c.get("owned", 0))))


def due_cards(user_id: int, limit: int = 10) -> list[str]:
    with connect() as con:
        rows = con.execute("SELECT phrase_id FROM phrase_cards WHERE user_id = ? AND due <= ? ORDER BY due LIMIT ?",
                           (user_id, iso(), limit)).fetchall()
    return [r["phrase_id"] for r in rows]


def card_rows(user_id: int) -> list[dict]:
    with connect() as con:
        rows = con.execute("SELECT * FROM phrase_cards WHERE user_id = ?", (user_id,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["success_days"] = json.loads(d["success_days"])
        out.append(d)
    return out


# ---------------------------------------------------------------- attempts
def log_attempt(user_id: int, lesson_id: str | None, drill_no: int | None, item: str, response: str,
                result: dict | None = None, pasted: int = 0, response_ms: int | None = None,
                is_revision: bool = False) -> None:
    with connect() as con:
        con.execute(
            """INSERT INTO attempts (user_id, lesson_id, drill_no, item, response, pasted, response_ms, result,
                 is_revision, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, lesson_id, drill_no, item, response, pasted, response_ms,
             json.dumps(result) if result is not None else None, int(is_revision), iso()))


def last_attempt(user_id: int, lesson_id: str, drill_no: int, item: str) -> sqlite3.Row | None:
    with connect() as con:
        return con.execute(
            """SELECT * FROM attempts WHERE user_id = ? AND lesson_id = ? AND drill_no = ? AND item = ?
               ORDER BY id DESC LIMIT 1""", (user_id, lesson_id, drill_no, item)).fetchone()


def paste_count(user_id: int) -> int:
    with connect() as con:
        row = con.execute("SELECT COALESCE(SUM(pasted), 0) AS n FROM attempts WHERE user_id = ?", (user_id,)).fetchone()
    return row["n"]
