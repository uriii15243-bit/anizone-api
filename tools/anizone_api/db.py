"""SQLite storage: one row per anime (full JSON) + indexed columns + FTS5."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS anime (
    id              INTEGER PRIMARY KEY,
    data            TEXT NOT NULL,
    title_hebrew    TEXT,
    title_english   TEXT,
    title_romaji    TEXT,
    type            TEXT,
    status          TEXT,
    year            INTEGER,
    season          TEXT,
    episodes        INTEGER,
    mal_score       REAL,
    israel_score    REAL,
    popularity      INTEGER,
    members         INTEGER,
    has_hebrew      INTEGER,
    lastmod         TEXT,
    scraped_at      TEXT
);
CREATE INDEX IF NOT EXISTS ix_anime_year_season ON anime(year, season);
CREATE INDEX IF NOT EXISTS ix_anime_popularity ON anime(popularity);
CREATE INDEX IF NOT EXISTS ix_anime_israel ON anime(israel_score);
CREATE INDEX IF NOT EXISTS ix_anime_mal ON anime(mal_score);

CREATE VIRTUAL TABLE IF NOT EXISTS anime_fts USING fts5(
    title_hebrew, title_english, title_romaji, known_titles, synopsis_hebrew,
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TABLE IF NOT EXISTS anime_category (
    anime_id INTEGER NOT NULL,
    kind     TEXT NOT NULL,          -- 'category' | 'subcategory'
    en       TEXT,
    he       TEXT
);
CREATE INDEX IF NOT EXISTS ix_cat_anime ON anime_category(anime_id);
CREATE INDEX IF NOT EXISTS ix_cat_he ON anime_category(he);
CREATE INDEX IF NOT EXISTS ix_cat_en ON anime_category(en COLLATE NOCASE);

CREATE TABLE IF NOT EXISTS crawl_state (
    url      TEXT PRIMARY KEY,
    id       INTEGER,
    lastmod  TEXT,
    status   INTEGER,
    error    TEXT,
    fetched_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_state_id ON crawl_state(id);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


def connect(path: str | Path = "anizone.db", readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        con = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True,
                              check_same_thread=False)
    else:
        con = sqlite3.connect(str(path), check_same_thread=False)
        con.execute("PRAGMA journal_mode=WAL")
        con.executescript(SCHEMA)
    con.row_factory = sqlite3.Row
    return con


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def upsert_anime(con: sqlite3.Connection, a: dict, lastmod: str | None = None) -> None:
    t = a.get("titles") or {}
    season = a.get("season") or {}
    sc = a.get("scores") or {}
    year = season.get("year") or (int(a["aired_from"][:4]) if a.get("aired_from") else None)
    row = {
        "id": a["id"],
        "data": json.dumps(a, ensure_ascii=False),
        "title_hebrew": t.get("hebrew"),
        "title_english": t.get("english"),
        "title_romaji": t.get("romaji"),
        "type": a.get("type"),
        "status": a.get("status"),
        "year": year,
        "season": season.get("season"),
        "episodes": a.get("episodes"),
        "mal_score": sc.get("mal"),
        "israel_score": sc.get("israel"),
        "popularity": sc.get("popularity"),
        "members": sc.get("members"),
        "has_hebrew": 1 if a.get("synopsis_hebrew") else 0,
        "lastmod": lastmod,
        "scraped_at": now(),
    }
    cols = ", ".join(row)
    ph = ", ".join(f":{k}" for k in row)
    upd = ", ".join(f"{k}=excluded.{k}" for k in row if k != "id")
    with con:
        con.execute(f"INSERT INTO anime ({cols}) VALUES ({ph}) ON CONFLICT(id) DO UPDATE SET {upd}", row)
        con.execute("DELETE FROM anime_category WHERE anime_id = ?", (a["id"],))
        con.executemany(
            "INSERT INTO anime_category(anime_id, kind, en, he) VALUES (?,?,?,?)",
            [(a["id"], kind, c.get("en"), c.get("he"))
             for kind, key in (("category", "categories"), ("subcategory", "subcategories"))
             for c in (a.get(key) or [])])
        # keep the FTS row in sync: delete-by-rowid then insert
        con.execute("DELETE FROM anime_fts WHERE rowid = ?", (a["id"],))
        con.execute(
            "INSERT INTO anime_fts(rowid, title_hebrew, title_english, title_romaji, known_titles, synopsis_hebrew)"
            " VALUES (?,?,?,?,?,?)",
            (a["id"], t.get("hebrew") or "", t.get("english") or "", t.get("romaji") or "",
             " | ".join((t.get("known") or []) + (t.get("synonyms") or [])),
             a.get("synopsis_hebrew") or ""),
        )


def get_state(con: sqlite3.Connection, url: str) -> sqlite3.Row | None:
    return con.execute("SELECT * FROM crawl_state WHERE url = ?", (url,)).fetchone()


def set_state(con, url, anime_id, lastmod, status, error=None) -> None:
    with con:
        con.execute(
            "INSERT INTO crawl_state(url,id,lastmod,status,error,fetched_at) VALUES (?,?,?,?,?,?)"
            " ON CONFLICT(url) DO UPDATE SET id=excluded.id, lastmod=excluded.lastmod,"
            " status=excluded.status, error=excluded.error, fetched_at=excluded.fetched_at",
            (url, anime_id, lastmod, status, error, now()),
        )


def set_meta(con, key, value) -> None:
    with con:
        con.execute("INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, str(value)))
