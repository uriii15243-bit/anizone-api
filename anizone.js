/*!
 * AniZone Open API - tiny JavaScript client (no dependencies)
 * Usage:
 *   <script src="https://YOUR-USER.github.io/anizone-api/anizone.js"></script>
 *   const naruto = await AniZone.anime(20);
 *   const results = await AniZone.search("נארוטו");
 * Data courtesy of AniZone (https://anizone.co.il), used with permission.
 */
(function (root) {
  "use strict";
  var script = typeof document !== "undefined" && document.currentScript;
  var BASE = (script && script.src) ? script.src.replace(/[^/]*$/, "") : "./";

  var cache = {};
  function get(path) {
    var url = AniZone.base.replace(/\/?$/, "/") + path.replace(/^\//, "");
    if (!cache[url]) {
      cache[url] = fetch(url).then(function (r) {
        if (!r.ok) { delete cache[url]; throw new Error("AniZone API: " + r.status + " for " + path); }
        return r.json();
      });
    }
    return cache[url];
  }

  // Hebrew/Latin normalisation: drop niqqud, punctuation, case
  function norm(s) {
    return (s || "").toLowerCase()
      .replace(/[֑-ׇ]/g, "")
      .replace(/[׳״'"`´:;.,!?()\[\]{}\-_/\\|~·•]/g, " ")
      .replace(/\s+/g, " ").trim();
  }

  var index = null;
  function loadIndex() {
    if (!index) {
      index = get("v1/search.json").then(function (j) {
        return j.data.map(function (r) {
          return { id: r[0], hebrew: r[1], english: r[2], romaji: r[3], other: r[4], type: r[5],
                   year: r[6], poster: r[7], popularity: r[8],
                   _t: [norm(r[1]), norm(r[2]), norm(r[3]), norm(r[4])] };
        });
      });
    }
    return index;
  }

  var AniZone = {
    base: BASE,
    /** API info and totals */
    info: function () { return get("v1/index.json"); },
    /** Full details of one anime (id = MyAnimeList id) */
    anime: function (id) { return get("v1/anime/" + Number(id) + ".json"); },
    /** kind: "popularity" | "israel" | "mal" */
    top: function (kind, page) { return get("v1/top/" + (kind || "popularity") + "/" + (page || 1) + ".json"); },
    seasons: function () { return get("v1/seasons/index.json"); },
    /** season: "winter" | "spring" | "summer" | "fall" */
    season: function (year, season) { return get("v1/seasons/" + year + "/" + season + ".json"); },
    categories: function () { return get("v1/categories/index.json"); },
    category: function (slug, page) { return get("v1/categories/" + encodeURIComponent(slug) + "/" + (page || 1) + ".json"); },
    types: function () { return get("v1/types/index.json"); },
    type: function (slug, page) { return get("v1/types/" + slug + "/" + (page || 1) + ".json"); },
    /** Search by title (Hebrew / English / Japanese). Runs in the browser. */
    search: function (query, opts) {
      var limit = (opts && opts.limit) || 20;
      var q = norm(query);
      if (!q) return Promise.resolve([]);
      var words = q.split(" ");
      return loadIndex().then(function (rows) {
        var hits = [];
        for (var i = 0; i < rows.length; i++) {
          var r = rows[i], best = 0;
          for (var f = 0; f < 4; f++) {
            var t = r._t[f];
            if (!t) continue;
            var all = true;
            for (var w = 0; w < words.length; w++) if (t.indexOf(words[w]) < 0) { all = false; break; }
            if (!all) continue;
            var sc = t === q ? 100 : t.indexOf(q) === 0 ? 60 : (" " + t).indexOf(" " + q) >= 0 ? 40 : 20;
            if (sc < 100 && (" " + t + " ").indexOf(" " + q + " ") >= 0) sc += 15; // whole-word match
            if (f === 3 && sc < 100) sc = 20; // alternate titles: match, but don't outrank main titles
            if (f === 0) sc += 5; // prefer Hebrew title matches
            if (sc > best) best = sc;
          }
          if (best) hits.push([best, r]);
        }
        hits.sort(function (a, b) {
          return b[0] - a[0] || ((a[1].popularity || 1e9) - (b[1].popularity || 1e9));
        });
        return hits.slice(0, limit).map(function (h) {
          var r = h[1];
          return { id: r.id, titles: { hebrew: r.hebrew, english: r.english, romaji: r.romaji },
                   type: r.type, year: r.year, poster: r.poster, popularity: r.popularity,
                   api_url: "v1/anime/" + r.id + ".json" };
        });
      });
    },
    /** A random anime (full details) */
    random: function () {
      return get("v1/ids.json").then(function (j) {
        return AniZone.anime(j.data[Math.floor(Math.random() * j.data.length)]);
      });
    }
  };

  if (typeof module === "object" && module.exports) module.exports = AniZone;
  else root.AniZone = AniZone;
})(typeof self !== "undefined" ? self : this);
