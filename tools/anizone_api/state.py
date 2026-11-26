"""
Let a fresh machine (e.g. a GitHub Actions runner) continue crawling incrementally.

A runner starts with no database. It rebuilds one from:
  * the published API itself   (v1/anime/{id}.json - every anime's full data), and
  * a small crawl-state file    (state/crawl_state.json.gz - every URL seen, its
                                 sitemap lastmod and HTTP status, 404s included)
then crawls only what changed, exports the API again, and saves the state.
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path

from .db import connect, set_meta, upsert_anime

STATE_VERSION = 1


def save_state(db_path: str, out_path: str) -> dict:
    con = connect(db_path, readonly=True)
    rows = con.execute("SELECT url, id, lastmod, status FROM crawl_state ORDER BY url").fetchall()
    meta = {r["key"]: r["value"] for r in con.execute("SELECT key, value FROM meta")}
    data = {"version": STATE_VERSION, "meta": meta,
            "urls": [[r["url"], r["id"], r["lastmod"], r["status"]] for r in rows]}
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    # mtime=0 -> identical content gives an identical file (no pointless git commits)
    with open(out, "wb") as f, gzip.GzipFile(fileobj=f, mode="wb", mtime=0) as gz:
        gz.write(raw)
    return {"urls": len(rows), "file": str(out), "kb": round(out.stat().st_size / 1024)}


def load_state(db_path: str, api_dir: str, state_path: str | None) -> dict:
    """Rebuild a crawl database from a published API folder + state file."""
    con = connect(db_path)
    lastmods: dict[int, str] = {}
    n_state = 0
    if state_path and Path(state_path).exists():
        with gzip.open(state_path, "rt", encoding="utf-8") as f:
            data = json.load(f)
        with con:
            con.executemany(
                "INSERT OR REPLACE INTO crawl_state(url,id,lastmod,status,error,fetched_at)"
                " VALUES (?,?,?,?,NULL,NULL)", [tuple(u) for u in data["urls"]])
        for url, aid, lastmod, status in data["urls"]:
            if aid is not None and lastmod and status == 200:
                lastmods[aid] = lastmod
        for k, v in (data.get("meta") or {}).items():
            set_meta(con, k, v)
        n_state = len(data["urls"])

    n = 0
    anime_dir = Path(api_dir) / "v1" / "anime"
    for f in sorted(anime_dir.glob("*.json")) if anime_dir.exists() else []:
        a = json.loads(f.read_text(encoding="utf-8"))
        a.pop("attribution", None)  # added at export time, re-added on the next export
        if a.get("id"):
            upsert_anime(con, a, lastmods.get(a["id"]))
            n += 1
    return {"anime_loaded": n, "state_urls": n_state}
