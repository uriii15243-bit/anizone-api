"""
Polite crawler for anizone.co.il anime pages.

- Discovers pages from the public sitemaps (sitemap.xml -> sitemap-anime-*.xml).
- Obeys robots.txt and never touches disallowed paths (/search, query strings...).
- One request at a time, with a fixed delay (minimum 1s, default 2s),
  exponential backoff on 429/5xx, and Retry-After support.
- Incremental: a page is re-fetched only when its sitemap <lastmod> changed.
"""
from __future__ import annotations

import logging
import random
import time
import xml.etree.ElementTree as ET
from collections import deque
from dataclasses import dataclass
from typing import Callable, Iterable
from urllib import robotparser

import requests

from . import __version__
from .db import connect, get_state, set_meta, set_state, upsert_anime, now
from .parser import BASE_URL, _ID_RE, extract_anime_links, parse_anime_page

log = logging.getLogger("anizone.crawler")

DEFAULT_UA = (f"AniZoneOpenAPI/{__version__} (+https://github.com/YOUR_USER/anizone-api; "
              "open-source metadata indexer)")
MIN_DELAY = 1.0
NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


@dataclass
class Response:
    status: int
    text: str
    headers: dict


Fetcher = Callable[[str], Response]


def requests_fetcher(user_agent: str = DEFAULT_UA, timeout: float = 30.0) -> Fetcher:
    s = requests.Session()
    s.headers.update({"User-Agent": user_agent, "Accept-Language": "he,en;q=0.8"})

    def fetch(url: str) -> Response:
        r = s.get(url, timeout=timeout)
        r.encoding = r.encoding or "utf-8"
        return Response(r.status_code, r.text, dict(r.headers))

    return fetch


class Crawler:
    def __init__(self, db_path="anizone.db", fetcher: Fetcher | None = None,
                 delay: float = 2.0, user_agent: str = DEFAULT_UA, max_retries: int = 4,
                 sleep: Callable[[float], None] = time.sleep, respect_robots: bool = True,
                 adopt_existing: bool = False):
        self.adopt_existing = adopt_existing
        self.con = connect(db_path)
        self.fetch_raw = fetcher or requests_fetcher(user_agent)
        self.delay = max(MIN_DELAY, float(delay))
        self.user_agent = user_agent
        self.max_retries = max_retries
        self.sleep = sleep
        self._last = 0.0
        self.robots: robotparser.RobotFileParser | None = None
        if respect_robots:
            self._load_robots()

    # ------------------------------------------------------------ http
    def _load_robots(self) -> None:
        rp = robotparser.RobotFileParser()
        try:
            r = self._get(f"{BASE_URL}/robots.txt", check_robots=False)
            rp.parse(r.text.splitlines() if r.status == 200 else [])
        except Exception as e:  # unreachable robots -> be conservative
            log.warning("robots.txt unavailable (%s); refusing to crawl", e)
            rp.parse(["User-agent: *", "Disallow: /"])
        self.robots = rp

    def allowed(self, url: str) -> bool:
        if "?" in url:  # robots.txt disallows /*?*
            return False
        return self.robots is None or self.robots.can_fetch(self.user_agent, url)

    def _throttle(self) -> None:
        wait = self.delay - (time.monotonic() - self._last)
        if wait > 0:
            self.sleep(wait)
        self._last = time.monotonic()

    def _get(self, url: str, check_robots: bool = True) -> Response:
        if check_robots and not self.allowed(url):
            raise PermissionError(f"robots.txt disallows {url}")
        backoff = self.delay * 2
        for attempt in range(self.max_retries + 1):
            self._throttle()
            try:
                r = self.fetch_raw(url)
            except requests.RequestException as e:
                if attempt == self.max_retries:
                    raise
                log.warning("network error %s (%s), retrying", url, e)
                self.sleep(backoff + random.random())
                backoff *= 2
                continue
            if r.status in (429, 500, 502, 503, 504) and attempt < self.max_retries:
                ra = (r.headers or {}).get("Retry-After") or (r.headers or {}).get("retry-after")
                wait = float(ra) if ra and str(ra).isdigit() else backoff
                log.warning("HTTP %s for %s, waiting %.0fs", r.status, url, wait)
                self.sleep(min(wait, 900) + random.random())
                backoff *= 2
                continue
            return r
        return r

    # ------------------------------------------------------------ sitemaps
    def discover(self) -> list[tuple[str, str | None]]:
        """Return [(anime_url, lastmod)] from the sitemaps."""
        idx = self._get(f"{BASE_URL}/sitemap.xml")
        root = ET.fromstring(idx.text.encode("utf-8"))
        children = [e.text.strip() for e in root.findall("sm:sitemap/sm:loc", NS) if e.text]
        anime_maps = [u for u in children if "sitemap-anime" in u] or children
        out: dict[str, str | None] = {}
        for sm in anime_maps:
            r = self._get(sm)
            if r.status != 200:
                log.error("sitemap %s -> HTTP %s", sm, r.status)
                continue
            for url_el in ET.fromstring(r.text.encode("utf-8")).findall("sm:url", NS):
                loc = url_el.findtext("sm:loc", default="", namespaces=NS).strip()
                if _ID_RE.search(loc):
                    out[loc] = url_el.findtext("sm:lastmod", default=None, namespaces=NS)
            log.info("sitemap %s: %d anime so far", sm, len(out))
        return list(out.items())

    # ------------------------------------------------------------ crawl
    def crawl_one(self, url: str, lastmod: str | None = None) -> tuple[dict | None, set[int]]:
        """Fetch + parse + store one page. Returns (anime or None, ids linked from the page)."""
        m = _ID_RE.search(url)
        url_id = int(m.group(1)) if m else None
        try:
            r = self._get(url)
        except PermissionError as e:
            log.info("%s", e)
            return None, set()
        except Exception as e:
            set_state(self.con, url, url_id, None, -1, repr(e))
            log.error("failed %s: %r", url, e)
            return None, set()
        if r.status != 200:
            set_state(self.con, url, url_id, None, r.status, f"HTTP {r.status}")
            if r.status != 404:
                log.warning("HTTP %s %s", r.status, url)
            return None, set()
        links = extract_anime_links(r.text)
        try:
            anime = parse_anime_page(r.text, url)
        except Exception as e:
            set_state(self.con, url, url_id, None, r.status, f"parse error: {e!r}")
            log.exception("parse error %s", url)
            return None, links
        if not anime.get("id"):
            set_state(self.con, url, url_id, None, r.status, "no id")
            return None, links
        if lastmod is None:  # a refresh: keep the sitemap date we already know
            prev = get_state(self.con, url)
            lastmod = prev["lastmod"] if prev else None
        upsert_anime(self.con, anime, lastmod)
        set_state(self.con, url, anime["id"], lastmod, 200)
        return anime, links

    # ------------------------------------------------------------ planning
    def _needs_fetch(self, url: str, anime_id: int | None, lastmod: str | None, force: bool) -> bool:
        if force:
            return True
        st = get_state(self.con, url)
        if lastmod:  # sitemap page: re-fetch only when lastmod changed
            if st is None and self.adopt_existing and anime_id is not None and self.con.execute(
                    "SELECT 1 FROM anime WHERE id = ?", (anime_id,)).fetchone():
                # first run without a state file: trust the already-published data
                set_state(self.con, url, anime_id, lastmod, 200)
                return False
            return not (st and st["status"] == 200 and st["lastmod"] == lastmod)
        # page outside the sitemap (no lastmod): fetch once
        if st and st["status"] in (200, 404):
            return False
        if anime_id is not None and self.con.execute(
                "SELECT 1 FROM anime WHERE id = ?", (anime_id,)).fetchone():
            return False
        return True

    def run(self, limit: int | None = None, force: bool = False,
            urls: Iterable[tuple[str, str | None]] | None = None,
            extra_ids: Iterable[int] = (), follow_links: bool = True, refresh: int = 0) -> dict:
        """Crawl sitemap pages, then `extra_ids`, then any anime linked from
        fetched pages (follow_links) - until nothing new is left.

        refresh=N also re-fetches up to N known anime that have no sitemap date:
        every airing anime first, then the ones checked longest ago (a rotation)."""
        log.info("AniZone Open API v%s", __version__)
        items = list(urls) if urls is not None else self.discover()
        queue: deque[tuple[str, str | None]] = deque()
        seen: set[int] = set()
        skipped = 0

        def add(url: str, lm: str | None) -> bool:
            nonlocal skipped
            m = _ID_RE.search(url)
            aid = int(m.group(1)) if m else None
            if aid is not None:
                if aid in seen:
                    return False
                seen.add(aid)
            if self._needs_fetch(url, aid, lm, force):
                queue.append((url, lm))
                return True
            skipped += 1
            return False

        for url, lm in items:
            add(url, lm)
        n_sitemap = len(queue)
        extra = sum(add(f"{BASE_URL}/anime/{i}", None) for i in extra_ids)
        refreshing = 0
        if refresh:
            queued = {int(m.group(1)) for u, _ in queue if (m := _ID_RE.search(u))}
            rows = self.con.execute(
                "SELECT a.id, (SELECT url FROM crawl_state c WHERE c.id = a.id AND c.status = 200"
                "  ORDER BY c.lastmod IS NULL LIMIT 1) AS url"
                " FROM anime a LEFT JOIN (SELECT id, MAX(fetched_at) AS f FROM crawl_state"
                "  WHERE status = 200 GROUP BY id) s ON s.id = a.id"
                " ORDER BY (a.status = 'בשידור') DESC, s.f IS NOT NULL, s.f, a.popularity IS NULL, a.popularity"
            ).fetchall()
            for r in rows:
                if refreshing >= refresh:
                    break
                if r["id"] in queued:
                    continue
                queue.append((r["url"] or f"{BASE_URL}/anime/{r['id']}", None))
                queued.add(r["id"])
                seen.add(r["id"])
                refreshing += 1
        # anime already known from earlier runs are "seen" too (their links were followed then)
        log.info("%d pages in sitemaps (%d to fetch), %d extra ids to try, %d to refresh, %d already up to date",
                 len(items), n_sitemap, extra, refreshing, skipped)
        log.info("~%.1f h at %.1fs/page (more may be discovered from links)",
                 len(queue) * self.delay / 3600, self.delay)

        ok = missing = fail = discovered = done = 0
        while queue:
            if limit and done >= limit:
                break
            url, lm = queue.popleft()
            anime, links = self.crawl_one(url, lm)
            done += 1
            if anime:
                ok += 1
            else:
                st = get_state(self.con, url)
                if st and st["status"] == 404:
                    missing += 1
                else:
                    fail += 1
            if follow_links:
                for lid in links:
                    if add(f"{BASE_URL}/anime/{lid}", None):
                        discovered += 1
            if done % 50 == 0:
                log.info("progress %d done, %d left (ok=%d, not on site=%d, failed=%d, found via links=%d)",
                         done, len(queue), ok, missing, fail, discovered)
        set_meta(self.con, "last_crawl", now())
        set_meta(self.con, "sitemap_total", len(items))
        total = self.con.execute("SELECT COUNT(*) FROM anime").fetchone()[0]
        return {"in_sitemaps": len(items), "refreshed": refreshing, "fetched": ok, "not_on_site": missing, "failed": fail,
                "found_via_links": discovered, "already_up_to_date": skipped,
                "left_in_queue": len(queue), "total_in_database": total}
