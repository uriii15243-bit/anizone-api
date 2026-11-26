/* Broadcast schedule + personal watchlist for "אנימה בעברית".
   Loaded before app.js; uses the helpers app.js exposes as window.AZ at call time. */
(function () {
  "use strict";
  var DAY_HE = ["ראשון", "שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת"];
  var IL = "Asia/Jerusalem";

  /* ---------- time ---------- */
  // the real next episode (from the API's next_episode, sourced from AniList), or null.
  // AniZone's weekly slot alone is NOT used: it stays listed while a show is on a break.
  function nextEp(a) {
    var n = a && a.next_episode;
    if (!n || !n.airing_at) return null;
    var d = new Date(n.airing_at);
    if (isNaN(d) || d.getTime() < Date.now() - 30 * 60e3) return null; // still "now" for 30 minutes
    return {date: d, episode: n.episode};
  }
  var fmtKey = new Intl.DateTimeFormat("en-CA", {timeZone: "Asia/Jerusalem", year: "numeric", month: "2-digit", day: "2-digit"});
  var fmtDay = new Intl.DateTimeFormat("en-US", {timeZone: IL, weekday: "short"});
  var fmtTime = new Intl.DateTimeFormat("he-IL", {timeZone: IL, hour: "2-digit", minute: "2-digit", hour12: false});
  var fmtDate = new Intl.DateTimeFormat("he-IL", {timeZone: IL, day: "numeric", month: "numeric"});
  function ilDayIndex(date) {
    return ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].indexOf(fmtDay.format(date));
  }
  function ilLabel(a) {
    var n = nextEp(a);
    return n && n.date - Date.now() < 14 * 864e5 ? DAY_HE[ilDayIndex(n.date)] + " " + fmtTime.format(n.date) : "";
  }
  function countdown(date) {
    var ms = date - Date.now();
    if (ms <= 0) return "משודר עכשיו";
    var m = Math.floor(ms / 60e3), h = Math.floor(m / 60), d = Math.floor(h / 24);
    if (d >= 1) return "בעוד " + d + (d === 1 ? " יום" : " ימים") + (h % 24 ? " ו-" + (h % 24) + " שע׳" : "");
    if (h >= 1) return "בעוד " + h + " שע׳" + (m % 60 ? " ו-" + (m % 60) + " דק׳" : "");
    return "בעוד " + Math.max(1, m) + " דק׳";
  }

  /* ---------- watchlist (this browser only) ---------- */
  var KEY = "anz_watchlist_v1";
  var STATUS = {watching: "אני צופה", plan: "רוצה לראות", done: "סיימתי"};
  var mem = null;
  function load() {
    if (mem) return mem;
    try { mem = JSON.parse(localStorage.getItem(KEY) || "{}") || {}; } catch (e) { mem = {}; }
    return mem;
  }
  function save() {
    try { localStorage.setItem(KEY, JSON.stringify(mem)); } catch (e) { /* private mode: keep in memory */ }
  }
  function setStatus(a, st) {
    var l = load(), id = String(a.id);
    if (!st || (l[id] && l[id].s === st)) delete l[id];
    else l[id] = {s: st, t: AZ.titleOf(a), p: a.poster || (a.images && a.images.poster) || null,
                  ty: a.type || null, se: a.season ? a.season.label : null, at: Date.now()};
    save();
  }
  function statusOf(id) { var e = load()[String(id)]; return e ? e.s : null; }

  /* ---------- small pieces app.js calls ---------- */
  function badge(id) {
    var s = statusOf(id);
    return s ? '<span class="wl-badge wl-' + s + '" title="' + STATUS[s] + '">' + (s === "done" ? "✓" : s === "watching" ? "▶" : "+") + "</span>" : "";
  }

  function animeExtras(a, box) {
    if (!box) return;
    function draw() {
      var cur = statusOf(a.id);
      var next = nextEp(a);
      box.innerHTML =
        '<div class="wl-btns" role="group" aria-label="רשימת צפייה">' +
        Object.keys(STATUS).map(function (k) {
          return '<button type="button" class="wl-btn' + (cur === k ? " on" : "") + '" data-s="' + k + '" aria-pressed="' + (cur === k) + '">' +
            (cur === k ? "✓ " : "") + STATUS[k] + "</button>";
        }).join("") + "</div>" +
        (next && next.date - Date.now() > 14 * 864e5
          ? '<div class="next-ep off">⏸ כרגע בהפסקה · ' + (next.episode ? "פרק " + next.episode : "הפרק הבא") + " צפוי בסביבות " +
            fmtDate.format(next.date) + "." + new Intl.DateTimeFormat("en", {timeZone: IL, year: "numeric"}).format(next.date) +
            ' <small>(מועד משוער, עוד לא סופי)</small></div>'
        : next ? '<div class="next-ep"><span class="dot"></span>' + (next.episode ? "פרק " + next.episode : "הפרק הבא") + ": <b>" +
          DAY_HE[ilDayIndex(next.date)] + " " + fmtDate.format(next.date) + " בשעה " + fmtTime.format(next.date) + "</b> · " +
          countdown(next.date) + ' <small>(שעון ישראל, לפי השידור ביפן)</small></div>'
        : a.status === "בשידור" && a.next_episode === null
          ? '<div class="next-ep off">⏸ כרגע בהפסקה: עוד לא פורסם מתי ישודר הפרק הבא</div>' : "");
    }
    box.addEventListener("click", function (e) {
      var b = e.target.closest(".wl-btn");
      if (!b) return;
      setStatus(a, b.dataset.s);
      draw();
    });
    draw();
  }

  /* ---------- schedule page ---------- */
  async function schedulePage(tab) {
    AZ.setNav("schedule");
    document.title = "לוח שידורים – אנימה בעברית";
    var sch = await AZ.get("v1/schedule.json");
    var mineOnly = tab === "mine";
    var now = Date.now();
    // the next 7 calendar days in Israel, as "YYYY-MM-DD" keys
    var keys = [0, 1, 2, 3, 4, 5, 6].map(function (i) { return fmtKey.format(new Date(now + i * 864e5)); });
    var all = (sch.data || []).map(function (a) {
      var n = nextEp(a);
      return n ? {a: a, next: n.date, ep: n.episode, key: fmtKey.format(n.date)} : null;
    }).filter(Boolean).sort(function (p, q) { return p.next - q.next; });
    var week = all.filter(function (x) { return keys.indexOf(x.key) >= 0; });
    all = all.filter(function (x) { return x.next - now < 14 * 864e5; }); // far-off dates are only estimates
    var mine = function (x) { var s = statusOf(x.a.id); return s === "watching" || s === "plan"; };
    var sel = /^[0-6]$/.test(tab || "") ? +tab : 0;
    var count = function (k) { return week.filter(function (x) { return x.key === k; }).length; };

    function row(x) {
      var a = x.a, t = AZ.titleOf(a), st = statusOf(a.id);
      return '<a class="sch-row" href="#/anime/' + (+a.id) + '">' +
        '<div class="sch-time"><b>' + fmtTime.format(x.next) + "</b><small>" + AZ.esc(countdown(x.next)) + "</small></div>" +
        AZ.poster(a.poster, t, "sch-pic") +
        '<div class="sch-info"><b>' + AZ.esc(t) + "</b><small>" +
        AZ.esc([x.ep ? "פרק " + x.ep + (a.episodes ? " מתוך " + a.episodes : "") : "", a.titles.english !== t ? a.titles.english : ""].filter(Boolean).join(" · ")) +
        "</small>" + (st ? '<span class="wl-tag wl-' + st + '">' + STATUS[st] + "</span>" : "") + "</div></a>";
    }
    function section(list, key) {
      var d = list[0] ? list[0].next : new Date(now + keys.indexOf(key) * 864e5);
      return '<section class="sch-day"><h2>' + (key === keys[0] ? "היום · " : "") + "יום " + DAY_HE[ilDayIndex(d)] +
        ' <small>' + fmtDate.format(d) + "</small></h2>" +
        (list.length ? list.map(row).join("") : '<p class="note">אין פרקים חדשים ביום הזה.</p>') + "</section>";
    }
    function byDay(list) {
      var groups = [];
      list.forEach(function (x) {
        var g = groups[groups.length - 1];
        if (!g || g.key !== x.key) groups.push(g = {key: x.key, items: []});
        g.items.push(x);
      });
      return groups.map(function (g) { return section(g.items, g.key); }).join("");
    }

    var body;
    if (!sch.available) body = '<div class="empty"><h2>מועדי הפרקים לא זמינים כרגע</h2><p>הם יתעדכנו בעדכון הלילי הבא.</p></div>';
    else if (mineOnly) {
      var my = all.filter(mine);
      body = my.length ? byDay(my)
        : '<div class="empty"><h2>אין כרגע פרקים קרובים לסדרות שלך</h2><p>בדף של כל אנימה לוחצים "אני צופה" או "רוצה לראות", וכשיהיה לה פרק חדש מתוכנן הוא יופיע כאן.</p></div>';
    } else body = section(week.filter(function (x) { return x.key === keys[sel]; }), keys[sel]);

    AZ.app.innerHTML = '<div class="wrap">' +
      '<div class="page-head"><h1>לוח שידורים</h1><p>' + AZ.nf.format(week.length) +
      " פרקים חדשים בשבוע הקרוב · השעות בשעון ישראל, לפי השידור בטלוויזיה ביפן (הפרקים עם תרגום עולים בדרך כלל כמה שעות אחר כך). מועדי הפרקים: AniList</p></div>" +
      '<div class="chips sch-tabs">' +
      keys.map(function (k, i) {
        return '<a class="chip' + (!mineOnly && sel === i ? " on" : "") + '" href="#/schedule/' + i + '">' +
          (i === 0 ? "היום" : DAY_HE[ilDayIndex(new Date(now + i * 864e5))]) + "<small>" + count(k) + "</small></a>";
      }).join("") +
      '<a class="chip' + (mineOnly ? " on" : "") + '" href="#/schedule/mine">★ הסדרות שלי<small>' + all.filter(mine).length + "</small></a></div>" +
      body + "</div>";
  }

  /* ---------- my list page ---------- */
  function listPage(tab) {
    AZ.setNav("list");
    document.title = "הרשימה שלי – אנימה בעברית";
    var l = load(), keys = Object.keys(STATUS);
    var cur = keys.indexOf(tab) >= 0 ? tab : "watching";
    var entries = Object.keys(l).map(function (id) { return Object.assign({id: +id}, l[id]); });
    var items = entries.filter(function (e) { return e.s === cur; }).sort(function (a, b) { return b.at - a.at; });
    AZ.app.innerHTML = '<div class="wrap">' +
      '<div class="page-head"><h1>הרשימה שלי</h1><p>נשמרת בדפדפן הזה בלבד, בלי הרשמה.</p></div>' +
      '<div class="chips" style="margin-bottom:22px">' + keys.map(function (k) {
        var n = entries.filter(function (e) { return e.s === k; }).length;
        return '<a class="chip' + (k === cur ? " on" : "") + '" href="#/list/' + k + '">' + STATUS[k] + "<small>" + n + "</small></a>";
      }).join("") + "</div>" +
      (items.length ? '<div class="grid">' + items.map(function (e) {
        return '<div class="wl-item">' + AZ.card({id: e.id, titles: {hebrew: e.t}, poster: e.p, type: e.ty, season: e.se ? {label: e.se} : null}) +
          '<button type="button" class="wl-remove" data-id="' + e.id + '" aria-label="הסרה מהרשימה">הסרה</button></div>';
      }).join("") + "</div>"
        : '<div class="empty"><h2>הרשימה ריקה</h2><p>בדף של כל אנימה יש כפתורים "אני צופה", "רוצה לראות" ו"סיימתי".</p><a class="btn" href="#/browse/top/popularity">לקטלוג</a></div>') +
      "</div>";
    AZ.app.querySelectorAll(".wl-remove").forEach(function (b) {
      b.onclick = function () { delete load()[b.dataset.id]; save(); listPage(cur); };
    });
  }

  window.AZX = {nextEp: nextEp, broadcastIL: function (a) { var s = ilLabel(a); return s ? s + " (שעון ישראל)" : ""; },
                badge: badge, animeExtras: animeExtras, schedulePage: schedulePage, listPage: listPage, statusOf: statusOf};
})();
