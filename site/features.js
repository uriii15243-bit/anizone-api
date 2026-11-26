/* Broadcast schedule + personal watchlist for "אנימה בעברית".
   Loaded before app.js; uses the helpers app.js exposes as window.AZ at call time. */
(function () {
  "use strict";
  var DAYS = ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"];
  var DAY_HE = ["ראשון", "שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת"];
  var IL = "Asia/Jerusalem";
  var JST_OFFSET = 9 * 3600e3; // Japan has no daylight saving time

  /* ---------- time ---------- */
  // next airing (as a Date) of a weekly JST slot {day, time}
  function nextAir(b, from) {
    if (!b || !b.day || !b.time) return null;
    var d = DAYS.indexOf(b.day), hm = b.time.split(":");
    if (d < 0 || hm.length < 2) return null;
    var now = from || new Date();
    var j = new Date(now.getTime() + JST_OFFSET); // "JST wall clock" read through UTC getters
    for (var k = 0; k < 8; k++) {
      var c = Date.UTC(j.getUTCFullYear(), j.getUTCMonth(), j.getUTCDate() + k, +hm[0], +hm[1]);
      var cd = new Date(c);
      if (cd.getUTCDay() !== d) continue;
      var real = c - JST_OFFSET;
      if (real > now.getTime() - 30 * 60e3) return new Date(real); // still "now" for 30 minutes
    }
    return null;
  }
  var fmtDay = new Intl.DateTimeFormat("en-US", {timeZone: IL, weekday: "short"});
  var fmtTime = new Intl.DateTimeFormat("he-IL", {timeZone: IL, hour: "2-digit", minute: "2-digit", hour12: false});
  var fmtDate = new Intl.DateTimeFormat("he-IL", {timeZone: IL, day: "numeric", month: "numeric"});
  function ilDayIndex(date) {
    return ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].indexOf(fmtDay.format(date));
  }
  function ilLabel(b) {
    var n = nextAir(b);
    return n ? DAY_HE[ilDayIndex(n)] + " " + fmtTime.format(n) : "";
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
      var next = a.status === "בשידור" ? nextAir(a.broadcast) : null;
      box.innerHTML =
        '<div class="wl-btns" role="group" aria-label="רשימת צפייה">' +
        Object.keys(STATUS).map(function (k) {
          return '<button type="button" class="wl-btn' + (cur === k ? " on" : "") + '" data-s="' + k + '" aria-pressed="' + (cur === k) + '">' +
            (cur === k ? "✓ " : "") + STATUS[k] + "</button>";
        }).join("") + "</div>" +
        (next ? '<div class="next-ep"><span class="dot"></span>הפרק הבא: <b>' + DAY_HE[ilDayIndex(next)] + " " +
          fmtTime.format(next) + "</b> · " + countdown(next) + ' <small>(שעון ישראל, לפי השידור ביפן)</small></div>' : "");
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
  async function schedulePage(day) {
    AZ.setNav("schedule");
    document.title = "לוח שידורים – אנימה בעברית";
    var sch = await AZ.get("v1/schedule.json");
    var mineOnly = day === "mine";
    var items = sch.data.map(function (a) {
      var n = nextAir(a.broadcast);
      return n ? {a: a, next: n, day: ilDayIndex(n)} : null;
    }).filter(Boolean);
    var today = ilDayIndex(new Date());
    var order = [0, 1, 2, 3, 4, 5, 6].map(function (i) { return (today + i) % 7; });
    var mine = function (x) { var s = statusOf(x.a.id); return s === "watching" || s === "plan"; };
    var shown = mineOnly ? items.filter(mine) : items;
    var counts = order.map(function (d) { return shown.filter(function (x) { return x.day === d; }).length; });
    var sel = /^\d$/.test(day || "") ? +day : today;
    if (mineOnly) sel = -1;

    function row(x) {
      var a = x.a, t = AZ.titleOf(a), st = statusOf(a.id);
      return '<a class="sch-row" href="#/anime/' + (+a.id) + '">' +
        '<div class="sch-time"><b>' + fmtTime.format(x.next) + "</b><small>" + AZ.esc(countdown(x.next)) + "</small></div>" +
        AZ.poster(a.poster, t, "sch-pic") +
        '<div class="sch-info"><b>' + AZ.esc(t) + "</b><small>" +
        AZ.esc([a.titles.english !== t ? a.titles.english : "", a.episodes ? a.episodes + " פרקים" : ""].filter(Boolean).join(" · ")) +
        "</small>" + (st ? '<span class="wl-tag wl-' + st + '">' + STATUS[st] + "</span>" : "") + "</div></a>";
    }
    function section(d) {
      var list = shown.filter(function (x) { return x.day === d; }).sort(function (p, q) { return p.next - q.next; });
      var first = list[0] ? fmtDate.format(list[0].next) : "";
      return '<section class="sch-day"><h2>' + (d === today ? "היום · " : "") + "יום " + DAY_HE[d] +
        (first ? ' <small>' + first + "</small>" : "") + "</h2>" +
        (list.length ? list.map(row).join("") : '<p class="note">אין שידורים ביום הזה.</p>') + "</section>";
    }

    AZ.app.innerHTML = '<div class="wrap">' +
      '<div class="page-head"><h1>לוח שידורים</h1><p>' + AZ.nf.format(items.length) +
      " אנימות בשידור השבוע · השעות בשעון ישראל, לפי השידור בטלוויזיה ביפן (הפרקים עם תרגום עולים בדרך כלל כמה שעות אחר כך)</p></div>" +
      '<div class="chips sch-tabs">' +
      order.map(function (d, i) {
        return '<a class="chip' + (sel === d ? " on" : "") + '" href="#/schedule/' + d + '">' + (d === today ? "היום" : DAY_HE[d]) +
          "<small>" + counts[i] + "</small></a>";
      }).join("") +
      '<a class="chip' + (mineOnly ? " on" : "") + '" href="#/schedule/mine">★ הסדרות שלי<small>' + items.filter(mine).length + "</small></a></div>" +
      (mineOnly
        ? (shown.length ? order.map(function (d) { return shown.some(function (x) { return x.day === d; }) ? section(d) : ""; }).join("")
                        : '<div class="empty"><h2>עוד אין סדרות ברשימה שלך</h2><p>בדף של כל אנימה שבשידור לוחצים "אני צופה", והיא תופיע כאן עם ספירה לאחור לפרק הבא.</p></div>')
        : section(sel)) +
      "</div>";
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

  window.AZX = {nextAir: nextAir, broadcastIL: function (b) { var s = ilLabel(b); return s ? s + " (שעון ישראל)" : ""; },
                badge: badge, animeExtras: animeExtras, schedulePage: schedulePage, listPage: listPage, statusOf: statusOf};
})();
