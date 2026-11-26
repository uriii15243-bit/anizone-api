"""
Parse a single AniZone anime page (https://anizone.co.il/anime/{id}/{slug})
into a plain dict.

The page is a Next.js (App Router) page. The parser reads three sources,
from most to least structured, and merges them:

1. JSON-LD (<script type="application/ld+json">): name, alternate names,
   genres, studio, producers, episode count, air date, external links.
2. The React Server Components payload (self.__next_f.push(...)): the
   "anime" object holding Hebrew/English/Japanese titles and the Hebrew synopsis.
3. The server-rendered HTML: scores, rank, season, broadcast, status,
   the "מידע" (info) block, characters & voice actors, staff.

Deliberately NOT collected: user reviews, usernames and avatars
(personal data of AniZone users; the site's terms forbid collecting it).
"""
from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag

BASE_URL = "https://anizone.co.il"

SEASON_HE = {"חורף": "winter", "אביב": "spring", "קיץ": "summer", "סתיו": "fall"}
DAYS_HE = {
    "ראשון": "sunday", "שני": "monday", "שלישי": "tuesday", "רביעי": "wednesday",
    "חמישי": "thursday", "שישי": "friday", "שבת": "saturday",
}
# Hebrew info labels -> output keys
INFO_LABELS = {
    "סוג": "type",
    "פרקים": "episodes",
    "קטגוריה": "category",
    "תת קטגוריה": "subcategory",
    "דמוגרפיה": "demographic",
    "דקות": "duration_minutes",
    "מפיקים": "producers",
    "זכויות": "licensors",
    "סטודיו": "studios",
    "מקור": "source",
    "דירוג גיל": "rating",
}
NOT_SPECIFIED = {"לא צויין", "לא צוין", "לא ידוע", "-", ""}

_ID_RE = re.compile(r"/anime/(\d+)(?:/([^/?#]+))?")
_NUM_RE = re.compile(r"[\d.,]+")


# ---------------------------------------------------------------- helpers
def _text(el: Tag | None) -> str:
    if el is None:
        return ""
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip()


def _num(s: str | None, as_float: bool = False):
    if not s:
        return None
    m = _NUM_RE.search(s)
    if not m:
        return None
    raw = m.group(0).replace(",", "").rstrip(".")
    try:
        return float(raw) if as_float else int(float(raw))
    except ValueError:
        return None


def _clean(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    return None if v in NOT_SPECIFIED else v


def _split_bilingual(v: str | None) -> dict | None:
    """'Fantasy / פנטזיה' -> {'en': 'Fantasy', 'he': 'פנטזיה'}"""
    v = _clean(v)
    if not v:
        return None
    if " / " in v:
        en, he = v.split(" / ", 1)
        return {"en": en.strip(), "he": he.strip()}
    has_he = bool(re.search(r"[֐-׿]", v))
    return {"en": None if has_he else v, "he": v if has_he else None}


def _split_bilingual_list(v: str | None) -> list[dict]:
    """'Action / אקשן, Adventure / הרפתקאות' -> [{'en':'Action','he':'אקשן'}, ...]"""
    v = _clean(v)
    if not v:
        return []
    return [b for b in (_split_bilingual(part) for part in re.split(r",\s*(?=[^,]*/)", v)) if b] \
        if " / " in v else [b for b in (_split_bilingual(x) for x in v.split(",")) if b]


def _split_list(v: str | None) -> list[str]:
    v = _clean(v)
    return [p.strip() for p in v.split(",") if p.strip()] if v else []


def _heading(soup: BeautifulSoup, title: str) -> Tag | None:
    """Prefer the real <h2> (desktop layout, untruncated) over role=heading."""
    for h in soup.find_all("h2"):
        if _text(h) == title:
            return h
    for h in soup.find_all(attrs={"role": "heading"}):
        if _text(h) == title:
            return h
    return None


def _section_body(heading: Tag) -> Tag | None:
    """The content block that follows a section heading.

    Real layout: <div><div><h2>X</h2><svg/></div><div>...items...</div></div>
    or           <div><h2>X</h2><svg/><div>...</div></div>
    Icons (svg) and buttons next to the heading are skipped.
    """
    node = heading
    for _ in range(3):
        for sib in node.find_next_siblings():
            if sib.name not in ("svg", "button", "span"):
                return sib
        node = node.parent
        if node is None:
            return None
    return None


def _direct_children(el: Tag) -> list[Tag]:
    return [c for c in el.children if isinstance(c, Tag)]


# ---------------------------------------------------------------- sources
def extract_rsc_payload(html: str) -> str:
    """Concatenate all self.__next_f.push([1,"..."]) string chunks."""
    out = []
    for m in re.finditer(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)', html, re.S):
        try:
            out.append(json.loads(m.group(1)))
        except json.JSONDecodeError:
            continue
    return "".join(out)


_ROW_RE = re.compile(rb"([0-9a-f]+):T([0-9a-f]+),")


def extract_rsc_text_rows(payload: str) -> dict[str, str]:
    """Long strings are sent as separate 'text rows':  <id>:T<hex byte length>,<text>
    and referenced elsewhere as "$<id>". The text has no terminating newline,
    so the length (in UTF-8 bytes) is the only way to know where it ends."""
    data = payload.encode("utf-8")
    rows: dict[str, str] = {}
    pos = 0
    while True:
        m = _ROW_RE.search(data, pos)
        if not m:
            break
        # a row id must begin a row: at the start, after a newline,
        # or right where the previous text row ended
        if not (m.start() == 0 or m.start() == pos or data[m.start() - 1] == 0x0A):
            pos = m.start() + 1
            continue
        n = int(m.group(2), 16)
        rows.setdefault(m.group(1).decode(), data[m.end():m.end() + n].decode("utf-8", errors="replace"))
        pos = m.end() + n
    return rows


def _resolve_refs(obj, rows: dict[str, str]):
    if isinstance(obj, str):
        m = re.fullmatch(r"\$([0-9a-f]+)", obj)
        if m:
            return rows.get(m.group(1))  # unresolvable reference -> None
        if obj.startswith("$") and not obj.startswith("$$") and ":" in obj:
            return None  # internal path reference like "$15:props:children"
        return obj
    if isinstance(obj, list):
        return [_resolve_refs(x, rows) for x in obj]
    if isinstance(obj, dict):
        return {k: _resolve_refs(v, rows) for k, v in obj.items()}
    return obj


def _balanced_object(s: str, start: int) -> str | None:
    depth, in_str, esc = 0, False, False
    for i in range(start, len(s)):
        c = s[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return s[start:i + 1]
    return None


def extract_rsc_anime(payload: str) -> dict:
    """Merge every `"anime":{...}` object found in the RSC payload.

    The page holds a small one ({mal_id, anizone_id, episodes, titles}) and
    a full one (titles + synopsis/synopsis_hebrew/background...). Objects for
    *other* anime (related cards) carry a different mal_id and are skipped.
    """
    merged: dict = {}
    page_id = None
    for m in re.finditer(r'"anime":\{', payload):
        raw = _balanced_object(payload, m.end() - 1)
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        oid = obj.get("mal_id")
        if oid is not None:
            if page_id is None:
                page_id = oid
            elif oid != page_id:
                continue  # a related-anime card
        for k, v in obj.items():
            if v not in (None, [], "") or k not in merged:
                merged[k] = v
    return _resolve_refs(merged, extract_rsc_text_rows(payload)) if merged else merged


def extract_json_ld(soup: BeautifulSoup) -> dict:
    """Return the TVSeries/Movie node from the JSON-LD graph."""
    for sc in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(sc.string or "")
        except json.JSONDecodeError:
            continue
        nodes = data.get("@graph", [data]) if isinstance(data, dict) else data
        for n in nodes if isinstance(nodes, list) else []:
            if isinstance(n, dict) and n.get("@type") in (
                "TVSeries", "Movie", "CreativeWork", "CreativeWorkSeries", "VideoObject"
            ) and n.get("name"):
                return n
    return {}


# ---------------------------------------------------------------- DOM parts
def parse_scores(soup: BeautifulSoup) -> dict:
    out: dict = {}
    box = soup.find(attrs={"aria-label": "ציונים"})
    root = box or soup
    for span in root.find_all("span"):
        label = _text(span)
        if label not in ("ציון במאל", "ציון ישראל"):
            continue
        sibs = [s for s in span.find_next_siblings("span")]
        val = _num(_text(sibs[0]), as_float=True) if sibs else None
        cnt = _num(_text(sibs[1])) if len(sibs) > 1 else None
        key = "mal" if label == "ציון במאל" else "israel"
        if not cnt and not val:
            val = None  # "0.00 / 10" just means nobody rated it yet
        if f"{key}_score" not in out:
            out[f"{key}_score"] = val
            out[f"{key}_scored_by"] = cnt
    # rank / popularity / members / favorites
    labels = {"דירוג": "rank", "פופולריות": "popularity", "צופים": "members", "מועדפים": "favorites"}
    for dt in soup.find_all("dt"):
        key = labels.get(_text(dt))
        if key and key not in out:
            dd = dt.find_next_sibling("dd")
            out[key] = _num(_text(dd))
    return out


def parse_broadcast(soup: BeautifulSoup) -> dict:
    out: dict = {}
    pairs: list[tuple[str, Tag]] = []
    for dt in soup.find_all("dt"):
        dd = dt.find_next_sibling("dd")
        if dd is not None:
            pairs.append((_text(dt), dd))
    # mobile layout: <div><p>label</p><span>value</span></div>
    for p in soup.find_all("p"):
        sp = p.find_next_sibling("span")
        if sp is not None:
            pairs.append((_text(p), sp))

    for label, val in pairs:
        if label == "עונה" and "season" not in out:
            a = val.find("a")
            href = a.get("href", "") if a else ""
            m = re.search(r"/seasons/(\d{4})/(\w+)", href)
            text = _text(val)
            out["season"] = {
                "label": text or None,
                "year": int(m.group(1)) if m else _num(text),
                "season": m.group(2) if m else next(
                    (v for k, v in SEASON_HE.items() if k in text), None),
            }
        elif label == "זמני שידור" and "broadcast" not in out:
            text = _text(val)
            day = next((v for k, v in DAYS_HE.items() if text.startswith(k)), None)
            tm = re.search(r"\b(\d{1,2}:\d{2})\b", text)
            out["broadcast"] = {"label": text, "day": day, "time": tm.group(1) if tm else None,
                                "timezone": "Asia/Jerusalem"}
        elif label == "סטטוס" and "status" not in out:
            out["status"] = _clean(_text(val))
    return out


def parse_info(soup: BeautifulSoup) -> dict:
    out: dict = {}
    h = _heading(soup, "מידע")
    body = _section_body(h) if h else None
    if body is None:
        return out
    for row in body.find_all("div"):
        p, sp = row.find("p", recursive=False), row.find("span", recursive=False)
        if p is None or sp is None:
            continue
        key = INFO_LABELS.get(_text(p))
        if not key or key in out:
            continue
        val = _text(sp)
        if key in ("episodes", "duration_minutes"):
            out[key] = _num(val)
        elif key in ("category", "subcategory"):
            out[key] = _split_bilingual_list(val)
        elif key == "demographic":
            out[key] = _split_bilingual(val)
        elif key in ("producers", "licensors", "studios"):
            out[key] = _split_list(val)
        else:
            out[key] = _clean(val)
    return out


def parse_alt_titles(soup: BeautifulSoup) -> dict:
    out: dict = {}
    h = _heading(soup, "שמות נוספים")
    body = _section_body(h) if h else None
    if body is None:
        return out
    lang_map = {"יפנית": "japanese", "אנגלית": "english", "נרדפים": "synonyms",
                "שמות נוספים": "synonyms", "עברית": "hebrew"}
    for p in body.find_all("p"):
        label_el = p.find("span")
        val_el = p.find("bdi") or p
        label = _text(label_el).rstrip(":").strip() if label_el else ""
        value = _text(val_el)
        if label_el is not None and val_el is p:
            value = value.replace(_text(label_el), "", 1).strip()
        key = lang_map.get(label, label or "other")
        out.setdefault(key, []).append(value)
    return out


def _img(el: Tag | None) -> str | None:
    if el is None:
        return None
    src = el.get("src")
    if not src or "person-unknown" in src or "questionmark" in src:
        return None
    return src if src.startswith("http") else BASE_URL + src


def parse_characters(soup: BeautifulSoup) -> list[dict]:
    h = _heading(soup, "דמויות ומדבבים")
    body = _section_body(h) if h else None
    if body is None:
        return []
    chars = []
    for item in _direct_children(body):
        kids = _direct_children(item)
        if not kids:
            continue
        char: dict[str, Any] = {"name": None, "role": None, "image": None, "voice_actors": []}
        for k in kids:
            if k.name == "img" and char["image"] is None and char["name"] is None:
                char["image"] = _img(k)
                char["name"] = (k.get("alt") or "").strip() or None
            elif k.name == "div" and k.find("img") is None:
                ps = k.find_all("p")
                if ps:
                    char["name"] = char["name"] or _text(ps[0])
                    char["role"] = _text(ps[1]) if len(ps) > 1 else None
            elif k.name == "div":
                img = k.find("img")
                ps = k.find_all("p")
                name = (img.get("alt") or "").strip() if img else ""
                char["voice_actors"].append({
                    "name": name or (_text(ps[0]) if ps else None),
                    "language": _text(ps[1]) if len(ps) > 1 else None,
                    "image": _img(img),
                })
        if char["name"]:
            chars.append(char)
    return chars


def parse_staff(soup: BeautifulSoup) -> list[dict]:
    # The site titles the staff section "מפיקים" (also used as an info label)
    h = _heading(soup, "מפיקים")
    body = _section_body(h) if h else None
    if body is None:
        return []
    staff = []
    for item in _direct_children(body):
        img = item.find("img")
        ps = item.find_all("p")
        name = (img.get("alt") or "").strip() if img else ""
        name = name or (_text(ps[0]) if ps else "")
        if not name:
            continue
        role = _text(ps[1]) if len(ps) > 1 else None
        staff.append({
            "name": name,
            "role": role,
            "roles": [r.strip() for r in role.split(",") if r.strip()] if role else [],
            "image": _img(img),
        })
    return staff


def parse_trailer(soup: BeautifulSoup) -> dict | None:
    for img in soup.find_all("img"):
        m = re.search(r"img\.youtube\.com/vi/([\w-]{6,})/", img.get("src", ""))
        if m:
            vid = m.group(1)
            return {"youtube_id": vid, "url": f"https://www.youtube.com/watch?v={vid}",
                    "embed_url": f"https://www.youtube.com/embed/{vid}"}
    return None


def parse_review_stats(soup: BeautifulSoup) -> dict | None:
    """Aggregate numbers only (no usernames / review text)."""
    h = _heading(soup, "ביקורות הקהילה")
    if h is None:
        return None
    p = h.find_next("p")
    text = _text(p)
    nums = [int(n) for n in re.findall(r"\d+", text)]
    return {"ratings": nums[0] if nums else None,
            "written_reviews": nums[1] if len(nums) > 1 else None}


# only real links to AniZone pages: href="/anime/..", "href":"/anime/.." (RSC), or absolute anizone URLs.
# (not image paths like cdn.myanimelist.net/images/anime/1000/...)
_LINK_RE = re.compile(r"""(?:anizone\.co\.il|href=\\?["']|\\?"href\\?":\\?")/anime/(\d+)(?=[/"'\\#])""")


def extract_anime_links(html: str) -> set[int]:
    """IDs of every anime linked from a page (related cards, recommendations...).
    Lets the crawler discover pages that are missing from the sitemap."""
    return {int(m.group(1)) for m in _LINK_RE.finditer(html)}


# ---------------------------------------------------------------- main
def parse_anime_page(html: str, url: str | None = None) -> dict:
    soup = BeautifulSoup(html, "lxml")
    ld = extract_json_ld(soup)
    rsc = extract_rsc_anime(extract_rsc_payload(html))

    canonical = None
    link = soup.find("link", rel="canonical")
    if link and link.get("href"):
        canonical = link["href"]
    page_url = canonical or url or ld.get("url")
    m = _ID_RE.search(urlparse(page_url).path) if page_url else None
    anime_id = rsc.get("mal_id") or rsc.get("anizone_id") or (int(m.group(1)) if m else None)

    h1 = soup.find("h1") or soup.find(attrs={"role": "heading", "aria-level": "1"})
    og = {t.get("property"): t.get("content") for t in soup.find_all("meta", property=True)}

    alt = parse_alt_titles(soup)
    info = parse_info(soup)
    sched = parse_broadcast(soup)
    scores = parse_scores(soup)

    title_he = rsc.get("title_hebrew") or ld.get("name") or _text(h1) or None
    known = list(dict.fromkeys(rsc.get("known_titles") or []))
    title_jp = (alt.get("japanese") or [None])[0] or next(
        (t for t in known if re.search(r"[぀-ヿ一-鿿]", t)), None)

    same_as = ld.get("sameAs") or []
    mal_url = next((u for u in same_as if "myanimelist.net/anime/" in u), None)
    if anime_id and not mal_url:
        mal_url = f"https://myanimelist.net/anime/{anime_id}"

    studio_ld = ld.get("productionCompany")
    studios = info.get("studios") or (
        [studio_ld["name"]] if isinstance(studio_ld, dict) and studio_ld.get("name") else [])
    producers = info.get("producers") or [
        p.get("name") for p in ld.get("producer", []) if isinstance(p, dict) and p.get("name")]

    date_pub = ld.get("datePublished")
    aired_from = date_pub[:10] if isinstance(date_pub, str) else None

    return {
        "id": anime_id,
        "mal_id": rsc.get("mal_id") or anime_id,
        "anizone_id": rsc.get("anizone_id"),
        "url": page_url,
        "slug": m.group(2) if m and m.group(2) else None,
        "titles": {
            "hebrew": title_he,
            "english": rsc.get("title_english") or (
                (ld.get("alternateName") or [None])[0] if ld else None),
            "romaji": rsc.get("title") or None,
            "japanese": title_jp,
            "synonyms": list(dict.fromkeys((rsc.get("title_synonyms") or []) + alt.get("synonyms", []))),
            "community": rsc.get("community_titles") or [],
            "known": known,
        },
        "synopsis_hebrew": rsc.get("synopsis_hebrew") or ld.get("description") or None,
        "background_hebrew": rsc.get("background_hebrew") or None,
        "type": info.get("type"),
        "episodes": info.get("episodes") or ld.get("numberOfEpisodes") or rsc.get("episodes"),
        "duration_minutes": info.get("duration_minutes"),
        "status": sched.get("status"),
        "aired_from": aired_from,
        "season": sched.get("season"),
        "broadcast": sched.get("broadcast"),
        "categories": info.get("category") or [],
        "subcategories": info.get("subcategory") or [],
        "demographic": info.get("demographic"),
        "genres": ld.get("genre") or [],
        "studios": studios,
        "producers": producers,
        "licensors": info.get("licensors") or [],
        "source": info.get("source"),
        "rating": info.get("rating"),
        "scores": {
            "mal": scores.get("mal_score"),
            "mal_scored_by": scores.get("mal_scored_by"),
            "israel": scores.get("israel_score"),
            "israel_scored_by": scores.get("israel_scored_by"),
            "rank": scores.get("rank"),
            "popularity": scores.get("popularity"),
            "members": scores.get("members"),
            "favorites": scores.get("favorites"),
        },
        "community_reviews": parse_review_stats(soup),
        "images": {
            "poster": ld.get("image") or og.get("og:image"),
        },
        "trailer": parse_trailer(soup),
        "characters": parse_characters(soup),
        "staff": parse_staff(soup),
        "external_links": {"myanimelist": mal_url, "other": [u for u in same_as if u != mal_url]},
    }
