"""Exact next-episode dates from AniList's free public GraphQL API.

AniZone only lists a show's regular weekly TV slot, which keeps showing even
when a show is on a break. AniList keeps the real next episode (number + air
time), and has none when nothing is scheduled. Looked up by MAL id (= AniZone id).
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

import requests

ANILIST_URL = "https://graphql.anilist.co"
QUERY = """query ($ids: [Int]) {
  Page(page: 1, perPage: 50) {
    media(idMal_in: $ids, type: ANIME) { idMal nextAiringEpisode { episode airingAt } }
  }
}"""


def _post(session, ids, sleep, tries=4):
    for attempt in range(tries):
        try:
            r = session.post(ANILIST_URL, json={"query": QUERY, "variables": {"ids": ids}},
                             headers={"Accept": "application/json"}, timeout=30)
        except requests.RequestException:
            r = None
        if r is not None and r.status_code == 200:
            return r.json()["data"]["Page"]["media"]
        wait = 5 * (attempt + 1)
        if r is not None and r.status_code == 429:
            wait = int(r.headers.get("Retry-After", 60)) + 1
        sleep(wait)
    raise RuntimeError("AniList did not answer")


def fetch_next_episodes(mal_ids, session=None, sleep=time.sleep, pause=2.2):
    """Return {mal_id: {"episode", "airing_at"} or None} for every id AniList knows.

    None means AniList has no upcoming episode (finished, or on a break).
    Ids AniList doesn't know are left out. Returns None if AniList can't be reached.
    """
    session = session or requests.Session()
    ids = sorted({int(i) for i in mal_ids})
    out: dict[int, dict | None] = {}
    try:
        for n in range(0, len(ids), 50):
            if n:
                sleep(pause)  # AniList allows ~30 requests a minute
            for m in _post(session, ids[n:n + 50], sleep):
                if not m.get("idMal"):
                    continue
                nx = m.get("nextAiringEpisode")
                out[int(m["idMal"])] = None if not nx else {
                    "episode": nx["episode"],
                    "airing_at": datetime.fromtimestamp(nx["airingAt"], timezone.utc).isoformat(timespec="seconds"),
                }
    except Exception:
        return None
    return out
