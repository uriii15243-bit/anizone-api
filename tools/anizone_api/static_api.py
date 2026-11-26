"""
Export the database as a STATIC JSON API (no server needed).

Host the output folder on GitHub Pages / Cloudflare Pages / Netlify and every
URL below works for anyone, for free, with CORS enabled:

  /v1/index.json                         API info, totals, endpoint list
  /v1/anime/{id}.json                    full details for one anime
  /v1/top/{popularity|israel|mal}/{page}.json      ranked lists, 25 per page
  /v1/seasons/index.json                 every season that has anime
  /v1/seasons/{year}/{season}.json       all anime of a season
  /v1/categories/index.json              every category (with slugs)
  /v1/categories/{slug}/{page}.json      anime in a category, by popularity
  /v1/types/{type}/{page}.json           TV / Movie / OVA ... by popularity
  /v1/search.json                        compact index for client-side search
  /v1/ids.json                           every anime id (for random picks)
"""
from __future__ import annotations

import json
import re
import shutil
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .db import connect

PAGE_SIZE = 25
SEASON_ORDER = {"winter": 0, "spring": 1, "summer": 2, "fall": 3}
DOCS_DIR = Path(__file__).parent / "static_docs"
ATTRIBUTION = {
    "source": "AniZone",
    "source_url": "https://anizone.co.il",
    "note": "המידע באדיבות AniZone, באישור מפעילי האתר. נתוני בסיס מקורם ב-MyAnimeList.",
}


def slugify(s: str) -> str:
    s = re.sub(r"[^\w֐-׿]+", "-", s.strip().lower()).strip("-")
    return s or "unknown"


UPCOMING = ("בשידור", "עדיין לא שודר")


def summary(a: dict) -> dict:
    t = a.get("titles") or {}
    sc = a.get("scores") or {}
    return {
        "id": a["id"],
        "titles": {"hebrew": t.get("hebrew"), "english": t.get("english"), "romaji": t.get("romaji")},
        "type": a.get("type"),
        "episodes": a.get("episodes"),
        "status": a.get("status"),
        "season": a.get("season"),
        "categories": a.get("categories") or [],
        "scores": {"israel": sc.get("israel"), "israel_scored_by": sc.get("israel_scored_by"),
                   "mal": sc.get("mal"), "popularity": sc.get("popularity")},
        "poster": (a.get("images") or {}).get("poster"),
        "url": a.get("url"),
        "api_url": f"v1/anime/{a['id']}.json",
    }


def _write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def _paginate(out: Path, base: str, items: list[dict], extra: dict | None = None) -> int:
    pages = max(1, (len(items) + PAGE_SIZE - 1) // PAGE_SIZE)
    for p in range(1, pages + 1):
        chunk = items[(p - 1) * PAGE_SIZE:p * PAGE_SIZE]
        _write(out / base / f"{p}.json", {
            **(extra or {}),
            "pagination": {"page": p, "per_page": PAGE_SIZE, "total": len(items), "pages": pages,
                           "has_next": p < pages,
                           "next": f"v1/{base}/{p + 1}.json" if p < pages else None,
                           "prev": f"v1/{base}/{p - 1}.json" if p > 1 else None},
            "data": chunk,
        })
    return pages


def export_static_api(db_path: str, out_dir: str, min_israel_votes: int = 5, airing_fetch=None) -> dict:
    out = Path(out_dir)
    v1 = out / "v1"
    if v1.exists():
        shutil.rmtree(v1)
    v1.mkdir(parents=True)

    con = connect(db_path, readonly=True)
    # exact next-episode dates (AniList); None = not checked / unavailable
    next_eps = None
    if airing_fetch:
        ids = [r[0] for r in con.execute("SELECT id FROM anime WHERE json_extract(data, '$.status') IN (?, ?)", UPCOMING)]
        next_eps = airing_fetch(ids)
    summaries: list[dict] = []
    search_rows: list[list] = []
    seasons: dict[tuple, list] = defaultdict(list)
    cats: dict[str, dict] = {}
    cat_items: dict[str, list] = defaultdict(list)
    types: dict[str, list] = defaultdict(list)
    schedule: list[dict] = []
    n = 0
    for row in con.execute("SELECT data FROM anime ORDER BY id"):
        a = json.loads(row["data"])
        if not a.get("id"):
            continue
        a["attribution"] = {**ATTRIBUTION, "page": a.get("url")}
        b = a.get("broadcast")
        if isinstance(b, dict):
            b["timezone"] = "Asia/Tokyo"  # AniZone lists the Japanese TV slot (JST)
        if next_eps is not None and a.get("status") in UPCOMING:
            a["next_episode"] = next_eps.get(a["id"])  # null = nothing scheduled (e.g. on a break)
        _write(v1 / "anime" / f"{a['id']}.json", a)
        s = summary(a)
        if a.get("next_episode"):
            schedule.append({**s, "broadcast": b, "aired_from": a.get("aired_from"), "next_episode": a["next_episode"]})
        summaries.append(s)
        t = a.get("titles") or {}
        search_rows.append([a["id"], t.get("hebrew"), t.get("english"), t.get("romaji"),
                            " ".join(filter(None, (t.get("synonyms") or []) + [t.get("japanese") or ""])) or None,
                            a.get("type"), (a.get("season") or {}).get("year"), s["poster"],
                            (a.get("scores") or {}).get("popularity")])
        se = a.get("season") or {}
        if se.get("year") and se.get("season"):
            seasons[(se["year"], se["season"])].append(s)
        for c in a.get("categories") or []:
            slug = slugify(c.get("en") or c.get("he") or "")
            cats.setdefault(slug, {"slug": slug, "en": c.get("en"), "he": c.get("he")})
            cat_items[slug].append(s)
        if a.get("type"):
            types[a["type"]].append(s)
        n += 1

    def by_pop(x):
        p = x["scores"]["popularity"]
        return (p is None or p == 0, p or 0, x["id"])

    summaries.sort(key=by_pop)
    _paginate(v1, "top/popularity", summaries)
    rated = [s for s in summaries if s["scores"]["israel"] and (s["scores"]["israel_scored_by"] or 0) >= min_israel_votes]
    rated.sort(key=lambda x: (-x["scores"]["israel"], -(x["scores"]["israel_scored_by"] or 0)))
    _paginate(v1, "top/israel", rated, {"note": f"רק אנימות עם {min_israel_votes} דירוגים ישראליים ומעלה"})
    mal = sorted([s for s in summaries if s["scores"]["mal"]], key=lambda x: -x["scores"]["mal"])
    _paginate(v1, "top/mal", mal)

    season_index = []
    for (y, se), items in sorted(seasons.items(), key=lambda kv: (-kv[0][0], -SEASON_ORDER.get(kv[0][1], 0))):
        items.sort(key=by_pop)
        label = items[0]["season"].get("label") if items else None
        _write(v1 / "seasons" / str(y) / f"{se}.json",
               {"year": y, "season": se, "label": label, "count": len(items), "data": items})
        season_index.append({"year": y, "season": se, "label": label, "count": len(items),
                             "api_url": f"v1/seasons/{y}/{se}.json"})
    _write(v1 / "seasons" / "index.json", {"data": season_index})

    cat_index = []
    for slug, info in sorted(cats.items(), key=lambda kv: -len(cat_items[kv[0]])):
        items = sorted(cat_items[slug], key=by_pop)
        pages = _paginate(v1, f"categories/{slug}", items, {"category": info})
        cat_index.append({**info, "count": len(items), "pages": pages, "api_url": f"v1/categories/{slug}/1.json"})
    _write(v1 / "categories" / "index.json", {"data": cat_index})

    type_index = []
    for tname, items in sorted(types.items(), key=lambda kv: -len(kv[1])):
        slug = slugify(tname)
        items.sort(key=by_pop)
        pages = _paginate(v1, f"types/{slug}", items, {"type": tname})
        type_index.append({"type": tname, "slug": slug, "count": len(items), "pages": pages,
                           "api_url": f"v1/types/{slug}/1.json"})
    _write(v1 / "types" / "index.json", {"data": type_index})

    search_rows.sort(key=lambda r: (r[8] is None or r[8] == 0, r[8] or 0))
    _write(v1 / "search.json", {
        "fields": ["id", "hebrew", "english", "romaji", "other_titles", "type", "year", "poster", "popularity"],
        "data": search_rows,
    })
    _write(v1 / "ids.json", {"count": len(summaries), "data": sorted(s["id"] for s in summaries)})
    schedule.sort(key=lambda x: (x["next_episode"]["airing_at"], by_pop(x)))
    _write(v1 / "schedule.json", {
        "note": "anime with a scheduled next episode, soonest first. next_episode.airing_at is UTC "
                "(source: AniList, anilist.co); broadcast is AniZone's regular Japanese TV slot (Asia/Tokyo)",
        "available": next_eps is not None,
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": len(schedule), "data": schedule})

    meta = {r["key"]: r["value"] for r in con.execute("SELECT key, value FROM meta")}
    _write(v1 / "index.json", {
        "name": "AniZone Open API",
        "version": __version__,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "data_crawled_at": meta.get("last_crawl"),
        "total_anime": n,
        "attribution": ATTRIBUTION,
        "note": "all paths are relative to the API base URL",
        "endpoints": {
            "anime": "/v1/anime/{id}.json",
            "top_popularity": "/v1/top/popularity/{page}.json",
            "top_israel": "/v1/top/israel/{page}.json",
            "top_mal": "/v1/top/mal/{page}.json",
            "seasons": "/v1/seasons/index.json",
            "season": "/v1/seasons/{year}/{season}.json",
            "categories": "/v1/categories/index.json",
            "category": "/v1/categories/{slug}/{page}.json",
            "types": "/v1/types/index.json",
            "type": "/v1/types/{slug}/{page}.json",
            "search_index": "/v1/search.json",
            "ids": "/v1/ids.json",
            "schedule": "/v1/schedule.json",
        },
    })

    # docs site + helpers
    if DOCS_DIR.exists():
        for f in DOCS_DIR.iterdir():
            if f.is_file():
                shutil.copy2(f, out / f.name)
    (out / ".nojekyll").write_text("")  # tell GitHub Pages to serve files as-is (much faster builds)

    files = sum(1 for _ in v1.rglob("*.json"))
    size = sum(f.stat().st_size for f in v1.rglob("*.json"))
    res = {"anime": n, "files": files, "size_mb": round(size / 1e6, 1), "out": str(out.resolve())}
    if size > 900e6:
        res["warning"] = "larger than ~900 MB: GitHub Pages allows up to 1 GB per site"
    return res
