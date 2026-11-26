"""
CLI:
  python -m anizone_api crawl  [--db anizone.db] [--delay 2] [--limit N] [--force] [--id 63382 ...]
  python -m anizone_api serve  [--db anizone.db] [--host 0.0.0.0] [--port 8000]
  python -m anizone_api export [--db anizone.db] [--out anime.jsonl]
  python -m anizone_api export-api [--db anizone.db] [--out public]   (static API for GitHub Pages)
  python -m anizone_api load-state --api-dir PUBLISHED_API [--state state/crawl_state.json.gz]
  python -m anizone_api save-state [--out state/crawl_state.json.gz]
"""
import argparse
import json
import logging
import os
import sys


def main(argv=None):
    p = argparse.ArgumentParser(prog="anizone_api", description="AniZone Open API (unofficial)")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("crawl", help="index anime pages from anizone.co.il into SQLite")
    c.add_argument("--db", default=os.environ.get("ANIZONE_DB", "anizone.db"))
    c.add_argument("--delay", type=float, default=2.0, help="seconds between requests (min 1.0)")
    c.add_argument("--limit", type=int, help="fetch at most N pages (for testing)")
    c.add_argument("--force", action="store_true", help="re-fetch even unchanged pages")
    c.add_argument("--id", type=int, nargs="*", help="only these anime ids")
    c.add_argument("--user-agent", help="identify yourself (put your contact/repo URL here)")
    c.add_argument("--all", action="store_true",
                   help="also find anime missing from the sitemap, using the MyAnimeList id list")
    c.add_argument("--no-follow", action="store_true", help="don't follow links to other anime pages")
    c.add_argument("--adopt-existing", action="store_true",
                   help="sitemap pages never seen before but already in the database count as up to date "
                        "(first run on a new machine without a state file)")
    c.add_argument("--refresh", type=int, default=0,
                   help="also re-fetch up to N known anime without a sitemap date "
                        "(airing first, then the longest unchecked) - a daily rotation")

    s = sub.add_parser("serve", help="run the REST API")
    s.add_argument("--db", default=os.environ.get("ANIZONE_DB", "anizone.db"))
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)

    e = sub.add_parser("export", help="dump the database to JSON Lines")
    e.add_argument("--db", default=os.environ.get("ANIZONE_DB", "anizone.db"))
    e.add_argument("--out", default="anime.jsonl")

    w = sub.add_parser("export-api", help="build the public static JSON API into a folder (for GitHub Pages)")
    w.add_argument("--db", default=os.environ.get("ANIZONE_DB", "anizone.db"))
    w.add_argument("--out", default="public")
    w.add_argument("--no-airing", action="store_true", help="skip next-episode dates from AniList")
    w.add_argument("--min-israel-votes", type=int, default=5,
                   help="minimum Israeli ratings for the /top/israel list")

    i = sub.add_parser("load-state", help="rebuild a database from a published API folder + state file")
    i.add_argument("--db", default=os.environ.get("ANIZONE_DB", "anizone.db"))
    i.add_argument("--api-dir", required=True, help="folder that contains v1/ (the published API)")
    i.add_argument("--state", default="state/crawl_state.json.gz")

    v = sub.add_parser("save-state", help="save the crawl state (seen URLs, lastmod, 404s) to a small file")
    v.add_argument("--db", default=os.environ.get("ANIZONE_DB", "anizone.db"))
    v.add_argument("--out", default="state/crawl_state.json.gz")

    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if a.cmd == "crawl":
        from .crawler import DEFAULT_UA, Crawler
        from .parser import BASE_URL
        cr = Crawler(a.db, delay=a.delay, user_agent=a.user_agent or DEFAULT_UA, adopt_existing=a.adopt_existing)
        urls = [(f"{BASE_URL}/anime/{i}", None) for i in a.id] if a.id else None
        extra = []
        if a.all and not a.id:
            from .mal_ids import load_mal_ids
            extra = load_mal_ids(os.path.join(os.path.dirname(os.path.abspath(a.db)), "mal_ids.json"))
        print(json.dumps(cr.run(limit=a.limit, force=a.force or bool(a.id), urls=urls,
                                extra_ids=extra, follow_links=not a.no_follow and not a.id,
                                refresh=a.refresh), indent=2))

    elif a.cmd == "serve":
        os.environ["ANIZONE_DB"] = a.db
        import uvicorn
        uvicorn.run("anizone_api.api:app", host=a.host, port=a.port)

    elif a.cmd == "export":
        from .db import connect
        con = connect(a.db, readonly=True)
        n = 0
        with open(a.out, "w", encoding="utf-8") as f:
            for row in con.execute("SELECT data FROM anime ORDER BY id"):
                f.write(row["data"] + "\n")
                n += 1
        print(f"wrote {n} anime to {a.out}")

    elif a.cmd == "export-api":
        from .static_api import export_static_api
        from .airing import fetch_next_episodes
        res = export_static_api(a.db, a.out, a.min_israel_votes,
                                airing_fetch=None if a.no_airing else fetch_next_episodes)
        print(json.dumps(res, indent=2, ensure_ascii=False))
        print(f"\nPreview:  python -m http.server 8080 --directory {a.out}   ->  http://localhost:8080")

    elif a.cmd == "load-state":
        from .state import load_state
        print(json.dumps(load_state(a.db, a.api_dir, a.state), indent=2))

    elif a.cmd == "save-state":
        from .state import save_state
        print(json.dumps(save_state(a.db, a.out), indent=2))


if __name__ == "__main__":
    sys.exit(main())
