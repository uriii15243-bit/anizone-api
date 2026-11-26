/* אנימה בעברית – website on top of the AniZone Open API (static JSON).
   Data courtesy of AniZone (https://anizone.co.il), used with permission. */
{
const params = new URLSearchParams(location.search);
const API = (params.get("api") ||
  (location.hostname.endsWith("github.io") ? new URL("../", location.href).href
                                           : "https://uriii15243-bit.github.io/anizone-api/")
).replace(/\/?$/, "/");

const app = document.getElementById("app");
const SEASONS_HE = {winter: "חורף", spring: "אביב", summer: "קיץ", fall: "סתיו"};
const SEASON_ORDER = ["winter", "spring", "summer", "fall"];
const nf = new Intl.NumberFormat("he-IL");

/* ---------- helpers ---------- */
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const cache = new Map();
function get(path) {
  if (!cache.has(path)) {
    cache.set(path, fetch(API + path).then(r => {
      if (!r.ok) { cache.delete(path); throw new Error(r.status); }
      return r.json();
    }));
  }
  return cache.get(path);
}
let clientReady = null;
function client() {   // anizone.js (search) is served by the API itself
  if (!clientReady) clientReady = new Promise((ok, fail) => {
    const s = document.createElement("script");
    s.src = API + "anizone.js";
    s.onload = () => { window.AniZone.base = API; ok(window.AniZone); };
    s.onerror = fail;
    document.head.appendChild(s);
  });
  return clientReady;
}
const titleOf = a => a.titles?.hebrew || a.titles?.english || a.titles?.romaji || a.hebrew || a.english || "";
const initial = t => esc((t || "?").trim().charAt(0));
const poster = (src, t, cls = "") => src
  ? `<img class="${cls}" src="${esc(src)}" alt="${esc(t)}" loading="lazy" referrerpolicy="no-referrer" data-t="${esc(t)}">`
  : `<div class="ph ${cls}">${initial(t)}</div>`;
document.addEventListener("error", e => {   // broken poster -> letter placeholder
  const im = e.target;
  if (im.tagName === "IMG" && im.dataset.t !== undefined) {
    const d = document.createElement("div");
    d.className = "ph " + im.className;
    d.textContent = (im.dataset.t || "?").trim().charAt(0);
    im.replaceWith(d);
  }
}, true);
const yearOf = a => a.season?.year || a.year || "";
function meta(a) {
  return [a.type, a.season?.label || a.year, a.episodes ? a.episodes + " פרקים" : ""].filter(Boolean).join(" · ");
}
function card(a, rank) {
  const t = titleOf(a);
  const sc = a.scores?.israel && a.scores?.israel_scored_by ? a.scores.israel
           : a.scores?.mal || null;
  return `<a class="card" href="#/anime/${+a.id}">
    <div class="pic">${poster(a.poster, t)}${window.AZX ? AZX.badge(a.id) : ""}
      ${sc ? `<span class="score">★ ${(+sc).toFixed(1)}</span>` : ""}
      ${rank ? `<span class="rank">${rank}</span>` : ""}</div>
    <h3>${esc(t)}</h3><small>${esc(meta(a))}</small></a>`;
}
const shelf = (title, link, items, ranked) => `<section class="shelf wrap">
  <div class="shelf-head"><h2>${esc(title)}</h2>${link ? `<a href="${link}">לכל הרשימה ←</a>` : ""}</div>
  <div class="row">${items.map((a, i) => card(a, ranked ? i + 1 : 0)).join("")}</div></section>`;
function currentSeason() {
  const d = new Date(), m = d.getMonth();
  return {year: d.getFullYear(), season: SEASON_ORDER[Math.floor(m / 3)]};
}
function setNav(name) {
  document.querySelectorAll("#nav a").forEach(a => a.classList.toggle("on", a.dataset.nav === name));
}
function loading() { app.innerHTML = '<div class="loading"><span></span></div>'; }
function fail(msg) { app.innerHTML = `<div class="err"><h2>אופס</h2><p>${esc(msg || "לא הצלחנו לטעון את המידע. נסו לרענן את הדף.")}</p><a class="btn" href="#/">לדף הבית</a></div>`; }

/* ---------- pages ---------- */
async function home() {
  setNav("home");
  document.title = "אנימה בעברית – כל האנימות במקום אחד";
  const cs = currentSeason();
  const [israel, pop, seasons, cats] = await Promise.all([
    get("v1/top/israel/1.json"), get("v1/top/popularity/1.json"),
    get("v1/seasons/index.json"), get("v1/categories/index.json")]);
  const se = seasons.data.find(s => s.year === cs.year && s.season === cs.season)
          || seasons.data.find(s => s.count >= 15) || seasons.data[0];
  const season = se ? await get(`v1/seasons/${se.year}/${se.season}.json`) : {data: []};
  const pick = israel.data[Math.floor(Math.random() * Math.min(10, israel.data.length))] || pop.data[0];
  const f = await get(`v1/anime/${pick.id}.json`).catch(() => pick);
  const t = titleOf(f);
  app.innerHTML = `
  <section class="hero">
    <div class="hero-bg" style="background-image:url('${esc(f.images?.poster || "")}')"></div>
    <div class="hero-in">
      <div>
        <div class="kicker">מומלץ מהקהילה הישראלית</div>
        <h1>${esc(t)}</h1>
        <div class="sub">${esc([f.titles?.english !== t ? f.titles?.english : "", meta(f)].filter(Boolean).join(" · "))}</div>
        ${stamps(f)}
        <p class="syn">${esc((f.synopsis_hebrew || "").replace(/\s*\[נכתב על ידי[^\]]*\]\s*$/, ""))}</p>
        <div class="btns"><a class="btn" href="#/anime/${+f.id}">לכל הפרטים</a>
          <a class="btn ghost" href="#/random">🎲 אנימה אקראית</a></div>
      </div>
      <div class="hero-poster">${poster(f.images?.poster, t)}</div>
    </div>
  </section>
  ${season.data.length ? shelf(`עכשיו בעונה: ${se.label || ""}`, `#/seasons/${se.year}/${se.season}`, season.data.slice(0, 20)) : ""}
  ${shelf("הכי מדורגות בישראל", "#/browse/top/israel", israel.data.slice(0, 20), true)}
  ${shelf("הכי פופולריות", "#/browse/top/popularity", pop.data.slice(0, 20), true)}
  <section class="shelf wrap"><div class="shelf-head"><h2>לפי קטגוריה</h2></div>
    <div class="chips">${cats.data.map(c => `<a class="chip" href="#/browse/category/${encodeURIComponent(c.slug)}">${esc(c.he || c.en)}<small>${nf.format(c.count)}</small></a>`).join("")}</div>
  </section>`;
}

function stamps(a) {
  const s = a.scores || {};
  const out = [];
  if (s.israel && s.israel_scored_by) out.push(`<span class="stamp il"><b>${(+s.israel).toFixed(1)}</b>ציון ישראלי · ${nf.format(s.israel_scored_by)} מדרגים</span>`);
  if (s.mal) out.push(`<span class="stamp mal"><b>${(+s.mal).toFixed(2)}</b>MAL</span>`);
  if (s.rank) out.push(`<span class="stamp"><b>#${nf.format(s.rank)}</b>בדירוג</span>`);
  return out.length ? `<div class="stamps">${out.join("")}</div>` : "";
}

const TOPS = {popularity: "הכי פופולריות", israel: "דירוג ישראלי", mal: "דירוג MAL"};
async function browse(kind = "top", arg = "popularity") {
  setNav("browse");
  const [cats, types] = await Promise.all([get("v1/categories/index.json"), get("v1/types/index.json")]);
  let title = TOPS.popularity, base = "v1/top/popularity", sub = "";
  if (kind === "top" && TOPS[arg]) { title = TOPS[arg]; base = `v1/top/${arg}`;
    if (arg === "israel") sub = "רק אנימות עם 5 דירוגים ישראליים ומעלה"; }
  if (kind === "category") { const c = cats.data.find(x => x.slug === arg);
    if (!c) return fail("הקטגוריה לא נמצאה"); title = c.he || c.en; base = `v1/categories/${encodeURIComponent(c.slug)}`; sub = "ממוין לפי פופולריות"; }
  if (kind === "type") { const t = types.data.find(x => x.slug === arg);
    if (!t) return fail("הסוג לא נמצא"); title = t.type; base = `v1/types/${t.slug}`; sub = "ממוין לפי פופולריות"; }
  document.title = `${title} – אנימה בעברית`;
  const isOn = (k, a) => k === kind && a === arg ? " on" : "";
  app.innerHTML = `<div class="wrap">
    <div class="page-head"><h1>${esc(title)}</h1>${sub ? `<p>${esc(sub)}</p>` : ""}</div>
    <div class="filters">
      <div><label>מיון</label><div class="chips">${Object.entries(TOPS).map(([k, v]) => `<a class="chip${isOn("top", k)}" href="#/browse/top/${k}">${v}</a>`).join("")}</div></div>
      <div><label>קטגוריה</label><div class="chips">${cats.data.map(c => `<a class="chip${isOn("category", c.slug)}" href="#/browse/category/${encodeURIComponent(c.slug)}">${esc(c.he || c.en)}<small>${nf.format(c.count)}</small></a>`).join("")}</div></div>
      <div><label>סוג</label><div class="chips">${types.data.map(t => `<a class="chip${isOn("type", t.slug)}" href="#/browse/type/${t.slug}">${esc(t.type)}<small>${nf.format(t.count)}</small></a>`).join("")}</div></div>
    </div>
    <p class="count" id="count"></p>
    <div class="grid" id="grid"></div>
    <div class="more"><button class="btn ghost" id="more" hidden>טען עוד</button></div></div>`;
  let page = 0, pages = 1, ranked = kind === "top";
  const grid = document.getElementById("grid"), more = document.getElementById("more");
  async function next() {
    more.disabled = true;
    const r = await get(`${base}/${page + 1}.json`);
    page = r.pagination.page; pages = r.pagination.pages;
    const offset = (page - 1) * r.pagination.per_page;
    grid.insertAdjacentHTML("beforeend", r.data.map((a, i) => card(a, ranked ? offset + i + 1 : 0)).join(""));
    document.getElementById("count").textContent = `${nf.format(r.pagination.total)} אנימות`;
    more.hidden = page >= pages; more.disabled = false;
  }
  more.onclick = () => next().catch(() => { more.disabled = false; });
  await next();
}

async function seasonsPage(year, season) {
  setNav("seasons");
  const idx = await get("v1/seasons/index.json");
  if (!year) {
    const cs = currentSeason();
    const s = idx.data.find(x => x.year === cs.year && x.season === cs.season) || idx.data.find(x => x.count >= 15) || idx.data[0];
    year = s.year; season = s.season;
  }
  year = +year;
  const list = idx.data;   // newest first
  const i = list.findIndex(x => x.year === year && x.season === season);
  if (i < 0) return fail("העונה לא נמצאה");
  const s = await get(`v1/seasons/${year}/${season}.json`);
  document.title = `${s.label} – אנימה בעברית`;
  const years = [...new Set(list.map(x => x.year))];
  const types = [...new Set(s.data.map(a => a.type).filter(Boolean))];
  app.innerHTML = `<div class="wrap">
    <div class="page-head"><h1>אנימות ${esc(s.label)}</h1><p>${nf.format(s.count)} אנימות בעונה הזו</p></div>
    <div class="season-bar">
      <button class="icon-btn" id="prev" aria-label="עונה קודמת" ${i >= list.length - 1 ? "disabled" : ""}>→</button>
      <select id="sy" aria-label="שנה">${years.map(y => `<option ${y === year ? "selected" : ""}>${y}</option>`).join("")}</select>
      <select id="ss" aria-label="עונה">${SEASON_ORDER.map(k => `<option value="${k}" ${k === season ? "selected" : ""}>${SEASONS_HE[k]}</option>`).join("")}</select>
      <button class="icon-btn" id="next" aria-label="עונה הבאה" ${i <= 0 ? "disabled" : ""}>←</button>
    </div>
    ${types.length > 1 ? `<div class="chips" id="tf" style="margin-bottom:22px"><button class="chip on" data-t="">הכל</button>${types.map(t => `<button class="chip" data-t="${esc(t)}">${esc(t)}</button>`).join("")}</div>` : ""}
    <div class="grid" id="grid"></div></div>`;
  const grid = document.getElementById("grid");
  const draw = t => { grid.innerHTML = s.data.filter(a => !t || a.type === t).map(a => card(a)).join(""); };
  draw("");
  document.getElementById("tf")?.addEventListener("click", e => {
    const b = e.target.closest(".chip"); if (!b) return;
    document.querySelectorAll("#tf .chip").forEach(x => x.classList.toggle("on", x === b));
    draw(b.dataset.t);
  });
  const go = (y, se) => { location.hash = `#/seasons/${y}/${se}`; };
  document.getElementById("prev").onclick = () => { const p = list[i + 1]; if (p) go(p.year, p.season); };
  document.getElementById("next").onclick = () => { const n = list[i - 1]; if (n) go(n.year, n.season); };
  const pickSel = () => {
    const y = +document.getElementById("sy").value, se = document.getElementById("ss").value;
    const hit = list.find(x => x.year === y && x.season === se) || list.find(x => x.year === y);
    if (hit) go(hit.year, hit.season);
  };
  document.getElementById("sy").onchange = pickSel;
  document.getElementById("ss").onchange = pickSel;
}

async function searchPage(q) {
  setNav("");
  document.title = `חיפוש: ${q} – אנימה בעברית`;
  document.getElementById("q").value = q;
  const AZ = await client();
  const res = await AZ.search(q, {limit: 60});
  app.innerHTML = `<div class="wrap"><div class="page-head"><h1>תוצאות עבור “${esc(q)}”</h1>
    <p>${res.length ? `${res.length} תוצאות` : "לא נמצאו תוצאות. נסו שם אחר, באנגלית או בעברית."}</p></div>
    <div class="grid">${res.map(a => card(a)).join("")}</div></div>`;
}

async function random() {
  const ids = await get("v1/ids.json");
  const id = ids.data[Math.floor(Math.random() * ids.data.length)];
  location.replace(`#/anime/${id}`);
}

const LANG = {"יפנית": 0, "אנגלית": 1};
async function animePage(id) {
  setNav("");
  let a;
  try { a = await get(`v1/anime/${+id}.json`); } catch { return fail("האנימה לא נמצאה."); }
  const t = titleOf(a);
  document.title = `${t} – אנימה בעברית`;
  const s = a.scores || {};
  const alt = [a.titles?.english, a.titles?.romaji, a.titles?.japanese].filter(Boolean)
    .filter((x, i, arr) => x.toLowerCase() !== t.toLowerCase() && arr.findIndex(y => y.toLowerCase() === x.toLowerCase()) === i);
  const syn = (a.synopsis_hebrew || "").split(/\n\s*\n/).map(p => p.trim()).filter(Boolean);
  const bg = (a.background_hebrew || "").split(/\n\s*\n/).map(p => p.trim()).filter(Boolean);
  const he = c => c && (c.he || c.en);
  const info = [
    ["סוג", a.type], ["פרקים", a.episodes], ["אורך פרק", a.duration_minutes ? a.duration_minutes + " דקות" : ""],
    ["סטטוס", a.status], ["עונה", a.season?.label], ["שידור", (window.AZX && a.status === "בשידור" && AZX.broadcastIL(a.broadcast)) || (a.broadcast?.label ? a.broadcast.label + " (שעון יפן)" : "")],
    ["תחילת שידור", a.aired_from ? new Date(a.aired_from).toLocaleDateString("he-IL") : ""],
    ["דמוגרפיה", he(a.demographic)], ["סטודיו", (a.studios || []).join(", ")],
    ["מפיקים", (a.producers || []).join(", ")], ["זכויות", (a.licensors || []).join(", ")],
  ].filter(r => r[1]);
  const chars = (a.characters || []).map(c => {
    const va = [...(c.voice_actors || [])].sort((x, y) => (LANG[x.language] ?? 9) - (LANG[y.language] ?? 9))[0];
    return `<div class="person"><div class="side">${poster(c.image, c.name)}<div><b>${esc(c.name)}</b><small>${esc(c.role || "")}</small></div></div>
      ${va ? `<div class="side va">${poster(va.image, va.name)}<div><b>${esc(va.name)}</b><small>${esc(va.language || "")}</small></div></div>` : ""}</div>`;
  }).join("");
  const staff = (a.staff || []).map(p => `<div class="person"><div class="side">${poster(p.image, p.name)}<div><b>${esc(p.name)}</b><small>${esc((p.roles || []).join(", ") || p.role || "")}</small></div></div></div>`).join("");
  const host = u => { try { return new URL(u).hostname.replace(/^www\./, ""); } catch { return u; } };
  const links = [a.url && [a.url, "הדף ב-AniZone"], a.external_links?.myanimelist && [a.external_links.myanimelist, "MyAnimeList"],
    ...(a.external_links?.other || []).slice(0, 8).map(u => [u, host(u)])].filter(Boolean);

  app.innerHTML = `
  <section class="hero a-hero">
    <div class="hero-bg" style="background-image:url('${esc(a.images?.poster || "")}')"></div>
    <div class="hero-in">
      <div class="hero-poster">${poster(a.images?.poster, t)}</div>
      <div>
        <div class="kicker">${esc([a.type, a.season?.label, a.status].filter(Boolean).join(" · "))}</div>
        <h1>${esc(t)}</h1>
        ${alt.length ? `<div class="titles-alt">${alt.map(x => `<span>${esc(x)}</span>`).join("")}</div>` : ""}
        <div class="chips" style="margin-top:14px">${[...(a.categories || []), ...(a.subcategories || [])].map(c => {
          const slug = (c.en || c.he || "").toLowerCase().replace(/[^\w֐-׿]+/g, "-").replace(/^-|-$/g, "");
          return (a.categories || []).includes(c) ? `<a class="chip" href="#/browse/category/${encodeURIComponent(slug)}">${esc(he(c))}</a>` : `<span class="chip">${esc(he(c))}</span>`;
        }).join("")}</div>
        <div id="az-extras"></div>
        <div class="btns">${a.trailer ? `<a class="btn" href="#trailer" id="go-trailer">▶ צפייה בטריילר</a>` : ""}
          <a class="btn ghost" href="${esc(a.url || "https://anizone.co.il")}" target="_blank" rel="noopener">לדף ב-AniZone ↗</a></div>
      </div>
    </div>
  </section>
  <div class="wrap a-body">
    <div>
      <div class="stats">
        <div class="stat il"><b>${s.israel && s.israel_scored_by ? (+s.israel).toFixed(1) : "–"}</b><span>ציון ישראלי${s.israel_scored_by ? ` · ${nf.format(s.israel_scored_by)} מדרגים` : ""}</span></div>
        <div class="stat mal"><b>${s.mal ? (+s.mal).toFixed(2) : "–"}</b><span>ציון MAL${s.mal_scored_by ? ` · ${nf.format(s.mal_scored_by)}` : ""}</span></div>
        <div class="stat"><b>${s.popularity ? "#" + nf.format(s.popularity) : "–"}</b><span>פופולריות</span></div>
        <div class="stat"><b>${s.members ? nf.format(s.members) : "–"}</b><span>צופים</span></div>
      </div>
      ${syn.length ? `<section class="sec syn-full"><h2>תקציר</h2>${syn.map(p => `<p>${esc(p)}</p>`).join("")}</section>` : ""}
      ${bg.length ? `<section class="sec syn-full"><h2>רקע</h2>${bg.map(p => `<p>${esc(p)}</p>`).join("")}</section>` : ""}
      ${a.trailer?.youtube_id ? `<section class="sec" id="trailer"><h2>טריילר</h2><div class="trailer"><iframe loading="lazy" src="https://www.youtube-nocookie.com/embed/${esc(a.trailer.youtube_id)}" title="טריילר" allow="encrypted-media; picture-in-picture; fullscreen" allowfullscreen></iframe></div></section>` : ""}
      ${chars ? `<section class="sec"><h2>דמויות ומדבבים</h2><div class="people">${chars}</div></section>` : ""}
      ${staff ? `<section class="sec staff"><h2>צוות</h2><div class="people">${staff}</div></section>` : ""}
      <div id="related"></div>
    </div>
    <aside>
      <div class="info"><dl>${info.map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join("")}</dl></div>
      ${a.titles?.synonyms?.length ? `<section class="sec" style="margin-top:24px"><h2>שמות נוספים</h2><p class="note">${a.titles.synonyms.map(esc).join(" · ")}</p></section>` : ""}
      ${links.length ? `<section class="sec" style="margin-top:24px"><h2>קישורים</h2><div class="links">${links.map(([u, l]) => `<a class="chip" href="${esc(u)}" target="_blank" rel="noopener">${esc(l)} ↗</a>`).join("")}</div></section>` : ""}
      <div class="credit">המידע על האנימה באדיבות <a href="${esc(a.url || "https://anizone.co.il")}" target="_blank" rel="noopener">AniZone</a>.</div>
    </aside>
  </div>`;
  if (window.AZX) AZX.animeExtras(a, document.getElementById("az-extras"));
  document.getElementById("go-trailer")?.addEventListener("click", e => {
    e.preventDefault(); document.getElementById("trailer")?.scrollIntoView({behavior: "smooth"});
  });
  // more from the same category
  const c0 = (a.categories || [])[0];
  if (c0) {
    const slug = (c0.en || c0.he || "").toLowerCase().replace(/[^\w֐-׿]+/g, "-").replace(/^-|-$/g, "");
    get(`v1/categories/${encodeURIComponent(slug)}/1.json`).then(r => {
      const items = r.data.filter(x => x.id !== a.id).slice(0, 14);
      const box = document.getElementById("related");
      if (box && items.length) box.outerHTML = `<section class="sec"><h2>עוד ${esc(he(c0))}</h2><div class="row">${items.map(x => card(x)).join("")}</div></section>`;
    }).catch(() => {});
  }
}

/* ---------- router ---------- */
async function route() {
  const parts = (location.hash.replace(/^#\/?/, "") || "").split("/").map(decodeURIComponent);
  loading();
  window.scrollTo(0, 0);
  document.getElementById("suggest").hidden = true;
  try {
    switch (parts[0]) {
      case "anime": await animePage(parts[1]); break;
      case "browse": await browse(parts[1], parts[2]); break;
      case "seasons": await seasonsPage(parts[1], parts[2]); break;
      case "search": await searchPage(parts.slice(1).join("/")); break;
      case "random": await random(); break;
      case "schedule": await AZX.schedulePage(parts[1]); break;
      case "list": AZX.listPage(parts[1]); break;
      default: await home();
    }
  } catch (e) { console.error(e); fail(); }
}
window.AZ = {get, card, poster, esc, titleOf, nf, app, setNav, fail};
addEventListener("hashchange", route);
route();

get("v1/index.json").then(i => {
  document.getElementById("foot-count").textContent = `${nf.format(i.total_anime)} אנימות · עודכן ${new Date(i.data_crawled_at || i.generated_at).toLocaleDateString("he-IL")}`;
}).catch(() => {});

/* ---------- live search ---------- */
const qEl = document.getElementById("q"), sug = document.getElementById("suggest");
let timer, sel = -1;
qEl.addEventListener("input", () => {
  clearTimeout(timer);
  const q = qEl.value.trim();
  if (!q) { sug.hidden = true; return; }
  timer = setTimeout(async () => {
    const AZ = await client().catch(() => null);
    if (!AZ) return;
    const res = await AZ.search(q, {limit: 7});
    if (qEl.value.trim() !== q) return;
    sel = -1;
    sug.innerHTML = res.map(a => `<a href="#/anime/${+a.id}">${poster(a.poster, titleOf(a))}<div><b>${esc(titleOf(a))}</b><small>${esc([a.titles.english !== titleOf(a) ? a.titles.english : "", a.type, a.year].filter(Boolean).join(" · "))}</small></div></a>`).join("")
      + `<a class="all" href="#/search/${encodeURIComponent(q)}">${res.length ? "לכל התוצאות" : "לא נמצא – חיפוש מלא"} ←</a>`;
    sug.hidden = false;
  }, 120);
});
qEl.addEventListener("keydown", e => {
  const items = [...sug.querySelectorAll("a")];
  if (sug.hidden || !items.length) return;
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    sel = (sel + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
    items.forEach((x, i) => x.classList.toggle("sel", i === sel));
  } else if (e.key === "Enter" && sel >= 0) { e.preventDefault(); location.hash = items[sel].getAttribute("href"); }
  else if (e.key === "Escape") sug.hidden = true;
});
document.getElementById("search").addEventListener("submit", e => {
  e.preventDefault();
  const q = qEl.value.trim();
  if (q) location.hash = `#/search/${encodeURIComponent(q)}`;
  qEl.blur();
});
document.addEventListener("click", e => { if (!e.target.closest("#search")) sug.hidden = true; });
sug.addEventListener("click", () => { sug.hidden = true; });
}
