/* Nasdaq-100 Monitor — frontend */
(() => {
"use strict";

// ------------------------------------------------------------ separate instance (phase 9A)
// Only when the server is a separate instance (instance.py): it writes the session's CSRF token and the label in two meta
// tags. Every request that changes something then carries the token; an expired session goes back to the login page.
// The protection is enforced by the server: this only lets the page's own requests through it. The personal dashboard
// has no such meta tags and nothing changes for it.
const INSTANCE = (() => {
  const csrf = document.querySelector('meta[name="ndx-csrf"]')?.content;
  return csrf ? { csrf, label: document.querySelector('meta[name="ndx-istanza"]')?.content || "" } : null;
})();
if (INSTANCE) {
  const nativeFetch = window.fetch.bind(window);
  window.fetch = async (url, opts = {}) => {
    const method = (opts.method || "GET").toUpperCase();
    const o = method === "GET" || method === "HEAD" ? opts : { ...opts, headers: { ...(opts.headers || {}), "X-CSRF-Token": INSTANCE.csrf } };
    const r = await nativeFetch(url, o);
    if (r.status === 401) location.assign("/accesso");
    return r;
  };
  const brand = document.querySelector(".brand");
  if (brand && INSTANCE.label) {
    const tag = document.createElement("span");
    tag.className = "env-tag";
    tag.textContent = INSTANCE.label;
    const out = document.createElement("button");
    out.type = "button"; out.className = "env-out link-btn"; out.textContent = "Esci";
    out.addEventListener("click", async () => { await fetch("/esci", { method: "POST" }).catch(() => {}); location.assign("/accesso"); });
    brand.append(tag, out);
  }
}

// ------------------------------------------------------------ portable Windows app (phase 9B)
// Only in the Windows app (desktop.py writes the ndx-desktop meta tag): a bar under the header with «Aggiorna dati»
// (the only heavy download), the date of the last update, the evening option, backup/restore of this PC's data and
// «Chiudi l'app». The Mac dashboard has no such tag and nothing here runs for it.
const DESKTOP = !!document.querySelector('meta[name="ndx-desktop"]');
if (DESKTOP) {
  const bar = document.createElement("div");
  bar.className = "desk-bar";
  bar.innerHTML = `<button class="btn primary" id="deskUpd" type="button">Aggiorna dati</button>
    <span class="small desk-info" id="deskInfo" role="status" aria-live="polite">…</span>
    <details class="desk-more"><summary class="small">Altro</summary><div class="desk-menu">
      <label class="small"><input type="checkbox" id="deskAuto"> Aggiorna da solo la sera, dopo la chiusura di Wall Street, se l'app è aperta</label>
      <div class="desk-row"><button class="btn" id="deskBackup" type="button">Backup dei miei dati</button>
        <button class="btn" id="deskRestoreBtn" type="button">Ripristina un backup…</button>
        <input type="file" id="deskRestore" accept=".zip" hidden></div>
      <p class="muted small" id="deskWhere"></p>
      <p class="muted small">Servono Internet e le fonti pubbliche (Yahoo Finance, Wikipedia, emittenti degli ETF, calendari ufficiali): ricevono solo ticker e ISIN, mai quantità, prezzi di carico o valori. Il portafoglio resta su questo PC.</p>
    </div></details>
    <button class="btn" id="deskClose" type="button">Chiudi l'app</button>`;
  document.querySelector("header.top")?.after(bar);
  const info = bar.querySelector("#deskInfo");
  const when = iso => iso ? new Date(iso).toLocaleString("it-IT", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "";
  const post = (url, body, headers = {}) => fetch(url, { method: "POST", body, headers: { "X-Requested-With": "ndx-dashboard", ...headers } });
  let last = null, timer = 0;
  async function deskState() {
    clearTimeout(timer);
    let S = null;
    try { S = await (await fetch("/api/app/stato", { cache: "no-store" })).json(); } catch { /* app closed */ }
    if (!S) { info.textContent = "L'app non risponde: forse è stata chiusa."; return; }
    bar.querySelector("#deskUpd").disabled = S.running;
    bar.querySelector("#deskAuto").checked = !!S.settings?.auto_sera;
    bar.querySelector("#deskWhere").textContent = `I tuoi dati sono in ${S.dataDir} (cartelle dati e backup).`;
    const bad = (S.steps || []).filter(x => x.status !== "ok");
    if (S.running) info.textContent = `Aggiornamento in corso: passo ${(S.steps || []).length + 1} di ${S.total} · ${S.current || "…"}`;
    else if (S.firstRun) info.textContent = S.firstRunText;
    else if (S.outcome === "completo") info.textContent = `Dati aggiornati il ${when(S.finishedAt)} (aggiornamento completo).`;
    else if (S.outcome === "parziale") info.textContent = `Ultimo aggiornamento il ${when(S.finishedAt)}: parziale (${bad.map(x => `${x.name}: ${x.note || "non riuscito"}`).join("; ")}). Gli altri dati sono aggiornati; quelli non riusciti restano quelli di prima.`;
    else if (S.outcome === "non riuscito") info.textContent = `Ultimo aggiornamento il ${when(S.finishedAt)} non riuscito: ${S.message || "errore"}.${S.lastComplete ? ` Dati completi del ${when(S.lastComplete)}.` : ""}`;
    else info.textContent = S.hasData ? "Dati già presenti sul PC: premi «Aggiorna dati» per i più recenti." : S.firstRunText;
    if (S.restored && !last) info.textContent = `Backup ripristinato: la dashboard usa i dati del backup (quelli di prima sono nella cartella backup). ${info.textContent}`;
    if (last && last.running && !S.running) { location.reload(); return; }   // new data: every panel reads it again
    last = S;
    timer = setTimeout(deskState, S.running ? 2500 : 60000);
  }
  bar.querySelector("#deskUpd").addEventListener("click", async () => {
    if (last?.firstRun && !confirm(`${last.firstRunText}\n\nVuoi scaricare i dati adesso?`)) return;
    const r = await post("/api/app/aggiorna").catch(() => null);
    if (r && !r.ok) info.textContent = (await r.json().catch(() => ({}))).message || "Aggiornamento non avviato.";
    deskState();
  });
  bar.querySelector("#deskAuto").addEventListener("change", e =>
    post("/api/app/impostazioni", JSON.stringify({ auto_sera: e.target.checked }), { "Content-Type": "application/json" }).then(deskState));
  bar.querySelector("#deskBackup").addEventListener("click", async () => {
    const r = await post("/api/app/backup").catch(() => null);
    if (!r || !r.ok) { alert("Backup non riuscito."); return; }
    const name = /filename="([^"]+)"/.exec(r.headers.get("Content-Disposition") || "")?.[1] || "Nasdaq100Monitor-backup.zip";
    const a = document.createElement("a");
    a.href = URL.createObjectURL(await r.blob()); a.download = name; a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 10000);
    alert(`Backup salvato come ${name} (nella cartella Download del browser; una copia resta anche nella cartella backup dell'app).`);
  });
  bar.querySelector("#deskRestoreBtn").addEventListener("click", () => bar.querySelector("#deskRestore").click());
  bar.querySelector("#deskRestore").addEventListener("change", async e => {
    const f = e.target.files[0];
    e.target.value = "";
    if (!f || !confirm(`Ripristinare il backup ${f.name}?\nI dati attuali verranno messi da parte (non cancellati) alla prossima apertura dell'app.`)) return;
    const r = await post("/api/app/ripristina", f, { "Content-Type": "application/zip" }).catch(() => null);
    const d = r ? await r.json().catch(() => ({})) : {};
    alert(r && r.ok ? d.message : `Ripristino non riuscito: ${d.error || "errore"}.`);
  });
  bar.querySelector("#deskClose").addEventListener("click", async () => {
    if (last?.running && !confirm("È in corso «Aggiorna dati». Chiudere comunque?")) return;
    await post("/api/app/chiudi").catch(() => {});
    location.replace("/static/chiuso.html");             // a page without timers: nothing keeps calling the closed app
  });
  // the shared texts speak of "this Mac": on Windows the data are on this PC
  const fix = node => {
    const w = document.createTreeWalker(node, NodeFilter.SHOW_TEXT);
    for (let t = w.nextNode(); t; t = w.nextNode()) if (t.data.includes("questo Mac")) t.data = t.data.replaceAll("questo Mac", "questo PC");
  };
  new MutationObserver(ms => ms.forEach(m => m.addedNodes.forEach(n => n.nodeType === 1 ? fix(n) : n.nodeType === 3 && fix(n.parentNode || n))))
    .observe(document.body, { childList: true, subtree: true });
  fix(document.body);
  deskState();
}

// ------------------------------------------------------------ state
const LS = {
  get(k, d) { try { const v = localStorage.getItem("ndx." + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem("ndx." + k, JSON.stringify(v)); } catch { /* storage unavailable */ } },
};

const state = {
  snap: null,
  bySym: new Map(),
  view: "opps",           // the tab opened at start: Opportunità from phase O1 (a link like #screener overrides it, see boot)
  tf: LS.get("tf", "1D"),
  size: "mcap",   // map tiles sized by market cap
  cvd: false,
  zoom: null,
  cols: LS.get("cols", "overview"),
  preset: "all",
  sector: "",
  ft: LS.get("scrTrend2", ""),    // Screener: «Tendenza» filter, "days:arrow" (arrows of the stock's Analisi box)
  fb: LS.get("scrBuy2", ""),      // Screener: «Ha senso comprare?» filter (market verdict of the Decisione sheet, by rule)
  buyV: null,                     // {asOf, verdicts: {ticker: {group, label, by}}} from /api/stocks/buy
  sort: { key: "mcap", dir: -1 },
  watch: new Set(),              // loaded from watchlist.json at boot (loadWatch)
  watchNews: {},                 // ticker -> newest headlines naming the stock (newest first)
  hideOpinion: LS.get("hideOpinion", false),
  mySort: { key: "chgPct", dir: -1 },
  secSel: null,
  detail: null,
  prevPrices: new Map(),
};

const METRICS = {
  "1D":  { key: "chgPct",  label: "1G",       dom: [-3, 0, 3] },
  "1W":  { key: "perf1W",  label: "1S",       dom: [-6, 0, 6] },
  "1M":  { key: "perf1M",  label: "1M",       dom: [-10, 0, 10] },
  "3M":  { key: "perf3M",  label: "3M",       dom: [-20, 0, 20] },
  "6M":  { key: "perf6M",  label: "6M",       dom: [-30, 0, 30] },
  "YTD": { key: "perfYTD", label: "YTD",      dom: [-40, 0, 40] },
  "1Y":  { key: "perf1Y",  label: "1A",       dom: [-50, 0, 50] },
  "RV":  { key: "relVol",  label: "Vol rel.", dom: [0, 1, 3], kind: "seq", fmt: v => fNum(v, 2) + "×" },
  "HI":  { key: "fromHi52", label: "vs max 52 sett.", dom: [-40, -15, 0] },
};
const PERF_TFS = ["1D", "1W", "1M", "3M", "6M", "YTD", "1Y"];

// ------------------------------------------------------------ formatting
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const isNum = v => typeof v === "number" && isFinite(v);
const sign = v => !isNum(v) || Math.abs(v) < 0.005 ? "flat" : v > 0 ? "up" : "down";
const zero = (v, d) => Math.abs(v) < 0.5 * 10 ** -d;                       // rounds to zero: "0%", never "−0,0%"
// zero keeps the column's decimals ("0,00%") so the digits stay aligned
const fPct = (v, d = 2) => !isNum(v) ? "—" : zero(v, d) ? fNum(0, d) + "%" : (v > 0 ? "+" : "") + fNum(v, d) + "%";
// thousands dot always (Chrome leaves it out between 1.000 and 9.999) and the typographic minus "−", as wide as "+"
const fNum = (v, d = 2) => isNum(v) ? v.toLocaleString("it-IT", { minimumFractionDigits: d, maximumFractionDigits: d, useGrouping: "always" }).replace("-", "−") : "—";
// the order summary copied into Fineco keeps the old plain format (ASCII minus, no dot below 10.000)
const fNumCopy = (v, d = 2) => isNum(v) ? v.toLocaleString("it-IT", { minimumFractionDigits: d, maximumFractionDigits: d }) : "—";
const fPrice = v => isNum(v) ? fNum(v, v >= 1000 ? 2 : 2) : "—";
const fChg = v => !isNum(v) ? "—" : zero(v, 2) ? fNum(0, 2) : (v > 0 ? "+" : "") + fNum(v, 2);
const fBig = v => {
  if (!isNum(v)) return "—";
  const a = Math.abs(v);
  if (a >= 1e12) return fNum(v / 1e12, 2) + "T";
  if (a >= 1e9) return fNum(v / 1e9, a >= 1e11 ? 0 : 1) + "Mld";
  if (a >= 1e6) return fNum(v / 1e6, 1) + "Mln";
  if (a >= 1e3) return fNum(v / 1e3, 0) + "K";
  return fNum(v, 0);
};
// whole percent; "—" when missing (e.g. old reports built with the 30-day average)
const pctR = v => isNum(v) ? Math.round(v) + "%" : "—";
const fX = v => isNum(v) ? fNum(v, 2) + "×" : "—";
// index weight: real for QQQ's top 10 holdings, "≈" when estimated from market cap
const fW = (s, d = 2) => isNum(s.weight) ? (s.weightSrc === "qqq" ? "" : "≈") + fNum(s.weight, d) + "%" : "—";
const fMetric = (tf, v) => !isNum(v) ? "—" : METRICS[tf].fmt ? METRICS[tf].fmt(v) : fPct(v);
const tz = "America/New_York";
const fTime = t => new Date(t * 1000).toLocaleTimeString("it-IT", { timeZone: tz, hour: "numeric", minute: "2-digit" });
// the same moment on the user's own clock (browser time zone), shown next to New York time
const fLocal = (d, sec = false) => new Date(d).toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit", ...(sec ? { second: "2-digit" } : {}) });
// a New York wall-clock time (e.g. 13:00) converted to the user's clock, today
function nyToLocal(h, m = 0) {
  const now = new Date(), [nh, nm] = now.toLocaleTimeString("en-GB", { timeZone: tz, hour: "2-digit", minute: "2-digit", hour12: false }).split(":").map(Number);
  const diff = now.getHours() * 60 + now.getMinutes() - (nh * 60 + nm);
  const x = ((h * 60 + m + diff) % 1440 + 1440) % 1440;
  return String(Math.floor(x / 60)).padStart(2, "0") + ":" + String(x % 60).padStart(2, "0");
}
const fDate = (t, o = { month: "short", day: "numeric" }) => new Date(t * 1000).toLocaleDateString("it-IT", { timeZone: tz, ...o });
const css = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const REC = { strong_buy: "Forte acquisto", buy: "Acquisto", hold: "Mantenere", underperform: "Sottoperformance", sell: "Vendita", none: "—" };
// display names for the report's rotation phases (the English keys are also CSS classes)
const QLAB = { Leading: "Leader", Weakening: "In indebolimento", Lagging: "In ritardo", Improving: "In miglioramento" };
const RLAB = { "1D": "1G", "5D": "5G", "1Y": "1A", "5Y": "5A", MAX: "Max" };

// ------------------------------------------------------------ color
// map tiles (always on the dark map background): muted red and green; "no change" is a slate grey that stays
// lighter than "no data", so a flat stock does not look like a missing one. The % with its sign is written on every tile.
function tileColors() {
  return state.cvd
    ? { neg: "#b8642a", mid: "#4a5553", pos: "#3a6ea5", na: "#232b2a" }
    : { neg: "#b2463a", mid: "#4a5553", pos: "#2f7d56", na: "#232b2a" };
}
function colorFor(tf) {
  const m = METRICS[tf], c = tileColors();
  const range = m.kind === "seq" ? ["#2c3534", c.mid, "#3a6ea5"] : [c.neg, c.mid, c.pos];
  const s = d3.scaleLinear().domain(m.dom).range(range).interpolate(d3.interpolateLab).clamp(true);
  return v => isNum(v) ? s(v) : c.na;
}
function legendHTML(tf) {
  const m = METRICS[tf], col = colorFor(tf);
  const [a, mid, b] = m.dom;
  const steps = m.kind === "seq" ? [0, 0.5, 1, 1.5, 2, 3] : [a, (a + mid) / 1.5, (a + mid) / 3, mid, (b + mid) / 3, (b + mid) / 1.5, b];
  const lab = v => m.kind === "seq" ? fNum(v, v % 1 ? 1 : 0) + "×" : (v > 0 ? "+" : "") + fNum(v, Math.abs(v) < 10 && v % 1 ? 1 : 0) + "%";
  return `<span>${esc(m.label)}</span><span class="ramp">${steps.map(v => `<i style="background:${col(v)}">${lab(v)}</i>`).join("")}</span>`;
}

// ------------------------------------------------------------ tooltip
const tip = $("#tip");
function showTip(html, ev) {
  tip.innerHTML = html;
  tip.classList.add("show");
  moveTip(ev);
}
function moveTip(ev) {
  const pad = 14, r = tip.getBoundingClientRect();
  let x = ev.clientX + pad, y = ev.clientY + pad;
  if (x + r.width > innerWidth - 8) x = ev.clientX - r.width - pad;
  if (y + r.height > innerHeight - 8) y = Math.max(8, innerHeight - r.height - 8);
  tip.style.left = Math.max(8, x) + "px";
  tip.style.top = y + "px";
}
const hideTip = () => tip.classList.remove("show");

// ------------------------------------------------------------ ⓘ explanations (one system for the whole dashboard)
// info(html) -> small ⓘ icon; hover shows the text, click pins it (touch / trackpad), click elsewhere closes it.
// Texts are fixed strings written here (plus values formatted by the page), never generated.
const info = html => html ? `<span class="info" tabindex="0" role="button" aria-label="Spiegazione" data-info="${esc(html)}">ⓘ</span>` : "";
let infoPinned = null;
function infoShow(el) {
  const r = el.getBoundingClientRect();
  showTip(`<div class="info-tip">${el.dataset.info}</div>`, { clientX: r.right, clientY: r.bottom });
}
document.addEventListener("mouseover", e => { const el = e.target.closest?.(".info"); if (el && !infoPinned) infoShow(el); });
document.addEventListener("mouseout", e => { const el = e.target.closest?.(".info"); if (el && !infoPinned) hideTip(); });
document.addEventListener("focusin", e => { if (e.target.classList?.contains("info")) infoShow(e.target); });
document.addEventListener("focusout", e => { if (e.target.classList?.contains("info") && infoPinned !== e.target) hideTip(); });
// capture phase: a click on ⓘ must not also sort a column or toggle a filter
document.addEventListener("click", e => {
  const el = e.target.closest(".info");
  if (el) {
    e.stopPropagation(); e.preventDefault();
    if (infoPinned === el) { infoPinned = null; hideTip(); } else { infoPinned = el; infoShow(el); }
    return;
  }
  if (infoPinned) { infoPinned = null; hideTip(); }
}, true);
// phase 8B.1: a pinned explanation never stays on screen on its own (anchor re-rendered away, page changed, scroll)
const unpinTip = () => { if (infoPinned) { infoPinned = null; hideTip(); } };
setInterval(() => { if (infoPinned && !infoPinned.isConnected) unpinTip(); }, 800);
addEventListener("scroll", () => { if (infoPinned) unpinTip(); }, { passive: true });
// phase 8B.1: the generic "exploratory, not advice" notices are one discreet line; the full text opens on request
const scopeNote = (lead, body) => `<details class="scope-note"><summary><span class="sn-lead">${lead}</span> <span class="sn-more">Come funziona</span></summary><div class="sn-body">${body}</div></details>`;

// ------------------------------------------------------------ sparkline (inline SVG)
function spark(values, w = 80, h = 22, base = null, color = null) {
  if (!values || values.length < 2) return `<svg width="${w}" height="${h}"></svg>`;
  const lo = Math.min(...values, base ?? Infinity), hi = Math.max(...values, base ?? -Infinity);
  const sx = i => (i / (values.length - 1)) * (w - 2) + 1;
  const sy = v => hi === lo ? h / 2 : h - 2 - ((v - lo) / (hi - lo)) * (h - 4);
  const pts = values.map((v, i) => sx(i).toFixed(1) + "," + sy(v).toFixed(1)).join(" ");
  const ref = base ?? values[0];
  const col = color || (values[values.length - 1] >= ref ? css("--up") : css("--down"));
  const bl = base != null ? `<line x1="0" x2="${w}" y1="${sy(base).toFixed(1)}" y2="${sy(base).toFixed(1)}" stroke="${css("--baseline")}" stroke-width="1"/>` : "";
  return `<svg width="${w}" height="${h}" aria-hidden="true">${bl}<polyline points="${pts}" fill="none" stroke="${col}" stroke-width="1.5" stroke-linejoin="round"/></svg>`;
}

// ------------------------------------------------------------ data
// must equal DASHBOARD_VERSION in server.py: otherwise the server runs old code and the page says so
const PAGE_VERSION = "2026-11-17a";
async function load() {
  const r = await fetch("/api/snapshot", { cache: "no-store" });
  const sv = r.headers.get("X-Dashboard-Version");
  $("#verBanner").hidden = sv === PAGE_VERSION;
  if (sv !== PAGE_VERSION) $("#verBanner").innerHTML = `<b>Il server usa una versione vecchia del codice</b> (${esc(sv || "senza versione")}, la pagina è ${PAGE_VERSION}): alcuni dati mancherebbero.
    ${DESKTOP ? "Chiudi Nasdaq-100 Monitor e riaprilo con il doppio clic." : "Riavvialo: apri l'app <b>Nasdaq-100 Monitor</b> e scegli <b>Riavvia server</b> (con una versione vecchia dell'app: «Ferma server», poi riapri l'app)."}`;
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.statusText);
  const snap = await r.json();
  if (state.snap) state.snap.stocks.forEach(s => state.prevPrices.set(s.ticker, s.price));
  state.snap = snap;
  state.bySym = new Map(snap.stocks.map(s => [s.ticker, s]));
  $("#loading").hidden = true;
  renderAll();
}

let nextAt = 0;
// every 60 s while the market (or pre/after-hours) is active, every 5 min when closed or on a holiday (as the server)
const refreshMs = () => ["open", "pre", "post"].includes(state.snap?.status) ? 60_000 : 5 * 60_000;
async function tick() {
  try { await load(); } catch (e) { console.warn("refresh failed", e); }
  nextAt = Date.now() + refreshMs();
}
setInterval(() => {
  if (!state.snap) return;
  const s = Math.max(0, Math.round((nextAt - Date.now()) / 1000));
  const t = new Date(state.snap.lastQuote || state.snap.asOf);
  $("#updated").textContent = `Aggiornato ${t.toLocaleTimeString("it-IT", { timeZone: tz, hour: "numeric", minute: "2-digit", second: "2-digit" })} ora NY (${fLocal(t, true)} ora locale) · prossimo aggiornamento tra ${s >= 60 ? Math.ceil(s / 60) + " min" : s + " s"}`;
  if (s === 0 && Date.now() > nextAt) { nextAt = Date.now() + refreshMs(); tick(); }
}, 1000);

// ------------------------------------------------------------ helpers over snapshot
const stocks = () => state.snap ? state.snap.stocks : [];
const val = (s, tf) => s[METRICS[tf].key];
function capWeighted(list, key) {
  let w = 0, acc = 0;
  for (const s of list) if (isNum(s[key]) && isNum(s.mcap)) { w += s.mcap; acc += s.mcap * s[key]; }
  return w ? acc / w : null;
}
function sectors() {
  const g = d3.group(stocks(), s => s.sector);
  return [...g].map(([name, list]) => {
    const o = { name, list, n: list.length, mcap: d3.sum(list, s => s.mcap || 0), weight: d3.sum(list, s => s.weight || 0) };
    for (const tf of Object.keys(METRICS)) o[tf] = tf === "RV" ? d3.median(list, s => s.relVol) : capWeighted(list, METRICS[tf].key);
    return o;
  }).sort((a, b) => b.mcap - a.mcap);
}

// ------------------------------------------------------------ render all
function renderAll() {
  renderTape();
  renderStatus();
  syncTfSegs();
  if (state.view === "opps") loadOpps();
  if (state.view === "overview") renderOverview();
  if (state.view === "watch") renderMyStocks();
  if (PF_SUBS.includes(state.view) && state.view !== "pffit") loadPortfolio();   // pffit: nothing personal until a click
  if (state.view === "pffit") renderFit();
  if (state.view === "screener") renderScreener();
  if (state.view === "sectors") renderSectors();
  if (state.view === "sectors") loadRotation();
  if (state.view === "diary") loadDiary();
  if (state.view === "etf") loadEtf();
  if (state.view === "alerts") loadAlerts();
  if (state.view === "brief") loadBrief();
  if (state.detail) { renderDetailHeader(); renderTA(); }
}

function renderTape() {
  const order = ["^NDX", "^GSPC", "^DJI", "^RUT", "^VIX", "^VXN", "^TNX", "DX-Y.NYB", "GC=F", "CL=F", "BTC-USD"];
  const idx = state.snap.indices;
  $("#tape").innerHTML = order.filter(k => idx[k]).map(k => {
    const x = idx[k], d = k === "^TNX" ? 3 : 2;
    return `<button class="tape-item" data-sym="${esc(k)}"><span class="l">${esc(x.label)}</span>
      <span class="v">${fNum(x.price, d)}<span class="${sign(x.chgPct)}">${fPct(x.chgPct)}</span></span></button>`;
  }).join("");
}
$("#tape").addEventListener("click", e => { const b = e.target.closest("[data-sym]"); if (b) openDetail(b.dataset.sym); });

function renderStatus() {
  const st = state.snap.status, note = state.snap.marketNote || {};
  let label = { open: "Mercato aperto", pre: "Pre-apertura", post: "Dopo la chiusura", closed: "Mercato chiuso" }[st] || st;
  if (st === "holiday") {
    const re = note.reopen ? new Date(note.reopen + "T12:00:00").toLocaleDateString("it-IT", { weekday: "long", day: "numeric", month: "long" }) : "";
    label = `Mercato USA chiuso · festività (${note.holiday})${re ? ` · riapre ${re}` : ""}`;
  } else if (note.earlyClose && ["pre", "open"].includes(st)) {
    label += ` · chiusura anticipata alle 13:00 ora NY (${nyToLocal(13)} ora locale) · ${note.earlyClose}`;
  }
  const el = $("#status");
  el.className = "status " + st;
  el.textContent = label;
  const w = $("#calWarn"), ws = note.calWarnings || [];
  w.hidden = !ws.length;
  w.dataset.info = ws.length ? `<b>Da controllare</b><ul class="why">${ws.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : "";
}

// ------------------------------------------------------------ timeframe segs
function syncTfSegs() {
  $$("[data-tf-seg]").forEach(seg => {
    const small = seg.classList.contains("small");
    const tfs = small ? PERF_TFS : Object.keys(METRICS);
    if (!seg.dataset.built || seg.dataset.built !== String(tfs.length)) {
      seg.innerHTML = tfs.map(tf => `<button data-tf="${tf}">${esc(METRICS[tf].label)}</button>`).join("");
      seg.dataset.built = tfs.length;
    }
    seg.querySelectorAll("button").forEach(b => b.classList.toggle("on", b.dataset.tf === state.tf));
  });
}
document.addEventListener("click", e => {
  const b = e.target.closest("[data-tf-seg] button");
  if (!b) return;
  state.tf = b.dataset.tf; LS.set("tf", state.tf);
  renderAll();
});

// ------------------------------------------------------------ treemap
// short sector names for narrow treemap headers (phase 8B.1)
const SEC_SHORT = { "Telecomunicazioni": "Telecom.", "Beni di prima necessità": "Beni primari", "Materiali di base": "Materiali", "Consumi discrezionali": "Consumi discr.",
  "Immobiliare": "Immobil.", "Industria": "Industria", "Energia": "Energia", "Utility": "Utility", "Sanità": "Sanità", "Finanza": "Finanza", "Tecnologia": "Tecnologia" };
const SEC_TINY = { "Telecomunicazioni": "Tel.", "Beni di prima necessità": "Beni", "Materiali di base": "Mat.", "Consumi discrezionali": "Cons.", "Immobiliare": "Imm.",
  "Industria": "Ind.", "Energia": "En.", "Utility": "Ut.", "Sanità": "San.", "Finanza": "Fin.", "Tecnologia": "Tec." };
// list under the market map: every sector with its value and stocks, so small boxes stay readable (touch and keyboard)
function mapListHTML(tf) {
  const secs = sectors().slice().sort((a, b) => (b.mcap || 0) - (a.mcap || 0));
  const by = d3.group(stocks(), s => s.sector);
  return `<details class="map-list" ${innerWidth < 700 ? "open" : ""}><summary><span class="small">Elenco dei settori e dei titoli (${secs.length} settori) · utile per i riquadri piccoli</span></summary>
    <div class="ml-grid">${secs.map(c => { const xs = (by.get(c.name) || []).slice().sort((a, b) => (b.mcap || 0) - (a.mcap || 0));
      return `<details class="ml-sec"><summary><b>${esc(c.name)}</b> <span class="${tf === "RV" ? "" : sign(c[tf])}">${fMetric(tf, c[tf])}</span> <span class="muted small">${xs.length} titoli</span></summary>
        <ul>${xs.map(x => `<li><button class="link-btn" data-open-map="${esc(x.ticker)}">${esc(x.ticker)}</button> <span class="muted small">${esc(x.name)}</span> <span class="${tf === "RV" ? "" : sign(val(x, tf))}">${fMetric(tf, val(x, tf))}</span></li>`).join("")}</ul></details>`; }).join("")}</div></details>`;
}
document.addEventListener("click", e => { const b = e.target.closest("[data-open-map]"); if (b) openDetail(b.dataset.openMap); });
function renderTreemap(el, opts = {}) {
  const W = el.clientWidth, H = el.clientHeight;
  if (!W || !H) return;
  const tf = state.tf, color = colorFor(tf);
  let list = stocks();
  if (state.zoom && opts.zoomable) list = list.filter(s => s.sector === state.zoom);
  const sizeOf = s => state.size === "equal" ? 1 : Math.max(s.mcap || 0, 1);
  const tree = { children: [...d3.group(list, s => s.sector)].map(([sec, ss]) => ({
    name: sec, children: [...d3.group(ss, s => s.industry)].map(([ind, xs]) => ({ name: ind, children: xs })),
  })) };
  const root = d3.hierarchy(tree).sum(d => d.ticker ? sizeOf(d) : 0).sort((a, b) => b.value - a.value);
  d3.treemap().size([W, H]).tile(d3.treemapSquarify.ratio(1.2))
    .paddingOuter(d => d.depth === 1 ? 1 : d.depth === 2 ? 0.5 : 0)
    .paddingTop(d => d.depth === 1 ? 17 : d.depth === 2 ? 0.5 : 0)
    .paddingInner(d => d.depth === 0 ? 3 : 1)
    .round(true)(root);

  const find = (opts.find || "").trim().toUpperCase();
  const finds = find ? find.split(/[\s,]+/).filter(Boolean) : [];
  const secAgg = new Map(sectors().map(s => [s.name, s]));
  let html = "";
  for (const sec of root.children || []) {
    const w = sec.x1 - sec.x0, h = sec.y1 - sec.y0, agg = secAgg.get(sec.data.name);
    // phase 8B.1: the full name when it fits, a short one otherwise, nothing cut in half (full name + value in the title)
    const full = sec.data.name, val1 = agg ? fMetric(tf, agg[tf]) : "", fit = t => t.length * 6.3 + 12 <= w;
    const label = fit(full) ? full : fit(SEC_SHORT[full] || full) ? (SEC_SHORT[full] || full) : fit(SEC_TINY[full] || "") ? SEC_TINY[full] : "";
    const showV = agg && w > label.length * 6.3 + 60;
    html += `<div class="sector-box" style="left:${sec.x0}px;top:${sec.y0}px;width:${w}px;height:${h}px">
      <div class="sector-h" data-sector="${esc(full)}" title="${esc(full)}${val1 ? " " + esc(String(val1).replace(/<[^>]+>/g, "")) : ""} · clicca per ingrandire"><span class="sn">${esc(label)}</span>${showV ? `<span class="sv">${val1}</span>` : ""}</div></div>`;
  }
  for (const leaf of root.leaves()) {
    const s = leaf.data, w = leaf.x1 - leaf.x0, h = leaf.y1 - leaf.y0;
    if (w < 1 || h < 1) continue;
    const v = val(s, tf);
    const fs = Math.min(w / (s.ticker.length * 0.68 + 0.5), h / 2.4, 38);
    let inner = "";
    if (fs >= 7.5) {
      inner = `<span class="tk" style="font-size:${fs.toFixed(1)}px">${esc(s.ticker)}</span>`;
      const fs2 = Math.max(8.5, fs * 0.56);
      if (h > fs + fs2 + 6 && w > fs2 * 3.8) inner += `<span class="pc" style="font-size:${fs2.toFixed(1)}px">${fMetric(tf, v)}</span>`;
    }
    const dim = finds.length && !finds.some(f => s.ticker.startsWith(f) || s.name.toUpperCase().includes(f)) ? " dim" : "";
    const prev = state.prevPrices.get(s.ticker);
    const flash = prev != null && prev !== s.price && tf === "1D" ? " flash" : "";
    html += `<div class="tile${dim}${flash}" data-t="${esc(s.ticker)}" style="left:${leaf.x0}px;top:${leaf.y0}px;width:${w}px;height:${h}px;background:${color(v)}">${inner}</div>`;
  }
  el.innerHTML = html;
  el.onmousemove = ev => {
    const t = ev.target.closest(".tile");
    if (!t) return hideTip();
    showTip(tileTip(state.bySym.get(t.dataset.t)), ev);
  };
  el.onmouseleave = hideTip;
  el.onclick = ev => {
    const t = ev.target.closest(".tile");
    if (t) { hideTip(); return openDetail(t.dataset.t); }
    const sh = ev.target.closest(".sector-h");
    if (sh) {
      if (opts.zoomable) { state.zoom = state.zoom ? null : sh.dataset.sector; renderOvMap(); }
    }
  };
}

function tileTip(s) {
  if (!s) return "";
  const tf = state.tf, color = colorFor(tf);
  const peers = stocks().filter(p => p.industry === s.industry).sort((a, b) => (b.mcap || 0) - (a.mcap || 0)).slice(0, 10);
  const v = val(s, tf);
  return `<div class="tip-h">${esc(s.sector)} › ${esc(s.industry)}</div>
    <div class="tip-main"><b>${esc(s.ticker)}</b><span class="num">${fPrice(s.price)} <span class="${sign(s.chgPct)}">${fPct(s.chgPct)}</span></span></div>
    <div class="tip-name">${esc(s.name)} · ${fBig(s.mcap)} · peso ${fW(s)}</div>
    ${spark(s.spark, 330, 52, s.prevClose)}
    ${tf !== "1D" ? `<div class="tip-row" style="margin-top:6px"><span>${esc(METRICS[tf].label)}</span><b class="${tf === "RV" ? "" : sign(v)}">${fMetric(tf, v)}</b></div>` : ""}
    ${peers.length > 1 ? `<table class="tip-peers">${peers.map(p => `<tr class="${p.ticker === s.ticker ? "me" : ""}">
      <td>${esc(p.ticker)}</td><td>${spark(p.spark, 70, 16, p.prevClose)}</td><td class="num">${fPrice(p.price)}</td>
      <td><span class="chip" style="background:${color(val(p, tf))}">${fMetric(tf, val(p, tf))}</span></td></tr>`).join("")}</table>` : ""}`;
}

// ------------------------------------------------------------ overview
function renderOverview() {
  renderKpis();
  renderOvMap();
  $$("[data-legend]").forEach(el => el.innerHTML = legendHTML(state.tf));
  renderIndexChart();
  renderEarnings();
  loadWhy();
  loadMacro();
}

// indicative volatility bands (same for VIX and VXN)
function volBand(v) {
  if (!isNum(v)) return { name: "—", cls: "" };
  return v < 15 ? { name: "calmo", cls: "calm", key: 0 } : v < 20 ? { name: "normale", cls: "norm", key: 1 }
    : v < 30 ? { name: "nervosismo", cls: "nerv", key: 2 } : { name: "paura", cls: "fear", key: 3 };
}
function volInfo(vix, vxn) {
  const line = (n, x) => x ? `<b>${n}</b> ${fNum(x.price, 1)} (${fPct(x.chgPct, 1)} oggi): <b>${volBand(x.price).name}</b>` : `<b>${n}</b> non disponibile`;
  const ref = vxn || vix;   // VXN is the Nasdaq-100's own gauge
  const effect = ["Mercato tranquillo: di solito movimenti giornalieri piccoli. Attenzione però all'eccesso di fiducia.",
    "Oscillazioni nella media: nessun segnale particolare.",
    "Oscillazioni più ampie del solito: le azioni tendono a muoversi di più, in entrambe le direzioni, e i cali possono essere bruschi.",
    "Forte agitazione, di solito durante cali marcati: movimenti giornalieri molto ampi. A volte i picchi di paura hanno coinciso con i minimi, ma non è una regola."][volBand(ref?.price).key ?? 1];
  return `<b>Cosa misurano.</b> Il VIX indica quanto il mercato si aspetta che l'S&P 500 oscilli nei prossimi 30 giorni, ricavato dai prezzi delle opzioni.
    Il VXN fa lo stesso per il Nasdaq-100: di solito è più alto, perché i titoli tecnologici oscillano di più.<br><br>
    ${line("VIX", vix)}<br>${line("VXN", vxn)}<br><br>
    <b>Fasce indicative:</b> sotto 15 calmo · 15–20 normale · 20–30 nervosismo · sopra 30 paura.<br><br>
    <b>Cosa comporta ora${vxn ? " (secondo il VXN)" : ""}:</b> ${effect}<br>
    <span class="muted">Quando la volatilità sale, di solito le azioni scendono: per questo la sua variazione è in rosso se sale.</span>`;
}

// Oggi's market map: clicking a sector name zooms on it, clicking again (or "Tutti i settori") shows the whole market
function renderOvMap() {
  $("#ovUnzoom").hidden = !state.zoom;
  renderTreemap($("#ovMap"), { zoomable: true });
  const ml = $("#ovMapList"), keep = ml.querySelector(".map-list"), wasOpen = keep ? keep.open : null;
  const openSecs = new Set([...ml.querySelectorAll(".ml-sec[open] > summary b")].map(b => b.textContent));
  ml.innerHTML = mapListHTML(state.tf);
  if (wasOpen !== null) ml.querySelector(".map-list").open = wasOpen;
  ml.querySelectorAll(".ml-sec").forEach(d => { if (openSecs.has(d.querySelector("summary b").textContent)) d.open = true; });
}
$("#ovUnzoom").addEventListener("click", () => { state.zoom = null; renderOvMap(); });

function renderKpis() {
  const S = stocks(), ndx = state.snap.indices["^NDX"], vix = state.snap.indices["^VIX"], vxn = state.snap.indices["^VXN"];
  const adv = S.filter(s => s.chgPct > 0).length, dec = S.filter(s => s.chgPct < 0).length, unch = S.length - adv - dec;
  const med = d3.median(S, s => s.chgPct);
  const above = k => Math.round(S.filter(s => s[k] > 0).length / S.length * 100);
  const kpi = (l, v, s, extra = "") => `<div class="kpi"><div class="l">${l}</div><div class="v">${v}</div><div class="s">${s}</div>${extra}</div>`;
  $("#kpis").innerHTML = [
    ndx ? kpi("Nasdaq-100", fNum(ndx.price, 2), `<span class="${sign(ndx.chg)}">${fChg(ndx.chg)} (${fPct(ndx.chgPct)})</span> · da inizio anno <span class="${sign(ndx.perfYTD)}">${fPct(ndx.perfYTD, 1)}</span>`) : "",
    kpi("In rialzo / In ribasso", `<span class="up">${adv}</span> <span class="muted">/</span> <span class="down">${dec}</span>`,
      `${unch} invariati · mediana ${fPct(med)}`,
      `<div class="breadth-bar"><i style="width:${adv}%;background:var(--up)"></i><i style="width:${unch}%;background:var(--baseline)"></i><i style="width:${dec}%;background:var(--down)"></i></div>`),
    kpi("Sopra le medie 20 / 40 / 60 · 200", `${above("vsSma20")} / ${above("vsSma40")} / ${above("vsSma60")} <span class="muted">·</span> ${above("vsSma200")}%`,
      "% dei titoli con il prezzo sopra la media"),
    vix || vxn ? kpi(`Volatilità VIX / VXN ${info(volInfo(vix, vxn))}`,
      [vix, vxn].map(x => x ? fNum(x.price, 2) : "—").join(` <span class="muted">/</span> `),
      [["VIX", vix], ["VXN", vxn]].filter(([, x]) => x).map(([n, x]) => `${n} <span class="${sign(-x.chgPct)}">${fPct(x.chgPct, 1)}</span> <b class="band ${volBand(x.price).cls}">${volBand(x.price).name}</b>`).join(" · ")) : "",
  ].join("");
}

// generic line chart (index-based x so overnight/weekend gaps collapse)
function lineChart(el, series, o = {}) {
  el.innerHTML = "";
  const W = el.clientWidth || 360, H = o.height || 200;
  const m = { t: 12, r: o.pctAxis ? 48 : 58, b: 22, l: 6 };
  const iw = W - m.l - m.r, ih = H - m.t - m.b;
  const main = series[0].pts;
  const n = o.slots || main.length;
  const x = d3.scaleLinear().domain([0, Math.max(1, n - 1)]).range([0, iw]);
  const all = series.flatMap(s => s.pts.map(p => p.v)).filter(isNum);
  if (o.baseline != null) all.push(o.baseline);
  (o.refs || []).forEach(r => isNum(r.v) && all.push(r.v));
  const [lo, hi] = d3.extent(all);
  const padY = (hi - lo) * 0.08 || 1;
  const y = d3.scaleLinear().domain([lo - padY, hi + padY]).range([ih, 0]).nice(5);
  const svg = d3.select(el).append("svg").attr("width", W).attr("height", H).attr("role", "img").attr("aria-label", o.label || "chart");
  const g = svg.append("g").attr("transform", `translate(${m.l},${m.t})`);
  g.append("g").attr("class", "gridline").call(d3.axisLeft(y).ticks(5).tickSize(-iw).tickFormat("")).attr("transform", `translate(0,0)`);
  g.append("g").attr("class", "axis").attr("transform", `translate(${iw},0)`)
    .call(d3.axisRight(y).ticks(5).tickSize(0).tickPadding(6).tickFormat(o.yFmt || (v => fNum(v, v >= 1000 ? 0 : 2)))).select(".domain").remove();
  // x ticks from timestamps
  const tickIdx = pickTicks(main, o.range, 6);
  g.append("g").attr("class", "axis").attr("transform", `translate(0,${ih})`)
    .call(d3.axisBottom(x).tickValues(tickIdx).tickSize(0).tickPadding(8).tickFormat(i => tickLabel(main[i]?.t, o.range)))
    .select(".domain").attr("stroke", css("--baseline"));
  if (o.baseline != null) {
    g.append("line").attr("x1", 0).attr("x2", iw).attr("y1", y(o.baseline)).attr("y2", y(o.baseline)).attr("stroke", css("--baseline")).attr("stroke-width", 1);
    if (o.baselineLabel) { // put the label on whichever side of the reference line the series is not
      const lastV = main.at(-1)?.v, above = isNum(lastV) && lastV >= o.baseline;
      g.append("text").attr("class", "ref-label").attr("x", iw - 4).attr("text-anchor", "end")
        .attr("y", y(o.baseline) + (above ? 13 : -5)).text(o.baselineLabel); }
  }
  (o.refs || []).filter(r => isNum(r.v)).forEach(r => {
    g.append("line").attr("x1", 0).attr("x2", iw).attr("y1", y(r.v)).attr("y2", y(r.v)).attr("stroke", r.color).attr("stroke-width", 1).attr("opacity", 0.8);
    g.append("text").attr("class", "ref-label").attr("x", 3).attr("y", y(r.v) - 3).text(r.label);
  });
  series.forEach((s, si) => {
    const line = d3.line().defined(p => isNum(p.v)).x((p, i) => x(i)).y(p => y(p.v)).curve(d3.curveMonotoneX);
    if (si === 0 && o.area !== false && (series.length === 1 || o.areaFirst)) {
      const gid = "g" + Math.random().toString(36).slice(2);
      const grad = svg.append("defs").append("linearGradient").attr("id", gid).attr("x1", 0).attr("x2", 0).attr("y1", 0).attr("y2", 1);
      grad.append("stop").attr("offset", "0%").attr("stop-color", s.color).attr("stop-opacity", 0.22);
      grad.append("stop").attr("offset", "100%").attr("stop-color", s.color).attr("stop-opacity", 0);
      const area = d3.area().defined(p => isNum(p.v)).x((p, i) => x(i)).y0(ih).y1(p => y(p.v)).curve(d3.curveMonotoneX);
      g.append("path").datum(s.pts).attr("d", area).attr("fill", `url(#${gid})`);
    }
    g.append("path").datum(s.pts).attr("d", line).attr("fill", "none").attr("stroke", s.color).attr("stroke-width", s.width || 2).attr("stroke-linejoin", "round")
      .attr("stroke-dasharray", s.dash || null);
    const last = s.pts.length - 1;
    if (s.dot !== false && last >= 0 && isNum(s.pts[last].v)) {
      g.append("circle").attr("cx", x(last)).attr("cy", y(s.pts[last].v)).attr("r", 3.5).attr("fill", s.color).attr("stroke", css("--surface")).attr("stroke-width", 2);
    }
  });
  // crosshair
  const xl = g.append("line").attr("class", "xhair").attr("y1", 0).attr("y2", ih).style("opacity", 0);
  const dots = series.map(s => g.append("circle").attr("r", 4).attr("fill", s.color).attr("stroke", css("--surface")).attr("stroke-width", 2).style("opacity", 0));
  g.append("rect").attr("width", iw).attr("height", ih).attr("fill", "transparent")
    .on("mousemove", ev => {
      const [mx] = d3.pointer(ev);
      const i = Math.max(0, Math.min(main.length - 1, Math.round(x.invert(mx))));
      xl.attr("x1", x(i)).attr("x2", x(i)).style("opacity", 1);
      series.forEach((s, si) => { const p = s.pts[i]; if (p && isNum(p.v)) dots[si].attr("cx", x(i)).attr("cy", y(p.v)).style("opacity", 1); });
      showTip(o.tip ? o.tip(i) : "", ev);
      if (o.onHover) o.onHover(i);
    })
    .on("mouseleave", () => { xl.style("opacity", 0); dots.forEach(d => d.style("opacity", 0)); hideTip(); if (o.onHover) o.onHover(null); });
  return { x, y, svg, g, m, iw, ih };
}
function pickTicks(pts, range, want) {
  if (!pts.length) return [];
  if (range === "1D") {
    const out = [];
    pts.forEach((p, i) => { const d = new Date(p.t * 1000); const mm = +d.toLocaleString("en-US", { timeZone: tz, minute: "numeric" }); const hh = +d.toLocaleString("en-US", { timeZone: tz, hour: "numeric", hour12: false }); if (mm === 0 && hh % 1 === 0) out.push(i); });
    return out.length > want ? out.filter((_, k) => k % 2 === 0) : out;
  }
  if (range === "5D") {
    const out = []; let last = "";
    pts.forEach((p, i) => { const d = fDate(p.t); if (d !== last) { out.push(i); last = d; } });
    return out;
  }
  const step = Math.max(1, Math.floor(pts.length / want));
  return d3.range(0, pts.length, step).slice(0, want);
}
function tickLabel(t, range) {
  if (t == null) return "";
  if (range === "1D") return fTime(t).replace(":00", "");
  if (range === "5Y") return fDate(t, { year: "numeric" });
  if (range === "MAX") return fDate(t, { year: "numeric" });
  if (range === "1Y" || range === "YTD" || range === "6M") return fDate(t, { month: "short" });
  return fDate(t);
}

function renderIndexChart() {
  const ndx = state.snap.indices["^NDX"];
  const el = $("#ndxChart");
  if (!ndx || !ndx.spark?.length) { el.innerHTML = `<div class="empty">Nessun dato intraday per ora</div>`; return; }
  $("#ndxHead").innerHTML = `<span class="num">${fNum(ndx.price, 2)}</span> <span class="${sign(ndx.chg)}">${fChg(ndx.chg)} (${fPct(ndx.chgPct)})</span>`;
  const pts = ndx.spark.map((v, i) => ({ t: ndx.sparkT[i], v }));
  const col = ndx.price >= ndx.prevClose ? css("--up") : css("--down");
  lineChart(el, [{ pts, color: col }], {
    height: 210, baseline: ndx.prevClose, baselineLabel: `Chiusura prec. ${fNum(ndx.prevClose, 0)}`, range: "1D", label: "Nasdaq-100 intraday",
    tip: i => { const p = pts[i]; const c = (p.v / ndx.prevClose - 1) * 100;
      return `<div class="tip-h">${fTime(p.t)} ora NY (${fLocal(p.t * 1000)} ora locale)</div><div class="tip-row"><span>NDX</span><b class="num">${fNum(p.v, 2)}</b></div>
        <div class="tip-row"><span>vs chiusura prec.</span><b class="${sign(c)}">${fPct(c)}</b></div>`; },
  });
}

// horizontal diverging bars (used for movers, sectors, sector members)
function hbars(el, rows, o) {
  el.innerHTML = "";
  if (!rows.length) { el.innerHTML = `<div class="empty">Nessun dato</div>`; return; }
  const W = el.clientWidth || 360, rh = o.rowH || 22, H = rows.length * rh + 4;
  const nameW = o.nameW || 64, valW = o.valW || 58, iw = W - nameW - valW;
  const ext = d3.max(rows, r => Math.abs(r.v)) || 1;
  const hasNeg = rows.some(r => r.v < 0), hasPos = rows.some(r => r.v > 0);
  const x = d3.scaleLinear().domain([hasNeg ? -ext : 0, hasPos ? ext : 0]).range([0, iw]);
  const svg = d3.select(el).append("svg").attr("width", W).attr("height", H);
  const up = css("--up"), dn = css("--down");
  const row = svg.selectAll("g").data(rows).join("g").attr("class", "bar-row").attr("transform", (_, i) => `translate(0,${i * rh})`);
  row.append("rect").attr("class", "hit").attr("width", W).attr("height", rh).attr("fill", "transparent").attr("rx", 4);
  row.append("text").attr("class", "bar-name").attr("x", 4).attr("y", rh / 2 + 4).text(r => r.name);
  row.append("rect").attr("x", r => nameW + Math.min(x(0), x(r.v))).attr("y", 5).attr("height", rh - 10)
    .attr("width", r => Math.max(1.5, Math.abs(x(r.v) - x(0)))).attr("rx", 2)
    .attr("fill", r => r.color || (r.v >= 0 ? up : dn));
  row.append("text").attr("class", "bar-label").attr("x", W - 4).attr("y", rh / 2 + 4).attr("text-anchor", "end").text(r => r.label);
  svg.append("line").attr("x1", nameW + x(0)).attr("x2", nameW + x(0)).attr("y1", 0).attr("y2", H).attr("stroke", css("--baseline"));
  row.on("mousemove", (ev, r) => o.tip && showTip(o.tip(r), ev)).on("mouseleave", hideTip)
    .on("click", (ev, r) => { hideTip(); o.click && o.click(r); });
}

function miniTable(el, list, cols, empty = "Nessun elemento") {
  if (!list.length) { el.innerHTML = `<div class="empty">${empty}</div>`; return; }
  el.innerHTML = `<table>${list.map(s => `<tr data-t="${esc(s.ticker)}">${cols(s)}</tr>`).join("")}</table>`;
  el.onclick = e => { const tr = e.target.closest("tr[data-t]"); if (tr && !e.target.closest(".star")) openDetail(tr.dataset.t); };
}
const pill = v => `<span class="pill ${sign(v)}">${fPct(v)}</span>`;

// ------------------------------------------------------------ signals & presets
const PRESETS = [
  { id: "all", label: "Tutti", f: () => true },
  { id: "watch", label: "★ Preferiti", f: s => state.watch.has(s.ticker) },
  { id: "gainers", label: "Su > 2% oggi", f: s => s.chgPct > 2 },
  { id: "losers", label: "Giù > 2% oggi", f: s => s.chgPct < -2 },
  { id: "highs", label: "Vicino al max 52 sett.", f: s => s.fromHi52 > -2, desc: "entro il 2% dal massimo a 52 settimane" },
  { id: "lows", label: "Vicino al min 52 sett.", f: s => s.fromLo52 < 5, desc: "entro il 5% dal minimo a 52 settimane" },
  { id: "volume", label: "Volumi insoliti", f: s => s.relVol >= 1.5, desc: "volume relativo ≥ 1,5×" },
  { id: "gapup", label: "Gap al rialzo", f: s => s.gapPct > 1.5, desc: "apertura oltre l'1,5% sopra la chiusura precedente" },
  { id: "gapdown", label: "Gap al ribasso", f: s => s.gapPct < -1.5, desc: "apertura oltre l'1,5% sotto la chiusura precedente" },
  { id: "overbought", label: "Ipercomprato", f: s => s.rsi > 70, desc: "RSI(14) sopra 70" },
  { id: "oversold", label: "Ipervenduto", f: s => s.rsi < 30, desc: "RSI(14) sotto 30" },
  { id: "above3", label: "Sopra 20, 40 e 60", f: s => s.vsSma20 > 0 && s.vsSma40 > 0 && s.vsSma60 > 0, desc: "prezzo sopra le medie a 20, 40 e 60 giorni" },
  { id: "below3", label: "Sotto 20, 40 e 60", f: s => s.vsSma20 < 0 && s.vsSma40 < 0 && s.vsSma60 < 0, desc: "prezzo sotto le medie a 20, 40 e 60 giorni" },
  { id: "golden", label: "Sopra medie 50 e 200", f: s => s.vsSma50 > 0 && s.vsSma200 > 0 },
  { id: "broken", label: "Sotto media 200", f: s => s.vsSma200 < 0 },
  { id: "earnings", label: "Trimestrale ≤ 14 g", f: s => daysTo(s.earningsTs) != null && daysTo(s.earningsTs) <= 14, desc: "conti in uscita nelle prossime due settimane" },
  { id: "value", label: "P/E atteso < 20", f: s => s.fpe > 0 && s.fpe < 20 },
  { id: "upside", label: "Potenziale analisti > 20%", f: s => s.upside > 20 },
  { id: "cheap", label: "Valutazione economica", f: s => s.valLabel === "Economica", desc: "più economica del settore e/o della propria storia" },
  { id: "rich", label: "Valutazione cara", f: s => s.valLabel === "Cara", desc: "più cara del settore e/o della propria storia" },
  { id: "upgrades", label: "Upgrade recenti", f: s => s.up30 > s.down30, desc: "più upgrade che downgrade negli ultimi 30 giorni" },
  { id: "estUp", label: "Stime in rialzo", f: s => s.epsRev30 > 3, desc: "stima utile del prossimo anno alzata di oltre il 3% in 30 giorni" },
  { id: "sigBuy", label: "Segnale positivo", f: s => s.sigScore >= 20, desc: "segnale finale Positivo o Molto positivo" },
  { id: "sigNeutral", label: "Segnale neutro", f: s => sigName(s.signal) === "Neutro", desc: "segnale finale Neutro (punteggio tra −20 e +20)" },
  { id: "sigSell", label: "Segnale negativo", f: s => s.sigScore <= -20, desc: "segnale finale Negativo o Molto negativo" },
  { id: "estDown", label: "Stime in calo", f: s => s.epsRev30 < -3, desc: "stima utile del prossimo anno abbassata di oltre il 3% in 30 giorni" },
];
// ⓘ text for every screener quick filter
const PRESET_INFO = {
  all: "Tutti i titoli del Nasdaq-100, senza filtri.",
  watch: "Solo i titoli che hai segnato con ★ (gli stessi di Azioni → Preferiti).",
  gainers: "Titoli saliti più del 2% oggi rispetto alla chiusura precedente.",
  losers: "Titoli scesi più del 2% oggi rispetto alla chiusura precedente.",
  gapup: "Il titolo ha aperto oltre l'1,5% sopra la chiusura di ieri: di solito dopo una notizia uscita a mercato chiuso.",
  gapdown: "Il titolo ha aperto oltre l'1,5% sotto la chiusura di ieri: di solito dopo una notizia uscita a mercato chiuso.",
  volume: "Oggi si scambia almeno 1,5 volte il volume normale per quest'ora: c'è più interesse del solito, spesso per una notizia.",
  earnings: "Presenta i conti trimestrali entro 14 giorni: in quei giorni il prezzo può muoversi molto.",
  above3: "Prezzo sopra le medie a 20, 40 e 60 giorni: il trend di breve e medio periodo è positivo.",
  below3: "Prezzo sotto le medie a 20, 40 e 60 giorni: il trend di breve e medio periodo è negativo.",
  golden: "Prezzo sopra le medie a 50 e 200 giorni: trend di medio e lungo periodo positivo.",
  broken: "Prezzo sotto la media a 200 giorni: trend di lungo periodo negativo. Molti investitori usano la 200 come spartiacque.",
  highs: "Entro il 2% dal prezzo più alto delle ultime 52 settimane: titoli forti.",
  lows: "Entro il 5% dal prezzo più basso delle ultime 52 settimane: titoli deboli (o possibili occasioni, da verificare).",
  overbought: "RSI sopra 70: il titolo è salito molto e in fretta. A volte segue una pausa, ma nei trend forti può restare ipercomprato a lungo.",
  oversold: "RSI sotto 30: il titolo è sceso molto e in fretta. A volte segue un rimbalzo, ma nei trend deboli può restare ipervenduto a lungo.",
  cheap: "Più economica dei titoli dello stesso settore e/o della propria storia (P/E, P/S, EV/EBITDA): in media oltre il 15% sotto i confronti.",
  rich: "Più cara dei titoli dello stesso settore e/o della propria storia: in media oltre il 18% sopra i confronti.",
  value: "Il prezzo è meno di 20 volte gli utili attesi nei prossimi 12 mesi.",
  upside: "Il prezzo obiettivo medio degli analisti è oltre il 20% sopra il prezzo attuale.",
  upgrades: "Negli ultimi 30 giorni le banche d'affari hanno alzato il giudizio più volte di quante l'abbiano abbassato.",
  estUp: "Negli ultimi 30 giorni gli analisti hanno alzato di oltre il 3% la stima degli utili del prossimo anno.",
  estDown: "Negli ultimi 30 giorni gli analisti hanno abbassato di oltre il 3% la stima degli utili del prossimo anno.",
  sigBuy: "Segnale finale Positivo o Molto positivo (punteggio da +20 in su), da analisti, valutazione e notizie. Esclude i titoli con «Dati insufficienti». Non è un consiglio d'acquisto.",
  sigNeutral: "Segnale finale Neutro: punteggio tra −20 e +20. Esclude i titoli con «Dati insufficienti» (una sola parte disponibile su tre).",
  sigSell: "Segnale finale Negativo o Molto negativo (punteggio da −20 in giù), da analisti, valutazione e notizie. Esclude i titoli con «Dati insufficienti». Non è un consiglio di vendita.",
};
// screener quick filters grouped by topic (same filters, only laid out in rows)
const PRESET_GROUPS = [
  { label: "", ids: ["all", "watch"] },
  { label: "Oggi", ids: ["gainers", "losers", "gapup", "gapdown", "volume", "earnings"] },
  { label: "Trend", ids: ["above3", "below3", "golden", "broken", "highs", "lows", "overbought", "oversold"] },
  { label: "Valutazione", ids: ["cheap", "rich", "value"] },
  { label: "Analisti", ids: ["upside", "upgrades", "estUp", "estDown"] },
  { label: "Segnale", ids: ["sigBuy", "sigNeutral", "sigSell"] },
];
function daysTo(ts) {
  if (!isNum(ts)) return null;
  const d = (ts * 1000 - Date.now()) / 864e5;
  return d >= -0.5 ? d : null;
}

document.addEventListener("click", e => {
  const b = e.target.closest("[data-star]");
  if (!b) return;
  e.stopPropagation();
  toggleWatch(b.dataset.star);
});
function toggleWatch(t) {
  state.watch.has(t) ? state.watch.delete(t) : state.watch.add(t);
  saveWatch();
  if (state.view === "watch") renderMyStocks();
  if (state.view === "overview") renderEarnings();
  if (state.view === "screener") renderScreener();
  if (state.detail === t) renderDetailHeader();
  if (state.view === "etf") renderEtf();
  if (state.panel === "etf" && etfS.open) openEtf(etfS.open);
}

// ------------------------------------------------------------ earnings (phase 8B.1: last 7 days + next 7, grouped by day)
// Details from /api/earnings (earnings.py). Missing figures are written "Non disponibile", never guessed. Three dates are
// kept apart: the day of the announcement, the accounting quarter, and the day the dashboard downloaded the data.
const earn = { data: {}, at: 0, open: new Set() };
const EARN_MOVE_INFO = `Quanto si è mosso in media il titolo, in più o in meno, nel giorno di reazione alle ultime trimestrali (la seduta stessa se i conti escono prima dell'apertura,
  quella dopo se escono dopo la chiusura), calcolato dai prezzi giornalieri. <b>Indica quanto si rischia tenendo il titolo durante i conti</b>, non in che direzione andrà.`;
const EARN_DATE_INFO = `<b>Data confermata</b>: Yahoo Finance indica che la data viene dalla società. <b>Data stimata</b>: Yahoo la stima dal calendario degli anni passati,
  la società non l'ha ancora annunciata: può cambiare. <b>Conferma non indicata</b>: la fonte non dice se è confermata; trattala come non verificata finché non la trovi
  sul sito della società (sezione «Investor relations»).`;
const EARN_SRC_INFO = `Stime degli analisti, utile per azione effettivo e sorpresa vengono da Yahoo Finance; i ricavi effettivi dai bilanci trimestrali scaricati
  da Yahoo, solo quando il trimestre risulta annunciato in quella data. La <b>guidance</b> (le previsioni della società) non è in nessuna fonte gratuita leggibile
  dalla dashboard: leggila nel comunicato della società. Un dato riscaricato oggi non vuol dire pubblicato oggi: conta la data dell'annuncio.`;
const NA = `<span class="na">Non disponibile</span>`;
async function loadEarnDetails() {
  if (Date.now() - earn.at < 60_000) return;
  earn.at = Date.now();
  try {
    const d = await getJSON("/api/earnings");
    earn.data = d.data || {};
    if (d.loading) { earn.at = 0; setTimeout(loadEarnDetails, 4000); }
  } catch { return; }
  if (state.view === "overview") { renderEarnings(); renderAgenda(); }
}
function earnWhen(ts) {          // Yahoo gives a time only when the company announced it
  const h = +new Date(ts * 1000).toLocaleString("en-US", { timeZone: tz, hour: "numeric", hour12: false });
  return h > 0 && h < 12 ? "prima dell'apertura" : h >= 16 ? "dopo la chiusura" : "orario non indicato";
}
const nyDay = ts => new Date(ts * 1000).toLocaleDateString("en-CA", { timeZone: tz });
const dayLong = iso => new Date(iso + "T12:00:00").toLocaleDateString("it-IT", { weekday: "long", day: "numeric", month: "long" });
const monthOf = ym => ym ? new Date(ym.slice(0, 7) + "-15T12:00:00").toLocaleDateString("it-IT", { month: "short", year: "numeric" }) : "";
// companies with an earnings date between 7 days ago and 7 days ahead (same window as /api/earnings)
function earnList() {
  const now = Date.now() / 1000;
  return stocks().filter(s => isNum(s.earningsTs) && s.earningsTs - now >= -7 * 86400 && s.earningsTs - now <= 7.5 * 86400);
}
function earnStatus(s) {
  const E = earn.data[s.ticker];
  if (E?.status) return E.status;
  return s.earningsTs * 1000 <= Date.now() ? "attesa dati" : "da pubblicare";
}
const EARN_ST = { "pubblicata": ["Pubblicata", "pub"], "attesa dati": ["Data passata · risultati non ancora nella fonte", "wait"], "da pubblicare": ["Da pubblicare", "next"] };
function earnConfirm(E) {
  if (!E || E.dateConfirmed == null) return `<span class="ec-tag warn">conferma non indicata dalla fonte</span>`;
  return E.dateConfirmed ? `<span class="ec-tag ok">data confermata (secondo Yahoo)</span>` : `<span class="ec-tag warn">data stimata da Yahoo, non confermata dalla società</span>`;
}
const usd = v => isNum(v) ? fNum(v, 2) + " $" : NA;
const big = v => isNum(v) ? "$" + fBig(v) : NA;
const surp = v => isNum(v) ? `<span class="${sign(v)}">${fPct(v, 1)}</span>` : NA;
function earnSummary(E, st) {
  if (!E) return "Dettagli in caricamento.";
  if (st === "pubblicata") {
    if (!isNum(E.epsActual) || !isNum(E.epsExpected)) return "Risultati pubblicati: confronto con le attese non disponibile.";
    const d = E.epsSurprise;
    const w = !isNum(d) ? "rispetto alle attese" : Math.abs(d) < 1 ? "in linea con le attese" : d > 0 ? "sopra le attese" : "sotto le attese";
    return `Utile per azione ${w} (${fNum(E.epsActual, 2)} $ contro ${fNum(E.epsExpected, 2)} $ attesi${isNum(d) ? `, sorpresa ${fPct(d, 1)}` : ""}).`
      + (isNum(E.revSurprise) ? ` Ricavi ${E.revSurprise >= 0 ? "sopra" : "sotto"} le attese (${fPct(E.revSurprise, 1)}).` : " Ricavi effettivi non ancora nella fonte.");
  }
  if (st === "attesa dati") return "La data è passata ma Yahoo non ha ancora i risultati: controlla il comunicato della società.";
  return isNum(E.epsExpected) ? `Attesi ${fNum(E.epsExpected, 2)} $ di utile per azione${E.epsAnalysts ? ` (media di ${E.epsAnalysts} analisti)` : ""}${isNum(E.revExpected) ? ` e ricavi per $${fBig(E.revExpected)}` : ""}.` : "Stime degli analisti non disponibili.";
}
function earnRow(s) {
  const E = earn.data[s.ticker], st = earnStatus(s), [stL, stC] = EARN_ST[st];
  const fav = state.watch.has(s.ticker), open = earn.open.has(s.ticker);
  const period = E?.period ? `trimestre chiuso a ${esc(monthOf(E.period))}${E.periodExact ? " (dai bilanci)" : " (stima dalla cadenza dei bilanci)"}` : "trimestre non disponibile";
  const yahoo = `https://finance.yahoo.com/quote/${encodeURIComponent(s.ticker)}/`;
  const site = E?.website && /^https?:\/\//.test(E.website) ? E.website : null;
  const pub = st === "pubblicata";
  const moves = E?.moves?.length ? `<div class="ed-row"><span>Movimenti dopo le ultime trimestrali</span><b>${E.moves.map(m => `<span class="${sign(m.move)}">${fPct(m.move, 1)}</span>`).join(" ")}</b>${isNum(E.usualMove) ? ` <span class="muted">di solito ±${fNum(E.usualMove, 0)}% ${info(EARN_MOVE_INFO)}</span>` : ""}</div>` : "";
  return `<div class="er ${open ? "open" : ""}">
    <div class="er-h"><button class="er-tk" data-open="${esc(s.ticker)}" title="Apri la scheda">${fav ? '<span class="mine" title="Nei tuoi Preferiti">★</span> ' : ""}${esc(s.ticker)}</button>
      <span class="er-n">${esc(s.name)}</span><span class="er-st ${stC}">${stL}</span></div>
    <div class="er-meta">${esc(earnWhen(s.earningsTs))} · ${period}${pub ? "" : " · " + earnConfirm(E) + " " + info(EARN_DATE_INFO)}</div>
    ${st === "attesa dati" ? "" : `<div class="er-grid">
      <div><span>Utile per azione atteso</span><b>${usd(E?.epsExpected)}</b></div>
      <div><span>Utile per azione effettivo</span><b>${pub ? usd(E?.epsActual) : `<span class="muted">non ancora pubblicato</span>`}</b></div>
      <div><span>Sorpresa utile</span><b>${pub ? surp(E?.epsSurprise) : "—"}</b></div>
      <div><span>Ricavi attesi</span><b>${big(E?.revExpected)}</b></div>
      <div><span>Ricavi effettivi</span><b>${pub ? big(E?.revActual) : `<span class="muted">non ancora pubblicati</span>`}</b></div>
      <div><span>Sorpresa ricavi</span><b>${pub ? surp(E?.revSurprise) : "—"}</b></div>
    </div>`}
    <p class="er-sum">${esc(earnSummary(E, st))} <span class="muted">Guidance: non disponibile nella fonte.</span></p>
    <div class="er-src small"><a href="${yahoo}" target="_blank" rel="noopener">Yahoo Finance ↗</a>${site ? ` · <a href="${esc(site)}" target="_blank" rel="noopener">sito della società ↗</a>` : ""}
      · <span class="muted">annuncio ${esc(fDate(s.earningsTs, { day: "numeric", month: "short" }))}${E?.fetched ? ` · dati scaricati il ${esc(dayIT(E.fetched))}` : ""}${E?.analystsDate ? ` · stime del ${esc(dayIT(E.analystsDate))}` : ""}</span> ${info(EARN_SRC_INFO)}
      ${moves || E?.prev ? `<button class="link-btn" data-earn="${esc(s.ticker)}">${open ? "Meno dettagli" : "Storico reazioni"}</button>` : ""}</div>
    ${open ? `<div class="er-more">${moves}${E?.prev ? `<div class="ed-row"><span>Trimestrale precedente (${esc(dayShort(E.prev.ts.slice(0, 10)))})</span><b>attesi ${usd(E.prev.eps)}, effettivi ${usd(E.prev.reported)}</b> ${surp(E.prev.surprise)}</div>` : ""}</div>` : ""}
  </div>`;
}
function renderEarnings() {
  loadEarnDetails();
  const el = $("#earnings");
  const list = earnList().sort((a, b) => a.earningsTs - b.earningsTs);
  if (!list.length) { el.innerHTML = `<div class="empty">Nessuna trimestrale negli ultimi 7 giorni né nei prossimi 7</div>`; earnBar(0, null); return; }
  const past = list.filter(s => earnStatus(s) !== "da pubblicare").reverse(), next = list.filter(s => earnStatus(s) === "da pubblicare");
  earnBar(list.length, next[0], next.length, past.length);
  const byDay = arr => { const g = new Map(); arr.forEach(s => { const d = nyDay(s.earningsTs); g.has(d) || g.set(d, []); g.get(d).push(s); }); return [...g]; };
  const mine = (a, b) => (state.watch.has(b.ticker) ? 1 : 0) - (state.watch.has(a.ticker) ? 1 : 0);
  const block = (title, arr, note) => `<section class="eg"><h3 class="eg-h">${title} <span class="muted small">${arr.length}</span></h3>${note ? `<p class="muted small">${note}</p>` : ""}
    ${arr.length ? byDay(arr).map(([d, xs]) => `<div class="eg-day"><h4>${esc(dayLong(d))}</h4><div class="eg-rows">${xs.sort(mine).map(earnRow).join("")}</div></div>`).join("") : `<p class="small muted">Nessuna.</p>`}</section>`;
  el.innerHTML = block("Da pubblicare · prossimi 7 giorni", next, "Le date senza conferma della società sono segnate come stimate o non verificate.")
    + block("Pubblicate · ultimi 7 giorni", past, "Risultati come li riporta Yahoo Finance; «data passata» = la fonte non ha ancora i numeri.");
}
document.addEventListener("click", e => {
  const b = e.target.closest("[data-earn]");
  if (!b || e.target.closest(".info")) return;
  const t = b.dataset.earn;
  earn.open.has(t) ? earn.open.delete(t) : earn.open.add(t);
  renderEarnings();
});
$("#earnings").addEventListener("click", e => { const b = e.target.closest("[data-open]"); if (b) openDetail(b.dataset.open); });

// short agenda next to the map: the next macro events and earnings, at most 6 lines (the full tables are below)
let macroNext = null;
function renderAgenda() {
  const el = $("#agenda");
  if (!el) return;
  const now = Date.now() / 1000;
  const items = [
    ...(macroNext?.events || []).filter(e => e.ts > now - 3600).map(e => ({ ts: e.ts, html: `<b>${esc(MACRO[e.kind].title.split(" (")[0])}</b>`, kind: "macro" })),
    ...earnList().filter(s => s.earningsTs > now - 3600 && earnStatus(s) === "da pubblicare").map(s => ({ ts: s.earningsTs, html: `<b>${esc(s.ticker)}</b> <span class="muted">trimestrale${state.watch.has(s.ticker) ? " ★" : ""}</span>`, kind: "earn", t: s.ticker })),
  ].sort((a, b) => a.ts - b.ts);
  macroBar();
  if (!items.length) { el.innerHTML = `<div class="empty">Nessun appuntamento nei prossimi 7 giorni</div>`; return; }
  const shown = items.slice(0, 6);
  el.innerHTML = `<ul class="ag-list">${shown.map(x => `<li><span class="ag-d">${esc(fDate(x.ts, { weekday: "short", day: "numeric", month: "short" }))}${x.kind === "macro" ? " · " + esc(new Date(x.ts * 1000).toLocaleTimeString("it-IT", { timeZone: tz, hour: "2-digit", minute: "2-digit" })) + " NY" : ""}</span><span class="ag-t">${x.html}</span></li>`).join("")}</ul>
    <p class="small"><a href="#macroCard" class="link-btn" data-fold-open="macroCard">Tutti gli eventi macro ↓</a> · <a href="#earnCard" class="link-btn" data-fold-open="earnCard">tutte le trimestrali (${items.filter(x => x.kind === "earn").length}) ↓</a></p>`;
}
// the agenda links open the accordion and scroll to it (data-fold-open, not data-goto: data-goto changes page)
document.addEventListener("click", e => {
  const g = e.target.closest("[data-fold-open]"); if (!g) return;
  e.preventDefault();
  const card = document.getElementById(g.dataset.foldOpen); if (!card) return;
  setFold(card, true);
  card.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
});

// ---- Eventi macro USA and Trimestrali as accordions: presentation only, the data and the tables are unchanged.
// Closed when Mercato opens; the button carries aria-expanded, the closed body is inert (no focus inside it).
function setFold(card, open) {
  card.classList.toggle("open", open);
  card.querySelector(".fold-btn").setAttribute("aria-expanded", String(open));
  card.querySelector(".fold-body").inert = !open;
  if (!open) card.classList.remove("shown");
  else setTimeout(() => card.classList.contains("open") && card.classList.add("shown"), 220);   // after the opening: tooltips not clipped
}
const closeFolds = () => $$(".mfold").forEach(c => setFold(c, false));   // "fold" alone is taken by other <details>

document.addEventListener("click", e => { const b = e.target.closest("[data-fold]"); if (!b) return; const c = document.getElementById(b.dataset.fold); setFold(c, !c.classList.contains("open")); });
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
const agWhen = ts => esc(fDate(ts, { weekday: "short", day: "numeric", month: "short" }));
function earnBar(n, first, nNext, nPast) {
  $("#earnCount").textContent = n ? `${plural(n, "società", "società")} · ${nNext} da pubblicare, ${plural(nPast, "pubblicata", "pubblicate")}` : "nessuna nel periodo";
  $("#earnNextLine").innerHTML = first ? `Prossima: <b>${esc(first.ticker)}</b>${state.watch.has(first.ticker) ? " ★" : ""} · ${agWhen(first.earningsTs)}, ${esc(earnWhen(first.earningsTs))}` : "";
}
function macroBar() {
  const P = MACRO_PERIODS.find(p => p[0] === macroPeriod) || MACRO_PERIODS[0];
  $("#macroCount").textContent = macroData ? `${plural(macroData.events.length, "evento", "eventi")} · ${P[1].toLowerCase()}` : "";
  const now = Date.now() / 1000, e = (macroNext?.events || []).find(x => x.ts > now - 3600);
  $("#macroNextLine").innerHTML = e ? `Prossimo: <b>${esc(MACRO[e.kind].title.split(" (")[0])}</b> · ${agWhen(e.ts)}, ${esc(new Date(e.ts * 1000).toLocaleTimeString("it-IT", { timeZone: tz, hour: "2-digit", minute: "2-digit" }))} NY` : "";
}

// ------------------------------------------------------------ news reliability labels (automatic, approximate)
// Ufficiale = the company's own releases / SEC filings; Opinione / ipotesi = commentary sites or speculative headlines;
// everything else = Notizia (news outlets, unknown sources).
const NEWS_OFFICIAL = /business ?wire|pr ?newswire|globe ?newswire|accesswire|\bsec\b|edgar/i;
const NEWS_OPINION_SRC = /motley fool|\bfool\b|zacks|seeking alpha|investorplace|simply wall|insider monkey|24\/7 wall|gurufocus|stocktwits|tipranks/i;
const NEWS_OPINION_TITLE = /\bcould\b|\bmay\b(?!\s+\d)|\bmight\b|should you (buy|sell)|\?|reportedly|sources? (say|said)|\brumou?rs?\b/i;
const NEWS_KIND = { official: "Ufficiale", news: "Notizia", opinion: "Opinione / ipotesi" };
function newsKind(n) {
  const src = n.publisher || "", url = n.url || "";
  if (NEWS_OFFICIAL.test(src) || /sec\.gov/i.test(url)) return "official";
  if (NEWS_OPINION_SRC.test(src) || NEWS_OPINION_TITLE.test(n.title || "")) return "opinion";
  return "news";
}
const newsTag = n => { const k = newsKind(n); return `<span class="nk ${k}">${NEWS_KIND[k]}</span>`; };
const visibleNews = list => state.hideOpinion ? list.filter(n => newsKind(n) !== "opinion") : list;
// the checkbox + the "automatic and approximate" line, shown wherever news are listed
const newsOpts = () => `<div class="news-opts"><label class="check"><input type="checkbox" data-hide-op ${state.hideOpinion ? "checked" : ""}> Nascondi opinioni</label>
  <span class="muted small">Etichette automatiche e approssimative: si basano sulla fonte e sulle parole del titolo.</span></div>`;
document.addEventListener("change", e => {
  if (!e.target.matches("[data-hide-op]")) return;
  state.hideOpinion = e.target.checked; LS.set("hideOpinion", state.hideOpinion);
  $$("[data-hide-op]").forEach(cb => cb.checked = state.hideOpinion);
  if (state.view === "overview") renderWhy();
  if (state.view === "watch") renderMyStocks();
  if (state.detail) renderDetailNews();
});

// ------------------------------------------------------------ US macro events (macro_calendar.py, /api/macro)
// Fixed texts, reviewed by the user. Times are never written here: the card shows New York time and local time.
const SURPRISE_NOTE = `<br><br><span class="muted">Il mercato reagisce soprattutto alla <b>sorpresa</b>, cioè alla differenza tra il dato
  uscito e quello che gli operatori si aspettavano, più che al dato in sé. La dashboard non ha le attese (non esiste una fonte
  gratuita affidabile), quindi mostra il valore precedente: confrontalo con le attese riportate dai siti di notizie.</span>`;
const MACRO = {
  fomc: {
    title: "Riunione della Fed (FOMC) e conferenza stampa",
    info: `<b>Cos'è.</b> La Fed è la banca centrale degli Stati Uniti e decide il tasso d'interesse di riferimento. Si riunisce 8 volte
      l'anno per due giorni: il secondo giorno pubblica la decisione e mezz'ora dopo il presidente tiene una conferenza stampa
      (l'orario è indicato nella card, anche nella tua ora locale). A marzo, giugno, settembre e dicembre pubblica anche le previsioni
      dei suoi membri sui tassi futuri.<br><br><b>Perché conta.</b> I tassi cambiano il costo del denaro per aziende e famiglie e quanto
      valgono oggi gli utili futuri: con tassi più alti, gli utili lontani nel tempo valgono meno.`,
    react: `se la Fed taglia i tassi più del previsto, o fa capire che li taglierà presto → di solito le azioni salgono, soprattutto
      quelle in crescita e tecnologiche; se li lascia più alti del previsto, o dice che resteranno alti a lungo → di solito scendono,
      di più quelle in crescita; se la decisione è quella attesa → spesso conta di più il tono della conferenza stampa, e i movimenti
      possono cambiare direzione mentre il presidente parla.`,
  },
  cpi: {
    title: "Inflazione CPI",
    info: `<b>Cos'è.</b> L'indice dei prezzi al consumo misura quanto sono aumentati in un mese i prezzi di ciò che comprano le famiglie
      americane: cibo, casa, benzina, servizi. Si guardano la variazione sul mese e sull'anno, e soprattutto l'inflazione
      <b>«core»</b>, che esclude cibo ed energia perché oscillano molto. Esce prima dell'apertura della borsa.<br><br><b>Perché conta.</b>
      La Fed decide i tassi guardando l'inflazione: un'inflazione alta rende meno probabili i tagli dei tassi.`,
    react: `se esce più alta delle attese → di solito salgono i rendimenti dei titoli di Stato e le azioni scendono, di più quelle in
      crescita e tecnologiche; se più bassa → di solito le azioni salgono; se in linea → la reazione di solito è piccola.`,
  },
  pce: {
    title: "Inflazione PCE",
    info: `<b>Cos'è.</b> Il PCE (spese per consumi personali) è un'altra misura dell'inflazione, pubblicata dalla BEA insieme a redditi
      e spese delle famiglie. L'obiettivo ufficiale della Fed è un'inflazione del <b>2% all'anno misurata sul PCE complessivo</b>; il
      PCE <b>«core»</b> (senza cibo ed energia) è quello che la Fed guarda di più per capire la tendenza. Esce prima dell'apertura,
      di solito dopo il CPI: per questo sorprende meno, perché gran parte delle informazioni è già nota.`,
    react: `se esce più alto delle attese → di solito rende meno probabili i tagli dei tassi e pesa sulle azioni in crescita; se più
      basso → di solito le aiuta; in genere la reazione è più piccola che per il CPI.`,
  },
  jobs: {
    title: "Rapporto sull'occupazione",
    info: `<b>Cos'è.</b> Il rapporto sull'occupazione (Employment Situation) esce di solito il primo venerdì del mese, prima dell'apertura.
      Dice quanti posti di lavoro sono stati creati nel mese (esclusa l'agricoltura, «non-farm payrolls»), il tasso di disoccupazione
      e quanto crescono i salari.<br><br><b>Perché conta.</b> Mostra la salute dell'economia; salari che crescono molto possono tenere
      alta l'inflazione.`,
    react: `qui la reazione dipende dal momento. Se esce molto più forte delle attese → di solito aiuta le aziende legate all'economia,
      ma se fa temere inflazione e tassi alti può pesare sulle azioni in crescita; se esce molto più debole → può far sperare in tagli
      dei tassi (azioni su) oppure far temere una recessione (azioni giù). Un dato molto lontano dalle attese, in un senso o
      nell'altro, di solito porta movimenti ampi.`,
  },
};
const monthIT = ym => ym ? new Date(ym + "-15T12:00:00").toLocaleDateString("it-IT", { month: "long", year: "numeric" }) : "";
const fS1 = v => isNum(v) ? (v > 0 ? "+" : "") + fNum(v, 1) + "%" : "—";
const macroFigures = (kind, v) => kind === "cpi"
  ? `${fS1(v.mom)} sul mese, ${fS1(v.yoy)} sull'anno · core ${fS1(v.coreMom)} sul mese, ${fS1(v.coreYoy)} sull'anno`
  : `${isNum(v.payrolls) ? (v.payrolls > 0 ? "+" : "") + fNum(v.payrolls, 0) + " mila posti di lavoro" : "—"}, disoccupazione ${isNum(v.unemp) ? fNum(v.unemp, 1) + "%" : "—"}, salari ${fS1(v.wagesMom)} sul mese`;
function macroValues(e, rate) {
  const v = e.values;
  if (e.kind === "fomc") return rate ? `Tasso attuale della Fed: ${esc(rate.replace("-", "–"))}%` : "";
  if (e.kind === "pce") return `<span class="muted">Valori non disponibili: servirebbe una chiave gratuita della BEA.</span>`;
  if (!v) return `<span class="muted">Valori BLS non disponibili al momento.</span>`;
  return `<b>${v.released ? "Uscito" : "Precedente"}</b> (${esc(monthIT(v.period))}): ${macroFigures(e.kind, v)}`;
}
function macroWhen(e) {
  const when = new Date(e.ts * 1000);
  const day = when.toLocaleDateString("it-IT", { timeZone: tz, weekday: "short", day: "numeric", month: "short" });
  const ny = when.toLocaleTimeString("it-IT", { timeZone: tz, hour: "2-digit", minute: "2-digit" });
  return { day, ny, local: fLocal(when) };
}
const macroTitle = e => MACRO[e.kind].title + (e.kind === "fomc" ? (e.sep ? " · con le previsioni economiche" : "") : ` (${monthIT(e.ref)})`);
// ---- phase 8B.1: full table of the chosen period (no inner scrolling). The approved texts above are reused as they are;
// MACRO_ASSETS (new, short) says which markets each event usually moves. Consensus is never invented: "Non disponibile".
const MACRO_ASSETS = {
  fomc: { azioni: "reagiscono alla decisione e al tono della conferenza stampa", tassi: "è la decisione sul tasso di riferimento",
    obbligazioni: "i rendimenti dei titoli di Stato si adeguano alle attese sui tassi (i prezzi si muovono in senso opposto)", dollaro: "tassi più alti del previsto di solito lo rafforzano" },
  cpi: { azioni: "inflazione sopra le attese di solito pesa, di più sulle azioni in crescita", tassi: "inflazione alta rende meno probabili i tagli della Fed",
    obbligazioni: "con inflazione sopra le attese i rendimenti di solito salgono", dollaro: "di solito si rafforza se l'inflazione sorprende al rialzo" },
  pce: { azioni: "come per il CPI, di solito con reazioni più piccole", tassi: "è la misura dell'inflazione su cui la Fed fissa l'obiettivo del 2%",
    obbligazioni: "come per il CPI, di solito con movimenti più piccoli", dollaro: "come per il CPI, di solito con movimenti più piccoli" },
  jobs: { azioni: "dipende dal momento: crescita dell'economia contro timori di tassi alti", tassi: "dati molto forti allontanano i tagli dei tassi",
    obbligazioni: "dati forti di solito spingono su i rendimenti", dollaro: "dati forti di solito lo rafforzano" },
};
const MACRO_PERIODS = [["n7", "Prossimi 7 giorni", 0, 7], ["n30", "Prossimi 30 giorni", 0, 30], ["p7", "Ultimi 7 giorni", 7, 0], ["p30", "Ultimi 30 giorni", 30, 0]];
let macroPeriod = LS.get("macro.period", "n7");
const MACRO_ST = { atteso: ["Atteso", "next"], pubblicato: ["Pubblicato", "pub"], rinviato: ["Rinviato", "wait"] };
const CONSENSUS_INFO = `<b>Consenso</b> = il valore che gli analisti si aspettano. Non esiste una fonte gratuita e affidabile leggibile dalla dashboard, quindi non viene
  mostrato e la differenza dal consenso non si può calcolare: niente numeri inventati.${SURPRISE_NOTE}`;
const cpiShort = v => `${fS1(v.mom)} sul mese · ${fS1(v.yoy)} sull'anno · core ${fS1(v.coreMom)} / ${fS1(v.coreYoy)}`;
const jobsShort = v => `${isNum(v.payrolls) ? (v.payrolls > 0 ? "+" : "") + fNum(v.payrolls, 0) + " mila posti" : "posti n.d."} · disoccupazione ${isNum(v.unemp) ? fNum(v.unemp, 1) + "%" : "n.d."}`;
const rateTxt = r => esc(r.replace("-", "–")) + "%";
// previous and actual value of one row, from the official data already downloaded (BLS, Fed page)
function macroPA(e) {
  const v = e.values, pub = e.status === "pubblicato";
  const fig = x => e.kind === "cpi" ? cpiShort(x) : jobsShort(x);
  if (e.kind === "cpi" || e.kind === "jobs") {
    if (!v) return { prev: NA, act: pub ? NA : `<span class="muted">non ancora pubblicato</span>` };
    if (v.released) return { prev: v.prev ? `${fig(v.prev)} <span class="muted">(${esc(monthIT(v.prev.period))})</span>` : NA, act: `<b>${fig(v)}</b> <span class="muted">(${esc(monthIT(v.period))})</span>` };
    return { prev: `${fig(v)} <span class="muted">(${esc(monthIT(v.period))})</span>`,
      act: pub ? `<span class="na">Non ancora scaricato dalla fonte</span>` : `<span class="muted">non ancora pubblicato</span>` };
  }
  if (e.kind === "fomc") {
    const R = e.rate || {};
    return { prev: R.previous ? `${rateTxt(R.previous)} <span class="muted">(in vigore)</span>` : NA,
      act: R.actual ? `<b>${rateTxt(R.actual)}</b> <span class="muted">(fascia del tasso Fed)</span>` : pub ? NA : `<span class="muted">non ancora deciso</span>` };
  }
  return { prev: `<span class="na">Non disponibile</span> <span class="muted small">(servirebbe una chiave BEA)</span>`, act: pub ? `<span class="na">Non disponibile</span>` : `<span class="muted">non ancora pubblicato</span>` };
}
function macroRow(e, k) {
  const w = macroWhen(e), [stL, stC] = MACRO_ST[e.status] || ["—", ""], pa = macroPA(e), A = MACRO_ASSETS[e.kind];
  const upd = e.updatedAt ? (e.updatedAt.length > 10 ? tsIT(e.updatedAt) : dayIT(e.updatedAt)) : null;
  return `<tr class="mt-main"><td class="l mt-ev" data-label="Evento"><button class="mc-open" data-macro="${k}"><b>${esc(macroTitle(e))}</b></button></td>
      <td class="l" data-label="Quando"><div class="mt-c">${esc(w.day)}<br><span class="small">${w.ny} New York · ${w.local} ora locale</span></div></td>
      <td class="l" data-label="Stato"><div class="mt-c"><span class="er-st ${stC}">${stL}</span>${e.movedTo ? `<br><span class="small">nuova data ${esc(dayIT(e.movedTo))}</span>` : ""}</div></td>
      <td class="l" data-label="Precedente"><div class="mt-c">${pa.prev}</div></td><td class="l" data-label="Consenso"><div class="mt-c">${NA} ${info(CONSENSUS_INFO)}</div></td>
      <td class="l" data-label="Effettivo"><div class="mt-c">${pa.act}</div></td><td class="l" data-label="Diff. dal consenso"><div class="mt-c"><span class="na">Non calcolabile</span></div></td></tr>
    <tr class="mt-sub"><td colspan="7"><div class="mt-why"><span><b>Azioni</b>: ${esc(A.azioni)}</span><span><b>Tassi</b>: ${esc(A.tassi)}</span><span><b>Obbligazioni</b>: ${esc(A.obbligazioni)}</span><span><b>Dollaro</b>: ${esc(A.dollaro)}</span></div>
      <div class="small mt-src">Fonte: <a href="${esc(e.source?.url || "#")}" target="_blank" rel="noopener">${esc(e.source?.name || "n.d.")} ↗</a>
        · ${upd ? `aggiornato dalla dashboard il ${esc(upd)}` : "aggiornamento non disponibile"}${e.kind === "pce" ? " (solo la data)" : ""}
        · <button class="link-btn" data-macro="${k}">Spiegazione completa →</button></div></td></tr>`;
}
let macroAt = 0, macroData = null, macroKey = null;
async function loadMacro(force) {
  const P = MACRO_PERIODS.find(p => p[0] === macroPeriod) || MACRO_PERIODS[0];
  if (!force && macroKey === P[0] && Date.now() - macroAt < 5 * 60_000) return;
  macroAt = Date.now(); macroKey = P[0];
  $("#macroSeg").innerHTML = MACRO_PERIODS.map(([id, l]) => `<button data-mperiod="${id}" class="${id === P[0] ? "on" : ""}" aria-pressed="${id === P[0]}">${l}</button>`).join("");
  let d;
  try {
    d = await getJSON(`/api/macro?past=${P[2]}&days=${P[3]}`);
    if (P[0] === "n7") macroNext = d; else if (!macroNext) getJSON("/api/macro").then(x => { macroNext = x; renderAgenda(); }).catch(() => {});
  } catch { macroAt = 0; $("#macro").innerHTML = `<div class="empty">Eventi non disponibili</div>`; $("#macroCount").textContent = "non disponibili"; return; }
  macroData = d;
  renderAgenda();             // also refreshes the closed bar (macroBar)
  $("#macroMeta").textContent = `${d.events.length} ${d.events.length === 1 ? "evento" : "eventi"} · orari di New York e ora locale${d.blsAt ? ` · valori BLS aggiornati il ${tsIT(d.blsAt)}` : ""}`;
  $("#macroWarn").innerHTML = d.warnings?.length ? `<p class="small data-note">${d.warnings.map(w => "! " + esc(w)).join("<br>")}</p>` : "";
  $("#macro").innerHTML = d.events.length ? `<div class="table-wrap mt-wrap"><table class="scr mt-tbl"><thead><tr><th class="l">Evento</th><th class="l">Quando</th><th class="l">Stato</th>
      <th class="l">Precedente</th><th class="l">Consenso</th><th class="l">Effettivo</th><th class="l">Diff. dal consenso</th></tr></thead>
      <tbody>${d.events.map((e, k) => macroRow(e, k)).join("")}</tbody></table></div>
      <p class="muted small">«Rinviato» si riconosce solo per Fed e PCE, i cui calendari ufficiali vengono riletti ogni giorno; per CPI e occupazione le date sono scritte a mano dal calendario BLS.</p>`
    : `<div class="empty">Nessun evento in questo periodo</div>`;
}
$("#macroSeg").addEventListener("click", e => { const b = e.target.closest("[data-mperiod]"); if (!b) return; macroPeriod = b.dataset.mperiod; LS.set("macro.period", macroPeriod); loadMacro(true); });
$("#macro").addEventListener("click", e => { const b = e.target.closest("[data-macro]"); if (b && macroData) openMacro(macroData.events[+b.dataset.macro]); });
// side panel of a macro event: same drawer as the stocks, texts from MACRO (unchanged), numbers from /api/macro
function openMacro(e) {
  if (!e) return;
  const M = MACRO[e.kind], w = macroWhen(e), v = e.values, R = e.relevance;
  state.detail = null; state.panel = null; state.macro = e;
  const tk = t => quoteFor(t) ? `<button class="pt-tk ${state.watch.has(t) ? "mine" : ""}" data-mopen="${esc(t)}">${esc(t)}</button>` : `<span class="pt-tk off">${esc(t)}</span>`;
  const values = e.kind === "cpi" || e.kind === "jobs"
    ? (v ? `<div class="d-stats one"><div><span>${v.released ? "<b>Uscito</b>" : "Ultimo dato disponibile"} · ${esc(monthIT(v.period))}</span><span>${macroFigures(e.kind, v)}</span></div>
        ${v.prev ? `<div><span>Mese prima · ${esc(monthIT(v.prev.period))}</span><span>${macroFigures(e.kind, v.prev)}</span></div>` : ""}</div>
        ${v.released ? "" : `<p class="muted small">Il dato di ${esc(monthIT(e.ref))} non è ancora uscito: compare qui dopo la pubblicazione.</p>`}`
      : `<p class="muted">Valori BLS non disponibili al momento.</p>`)
    : `<p>${macroValues(e, macroData?.rate) || `<span class="muted">Tasso della Fed non disponibile al momento.</span>`}</p>`;
  drawer.classList.remove("full");
  drawer.innerHTML = `<div class="d-top"><div class="d-head"><div><div class="tt">${esc(M.title)}</div>
        <div class="nm">${e.kind === "fomc" ? (e.sep ? "con le previsioni economiche" : "evento macro USA") : `dato di ${esc(monthIT(e.ref))}`}</div></div>
      <div class="actions"><button class="icon-btn close-btn" id="dClose" aria-label="Chiudi">×</button></div></div></div>
    <div class="d-rest macro-d">
      <div class="d-sec"><h3>Quando</h3><p><b>${esc(w.day)}</b> · ${w.ny} ora di New York · <b>${w.local} ora italiana</b>${e.kind === "fomc" ? "<br>La conferenza stampa inizia mezz'ora dopo la decisione." : ""}</p></div>
      <div class="d-sec"><h3>Valori</h3>${values}
        <p class="small"><b>Valore atteso:</b> lo trovi nel calendario economico di Fineco (Mercati e trading). La dashboard non lo mostra perché non esiste una fonte gratuita affidabile per le attese.</p></div>
      <div class="d-sec"><h3>Spiegazione</h3><p>${M.info}${SURPRISE_NOTE}</p></div>
      <div class="d-sec"><h3>Come reagisce di solito il mercato</h3><p>${M.react.charAt(0).toUpperCase() + M.react.slice(1)}</p></div>
      <div class="d-sec"><h3>Settori e temi coinvolti</h3><p><b>Settori:</b> ${esc(e.impact.sectors.join(", "))}<br><b>Temi:</b> ${esc(e.impact.themes.join(", "))}</p>
        <p class="muted small">Sono i settori e i temi di solito più sensibili a questo evento.</p></div>
      ${R ? `<div class="d-sec"><h3>Il tuo portafoglio</h3>${isNum(R.pfShare)
          ? `<p>Riguarda circa il <b>${Math.round(R.pfShare)}%</b> del valore del tuo portafoglio (${R.pfItems.length} ${R.pfItems.length === 1 ? "posizione" : "posizioni"}).</p><div class="pt-stocks">${R.pfItems.map(tk).join("")}</div>`
          : `<p class="muted">Portafoglio non caricato.</p>`}</div>
        <div class="d-sec"><h3>I tuoi preferiti</h3>${R.watchTotal
          ? `<p>${R.watchItems.length} dei tuoi ${R.watchTotal} preferiti sono nei settori o nei temi coinvolti.</p><div class="pt-stocks">${R.watchItems.map(tk).join("")}</div>`
          : `<p class="muted">Nessun preferito.</p>`}</div>` : ""}
      <p class="disclaimer">Le reazioni descritte sono quelle più frequenti, non una previsione. Non è una consulenza finanziaria.</p></div>`;
  drawer.classList.add("open"); drawer.setAttribute("aria-hidden", "false"); scrim.hidden = false;
  $("#dClose").onclick = closeDetail;
}

// ------------------------------------------------------------ why they move (rule-based, from /api/movers-why)
// Phase 8B.1: every card says how solid the explanation is (server: move_evidence). CAUSA DOCUMENTATA only when an
// article written to explain the move states the reason; a coincidence in time is EVENTO CORRELATO, never a cause.
let whyLoadedAt = 0, whyData = null;
const WHY_EV_CLS = { documented: "doc", related: "rel", unverified: "unv" };
const WHY_LEGEND = `<b>CAUSA DOCUMENTATA</b>: un articolo scritto per spiegare il movimento indica il motivo (è la spiegazione della fonte, non una verifica della dashboard).<br>
  <b>EVENTO CORRELATO</b>: nella stessa finestra di tempo c'è un evento o una notizia (trimestrale, comunicato, movimento del settore, dato macro), ma nessuna fonte dice che il movimento è dovuto a quello.<br>
  <b>CAUSA NON VERIFICATA</b>: le fonti lette non spiegano il movimento.<br><br>Regole fisse sulle parole dei titoli, nessuna intelligenza artificiale: verifica sempre aprendo la fonte.`;
function renderWhy() {
  if (!whyData) return;
  const D = whyData, W = D.window || [];
  const hm = x => x ? new Date(x).toLocaleString("it-IT", { timeZone: tz, weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "";
  $("#whyMeta").innerHTML = `seduta del ${esc(dayIT(D.session))} · notizie: ${esc(D.newsSource || "Yahoo Finance")}${W.length ? ` · cercate da ${esc(hm(W[0]))} a ${esc(hm(W[1]))} (ora di New York)` : ""}`;
  $("#whyLegend").innerHTML = `<p class="small muted why-leg">Ogni scheda dice quanto è solida la spiegazione: <span class="ev-tag doc">CAUSA DOCUMENTATA</span> <span class="ev-tag rel">EVENTO CORRELATO</span> <span class="ev-tag unv">CAUSA NON VERIFICATA</span> ${info(WHY_LEGEND)}
    ${isNum(D.newsFound) && D.newsFound === 0 ? `<br><b class="warn">Nessuna notizia ricevuta dalla fonte in questo momento</b>: le schede mostrano solo eventi e settore.` : ""}</p>`;
  $("#whyNewsOpts").innerHTML = newsOpts();
  $("#whyTop").innerHTML = D.top.map(x => whyItem(x, D)).join("") || `<div class="empty">Nessun dato</div>`;
  $("#whyFlop").innerHTML = D.flop.map(x => whyItem(x, D)).join("") || `<div class="empty">Nessun dato</div>`;
}
async function loadWhy() {
  if (Date.now() - whyLoadedAt < 5 * 60_000) return;
  whyLoadedAt = Date.now();
  try {
    whyData = await getJSON("/api/movers-why");
    renderWhy();
  } catch {
    whyLoadedAt = 0;   // retry on the next refresh
    $("#whyTop").innerHTML = $("#whyFlop").innerHTML = `<div class="empty">Notizie non disponibili</div>`;
  }
}
function whyItem(x, D) {
  const E = x.evidence || { key: "unverified", label: "CAUSA NON VERIFICATA", meaning: "", verify: "", facts: [] };
  const n = x.news;
  const topics = x.reasons.length ? `<div class="mv-tags">${x.reasons.map(r => `<span>${esc(r)}</span>`).join("")}${isNum(x.sectorChg) ? `<span class="sec">${esc(x.sector)} ${fPct(x.sectorChg)}</span>` : ""}</div>`
    : isNum(x.sectorChg) ? `<div class="mv-tags"><span class="sec">${esc(x.sector)} ${fPct(x.sectorChg)}</span></div>` : "";
  const what = E.key === "documented" && n?.clause ? `<div class="mv-sum">Secondo la fonte: «${esc(n.clause)}»</div>`
    : E.facts.length ? `<div class="mv-sum">Nella stessa finestra: ${esc(E.facts.join("; "))}.</div>` : `<div class="mv-sum">Nessuna notizia, evento della società o movimento del settore trovato.</div>`;
  const absT = t => { const ms = typeof t === "number" ? t * 1000 : Date.parse(t); return isFinite(ms) ? new Date(ms).toLocaleString("it-IT", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : ""; };
  // with opinions hidden the label stays, but the article it came from is not shown
  const src = !n ? "" : state.hideOpinion && newsKind(n) === "opinion"
    ? `<div class="nm">Fonte: articolo d'opinione (nascosto)</div>`
    : `<a class="mv-news" href="${esc(n.url)}" target="_blank" rel="noopener">${esc(n.title)} ↗</a>
      <div class="nm">${newsTag(n)} ${esc(n.publisher || "fonte non indicata")} · ${esc(absT(n.time))} ora locale (${esc(ago(n.time))})</div>`;
  return `<div class="mv-it"><div class="mv-h"><b data-open="${esc(x.ticker)}" role="button" tabindex="0" title="Apri la scheda">${esc(x.ticker)}</b><span class="n">${esc(x.name || "")}</span>${pill(x.chgPct)}</div>
    <div class="mv-when small muted">${isNum(x.chgPct) ? fPct(x.chgPct) : "—"} nella seduta del ${esc(dayIT(D.session))}, rispetto alla chiusura precedente</div>
    <div><span class="ev-tag ${WHY_EV_CLS[E.key]}">${esc(E.label)}</span> ${info(esc(E.meaning) + (E.verify ? `<br><br><b>Come verificarlo.</b> ${esc(E.verify)}` : ""))}</div>
    ${what}${topics}${src}</div>`;
}
$(".mv-cols").addEventListener("click", e => { const b = e.target.closest("[data-open]"); if (b) openDetail(b.dataset.open); });
$(".mv-cols").addEventListener("keydown", e => { const b = e.target.closest("[data-open]"); if (b && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); openDetail(b.dataset.open); } });

function ago(t) {
  const ms = typeof t === "number" ? t * 1000 : Date.parse(t);
  if (!isFinite(ms)) return "";
  const m = Math.round((Date.now() - ms) / 60000);
  if (m < 60) return m + " min fa";
  if (m < 1440) return Math.round(m / 60) + " h fa";
  return Math.round(m / 1440) + " g fa";
}

// ------------------------------------------------------------ my stocks (watchlist.json in the project folder)
let watchLoadedAt = 0;
async function loadWatch(imported = false) {
  try {
    const d = await getJSON("/api/watchlist");
    if (!d.exists && !imported) {   // first run: import the favourites the browser used to keep
      state.watch = new Set(LS.get("watch", ["NVDA", "AAPL", "MSFT", "AMZN", "GOOGL", "META", "TSLA"]));
      await saveWatch();
      return loadWatch(true);
    }
    if (d.exists) state.watch = new Set(d.tickers);
    state.watchNews = d.news || {};
    watchLoadedAt = Date.now();
  } catch (e) { console.warn("watchlist unavailable", e); }
}
async function saveWatch() {
  try {
    await fetch("/api/watchlist", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ tickers: [...state.watch] }) });
  } catch (e) { console.warn("watchlist not saved", e); }
}
const myNews = t => visibleNews([].concat(state.watchNews[t] || []))[0];   // [].concat: older servers sent one item
// 1 = price > 20 > 40 > 60, -1 = the opposite, 0 = mixed (same rule as maOrder)
function maStack(s) {
  const { price: p, sma20: a, sma40: b, sma60: c } = s;
  if (![p, a, b, c].every(isNum)) return null;
  return p > a && a > b && b > c ? 1 : p < a && a < b && b < c ? -1 : 0;
}
const MY_COLS = ["star", "ticker", "name", "price", "chgPct", "perf1M", "perfYTD", "vsSma20", "vsSma40", "vsSma60", "vsSma200", "maOrder", "valLabel", "upside", "signal", "trend", "earnings", "news"];
function renderMyStocks() {
  if (Date.now() - watchLoadedAt > 5 * 60_000) loadWatch().then(() => state.view === "watch" && renderMyStocks());   // fresh headlines
  const col = C[state.mySort.key] || C.chgPct;
  const rows = [...state.watch].map(t => state.bySym.get(t)).filter(Boolean).sort((a, b) => {
    const va = col.sort(a), vb = col.sort(b);
    if (va == null && vb == null) return 0;
    if (va == null) return 1;
    if (vb == null) return -1;
    return (typeof va === "string" ? va.localeCompare(vb) : va - vb) * state.mySort.dir;
  });
  $("#myCount").textContent = `${rows.length} titoli`;
  $("#myNewsOpts").innerHTML = newsOpts();
  const pr = COL_PRIO.my;
  $("#myTbl").innerHTML = `<thead><tr>${MY_COLS.map(k => `<th class="${C[k].cls?.split(" ")[0] || ""} ${pr[k] || ""} ${state.mySort.key === k ? "sorted" + (state.mySort.dir > 0 ? " asc" : "") : ""}" data-k="${k}">${colHead(k)}</th>`).join("")}</tr></thead>
    <tbody>${rows.map(s => `<tr data-t="${esc(s.ticker)}">${MY_COLS.map(k => `<td class="${C[k].cls || ""} ${pr[k] || ""}">${C[k].html(s)}</td>`).join("")}</tr>`).join("")
      || `<tr><td colspan="${MY_COLS.length}" class="empty">Nessun titolo: aggiungili con ★ dallo Screener o dalla scheda del titolo</td></tr>`}</tbody>`;
}
$("#myTbl").addEventListener("click", e => {
  if (e.target.closest("a")) return;   // news link opens the article
  const th = e.target.closest("th[data-k]");
  if (th) {
    const k = th.dataset.k; if (C[k].nosort) return;
    state.mySort = state.mySort.key === k ? { key: k, dir: -state.mySort.dir } : { key: k, dir: ["ticker", "name", "earnings"].includes(k) ? 1 : -1 };
    return renderMyStocks();
  }
  const tr = e.target.closest("tr[data-t]");
  if (tr && !e.target.closest(".star")) openDetail(tr.dataset.t);
});

// ------------------------------------------------------------ portfolio (newest Fineco export in portafoglio/)
const pf = { data: null, sort: { key: "value", dir: -1 }, retry: null, dim: LS.get("pfDim", "sector"), cols: LS.get("pfCols", "values") };
const fEur = (v, d = 2) => isNum(v) ? fNum(v, d) + " €" : "—";
const fEurS = (v, d = 2) => isNum(v) ? (v > 0 ? "+" : "") + fNum(v, d) + " €" : "—";
// detail header for stocks outside the Nasdaq-100 that I own
function pfQuote(t) {
  const x = pf.data?.positions?.find(p => p.ticker === t);
  if (!x) return null;
  const chg = isNum(x.prevClose) ? x.price - x.prevClose : null;
  return { name: x.name, price: x.price, prevClose: x.prevClose, chg, chgPct: isNum(chg) ? chg / x.prevClose * 100 : null };
}
async function loadPortfolio() {
  try { pf.data = await getJSON("/api/portfolio"); } catch { pf.data = { file: null, error: "Server non raggiungibile" }; }
  renderPortfolio();
  if (pf.data.file && !pf.data.error && !pf.data.resolving) {     // recomputed when the file changes, otherwise every 5 minutes
    if (risk.data?.status !== "ok" || risk.file !== pf.data.file || Date.now() - risk.at > 5 * 60_000) { risk.file = pf.data.file; risk.at = Date.now(); loadRisk(); }
  } else { risk.data = null; renderRisk(); }
  if (pf.data.file && !pf.data.error) loadPerf(); else { perf.data = null; renderPerf(); }
  clearTimeout(pf.retry);
  if (pf.data.resolving && PF_SUBS.includes(state.view)) pf.retry = setTimeout(loadPortfolio, 3000);   // tickers still being matched
}
const FX_INFO = `Per i titoli in dollari il risultato in euro dipende da due cose: il <b>prezzo del titolo</b> e il <b>cambio EUR/USD</b>.
  "Di cui effetto cambio" è la parte dovuta solo al cambio: quanto varrebbe la posizione al prezzo di oggi ma al cambio dei giorni
  di acquisto, confrontato con il valore di oggi. Negativo = il dollaro si è indebolito rispetto all'euro da quando hai comprato.`;
const LEV_INFO = (n = 3) => `<b>Prodotto a leva ${n}x giornaliera.</b> Ogni giorno si muove circa ${n} volte il suo indice
  (indice +1% → circa +${n}%, indice −1% → circa −${n}%). La leva si azzera ogni giorno, quindi su più giorni il risultato
  <b>non</b> è ${n} volte quello dell'indice.<br><br><b>Con il mercato altalenante perde valore</b> anche se l'indice torna al punto
  di partenza. Esempio: indice +10% e poi −9,1% = pari; prodotto 3x +30% e poi −27,3% = <b>−5,5%</b>.<br><br>
  <b>In un crollo forte</b> può perdere gran parte del valore in pochi giorni: un calo dell'indice di circa il 33% in un solo giorno
  lo azzererebbe. Costa anche più di un ETF normale. È pensato per periodi brevi e va controllato spesso.`;
const pfAct = x => x.action ? `<button class="act-btn" data-pos="${esc(x.isin)}" title="${esc(x.action.reasons.join(" · ") || "Nessuna regola scattata")}">${actBadge(x.action)}</button>` : "—";
// phase 8B.1: no automatic leverage banner; the share of value and of effective exposure is in the ⓘ of the position itself
const levShare = x => { const T = pf.data?.totals || {};
  return isNum(T.value) && T.value && isNum(T.exposure) && T.exposure ? `<br><br><b>Questa posizione:</b> ${fNum(x.value / T.value * 100, 1)}% del valore del portafoglio,
    ma ${fNum(x.exposure / T.exposure * 100, 1)}% dell'esposizione effettiva (valore × leva).` : ""; };
const pfName = x => `<b>${esc(x.name)}</b>${x.leverage > 1 ? ` <span class="lev-badge">leva ${x.leverage}x</span> ${info(LEV_INFO(x.leverage) + levShare(x))}` : ""}
  <div class="muted small">${esc(x.ticker || x.symbol)} · ${esc(x.kind)} · ${esc(x.currency)}</div>${x.action ? `<div class="pf-act-in">${pfAct(x)}</div>` : ""}`;
// Nasdaq-100 data the dashboard already has (same renderers as the Screener); "—" for the other positions
const ndxCol = (k, l) => ({ k, l, i: COL_INFO[k], sort: x => { const s = state.bySym.get(x.ticker); return s ? C[k].sort(s) : null; },
  html: x => { const s = state.bySym.get(x.ticker); return s ? C[k].html(s) : `<span class="muted">—</span>`; } });
const PF_DASH = () => [
  { k: "name", l: "Titolo", cls: "l", sort: x => x.name, html: pfName },
  { k: "value", l: "Valore", sort: x => x.value, html: x => fEur(x.value) },
  { k: "weight", l: "Peso", p: 3, sort: x => x.weight, html: x => isNum(x.weight) ? fNum(x.weight, 1) + "%" : "—" },
  { k: "action", l: "Azione", cls: "l", i: "Indicazione proposta dalle regole, solo dall'analisi del titolo (clicca per pagella, stop e motivi). Regole di disciplina, non verificate da backtest.", sort: x => ({ "Valuta la vendita": 3, "Attenzione": 2, "Accumula": 1 }[x.action?.action] || 0),
    p: 4, html: pfAct },
  { ...ndxCol("trend", "Trend"), cls: "", p: 2 }, { ...ndxCol("signal", "Segnale"), cls: "l", p: 3 }, { ...ndxCol("valLabel", "Valutazione"), cls: "l", p: 3 },
  { ...ndxCol("upside", "Potenziale analisti"), cls: "", p: 2 }, { ...ndxCol("earnings", "Prossima trimestrale"), cls: "l", p: 2 },
];
const PF_COLS = [
  { k: "name", l: "Titolo", cls: "l", sort: x => x.name, html: pfName },
  { k: "qty", l: "Quantità", p: 3, sort: x => x.qty, html: x => fNum(x.qty, x.qty % 1 ? 2 : 0) },
  { k: "costPrice", l: "Prezzo di carico", p: 2, sort: x => x.costPrice, html: x => fPrice(x.costPrice) },
  { k: "price", l: "Prezzo", p: 3, sort: x => x.price, html: x => `${fPrice(x.price)}${x.live ? "" : ` <span class="muted small" title="Ticker non trovato: prezzo del file">(file)</span>`}` },
  { k: "value", l: "Valore", sort: x => x.value, html: x => fEur(x.value) },
  { k: "pnl", l: "Guadagno / perdita", sort: x => x.pnl, html: x => `<span class="${sign(x.pnl)}">${fEurS(x.pnl)}</span><span class="sub2 s3 ${sign(x.pnlPct)}">${fPct(x.pnlPct, 1)}</span>` },
  { k: "pnlPct", l: "%", p: 3, sort: x => x.pnlPct, html: x => `<span class="${sign(x.pnlPct)}">${fPct(x.pnlPct, 1)}</span>` },
  { k: "fxEffect", l: "Di cui cambio", i: FX_INFO, p: 2, sort: x => x.fxEffect, html: x => x.currency === "EUR" ? `<span class="muted">—</span>` : `<span class="${sign(x.fxEffect)}">${fEurS(x.fxEffect)}</span>` },
  { k: "today", l: "Oggi", i: "Variazione di oggi in euro, dovuta al prezzo (rispetto alla chiusura precedente della sua borsa).", p: 3, sort: x => x.today, html: x => `<span class="${sign(x.today)}">${fEurS(x.today)}</span>` },
  { k: "weight", l: "Peso", i: "Quota del valore totale del portafoglio.", p: 3, sort: x => x.weight, html: x => isNum(x.weight) ? fNum(x.weight, 1) + "%" : "—" },
  { k: "action", l: "Azione", cls: "l", i: "Indicazione proposta dalle regole, solo dall'analisi del titolo (clicca per pagella, stop e motivi). Regole di disciplina, non verificate da backtest.", sort: x => ({ "Valuta la vendita": 3, "Attenzione": 2, "Accumula": 1 }[x.action?.action] || 0),
    p: 4, html: pfAct },
];
function renderPortfolio() {
  const D = pf.data;
  const empty = !D || !D.file || D.error;
  $("#pfEmpty").hidden = !empty; $("#pfBody").hidden = empty;
  renderTaxBox();
  if (empty) {
    $("#pfEmpty").innerHTML = D?.error ? esc(D.error)
      : `Nessun file del portafoglio. Esporta le posizioni da Fineco in Excel (.xls) e caricale con il pulsante <b>Carica file Fineco</b> qui sopra, oppure trascina il file su questa pagina.`;
    return;
  }
  const T = D.totals;
  const kpi = (l, v, sub) => `<div class="kpi"><div class="l">${l}</div><div class="v">${v}</div><div class="s">${sub}</div></div>`;
  $("#pfKpis").innerHTML = [
    kpi("Valore attuale", fEur(T.value, 0), `costo ${fEur(T.cost, 0)}${isNum(T.exposure) && Math.abs(T.exposure - T.value) > 1 ? ` · esposizione effettiva ${fEur(T.exposure, 0)}` : ""}`),
    kpi("Guadagno / perdita", `<span class="${sign(T.pnl)}">${fEurS(T.pnl, 0)}</span>`, `<span class="${sign(T.pnlPct)}">${fPct(T.pnlPct, 1)}</span> sul costo`),
    kpi(`Di cui effetto cambio ${info(FX_INFO)}`, `<span class="${sign(T.fxEffect)}">${fEurS(T.fxEffect, 0)}</span>`, isNum(D.fx) ? `EUR/USD oggi ${fNum(D.fx, 4)}` : "cambio non disponibile"),
    kpi("Oggi", `<span class="${sign(T.today)}">${fEurS(T.today, 0)}</span>`, "variazione dei prezzi rispetto alla chiusura precedente"),
  ].join("");
  const when = D.quotesAt ? new Date(D.quotesAt * 1000).toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" }) : null;
  $("#pfFileInfo").textContent = `file attuale: ${D.file}, del ${new Date(D.fileTime * 1000).toLocaleString("it-IT", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" })}`;
  $("#pfMeta").textContent = D.resolving ? "cerco i ticker su Yahoo…" : when ? `prezzi aggiornati alle ${when} ora locale` : "";
  // phase 8B.1: instruments without a certain category are one small line with the list on request (no yellow box);
  // the other warnings about the file (ticker not found…) stay as before
  const UC = D.unclassified || [], other = D.warnings.filter(w => !/: non classificato \(aggiungilo/.test(w));
  $("#pfWarn").hidden = !UC.length && !other.length;
  $("#pfWarn").innerHTML = (UC.length ? `<details class="pf-uc"><summary><span class="small">Alcuni strumenti non sono stati associati con certezza a una categoria.
      Le relative esposizioni potrebbero essere parziali.</span> <span class="sn-more">Quali e cosa manca (${UC.length})</span></summary>
      <ul class="pf-uc-list">${UC.map(u => `<li><b>${esc(u.name)}</b> <span class="muted small">${esc(u.kind)} · ISIN ${esc(u.isin)}</span><br>
        <span class="small">Manca: ${u.missing.map(esc).join("; ")}.${u.catalogIndex ? ` Il catalogo ETF pubblico conosce questo ISIN (indice: ${esc(u.catalogIndex)}): può aiutarti a compilarla.` : ""}</span>
        ${pfIsFund(u.kind) ? pfClsForm(u.isin, D) : ""}</li>`).join("")}</ul>
      <p class="muted small">Perché succede: per ETF ed ETC la dashboard non ha una fonte affidabile di settore, tema e paese, quindi li legge solo da
        <code>portafoglio/classificazione.json</code>, che compili tu con l'ISIN. Finché manca, lo strumento finisce in «Non classificato» nelle concentrazioni
        (è normale per ogni ETF nuovo). La dashboard non inventa la classificazione: la scrivi tu con «Compila la classificazione» (oppure nel file) e la puoi cambiare quando vuoi.</p></details>` : "")
    + (other.length ? `<details class="fold pf-warn-box"><summary><span class="pf-warn-n">! ${other.length} ${other.length === 1 ? "avviso" : "avvisi"} sui dati del file</span></summary>`
    + other.map(w => `<div>⚠ ${esc(w)}</div>`).join("")
    + `<div class="muted small">Puoi indicare il ticker giusto qui sotto (salvato in <code>portafoglio/ticker.json</code>), per esempio VWCE.DE o QQQ3.MI.</div>`
    + D.positions.filter(p => !p.ticker).map(p => `<form class="pf-tk-f" data-isin="${esc(p.isin)}"><label class="small">Ticker Yahoo per <b>${esc(p.name)}</b>
        <input name="ticker" maxlength="20" autocomplete="off" spellcheck="false" placeholder="es. VWCE.DE"></label>
        <button class="btn" type="submit">Salva</button> <span class="pf-f-msg small" role="status"></span></form>`).join("") + `</details>` : "");
  const COLS = pf.cols === "dash" ? PF_DASH() : PF_COLS;
  $$("#pfColSeg button").forEach(b => b.classList.toggle("on", b.dataset.cols === pf.cols));
  const col = COLS.find(c => c.k === pf.sort.key) || COLS.find(c => c.k === "value");
  const rows = [...D.positions].sort((a, b) => {
    const va = col.sort(a), vb = col.sort(b);
    if (va == null) return 1; if (vb == null) return -1;
    return (typeof va === "string" ? va.localeCompare(vb) : va - vb) * pf.sort.dir;
  });
  $("#pfCount").textContent = `${rows.length} posizioni`;
  $("#pfTbl").innerHTML = `<thead><tr>${COLS.map(c => `<th class="${c.cls || ""}${c.p ? " p" + c.p : ""} ${pf.sort.key === c.k ? "sorted" + (pf.sort.dir > 0 ? " asc" : "") : ""}" data-k="${c.k}">${esc(c.l)}${c.i ? " " + info(c.i) : ""}</th>`).join("")}</tr></thead>
    <tbody>${rows.map(x => `<tr data-t="${esc(x.ticker || "")}" class="${x.leverage > 1 ? "lev" : ""}">${COLS.map(c => `<td class="${c.cls || ""}${c.p ? " p" + c.p : ""}">${c.html(x)}</td>`).join("")}</tr>`).join("")}</tbody>`;
  renderConcentration();
}
const EXPO_INFO = `<b>Valore investito</b>: quanto vale oggi quello che possiedi.<br><b>Esposizione effettiva</b>: quanto ti muovi davvero
  con il mercato. Per i prodotti a leva 3x è 3 volte il valore (1.000 € investiti si muovono ogni giorno come 3.000 €), per tutto il resto
  coincide con il valore. Le percentuali dell'esposizione sono sul totale dell'esposizione.`;
const DIM_LAB = { sector: "Settore", theme: "Tema", country: "Paese / area" };
function renderConcentration() {
  const D = pf.data, rows = D.concentration?.[pf.dim] || [];
  $$("#pfDimSeg button").forEach(b => b.classList.toggle("on", b.dataset.dim === pf.dim));
  const T = D.totals, maxPct = Math.max(1, ...rows.map(r => Math.max(r.pct || 0, r.expPct || 0)));
  $("#pfConcMeta").innerHTML = `valore investito ${fEur(T.value, 0)} · esposizione effettiva ${fEur(T.exposure, 0)} ${info(EXPO_INFO)}`;
  $("#pfConc").innerHTML = `<thead><tr><th class="l">${DIM_LAB[pf.dim]}</th><th>Valore investito</th><th class="p4">%</th><th>Esposizione effettiva</th><th class="p4">%</th><th class="l p4">confronto</th></tr></thead>
    <tbody>${rows.map(r => `<tr><td class="l wrap"><b>${esc(r.name)}</b></td><td>${fEur(r.value, 0)}<span class="sub2 s4">${fNum(r.pct, 1)}%</span></td><td class="p4">${fNum(r.pct, 1)}%</td>
      <td>${fEur(r.exposure, 0)}<span class="sub2 s4"><b>${fNum(r.expPct, 1)}%</b></span></td><td class="p4"><b>${fNum(r.expPct, 1)}%</b></td>
      <td class="l p4"><span class="cbar"><i class="v" style="width:${(r.pct / maxPct * 100).toFixed(1)}%"></i><i class="e" style="width:${(r.expPct / maxPct * 100).toFixed(1)}%"></i></span></td></tr>`).join("")}</tbody>`;
  const notes = {
    sector: "Azioni del Nasdaq-100: settore usato dalla dashboard. Altre azioni: settore di Yahoo. ETF ed ETC: portafoglio/classificazione.json (il Nasdaq-100 3x è diviso come i settori dell'indice).",
    theme: "Azioni: temi di themes.json (un titolo in due temi conta metà in ciascuno) oppure la sezione _azioni di portafoglio/classificazione.json. ETF ed ETC: stesso file.",
    country: "Azioni: paese della società secondo Yahoo (corretto in portafoglio/classificazione.json se serve). ETF ed ETC: area a cui sono esposti, non la sede del fondo; «Mondo» non è diviso per paese.",
  };
  $("#pfConcNote").innerHTML = `${notes[pf.dim]} Barra chiara = valore investito, barra scura = esposizione effettiva.`;
}
// ---- proposed level of each position (actions.py, phase 26: only the analysis of the stock)
const ACT_CLS = { "Valuta la vendita": "red", "Attenzione": "rev", "Accumula": "acc", "Mantieni": "hold" };
const actBadge = a => `<span class="act ${ACT_CLS[a.action] || "hold"}">${esc(a.label || a.action)}</span>`;   // label: "Attenzione · target raggiunto"
const TAX_NOTE = "Stima indicativa, non è una consulenza fiscale: non conta commissioni, minusvalenze che hai già, né casi particolari.";
const actTax = a => a.tax ? `<span class="act-tax">Effetto fiscale stimato: ${esc(a.tax.text)}. ${info(`<b>Effetto fiscale stimato.</b> Guadagno o perdita in euro sulla parte da vendere, in proporzione al «Valore di carico» di Fineco, con l'imposta indicativa del 26%.<br><br>
  <b>Azioni ed ETC/ETN</b>: guadagni e perdite sono «redditi diversi» e si compensano tra loro (le perdite valgono per i 4 anni successivi).<br>
  <b>ETF UCITS</b>: i guadagni sono «redditi di capitale», tassati al 26% senza poterli compensare con le perdite; le perdite sono «redditi diversi».<br><br>${TAX_NOTE}`)}</span>` : "";
const ACT_INFO = `Per ogni posizione la dashboard propone uno di quattro livelli con regole esplicite, usando <b>solo l'analisi del titolo</b>,
  come quando decidi se comprarlo: pagella, verdetto di mercato, stop automatico e novità degli ultimi giorni. Sotto vedi quali regole sono scattate e con quali numeri.<br><br>
  <b>✕ Valuta la vendita</b> (ne basta una): stop automatico rotto; almeno 2 controlli della pagella caduti e almeno la metà di quelli valutabili
  (servono almeno 3 controlli valutabili, altrimenti «dati insufficienti»); prodotto a leva tenuto oltre 30 giorni; verdetto di mercato «Evita».<br>
  <b>! Attenzione</b> (le novità): controllo appena caduto, prezzo appena sceso sotto la media a 200 giorni, stime tagliate, più downgrade che upgrade,
  trimestrale entro 5 giorni, prezzo a meno di 1 ATR dallo stop automatico.<br>
  <b>✓ Accumula</b> (devono valere tutte): pagella buona (azioni: almeno 4 ✓ su 6 e nessun ✕; ETF ed ETC: tutti ✓), trend di fondo intatto (prezzo sopra la media 200 e media 50 sopra la 200),
  verdetto «Entra ora» o «Entra su ritracciamento», nessuna trimestrale entro 5 giorni, nessun avviso, niente leva.<br>
  <b>– Mantieni</b>: tutto il resto.<br><br>
  Un controllo con <b>«?»</b> (dato mancante) <b>non conta mai come caduto</b> e non conta mai come vero: per «Valuta la vendita» la metà si calcola solo sui controlli valutabili.<br><br>
  Sono <b>regole di disciplina, non verificate da un backtest</b>: servono a non dimenticare le cose da controllare, non dicono cosa farà il prezzo.
  Ogni sera l'indicazione viene salvata nel diario delle posizioni per misurarla nel tempo.`;
// ---- "Pagella del titolo" (pillars.py): the same automatic checks for every position, nothing chosen by me
const PIL_INFO = `<b>Pagella del titolo.</b> Gli stessi controlli automatici per tutte le azioni (ricavi, stime, consenso, margine, valutazione, trend) e
  per tutti gli ETF ed ETC (trend e diversificazione), calcolati ogni giorno con i dati pubblici: ✓ vale, ✕ caduto, ? dato mancante.<br><br>
  Un <b>«?»</b> non conta mai come caduto e non conta mai come vero. Quando un controllo passa da ✓ a ✕ (o al contrario), il registro lo annota con la data.
  Non è verificata da backtest: dice com'è messo il titolo, non cosa farà il prezzo.`;
const STOP_INFO = `<b>Stop automatico.</b> Ogni giorno la dashboard calcola uno stop dal prezzo attuale con la stessa regola del piano di acquisto della sezione Decisione:
  il livello del grafico più vicino a una distanza ragionevole (la media a 50 giorni o l'ultimo minimo, meno mezzo ATR), oppure, se nessuno va bene, un multiplo dell'ATR
  (l'ATR è il movimento medio di un giorno).<br><br>Lo stop <b>si alza ma non scende mai</b>: si tiene il più alto mai raggiunto, come uno stop che segue il prezzo.
  Parte dal primo giorno in cui la dashboard vede la posizione, quindi sta sotto il prezzo di quel giorno, <b>non sotto il tuo prezzo di acquisto</b>; se vendi e ricompri riparte da zero.<br><br>
  Se il prezzo scende sotto lo stop scatta «Valuta la vendita» (regola S1); a meno di 1 ATR sopra lo stop scatta «Attenzione» (T6). Non è un ordine inserito su Fineco.`;
const PIL_ICON = { ok: "✓", ko: "✕", na: "?" };
const pilLog = e => `<li><span class="muted">${dayIT(e.date)}</span> <span class="pil-st ${e.to}">${PIL_ICON[e.to]}</span> <b>${esc(e.name)}</b> ${e.to === "ok" ? "è tornato vero" : "è caduto"}
    <span class="muted small">${esc(e.detail || "")}</span></li>`;
function pagellaHTML(p) {
  const P = p.pillars;
  if (!P) return "";
  const S = P.score;
  return `<div class="d-sec"><h3>Pagella del titolo ${info(PIL_INFO)}</h3>
    <p class="small"><b>${S.ok} ✓</b> · <b>${S.ko} ✕</b>${S.na ? ` · ${S.na} ?` : ""} su ${S.n} controlli</p>
    <ul class="pil-list">${P.list.map(x => `<li><div class="pil-row">
      <span class="pil-st ${x.state}" title="${{ ok: "vale", ko: "caduto", na: "non valutabile" }[x.state]}">${PIL_ICON[x.state]}</span>
      <span><b>${esc(x.name)}</b><br><span class="muted small">${esc(x.rule)}</span><br><span class="small">${x.state === "na" ? "non valutabile: " : ""}${esc(x.detail)}</span></span></div></li>`).join("")}</ul>
    <h4 class="bt-h">Registro</h4>
    ${P.log?.length ? `<ul class="pil-log small">${P.log.map(pilLog).join("")}</ul>` : `<p class="muted small">Ancora vuoto: qui compaiono, con la data, i controlli che cambiano stato.</p>`}
  </div>`;
}
function marketHTML(p) {
  const M = p.market || {}, S = p.stopAuto;
  const v = M.verdict ? `<span class="act ${VERDICT_CLS[M.verdict] || "hold"}">${esc(M.label || M.verdict)}</span> ${M.why?.length ? `<span class="small">${esc(M.why[0])}</span>` : ""}`
    : `<span class="muted">non calcolabile oggi</span>`;
  const atrs = S && S.atr ? (p.price - S.stop) / S.atr : null;
  return `<div class="d-sec"><h3>Mercato e stop</h3>
    <p><b>Verdetto di mercato</b>: ${v}<br><span class="muted small">${esc(M.source || "")}${M.skipped?.length ? ` · regole saltate: ${M.skipped.map(esc).join(", ")}` : ""} · come se dovessi comprare oggi</span></p>
    <p><b>Stop automatico</b> ${info(STOP_INFO)}: ${S && S.stop == null ? `<span class="muted">${esc(S.why || "non calcolabile")}</span>` : S ? `<b>${fPrice(S.stop)} ${esc(S.currency || p.currency)}</b>
      <span class="small">· ${atrs !== null ? `${atrs > 0 ? "" : "rotto: "}${fNum(atrs, 1)} ATR dal prezzo` : ""} · dal ${dayIT(S.since)}${S.raised ? `, alzato ${S.raised} ${S.raised === 1 ? "volta" : "volte"}` : ""}</span>
      <br><span class="muted small">${esc(S.how)}</span>` : `<span class="muted">non ancora calcolabile (servono i prezzi giornalieri del titolo)</span>`}</p></div>`;
}
// the fixed test of the levels in the positions diary (pos_diary.py): 3 months, at least 30 cases, 60% and 2 points
const posDiaryLine = D => {
  if (!D) return "";
  const one = (name, x) => `«${name}»: ${x.verdict === "dati ancora insufficienti" ? `dati ancora insufficienti (${x.cases} ${x.cases === 1 ? "caso" : "casi"} su 30)`
    : `${esc(x.verdict)} (${x.cases} casi, peggio delle altre posizioni nel ${fNum(x.worse, 0)}%, differenza mediana ${x.median > 0 ? "+" : ""}${fNum(x.median, 1)} punti)`}`;
  return `<p class="muted small"><b>Verifica nel diario delle posizioni</b> (a 3 mesi, test fissato il 4 novembre 2026): ${one("Valuta la vendita", D.sell)} · ${one("Accumula", D.add)}.
    ${D.days ? `Conteggio dal ${dayIT(D.since)}, ${D.days} ${D.days === 1 ? "seduta" : "sedute"} con le regole attuali.` : "Il primo giorno viene salvato stasera dopo la chiusura di Wall Street."}
    Le posizioni vendute prima dei 3 mesi escono dal conto.</p>`;
};
// panel of one position: proposed level with its rules, market verdict and automatic stop, pagella
function openPosition(isin) {
  const p = pf.data?.positions?.find(x => x.isin === isin);
  if (!p || !p.action) return;
  const A = p.action;
  state.detail = null; state.macro = null; state.panel = "position"; pf.openPos = isin;
  const icon = { on: "✅", off: "—", na: "·" };
  const groups = ["Valuta la vendita", "Attenzione", "Accumula"];
  drawer.classList.remove("full");
  drawer.innerHTML = `<div class="d-top"><div class="d-head"><div><div class="tt">${esc(p.ticker || p.symbol || p.name)}</div><div class="nm">${esc(p.name)} · ${fNum(p.weight, 1)}% del portafoglio</div></div>
      <div class="actions"><button class="icon-btn close-btn" id="dClose" aria-label="Chiudi">×</button></div></div></div>
    <div class="d-rest pos-d">
      <div class="d-sec"><h3>Indicazione ${info(ACT_INFO)}</h3><p>${actBadge(A)}</p>
        ${A.reasons.length ? `<ul class="why">${A.reasons.map(r => `<li>${esc(r)}</li>`).join("")}</ul>` : `<p class="muted">Nessuna regola scattata.</p>`}
        <p class="act-todo"><b>Cosa fare</b>: ${esc(A.todo)}${A.until?.length ? `<br><b>Quando sparisce</b>: ${A.until.map(esc).join("; ")}.` : ""}</p>
        ${A.tax ? `<p class="small">${actTax(A)}<br><span class="muted">${TAX_NOTE}</span></p>` : ""}
        ${A.notes.length ? `<p class="muted small">${A.notes.map(esc).join("<br>")}</p>` : ""}</div>
      ${marketHTML(p)}
      ${pagellaHTML(p)}
      <div class="d-sec"><h3>Tutte le regole</h3>
        ${groups.map(g => `<h4 class="bt-h">${g}${g === "Accumula" ? " (devono valere tutte)" : " (ne basta una)"}</h4><ul class="rule-list">${A.rules.filter(r => r.group === g).map(r =>
          `<li class="${r.state}"><span class="ri">${icon[r.state]}</span><span><b>${r.id}</b> ${esc(r.text)}<span class="muted small"> ${r.state === "na" ? "non valutabile: " : ""}${esc(r.detail)}</span></span></li>`).join("")}</ul>`).join("")}
        <p class="muted small">✅ scattata (per Accumula: soddisfatta) · — non scattata · “non valutabile” quando manca il dato (un dato mancante non fa mai scattare un avviso). Regole di disciplina, non verificate da backtest.</p>
        ${posDiaryLine(pf.data.posDiary)}</div>
      ${p.ticker && state.bySym.has(p.ticker) ? `<button class="link-btn" data-mopen="${esc(p.ticker)}">Apri la scheda del titolo →</button>` : ""}
      <p class="disclaimer">Non è una consulenza finanziaria.</p></div>`;
  drawer.classList.add("open"); drawer.setAttribute("aria-hidden", "false"); scrim.hidden = false;
  $("#dClose").onclick = closeDetail;
}
document.addEventListener("click", e => { const b = e.target.closest("[data-pos]"); if (b) { e.stopPropagation(); openPosition(b.dataset.pos); } }, true);
// ---- history and performance (history.py): daily pictures in portafoglio/storico/, time-weighted return vs references
const PERF_INFO = `<b>Rendimento ponderato per il tempo.</b> Se oggi il portafoglio vale 30.000 € e domani aggiungi 5.000 €, il valore sale a 35.000 € ma non hai guadagnato nulla.
  Per questo ogni giorno il rendimento è calcolato <b>solo sui soldi che c'erano già</b> (valore di fine giornata meno i soldi aggiunti, diviso il valore del giorno prima),
  e i rendimenti dei giorni vengono concatenati. Misura come sono andate le tue scelte, indipendentemente da quando hai versato o prelevato: è il metodo con cui si misurano i fondi.<br><br>
  <b>Guadagno in euro</b>: variazione del valore meno i soldi aggiunti (più quelli tolti).<br><br>
  I riferimenti sono in euro e comprendono i dividendi: QQQ (Nasdaq-100) e VWCE (Vanguard FTSE All-World, azionario mondiale quotato in Europa).`;
const perf = { data: null, range: LS.get("pfPerfRange", "ALL"), at: 0 };
async function loadPerf() {
  if (perf.data && Date.now() - perf.at < 5 * 60_000) return renderPerf();
  perf.at = Date.now();
  try { perf.data = await getJSON("/api/portfolio/history"); } catch { perf.data = null; }
  renderPerf();
}
function renderPerf() {
  const el = $("#pfPerf"), D = perf.data;
  if (!D) { el.hidden = true; return; }
  el.hidden = false;
  const ranges = [["1M", "1 mese", 31], ["3M", "3 mesi", 92], ["YTD", "Da inizio anno", 0], ["ALL", "Tutto", 0]];
  const head = `<div class="card-h"><h2>Performance ${info(PERF_INFO)}</h2><div class="seg small">${ranges.map(([k, l]) => `<button data-perf="${k}" class="${perf.range === k ? "on" : ""}">${l}</button>`).join("")}</div></div>`;
  const all = D.points;
  if (all.length < 2) {
    el.innerHTML = head + `<div class="empty">${all.length ? `Lo storico parte dal ${dayIT(all[0].date)}: grafico e rendimenti compaiono dal secondo giorno salvato.` : "Nessun giorno salvato ancora: lo storico parte al prossimo aggiornamento dei prezzi."}</div>
      <p class="muted small">Ogni giorno la dashboard salva valore, costo e posizioni in <code>portafoglio/storico/</code>, solo su questo Mac.</p>`;
    return;
  }
  const lastDay = all.at(-1).date, r = ranges.find(x => x[0] === perf.range) || ranges[3];
  const from = r[0] === "YTD" ? lastDay.slice(0, 4) + "-01-01" : r[2] ? new Date(Date.parse(lastDay) - r[2] * 864e5).toISOString().slice(0, 10) : "";
  let k0 = all.findIndex(p => p.date >= from);
  if (k0 > 0) k0 -= 1;                                   // the day before the period is its starting point
  const pts = all.slice(Math.max(0, k0)), a = pts[0], z = pts.at(-1);
  const t = p => Date.parse(p.date + "T12:00:00") / 1000;
  const ret = k => isNum(z[k]) && isNum(a[k]) && a[k] ? (z[k] / a[k] - 1) * 100 : null;
  const flows = pts.slice(1).reduce((s, p) => s + p.flow, 0), gain = z.value - a.value - flows;
  const series = [["twr", "Portafoglio", "--ink"], ["qqq", D.bench?.qqq || "QQQ in euro", "--series-1"], ["world", D.bench?.world || "VWCE", "--series-2"]].filter(([k]) => pts.some(p => isNum(p[k])));
  const pc = v => `<span class="${sign(v)}">${fPct(v, 1)}</span>`;
  const fl = D.flows.filter(f => f.date > a.date && f.date <= z.date);
  el.innerHTML = head + `
    ${D.short ? `<p class="warn-box">Lo storico ha ${all.length} ${all.length === 1 ? "giorno" : "giorni"} (dal ${dayIT(all[0].date)}): è ancora troppo corto per trarre conclusioni. Sotto i 3 mesi le differenze con i riferimenti possono essere solo caso.</p>` : ""}
    <h4 class="bt-h">Valore nel tempo (€) <span class="muted">▲ soldi aggiunti · ▼ soldi tolti</span></h4><div id="pfPerfVal" class="chart"></div>
    <h4 class="bt-h">Rendimento dall'inizio del periodo (%)</h4>
    <div class="series-key">${series.map(([, l, c]) => `<span><i style="background:var(${c})"></i>${esc(l)}</span>`).join("")}</div><div id="pfPerfRet" class="chart"></div>
    <div class="table-wrap"><table class="scr perf-sum"><thead><tr><th class="l">Dal ${dayIT(a.date)} al ${dayIT(z.date)}</th>${series.map(([, l]) => `<th>${esc(l)}</th>`).join("")}<th>Guadagno in euro</th><th class="p4">Soldi aggiunti (netti)</th></tr></thead>
      <tbody><tr><td class="l"><b>Rendimento</b> <span class="muted small">ponderato per il tempo</span></td>${series.map(([k]) => `<td><b>${pc(ret(k))}</b></td>`).join("")}
        <td><span class="${sign(gain)}">${fEurS(gain, 0)}</span></td><td class="p4">${fEurS(flows, 0)}</td></tr></tbody></table></div>
    <p class="small"><span class="muted">Movimenti nel periodo:</span> ${fl.length ? fl.map(f => `${dayShort(f.date)} ${f.bought ? `acquisti +${fEur(f.bought, 0)}` : ""}${f.bought && f.sold ? ", " : ""}${f.sold ? `vendite −${fEur(f.sold, 0)}${f.estimated ? " (stimato)" : ""}` : ""}`).join(" · ") : "nessuno"}</p>
    <details class="fold"><summary><span class="small">Limiti di questo calcolo</span></summary><ul class="why bt-lim">${D.limits.map(l => `<li><b>${esc(l.title)}.</b> ${esc(l.text)}</li>`).join("")}</ul>
      <p class="muted small">${pts.filter(p => p.rebuilt).length} giorni ricostruiti nel periodo. Dati salvati in <code>portafoglio/storico/</code>, solo su questo Mac; i giorni passati non vengono mai modificati.</p></details>`;
  const tipDay = i => `<div class="tip-h">${dayIT(pts[i].date)}${pts[i].rebuilt ? " · ricostruito" : ""}</div>`;
  const ch = lineChart($("#pfPerfVal"), [{ pts: pts.map(p => ({ t: t(p), v: p.value })), color: css("--ink"), width: 1.8 }], {
    height: 200, range: pts.length > 120 ? "1Y" : "1M", yFmt: v => fNum(v, 0), label: "Valore del portafoglio in euro",
    tip: i => `${tipDay(i)}<div class="tip-row"><span>Valore</span><b class="num">${fEur(pts[i].value, 0)}</b></div>${pts[i].flow ? `<div class="tip-row"><span>${pts[i].flow > 0 ? "Soldi aggiunti" : "Soldi tolti"}</span><b class="num">${fEurS(pts[i].flow, 0)}</b></div>` : ""}`,
  });
  if (ch?.x) d3.select("#pfPerfVal svg").append("g").attr("transform", `translate(${ch.m.l},0)`).selectAll("text").data(pts.map((p, i) => ({ p, i })).filter(d => d.p.flow)).join("text")
    .attr("class", "perf-flow").attr("x", d => ch.x(d.i)).attr("y", 11).attr("text-anchor", "middle").attr("fill", d => css(d.p.flow > 0 ? "--up" : "--down")).text(d => d.p.flow > 0 ? "▲" : "▼");
  lineChart($("#pfPerfRet"), series.map(([k, , c]) => ({ pts: pts.map(p => ({ t: t(p), v: isNum(p[k]) && a[k] ? (p[k] / a[k] - 1) * 100 : null })), color: css(c), width: k === "twr" ? 2 : 1.5 })), {
    height: 200, range: pts.length > 120 ? "1Y" : "1M", baseline: 0, area: false, yFmt: v => fNum(v, 1) + "%", label: "Rendimento del portafoglio e dei riferimenti",
    tip: i => tipDay(i) + series.map(([k, l, c]) => `<div class="tip-row"><span><i class="swatch" style="background:var(${c})"></i>${esc(l)}</span><b class="num">${isNum(pts[i][k]) && a[k] ? fPct((pts[i][k] / a[k] - 1) * 100, 1) : "—"}</b></div>`).join(""),
  });
}
document.addEventListener("click", e => { const b = e.target.closest("[data-perf]"); if (b) { perf.range = b.dataset.perf; LS.set("pfPerfRange", perf.range); renderPerf(); } });
// ---- risk of the portfolio (risk.py): estimates on the last 2 years with today's weights, limits always shown
const RISK_INFO = {
  all: `Quanto può oscillare il portafoglio <b>com'è oggi</b>. I numeri sono stime sugli ultimi 2 anni, calcolate come se avessi sempre avuto i pesi di oggi,
    con tutti i prezzi convertiti in euro. Non sono previsioni: leggi i limiti in fondo alla sezione.`,
  vol: `<b>Volatilità annua</b>: di quanto oscilla di solito il valore in un anno, in più o in meno. Con una volatilità del 25%, in circa due anni su tre
    il risultato dell'anno resta entro ±25% dalla media; negli altri va oltre. Più è alta, più le oscillazioni sono ampie. QQQ è il fondo che replica il Nasdaq-100.`,
  beta: `<b>Beta</b>: di quanto si muove in media il portafoglio quando il Nasdaq-100 si muove dell'1%. Beta 1 = come l'indice; 1,3 = il 30% in più, in salita e in discesa;
    0,7 = il 30% in meno. È stimato sui rendimenti settimanali degli ultimi 2 anni.`,
  scen: `<b>Scenario</b>: beta × calo dell'indice × valore del portafoglio, a cambio EUR/USD fermo. I prodotti a leva entrano con i loro prezzi veri, quindi la leva è già contata.
    È una stima lineare: nei cali forti e veloci la perdita reale può essere più grande, soprattutto con prodotti a leva giornaliera.`,
  dd: `<b>Massima perdita storica</b> (drawdown): il calo più profondo, dal punto più alto al punto più basso successivo, che il portafoglio di oggi avrebbe avuto negli ultimi 2 anni.
    Serve a chiedersi: «avrei retto questa discesa senza vendere nel momento peggiore?».`,
  rc: `<b>Contributo al rischio</b>: quanta parte delle oscillazioni del portafoglio dipende da ogni posizione (la somma fa 100%). Dipende dal peso, da quanto la posizione oscilla
    e da quanto si muove insieme alle altre. Se una posizione pesa il 6% in euro ma porta il 19% del rischio, conta sul rischio 3 volte il suo peso (⚠ da 1,5 volte in su).`,
  corr: `<b>Correlazione</b>: da −1 a +1, quanto due posizioni si muovono insieme. Vicino a 1 = quasi la stessa cosa (per esempio due ETF sullo stesso indice): tenerle entrambe
    diversifica poco. La media è pesata per i pesi delle posizioni: sotto 0,3 bassa, tra 0,3 e 0,6 media, sopra 0,6 alta.`,
};
const risk = { data: null, retry: null, file: null, at: 0 };
async function loadRisk() {
  clearTimeout(risk.retry);
  try { risk.data = await getJSON("/api/portfolio/risk"); } catch { risk.data = { status: "error", error: "server non raggiungibile" }; }
  renderRisk();
  if (risk.data.status === "loading" && PF_SUBS.includes(state.view)) risk.retry = setTimeout(loadRisk, 3000);
}
function renderRisk() {
  const el = $("#pfRisk"), D = risk.data;
  if (!D || D.status === "none") { el.hidden = true; return; }
  el.hidden = false;
  const head = meta => `<div class="card-h"><h2>Rischio ${info(RISK_INFO.all)}</h2><span class="card-meta">${meta}</span></div>`;
  if (D.status === "loading") { el.innerHTML = head("") + `<div class="empty">Calcolo in corso: scarico 2 anni di prezzi delle tue posizioni (qualche secondo)…</div>`; return; }
  if (D.status !== "ok") { el.innerHTML = head("") + `<div class="empty">Rischio non calcolabile al momento (${esc(D.error || "dati mancanti")}).</div>`; return; }
  const kpi = (l, i, v, sub) => `<div class="kpi"><div class="l">${l} ${info(i)}</div><div class="v">${v}</div><div class="s">${sub}</div></div>`;
  const dd = D.drawdown, b = D.beta;
  const betaSay = !isNum(b) ? "" : Math.abs(b - 1) < 0.05 ? "si muove circa come l'indice" : `si muove il ${fNum(Math.abs(b - 1) * 100, 0)}% ${b > 1 ? "più" : "meno"} dell'indice`;
  const left = D.left.length ? ` · fuori dal calcolo: ${D.left.map(x => `${esc(x.name)} (${fNum(x.weight, 1)}% del valore: ${esc(x.why)})`).join(", ")}` : "";
  el.innerHTML = head(`stima dal ${dayIT(D.from)} al ${dayIT(D.to)}, con i pesi di oggi, in euro · copre il ${fNum(D.coverage, 0)}% del valore${D.left.length ? ` (${D.left.length} ${D.left.length === 1 ? "posizione esclusa" : "posizioni escluse"}, vedi i limiti)` : ""}`) + `
    <p class="risk-intro">Questa pagina serve a capire <b>quanto oscilla il portafoglio</b> e <b>quali posizioni lo fanno oscillare più di quanto pesano</b>:
      una posizione piccola ma molto volatile, o a leva, può pesare sul rischio molto più che sul valore.</p>
    <div class="kpis">
      ${kpi("Volatilità annua", RISK_INFO.vol, fNum(D.vol, 0) + "%", `QQQ: ${fNum(D.benchVol, 0)}%`)}
      ${kpi("Beta sul Nasdaq-100", RISK_INFO.beta, fNum(b, 2), betaSay)}
      ${kpi("Se il Nasdaq-100 perde", RISK_INFO.scen, D.scenarios.map(s => `<div class="risk-sc">−${s.drop}% → <span class="down">circa ${fEur(s.loss, 0)}</span></div>`).join(""), `circa ${D.scenarios.map(s => fNum(s.pct, 0) + "%").join(" e ")} del portafoglio`)}
    </div>
    <h4 class="bt-h">Contributo al rischio ${info(RISK_INFO.rc)} <span class="muted">chi pesa sul rischio più di quanto pesa in euro</span></h4>
    <div class="table-wrap"><table class="scr"><thead><tr><th class="l">Posizione</th><th>Peso in euro</th><th>Quota del rischio</th><th>Rapporto</th><th class="p3">Beta</th><th class="p3">Volatilità annua</th></tr></thead>
      <tbody>${D.positions.map(p => `<tr><td class="l wrap"><b>${esc(p.name)}</b>${p.fullName !== p.name ? ` <span class="muted small">${esc(p.fullName)}</span>` : ""}</td>
        <td>${fNum(p.weight, 1)}%</td><td><b>${fNum(p.risk, 1)}%</b></td><td class="${p.flag ? "flag" : ""}">${fNum(p.ratio, 1)}×${p.flag ? " ⚠" : ""}</td><td class="p3">${fNum(p.beta, 2)}</td><td class="p3">${fNum(p.vol, 0)}%</td></tr>`).join("")}</tbody></table></div>
    <details class="fold"><summary><span class="small">Altre misure: massima perdita storica e correlazione</span></summary>
      <div class="kpis">      ${kpi("Massima perdita storica", RISK_INFO.dd, `<span class="down">${fNum(dd.pct, 0)}%</span>`, `dal ${dayIT(dd.peak)} al ${dayIT(dd.trough)} · QQQ negli stessi giorni ${fNum(dd.benchSame, 0)}%`)}
      </div>
    <h4 class="bt-h">Correlazione ${info(RISK_INFO.corr)}</h4>
    <p>${isNum(D.correlation.avg) ? `Media <b>${fNum(D.correlation.avg, 2)}</b> (${D.correlation.label}): ${{ bassa: "le posizioni si muovono in modo abbastanza indipendente.", media: "le posizioni si muovono in parte insieme.", alta: "le posizioni tendono a muoversi insieme: nei cali scendono quasi tutte." }[D.correlation.label]}` : "Non calcolabile."}
      ${D.correlation.pairs.length ? `<br><span class="muted">Coppie più simili:</span> ${D.correlation.pairs.map(x => `${esc(x.a)} ↔ ${esc(x.b)} <b>${fNum(x.corr, 2)}</b>`).join(" · ")}` : ""}</p>
    </details>
    <details class="fold"><summary><span class="small">Limiti di questi calcoli: leggili prima di fidarti dei numeri</span></summary>
      <ul class="why bt-lim">${D.limits.map(l => `<li><b>${esc(l.title)}.</b> ${esc(l.text)}</li>`).join("")}</ul>
      <p class="muted small">Calcolato sul ${fNum(D.coverage, 0)}% del valore (${fEur(D.covered, 0)})${left}. Stime, non previsioni. Non è una consulenza finanziaria.</p></details>`;
}
const ruleLimit = v => fNum(v, v % 1 ? 1 : 0) + "%";
// ---- zainetto fiscale (actions.py, portafoglio/fiscale.json): optional, used only by the indicative tax estimate.
// Phase 8B.1: the box is no longer on the Portafoglio page (its element was removed from index.html); this function,
// /api/fiscal and the saved data stay, and the tax estimate keeps using them.
function renderTaxBox() {
  const el = $("#pfTax"), F = pf.data?.fiscal || {};
  if (!el || el.contains(document.activeElement) && document.activeElement.tagName === "INPUT") return;   // typing: do not redraw
  el.innerHTML = `<summary><span class="small"><b>Zainetto fiscale</b> (facoltativo) · ${F.losses ? `minusvalenze disponibili ${fEur(F.losses, 0)}${F.expiry ? `, scadenza più vicina ${dayIT(F.expiry)}` : ""}` : "non indicato"}</span></summary>
    <p class="small">Lo «zainetto» sono le minusvalenze (perdite realizzate) che puoi ancora usare per pagare meno imposte sulle plusvalenze di azioni, ETC e derivati, entro 4 anni.
      Lo trovi nel sito Fineco (area fiscale). Se lo indichi, la stima fiscale accanto a «Valuta la vendita» e «target raggiunto» ne tiene conto per <b>azioni ed ETC</b>; per gli <b>ETF</b> no,
      perché i loro guadagni sono redditi di capitale e non si compensano.</p>
    <div class="toolbar"><label class="small">Minusvalenze disponibili <input type="number" id="taxLosses" min="0" step="1" value="${F.losses ?? ""}" placeholder="es. 1200"> €</label>
      <label class="small">Scadenza più vicina <input type="date" id="taxExpiry" value="${F.expiry || ""}"></label>
      <button class="btn" id="taxSave">Salva</button><span id="taxMsg" class="small"></span></div>
    <p class="muted small">${F.losses ? "" : "Campo vuoto: se hai minusvalenze nello zainetto, l'imposta reale può essere più bassa di quella stimata. "}Salvato in portafoglio/fiscale.json, solo su questo Mac. Stima indicativa, non è una consulenza fiscale.</p>`;
  $("#taxSave").onclick = async () => {
    const raw = $("#taxLosses").value.trim().replace(",", "."), losses = raw === "" ? null : parseFloat(raw);
    if (losses !== null && !(losses >= 0)) { $("#taxMsg").innerHTML = `<span class="down">Scrivi un importo in euro, oppure lascia vuoto.</span>`; return; }
    try {
      await pfPost("/api/fiscal", { body: JSON.stringify({ losses, expiry: $("#taxExpiry").value || null }), headers: { "Content-Type": "application/json" } });
      document.activeElement?.blur();
      await loadPortfolio();
      $("#taxMsg").textContent = "✓ Salvato";
    } catch (e) { $("#taxMsg").innerHTML = `<span class="down">Non salvato: ${esc(e.message)}</span>`; }
  };
}
// ---- phase 9A: classification of an ETF/ETC and Yahoo ticker typed by the user (before: only by hand in the files).
// The dashboard invents nothing: it saves what is typed (server-side checks in portfolio.save_classification / save_ticker).
const pfIsFund = kind => /^(ETF|ETC|ETN)$/i.test(kind || "") || !/^azion/i.test(kind || "");
function pfClsForm(isin, D) {
  const secs = [...new Set(["come il Nasdaq-100", ...((D.concentration || {}).sector || []).map(r => r.name).filter(n => n && n !== "Non classificato")])];
  const id = "pfSec" + isin.replace(/[^A-Za-z0-9]/g, "");
  return `<details class="pf-cls"><summary class="small">Compila la classificazione</summary>
    <form class="pf-cls-f" data-isin="${esc(isin)}">
      <label class="small">Settore <input name="settore" maxlength="40" list="${id}" required></label><datalist id="${id}">${secs.map(x => `<option value="${esc(x)}">`).join("")}</datalist>
      <label class="small">Tema <input name="tema" maxlength="40"></label>
      <label class="small">Paese o area <input name="paese" maxlength="40" placeholder="es. USA, Mondo, Europa"></label>
      <label class="small">Leva <select name="leva"><option value="">nessuna</option>${[2, 3, 4, 5].map(n => `<option value="${n}">${n}x</option>`).join("")}</select></label>
      <button class="btn" type="submit">Salva</button> <span class="pf-f-msg small" role="status"></span>
    </form></details>`;
}
document.addEventListener("submit", async e => {
  const f = e.target.closest(".pf-cls-f, .pf-tk-f");
  if (!f) return;
  e.preventDefault();
  const msg = f.querySelector(".pf-f-msg"), v = n => f.elements[n]?.value.trim() || null;
  const cls = f.classList.contains("pf-cls-f");
  const body = cls ? { isin: f.dataset.isin, fields: { settore: v("settore"), tema: v("tema"), paese: v("paese"), leva: v("leva") } }
    : { isin: f.dataset.isin, ticker: v("ticker") };
  msg.textContent = "Salvo…";
  try {
    await pfPost(cls ? "/api/portfolio/classification" : "/api/portfolio/ticker", { body: JSON.stringify(body), headers: { "Content-Type": "application/json" } });
    msg.textContent = "✓ Salvato";
    await loadPortfolio();
  } catch (err) { msg.innerHTML = `<span class="down">Non salvato: ${esc(err.message)}</span>`; }
});
// ---- upload of a Fineco export: preview first (new, sold, changed positions), saved only after confirmation.
// The file goes only to the server on this Mac (portafoglio/, outside Git); older files stay there.
const pfUp = { busy: false };
const pfPost = (url, opts = {}) => fetch(url, { method: "POST", ...opts, headers: { "X-Requested-With": "ndx-dashboard", ...(opts.headers || {}) } })
  .then(async r => { const d = await r.json().catch(() => ({})); if (!r.ok) throw new Error(d.error || r.statusText); return d; });
function pfUpShow(html) { const b = $("#pfUpBox"); b.hidden = !html; b.innerHTML = html || ""; }
async function pfUpload(file) {
  if (!file || pfUp.busy) return;
  pfUp.busy = true;
  pfUpShow(`<div class="muted">Leggo ${esc(file.name)}…</div>`);
  try {
    const d = await pfPost("/api/portfolio/upload", { body: file, headers: { "X-Filename": encodeURIComponent(file.name), "Content-Type": "application/octet-stream" } });
    const q = v => fNum(v, v % 1 ? 2 : 0);
    const grp = (title, list, row) => `<div class="pf-up-g"><b>${title} (${list.length})</b>${list.length
      ? `<ul>${list.map(x => `<li>${esc(x.name)} <span class="muted">${esc(x.isin)}</span> · ${row(x)}</li>`).join("")}</ul>` : ` <span class="muted">nessuna</span>`}</div>`;
    pfUpShow(`<div class="card-h"><h2>Anteprima: ${esc(d.file)}</h2><span class="card-meta">${d.count} posizioni · ${d.current ? `confronto con ${esc(d.current)}` : "nessun file attuale"}</span></div>
      ${grp("Nuove", d.new, x => `quantità ${q(x.qty)}`)}${grp("Vendute", d.sold, x => `erano ${q(x.qty)}`)}
      ${grp("Quantità cambiata", d.changed, x => `da ${q(x.from)} a ${q(x.qty)}`)}
      <div class="pf-up-g"><b>Invariate</b> ${d.same}</div>
      <p class="muted small">Il file attuale non viene cancellato: resta nella cartella <code>portafoglio/</code>. La dashboard userà il nuovo file.</p>
      <div class="toolbar"><button class="btn" id="pfUpCancel">Annulla</button><button class="btn primary" id="pfUpOk" data-token="${esc(d.token)}">Conferma e usa questo file</button></div>`);
  } catch (e) {
    pfUpShow(`<div class="pf-up-err">⚠ File non caricato. ${esc(e.message)}</div><div class="toolbar"><button class="btn" id="pfUpCancel">Chiudi</button></div>`);
  }
  pfUp.busy = false;
  $("#pfUpFile").value = "";
}
$("#pfUpBtn").addEventListener("click", () => $("#pfUpFile").click());
$("#pfUpFile").addEventListener("change", e => pfUpload(e.target.files[0]));
$("#pfUpBox").addEventListener("click", async e => {
  if (e.target.id === "pfUpCancel") { pfUpShow(""); pfPost("/api/portfolio/upload/cancel").catch(() => {}); }
  if (e.target.id === "pfUpOk") {
    e.target.disabled = true;
    try {
      const d = await pfPost("/api/portfolio/upload/confirm", { body: JSON.stringify({ token: e.target.dataset.token }), headers: { "Content-Type": "application/json" } });
      pfUpShow(`<div class="muted">✓ Salvato come <code>portafoglio/${esc(d.file)}</code>. Aggiorno le posizioni…</div>`);
      await loadPortfolio();
      setTimeout(() => pfUpShow(""), 6000);
    } catch (err) { pfUpShow(`<div class="pf-up-err">⚠ ${esc(err.message)}</div><div class="toolbar"><button class="btn" id="pfUpCancel">Chiudi</button></div>`); }
  }
});
// drag and drop, only while the Portafoglio tab is open (elsewhere the browser keeps its normal behaviour)
const pfDragging = e => state.view === "portfolio" && [...(e.dataTransfer?.types || [])].includes("Files");   // Posizioni only
addEventListener("dragover", e => { if (pfDragging(e)) { e.preventDefault(); $("#view-portfolio").classList.add("drop"); } });
addEventListener("dragleave", e => { if (!e.relatedTarget) $("#view-portfolio").classList.remove("drop"); });
addEventListener("drop", e => {
  if (!pfDragging(e)) return;
  e.preventDefault();
  $("#view-portfolio").classList.remove("drop");
  pfUpload(e.dataTransfer.files[0]);
});
$("#pfColSeg").addEventListener("click", e => { const b = e.target.closest("[data-cols]"); if (b) { pf.cols = b.dataset.cols; LS.set("pfCols", pf.cols); renderPortfolio(); } });
$("#pfDimSeg").addEventListener("click", e => { const b = e.target.closest("[data-dim]"); if (b) { pf.dim = b.dataset.dim; LS.set("pfDim", pf.dim); renderConcentration(); } });
$("#pfTbl").addEventListener("click", e => {
  const th = e.target.closest("th[data-k]");
  if (th) {
    const k = th.dataset.k;
    pf.sort = pf.sort.key === k ? { key: k, dir: -pf.sort.dir } : { key: k, dir: k === "name" ? 1 : -1 };
    return renderPortfolio();
  }
  const tr = e.target.closest("tr[data-t]");
  if (tr && tr.dataset.t) openDetail(tr.dataset.t);
});

// ------------------------------------------------------------ screener
const C = {
  star:   { l: "", cls: "l", sort: s => state.watch.has(s.ticker) ? 1 : 0, html: s => `<button class="star ${state.watch.has(s.ticker) ? "on" : ""}" data-star="${esc(s.ticker)}" aria-label="${state.watch.has(s.ticker) ? "Togli dai Preferiti" : "Aggiungi ai Preferiti"}" title="${state.watch.has(s.ticker) ? "Togli dai Preferiti" : "Aggiungi ai Preferiti"}" aria-pressed="${state.watch.has(s.ticker)}">${state.watch.has(s.ticker) ? "★" : "☆"}</button>` },
  ticker: { l: "Ticker", cls: "l tk", sort: s => s.ticker, html: s => esc(s.ticker) },
  name:   { l: "Società", cls: "l nm", sort: s => s.name, html: s => esc(s.name) },
  sector: { l: "Settore", cls: "l", sort: s => s.sector, html: s => esc(s.sector) },
  industry: { l: "Industria", cls: "l", sort: s => s.industry, html: s => esc(s.industry) },
  mcap:   { l: "Capitalizz.", sort: s => s.mcap, html: s => isNum(s.mcap) ? fNum(s.mcap / 1e9, 0) + " Mld" : "—" },   // one unit per column
  weight: { l: "Peso", sort: s => s.weight, html: s => fW(s) },
  price:  { l: "Prezzo", sort: s => s.price, html: s => fPrice(s.price) },
  chgPct: { l: "Var.", sort: s => s.chgPct, html: s => `<span class="${sign(s.chgPct)}">${fPct(s.chgPct)}</span>` },
  volume: { l: "Volume", sort: s => s.volume, html: s => isNum(s.volume) ? fNum(s.volume / 1e6, 1) + " Mln" : "—" },
  relVol: { l: "Volume relativo", sort: s => s.relVol, html: s => fX(s.relVol) },
  d30:    { l: "30 giorni", nosort: true, html: s => spark(s.d30, 90, 22, null) },
  pe:     { l: "P/E", sort: s => s.pe, html: s => fNum(s.pe, 1) },
  fpe:    { l: "P/E atteso", sort: s => s.fpe, html: s => fNum(s.fpe, 1) },
  divYield: { l: "Rend. div.", sort: s => s.divYield, html: s => isNum(s.divYield) && s.divYield > 0 ? fNum(s.divYield, 2) + "%" : "—" },
  beta:   { l: "Beta", sort: s => s.beta, html: s => fNum(s.beta, 2) },
  revGrowth: { l: "Crescita ricavi", sort: s => s.revGrowth, html: s => isNum(s.revGrowth) ? `<span class="${sign(s.revGrowth)}">${fPct(s.revGrowth * 100, 1)}</span>` : "—" },
  margin: { l: "Margine netto", sort: s => s.margin, html: s => isNum(s.margin) ? fNum(s.margin * 100, 1) + "%" : "—" },
  target: { l: "Target", sort: s => s.target, html: s => fPrice(s.target) },
  upside: { l: "Potenziale", sort: s => s.upside, html: s => `<span class="${sign(s.upside)}">${fPct(s.upside, 1)}</span>` },
  rec:    { l: "Analisti", cls: "l", sort: s => s.recMean, html: s => esc(REC[s.rec] || "—") },
  signal: { l: "Segnale", cls: "l", sort: s => s.sigScore, html: s => s.signal ? `${sigBadge(s.signal)}${isNum(s.sigScore) ? ` <span class="muted num">${fNum(Math.round(s.sigScore) || 0, 0)}</span>` : ""}` : "—" },
  trend:  { l: "Trend", sort: s => s.trend, html: s => isNum(s.trend) ? scoreBar(s.trend) : "—" },
  valLabel: { l: "Valutazione", cls: "l", sort: s => s.valRatio, html: s => valBadge(s.valLabel) },
  ps:     { l: "P/S", sort: s => s.ps, html: s => fNum(s.ps, 1) },
  evEbitda: { l: "EV/EBITDA", sort: s => s.evEbitda, html: s => fNum(s.evEbitda, 1) },
  peg:    { l: "PEG", sort: s => s.peg, html: s => fNum(s.peg, 2) },
  anl30:  { l: "Upgrade/downgrade 30 g", sort: s => (s.up30 || 0) - (s.down30 || 0), html: s => isNum(s.up30) ? `<span class="up">${s.up30}↑</span> <span class="down">${s.down30}↓</span>` : "—" },
  epsRev30: { l: "Revisione stime 30 g", sort: s => s.epsRev30, html: s => `<span class="${sign(s.epsRev30)}">${fPct(s.epsRev30, 1)}</span>` },
  rsi:    { l: "RSI 14", sort: s => s.rsi, html: s => { const v = s.rsi; return isNum(v) ? `<span class="${v > 70 ? "down" : v < 30 ? "up" : ""}">${v.toFixed(0)}</span>` : "—"; } },
  vsSma20: { l: "vs media 20", sort: s => s.vsSma20, html: s => `<span class="${sign(s.vsSma20)}">${fPct(s.vsSma20, 1)}</span>` },
  vsSma40: { l: "vs media 40", sort: s => s.vsSma40, html: s => `<span class="${sign(s.vsSma40)}">${fPct(s.vsSma40, 1)}</span>` },
  vsSma60: { l: "vs media 60", sort: s => s.vsSma60, html: s => `<span class="${sign(s.vsSma60)}">${fPct(s.vsSma60, 1)}</span>` },
  vsSma50: { l: "vs media 50", sort: s => s.vsSma50, html: s => `<span class="${sign(s.vsSma50)}">${fPct(s.vsSma50, 1)}</span>` },
  vsSma200: { l: "vs media 200", sort: s => s.vsSma200, html: s => `<span class="${sign(s.vsSma200)}">${fPct(s.vsSma200, 1)}</span>` },
  range52: { l: "Range 52 sett.", sort: s => s.range52, html: s => isNum(s.range52) ? `<span class="range-bar" title="${fPrice(s.lo52)} – ${fPrice(s.hi52)}"><i style="left:${s.range52}%"></i></span>` : "—" },
  fromHi52: { l: "Dal max 52 sett.", sort: s => s.fromHi52, html: s => `<span class="${sign(s.fromHi52)}">${fPct(s.fromHi52, 1)}</span>` },
  fromLo52: { l: "Dal min 52 sett.", sort: s => s.fromLo52, html: s => `<span class="${sign(s.fromLo52)}">${fPct(s.fromLo52, 1)}</span>` },
  gapPct: { l: "Gap in apertura", sort: s => s.gapPct, html: s => `<span class="${sign(s.gapPct)}">${fPct(s.gapPct)}</span>` },
  vol20:  { l: "Volatilità 20 g", sort: s => s.vol20, html: s => isNum(s.vol20) ? fNum(s.vol20, 0) + "%" : "—" },
  maOrder: { l: "Ordine medie", cls: "l", sort: s => maStack(s), html: s => maOrder(s) },
  earnings: { l: "Trimestrale", cls: "l", sort: s => daysTo(s.earningsTs), html: s => { const d = daysTo(s.earningsTs);
    return d == null ? "—" : `${fDate(s.earningsTs, { day: "numeric", month: "short" })} <span class="muted">${d < 0.5 ? "oggi" : "tra " + Math.round(d) + " g"}</span>`; } },
  news:   { l: "Ultima notizia", cls: "l nw", sort: s => { const n = myNews(s.ticker); return n ? Date.parse(n.time) || n.time * 1000 : null; },
    html: s => { const n = myNews(s.ticker);
      return n ? `${newsTag(n)} <a href="${esc(n.url)}" target="_blank" rel="noopener" title="${esc(n.title)}">${esc(n.title)}</a> <span class="muted">${esc(ago(n.time))}</span>` : `<span class="muted">—</span>`; } },
  short:  { l: "Short % flottante", sort: s => s.short, html: s => isNum(s.short) ? fNum(s.short * 100, 1) + "%" : "—" },
};
for (const [tf, m] of Object.entries(METRICS)) if (PERF_TFS.includes(tf) && tf !== "1D")
  C[m.key] = { l: m.label, sort: s => s[m.key], html: s => `<span class="${sign(s[m.key])}">${fPct(s[m.key])}</span>` };
// ⓘ text for every screener / "I miei titoli" column
const COL_INFO = {
  sector: "Settore economico della società (classificazione di Yahoo Finance).",
  industry: "Il ramo più specifico dentro il settore.",
  mcap: "Capitalizzazione: quanto vale in borsa la società (prezzo × numero di azioni).",
  weight: "Peso nel Nasdaq-100. Per i 10 titoli più grandi è il peso vero del fondo QQQ (da Nasdaq.com, una volta al giorno); per gli altri, segnati con ≈, è stimato: la parte restante dell'indice divisa in proporzione alla capitalizzazione. L'indice mette dei tetti ai titoli più grandi, per questo i pesi non sono la semplice quota di capitalizzazione.",
  price: "Ultimo prezzo, in dollari.",
  chgPct: "Variazione di oggi rispetto alla chiusura precedente.",
  volume: "Numero di azioni scambiate oggi.",
  relVol: "Volume di oggi diviso il volume medio, tenendo conto dell'ora del giorno. 1× = normale, 2× = il doppio del solito: c'è più interesse, spesso per una notizia.",
  d30: "Andamento del prezzo negli ultimi 30 giorni.",
  pe: "P/E: prezzo diviso l'utile per azione degli ultimi 12 mesi. Più basso = più economico, ma va confrontato con il settore e con la crescita.",
  fpe: "P/E atteso: come il P/E, ma con gli utili stimati dagli analisti per i prossimi 12 mesi.",
  divYield: "Rendimento del dividendo: dividendi pagati in un anno diviso il prezzo.",
  beta: "Quanto il titolo si muove rispetto al mercato: 1 = come il mercato, 1,5 = circa il 50% in più, sotto 1 = meno.",
  revGrowth: "Crescita dei ricavi rispetto allo stesso periodo dell'anno prima.",
  margin: "Margine netto: quanta parte dei ricavi diventa utile.",
  target: "Prezzo obiettivo medio degli analisti, a 12 mesi.",
  upside: "Potenziale: di quanto il target medio degli analisti è sopra (o sotto) il prezzo attuale.",
  rec: "Giudizio medio degli analisti, da Forte acquisto a Vendita.",
  signal: "Segnale finale, da −100 a +100: analisti 42%, valutazione 33%, notizie 25% (se una parte manca, il suo peso va alle altre). Con una sola parte disponibile compare «Dati insufficienti». Non è verificato con un backtest e non è una consulenza finanziaria.",
  trend: "Trend, da −100 a +100: come si sta muovendo il prezzo (medie 20/40/60, RSI, forza rispetto a QQQ). Descrive l'andamento, non è un voto: il backtest non ha mostrato che un Trend alto dia rendimenti migliori.",
  valLabel: "Confronto dei multipli (P/E, P/S, EV/EBITDA) con i titoli dello stesso settore e con la storia del titolo. Economica = in media oltre il 15% sotto, Cara = oltre il 18% sopra.",
  ps: "P/S: capitalizzazione diviso i ricavi di un anno. Utile per le società con pochi utili.",
  evEbitda: "EV/EBITDA: valore dell'azienda (compresi i debiti, meno la cassa) diviso il margine operativo lordo. Permette di confrontare società con debiti diversi.",
  peg: "PEG: P/E diviso la crescita attesa degli utili. Intorno a 1 = prezzo in linea con la crescita; sopra 2 = la crescita si paga cara.",
  anl30: "Quante volte negli ultimi 30 giorni le banche d'affari hanno alzato (upgrade ↑) o abbassato (downgrade ↓) il giudizio sul titolo.",
  epsRev30: "Di quanto è cambiata in 30 giorni la stima media degli utili del prossimo anno. Positivo = gli analisti sono diventati più ottimisti.",
  rsi: "RSI a 14 giorni, da 0 a 100: misura la forza dei movimenti recenti. Sopra 70 = ipercomprato (salito molto e in fretta), sotto 30 = ipervenduto.",
  vsSma20: "Distanza del prezzo dalla media degli ultimi 20 giorni (trend di breve). Positivo = il prezzo è sopra la media.",
  vsSma40: "Distanza del prezzo dalla media degli ultimi 40 giorni (trend di breve-medio periodo).",
  vsSma60: "Distanza del prezzo dalla media degli ultimi 60 giorni (trend di medio periodo).",
  vsSma50: "Distanza del prezzo dalla media degli ultimi 50 giorni (trend di medio periodo, molto seguita).",
  vsSma200: "Distanza del prezzo dalla media degli ultimi 200 giorni (trend di lungo periodo). Sotto la 200 molti considerano il titolo in fase debole.",
  range52: "Dove si trova il prezzo tra il minimo (a sinistra) e il massimo (a destra) delle ultime 52 settimane.",
  fromHi52: "Di quanto il prezzo è sotto il massimo delle ultime 52 settimane.",
  fromLo52: "Di quanto il prezzo è sopra il minimo delle ultime 52 settimane.",
  gapPct: "Differenza tra il prezzo di apertura di oggi e la chiusura di ieri: spesso nasce da notizie uscite a mercato chiuso.",
  vol20: "Volatilità: quanto oscilla il prezzo, misurata sugli ultimi 20 giorni e riportata su base annua. Più alta = più rischio.",
  short: "Quota delle azioni vendute allo scoperto, cioè da chi scommette sul ribasso. Oltre il 10% indica molto pessimismo.",
  maOrder: "Ordine delle medie: rialzista se prezzo > media 20 > 40 > 60, ribassista se al contrario, misto negli altri casi.",
  earnings: "Data della prossima presentazione dei conti trimestrali.",
  news: "Ultima notizia che nomina la società, tra quelle scaricate dal server.",
  perf1W: "Variazione del prezzo nell'ultima settimana.", perf1M: "Variazione del prezzo nell'ultimo mese.",
  perf3M: "Variazione del prezzo negli ultimi 3 mesi.", perf6M: "Variazione del prezzo negli ultimi 6 mesi.",
  perfYTD: "Variazione del prezzo da inizio anno.", perf1Y: "Variazione del prezzo nell'ultimo anno.",
};
const colHead = k => `${esc(C[k].l)}${COL_INFO[k] ? " " + info(COL_INFO[k]) : ""}`;
const COLSETS = {
  overview: ["star", "ticker", "name", "sector", "industry", "mcap", "weight", "price", "chgPct", "signal", "trend", "volume", "relVol", "d30"],
  performance: ["star", "ticker", "name", "price", "chgPct", "perf1W", "perf1M", "perf3M", "perf6M", "perfYTD", "perf1Y", "vol20", "d30"],
  valuation: ["star", "ticker", "name", "mcap", "signal", "valLabel", "pe", "fpe", "ps", "evEbitda", "peg", "divYield", "revGrowth", "margin", "target", "upside", "rec", "anl30", "epsRev30"],
  technical: ["star", "ticker", "name", "price", "chgPct", "trend", "signal", "rsi", "vsSma20", "vsSma40", "vsSma60", "vsSma50", "vsSma200", "range52", "fromHi52", "fromLo52", "gapPct", "relVol", "short"],
};

// column priorities (see styles.css): p15 hidden below 1500 px, p2 below 1100, p3 below 860, p4 below 640 (phones);
// no letter = always shown. Hidden columns stay in the CSV export and in the stock's panel.
const COL_PRIO = {
  overview: { name: "p4", sector: "p3", industry: "p15", mcap: "p2", weight: "p3", price: "p4", trend: "p2", volume: "p15", relVol: "p3", d30: "p15" },
  performance: { name: "p3", price: "p4", perf1W: "p3", perf3M: "p2", perf6M: "p2", perf1Y: "p3", vol20: "p15", d30: "p15" },
  valuation: { name: "p3", mcap: "p15", pe: "p2", fpe: "p3", ps: "p15", evEbitda: "p15", peg: "p15", divYield: "p15", revGrowth: "p2",
    margin: "p15", target: "p15", upside: "p3", rec: "p2", anl30: "p15", epsRev30: "p15" },
  technical: { name: "p3", price: "p4", trend: "p2", signal: "p3", rsi: "p2", vsSma20: "p15", vsSma40: "p15", vsSma60: "p15", vsSma50: "p2",
    range52: "p15", fromHi52: "p3", fromLo52: "p15", gapPct: "p15", relVol: "p15", short: "p15" },
  my: { name: "p3", price: "p4", perf1M: "p2", perfYTD: "p3", vsSma20: "p15", vsSma40: "p15", vsSma60: "p15", vsSma200: "p2", maOrder: "p15",
    valLabel: "p3", upside: "p15", trend: "p2", earnings: "p2", news: "p3" },
};
// two filters that add up (with each other, the sector, the quick filters and the search): Trend and «Ha senso comprare?»
// Tendenza: the arrows of the stock's Analisi box (technical.trends, closed sessions): ▲ above +1% / +2% / +4% over 1 week /
// 1 month / 3 months, ▼ below the same thresholds in negative, = in between. One period at a time, as in the box.
const SCR_NONE = "non calcolabile";
const SCR_PERIODS = [[5, "1 settimana"], [21, "1 mese"], [63, "3 mesi"]], SCR_ARROWS = [["▲", "in salita"], ["=", "laterale"], ["▼", "in discesa"]];
const SCR_TRENDS = SCR_PERIODS.flatMap(([d]) => SCR_ARROWS.map(([a]) => `${d}:${a}`));
const scrHasTrend = (s, v) => { const [d, a] = v.split(":"); return (s.trends || []).some(t => String(t.days) === d && t.arrow === a); };
// «Ha senso comprare?»: the buy verdict of the Decisione sheet grouped by the rule that decided it (server.BUY_GROUPS)
const SCR_BUY = ["Entra ora", "Entra su ritracciamento", "Attendi: trimestrale in arrivo", "Attendi: sotto la media 200",
  "Attendi: a ridosso del massimo", "Attendi: dati insufficienti", "Evita"];
const scrBuy = s => !state.buyV ? null : state.buyV.verdicts[s.ticker]?.group || SCR_NONE;
const scrOkT = (s, v = state.ft) => !v || scrHasTrend(s, v);
const scrOkB = (s, v = state.fb) => !v || !state.buyV || scrBuy(s) === v;     // verdicts still loading: nothing hidden
let scrBuyAsked = null;                                          // asOf of the snapshot whose verdicts were asked (one request each)
async function loadBuyVerdicts() {
  const at = state.snap?.asOf;
  if (!at || state.buyV?.asOf === at || scrBuyAsked === at) return;
  scrBuyAsked = at;
  try { const d = await getJSON("/api/stocks/buy"); if (d.verdicts) state.buyV = d; } catch { scrBuyAsked = null; }   // retried at the next render
  if (state.view === "screener") renderScreener();
}
function screenerRows() {
  const p = PRESETS.find(x => x.id === state.preset) || PRESETS[0];
  const q = $("#scrFind").value.trim().toLowerCase();
  const col = C[state.sort.key] || C.mcap;
  return stocks().filter(p.f)
    .filter(s => !state.sector || s.sector === state.sector)
    .filter(s => scrOkT(s) && scrOkB(s))
    .filter(s => !q || s.ticker.toLowerCase().includes(q) || s.name.toLowerCase().includes(q) || s.industry.toLowerCase().includes(q))
    .sort((a, b) => {
      const va = col.sort(a), vb = col.sort(b);
      if (va == null && vb == null) return 0;
      if (va == null) return 1;
      if (vb == null) return -1;
      return (typeof va === "string" ? va.localeCompare(vb) : va - vb) * state.sort.dir;
    });
}

function renderScreener() {
  const S = stocks();
  $$("#colSeg button").forEach(b => b.classList.toggle("on", b.dataset.cols === state.cols));
  const sel = $("#sectorSel");
  const secs = [...new Set(S.map(s => s.sector))].sort();
  if (sel.options.length !== secs.length + 1) sel.innerHTML = `<option value="">Tutti i settori</option>` + secs.map(s => `<option>${esc(s)}</option>`).join("");
  sel.value = state.sector;
  loadBuyVerdicts();
  const base = stocks().filter(s => !state.sector || s.sector === state.sector);            // counts: same sector, the other filter
  const nT = v => base.filter(s => scrHasTrend(s, v) && scrOkB(s)).length;
  const trendSel = `<label class="cat-f"><span>Tendenza ${info(SCR_TREND_INFO)}</span><select id="scrTrendSel" data-scrf="ft"><option value="">tutte</option>
    ${SCR_PERIODS.map(([d, pl]) => `<optgroup label="${pl}">${SCR_ARROWS.map(([a, al]) => `<option value="${d}:${a}" ${state.ft === `${d}:${a}` ? "selected" : ""}>${pl}: ${a} ${al} (${nT(`${d}:${a}`)})</option>`).join("")}</optgroup>`).join("")}</select></label>`;
  const known = !!state.buyV, nB = v => base.filter(s => scrBuy(s) === v && scrOkT(s)).length;
  const buyVals = SCR_BUY.concat(known && base.some(s => !SCR_BUY.includes(scrBuy(s))) ? [SCR_NONE] : []);
  const buySel = `<label class="cat-f"><span>Ha senso comprare? <span class="muted">${known ? "(solo mercato)" : "(in calcolo…)"}</span> ${info(SCR_BUY_INFO)}</span><select id="scrBuySel" data-scrf="fb"><option value="">tutti</option>
    ${buyVals.map(v => `<option value="${esc(v)}" ${state.fb === v ? "selected" : ""}>${esc(v)}${known ? ` (${nB(v)})` : ""}</option>`).join("")}</select></label>`;
  $("#scrFilters").innerHTML = `${trendSel}${buySel}${state.ft || state.fb ? `<button class="link-btn" data-scrclear>Togli i filtri</button>` : ""}`;
  const chip = p => `<button data-p="${p.id}" class="${p.id === state.preset ? "on" : ""}">${esc(p.label)}<span>${S.filter(p.f).length}</span>${info(PRESET_INFO[p.id])}</button>`;
  $("#presets").innerHTML = PRESET_GROUPS.map(g => `<div class="chip-row"><span class="chip-g">${esc(g.label)}</span>${g.ids.map(id => chip(PRESETS.find(p => p.id === id))).join("")}</div>`).join("");
  const rows = screenerRows();
  const cols = COLSETS[state.cols], pr = COL_PRIO[state.cols] || {};
  $("#scrCount").textContent = `${rows.length} di ${S.length}`;
  $("#scr").innerHTML = `<thead><tr>${cols.map(k => `<th class="${C[k].cls?.split(" ")[0] || ""} ${pr[k] || ""} ${state.sort.key === k ? "sorted" + (state.sort.dir > 0 ? " asc" : "") : ""}" data-k="${k}">${colHead(k)}</th>`).join("")}</tr></thead>
    <tbody>${rows.map(s => `<tr data-t="${esc(s.ticker)}">${cols.map(k => `<td class="${C[k].cls || ""} ${pr[k] || ""}">${C[k].html(s)}</td>`).join("")}</tr>`).join("")}</tbody>`;
  if (!rows.length) $("#scr").insertAdjacentHTML("beforeend", `<tbody><tr><td colspan="${cols.length}" class="empty">Nessun titolo corrisponde ai filtri${state.ft || state.fb ? ` <button class="link-btn" data-scrclear>Togli i filtri</button>` : ""}</td></tr></tbody>`);
}
const SCR_TREND_INFO = `<b>Tendenza</b>: le stesse frecce del riquadro Analisi di ogni titolo, sulle sedute chiuse. <b>▲ in salita</b> se il prezzo è salito più
  dell'1% in 1 settimana, del 2% in 1 mese o del 4% in 3 mesi; <b>▼ in discesa</b> se è sceso oltre le stesse soglie; <b>= laterale</b> in mezzo. Scegli un periodo alla volta.
  Descrive l'andamento, non è un voto. La colonna «Trend» della tabella è un'altra cosa: il punteggio da −100 a +100.`;
const SCR_BUY_INFO = `<b>Ha senso comprare?</b> È il verdetto di acquisto della sezione Decisione di ogni titolo, con le stesse regole e la stessa
  parola: decide la prima regola non soddisfatta. D1 azienda e valutazione deboli → <b>Evita</b>; D2 trimestrale entro 5 giorni → <b>Attendi: trimestrale in arrivo</b>;
  D4 prezzo sotto la media 200 → <b>Attendi: sotto la media 200</b>; D5 titolo tirato o D7 azienda nella media → <b>Entra su ritracciamento</b>;
  D6 a meno del 3% dal massimo a 52 settimane → <b>Attendi: a ridosso del massimo</b>; tutte soddisfatte → <b>Entra ora</b>. Calcolato <b>solo sul mercato</b>,
  senza il tuo portafoglio: per un titolo che possiedi la scheda mostra invece il livello della posizione. Regole esplicite ma <b>non verificate</b>; non è una consulenza finanziaria.`;
document.addEventListener("change", e => {
  const f = e.target.closest("[data-scrf]");
  if (f) { const k = f.dataset.scrf; state[k] = f.value; LS.set(k === "ft" ? "scrTrend2" : "scrBuy2", f.value); renderScreener(); }
});
document.addEventListener("click", e => {
  if (e.target.closest("[data-scrclear]")) { state.ft = state.fb = ""; LS.set("scrTrend2", ""); LS.set("scrBuy2", ""); renderScreener(); }
});
$("#colSeg").addEventListener("click", e => { const b = e.target.closest("[data-cols]"); if (b) { state.cols = b.dataset.cols; LS.set("cols", state.cols); renderScreener(); } });
// clicking the active filter again switches it off (back to "Tutti")
$("#presets").addEventListener("click", e => {
  const b = e.target.closest("[data-p]");
  if (!b) return;
  state.preset = state.preset === b.dataset.p ? "all" : b.dataset.p;
  renderScreener();
});
$("#sectorSel").addEventListener("change", e => { state.sector = e.target.value; renderScreener(); });
$("#scrFind").addEventListener("input", () => renderScreener());
$("#scr").addEventListener("click", e => {
  const th = e.target.closest("th[data-k]");
  if (th) {
    const k = th.dataset.k; if (C[k].nosort) return;
    state.sort = state.sort.key === k ? { key: k, dir: -state.sort.dir } : { key: k, dir: ["ticker", "name", "sector", "industry", "rec"].includes(k) ? 1 : -1 };
    return renderScreener();
  }
  const tr = e.target.closest("tr[data-t]");
  if (tr && !e.target.closest(".star")) openDetail(tr.dataset.t);
});
$("#csvBtn").addEventListener("click", () => {
  const keys = ["ticker", "name", "sector", "industry", "price", "chgPct", "mcap", "weight", "volume", "relVol", "perf1W", "perf1M", "perf3M", "perf6M", "perfYTD", "perf1Y",
    "signal", "sigScore", "trend", "pe", "fpe", "ps", "evEbitda", "peg", "valLabel", "divYield", "beta", "target", "upside", "up30", "down30", "epsRev30", "rsi", "vsSma20", "vsSma40", "vsSma60", "vsSma50", "vsSma200", "hi52", "lo52", "fromHi52"];
  const q = v => v == null ? "" : typeof v === "string" ? `"${v.replace(/"/g, '""')}"` : +v.toFixed(4);
  const csv = [keys.join(","), ...screenerRows().map(s => keys.map(k => q(s[k])).join(","))].join("\n");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
  a.download = `nasdaq100_${state.snap.session}.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
});

// ------------------------------------------------------------ sectors view
// no sector selected = all sectors (only the weights chart); a selected sector also lists its stocks
function renderSectors() {
  const secs = sectors();
  if (state.secSel && !secs.some(s => s.name === state.secSel)) state.secSel = null;
  const tfs = PERF_TFS;
  // a light tint that grows with the size of the move; the number keeps its sign
  const heatBg = (tf, v) => !isNum(v) || zero(v, 2) ? "transparent"
    : `color-mix(in srgb, var(${v > 0 ? "--pos" : "--neg"}) ${Math.round(6 + 30 * Math.min(1, Math.abs(v) / METRICS[tf].dom[2]))}%, var(--surface))`;
  const total = d3.sum(secs, s => s.weight) || 100;   // ≈ 100
  const maxW = d3.max(secs, s => s.weight / total);
  $("#matrix").innerHTML = `<thead><tr><th class="l">Settore</th><th>Titoli</th><th class="l">Peso</th>${tfs.map(tf => `<th>${METRICS[tf].label}</th>`).join("")}<th>Rialzo / Ribasso</th></tr></thead>
    <tbody>${secs.map(s => {
      const w = s.weight / total * 100;
      const adv = s.list.filter(x => x.chgPct > 0).length;
      return `<tr data-sec="${esc(s.name)}" class="${s.name === state.secSel ? "sel" : ""}"><td class="l"><b>${esc(s.name)}</b></td><td>${s.n}</td>
        <td class="l"><span class="wbar" style="width:${(w / (maxW * 100) * 90).toFixed(0)}px"></span>${fNum(w, 1)}%</td>
        ${tfs.map(tf => `<td class="heat" style="background:${heatBg(tf, s[tf])}">${fPct(s[tf])}</td>`).join("")}
        <td><span class="up">${adv}</span> / <span class="down">${s.list.filter(x => x.chgPct < 0).length}</span></td></tr>`;
    }).join("")}</tbody>`;
  const sec = secs.find(s => s.name === state.secSel);
  $("#secAll").hidden = $("#secStocks").hidden = !sec;
  $("#secDetail").classList.toggle("one", !sec);
  const wr = secs.map(s => ({ name: s.name, v: s.weight / total * 100, label: fNum(s.weight / total * 100, 1) + "%", color: css(s.name === state.secSel ? "--series-2" : "--series-1"), s }));
  hbars($("#weights"), wr, { nameW: 170, rowH: 26, click: r => { state.secSel = state.secSel === r.name ? null : r.name; renderSectors(); },
    tip: r => `<div class="tip-h">${esc(r.name)}</div><div class="tip-row"><span>Capitalizzazione</span><b>$${fBig(r.s.mcap)}</b></div><div class="tip-row"><span>I più grandi</span><b>${esc([...r.s.list].sort((a, b) => b.mcap - a.mcap).slice(0, 3).map(x => x.ticker).join(", "))}</b></div>` });
  if (!sec) return;
  const tf = PERF_TFS.includes(state.tf) ? state.tf : "1D";
  $("#secTitle").textContent = `${sec.name} · ${METRICS[tf].label}`;
  const rows = sec.list.filter(s => isNum(val(s, tf))).sort((a, b) => val(b, tf) - val(a, tf))
    .map(s => ({ name: s.ticker, v: val(s, tf), label: fMetric(tf, val(s, tf)), s }));
  hbars($("#secBars"), rows, { rowH: 22, click: r => openDetail(r.s.ticker),
    tip: r => `<div class="tip-h">${esc(r.s.industry)}</div><b>${esc(r.s.name)}</b><div class="tip-row"><span>${METRICS[tf].label}</span><b class="${sign(r.v)}">${r.label}</b></div><div class="tip-row"><span>Peso</span><b>${fW(r.s)}</b></div>` });
}
// a row shows that sector's stocks; the same row again (or "Tutti i settori") goes back to all sectors
$("#matrix").addEventListener("click", e => {
  const tr = e.target.closest("tr[data-sec]");
  if (!tr) return;
  state.secSel = state.secSel === tr.dataset.sec ? null : tr.dataset.sec;   // same row again = back to all sectors
  renderSectors();
});
$("#secAll").addEventListener("click", () => { state.secSel = null; renderSectors(); });

// ------------------------------------------------------------ detail drawer
const drawer = $("#drawer"), scrim = $("#scrim");
let dRange = "1D", dCompare = false, dInfo = null, dReq = 0;
// moving averages drawn on the detail chart (daily closes, computed here only for display)
const MAS = [{ n: 20, color: "--series-1" }, { n: 40, color: "--series-2" }, { n: 60, color: "--series-3" }, { n: 200, color: "--series-4" }];
const MA_RANGES = ["1M", "6M", "YTD", "1Y"];
const dMA = new Set(LS.get("dMA", [20, 40, 60, 200]));
let dDaily = null;   // { t, pts } two years of daily closes for the open stock
let dFull = LS.get("dFull", false);
let dNews = [];   // headlines of the open stock (from /api/stock)   // detail as side panel (false) or full screen (true), remembered

function openDetail(t) {
  state.detail = t; state.macro = null; state.panel = null; dInfo = null; dDaily = null; dRange = "1D";
  drawer.innerHTML = `<div class="d-top"></div><div class="d-sum"></div><div class="d-ctrl"></div><div id="dChart" class="chart"></div><div id="dVol" class="chart"></div><div class="d-rest"><div class="loading" style="padding:40px"><div class="spinner"></div></div></div>`;
  drawer.classList.add("open"); drawer.classList.toggle("full", dFull); drawer.setAttribute("aria-hidden", "false"); scrim.hidden = false;
  renderDetailHeader();
  renderDetailCtrl();
  loadDetailChart();
  loadDetailInfo();
}
function closeDetail() {
  state.detail = null; state.macro = null; state.panel = null; drawer.classList.remove("open"); drawer.setAttribute("aria-hidden", "true"); scrim.hidden = true; hideTip();
}
scrim.addEventListener("click", closeDetail);

function quoteFor(t) {
  return state.bySym.get(t) || state.snap.indices[t] || pfQuote(t) || null;
}
function renderDetailHeader() {
  const t = state.detail, s = quoteFor(t), top = drawer.querySelector(".d-top");
  if (!top) return;
  const name = s?.name || s?.label || dInfo?.longName || t;
  top.innerHTML = `<div class="d-head"><div><div class="tt">${esc(t)}</div><div class="nm">${esc(dInfo?.longName || name)}</div>
      ${s?.sector ? `<div class="sec">${esc(s.sector)} › ${esc(s.industry)} · capitalizzazione $${fBig(s.mcap)} · ${fW(s)} dell'indice</div>` : ""}</div>
      <div class="actions">${state.bySym.has(t) ? `<button class="icon-btn star ${state.watch.has(t) ? "on" : ""}" data-star="${esc(t)}" title="${state.watch.has(t) ? "Togli dai Preferiti" : "Aggiungi ai Preferiti"}" aria-label="${state.watch.has(t) ? "Togli dai Preferiti" : "Aggiungi ai Preferiti"}" aria-pressed="${state.watch.has(t)}">${state.watch.has(t) ? "★" : "☆"}</button>` : ""}
      <button class="icon-btn" id="dFull" title="${dFull ? "Torna al pannello laterale" : "Apri a schermo intero"}" aria-label="${dFull ? "Pannello laterale" : "Schermo intero"}">${dFull ? "⤡" : "⤢"}</button>
      <button class="icon-btn close-btn" id="dClose" aria-label="Chiudi">×</button></div></div>
    ${s ? `<div class="d-price"><span class="p num">${fPrice(s.price)}</span><span class="c ${sign(s.chg)}">${fChg(s.chg)} (${fPct(s.chgPct)})</span>
      <span class="when">${state.snap.status === "open" ? "in tempo reale · " : "ultimo · "}${esc(new Date(state.snap.lastQuote || state.snap.asOf).toLocaleTimeString("it-IT", { timeZone: tz, hour: "numeric", minute: "2-digit" }))} ora NY
        (${fLocal(state.snap.lastQuote || state.snap.asOf)} ora locale)</span>
      ${earnBadge(s)}</div>${maRow(s)}` : ""}`;
  $("#dClose").onclick = closeDetail;
  $("#dFull").onclick = toggleFull;
}
// switch side panel <-> full screen; charts are redrawn at the new width
function toggleFull() {
  dFull = !dFull; LS.set("dFull", dFull);
  drawer.classList.toggle("full", dFull);
  renderDetailHeader();
  loadDetailChart();
}
// "Trimestrale 23 ott · tra 25 giorni" (only for a future date)
function earnBadge(s) {
  const d = daysTo(s.earningsTs);
  if (d == null) return "";
  const n = Math.round(d);
  return `<span class="d-earn">Trimestrale ${fDate(s.earningsTs, { day: "numeric", month: "short" })} · ${n <= 0 ? "oggi" : n === 1 ? "domani" : `tra ${n} giorni`}</span>`;
}
// price above/below the 20/40/60/200-day averages, same values as the Trend section
function maRow(s) {
  if (!s.ticker) return "";
  const cell = n => { const v = s["vsSma" + n];
    return `<span>Media ${n} <b class="${sign(v)}">${isNum(v) ? (v >= 0 ? "▲ " : "▼ ") + fPct(v, 1) : "—"}</b></span>`; };
  return `<div class="d-ma">${[20, 40, 60, 200].map(cell).join("")}</div>`;
}
function renderDetailCtrl() {
  const el = drawer.querySelector(".d-ctrl");
  const maOk = MA_RANGES.includes(dRange) && !dCompare;
  const maNote = dCompare ? "medie nascoste durante il confronto" : maOk ? "" : "medie visibili su 1M, 6M, YTD e 1A";
  el.innerHTML = `<div class="seg">${["1D", "5D", "1M", "6M", "YTD", "1Y", "5Y", "MAX"].map(r => `<button data-r="${r}" class="${r === dRange ? "on" : ""}">${RLAB[r] || r}</button>`).join("")}</div>
    ${state.detail !== "^NDX" ? `<label class="check"><input type="checkbox" id="dCmp" ${dCompare ? "checked" : ""}> Confronta con il Nasdaq-100</label>` : ""}
    <div class="ma-toggles${maOk ? "" : " off"}"><span class="muted">Medie mobili</span>${MAS.map(m => `<label class="check"><input type="checkbox" data-ma="${m.n}" ${dMA.has(m.n) ? "checked" : ""} ${maOk ? "" : "disabled"}><i class="${m.n === 200 ? "dash" : ""}" style="background:var(${m.color});color:var(${m.color})"></i>${m.n}</label>`).join("")}
      ${maNote ? `<span class="muted small">${maNote}</span>` : ""}</div>`;
  el.onclick = e => { const b = e.target.closest("[data-r]"); if (b) { dRange = b.dataset.r; renderDetailCtrl(); loadDetailChart(); } };
  el.onchange = e => {
    if (e.target.id === "dCmp") { dCompare = e.target.checked; renderDetailCtrl(); return loadDetailChart(); }
    const n = +e.target.dataset.ma;
    if (!n) return;
    e.target.checked ? dMA.add(n) : dMA.delete(n);
    LS.set("dMA", [...dMA]);
    loadDetailChart();
  };
}
// simple moving averages of the daily closes, aligned to the chart points (each point takes the value of its trading day)
async function maSeries(t, pts) {
  const on = MAS.filter(m => dMA.has(m.n));
  if (!on.length) return [];
  if (!dDaily || dDaily.t !== t) dDaily = { t, pts: (await getJSON(`/api/history/${encodeURIComponent(t)}/2Y`)).filter(p => isNum(p.c)) };
  const D = dDaily.pts;
  return on.map(m => {
    let sum = 0;
    const sma = D.map((p, i) => { sum += p.c; if (i >= m.n) sum -= D[i - m.n].c; return i >= m.n - 1 ? sum / m.n : null; });
    let j = -1;
    return { n: m.n, color: css(m.color), width: m.n === 200 ? 2.2 : 1.4, dash: m.n === 200 ? "6 4" : null, dot: false,
      pts: pts.map(p => { while (j + 1 < D.length && D[j + 1].t <= p.t) j++; return { t: p.t, v: j >= 0 ? sma[j] : null }; }) };
  });
}
const getJSON = async u => { const r = await fetch(u); if (!r.ok) throw new Error(r.statusText); return r.json(); };

async function loadDetailChart() {
  const t = state.detail, req = ++dReq, rng = dRange;
  const chartEl = $("#dChart"), volEl = $("#dVol");
  chartEl.innerHTML = `<div class="empty" style="height:260px">Caricamento grafico…</div>`; volEl.innerHTML = "";
  try {
    const [h, bench] = await Promise.all([
      getJSON(`/api/history/${encodeURIComponent(t)}/${rng}`),
      dCompare && t !== "^NDX" ? getJSON(`/api/history/${encodeURIComponent("^NDX")}/${rng}`) : null,
    ]);
    if (req !== dReq || state.detail !== t) return;
    const pts = h.filter(p => isNum(p.c)).map(p => ({ t: p.t, v: p.c, o: p.o, h: p.h, l: p.l, vol: p.v }));
    if (!pts.length) { chartEl.innerHTML = `<div class="empty">Nessuno storico dei prezzi</div>`; return; }
    const q = quoteFor(t);
    const base = rng === "1D" && q?.prevClose ? q.prevClose : pts[0].v;
    let chart;
    const tipFor = i => {
      const p = pts[i], chg = (p.v / base - 1) * 100;
      const when = ["1D", "5D", "1M"].includes(rng) ? `${fDate(p.t, { weekday: "short", month: "short", day: "numeric" })} ${fTime(p.t)}` : fDate(p.t, { month: "short", day: "numeric", year: "numeric" });
      let html = `<div class="tip-h">${when}</div>`;
      if (bnPts) {
        html += `<div class="tip-row"><span><i class="swatch" style="background:${css("--series-1")}"></i>${esc(t)}</span><b class="${sign(sPts[i].v - 100)}">${fPct(sPts[i].v - 100)}</b></div>
                 <div class="tip-row"><span><i class="swatch" style="background:${css("--series-2")}"></i>Nasdaq-100</span><b class="${sign(bnPts[i].v - 100)}">${isNum(bnPts[i].v) ? fPct(bnPts[i].v - 100) : "—"}</b></div>`;
      } else {
        html += `<div class="tip-row"><span>Chiusura</span><b class="num">${fPrice(p.v)}</b></div>
          <div class="tip-row"><span>Ap. / Max / Min</span><span class="num">${fPrice(p.o)} / ${fPrice(p.h)} / ${fPrice(p.l)}</span></div>
          <div class="tip-row"><span>Variazione</span><b class="${sign(chg)}">${fPct(chg)}</b></div>`;
        html += mas.map(m => `<div class="tip-row"><span><i class="swatch" style="background:${m.color}"></i>Media ${m.n}</span><span class="num">${fPrice(m.pts[i].v)}</span></div>`).join("");
      }
      return html + (isNum(p.vol) && p.vol > 0 ? `<div class="tip-row"><span>Volume</span><span class="num">${fBig(p.vol)}</span></div>` : "");
    };
    let sPts = null, bnPts = null, mas = [];
    if (bench && bench.length) {
      // align benchmark to stock timestamps (last benchmark value at or before each point)
      const B = bench.filter(p => isNum(p.c));
      let j = 0, last = null;
      const aligned = pts.map(p => { while (j < B.length && B[j].t <= p.t + 60) { last = B[j].c; j++; } return last; });
      const b0 = aligned.find(isNum);
      sPts = pts.map(p => ({ t: p.t, v: p.v / pts[0].v * 100 }));
      bnPts = pts.map((p, i) => ({ t: p.t, v: isNum(aligned[i]) ? aligned[i] / b0 * 100 : null }));
      chart = lineChart(chartEl, [{ pts: sPts, color: css("--series-1") }, { pts: bnPts, color: css("--series-2") }], {
        height: 280, baseline: 100, range: rng, pctAxis: true, yFmt: v => (v - 100 > 0 ? "+" : "") + (v - 100).toFixed(0) + "%", tip: tipFor, label: `${t} vs Nasdaq-100`,
      });
      chartEl.insertAdjacentHTML("afterbegin", `<div class="series-key"><span><i style="background:${css("--series-1")}"></i>${esc(t)} ${fPct(sPts.at(-1).v - 100)}</span><span><i style="background:${css("--series-2")}"></i>Nasdaq-100 ${fPct((bnPts.at(-1).v ?? 100) - 100)}</span></div>`);
    } else {
      const col = pts.at(-1).v >= base ? css("--up") : css("--down");
      if (MA_RANGES.includes(rng)) {
        try { mas = await maSeries(t, pts); } catch { mas = []; }   // chart still works without the averages
        if (req !== dReq || state.detail !== t) return;
      }
      // with averages on top the price is drawn in a neutral colour (black / white in dark theme), without the area
      chart = lineChart(chartEl, [{ pts, color: mas.length ? css("--ink") : col, width: mas.length ? 1.8 : 2 }, ...mas], {
        height: 280, baseline: rng === "1D" ? base : null, baselineLabel: rng === "1D" ? `Chiusura prec. ${fPrice(base)}` : "", range: rng, tip: tipFor, label: `${t} price`,
      });
      if (mas.length) chartEl.insertAdjacentHTML("afterbegin", `<div class="series-key">${mas.map(m => {
        const v = m.pts.at(-1).v, d = isNum(v) ? (pts.at(-1).v / v - 1) * 100 : null;
        return `<span><i class="${m.dash ? "dash" : ""}" style="background:${m.color};color:${m.color}"></i>Media ${m.n} ${fPrice(v)} <b class="${sign(d)}">${isNum(d) ? `prezzo ${fPct(d, 1)}` : ""}</b></span>`; }).join("")}</div>`);
    }
    // volume panel (its own axis-free strip, same x positions)
    if (pts.some(p => p.vol > 0)) {
      const W = chartEl.clientWidth, H = 56, { m, iw } = chart;
      const x = d3.scaleBand().domain(d3.range(pts.length)).range([0, iw]).paddingInner(pts.length > 120 ? 0 : 0.2);
      const y = d3.scaleLinear().domain([0, d3.max(pts, p => p.vol) || 1]).range([H - 6, 0]);
      const svg = d3.select(volEl).append("svg").attr("width", W).attr("height", H).attr("aria-label", "Volume");
      const g = svg.append("g").attr("transform", `translate(${m.l},2)`);
      const off = x.bandwidth() / 2;
      g.selectAll("rect").data(pts).join("rect").attr("x", (_, i) => chart.x(i) - off).attr("width", Math.max(1, x.bandwidth()))
        .attr("y", p => y(p.vol || 0)).attr("height", p => H - 6 - y(p.vol || 0))
        .attr("fill", (p, i) => (i ? p.v >= pts[i - 1].v : p.v >= base) ? css("--up") : css("--down")).attr("opacity", 0.45);
      g.append("text").attr("class", "ref-label").attr("x", iw + 6).attr("y", 10).text("Vol");
    }
  } catch (e) {
    if (req === dReq) chartEl.innerHTML = `<div class="empty">Grafico non disponibile (${esc(e.message)})</div>`;
  }
}

// ------------------------------------------------------------ detail: Decisione (index stocks only)
// The sheet an analyst would bring to the investment committee, in five blocks read in order (decision.py computes
// everything, also for the signal diary; this code only shows it). Rules of the dashboard: every indication shows the
// rules that produced it; only patterns that passed the test can be called "verificato"; nothing is a recommendation.
const dTA = { t: null, ta: null, D: null, fx: null, trend: "", sel: {} };
const fUsd = v => isNum(v) ? fNum(v, 2) + " $" : "—";
const DEC_INFO = `La scheda che un analista porta al comitato d'investimento, in cinque blocchi da leggere in ordine.
  <b>L'azienda e la valutazione decidono SE comprare, il tempismo tecnico decide QUANDO e A CHE PREZZO, il portafoglio decide QUANTO.</b><br><br>
  Il verdetto finale esce da regole esplicite, elencate sotto con ✅ e ❌. Queste regole <b>non sono verificate da un backtest</b>
  (analisti e fondamentali non hanno uno storico gratuito): il Diario dei segnali le misura da oggi in avanti. Non è una consulenza finanziaria.`;
const TA_PLAN_INFO = `Questi livelli servono a <b>decidere in anticipo quanto rischi</b>, non a prevedere il prezzo.<br><br>
  <b>Stop</b>: il prezzo sotto il quale esci. Si appoggia a un livello oggettivo (media a 50 giorni, ultimo minimo) oppure alla volatilità.<br>
  <b>ATR</b>: di quanto si muove in media il titolo in un giorno (ultime 14 sedute).<br>
  <b>Target</b>: convenzionale, a 2 volte il rischio. Non è una previsione.<br>
  <b>Quante azioni</b>: il numero con cui, se scatta lo stop, perdi al massimo il rischio per operazione delle tue regole, senza superare lo spazio che le tue regole lasciano
  (titolo, tema, settore, paese). Lo stop non garantisce il prezzo di uscita: con un'apertura in forte ribasso la perdita può essere maggiore.`;
const TA_WAIT_INFO = `Un ordine condizionato compra solo se il prezzo supera un livello. Qui il livello è la resistenza più un
  <b>margine di un quarto di ATR</b> (l'ATR è il movimento medio di un giorno): serve a non far scattare l'ordine per un superamento di pochi centesimi.<br><br>
  Lo stop è un ATR sotto il livello rotto: se il prezzo torna sotto, la rottura è fallita.`;
const VERDICT_CLS = { "Entra ora": "acc", "Entra su ritracciamento": "wait", "Entra su rottura": "wait", "Attendi": "hold", "Evita": "red",
  "Rivedi la tesi": "rev", "Valuta la vendita": "red", "Attenzione": "rev", "Accumula": "acc", "Mantieni": "hold" };
const verdictBadge = v => `<span class="act big ${VERDICT_CLS[v.category] || "hold"}">${esc(v.label)}</span>`;

// one operating plan computed by the server (entry, stop options, money); the stop can be switched here
function taPlanHTML(id, p) {
  if (!p) return `<p class="muted small">Livelli non calcolabili per questo titolo.</p>`;
  const entry = p.entry, st = p.opts.find(o => o.id === dTA.sel[id]) || p.opts.find(o => o.id === p.def), risk = entry - st.v, target = entry + 2 * risk;
  const pct = v => fPct((v / entry - 1) * 100, 1);
  const res = p.resistance && p.resistance.v < target ? `<div class="ta-note">⚠ Prima del target c'è il massimo a 52 settimane a ${fUsd(p.resistance.v)} (${pct(p.resistance.v)}): fino a lì il rapporto è solo ${fNum((p.resistance.v - entry) / risk, 1)} : 1.</div>` : "";
  const others = p.opts.filter(o => o.id !== st.id);
  let size;              // quantities computed by the server for every stop option, with Fineco's exchange spread (decision.quantity_eur)
  if (!isNum(p.budgetEur)) size = `<span class="muted">inserisci il capitale nel blocco 4</span>`;
  else if (!isNum(st.qty)) size = `<span class="muted">cambio EUR/USD non disponibile</span>`;
  else {
    const n = st.qty, share = v => fNum(v / p.capital * 100, 1);
    size = !n ? `<b>0</b> <span class="muted">con questo capitale e questo rischio non si arriva a un'azione intera</span>`
      : `<b>${fNum(n, 0)}</b> <span class="muted">valore ${fUsd(n * entry)} ≈ ${fEur(st.valueEur, 0)}, ${share(st.valueEur)}% del portafoglio</span>
        <div class="ta-note">Se scatta lo stop perdi circa ${fEur(st.lossEur, 0)} (${share(st.lossEur)}% del portafoglio; il tuo rischio per operazione è ${ruleLimit(p.riskPct)})${p.spread ? ", compreso lo spread di cambio di Fineco" : ""}.</div>`;
  }
  return `<div class="ta-plan">
    <div><span>${p.kind === "breakout" ? "Livello di rottura" : p.kind === "pullback" ? "Ordine limite" : "Entrata"}</span><div><b>${fUsd(entry)}</b> <span class="muted">${esc(p.entryNote)}${p.kind === "pullback" ? ` · ${fPct((entry / dTA.D.price - 1) * 100, 1)} dal prezzo attuale` : ""}</span></div></div>
    <div><span>Stop</span><div><b>${fUsd(st.v)}</b> <span class="down">${pct(st.v)}</span> <span class="muted">${esc(st.label)} · ${fNum(st.atrs, 1)} ATR</span>
      ${st.id === p.def ? `<div class="ta-note">Perché: ${esc(p.why)}</div>` : `<div class="ta-note">Scelto da te al posto di quello proposto.</div>`}
      ${others.length ? `<div class="ta-note">Altre opzioni: ${others.map(o => `<button class="ta-opt" data-ta-stop="${id}:${o.id}">${fUsd(o.v)} (${pct(o.v)}) ${esc(o.label)}${o.id === p.def ? " · proposto" : ""}</button>`).join(" ")}</div>` : ""}</div></div>
    <div><span>Target</span><div><b>${fUsd(target)}</b> <span class="up">${pct(target)}</span> <span class="muted">convenzionale: 2 volte il rischio → rapporto rischio/rendimento 2,0 : 1</span>${res}</div></div>
    <div><span>Quante azioni</span><div>${size}</div></div></div>`;
}
function taBreakoutHTML(k, p) {
  const P = pt.data, t = P?.patterns.find(x => x.key === p.pattern), h = t?.horizons["3M"], price = dTA.D.price;
  const test = !t ? `<b>Pattern non verificato</b>: il test dei pattern non è disponibile.`
    : `<b>${t.favorable ? "Pattern che ha superato il test, con i suoi limiti" : "Pattern non verificato: in passato, in media, non ha dato un vantaggio"}.</b>
      «${esc(t.name)}»: ${fNum(t.n, 0)} casi; a 3 mesi, rispetto agli altri titoli nello stesso giorno, media ${ptPts(h.vsAll)} punti e mediana ${ptPts(h.vsAllMedian)};
      ha battuto QQQ nel ${pctR(h.beat)} dei casi (tutti i titoli: ${pctR(P.all.horizons["3M"].beat)}). Condizioni del test rispettate: ${t.checks.filter(Boolean).length} su 6.
      <b>Non è un consiglio di acquisto.</b>`;
  return `<div class="ta-wait"><p class="warn-box">${test}</p>
    <p>Resistenza: ${esc(p.what)} a <b>${fUsd(p.level)}</b>, ${fPct((p.level / price - 1) * 100, 1)} dal prezzo.<br>
      <b>Livello di rottura: ordine di acquisto condizionato sopra ${fUsd(p.entry)}</b> <span class="muted">(resistenza + un quarto di ATR) ${info(TA_WAIT_INFO)}</span></p>
    ${taPlanHTML("b" + k, p)}
    <p class="muted small">Nota: l'ordine condizionato scatta solo sul prezzo, mentre il pattern richiede anche volumi alti (almeno 1,5 volte la media a 50 giorni) e una chiusura sopra il livello.
      Dopo l'attivazione conviene controllare i volumi.</p></div>`;
}
function taPatterns(D) {
  const T = D.timing;
  if (!T.testAvailable) return `<p class="muted">Test dei pattern non disponibile: dal Terminale <code>.venv/bin/python backtest.py --patterns</code>. Senza test nessun pattern è verificato.</p>`;
  const P = pt.data, when = x => x.date ? `, scattato il ${dayShort(x.date)}` : "";
  const ok = T.patterns.filter(x => x.verified), no = T.patterns.filter(x => !x.verified);
  const say = x => { const p = P?.patterns.find(q => q.key === x.key); return p ? ptSay(p, P) : ""; };
  return `${ok.length ? ok.map(x => `<div class="ta-ok"><b>${esc(x.name)}</b>${when(x)} ${info(PT_INFO[x.key] || "")} <span class="ta-tag ok">verificato</span>
        <div>${say(x)} È un'informazione, non un'indicazione di acquisto.</div></div>`).join("") : `<p><b>Nessun pattern verificato oggi.</b></p>`}
    ${no.length ? `<div class="muted small">Pattern presenti ma non verificati (non hanno superato il test):</div>
      <ul class="ta-list">${no.map(x => `<li>${esc(x.name)}${when(x)} ${info(PT_INFO[x.key] || "")} <span class="ta-tag">non verificato</span></li>`).join("")}</ul>` : ""}
    <p class="muted small">I risultati completi del test dei 9 pattern sono nel README del progetto.</p>`;
}
// fixed phrases chosen from the numbers: stock vs group at 1 and 3 months, and the group's rotation phase vs the Nasdaq-100
function taGroupSay(t, g) {
  const what = g.kind === "sector" ? "settore" : `tema «${esc(g.name)}»`;
  const a = g.vs1m, b = g.vs3m, T = 1;
  const stock = a > T && b > T ? `più forte del suo ${what}` : a < -T && b < -T ? `più debole del suo ${what}`
    : b > T && a < -T ? `davanti al suo ${what} a 3 mesi, ma rimasto indietro nell'ultimo mese`
    : b < -T && a > T ? `indietro rispetto al suo ${what} a 3 mesi, ma in recupero nell'ultimo mese`
    : a < -T ? `rimasto indietro rispetto al suo ${what} nell'ultimo mese (in linea a 3 mesi)`
    : a > T ? `più forte del suo ${what} nell'ultimo mese (in linea a 3 mesi)`
    : b > T ? `davanti al suo ${what} a 3 mesi (in linea nell'ultimo mese)`
    : b < -T ? `indietro rispetto al suo ${what} a 3 mesi (in linea nell'ultimo mese)`
    : `in linea con il suo ${what}`;
  const phase = { Leading: "è più forte del Nasdaq-100 e continua a guadagnare terreno", Improving: "è più debole del Nasdaq-100 ma sta recuperando",
    Weakening: "è più forte del Nasdaq-100 a 1 mese ma sta perdendo terreno", Lagging: "è più debole del Nasdaq-100 e continua a perdere terreno" }[g.quadrant];
  return `${esc(t)} è ${stock}; il ${g.kind === "sector" ? "settore" : "tema"} ${phase}.`;
}
function taGroups(t, groups) {
  if (!groups.length) return `<p class="muted">Settore e tema non disponibili.</p>`;
  const pp = v => `<span class="${sign(v)}">${fChg(v)}</span>`;
  return `<div class="table-wrap"><table class="scr ta-grp"><thead><tr><th class="l">Gruppo</th><th class="l">Fase ${info(`Fase di rotazione rispetto a QQQ, come nella mappa di rotazione in Mercato → Settori:
      <b>Leader</b> = più forte a 1 mese e a 1 settimana; <b>In indebolimento</b> = più forte a 1 mese ma non nell'ultima settimana;
      <b>In miglioramento</b> = più debole a 1 mese ma in recupero nell'ultima settimana; <b>In ritardo</b> = più debole su entrambe.`)}</th>
      <th>Gruppo vs QQQ 1 sett.</th><th>Gruppo vs QQQ 1 mese</th><th>${esc(t)} vs gruppo 1 mese</th><th>${esc(t)} vs gruppo 3 mesi</th></tr></thead>
    <tbody>${groups.map(g => `<tr><td class="l"><b>${esc(g.name)}</b><div class="muted small">${g.kind === "sector" ? "settore" : "tema"} · ${g.n} titoli</div></td>
      <td class="l"><span class="q ${g.quadrant}">${QLAB[g.quadrant]}</span></td><td>${pp(g.rs1w)}</td><td>${pp(g.rs1m)}</td><td>${pp(g.vs1m)}</td><td>${pp(g.vs3m)}</td></tr>`).join("")}</tbody></table></div>
    <p class="ta-say"><b>In sintesi.</b> ${groups.map(g => taGroupSay(t, g)).join(" ")}</p>`;
}
function decCompany(C) {
  const cls = { solida: "acc", "nella media": "hold", debole: "red", "dati insufficienti": "hold" }[C.summary];
  const pts = p => p == null ? `<span class="muted">—</span>` : `<span class="${p > 0 ? "up" : p < 0 ? "down" : "muted"}">${p > 0 ? "+1" : p < 0 ? "−1" : "0"}</span>`;
  return `<p><span class="act big ${cls}">${esc(C.summary)}</span> <span class="muted">${C.score > 0 ? "+" : ""}${C.score} punti su ${C.known} criteri disponibili</span></p>
    <div class="table-wrap"><table class="scr dec-crit"><tbody>${C.criteria.map(c => `<tr><td class="l">${esc(c.label)}</td><td class="l">${esc(c.text)}</td><td>${pts(c.points)}</td></tr>`).join("")}</tbody></table></div>
    <p class="muted small">${esc(C.rule)} Soglie: crescita oltre il 10% (+1) o negativa (−1); margine netto oltre il 15% o sotto il 5%; cassa generata oltre il 10% dei ricavi o negativa;
      debito netto ripagabile in meno di 2 anni di cassa o in più di 5; valutazione Economica o Cara; stime riviste di oltre +2% o −3%; più upgrade o più downgrade.
      Sintesi meccanica di dati pubblici, non verificata da backtest. Il dettaglio di valutazione e analisti è più sotto nella scheda.</p>`;
}
function decContext(t, X) {
  const ev = X.events.map(e => `<button class="link-btn" data-dec-macro="${esc(e.kind)}|${esc(e.date)}">${esc(MACRO[e.kind]?.title || e.kind)} · ${dayShort(e.date)}</button>`);
  const earn = X.earningsDays == null ? "data della prossima trimestrale non nota" : X.earningsDays === 0 ? "<b>trimestrale oggi</b>" : `prossima trimestrale il ${esc(X.earningsDay)} (tra ${X.earningsDays} ${X.earningsDays === 1 ? "giorno" : "giorni"})`;
  return `${taGroups(t, X.groups)}
    <p><b>Trimestrale:</b> ${earn}${X.earningsDays != null && X.earningsDays <= 5 ? ` <span class="ta-tag warn">entro 5 giorni</span>` : ""}<br>
      <b>Eventi macro dei prossimi 7 giorni:</b> ${ev.length ? ev.join(" · ") : `<span class="muted">nessuno</span>`}</p>`;
}
const RISK_FIELD_INFO = `Quanto del portafoglio perdi al massimo se scatta lo stop di un'operazione. Con l'1%, dieci stop di fila costano circa il 10%.
  È l'unica regola rimasta per le quantità (i limiti di peso sono stati tolti): il numero di azioni è quello con cui, se scatta lo stop, perdi questa percentuale.
  Si salva in portafoglio/regole.json, solo su questo Mac.`;
function decPlace(D) {
  const P = D.place;
  const field = `<p class="ta-risk"><label>Rischio massimo per operazione <input type="number" id="taRisk" min="0.1" max="10" step="0.1" value="${P.riskPct}"> % del portafoglio</label>
    ${info(RISK_FIELD_INFO)} · <label>Regolo i titoli USA in <select id="taSettle"><option ${P.settle === "EUR" ? "selected" : ""}>EUR</option><option ${P.settle === "USD" ? "selected" : ""}>USD</option></select></label>
    ${info(AN_SETTLE_INFO)} <span id="taRiskMsg" class="small muted"></span></p>`;
  if (!P.loaded) {
    const manual = +LS.get("taCapital", 0) || "";
    return `<p class="muted">Portafoglio non caricato: non posso dire se lo possiedi.</p>${field}
      <p>Per calcolare le quantità inserisci il capitale: <input type="number" id="taCapital" min="0" step="100" value="${manual}" placeholder="es. 20000"> €
        <span class="muted small">(resta solo nel browser)</span></p>`;
  }
  const o = P.etfOverlap;
  return `<p>${P.owned ? `<b>Lo possiedi già</b>: ${fEur(P.value, 0)}, ${fNum(P.weight, 1)}% del portafoglio.` : "<b>Non lo possiedi</b> direttamente."}
      ${o ? `<br><b>Sovrapposizione con i tuoi ETF sul Nasdaq-100:</b> ne possiedi già circa ${fEur(o.eur, 0)} in modo indiretto (pesa il ${fNum(o.indexWeight, 2)}% dell'indice; ${o.etfs.map(esc).join(", ")}; conta la leva).`
        : `<br><span class="muted">Nessuna sovrapposizione calcolabile: la dashboard conosce la composizione solo degli ETF sul Nasdaq-100.</span>`}</p>
    ${field}
    <p class="muted small">Le quantità del piano vengono solo da questo rischio e dalla distanza tra entrata e stop: non ci sono limiti di peso, quindi guarda quanto peserebbe la posizione sul portafoglio.</p>`;
}
function decPlan(D) {
  const V = D.verdict, pl = D.plans, icon = { true: "✅", false: "❌", null: "·" };
  const brk = pl.breakouts || [];
  const main = V.plan === "now" ? `<h5>Piano: entra ora ${info(TA_PLAN_INFO)}</h5>${taPlanHTML("now", pl.now)}`
    : V.plan === "pullback" ? `<h5>Piano: ordine limite su ritracciamento ${info(TA_PLAN_INFO)}</h5>${taPlanHTML("pullback", pl.pullback)}
        <p class="muted small">L'ordine limite compra solo se il prezzo scende fino a quel livello. Se il prezzo non ci arriva, non compri: è il costo di aspettare un prezzo migliore.</p>`
    : V.plan === "breakout" ? `<h5>Livello di rottura: solo un'informazione, il pattern non è verificato</h5>${brk.filter(p => p.pattern === (V.pattern || p.pattern)).slice(0, 1).map((p, k) => taBreakoutHTML(brk.indexOf(p), p)).join("")}` : "";
  const others = [
    V.plan !== "now" && pl.now ? `<h5>Se comprassi adesso ${info(TA_PLAN_INFO)}</h5>${taPlanHTML("now", pl.now)}` : "",
    V.plan !== "pullback" && pl.pullback ? `<h5>Ordine limite su ritracciamento (vicino alla media ${pl.pullback.ma})</h5>${taPlanHTML("pullback", pl.pullback)}` : "",
    ...brk.map((p, k) => V.plan === "breakout" && p.pattern === V.pattern ? "" : `<h5>Ordine condizionato sulla rottura (pattern non verificato)</h5>${taBreakoutHTML(k, p)}`),
  ].filter(Boolean);
  return `<div class="dec-verdict"><div>${verdictBadge(V)}</div>
      <ul class="why">${V.why.map(w => `<li>${esc(w)}</li>`).join("")}</ul>
      ${V.change ? `<p><b>Cosa deve cambiare:</b> ${esc(V.change)}.</p>` : ""}
      ${V.owned ? `<p class="small">Lo possiedi: il verdetto è l'azione proposta dalle regole sulle posizioni. <button class="link-btn" data-pos="${esc(V.isin)}">Apri pagella e regole della posizione →</button></p>` : ""}</div>
    ${main}
    <h5>Regole del verdetto ${V.owned ? `<span class="muted">(per un nuovo acquisto; per le posizioni che hai valgono le regole della posizione)</span>` : `<span class="muted">(decide la prima non soddisfatta, in ordine)</span>`}</h5>
    <ul class="rule-list">${D.checks.map(c => `<li class="${c.ok === false ? "bad" : c.ok ? "on" : "na"}"><span class="ri">${icon[c.ok]}</span><span><b>${c.id}</b> ${esc(c.text)}<span class="muted small"> ${c.ok == null ? "non valutabile" : ""} ${esc(c.detail)}</span></span></li>`).join("")}</ul>
    <p class="muted small">${esc(D.principle)} Se sono tutte soddisfatte: «Entra ora». D1 debole: «Evita». D2 e D4: «Attendi». D5 e D7: «Entra su ritracciamento». D6: «Attendi: a ridosso del massimo»
      (la rottura del massimo non ha superato il test dei pattern). La regola D3 sui limiti di peso è stata tolta.</p>
    ${others.length ? `<details class="fold"><summary><span class="small">Altri piani possibili (${others.length}), con i loro limiti</span></summary>${others.join("")}</details>` : ""}`;
}
// ---- "Analisi" box on top of Decisione (phase 22, in the style of Fineco's Analisi page). Only signal, trend and comment
// are visible; everything else is in sections closed by default. All numbers come from decision.analysis_box.
const AN_TREND_INFO = r => `Rendimento del titolo su 5 sedute (breve, circa 1 settimana), 21 (medio, 1 mese) e 63 (lungo, 3 mesi).
  <b>▲</b> se supera +${fNum(r.trend["5"], 0)}% / +${fNum(r.trend["21"], 0)}% / +${fNum(r.trend["63"], 0)}%, <b>▼</b> se scende sotto le stesse soglie in negativo, <b>=</b> altrimenti.
  Descrive l'andamento, non è un voto né una previsione.`;
const AN_BAND_INFO = `Quanto si muove di solito il titolo in una settimana (5 sedute): la fascia è il prezzo ± la deviazione standard dei rendimenti giornalieri
  delle ultime 63 sedute × √5. Circa 2 settimane su 3 il prezzo resta nella fascia del 68%, circa 9 su 10 in quella del 90%.
  <b>Non sono obiettivi</b>: servono a capire se uno stop è troppo vicino e rischia di scattare per il normale «rumore» del mercato.`;
const AN_LEVELS_INFO = r => `Livelli considerati: massimi e minimi significativi delle ultime ${r.swing[0]} sedute (il prezzo più alto o più basso delle ${r.swing[1]} sedute prima e dopo),
  massimo e minimo a 52 settimane, medie a 50 e 200 giorni. Livelli a meno dell'${fNum(r.zone, 0)}% l'uno dall'altro diventano una zona. Sono mostrati i due più vicini sopra e sotto il prezzo.`;
const AN_CONS_INFO = `Distribuzione dei giudizi degli analisti nel mese (dati Yahoo). <b>Voto medio</b> da 1 a 5: Strong Buy vale 1, Buy 2, Hold 3, Sell 4, Strong Sell 5;
  si moltiplica ogni giudizio per il suo valore, si somma e si divide per il numero di analisti. 1 = acquistare, 5 = vendere.`;
const AN_SETTLE_INFO = `Valuta con cui regoli su Fineco i titoli americani. <b>EUR</b>: Fineco converte al cambio con uno spread di 0,0033 sul EUR/USD sia quando compri sia quando vendi,
  quindi il rischio in euro è un po' più alto e le quantità un po' più basse. <b>USD</b>: hai già dollari sul conto, niente spread.`;
const an = { copy: [] };
function anBox(D) {
  const A = D.analysis;
  if (!A) return "";
  const S = A.signal, sp = S.plan, pr = D.price, pct = v => fPct((v / pr - 1) * 100, 1);
  const since = S.since ? (S.since.today ? `da oggi (${dayShort(S.since.date)})`
      : `${S.since.atLeast ? "almeno dal" : "dal"} ${dayIT(S.since.date)} a ${fUsd(S.since.price)} <span class="${sign(S.sinceChg)}">(${fPct(S.sinceChg, 1)} da allora)</span>`) : "";
  const sinceNote = !S.since ? "" : S.diaryDays < 5 ? `Il diario ha solo ${S.diaryDays} ${S.diaryDays === 1 ? "giorno" : "giorni"}: la data può essere più vecchia.`
    : S.since.atLeast ? "La serie arriva al primo giorno del diario: il verdetto può essere più vecchio." : S.prevLabel ? `Prima il verdetto era «${esc(S.prevLabel)}».` : "";
  const plan = sp ? `<div class="an-plan">${sp.info ? "<b>Livello di rottura</b> (solo informazione, pattern non verificato): " : ""}Entrata <b>${fUsd(sp.entry)}</b> · Stop <b>${fUsd(sp.stop)}</b> <span class="down">${pct(sp.stop)}</span>
      · Target <b>${fUsd(sp.target)}</b> <span class="up">${pct(sp.target)}</span> · Rischio/rendimento <b>2,0 : 1</b>${isNum(sp.rrResistance) ? ` <span class="muted">(fino al massimo a 52 settimane, ${fUsd(sp.resistance)}: ${fNum(sp.rrResistance, 1)} : 1)</span>` : ""}</div>`
    : `<div class="an-plan muted">Nessun piano di acquisto con questo verdetto: ${esc(D.verdict.why[0] || "")}.</div>`;
  const lab = { 5: "breve (1 settimana)", 21: "medio (1 mese)", 63: "lungo (3 mesi)" };
  const tr = A.trends.map(t => `<span class="an-tr"><span class="muted">${lab[t.days]}</span> <b class="${t.arrow === "▲" ? "up" : t.arrow === "▼" ? "down" : ""}">${t.arrow || "—"}</b> ${isNum(t.pct) ? fPct(t.pct, 1) : ""}</span>`).join("");
  const z = A.zones, zone = x => `<b>${Math.abs(x.hi - x.lo) < 0.005 ? fUsd(x.lo) : `${fNum(x.lo, 2)}–${fNum(x.hi, 2)} $`}</b> ${esc(x.names.join(" / "))} <span class="${sign(x.pct)}">(${fPct(x.pct, 1)})</span>`;
  const P = A.pivots, B = A.band, Dt = A.data, C = A.consensus, L = C.last;
  const big = v => isNum(v) ? (v >= 1e6 ? fNum(v / 1e6, 1) + " mln" : fNum(v, 0)) : "—";
  an.copy = A.orders.map(o => [`${D.ticker} – ${o.type}${o.info ? " (pattern non verificato)" : ""}`, `Prezzo: ${fNumCopy(o.price, 2)} $`, `Quantità: ${o.qty ?? "—"}`,
    `Stop loss: ${fNumCopy(o.stopLoss, 2)} $`, `Take profit: ${fNumCopy(o.takeProfit, 2)} $`, `Scadenza: ${o.expiry} (${o.expiryNote})`,
    `Regolo in: ${A.settle}`, "Stop loss e take profit autoescludenti; non attivi nell'after hours.", "Screening automatico, non è una consulenza finanziaria."].join("\n"));
  const orderLab = { now: "Entra ora", pullback: "Ordine limite su ritracciamento", breakout: "Ordine condizionato sulla rottura (pattern non verificato)" };
  const orders = A.orders.map((o, k) => `<div class="an-order${o.info ? " info" : ""}"><h5>${orderLab[o.kind]}</h5>
    <div class="an-grid">
      <span>Tipo di ordine</span><b>${o.type} a ${fUsd(o.price)}</b>
      <span>Stop loss</span><b>${fUsd(o.stopLoss)}</b>
      <span>Take profit</span><b>${fUsd(o.takeProfit)}</b>
      <span>Scadenza</span><b>${o.expiry} <span class="muted">(${o.expiryNote})</span></b>
      <span>Quantità</span><b>${isNum(o.qty) ? `${fNum(o.qty, 0)} azioni ≈ ${fEur(o.valueEur, 0)}` : "—"}</b>
    </div>
    ${isNum(o.qty) ? `<p class="ta-note">Se scatta lo stop perdi circa ${fEur(o.lossEur, 0)} (${fNum(A.riskPct, 1)}% del portafoglio)${A.spread ? `, compreso lo spread di cambio di Fineco (${fNum(A.spread, 4)} sul EUR/USD): senza spread sarebbero ${o.noSpreadQty}` : ", regolando in dollari (niente spread)"}.</p>` : ""}
    <button class="btn" data-an-copy="${k}">Copia riepilogo ordine</button> <span class="small muted" data-an-copied="${k}"></span></div>`).join("");
  return `<div class="an-box">
    <h4>Analisi <span class="muted">${esc(D.ticker)} · ${fUsd(pr)}</span></h4>
    <div class="an-sig">${verdictBadge(D.verdict)} <span>${since}</span>${sinceNote ? `<div class="muted small">${sinceNote}</div>` : ""}${plan}</div>
    <div class="an-trend"><span class="an-l">Tendenza ${info(AN_TREND_INFO(A.rules))}</span>${tr}</div>
    <div class="an-comment"><p>${esc(A.comment.text)}</p><p>${esc(A.comment.owner)}</p><p>${esc(A.comment.notOwner)}</p><p class="muted small">${esc(A.comment.end)}</p></div>
    <details class="fold"><summary><span class="small">Supporti e resistenze ${info(AN_LEVELS_INFO(A.rules))}</span></summary>
      <p><span class="muted">Resistenze:</span> ${z.above.length ? z.above.slice().reverse().map(zone).join(" · ") : "nessun livello sopra il prezzo tra quelli considerati"}<br>
        <span class="muted">Supporti:</span> ${z.below.length ? z.below.map(zone).join(" · ") : "nessun livello sotto il prezzo tra quelli considerati"}</p>
      <p><span class="muted">Punti pivot del giorno (livelli di brevissimo periodo, cambiano ogni giorno; formula classica sui prezzi di ieri):</span><br>
        S2 ${fNum(P.S2, 2)} · S1 ${fNum(P.S1, 2)} · <b>Pivot ${fNum(P.P, 2)}</b> · R1 ${fNum(P.R1, 2)} · R2 ${fNum(P.R2, 2)}</p></details>
    <details class="fold"><summary><span class="small">Oscillazione normale a 5 giorni ${info(AN_BAND_INFO)}</span></summary>
      <p>68% delle settimane: <b>${fUsd(B.p68[0])} – ${fUsd(B.p68[1])}</b> (±${fNum(B.sd, 1)}%) · 90%: <b>${fUsd(B.p90[0])} – ${fUsd(B.p90[1])}</b> (±${fNum(B.sd * 1.645, 1)}%)</p>
      ${isNum(B.stop) ? (B.stopInside ? `<p class="warn-box">⚠ Stop dentro l'oscillazione normale: rischia di scattare per rumore (stop ${fUsd(B.stop)}).</p>`
        : `<p class="muted small">Lo stop proposto (${fUsd(B.stop)}) è fuori dalla fascia del 68%.</p>`) : ""}</details>
    <details class="fold"><summary><span class="small">Dati sintetici</span></summary>
      <p>Volumi medi 5 g <b>${big(Dt.vol5)}</b> · 21 g <b>${big(Dt.vol21)}</b> (${fNum(Dt.volRatio, 2)}×) · Variazione 1 g <b class="${sign(Dt.chg1)}">${fPct(Dt.chg1, 1)}</b> · 5 g <b class="${sign(Dt.chg5)}">${fPct(Dt.chg5, 1)}</b> · 21 g <b class="${sign(Dt.chg21)}">${fPct(Dt.chg21, 1)}</b><br>
        Volatilità annua 5 g <b>${fNum(Dt.vola5, 1)}%</b> · 10 g <b>${fNum(Dt.vola10, 1)}%</b> · 21 g <b>${fNum(Dt.vola21, 1)}%</b></p></details>
    <details class="fold"><summary><span class="small">Consenso degli analisti ${info(AN_CONS_INFO)}</span></summary>
      ${C.n ? `<p>Strong Buy ${C.counts[0]} · Buy ${C.counts[1]} · Hold ${C.counts[2]} · Sell ${C.counts[3]} · Strong Sell ${C.counts[4]} (${C.n} analisti)<br>
        Voto medio <b>${fNum(C.mean, 2)}</b> su 5 <span class="muted">(1 = acquistare, 5 = vendere)</span></p>` : `<p class="muted">Giudizi degli analisti non disponibili.</p>`}
      <p>${isNum(C.target) ? `Prezzo obiettivo medio <b>${fUsd(C.target)}</b>${C.targetN ? ` (${C.targetN} analisti)` : ""}, potenziale <b class="${sign(C.upside)}">${fPct(C.upside, 1)}</b>` : `<span class="muted">Prezzo obiettivo non disponibile.</span>`}<br>
        ${L && isNum(L.reported) ? `Ultima trimestrale (${dayShort(L.ts.slice(0, 10))}): EPS atteso ${isNum(L.eps) ? fNum(L.eps, 2) + " $" : "—"}, effettivo ${fNum(L.reported, 2)} $${isNum(L.surprise) ? `, sorpresa <b class="${sign(L.surprise)}">${fPct(L.surprise, 1)}</b>` : ""}` : `<span class="muted">Ultima trimestrale non disponibile.</span>`}</p>
      ${C.surpriseHigh ? `<p class="small muted">Sorpresa molto alta: spesso dipende da voci straordinarie (plusvalenze, rivalutazioni), non da un aumento stabile degli utili.</p>` : ""}</details>
    <details class="fold"><summary><span class="small">Piano pronto per Fineco</span></summary>
      ${orders || `<p class="muted">Nessun piano calcolabile.</p>`}
      <ul class="why small">
        <li>Su Fineco <b>stop loss e take profit sono autoescludenti</b>: quando scatta uno, l'altro si cancella.</li>
        <li><b>Stop loss e take profit non sono attivi nell'after hours.</b></li>
        <li>Su Fineco stop loss e take profit sono esclusi da AutoFX: la prima volta verifica nel book in che valuta vengono regolati sui titoli USA.</li>
        <li>Quantità dal tuo rischio per operazione (${fNum(A.riskPct, 1)}%), regolando in ${A.settle}${A.spread ? ` con lo spread di cambio di Fineco (${fNum(A.spread, 4)} sul EUR/USD) all'acquisto e all'uscita` : " (niente spread di cambio)"}. Scadenza massima 30 giorni.</li>
      </ul></details>
  </div>`;
}
document.addEventListener("click", e => {
  const b = e.target.closest("[data-an-copy]");
  if (!b) return;
  const k = +b.dataset.anCopy, text = an.copy[k] || "", done = () => { const m = $(`[data-an-copied="${k}"]`); if (m) m.textContent = "✓ copiato"; };
  (navigator.clipboard?.writeText(text) || Promise.reject()).then(done).catch(() => {
    const t = document.createElement("textarea"); t.value = text; document.body.appendChild(t); t.select();
    try { document.execCommand("copy"); done(); } catch { /* the text stays selectable */ } t.remove();
  });
});
function renderTA() {
  const el = $("#dTA"), t = state.detail, D = dTA.D, s = state.bySym.get(t);
  if (!el || dTA.t !== t || !D || !s) return;
  if (el.contains(document.activeElement) && document.activeElement.tagName === "INPUT") return;   // typing: do not redraw
  const T = D.timing, lv = T.levels;
  el.innerHTML = `<h3>Decisione ${info(DEC_INFO)} <span class="muted small ta-asof">${dTA.ta ? `livelli alla chiusura del ${dayIT(dTA.ta.asOf)} · ` : ""}prezzo ${fUsd(D.price)}</span></h3>
    ${anBox(D) || `<div class="dec-top">Verdetto: ${verdictBadge(D.verdict)} <span class="muted small">i motivi e le regole sono nel blocco 5</span></div>`}
    <div class="ta-part"><h4>1 · Azienda e valutazione <span class="muted">decide se comprare</span></h4>${decCompany(D.company)}</div>
    <div class="ta-part"><h4>2 · Contesto</h4>${decContext(t, D.context)}</div>
    <div class="ta-part"><h4>3 · Tempismo tecnico <span class="muted">decide quando e a che prezzo</span></h4>${dTA.trend}
      ${lv ? `<p><b>Livelli chiave:</b> massimo a 52 settimane ${fUsd(lv.high52.v)} (${dayShort(lv.high52.date)}) · media 20 ${fUsd(lv.sma20)} · media 50 ${fUsd(lv.sma50)} · media 200 ${fUsd(lv.sma200)} ·
        ultimo minimo ${fUsd(lv.low.v)} (${dayShort(lv.low.date)}) · ATR ${fUsd(lv.atr)} (${fNum(lv.atr / D.price * 100, 1)}% del prezzo)</p>` : ""}
      <h5>Pattern presenti ed esito del test</h5>${taPatterns(D)}</div>
    <div class="ta-part"><h4>4 · Posto nel mio portafoglio <span class="muted">decide quanto</span></h4>${decPlace(D)}</div>
    <div class="ta-part"><h4>5 · Piano operativo</h4>${decPlan(D)}</div>
    <p class="disclaimer">Screening meccanico a scopo di studio: verdetto e livelli non sono previsioni né consigli, e le regole non sono verificate da backtest. Non è una consulenza finanziaria.</p>`;
}
async function taEnsure() {      // the pattern test and the portfolio (for the position panel), loaded once
  const jobs = [];
  if (!pt.data) jobs.push(getJSON("/api/patterns").then(d => { pt.data = d; }).catch(() => {}));
  if (!pf.data) jobs.push(getJSON("/api/portfolio").then(d => { pf.data = d; }).catch(() => {}));
  if (jobs.length) { await Promise.all(jobs); renderTA(); }
}
drawer.addEventListener("click", e => {
  const o = e.target.closest("[data-ta-stop]");
  if (o) { const [id, v] = o.dataset.taStop.split(":"); dTA.sel[id] = v; return renderTA(); }
  const k = e.target.closest("[data-dec-macro]");        // a macro event listed in the context block
  if (k) {
    const [kind, day] = k.dataset.decMacro.split("|");
    const hit = D => (D?.events || []).find(x => x.kind === kind && x.date === day);
    (hit(macroData) || hit(macroNext) ? Promise.resolve() : getJSON("/api/macro").then(d => { macroNext = d; })).then(() => openMacro(hit(macroData) || hit(macroNext))).catch(() => {});
    return;
  }
  const m = e.target.closest("[data-mopen]");          // a stock listed in a macro event's panel
  if (m) openDetail(m.dataset.mopen);
});
drawer.addEventListener("change", e => {
  if (e.target.id === "taSettle") {                     // EUR (Fineco's exchange spread) or USD, saved in portafoglio/regole.json
    pfPost("/api/rules", { body: JSON.stringify({ settle: e.target.value }), headers: { "Content-Type": "application/json" } })
      .then(() => { pf.data = null; loadDetailInfo(); })
      .catch(err => { $("#taRiskMsg").innerHTML = `<span class="down">non salvato: ${esc(err.message)}</span>`; });
    return;
  }
  if (e.target.id === "taRisk") {                       // my risk per trade, saved in portafoglio/regole.json
    const v = parseFloat(String(e.target.value).replace(",", "."));
    if (!(v >= 0.1 && v <= 10)) { $("#taRiskMsg").innerHTML = `<span class="down">serve un numero tra 0,1 e 10</span>`; return; }
    pfPost("/api/rules", { body: JSON.stringify({ tradeRisk: v }), headers: { "Content-Type": "application/json" } })
      .then(() => { e.target.blur(); pf.data = null; loadDetailInfo(); })
      .catch(err => { $("#taRiskMsg").innerHTML = `<span class="down">non salvato: ${esc(err.message)}</span>`; });
    return;
  }
  if (e.target.id !== "taCapital") return;
  const v = parseFloat(e.target.value);
  LS.set("taCapital", isNum(v) && v > 0 ? v : 0);
  e.target.blur();
  loadDetailInfo();               // the quantities are computed by the server with this capital
});

async function loadDetailInfo() {
  const t = state.detail;
  let data = { info: {}, news: [] };
  const cap = +LS.get("taCapital", 0);        // manual capital for the position size when the portfolio is not loaded
  try { data = await getJSON(`/api/stock/${encodeURIComponent(t)}${cap > 0 ? `?capital=${cap}` : ""}`); } catch { /* show what we have */ }
  if (state.detail !== t) return;
  dInfo = data.info || {};
  renderDetailHeader();
  const s = state.bySym.get(t) || {}, i = dInfo;
  const idx = state.snap.indices[t];
  const q = s.ticker ? s : idx || {};
  const perf = [["1G", q.chgPct], ["1S", q.perf1W], ["1M", q.perf1M], ["3M", q.perf3M], ["6M", q.perf6M], ["YTD", q.perfYTD], ["1A", q.perf1Y]];
  const stat = (l, v) => `<div><span>${l}</span><span>${v}</span></div>`;
  const vs = k => `<span class="${sign(s[k])}">${fPct(s[k], 1)}</span>`;
  const pctOf = v => isNum(v) ? fNum(v * 100, 1) + "%" : "—";
  const tech = data.tech || {};
  const rng52 = isNum(s.lo52) && isNum(s.hi52) ? rangeViz(s.lo52, s.hi52, s.price, null, "Range a 52 settimane") : "";
  const tgt = isNum(i.targetLowPrice) && isNum(i.targetHighPrice) && isNum(s.price)
    ? rangeViz(Math.min(i.targetLowPrice, s.price), Math.max(i.targetHighPrice, s.price), s.price, i.targetMeanPrice,
      `Target degli analisti · ${esc(REC[i.recommendationKey] || "—")} · ${i.numberOfAnalystOpinions || 0} analisti`, [i.targetLowPrice, i.targetHighPrice]) : "";
  const trend = `<div class="d-sec"><h3>Trend</h3>
    <div class="d-perf">${perf.map(([l, v]) => `<div><div class="l">${l}</div><div class="v ${sign(v)}">${fPct(v, 1)}</div></div>`).join("")}</div>
    ${s.ticker ? `<div class="d-stats">
      ${stat("vs media 20 giorni", vs("vsSma20"))}${stat("vs media 40 giorni", vs("vsSma40"))}
      ${stat("vs media 60 giorni", vs("vsSma60"))}${stat("Ordine medie 20/40/60", maOrder(s))}
      ${stat("vs media 50 giorni", vs("vsSma50"))}${stat("vs media 200 giorni", vs("vsSma200"))}
      ${stat("RSI (14)", fNum(s.rsi, 0))}${stat("Volatilità (20 g, annua)", isNum(s.vol20) ? fNum(s.vol20, 0) + "%" : "—")}
      ${stat("Beta", fNum(i.beta, 2))}${stat("Short % flottante", pctOf(i.shortPercentOfFloat))}
      ${stat(`Pendenza media 20 ${info(slopeInfo(20, tech.slope20))}`, slopeCell(tech.slope20))}${stat(`Pendenza media 60 ${info(slopeInfo(60, tech.slope60))}`, slopeCell(tech.slope60))}
      ${stat(`Volumi 20/60 giorni ${info(volRatioInfo(tech.volRatio))}`, fX(tech.volRatio))}
    </div>${rng52}` : ""}</div>`;
  dNews = data.news || [];
  const newsSec = dNews.length ? `<div class="d-sec" id="dNews"></div>` : "";
  const company = s.ticker ? `<details class="d-sec fold"><summary><h3>Dati della società</h3><span class="muted small">profilo, sede, dati del giorno</span></summary>
    ${i.longBusinessSummary ? `<p class="about clamp" id="about">${esc(i.longBusinessSummary)}</p>
      <button class="link-btn" id="aboutMore">Mostra altro</button>${i.website ? ` <a class="link-btn" href="${esc(i.website)}" target="_blank" rel="noopener">${esc(i.website.replace(/^https?:\/\/(www\.)?/, ""))} ↗</a>` : ""}` : ""}
    <div class="d-stats" style="margin-top:10px">
      ${stat("Dipendenti", isNum(i.fullTimeEmployees) ? i.fullTimeEmployees.toLocaleString("it-IT") : "—")}${stat("Sede", esc([i.city, i.state || i.country].filter(Boolean).join(", ") || "—"))}
      ${stat("Apertura", fPrice(s.open))}${stat("Range del giorno", `${fPrice(s.low)} – ${fPrice(s.high)}`)}
      ${stat("Volume", fBig(s.volume))}${stat("Volume relativo", fX(s.relVol))}
    </div></details>` : "";
  const fundamentals = `<div class="d-stats val-tbl">
      ${stat("P/E (ultimi 12 mesi)", fNum(i.trailingPE, 1))}${stat("P/E atteso", fNum(i.forwardPE, 1))}
      ${stat("PEG", fNum(data.valuation?.peg ?? s.peg, 2))}${stat("P/S", fNum(i.priceToSalesTrailing12Months, 1))}
      ${stat("EV/EBITDA", fNum(i.enterpriseToEbitda, 1))}${stat("Crescita ricavi", isNum(i.revenueGrowth) ? fPct(i.revenueGrowth * 100, 1) : "—")}
      ${stat("Margine lordo", pctOf(i.grossMargins))}${stat("Margine netto", pctOf(i.profitMargins))}
      ${stat("Flusso di cassa libero", accMoney(i.freeCashflow, data.accountsCurrency))}${stat("ROE", pctOf(i.returnOnEquity))}
      ${stat("Utile per azione (12 mesi)", fNum(i.trailingEps, 2))}${stat("Utile per azione atteso", fNum(i.forwardEps, 2))}
      ${stat("Ricavi (12 mesi)", accMoney(i.totalRevenue, data.accountsCurrency))}${stat("Rendimento dividendo", isNum(i.dividendYield) && i.dividendYield > 0 ? fNum(i.dividendYield, 2) + "%" : "—")}
    </div>`;
  // index stocks: the Trend block lives inside "Decisione" (block 3), not twice
  const hasTA = !!(s.ticker && data.decision);
  Object.assign(dTA, { t, ta: data.ta || null, D: hasTA ? data.decision : null, fx: data.fx, trend: trend.replace('<div class="d-sec"><h3>Trend</h3>', '<div>'), sel: {} });
  drawer.querySelector(".d-rest").innerHTML = `${hasTA ? `<div class="d-sec ta" id="dTA"></div>` : ""}<div class="d-cols">
      <div class="d-col">${hasTA ? "" : trend}${s.ticker ? valuationHTML(data.valuation, fundamentals) : ""}</div>
      <div class="d-col">${s.ticker ? analystsHTML(data.analysts, s, tgt, data.accountsCurrency) : ""}${newsSec}</div></div>${s.ticker ? `<div class="d-sec" id="dInv"><h3>Analisi investimento</h3><div class="muted small">Carico…</div></div><div class="d-sec" id="dVal"><h3>Valutazione e scenari</h3><div class="muted small">Carico…</div></div>` : ""}${company}`;
  drawer.querySelector(".d-sum").innerHTML = signalHTML(data.signal);
  if (hasTA) { renderTA(); taEnsure(); }
  renderDetailNews();
  if (s.ticker) { loadDetailInv(t); loadDetailVal(t); }
  const more = $("#aboutMore");
  if (more) more.onclick = () => { $("#about").classList.toggle("clamp"); more.textContent = $("#about").classList.contains("clamp") ? "Mostra altro" : "Mostra meno"; };
}
function renderDetailNews() {
  const el = $("#dNews");
  if (!el) return;
  const list = visibleNews(dNews).slice(0, 8);
  el.innerHTML = `<h3>Notizie</h3>${newsOpts()}<div class="news">${list.map(n => `<a href="${esc(n.url)}" target="_blank" rel="noopener"><div class="nt">${esc(n.title)}</div>
    <div class="nm">${newsTag(n)} ${esc(n.publisher || "")} · ${esc(ago(n.time))}</div></a>`).join("") || `<div class="empty">Solo articoli d'opinione: deseleziona "Nascondi opinioni" per vederli</div>`}</div>`;
}
// trend figures for the detail (from the technical score's metrics)
const slopeCell = v => isNum(v) ? `<span class="${sign(v)}">${fPct(v, 2)}/sett.</span>` : "—";
function slopeInfo(n, v) {
  let t = `Di quanto è cambiata in una settimana la media mobile a ${n} giorni. Dice in che direzione va il trend
    ${n === 20 ? "di breve" : "di medio"} periodo: positiva = la media sale, negativa = scende.`;
  if (isNum(v)) t += `<br><br>Ora: <b>${fPct(v, 2)} a settimana</b>, ${v > 0.05 ? "la media sale" : v < -0.05 ? "la media scende" : "la media è quasi piatta"}.`;
  return t;
}
function volRatioInfo(v) {
  let t = `Volume medio degli ultimi 20 giorni diviso il volume medio degli ultimi 60. Sopra 1× = negli ultimi giorni si scambia
    più del solito (più interesse, spesso per notizie o trimestrali); sotto 1× = meno.`;
  if (isNum(v)) t += `<br><br>Ora: <b>${fX(v)}</b>, ${v >= 1.2 ? "volumi in aumento" : v <= 0.8 ? "volumi in calo" : "volumi nella norma"}.`;
  return t;
}
// price vs the 20/40/60-day averages, same wording as the report's "Ordine medie"
function maOrder(s) {
  const { price: p, sma20: a, sma40: b, sma60: c } = s;
  if (![p, a, b, c].every(isNum)) return "—";
  if (p > a && a > b && b > c) return `<span class="up">rialzista (20>40>60)</span>`;
  if (p < a && a < b && b < c) return `<span class="down">ribassista (20<40<60)</span>`;
  return "misto";
}
// ------------------------------------------------------------ detail: valuation & analysts (daily data, analysts.py)
// final signal (score.py): technical 40% + analysts 25% + valuation 20% + news 15%
const SIG_CLS = { "Molto positivo": "b2", Positivo: "b1", Neutro: "n", Negativo: "s1", "Molto negativo": "s2", "Dati insufficienti": "na" };
// reports and backtests saved before the rename still carry the old band names
const SIG_OLD = { "Forte acquisto": "Molto positivo", Acquisto: "Positivo", Vendita: "Negativo", "Forte vendita": "Molto negativo" };
const sigName = l => SIG_OLD[l] || l;
const sigBadge = l => l ? `<span class="sg ${SIG_CLS[sigName(l)]}">${esc(sigName(l))}</span>` : "—";
// "In sintesi": signal plus the first reason of the 3 parts that move the score most (score × effective weight)
const SIG_INFO = `Il segnale combina tre parti: <b>analisti</b> (42%), <b>valutazione</b> (33%) e <b>notizie</b> (25%).
  Se una parte manca, il suo peso va alle altre. Con una sola parte disponibile (per esempio solo le notizie) il segnale
  non è affidabile: al suo posto compare <b>Dati insufficienti</b>.<br><br>La parte tecnica non ne fa più parte: il backtest
  ha mostrato che non distingue la direzione. È mostrata a parte come <b>Trend</b>.`;
const TREND_INFO = `Trend: punteggio da −100 a +100 su come si sta muovendo il prezzo (ordine e pendenza delle medie 20/40/60,
  distanza dalle medie, RSI, forza rispetto a QQQ). Descrive l'andamento, <b>non è un voto</b>: il backtest non ha mostrato
  che i titoli con Trend alto vadano meglio di quelli con Trend basso.`;
function signalHTML(sig) {
  if (!sig) return "";
  const ok = isNum(sig.score), tr = sig.trend;
  const top = sig.components.filter(c => c.used && isNum(c.score))
    .sort((a, b) => Math.abs(b.score * b.effWeight) - Math.abs(a.score * a.effWeight)).slice(0, 3);
  return `<div class="sigbox"><h3>In sintesi ${info(SIG_INFO)}</h3>
    <div class="sig-head">${sigBadge(sig.signal)}${ok ? `<span class="sig-score num ${sign(sig.score)}">${sig.score > 0 ? "+" : ""}${fNum(sig.score, 0)}</span>
      <span class="muted small">punteggio da −100 a +100 · ≥ +20 positivo, ≤ −20 negativo</span>`
      : `<span class="muted small">disponibile solo ${top.length} parte su 3: servono almeno 2 parti tra analisti, valutazione e notizie</span>`}</div>
    <ol class="top3">${top.map(c => `<li><b>${esc(c.name)}</b> <span class="num ${sign(c.score)}">${c.score > 0 ? "+" : ""}${fNum(c.score, 0)}</span> · ${esc(c.reasons[0] || "")}</li>`).join("")}</ol>
    <div class="muted small">Analisti, valutazione e notizie non hanno uno storico gratuito: questo segnale non è verificato con un backtest.</div>
    ${tr ? `<div class="trend-row"><b>Trend</b> ${info(TREND_INFO)} ${scoreBar(tr.score)} <span class="muted small">andamento del prezzo, non un voto</span>
      <ul class="why">${tr.reasons.map(r => `<li>${esc(r)}</li>`).join("")}</ul></div>` : ""}
    <details class="fold"><summary><span class="small">Dettaglio del segnale</span></summary>
    <div class="sig-comps">${sig.components.map(c => `<div class="sig-c ${c.used ? "" : "off"}">
      <div class="sig-cn"><b>${esc(c.name)}</b> <span class="muted">${c.used ? `peso ${fNum(c.effWeight * 100, 0)}%` : "non disponibile"}</span></div>
      <div>${c.used ? scoreBar(c.score) : ""}</div>
      <ul class="why">${c.reasons.map(r => `<li>${esc(r)}</li>`).join("")}</ul></div>`).join("")}</div>
    <div class="muted small">Combinazione automatica di dati pubblici (pesi: analisti 42%, valutazione 33%, notizie 25%).
      Non è una consulenza finanziaria: usalo come punto di partenza per le tue verifiche.</div></details></div>`;
}
const VAL_CLS = { Economica: "cheap", "In linea": "fair", Cara: "rich" };
const valBadge = l => l ? `<span class="vb ${VAL_CLS[l]}">${esc(l)}</span>` : "—";
function valuationHTML(v, table = "") {
  if (!v) return `<div class="d-sec"><h3>Valutazione</h3>${table}</div>`;
  const d = isNum(v.ratio) ? (v.ratio - 1) * 100 : null;
  const head = v.label ? `${valBadge(v.label)} <span class="muted">${Math.abs(d) < 3 ? "in media con i confronti"
    : `in media ${fNum(Math.abs(d), 0)}% ${d > 0 ? "più cara" : "più economica"} dei confronti`}</span>` : `<span class="muted">Dati insufficienti per un giudizio</span>`;
  const pe = v.vsHistory?.pe;
  const years = pe ? `<div class="muted small">P/E alle chiusure di bilancio: ${pe.years.slice().reverse().map(y => `${y.fy.slice(0, 4)} ${fNum(y.v, 1)}`).join(" · ")} · oggi ${fNum(pe.value, 1)}</div>` : "";
  return `<div class="d-sec"><h3>Valutazione</h3>${table}<div class="val-head">${head}</div>
    <ul class="why">${v.notes.map(n => `<li>${esc(n)}</li>`).join("")}</ul>${years}
    <div class="muted small">Confronto con la mediana dei titoli dello stesso settore nel Nasdaq-100 e con la storia del titolo
    (P/E e P/S alle ultime chiusure di bilancio). Giudizio: Economica sotto −15%, Cara sopra +18%.</div></div>`;
}
const ACT_IT = { up: "Upgrade", down: "Downgrade", init: "Avvio copertura", main: "Conferma", reit: "Conferma" };
// Figures in the currency of the statements (phase 5B fix): "$" only when the accounts are in USD; PDD (CNY) or ASML
// (EUR) amounts from Yahoo are in their own currency, not in dollars. Unknown currency: said in words.
function accMoney(v, cur) {
  if (!isNum(v)) return "—";
  if (cur === "USD") return "$" + fBig(v);
  return fBig(v) + (cur ? " " + cur : " (valuta del bilancio)");
}

function analystsHTML(a, s, tgt = "", accCur = null) {
  if (!a) return `<div class="d-sec"><h3>Analisti</h3>${tgt}<div class="muted">Dati degli analisti in caricamento (si aggiornano una volta al giorno)</div></div>`;
  const rt = a.recTrend || [], now = rt[0], old = rt[3];
  const KEYS = [["strongBuy", "Forte acquisto"], ["buy", "Acquisto"], ["hold", "Mantenere"], ["sell", "Vendita"], ["strongSell", "Forte vendita"]];
  const tot = now ? KEYS.reduce((n, [k]) => n + (now[k] || 0), 0) : 0;
  const bar = tot ? `<div class="recbar">${KEYS.map(([k, l]) => now[k] ? `<i class="${k}" style="flex:${now[k]}" title="${l}: ${now[k]}"></i>` : "").join("")}</div>
    <div class="reclegend">${KEYS.map(([k, l]) => `<span><i class="${k}"></i>${l} ${now[k] || 0}</span>`).join("")}</div>
    ${old ? `<div class="muted small">3 mesi fa: ${KEYS.map(([k, l]) => `${l.toLowerCase()} ${old[k] || 0}`).join(" · ")}</div>` : ""}` : "";
  const cutoff = new Date(Date.now() - 30 * 864e5).toISOString().slice(0, 10);
  const recent = (a.actions || []).filter(x => x.date >= cutoff);
  const cnt = f => recent.filter(f).length;
  const last30 = `Ultimi 30 giorni: <b class="up">${cnt(x => x.action === "up")} upgrade</b> · <b class="down">${cnt(x => x.action === "down")} downgrade</b> ·
    ${cnt(x => x.action === "init")} nuove coperture · target alzati ${cnt(x => x.ptAction === "Raises")}, abbassati ${cnt(x => x.ptAction === "Lowers")}`;
  const e = a.eps || {}, r = a.rev || {}, tr = (a.epsTrend || {})["+1y"] || {}, rv = (a.revisions || {})["+1y"] || {};
  const chg = (x, y) => isNum(x) && isNum(y) && y ? (x / y - 1) * 100 : null;
  const cell = (o, big) => o ? `<td class="num">${big ? accMoney(o.avg, accCur) : fNum(o.avg, 2)}</td><td class="num ${sign(o.growth)}">${isNum(o.growth) ? fPct(o.growth * 100, 1) : "—"}</td>` : "<td>—</td><td>—</td>";
  const est = `<table class="est"><thead><tr><th class="l">Stime medie</th><th colspan="2">Anno in corso</th><th colspan="2">Prossimo anno</th></tr>
    <tr><th></th><th>valore</th><th>crescita</th><th>valore</th><th>crescita</th></tr></thead>
    <tbody><tr><td class="l">Utile per azione</td>${cell(e["0y"])}${cell(e["+1y"])}</tr><tr><td class="l">Ricavi</td>${cell(r["0y"], true)}${cell(r["+1y"], true)}</tr></tbody></table>
    <div class="small">Stima dell'utile del prossimo anno: <b class="${sign(chg(tr.current, tr["30daysAgo"]))}">${fPct(chg(tr.current, tr["30daysAgo"]), 1)}</b> in 30 giorni,
    <b class="${sign(chg(tr.current, tr["90daysAgo"]))}">${fPct(chg(tr.current, tr["90daysAgo"]), 1)}</b> in 90 giorni
    ${isNum(rv.upLast30days) ? `<span class="muted">(${rv.upLast30days} analisti l'hanno alzata e ${rv.downLast30days || 0} abbassata nell'ultimo mese)</span>` : ""}</div>`;
  const acts = (a.actions || []).slice(0, 8);
  const table = acts.length ? `<table class="est acts"><thead><tr><th class="l">Data</th><th class="l">Società</th><th class="l">Azione</th><th class="l">Giudizio</th><th>Target</th></tr></thead><tbody>
    ${acts.map(x => `<tr><td class="l">${fDate(Date.parse(x.date) / 1000 + 43200, { day: "numeric", month: "short" })}</td><td class="l">${esc(x.firm)}</td>
      <td class="l ${x.action === "up" ? "up" : x.action === "down" ? "down" : ""}">${esc(ACT_IT[x.action] || x.action)}</td>
      <td class="l">${x.from && x.from !== x.to ? esc(x.from) + " → " : ""}${esc(x.to || "")}</td>
      <td class="num">${isNum(x.ptPrior) && x.ptPrior && x.ptPrior !== x.pt ? `${fPrice(x.ptPrior)} → ` : ""}${isNum(x.pt) && x.pt ? `<b class="${x.ptAction === "Raises" ? "up" : x.ptAction === "Lowers" ? "down" : ""}">${fPrice(x.pt)}</b>` : "—"}</td></tr>`).join("")}</tbody></table>` : `<div class="muted">Nessuna azione degli analisti negli ultimi 6 mesi</div>`;
  return `<div class="d-sec"><h3>Analisti</h3>${tgt}${bar}<div class="small" style="margin:8px 0">${last30}</div>${est}
    <h3 style="margin-top:14px">Ultime azioni delle banche d'affari</h3>${table}</div>`;
}

function rangeViz(lo, hi, price, target, title, ends) {
  const p = v => ((v - lo) / (hi - lo || 1) * 100).toFixed(1) + "%";
  // keep labels inside the track near either end
  const lbl = v => { const x = (v - lo) / (hi - lo || 1) * 100; return x > 88 ? "left:auto;right:-2px;transform:none" : x < 12 ? "left:-2px;transform:none" : ""; };
  return `<div class="rangeviz"><h3>${title}</h3><div class="track">
    ${ends ? `<div class="fill" style="left:${p(ends[0])};right:calc(100% - ${p(ends[1])})"></div>` : ""}
    <div class="mark" style="left:${p(price)}"><span style="${lbl(price)}">${fPrice(price)}</span></div>
    ${isNum(target) ? `<div class="mark tgt" style="left:${p(target)}" title="Target medio"><span style="bottom:auto;top:16px;${lbl(target)}">Target ${fPrice(target)}</span></div>` : ""}
    </div><div class="ends"><span>${fPrice(ends ? ends[0] : lo)}${ends ? " min" : ""}</span><span>${fPrice(ends ? ends[1] : hi)}${ends ? " max" : ""}</span></div>${isNum(target) ? "<div style='height:14px'></div>" : ""}</div>`;
}


// ------------------------------------------------------------ dates, pattern test texts, rotation map
const dayIT = iso => new Date(iso + "T12:00:00").toLocaleDateString("it-IT", { day: "numeric", month: "short", year: "numeric" });
const QCOL = { Leading: "--up", Weakening: "--warn", Lagging: "--down", Improving: "--accent" };
// Pattern test (reports/patterns.json, backtest.py --patterns): used by the stock detail to say "verificato" / "non
// verificato". No pattern is ever presented as "favorevole"; the full results are in the README.
const PT_INFO = {
  high52: "Il titolo chiude al prezzo più alto dell'ultimo anno e quel giorno si scambiano molte più azioni del solito. L'idea è che un massimo raggiunto con tanti scambi mostri un interesse forte dei compratori.",
  near52: "Il prezzo è a non più del 5% dal punto più alto dell'ultimo anno. È un modo semplice per dire che il titolo è forte.",
  mom12_1: "Il titolo è tra i migliori per rendimento nell'ultimo anno, senza contare l'ultimo mese (che spesso va in senso contrario). È il «momentum» classico: l'idea è che chi è salito tenda a continuare.",
  pull50: "Il titolo è in salita, ha rallentato ed è tornato ad appoggiarsi sulla media dei prezzi degli ultimi 50 giorni. L'idea è comprare un titolo forte durante una pausa.",
  range_break: "Per circa un mese e mezzo il prezzo si è mosso poco, dentro una fascia stretta; oggi esce dalla fascia verso l'alto con molti scambi. L'idea è che dopo una pausa parta un nuovo movimento.",
  golden: "La media dei prezzi degli ultimi 50 giorni sale sopra quella degli ultimi 200. Indica che la tendenza recente è diventata più forte di quella di lungo periodo. È un segnale lento: arriva quando il titolo è già salito da un po'.",
  leader: "Titolo con le medie a 20, 40 e 60 giorni in ordine rialzista che nell'ultimo mese ha fatto nettamente meglio di QQQ, senza essere già troppo lontano dalla media a 20. Era un setup della vecchia scheda Idee.",
  pullback: "Titolo con le medie a 40 e 60 giorni in salita, tornato vicino alla media a 20 giorni. Era un setup della vecchia scheda Idee.",
  bull_x: "La media dei prezzi a 20 giorni ha appena superato quella a 60 giorni: il breve periodo torna più forte del medio. Era un setup della vecchia scheda Idee.",
};
const pt = { data: null };
const dayShort = iso => new Date(iso + "T12:00:00").toLocaleDateString("it-IT", { day: "numeric", month: "short" });
// signed points; a value that rounds to 0,00 is shown with more digits (the golden cross median is +0,0003)
const ptPts = v => !isNum(v) ? "—" : (v > 0 ? "+" : "") + fNum(v, v !== 0 && Math.abs(v) < 0.005 ? 4 : 2);
const ptEdge = p => p.favorable && p.horizons["3M"].vsAllMedian < 0.5;   // passed, but the typical case is barely above the others

function ptSay(p, P) {
  const h = p.horizons["3M"], all = P.all.horizons["3M"];
  if (p.favorable)
    return `Ha superato il test${ptEdge(p) ? ", ma il vantaggio è minimo" : ""} (ha battuto QQQ a 3 mesi nel ${pctR(h.beat)} dei casi contro il ${pctR(all.beat)}
      di tutti i titoli) e, avendo provato ${P.patterns.length} pattern, potrebbe essere dovuto al caso.`;
  if (h.vsAll >= 0.5 && h.vsAllMedian <= 0)
    return `In media ha fatto meglio degli altri titoli (${ptPts(h.vsAll)} punti a 3 mesi), ma il caso tipico no: la mediana è negativa
      (${ptPts(h.vsAllMedian)}). Il vantaggio viene da pochi titoli saliti molto.`;
  if (h.vsAll > 0 && h.vsAllMedian <= 0)
    return `Il vantaggio medio sugli altri titoli è troppo piccolo (${ptPts(h.vsAll)} punti a 3 mesi) e nel caso tipico ha fatto peggio (mediana ${ptPts(h.vsAllMedian)}).`;
  if (h.vsAll <= 0)
    return `In media ha fatto peggio degli altri titoli (${ptPts(h.vsAll)} punti a 3 mesi; mediana ${ptPts(h.vsAllMedian)}).`;
  return "Non rispetta tutte le condizioni: passa sopra quelle con ❌ per vedere i numeri.";
}

// Rotation map of themes and sectors vs QQQ (Mercato → Settori), from /api/rotation (same calculation as the old report)
const rot = { data: null, grp: LS.get("rotGrp", "themes"), at: 0 };
async function loadRotation() {
  if (!rot.data || Date.now() - rot.at > 5 * 60_000) {
    rot.at = Date.now();
    try { rot.data = await getJSON("/api/rotation"); } catch { /* keep the previous one */ }
  }
  if (rot.data) renderRRG(rot.data);
}
function renderRRG(R) {
  $$("[data-grp-seg] button").forEach(b => b.classList.toggle("on", b.dataset.grp === rot.grp));
  drawRRG($("#rrg"), R[rot.grp], groupTip, "Rendimento relativo a 1 mese vs QQQ (punti) →");
}
// rotation chart: x = 1-month return vs the reference, y = 1-week return vs the reference (also used by the ETF tab)
// opts.fit: axes fitted to the data (zero always visible); opts.labels: Set of the only names written (others on hover)
function drawRRG(el, groups, tipFn, xLabel, opts = {}) {
  el.innerHTML = "";
  if (!groups?.length) return;
  const W = el.clientWidth || 500, H = 360, m = { t: 14, r: 16, b: 30, l: 44 }, iw = W - m.l - m.r, ih = H - m.t - m.b;
  const span = (k, min) => { const lo = Math.min(0, d3.min(groups, d => d[k])), hi = Math.max(0, d3.max(groups, d => d[k])), pad = Math.max(min / 4, (hi - lo) * 0.08); return [lo - pad, hi + pad]; };
  const ex = Math.max(3, d3.max(groups, d => Math.abs(d.rs1m)) * 1.15), ey = Math.max(2, d3.max(groups, d => Math.abs(d.rs1w)) * 1.2);
  const x = d3.scaleLinear().domain(opts.fit ? span("rs1m", 1) : [-ex, ex]).range([0, iw]).nice(), y = d3.scaleLinear().domain(opts.fit ? span("rs1w", 0.5) : [-ey, ey]).range([ih, 0]).nice();
  const svg = d3.select(el).append("svg").attr("width", W).attr("height", H).attr("role", "img").attr("aria-label", "Mappa di rotazione relativa");
  const g = svg.append("g").attr("transform", `translate(${m.l},${m.t})`);
  g.append("g").attr("class", "gridline").call(d3.axisLeft(y).ticks(5).tickSize(-iw).tickFormat(""));
  g.append("g").attr("class", "axis").call(d3.axisLeft(y).ticks(5).tickSize(0).tickPadding(6).tickFormat(v => (v > 0 ? "+" : "") + v)).select(".domain").remove();
  g.append("g").attr("class", "axis").attr("transform", `translate(0,${ih})`).call(d3.axisBottom(x).ticks(6).tickSize(0).tickPadding(8).tickFormat(v => (v > 0 ? "+" : "") + v)).select(".domain").remove();
  g.append("line").attr("x1", x(0)).attr("x2", x(0)).attr("y1", 0).attr("y2", ih).attr("stroke", css("--baseline"));
  g.append("line").attr("x1", 0).attr("x2", iw).attr("y1", y(0)).attr("y2", y(0)).attr("stroke", css("--baseline"));
  [["Leading", iw - 6, 12, "end"], ["Weakening", iw - 6, ih - 6, "end"], ["Lagging", 6, ih - 6, "start"], ["Improving", 6, 12, "start"]]
    .forEach(([t, px, py, a]) => g.append("text").attr("class", "rrg-q").attr("x", px).attr("y", py).attr("text-anchor", a).text(QLAB[t]));
  const pts = g.selectAll("g.pt").data(groups).join("g").attr("class", "pt").attr("transform", d => `translate(${x(d.rs1m)},${y(d.rs1w)})`);
  pts.append("circle").attr("r", 12).attr("fill", "transparent");
  pts.append("circle").attr("r", d => 4 + Math.sqrt(d.n) * 1.3).attr("fill", d => css(QCOL[d.quadrant])).attr("stroke", css("--surface")).attr("stroke-width", 2);
  // phase 8B.1: labels never overlap each other or the dots and never leave the chart. Each point is numbered (1 = the most
  // ahead on the horizontal axis); the full name is written where a free place exists, otherwise only its number.
  // The numbered list under the chart has every name and value (reachable by touch and keyboard).
  const order = groups.slice().sort((a, b) => b.rs1m - a.rs1m), num = new Map(order.map((d, i) => [d.name, i + 1]));
  const placed = groups.map(d => { const r = 4 + Math.sqrt(d.n) * 1.3 + 1; return { x: x(d.rs1m) - r, y: y(d.rs1w) - r, w: 2 * r, h: 2 * r }; });
  g.selectAll("text.rrg-q").each(function () { const b = this.getBBox(); placed.push({ x: b.x - 2, y: b.y - 1, w: b.width + 4, h: b.height + 2 }); });
  const free = b => b.x >= 0 && b.y >= 0 && b.x + b.w <= iw && b.y + b.h <= ih && !placed.some(p => b.x < p.x + p.w && p.x < b.x + b.w && b.y < p.y + p.h && p.y < b.y + b.h);
  const layer = g.append("g").attr("class", "rrg-labels");
  const narrow = W < 560;
  const byRoom = groups.slice().sort((a, b) => b.n - a.n);
  for (const d of byRoom) {
    const ox = x(d.rs1m), oy = y(d.rs1w), r = 4 + Math.sqrt(d.n) * 1.3;
    const want = !narrow && (!opts.labels || opts.labels.has(d.name));
    const tries = (txt, far) => {
      const t = layer.append("text").attr("class", "rrg-label").text(txt);
      const bb = t.node().getBBox(), w = bb.width, h = Math.ceil(bb.height) + 1, top = -bb.y;   // real text box (font metrics)
      const cand = [[r + 4, 4], [-r - 4 - w, 4], [r + 2, -r - 2], [r + 2, r + 12], [-r - 2 - w, -r - 2], [-r - 2 - w, r + 12], [-w / 2, -r - 4], [-w / 2, r + 13]];
      for (const dy of far ? [0, 12, -12, 24, -24, 36, -36, 48, -48, 60, -60] : [0, 12, -12, 24, -24]) for (const [cx, cy] of cand) {
        const b = { x: ox + cx, y: oy + cy + dy - top - 0.5, w, h };
        if (free(b)) { t.attr("x", ox + cx).attr("y", oy + cy + dy); placed.push(b); return true; }
      }
      t.remove(); return false;
    };
    if (want && tries(d.name)) continue;
    if (!tries(String(num.get(d.name)), true)) {   // last resort: the number right on the dot, in white
      layer.append("text").attr("class", "rrg-num-in").attr("x", ox).attr("y", oy + 3.5).attr("text-anchor", "middle").text(num.get(d.name));
    }
  }
  pts.attr("tabindex", 0).attr("data-rrg", d => d.name).attr("role", "button").attr("aria-label", d => `${num.get(d.name)}. ${d.name}`);
  svg.on("click", ev => { if (!ev.target.closest("g.pt")) hideTip(); });
  pts.on("mousemove", (ev, d) => showTip(tipFn(d), ev)).on("mouseleave", hideTip)
    .on("click", (ev, d) => { ev.stopPropagation(); showTip(tipFn(d), ev); })
    .on("focus", function (ev, d) { const b = this.getBoundingClientRect(); showTip(tipFn(d), { clientX: b.right, clientY: b.bottom }); }).on("blur", hideTip);
  const listOpen = innerWidth < 700 ? "open" : "";
  const qn = q => QLAB[q] || q;
  const list = document.createElement("details");
  list.className = "rrg-list"; if (listOpen) list.open = true;
  list.innerHTML = `<summary><span class="small">Elenco numerato con nomi e valori (${groups.length})</span></summary>
    <div class="table-wrap"><table class="scr mini rrg-tbl"><thead><tr><th>#</th><th class="l">Nome</th><th class="l">Zona</th><th title="valore sull'asse orizzontale, in punti">→ x</th><th title="valore sull'asse verticale, in punti">↑ y</th></tr></thead><tbody>
    ${order.map(d => `<tr tabindex="0" data-rrgrow="${esc(d.name)}"><td>${num.get(d.name)}</td><td class="l">${esc(d.name)}</td><td class="l"><span class="q ${d.quadrant}">${esc(qn(d.quadrant))}</span></td><td class="${sign(d.rs1m)}">${fChg(d.rs1m)}</td><td class="${sign(d.rs1w)}">${fChg(d.rs1w)}</td></tr>`).join("")}</tbody></table></div>`;
  el.appendChild(list);
  const hl = (name, on) => pts.filter(d => d.name === name).classed("hl", on);
  list.addEventListener("mouseover", e => { const r = e.target.closest("[data-rrgrow]"); if (r) hl(r.dataset.rrgrow, true); });
  list.addEventListener("mouseout", e => { const r = e.target.closest("[data-rrgrow]"); if (r) hl(r.dataset.rrgrow, false); });
  list.addEventListener("focusin", e => { const r = e.target.closest("[data-rrgrow]"); if (r) hl(r.dataset.rrgrow, true); });
  list.addEventListener("focusout", e => { const r = e.target.closest("[data-rrgrow]"); if (r) hl(r.dataset.rrgrow, false); });
  svg.append("text").attr("class", "ref-label").attr("x", m.l + iw).attr("y", H - 2).attr("text-anchor", "end").text(xLabel);
}
function groupTip(d) {
  return `<div class="tip-h">${d.kind === "theme" ? "Tema" : "Settore"} · ${d.n} titoli</div><b>${esc(d.name)}</b> <span class="q ${d.quadrant}">${QLAB[d.quadrant]}</span>
    <div class="tip-row" style="margin-top:6px"><span>Punteggio trend</span><b class="${sign(d.score)}">${d.score > 0 ? "+" : ""}${fNum(d.score, 1)}</b></div>
    <div class="tip-row"><span>vs QQQ 1M / 1S</span><b>${fChg(d.rs1m)} / ${fChg(d.rs1w)}</b></div>
    <div class="tip-row"><span>Medie in ordine rialzista</span><b>${Math.round(d.bull)}%</b></div>
    <div class="tip-row"><span>Sopra medie 20 / 40 / 60</span><b>${pctR(d.above20)} / ${pctR(d.above40)} / ${pctR(d.above60)}</b></div>
    <div class="tip-row"><span>Migliori</span><b>${esc(d.leaders.join(", "))}</b></div>`;
}
const scoreBar = v => {
  const w = Math.min(50, Math.abs(v) / 2);
  return `<span class="sbar"><span class="trk"><i style="${v >= 0 ? `left:50%` : `right:50%`};width:${w}%;background:var(${v >= 0 ? "--up" : "--down"})"></i></span><span class="num ${sign(v)}">${v > 0 ? "+" : ""}${fNum(v, 0)}</span></span>`;
};

document.addEventListener("click", e => {
  const b = e.target.closest("[data-grp-seg] button");
  if (b) { rot.grp = b.dataset.grp; LS.set("rotGrp", rot.grp); if (rot.data) renderRRG(rot.data); }
});

// ------------------------------------------------------------ Ricerca → ETF (etf.py, /api/etf)
// What is rising, why (computed), whether it makes sense for my portfolio. The momentum rules failed the test
// (etf_backtest.py): nothing here says "favorevole" or "investi", only "non verificato". Texts fixed, numbers from data.
const etfS = { data: null, at: 0, grp: LS.get("etfGrp", "Tutti"), ft: LS.get("etfTrend", ""), fb: LS.get("etfBuy", ""), sort: { key: LS.get("etfSort", "r3m"), dir: -1 }, retry: null, why: {} };
const ETF_PER = [["r1w", "1 settimana"], ["r2w", "2 settimane"], ["r1m", "1 mese"], ["r3m", "3 mesi"], ["r6m", "6 mesi"], ["r1y", "1 anno"], ["r3y", "3 anni"]];
const ETF_PER_Y = { r1w: "2 giorni", r2w: "1 settimana", r1m: "1 settimana", r3m: "1 mese", r6m: "1 mese", r1y: "3 mesi", r3y: "6 mesi" };
const TREND_CLS = { "Rialzista": "up", "Laterale": "flat", "Ribassista": "down" };
// phase 8B.1: fuller explanation, written from etf.trend_word / etf_opportunity.trend_word and the E2 conditions (rules unchanged)
const ETF_TREND_INFO = `<b>Trend</b> (regola approvata, la stessa nella tabella ETF e nel modello delle opportunità ETF).<br><br>
  <b>Cosa significa.</b> Descrive la direzione recente del prezzo dell'ETF rispetto alle sue medie.<br>
  <b>Indicatori e periodo.</b> Il prezzo di chiusura dell'ultima seduta, la media semplice delle ultime <b>50</b> chiusure (circa 2 mesi e mezzo)
  e quella delle ultime <b>200</b> (circa 10 mesi), con i prezzi in euro.<br>
  <b>Condizioni.</b> <b>Rialzista</b>: prezzo sopra la media 50 <b>e</b> media 50 sopra la media 200. <b>Ribassista</b>: prezzo sotto la media 50 <b>e</b>
  media 50 sotto la media 200. <b>Laterale</b>: tutti gli altri casi (per esempio prezzo sopra la media 50 ma media 50 ancora sotto la 200).
  «—» quando mancano 200 sedute di prezzi.<br>
  <b>Cosa NON significa.</b> Non è una previsione né un segnale di acquisto o vendita: stare sopra la media 200 <b>non ha superato il test</b> come regola di acquisto (M2).<br><br>
  <b>Da non confondere con:</b><br>
  · <b>trend assoluto</b> (questo): l'ETF confrontato solo con le proprie medie;<br>
  · <b>forza relativa</b>: rendimento dell'ETF meno quello del suo benchmark, in punti, a 1, 6 o 12 mesi; un ETF può essere Rialzista ma più debole del benchmark;<br>
  · <b>cambio di trend recente</b>: nel modello delle opportunità ETF, la forza relativa a 6 mesi salita di almeno 1 punto in 21 sedute (L4) o quella a 1 mese salita di almeno 0,5 punti in 5 sedute (S4);<br>
  · <b>rischio e volatilità</b>: quanto oscilla il prezzo e quanto è sceso dal massimo; un trend Rialzista può avere volatilità alta.<br><br>
  Il mini-grafico mostra gli ultimi 6 mesi con la media 200 tratteggiata.`;
const trendWord = r => r.trend ? `<span class="trend-w ${TREND_CLS[r.trend]}">${r.trend}</span>` : `<span class="muted small">—</span>`;
// 6-month mini chart: closes and the 200-day average (dashed)
function sparkSVG(sp, w = 90, h = 26) {
  if (!sp?.p?.length) return "";
  const vals = sp.p.concat(sp.ma200).filter(isNum), lo = Math.min(...vals), hi = Math.max(...vals), n = sp.p.length;
  const X = i => (i / (n - 1)) * (w - 2) + 1, Y = v => h - 1 - ((v - lo) / (hi - lo || 1)) * (h - 2);
  const line = arr => arr.map((v, i) => isNum(v) ? `${X(i).toFixed(1)},${Y(v).toFixed(1)}` : null).filter(Boolean).join(" ");
  const up = sp.p[n - 1] >= sp.p[0];
  return `<svg class="spark" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" role="img" aria-label="Ultimi 6 mesi e media 200">
    <polyline points="${line(sp.ma200)}" fill="none" stroke="${css("--ink-2")}" stroke-width="1" stroke-dasharray="3 2"/>
    <polyline points="${line(sp.p)}" fill="none" stroke="${css(up ? "--up" : "--down")}" stroke-width="1.4"/></svg>`;
}
const BUY_INFO = `<b>Ha senso comprare?</b> Regole approvate, nell'ordine; la prima che vale decide: <b>E1</b> prodotto a leva → solo informazione; <b>E2</b> trend ribassista → Evita;
  <b>E3</b> si sovrappone al tuo portafoglio → Evita; <b>E4</b> patrimonio sotto 100 milioni → Evita; <b>A0</b> trend non calcolabile → Attendi; <b>A1</b> trend laterale → Attendi;
  <b>A2</b> TER sopra lo 0,50% → Attendi; <b>A3</b> «neutro» per il tuo portafoglio → Attendi; <b>R1</b> rischio di essere arrivati tardi alto → Entra su ritracciamento
  (entrata alla media 50); altrimenti <b>Entra ora</b>. «Solo mercato» usa le stesse regole senza E3 e A3. Il momentum 12-1 è solo un'informazione.<br><br>
  <b>Non verificato</b>: le regole di momentum e trend non hanno superato il test sulle categorie; ogni verdetto viene salvato nel diario degli ETF per misurarlo dal vivo.`;
const buyBadge = (v, big) => v ? `<span class="act ${big ? "big " : ""}${VERDICT_CLS[v] || "hold"}">${esc(v)}</span>` : `<span class="muted small">—</span>`;
const ETF_GROUPS = ["Tutti", "Globali", "Aree e paesi", "Settori", "Temi", "Stili e fattori", "Obbligazionari", "Oro e materie prime"];
const FIT_CLS = { "diversifica": "acc", "neutro": "hold", "si sovrappone": "red" };
const fitBadge = f => f ? `<span class="act ${FIT_CLS[f.verdict]}">${esc(f.verdict[0].toUpperCase() + f.verdict.slice(1))}</span>` : `<span class="muted small">—</span>`;
const ETF_FISCAL_INFO = `<b>Tasse sugli ETF (indicazioni generali, da verificare con Fineco).</b> I guadagni degli ETF UCITS sono <b>redditi di capitale</b>, tassati al 26%,
  e <b>non si compensano</b> con le minusvalenze dello zainetto; le perdite invece sono redditi diversi e compensano guadagni su azioni, ETC e derivati.
  Per gli <b>ETC</b> (oro, argento, materie prime) guadagni e perdite sono entrambi redditi diversi, compensabili. Per la parte in titoli di Stato (come i BTP) è prevista
  un'aliquota agevolata del 12,5%.<br><br><b>Accumulazione</b>: i dividendi restano nell'ETF e non paghi tasse finché non vendi. <b>Distribuzione</b>: li incassi e paghi subito il 26%.<br>
  <b>Hedged</b> (cambio coperto): l'ETF elimina l'effetto del cambio euro/dollaro, con un piccolo costo in più.`;
const ETF_SAT_INFO = `<b>Satellite.</b> Nei portafogli professionali i temi (idrogeno, uranio, spazio…) si usano in <b>piccole quote</b> accanto a ETF ampi, il «nucleo».
  Sono più volatili e spesso gli ETF nascono vicino al picco del tema: per esempio gli ETF sull'idrogeno lanciati nel 2021, poco prima di un forte calo.`;
const ETF_OVERLAP_INFO = `<b>Sovrapposizione</b>: per ciascuno dei primi 10 titoli dell'ETF (dall'ETF americano equivalente) somma il più piccolo tra il suo peso nell'ETF e il suo peso nel tuo
  portafoglio, guardando dentro i tuoi fondi. Usa <b>solo i primi 10 titoli</b>: per gli ETF molto ampi (MSCI World, All-World) il valore reale è più alto di quello mostrato.
  I titoli sono confrontati per ISIN quando c'è, altrimenti per nome della società; le due classi di azioni della stessa società (per esempio Samsung ordinarie e
  privilegiate, Alphabet A e C) contano come una.`;
const ETF_SHARE_INFO = `<b>Quota dell'ETF in titoli che già possiedi</b>: la somma dei pesi, nell'ETF, dei suoi primi 10 titoli che hai già (direttamente o dentro i tuoi fondi),
  per quanto poco pesino nel tuo portafoglio. È un'informazione: il verdetto usa la sovrapposizione in punti, che tiene conto di quanto pesano davvero.`;
const ETF_FIT_INFO = `Regole: <b>si sovrappone</b> se la sovrapposizione è almeno 25 punti, o la correlazione con il tuo portafoglio è almeno 0,85, o investendo il 10% del portafoglio
  sale di almeno 1 punto la tua concentrazione più alta (tecnologia, USA o dollaro). <b>Diversifica</b> se la sovrapposizione è sotto 10 punti, la correlazione sotto 0,60 e
  il 10% fa scendere di almeno 1 punto una delle tre senza farne salire nessuna di più di 0,5. Altrimenti <b>neutro</b>. Il dollaro è stimato dal peso degli USA.`;
const ETF_LATE_INFO = `<b>Rischio di essere arrivati tardi</b>: confronta quanto il prezzo è lontano oggi dalla sua media a 200 giorni con la storia della stessa categoria negli ultimi 5 anni
  (o quella disponibile). <b>Alto</b> se oggi è più lontano che nel 90% dei giorni, <b>medio</b> tra il 70% e il 90%, <b>basso</b> altrimenti. Descrive, non prevede.`;
const ETF_FALLBACK_INFO = `<b>*</b> Rendimento calcolato con uno <b>storico di ripiego</b>: i prezzi di Borsa Italiana dell'ETF sono incompleti, quindi si usano
  quelli dello stesso ETF su Xetra (Francoforte) o, se mancano anche quelli, l'ETF americano sullo stesso indice convertito in euro con il cambio di ogni giorno.
  Il prodotto che compri a Milano può aver reso un po' diversamente. La fonte è scritta nel pannello dell'ETF.`;
const ETF_MOM_INFO = `<b>Momentum 12-1</b>: rendimento in euro da 12 mesi fa a 1 mese fa. Forte = terzo migliore delle categorie, debole = ultimo terzo.
  Questa regola <b>non ha superato il test</b> sulle categorie (risultati nel README): è un'informazione, <b>non verificata</b>.`;
const ETF_TEST_INFO = `<b>Test delle regole sulle categorie</b> (2000–2026, ETF americani): momentum 12-1 (M1) +0,37 punti ogni 3 mesi contro la soglia di +0,5 fissata prima
  del test, <b>non superato</b>; sopra la media 200 (M2) non batte le altre categorie e non riduce la perdita massima nei crolli secondo la soglia fissata, <b>non verificato</b>.
  Tabella completa nel README.`;
const hm = iso => iso ? iso.slice(11, 16) : "";
async function loadEtf() {
  clearTimeout(etfS.retry);
  if (!etfS.data || etfS.data.status !== "ok" || Date.now() - etfS.at > 5 * 60_000) {
    try { etfS.data = await getJSON("/api/etf"); etfS.at = Date.now(); } catch { etfS.data = { status: "error", error: "server non raggiungibile" }; }
  }
  if (state.view === "etf") renderEtf();
  const st = etfS.data.status === "ok" ? etfS.data.dataStatus : etfS.data;
  if (etfS.data.status === "loading" || st?.running) etfS.retry = setTimeout(() => { etfS.at = 0; loadEtf(); }, 10_000);
  else if (st?.retryAt) etfS.retry = setTimeout(() => { etfS.at = 0; loadEtf(); }, Math.max(60_000, new Date(st.retryAt) - Date.now() + 60_000));
}
// justETF writes in English: the page shows Italian words (unknown ones stay as they are)
const ETF_IT = {
  "Accumulating": "Accumulazione", "Distributing": "Distribuzione", "Physical": "Fisica", "Synthetic": "Sintetica (swap)",
  "Full replication": "replica completa", "Optimized sampling": "campionamento ottimizzato", "Sampling": "campionamento",
  "Unfunded swap": "swap", "Physically backed": "garantito dal metallo fisico", "Currency unhedged": "Non coperto",
  "Currency hedged": "Coperto (hedged)", "Other": "Altro", "United States": "USA", "Japan": "Giappone", "United Kingdom": "Regno Unito",
  "Germany": "Germania", "France": "Francia", "Switzerland": "Svizzera", "Netherlands": "Paesi Bassi", "Italy": "Italia",
  "Ireland": "Irlanda", "Spain": "Spagna", "South Korea": "Corea del Sud", "China": "Cina", "Brazil": "Brasile", "Mexico": "Messico",
  "Singapore": "Singapore", "Luxembourg": "Lussemburgo", "Hong Kong": "Hong Kong", "Denmark": "Danimarca", "Israel": "Israele",
  "Finance": "Finanza", "Technology": "Tecnologia", "Industrials": "Industria", "Healthcare": "Sanità",
  "Consumer Non-Cyclicals": "Beni di prima necessità", "Consumer Cyclicals": "Consumi discrezionali", "Non-Energy Materials": "Materiali",
  "Energy": "Energia", "Business Services": "Servizi alle imprese", "Utilities": "Utility", "Non-Corporate": "Enti non societari",
  "Sovereign": "Titoli di Stato", "Telecommunication": "Telecomunicazioni", "Consumer Services": "Servizi ai consumatori" };
const MONTHS_EN = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const MONTHS_IT = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"];
const etfIt = v => v == null ? v : ETF_IT[v] ?? String(v).replace(new RegExp(MONTHS_EN.join("|")), m => MONTHS_IT[MONTHS_EN.indexOf(m)]).replace(/^As of /, "Dati al ");
const etfRow = isin => etfS.data?.rows?.find(r => r.isin === isin);
const etfFit = isin => etfS.data?.fit?.[isin];
function momText(t, months) {
  return t ? `momentum ${t}${months ? ` da ${months} ${months === 1 ? "mese" : "mesi"}` : ""}, <b>non verificato</b>` : "momentum non calcolabile";
}
function lateText(L) {
  if (!L) return "storia troppo breve per confrontare la distanza dalla media 200";
  return `rischio di essere arrivati tardi <b>${L.level}</b>: ${fPct(L.dist, 1)} dalla media 200; oggi è più lontano dalla media di quanto sia stato nel
    ${fNum(L.percentile, [70, 90].some(t => Math.abs(L.percentile - t) < 1) ? 1 : 0)}% dei giorni degli ultimi ${fNum(L.years, 0)} anni`;   // a decimal near the thresholds
}
// what is missing is said in words, with the time of the next try, never with dashes or half verdicts
function etfNotice(D) {
  if (D.status !== "ok") return "";
  const st = D.dataStatus || {}, out = [];
  if (!st.today) out.push(st.running ? `Calcolo dei dati di oggi in corso: la tabella mostra quelli del ${dayIT(st.dataDay)}.`
    : `Dati del <b>${dayIT(st.dataDay)}</b>: oggi ${st.error ? `${esc(st.error)}; nuovo tentativo alle ${hm(st.retryAt)}` : "il calcolo non è ancora partito"}.`);
  const miss = D.rows.filter(r => r.noPrices).length;
  if (miss) out.push(`${miss} ETF senza prezzi da Yahoo oggi: le loro righe lo indicano.`);
  if (D.portfolioLoaded && !D.fitComplete) out.push(!D.corrReady ? "Prezzi del tuo portafoglio in scaricamento: «Per il mio portafoglio» e il verdetto personale arrivano tra poco; intanto vedi il verdetto del solo mercato."
    : `<b>Prezzi storici del tuo portafoglio non disponibili</b> (Yahoo): senza correlazione «Per il mio portafoglio» non è calcolabile; nuovo tentativo alle ${hm(D.pricesRetryAt)}. Intanto vedi il verdetto del solo mercato.`);
  return out.length ? `<p class="warn-box etf-notice">${out.join("<br>")}</p>` : "";
}
function renderEtf() {
  etfModeBar();                                                       // phase 6A: market table or UCITS catalogue
  if (etfC.mode === "cat") { if (!etfC.drawn) loadEtfCat(); return; }
  const el = $("#etfBody"), D = etfS.data;
  if (!D || D.status === "error") { el.innerHTML = `<div class="card empty"><b>Prezzi degli ETF non disponibili</b>${D?.error ? ` (${esc(D.error)})` : ""}.${D?.retryAt ? ` Nuovo tentativo alle ${hm(D.retryAt)}.` : ""}</div>`; return; }
  if (D.status === "loading") { el.innerHTML = `<div class="card empty">Calcolo in corso: scarico i prezzi di 63 ETF e le composizioni (qualche minuto la prima volta al giorno)…</div>`; return; }
  const stale = D.rows.filter(r => r.stale).length, buy = isin => D.buy?.[isin], personal = D.fitComplete;
  const { key, dir } = etfS.sort;
  const BUY_ORDER = { "Entra ora": 4, "Entra su ritracciamento": 3, "Attendi": 2, "Evita": 1, "Solo informazione": 0 };
  const verdictOf = isin => personal ? buy(isin)?.verdict : buy(isin)?.market.verdict;
  // two filters that add up (and add up with the group): Trend and «Ha senso comprare?» (the verdict shown in the column)
  const NONE = "non calcolabile", trendOf = r => r.trend || NONE, buyOf = r => verdictOf(r.isin) || NONE;
  const okT = (r, v = etfS.ft) => !v || trendOf(r) === v, okB = (r, v = etfS.fb) => !v || buyOf(r) === v;
  const rowsGrp = D.rows.filter(r => etfS.grp === "Tutti" || r.group === etfS.grp);
  const rowsAll = rowsGrp.filter(r => okT(r) && okB(r)), filtered = !!(etfS.ft || etfS.fb);
  const fSel = (k, label, order, of, ok) => {
    const vals = order.filter(v => v === etfS[k] || rowsGrp.some(r => of(r) === v)).concat(rowsGrp.some(r => !order.includes(of(r))) ? [NONE] : []);
    const n = v => rowsGrp.filter(r => of(r) === v && ok(r)).length;            // how many with this value AND the other filter
    return `<label class="cat-f"><span>${label}</span><select data-etff="${k}"><option value="">tutti</option>
      ${[...new Set(vals)].map(v => `<option value="${esc(v)}" ${etfS[k] === v ? "selected" : ""}>${esc(v)} (${n(v)})</option>`).join("")}</select></label>`;
  };
  const filtersHTML = `<div class="etf-filters">${fSel("ft", "Trend", ["Rialzista", "Laterale", "Ribassista"], trendOf, r => okB(r))}
    ${fSel("fb", `Ha senso comprare? <span class="muted">(${personal ? "per te" : "solo mercato"})</span>`, Object.keys(BUY_ORDER), buyOf, r => okT(r))}
    ${filtered ? `<button class="link-btn" data-etfclear>Togli i filtri</button>` : ""}</div>`;
  const val = (r, k) => k === "fit" ? (personal ? ({ "diversifica": 1, "neutro": 0, "si sovrappone": -1 }[etfFit(r.isin)?.verdict] ?? null) : null) : k === "name" ? r.category
    : k === "trend" ? ({ "Rialzista": 1, "Laterale": 0, "Ribassista": -1 }[r.trend] ?? null) : k === "buy" ? (BUY_ORDER[verdictOf(r.isin)] ?? null) : r[k];
  const rows = rowsAll.slice().sort((a, b) => { const va = val(a, key), vb = val(b, key); if (va == null) return 1; if (vb == null) return -1; return (typeof va === "string" ? va.localeCompare(vb) : va - vb) * dir; });
  const pc = v => `<span class="${sign(v)}">${isNum(v) ? fPct(v, 1) : "—"}</span>`;
  const pcs = (r, k) => `${pc(r[k])}${r.fallback && isNum(r[k]) ? '<sup class="fb">*</sup>' : ""}`;
  const RET = ["r1w", "r1m", "r3m", "r1y", "r3y"];
  // column priorities: p2 hidden below 1100 px, p3 below 860, p4 on phones (where "Per il mio portafoglio" goes under the verdict)
  const PRIO = { r1w: "p2", r3y: "p2", r1m: "p3", r1y: "p3", ter: "p3", trend: "p4", fit: "p4" }, pr = k => PRIO[k] || "";
  const cols = [["name", "ETF", "l"], ...RET.map(k => [k, ETF_PER.find(x => x[0] === k)[1]]), ["trend", "Trend", "l"], ["ter", "TER"], ["buy", "Ha senso comprare?", "l"], ["fit", "Per il mio portafoglio", "l"]];
  const waitFit = D.portfolioLoaded ? `<span class="muted small">in attesa dei prezzi del portafoglio${D.pricesRetryAt ? ` (nuovo tentativo alle ${hm(D.pricesRetryAt)})` : ""}</span>` : `<span class="muted small">portafoglio non caricato</span>`;
  const nameCell = r => `<td class="l etf-name"><b>${esc(r.category)}</b><div class="muted small">${esc(r.name || "")}${state.watch.has(r.yahoo) ? " ★" : ""}${personal && etfFit(r.isin)?.held ? " · <b>lo possiedi</b>" : ""}</div></td>`;
  const buyCell = r => { const b = buy(r.isin); if (!b) return `<td class="l"><span class="muted small">non calcolabile</span></td>`;
    return `<td class="l">${buyBadge(verdictOf(r.isin))}${personal ? (b.verdict !== b.market.verdict ? `<div class="muted small">mercato: ${esc(b.market.verdict)}</div>` : "") : `<div class="muted small">solo mercato</div>`}${personal ? `<div class="sub2 s4">${fitBadge(etfFit(r.isin))}</div>` : ""}</td>`; };
  const fitCell = r => `<td class="l p4">${personal ? fitBadge(etfFit(r.isin)) : waitFit}</td>`;
  const terCell = r => `<td class="p3">${isNum(r.ter) ? fNum(r.ter, 2) + "%" : "—"}</td>`;
  const rowHTML = r => r.noPrices
    ? `<tr data-etf="${esc(r.isin)}">${nameCell(r)}<td colspan="${RET.length + 1}" class="l"><span class="down small"><b>prezzi non disponibili oggi</b> (Yahoo non li ha dati)</span></td>${terCell(r)}${buyCell(r)}${fitCell(r)}</tr>`
    : `<tr data-etf="${esc(r.isin)}">${nameCell(r)}${RET.map(k => `<td class="${pr(k)}">${pcs(r, k)}</td>`).join("")}<td class="l trend-c p4">${trendWord(r)}${sparkSVG(r.spark, 64, 20)}</td>${terCell(r)}${buyCell(r)}${fitCell(r)}</tr>`;
  const P = RET.includes(key) || ["r2w", "r6m"].includes(key) ? key : "r3m", PL = ETF_PER.find(x => x[0] === P)[1];
  el.innerHTML = `${scopeNote("Verdetti esplorativi: regole esplicite ma non validate · rendimenti in euro · non è una consulenza finanziaria.",
      `I verdetti «Ha senso comprare?» seguono regole esplicite ma non verificate ${info(ETF_TEST_INFO)}: le regole di momentum e trend non hanno superato
      il test sulle categorie, e i verdetti vengono salvati ogni giorno nel diario degli ETF per misurarli dal vivo. Rendimenti in euro, quello che guadagni tu.`)}
    ${stale ? `<p class="small data-note">! <b>${stale} ETF hanno dati di justETF con più di 6 mesi</b>: rilancia etf_universe.py.</p>` : ""}
    ${etfNotice(D)}
    ${diversifyHTML(D)}
    <div class="card"><div class="card-h"><h2>Tutti gli ETF</h2><span class="card-meta">${filtered ? `${rows.length} di ${rowsGrp.length}` : rows.length} ETF · clicca un'intestazione per ordinare, una riga per i dettagli · dati del ${dayIT(D.generated.slice(0, 10))}</span></div>
      <div class="chips">${ETF_GROUPS.map(g => `<button data-etfgrp="${esc(g)}" class="${g === etfS.grp ? "on" : ""}">${esc(g)}</button>`).join("")}</div>
      ${filtersHTML}
      <div class="table-wrap etf-wrap"><table class="scr etf-tbl"><thead><tr>${cols.map(([k, l, c]) => `<th class="${c || ""} ${pr(k)} ${key === k ? "sorted" + (dir > 0 ? " asc" : "") : ""}" data-etfsort="${k}">${l}${k === "fit" ? " " + info(ETF_FIT_INFO) : k === "trend" ? " " + info(ETF_TREND_INFO) : k === "buy" ? " " + info(BUY_INFO) : ""}</th>`).join("")}</tr></thead>
        <tbody>${rows.length ? rows.map(rowHTML).join("") : `<tr><td class="l" colspan="${cols.length}"><span class="muted">Nessun ETF ${etfS.grp === "Tutti" ? "" : `del gruppo «${esc(etfS.grp)}» `}con questi filtri.</span> <button class="link-btn" data-etfclear>Togli i filtri</button></td></tr>`}</tbody></table></div>
      <p class="muted small"><b>*</b> = storico di ripiego ${info(ETF_FALLBACK_INFO)} · Rendimenti in euro, dividendi inclusi per gli ETF ad accumulazione. Trend: <span class="trend-w up">Rialzista</span>
        <span class="trend-w flat">Laterale</span> <span class="trend-w down">Ribassista</span>, mini-grafico di 6 mesi con la media 200 tratteggiata ${info(ETF_TREND_INFO)}.
        «Ha senso comprare?»: verdetto per te (sotto, «mercato» se senza il tuo portafoglio sarebbe diverso), <b>non verificato</b> ${info(BUY_INFO)}. 2 settimane, 6 mesi, volatilità,
        perdita massima e momentum 12-1 sono nel pannello di ogni ETF.
        ${D.fitMissing?.length ? `${D.fitMissing.length} dei tuoi fondi non hanno una composizione (in scaricamento o non disponibile): i loro titoli non entrano nella sovrapposizione.` : ""}</p></div>
    ${etfWatchHTML(D)}
    <details class="card fold"><summary><span class="small"><b>Mappa di rotazione delle categorie</b> (rispetto all'All-World VWCE, ${PL} e ${ETF_PER_Y[P]}: segue la colonna ordinata, 3 mesi se non è un rendimento)</span></summary><div id="etfRrg" class="chart"></div>
      <p class="muted small">Scritti i nomi delle 5 categorie più avanti e delle 5 più indietro; le altre compaiono passando con il mouse sul punto.</p></details>
    <details class="card fold" id="etfDiary"><summary><span class="small"><b>Diario degli ETF</b>: com'è andato ogni verdetto dopo 1, 3 e 6 mesi</span></summary><div id="etfDiaryBody" class="muted small">Carico…</div></details>`;
  const rr = $("#etfRrg"), pts = D.rotation[P] || [];
  const ends = pts.slice().sort((a, b) => b.rs1m - a.rs1m), labels = new Set(ends.slice(0, 5).concat(ends.slice(-5)).map(x => x.name));
  rr.closest("details").addEventListener("toggle", () => drawRRG(rr, pts, d => `<div class="tip-h">Categoria</div><b>${esc(d.name)}</b> <span class="q ${d.quadrant}">${QLAB[d.quadrant]}</span>
      <div class="tip-row"><span>vs All-World ${PL} / ${ETF_PER_Y[P]}</span><b>${fChg(d.rs1m)} / ${fChg(d.rs1w)}</b></div>`, `Rendimento relativo a ${PL} vs All-World (punti) → · in verticale: ${ETF_PER_Y[P]}`,
      { fit: true, labels }), { once: true });
  $("#etfDiary").addEventListener("toggle", loadEtfDiary, { once: true });
}
async function loadEtfDiary() {
  const el = $("#etfDiaryBody");
  try { el.innerHTML = etfDiaryHTML(await getJSON("/api/etf/diary"), "1 mese") + etfDiaryHTML.more; } catch { el.textContent = "Diario degli ETF non disponibile al momento."; }
}
// ---------------------------------------------------------------- phase 6A: UCITS ETF catalogue and comparison
// A second mode of the ETF tab, next to the market table above (which stays as it is). Public data from etf_catalog/
// (rebuilt by hand with etf_catalog_build.py): identity, listings, costs, structure, exposure, sources. No verdict,
// no score, no winner; the portfolio is never read here.
const etfC = { mode: LS.get("etfMode", "market"), data: null, err: null, q: "", f: {}, sel: [], detail: null, item: null, cmp: null, cmpErr: null, drawn: false };
const ETF_CAT_AC = { azionario: "Azionari", obbligazionario: "Obbligazionari", monetario: "Monetari", materie_prime: "Materie prime" };
const CMP_LEVEL_CLS = { 1: "acc", 2: "wait", 3: "rev", 4: "red" };
const ETF_CAT_INFO = `<b>Come leggere il catalogo.</b> L'<b>ISIN</b> identifica la classe del fondo: lo stesso ETF può avere più ticker su borse diverse,
  ma resta una sola riga. La <b>valuta di negoziazione</b> (in cui lo compri) non è l'<b>esposizione valutaria</b> (le valute dei titoli che possiede),
  a meno che la classe sia coperta (hedged). Ogni dato ha la sua fonte e la sua data; un dato mancante resta «n.d.», mai zero.
  La disponibilità presso il tuo broker (Fineco) <b>non è verificata</b>.`;
const yn = v => v === true ? "coperta" : v === false ? "non coperta" : "n.d.";
const catPct = v => isNum(v) ? fNum(v, 2) + "%" : "n.d.";
const srcTag = f => f && (f.src || f.asOf) ? `<span class="cat-src">${esc(f.src || "")}${f.asOf ? ` · ${esc(dayIT(f.asOf.slice(0, 10)))}` : ""}</span>` : "";
const fvText = (f, fmt) => f == null || f.v == null || (Array.isArray(f.v) && !f.v.length) ? "n.d." : fmt ? fmt(f.v) : f.v === true ? "sì" : f.v === false ? "no" : String(f.v);
function etfModeBar() {
  const bar = $("#etfModeBar");
  if (!bar) return;
  bar.innerHTML = `<div class="seg etf-mode">${[["market", "Mercato ETF"], ["cat", "Catalogo UCITS e confronto"]].map(([k, l]) =>
    `<button data-etfmode="${k}" class="${etfC.mode === k ? "on" : ""}">${l}</button>`).join("")}</div>`;
  $("#etfBody").hidden = etfC.mode === "cat";
  $("#etfCatBody").hidden = etfC.mode !== "cat";
}
async function loadEtfCat() {
  if (!etfC.data) {
    try { etfC.data = await getJSON("/api/etf/catalog"); etfC.err = etfC.data.status === "ok" ? null : etfC.data.error; }
    catch { etfC.err = "server non raggiungibile"; }
  }
  renderEtfCat();
}
function etfCatRows() {
  const D = etfC.data, words = etfC.q.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").split(/\s+/).filter(Boolean);
  return (D?.rows || []).filter(r => {
    const hay = [r.isin, r.name, r.issuer, r.index, r.category, r.familyLabel, ...(r.tickers || [])].join(" ").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
    if (!words.every(w => hay.includes(w))) return false;
    return Object.entries(etfC.f).every(([k, v]) => !v || (k === "hedged" ? String(!!r.hedged) === v : String(r[k]) === v));
  });
}
function etfCatListHTML() {
  const rows = etfCatRows(), full = etfC.sel.length >= 4;
  if (!rows.length) return `<p class="empty">Nessun ETF corrisponde alla ricerca e ai filtri.</p>`;
  return `<div class="table-wrap"><table class="scr cat-tbl"><thead><tr><th class="l">ETF</th><th class="l p3">ISIN · ticker</th><th>TER</th>
      <th class="l p4">Proventi</th><th class="l p4">Cambio</th><th class="l p3">Dati</th><th>Confronta</th></tr></thead><tbody>
    ${rows.map(r => { const on = etfC.sel.includes(r.isin);
      return `<tr data-catisin="${esc(r.isin)}" class="${etfC.detail === r.isin ? "on" : ""}"><td class="l"><b>${esc(r.category || "")}</b>${r.theme ? ` <span class="cat-chip">tema</span>` : ""}
        ${r.status?.startsWith("aggiunto") ? ` <span class="cat-chip">da approvare</span>` : ""}<div class="muted small">${esc(r.name || "")}</div>
        <div class="muted sub2 s3">${esc(r.isin)} · ${esc((r.tickers || []).filter(t => !t.includes(".")).join(", "))}</div></td>
        <td class="l p3 small">${esc(r.isin)}<div class="muted">${esc((r.tickers || []).filter(t => !t.includes(".")).join(", ") || "nessuna quotazione")}</div></td>
        <td>${catPct(r.ter)}</td><td class="l p4 small">${esc(r.distribution || "n.d.")}</td><td class="l p4 small">${yn(r.hedged)}</td>
        <td class="l p3 small">${esc(r.completeness)}${r.stale?.length ? " · datati" : ""}</td>
        <td><input type="checkbox" class="cat-ck" data-catsel="${esc(r.isin)}" ${on ? "checked" : ""} ${!on && full ? "disabled" : ""} aria-label="Confronta ${esc(r.category || r.isin)}"></td></tr>`; }).join("")}
    </tbody></table></div><p class="muted small">${rows.length} ETF · clic su una riga per la scheda · spunta fino a 4 ETF per confrontarli.</p>`;
}
function etfCatSelHTML() {
  const D = etfC.data, name = i => D.rows.find(r => r.isin === i)?.category || i;
  return etfC.sel.length ? `<div class="cat-sel">Da confrontare: ${etfC.sel.map(i => `<span class="cat-chip">${esc(name(i))} <button data-catsel="${esc(i)}" aria-label="Togli">✕</button></span>`).join(" ")}
      <button class="btn" data-catcmp ${etfC.sel.length < 2 ? "disabled" : ""}>Confronta (${etfC.sel.length})</button> <button class="btn ghost" data-catclear>Svuota</button></div>`
    : `<p class="muted small">Spunta 2–4 ETF nell'elenco (o usa «Confronta» dalla scheda di un ETF) per vederli affiancati.</p>`;
}
function renderEtfCat() {
  const el = $("#etfCatBody"), D = etfC.data;
  if (!el) return;
  etfC.drawn = true;
  if (etfC.err || !D) { el.innerHTML = `<div class="card empty">${D || etfC.err ? `Catalogo non disponibile: ${esc(etfC.err || "")}` : "Carico il catalogo…"}</div>`; return; }
  const S = D.summary, F = D.facets || {};
  const opt = (k, label, values, lab = x => x) => `<label class="cat-f"><span>${label}</span><select data-catf="${k}"><option value="">tutti</option>
      ${values.filter(v => v != null && v !== "null").map(v => `<option value="${esc(v)}" ${String(etfC.f[k] ?? "") === String(v) ? "selected" : ""}>${esc(lab(v))}</option>`).join("")}</select></label>`;
  el.innerHTML = `${scopeNote("Catalogo informativo, non una classifica · non è una consulenza finanziaria.",
      `Serve a identificare e confrontare ETF UCITS con dati verificabili: nessun segnale di acquisto o vendita, nessun punteggio, nessun «vincitore».
      Un costo più basso non rende un ETF migliore da solo. ${info(ETF_CAT_INFO)}`)}
    <div class="card"><div class="card-h"><h2>Catalogo ETF UCITS</h2><span class="card-meta">${S.etfs} ETF · ${S.listings} quotazioni · completezza media ${fNum(S.completenessAvg * 100, 0)}% ·
      aggiornato il ${esc(dayIT(S.builtAt.slice(0, 10)))} (a mano, con etf_catalog_build.py)</span></div>
      <div class="cat-bar"><input type="search" id="etfCatQ" placeholder="Cerca per nome, ticker, ISIN, emittente, indice…" value="${esc(etfC.q)}" aria-label="Cerca nel catalogo">
        ${opt("assetClass", "Tipo", Object.keys(F.assetClass || {}), v => ETF_CAT_AC[v] || v)}
        ${opt("family", "Categoria", Object.keys(D.families || {}), v => D.families[v] || v)}
        ${opt("issuer", "Emittente", Object.keys(F.issuer || {}).sort())}
        ${opt("distribution", "Proventi", Object.keys(F.distribution || {}))}
        ${opt("hedged", "Cambio", ["true", "false"], v => v === "true" ? "coperto" : "non coperto")}</div>
      <div id="etfCatSel">${etfCatSelHTML()}</div>
      <div id="etfCatList">${etfCatListHTML()}</div></div>
    <div id="etfCatCmp">${etfCmpHTML()}</div>
    <div id="etfCatDetail">${etfDetailHTML()}</div>
    <details class="card fold"><summary><span class="small"><b>Prodotti esclusi dal catalogo ordinario</b> (${D.excluded.length}): ETC, ETN, leva, inversi, non UCITS</span></summary>
      <ul class="why">${D.excluded.map(x => `<li><b>${esc(x.category || x.isin)}</b> ${esc(x.name || "")} (${esc(x.isin)}): ${esc(x.reason || "")}</li>`).join("") || "<li>nessuno</li>"}</ul>
      <p class="muted small">Restano visibili nella scheda «Mercato ETF» come prima: qui sono tenuti separati perché non sono fondi UCITS o hanno rischi diversi.</p></details>
    <details class="card fold"><summary><span class="small"><b>Limiti dei dati</b></span></summary><ul class="why">${(D.notes || []).map(n => `<li>${esc(n)}</li>`).join("")}
      <li>I dati di justETF sono la copia salvata l'8 ottobre 2026 (non vengono riscaricati in automatico); paesi e settori hanno la data indicata da justETF.</li>
      <li>Le classi «da approvare» sono state aggiunte nella Fase 6A per mostrare la differenza tra fondo e classe: non sono nella scheda «Mercato ETF».</li></ul></details>`;
}
function etfDetailHTML() {
  const e = etfC.item;
  if (!etfC.detail) return "";
  if (!e) return `<div class="card empty">Carico la scheda…</div>`;
  if (e.error) return `<div class="card empty">${esc(e.error)}</div>`;
  const I = e.identity, Fd = e.fund, C = e.costs, X = e.exposure || {}, B = e.bond || {}, K = e.classification || {};
  const line = (label, f, fmt, extra = "") => `<tr><th class="l">${label}</th><td class="l">${esc(fvText(f, fmt))}${extra}${f?.note ? `<div class="muted small">${esc(f.note)}</div>` : ""}</td><td class="l">${srcTag(f)}</td></tr>`;
  const st = s => s ? ` <span class="cat-chip ${s === "discordante" ? "bad" : ""}">${esc(s)}</span>` : "";
  const list = v => v.map(x => `${etfIt(x.name)} ${fNum(x.weight, 1)}%`).join(", ");
  const listings = (e.listings || []).map(l => `<tr><td class="l">${esc(l.venue)}</td><td class="l">${esc(l.mic)}</td><td class="l"><b>${esc(l.ticker)}</b></td>
      <td class="l">${esc(fvText(l.currency))}</td><td>${isNum(l.avgTurnover3m?.v) ? fNum(l.avgTurnover3m.v, 0) : "n.d."}</td>
      <td class="l small">${l.spread ? (l.spread.representative ? catPct(l.spread.v) : `book letto a mercato chiuso (${esc(l.spread.at.slice(11, 16))}), non rappresentativo`) : "n.d."}</td></tr>`).join("");
  const bond = K.assetClass === "obbligazionario" || K.assetClass === "monetario";
  return `<div class="card cat-detail"><div class="card-h"><h2>${esc(K.label || "")}: ${esc(fvText(I.name))}</h2>
      <span class="card-meta">${esc(e.isin)} · ${esc(e.status || "")}${e.statusNote ? ` (${esc(e.statusNote)})` : ""}</span>
      <button class="btn ghost" data-catclose aria-label="Chiudi la scheda">Chiudi</button></div>
    <p class="small">Completezza: <b>${esc(e.completeness.state)}</b> (${fNum(e.completeness.share * 100, 0)}%)${e.completeness.missing.length ? ` · mancano: ${esc(e.completeness.missingLabels.join(", "))}` : ""}
      ${e.freshness.stale.length ? ` · <b>dati datati</b>: ${esc(e.freshness.stale.join(", "))}` : ""}</p>
    <details class="fold" open><summary><b>Identità e classe</b></summary><table class="cat-kv">
      ${line("Nome", I.name)}${line("Fondo", I.fundName)}${line("Emittente", I.issuer)}${line("Società (Borsa Italiana)", I.legalEntity)}
      ${line("Domicilio", I.domicile)}${line("UCITS", I.ucits)}${line("Tipo di prodotto", I.productType)}${line("Classe", I.shareClass)}
      ${line("Valuta della classe (NAV)", Fd.baseCurrency, null, st(Fd.baseCurrencyState))}${line("Copertura del cambio", Fd.hedged, yn, st(Fd.hedgedState))}
      ${line("Proventi", Fd.distribution, null, st(Fd.distributionState))}${line("Frequenza dei proventi", Fd.distributionFrequency)}
      ${line("Indice", I.index)}${line("Benchmark su Borsa Italiana", I.benchmarkExchange)}</table></details>
    <details class="fold" open><summary><b>Quotazioni</b> (stesso ISIN, borse e ticker diversi)</summary>
      ${listings ? `<div class="table-wrap"><table class="scr"><thead><tr><th class="l">Borsa</th><th class="l">MIC</th><th class="l">Ticker</th><th class="l">Valuta</th><th>Scambi medi/giorno (3 mesi)</th><th class="l">Spread</th></tr></thead><tbody>${listings}</tbody></table></div>`
        : `<p class="small">Nessuna quotazione trovata sulle borse controllate (Borsa Italiana, Xetra).</p>`}
      <p class="muted small">Valuta di negoziazione = quella in cui compri. Volumi da Yahoo (indicativi), book da Borsa Italiana (ritardato 15 min). Disponibilità presso il broker: <b>non verificata</b>.</p></details>
    <details class="fold"><summary><b>Costi</b></summary><table class="cat-kv">
      ${line("TER / costi correnti", C.ter, catPct, st(C.terState))}
      ${C.terChecks?.length > 1 ? `<tr><th class="l">Valori per fonte</th><td class="l" colspan="2">${C.terChecks.map(c => `${esc(c.src)}: ${catPct(c.v)}`).join(" · ")}</td></tr>` : ""}
      ${line("Tracking difference", C.trackingDifference)}${line("Tracking error", C.trackingError)}${line("Commissioni del broker", C.brokerFees)}</table></details>
    <details class="fold"><summary><b>Struttura, dimensione e documenti</b></summary><table class="cat-kv">
      ${line("Replica", Fd.replication)}<tr><th class="l">Controparte</th><td class="l" colspan="2">${esc(Fd.counterpartyRisk || "n.d.")}</td></tr>
      ${line("Patrimonio del fondo", Fd.sizeFund, v => fNum(v, 0) + " mln " + (Fd.sizeFund.unit || ""))}${line("Patrimonio della classe", Fd.sizeClass, v => fNum(v, 0) + " mln")}
      ${line("Data di lancio", Fd.launch, v => dayIT(v))}${line("Data del KID", Fd.kidDate, v => dayIT(v))}${line("Data del prospetto", Fd.prospectusDate, v => dayIT(v))}</table></details>
    <details class="fold"><summary><b>${bond ? "Obbligazioni ed esposizione" : "Esposizione"}</b></summary><table class="cat-kv">
      ${bond ? line("Tipo", B.bondKind) + line("Duration (anni)", B.duration, v => fNum(v, 2)) + line("Rendimento a scadenza (al peggio)", B.yield, catPct)
        + line("Rendimento distribuito 12 mesi", B.distYield, catPct) + line("Qualità del credito", B.credit) + line("Valuta", B.currency) : ""}
      ${line("Numero di titoli", X.holdingsCount, v => fNum(v, 0))}${line("Peso dei primi 10", X.top10Weight, v => fNum(v * 100, 1) + "%")}
      ${line("Primi 10 titoli", X.top10, v => v.map(h => `${h.name} ${isNum(h.weight) ? fNum(h.weight * 100, 1) + "%" : ""}`).join(", "))}
      ${line("Paesi", X.countries, list)}${line("Settori", X.sectors, list)}
      ${line("Esposizione valutaria (stima)", X.currencyExposure, v => v.map(c => c.currency + (isNum(c.weight) ? " " + fNum(c.weight, 0) + "%" : "")).join(", "))}</table></details>
    <details class="fold"><summary><b>Rischi principali</b></summary><ul class="why">${e.risks.map(r => `<li>${esc(r)}</li>`).join("") || "<li>n.d.</li>"}</ul></details>
    <details class="fold" open><summary><b>ETF simili nel catalogo</b></summary>${e.similar.length ? `<ul class="why">${e.similar.map(s => `<li><span class="act ${CMP_LEVEL_CLS[s.level]}">${s.level} · ${esc(s.label)}</span>
        <b>${esc(s.name || s.isin)}</b> <span class="muted small">${esc(s.reasons.join("; "))}</span>
        <button class="btn ghost" data-catpair="${esc(e.isin)},${esc(s.isin)}">Confronta</button></li>`).join("")}</ul>` : `<p class="small">Nessun ETF dello stesso tipo nel catalogo.</p>`}</details>
    <details class="fold"><summary><b>Fonti</b></summary><ul class="why">${Object.entries(e.sources || {}).map(([k, s]) => `<li><b>${esc(k)}</b>: ${esc(s.publisher || "")}
        ${s.url ? ` · <a href="${esc(s.url)}" target="_blank" rel="noopener">link</a>` : ""}${s.asOf ? ` · dati al ${esc(dayIT(s.asOf))}` : ""}${s.fetched ? ` · letto il ${esc(dayIT(s.fetched))}` : ""}</li>`).join("")}</ul></details>
    <p class="muted small">${esc(e.disclaimer)}</p></div>`;
}
function etfCmpHTML() {
  if (etfC.cmpErr) return `<div class="card empty">${esc(etfC.cmpErr)}</div>`;
  const c = etfC.cmp;
  if (!c) return "";
  const head = `<tr><th class="l"></th>${c.items.map(r => `<th class="l"><b>${esc(r.category || "")}</b><div class="muted small">${esc(r.isin)}</div></th>`).join("")}</tr>`;
  const cellH = v => `<td class="l ${v.missing ? "muted" : ""}">${esc(v.text)}${v.state ? ` <span class="cat-chip ${v.state === "discordante" ? "bad" : ""}">${esc(v.state)}</span>` : ""}${v.note && !v.missing ? `<div class="muted small">${esc(v.note)}</div>` : ""}</td>`;
  const dim = d => `<details class="fold" ${["indice", "costi"].includes(d.key) ? "open" : ""}><summary><b>${esc(d.label)}</b></summary>
      <div class="table-wrap"><table class="scr cmp-tbl"><thead>${head}</thead><tbody>${d.rows.map(r => `<tr class="${r.same ? "same" : ""}"><th class="l">${esc(r.label)}</th>${r.values.map(cellH).join("")}</tr>`).join("")}</tbody></table></div>
      ${d.note ? `<p class="muted small">${esc(d.note)}</p>` : ""}</details>`;
  const o = c.overlap;
  return `<div class="card cat-cmp"><div class="card-h"><h2>Confronto</h2><span class="act big ${CMP_LEVEL_CLS[c.level]}">Livello ${c.level} · ${esc(c.levelLabel)}</span>
      <button class="btn ghost" data-catcmpclose>Chiudi</button></div>
    <p class="small">${esc(c.levelText)}</p>
    ${c.pairs.length > 1 || c.pairs[0].reasons.length ? `<ul class="why">${c.pairs.map(p => `<li><b>${esc(p.a)} – ${esc(p.b)}</b>: livello ${p.level} (${esc(p.label)})${p.reasons.length ? ": " + esc(p.reasons.join("; ")) : ""}</li>`).join("")}</ul>` : ""}
    ${c.differences.length ? `<h4>Cosa cambia tra loro</h4><ul class="why">${c.differences.map(d => `<li>${esc(d)}</li>`).join("")}</ul>` : ""}
    ${c.dimensions.map(dim).join("")}
    <details class="fold"><summary><b>Titoli in comune</b> (primi 10)</summary>${o.available ? `<p class="small">${esc(o.note)}</p>
      ${o.common.length ? `<ul class="why">${o.common.map(x => `<li>${esc(x.name)}: ${x.weights.map(w => isNum(w) ? fNum(w * 100, 1) + "%" : "n.d.").join(" / ")}</li>`).join("")}</ul>` : ""}
      ${o.warnings.length ? `<p class="muted small">${esc(o.warnings.join(" · "))}</p>` : ""}<p class="muted small">Date delle composizioni: ${o.dates.map(d => esc(dayIT(d))).join(" / ")}.</p>`
      : `<p class="small">${esc(o.reason)}</p>`}</details>
    <p class="muted small">Righe in grigio = valore uguale per tutti. ${esc(c.disclaimer)}</p></div>`;
}
async function etfCatOpen(isin) {
  etfC.detail = isin; etfC.item = null; $("#etfCatDetail").innerHTML = etfDetailHTML();
  try { const r = await fetch("/api/etf/catalog/" + encodeURIComponent(isin)); etfC.item = r.ok ? await r.json() : { error: "ETF non trovato nel catalogo" }; }
  catch { etfC.item = { error: "server non raggiungibile" }; }
  if (etfC.detail !== isin) return;
  $("#etfCatDetail").innerHTML = etfDetailHTML();
  $("#etfCatDetail").scrollIntoView({ behavior: "smooth", block: "start" });
}
async function etfCatCompare(isins) {
  etfC.cmpErr = null; etfC.cmp = null;
  try { const r = await fetch("/api/etf/compare?isins=" + encodeURIComponent(isins.join(","))); const j = await r.json(); if (r.ok) etfC.cmp = j; else etfC.cmpErr = j.error; }
  catch { etfC.cmpErr = "server non raggiungibile"; }
  $("#etfCatCmp").innerHTML = etfCmpHTML();
  $("#etfCatCmp").scrollIntoView({ behavior: "smooth", block: "start" });
}
function etfCatRefreshList() { $("#etfCatList").innerHTML = etfCatListHTML(); $("#etfCatSel").innerHTML = etfCatSelHTML(); }
document.addEventListener("click", e => {
  const m = e.target.closest("[data-etfmode]");
  if (m) { etfC.mode = m.dataset.etfmode; LS.set("etfMode", etfC.mode); etfModeBar(); if (etfC.mode === "cat") loadEtfCat(); else renderEtf(); return; }
  if (!e.target.closest("#etfCatBody")) return;
  const s = e.target.closest("[data-catsel]");
  if (s) { const i = s.dataset.catsel; etfC.sel = etfC.sel.includes(i) ? etfC.sel.filter(x => x !== i) : etfC.sel.concat(i).slice(0, 4); etfCatRefreshList(); return; }
  if (e.target.closest("[data-catclear]")) { etfC.sel = []; etfCatRefreshList(); return; }
  if (e.target.closest("[data-catcmp]")) { etfCatCompare(etfC.sel); return; }
  if (e.target.closest("[data-catcmpclose]")) { etfC.cmp = null; etfC.cmpErr = null; $("#etfCatCmp").innerHTML = ""; return; }
  if (e.target.closest("[data-catclose]")) { etfC.detail = null; etfC.item = null; $("#etfCatDetail").innerHTML = ""; etfCatRefreshList(); return; }
  const p = e.target.closest("[data-catpair]");
  if (p) { etfC.sel = p.dataset.catpair.split(","); etfCatRefreshList(); etfCatCompare(etfC.sel); return; }
  const r = e.target.closest("tr[data-catisin]");
  if (r && !e.target.closest("input")) { etfCatOpen(r.dataset.catisin); etfCatRefreshList(); }
});
document.addEventListener("input", e => {
  if (e.target.id === "etfCatQ") { etfC.q = e.target.value; $("#etfCatList").innerHTML = etfCatListHTML(); }
});
document.addEventListener("change", e => {
  const f = e.target.closest("[data-catf]");
  if (f) { etfC.f[f.dataset.catf] = f.value; $("#etfCatList").innerHTML = etfCatListHTML(); }
  const ef = e.target.closest("[data-etff]");                    // Mercato ETF: Trend and «Ha senso comprare?» filters
  if (ef) { const k = ef.dataset.etff; etfS[k] = ef.value; LS.set(k === "ft" ? "etfTrend" : "etfBuy", ef.value); renderEtf(); }
});
// Opportunità → ETF (phase 6B): exploratory scanner of the ETF EXPOSURES (etf_opportunity.py). Exposure first, products
// after; the judgement on the exposure and the quality of the product stay separate; never Compra/Vendi, never a score.
const EO = { mode: LS.get("eo.mode", "lungo"), data: {}, err: {}, loading: {}, open: null, det: {}, detErr: null };
const EO_MODES = { lungo: "Medio-lungo periodo", breve: "Breve periodo" };
const EO_INS = "Da approfondire — evidenza insufficiente per un giudizio favorevole";      // model E2, bonds only
const EO_ST = { "Esposizione da approfondire": "ok", "Trend favorevole da monitorare": "mon", [EO_INS]: "ins", "Condizioni contrastanti": "mix",
  "Rischio elevato": "risk", "Dati insufficienti": "na", "Nessuna opportunità convincente": "none", "Riferimento di mercato": "ref" };
const eoSt = s => `<span class="eo-st eo-${EO_ST[s] || "none"}">${esc(s)}</span>${s === "Trend favorevole da monitorare" ? " " + info(E2_MON_HELP) : ""}`;
const eoPts = v => isNum(v) ? `<span class="${v > 0 ? "pos" : v < 0 ? "neg" : ""}">${(v > 0 ? "+" : "") + fNum(v, 1)}</span>` : "n.d.";
const eoPct = v => isNum(v) ? fPct(v, 1) : "n.d.";
const eoCk = c => `<li class="${c.ok === true ? "ck-ok" : c.ok === false ? "ck-ko" : "ck-na"}">${esc(c.text)}${c.value != null ? ` — <b>${esc(String(c.value))}</b>` : ""}${c.why ? ` <span class="muted">(${esc(c.why)})</span>` : ""}</li>`;
async function loadEo(mode, force) {
  if (EO.loading[mode] || (EO.data[mode] && !force)) return;
  EO.loading[mode] = true; EO.err[mode] = null;
  try { const r = await fetch("/api/etf/opportunities?mode=" + mode); const j = await r.json(); if (r.ok && j.status === "ok") EO.data[mode] = j; else EO.err[mode] = j.error || "dati non disponibili"; }
  catch { EO.err[mode] = "server non raggiungibile"; }
  EO.loading[mode] = false;
  if (opps.mode === "etf") renderOpps();
}
async function loadEoDetail(key) {
  const k = EO.mode + ":" + key;
  EO.open = key; EO.detErr = null;
  if (!EO.det[k]) {
    renderOpps();
    try { const r = await fetch(`/api/etf/opportunities/${encodeURIComponent(key)}?mode=${EO.mode}`); const j = await r.json(); if (r.ok) EO.det[k] = j; else EO.detErr = j.error; }
    catch { EO.detErr = "server non raggiungibile"; }
  }
  renderOpps();
  document.getElementById("eoDetail")?.scrollIntoView({ behavior: "smooth", block: "start" });
}
function eoRetCells(r, mode) {
  const R = r.returns || {}, X = r.rel || {};
  return mode === "breve" ? `1 mese ${eoPct(R["1m"])} · contro il mercato ${eoPts(X["1m"])} punti`
    : `6 mesi ${eoPct(R["6m"])} · 12 mesi ${eoPct(R["12m"])} · contro il mercato a 6 mesi ${eoPts(X["6m"])} punti`;
}
function eoCard(o, mode) {
  const m = o.measures || {}, b = o.bond;
  const prods = o.products.products;
  const andamento = o.kind === "bond"
    ? `Duration ${fNum(b.duration, 1)} anni · rendimento a scadenza ${fNum(b.yield, 2)}% lordo (al ${esc(dayIT(b.yieldAsOf || ""))}) · ${esc(o.role)}`
    : eoRetCells({ returns: m.returns, rel: m.rel }, mode) + ` · trend ${esc(m.trend || "n.d.")}`;
  return `<div class="eo-card"><div class="eo-card-h"><b>${esc(o.label)}</b> ${eoSt(o.state)}</div>
    <p class="small muted">${esc(o.familyLabel)}${o.benchmarkName ? ` · confronto con ${esc(o.benchmarkName)}` : ""}</p>
    <p class="small"><b>Andamento:</b> ${andamento}</p>
    <p class="small"><b>Rischio:</b> ${esc((o.risk || {}).level || "n.d.")}${(o.risk?.flags || []).length ? " — " + esc(o.risk.flags.map(f => f.text).join("; ")) : ""}</p>
    <h4>Perché è stata selezionata</h4><ul class="why">${o.why.map(w => `<li>${esc(w)}</li>`).join("")}</ul>
    <h4>Cosa potrebbe invalidare il giudizio</h4><ul class="why">${o.invalidate.map(w => `<li>${esc(w)}</li>`).join("")}</ul>
    <p class="small"><b>ETF per ottenerla:</b> ${prods.map(p => `${esc(p.tickers[0] || p.isin)} (TER ${isNum(p.ter) ? fNum(p.ter, 2) + "%" : "n.d."}${p.hedged ? ", coperto" : ""})`).join(" · ")}</p>
    <p class="eo-act"><button class="btn" data-eoopen="${esc(o.key)}">Scheda dell'esposizione</button>
      ${prods.length > 1 ? `<button class="btn ghost" data-oppetf="${esc(o.products.compare.join(","))}">Confronta gli ETF nel catalogo</button>` : ""}</p></div>`;
}
function eoListHTML(D) {
  const byFam = {};
  D.rows.forEach(r => (byFam[r.family] = byFam[r.family] || []).push(r));
  return D.families.filter(f => byFam[f.key]).map(f => {
    const rows = byFam[f.key];
    const n = rows.filter(r => r.state === "Esposizione da approfondire").length;
    const bond = rows[0].kind === "bond";
    return `<details class="fold" data-k="eo-${f.key}"><summary><b>${esc(f.label)}</b> <span class="muted small">${rows.length} esposizioni${n ? `, ${n} da approfondire` : ""}</span></summary>
      <div class="table-wrap"><table class="scr eo-tbl"><thead><tr><th class="l">Esposizione</th><th class="l">Stato</th>
      ${bond ? `<th>Duration</th><th>Rend. a scadenza</th><th class="l p3">Ruolo</th>` : `<th>${D.mode === "breve" ? "1 mese" : "6 mesi"}</th><th>Contro il mercato</th><th class="l p3">Trend</th>`}
      <th class="l">Rischio</th><th class="l p3">ETF</th></tr></thead><tbody>${rows.map(r => {
        const k = D.mode === "breve" ? "1m" : "6m";
        return `<tr data-eoopen="${esc(r.key)}"><td class="l"><b>${esc(r.label)}</b></td><td class="l">${eoSt(r.state)}</td>
          ${bond ? `<td>${r.bond && isNum(r.bond.duration) ? fNum(r.bond.duration, 1) : "n.d."}</td><td>${r.bond && isNum(r.bond.yield) ? fNum(r.bond.yield, 2) + "%" : "n.d."}</td><td class="l p3 small">${esc(r.bondRole || "")}</td>`
            : `<td>${eoPct((r.returns || {})[k])}</td><td>${eoPts((r.rel || {})[k])}</td><td class="l p3">${esc(r.trend || "n.d.")}</td>`}
          <td class="l">${esc(r.risk || "n.d.")}</td><td class="l p3 small">${r.products.map(p => esc(p.ticker)).join(", ")}</td></tr>`;
      }).join("")}</tbody></table></div></details>`;
  }).join("");
}
// Bond rate sensitivity. Model E2: duration (modified when published, else effective, declared), indicative ±1 point
// scenarios and the yield ÷ duration ratio as a plain figure without threshold. Model E1 rows keep the old single line.
function eoBondRate(b) {
  if (!("rateScenarios" in b))
    return `<tr><th>Duration effettiva</th><td>${isNum(b.duration) ? fNum(b.duration, 2) + " anni: con tassi +1 punto il valore scende di circa il " + fNum(b.duration, 1) + "%" : "n.d."}</td></tr>`;
  const sc = b.rateScenarios;
  return `<tr><th>Duration${b.durationKind ? " " + esc(b.durationKind) : ""}</th><td>${isNum(b.durationUsed) ? fNum(b.durationUsed, 2) + " anni" : "n.d."}</td></tr>
    <tr><th>Sensibilità indicativa ai tassi</th><td>${sc ? sc.map(x => `rendimenti di mercato ${x.shift > 0 ? "+" : "−"}${fNum(Math.abs(x.shift), 0)} punto: prezzo circa ${x.priceChange > 0 ? "+" : "−"}${fNum(Math.abs(x.priceChange), 1)}%`).join("<br>") : "non calcolabile"}
      <br><span class="cat-src">${esc((b.scenarioNotes || []).join("; "))}</span></td></tr>
    <tr><th>Rendimento ÷ duration</th><td>${isNum(b.ratio) ? fNum(b.ratio, 2) + ` <span class="cat-src">${esc(b.ratioNote || "")}</span>` : "n.d."}</td></tr>`;
}
function eoDetailHTML() {
  const o = EO.det[EO.mode + ":" + EO.open];
  if (!EO.open) return "";
  if (!o) return `<div class="card" id="eoDetail">${EO.detErr ? esc(EO.detErr) : "Caricamento della scheda…"}</div>`;
  const m = o.measures || {}, c = o.concentration || {}, P = o.products;
  const top = (arr, n = 5) => (arr || []).slice(0, n).map(x => `${esc(ETF_IT[x.name] || x.name)} ${fNum(x.weight, 1)}%`).join(" · ");
  const contains = o.kind === "bond"
    ? `<table class="cat-kv eo-kv"><tr><th>Tipo</th><td>${esc(o.bond.kind || "n.d.")}</td></tr><tr><th>Credito</th><td>${esc(o.bond.credit || "n.d.")}${isNum(o.bond.aOrBetter) ? ` · rating A o superiore ${fNum(o.bond.aOrBetter, 0)}% (al ${esc(dayIT(o.bond.ratingsAsOf || ""))})` : ""}</td></tr>
       ${eoBondRate(o.bond)}
       <tr><th>Scadenza media</th><td>${isNum(o.bond.maturity) ? fNum(o.bond.maturity, 1) + " anni" : "n.d."}</td></tr>
       <tr><th>Rendimento a scadenza</th><td>${isNum(o.bond.yield) ? fNum(o.bond.yield, 2) + "% annuo lordo, senza spese (al " + esc(dayIT(o.bond.yieldAsOf || "")) + "): non è un rendimento netto garantito" : "n.d."}</td></tr>
       <tr><th>Cedola media</th><td>${isNum(o.bond.coupon) ? fNum(o.bond.coupon, 2) + "% (gli interessi dei titoli, non il rendimento)" : "n.d."}</td></tr>
       <tr><th>Distribuzioni ultimi 12 mesi</th><td>${isNum(o.bond.distYield) ? fNum(o.bond.distYield, 2) + "% (guarda indietro: non è il rendimento a scadenza)" : "n.d."}</td></tr>
       <tr><th>Valuta</th><td>${esc(o.bond.currency || "n.d.")}${o.bond.hedgedText ? ` · ${esc(o.bond.hedgedText)}` : ""}</td></tr>
       ${o.bondChange ? `<tr><th>Dalla rilevazione del ${esc(dayIT(o.bondChange.since))}</th><td>rendimento ${eoPts(o.bondChange.yield)} punti</td></tr>` : `<tr><th>Rilevazione precedente</th><td>nessuna: il confronto parte dalla prima registrazione nel diario</td></tr>`}</table>`
    : `<table class="cat-kv eo-kv"><tr><th>Concentrazione</th><td>${isNum(c.top10) ? `primi 10 titoli ${fNum(c.top10, 0)}% del fondo` : "n.d."}${c.src ? ` <span class="cat-src">(${esc(c.src)}${c.asOf ? ", " + esc(dayIT(c.asOf)) : ""})</span>` : ""}${c.kind === "ETF americano" ? ` <span class="warn small">composizione dell'ETF americano sullo stesso indice: non verificata per l'ETF europeo</span>` : ""}</td></tr>
       <tr><th>Paesi</th><td>${top(c.countries) || "n.d."}</td></tr><tr><th>Settori</th><td>${top(c.sectors) || "n.d."}</td></tr>
       <tr><th>Valutazione</th><td>${isNum(o.valuation?.pe) ? `P/E ${fNum(o.valuation.pe, 1)}${isNum(o.valuation.pb) ? ` · P/B ${fNum(o.valuation.pb, 1)}` : ""} (al ${esc(dayIT(o.valuation.asOf || ""))})${isNum(o.valuation.benchPe) ? ` · mercato di confronto P/E ${fNum(o.valuation.benchPe, 1)}` : ""}` : "n.d."}
         <span class="cat-src">${esc(o.valuation?.note || "")}</span></td></tr>
       <tr><th>Ruolo possibile</th><td>${esc(o.role || "n.d.")} <span class="cat-src">(non analizzato rispetto al tuo portafoglio)</span></td></tr></table>`;
  const meas = o.kind === "equity" && m.returns ? `<div class="table-wrap"><table class="scr"><thead><tr><th class="l"></th><th>1 sett.</th><th>1 mese</th><th>3 mesi</th><th>6 mesi</th><th>12 mesi</th></tr></thead><tbody>
      <tr><td class="l">Rendimento totale in euro</td>${["1s", "1m", "3m", "6m", "12m"].map(k => `<td>${eoPct(m.returns[k])}</td>`).join("")}</tr>
      <tr><td class="l">Contro ${esc(o.benchmarkName || "—")} (punti)</td>${["1s", "1m", "3m", "6m", "12m"].map(k => `<td>${eoPts((m.rel || {})[k])}</td>`).join("")}</tr>
      <tr><td class="l">Stessa misura ${o.mode === "breve" ? 5 : 21} sedute fa</td>${["1s", "1m", "3m", "6m", "12m"].map(k => `<td>${eoPts((m.relPrev || {})[k])}</td>`).join("")}</tr></tbody></table></div>
      <p class="small">Trend ${esc(m.trend || "n.d.")} · volatilità 1 mese ${eoPct(m.vol1m)}, 3 mesi ${eoPct(m.vol3m)}, 12 mesi ${eoPct(m.vol12m)} · calo dal massimo a 3 mesi ${eoPct(m.dd3m)}, a 12 mesi ${eoPct(m.dd12m)} · prezzi al ${esc(dayIT(m.date || ""))}, ${m.aligned || "n.d."} sedute allineate con il benchmark</p>` : "";
  const trends = (o.trends || []).length ? o.trends.map(t => `<li><b>${esc(t.label)}</b>: ${esc(t.observed)} (${esc(t.period)}${t.benchmark ? ", contro " + esc(t.benchmark) : ""})${t.previous ? `; prima: ${esc(t.previous)}` : ""}
      ${t.favourable.length ? `<br><span class="pos">a favore:</span> ${esc(t.favourable.join("; "))}` : ""}${t.contrary.length ? `<br><span class="neg">contro:</span> ${esc(t.contrary.join("; "))}` : ""}</li>`).join("")
    : `<li>Nessun cambiamento significativo secondo le condizioni descritte sotto.</li>`;
  const prod = p => `<tr><td class="l"><b>${esc(p.tickers.join(" · ") || p.isin)}</b><br><span class="small muted">${esc(p.name)}</span><br><span class="cat-src">${esc(p.isin)} · ${esc(p.status || "")}</span>${p.level ? `<br><span class="small">livello ${p.level} rispetto alla classe di misura</span>` : ""}</td>
      <td class="l small">${esc(p.index || "n.d.")}</td>
      <td>${isNum(p.ter) ? fNum(p.ter, 2) + "%" : "n.d."}<br><span class="cat-src">${esc(p.terResolution || "")}</span></td>
      <td>${isNum(p.tdAvg) ? eoPts(p.tdAvg) + " /anno" : "n.d."}${isNum(p.td) ? `<br><span class="cat-src">ultimo anno ${eoPts(p.td)}</span>` : ""}</td>
      <td class="l small">${esc(p.replication || "n.d.")} · ${esc(p.distribution || "n.d.")}${p.frequency ? ` (${esc(p.frequency.toLowerCase())})` : ""} · ${p.hedged ? "cambio coperto" : "cambio non coperto"}</td>
      <td class="small">${isNum(p.size) ? fNum(p.size, 0) + " mln " + esc(p.sizeUnit || "") : "n.d."}</td>
      <td class="l small">${esc(p.domicile || "n.d.")} · ${esc(p.tradingCurrencies.join(", ") || "n.d.")}</td>
      <td class="l small">${p.listings.map(l => `${esc(l.ticker)}: ${isNum(l.turnover) ? fNum(l.turnover / 1000, 0) + " mila €/giorno" : "n.d."}`).join("<br>")}<br><span class="cat-src">spread ${esc(p.spread)}</span></td></tr>`;
  return `<div class="card eo-detail" id="eoDetail"><div class="card-h"><h2>${esc(o.label)}</h2> ${eoSt(o.state)}<button class="btn ghost" data-eoclose>Chiudi</button></div>
    <p class="small muted">${esc(o.familyLabel)} · ${esc(EO_MODES[o.mode])} · modello ${esc(o.version)}${o.benchmarkName ? ` · benchmark: ${esc(o.benchmarkName)}` : ""}</p>
    <h3>Cosa contiene</h3>${contains}
    <h3>Perché viene monitorata</h3><ul class="why">${o.why.map(w => `<li>${esc(w)}</li>`).join("")}</ul>
    ${meas}
    <h3>Segnali</h3><div class="opp-x"><div class="opp-cols"><div><h4>Favorevoli</h4><ul>${o.conditions.fav.map(eoCk).join("")}</ul></div>
      <div><h4>Contrari</h4><ul>${o.conditions.con.map(eoCk).join("")}</ul></div></div></div>
    <p class="muted small">✅ condizione soddisfatta · ❌ non soddisfatta · ❓ non valutabile (non conta mai come soddisfatta). Condizioni valutabili: ${esc(o.completeness.conditions)}.${o.completeness.notes.length ? " " + esc(o.completeness.notes.join("; ")) + "." : ""}</p>
    <h3>Cosa è cambiato</h3><ul class="why">${trends}</ul>
    <h3>Rischi</h3><ul class="why">${(o.risk?.flags || []).length ? o.risk.flags.map(f => `<li>${f.high ? "⚠ " : ""}${esc(f.text)}</li>`).join("") : "<li>Nessun rischio oltre le soglie descritte.</li>"}</ul>
    <p class="small">Cosa potrebbe invalidare il giudizio: ${esc(o.invalidate.join("; "))}.</p>
    <h3>Prodotti che la replicano</h3>
    <p class="small"><b>${esc(P.verdict)}.</b> Il giudizio sull'esposizione è separato dalla qualità del prodotto. Disponibilità presso Fineco: non verificata.</p>
    <div class="table-wrap"><table class="scr eo-prod"><thead><tr><th class="l">ETF</th><th class="l">Indice</th><th>TER</th><th>Tracking difference</th><th class="l">Struttura</th><th>Patrimonio</th><th class="l">Domicilio · valuta</th><th class="l">Scambi e spread</th></tr></thead>
      <tbody>${P.products.map(prod).join("")}</tbody></table></div>
    ${P.differences.length ? `<h4>Cosa cambia tra loro</h4><ul class="why">${P.differences.map(d => `<li>${esc(d)}</li>`).join("")}</ul>` : ""}
    <details class="fold"><summary><span class="small">Qualità del prodotto (controlli separati, non un punteggio)</span></summary>
      ${P.products.map(p => `<p class="small"><b>${esc(p.tickers[0] || p.isin)}</b></p><div class="opp-x"><ul>${p.checks.map(eoCk).join("")}</ul></div>`).join("")}</details>
    ${P.similar.length ? `<p class="small">Esposizioni simili ma non identiche (stessa categoria, indice diverso): ${P.similar.map(x => `<button class="cat-chip" data-oppetf="${esc([o.reference, x.isin].filter(Boolean).join(","))}">${esc(x.label)}</button>`).join(" ")}</p>` : ""}
    <p class="eo-act"><button class="btn" data-oppetf="${esc(P.compare.join(","))}">${P.compare.length > 1 ? "Confronta questi ETF nel catalogo" : "Apri l'ETF nel catalogo"}</button></p>
    <p class="muted small">${esc(o.disclaimer)}</p></div>`;
}
function oppEtfHTML() {
  const mode = EO.mode, D = EO.data[mode];
  const head = `<div class="card"><div class="card-h"><h2>ETF · esposizioni da approfondire</h2>
      <div class="seg">${Object.entries(OPP_MODES).map(([k, l]) => `<button data-opm="${k}" class="${k === "etf" ? "on" : ""}">${esc(l.split(" · ")[0])}</button>`).join("")}</div></div>
      <div class="seg small">${Object.entries(EO_MODES).map(([k, l]) => `<button data-eomode="${k}" class="${k === mode ? "on" : ""}">${esc(l)}</button>`).join("")}</div>
      <p class="small muted">${mode === "breve" ? "3–30 sedute: movimenti, forza relativa a 1 mese, volatilità e cali recenti. Screening esplorativo: nessun segnale di trading."
        : "3–24 mesi: trend sulle medie 50 e 200, forza relativa a 6 e 12 mesi, rischio, costi e struttura. Per le obbligazioni un modello separato (duration, rendimento, credito)."}</p></div>`;
  if (!D) {
    if (!EO.loading[mode] && !EO.err[mode]) loadEo(mode);
    return head + `<div class="card empty">${EO.err[mode] ? esc(EO.err[mode]) : "Caricamento dello scanner ETF…"}</div>`;
  }
  const O = D.overview, sel = D.selectedRows;
  const kpi = (l, v, s) => `<div class="kpi"><div class="l">${l}</div><div class="v">${v}</div><div class="s">${s || ""}</div></div>`;
  const chg = (arr, cls) => arr.length ? arr.map(x => `<button class="cat-chip" data-eoopen="${esc(x.key)}">${esc(x.label)} <b class="${cls}">${(x.change > 0 ? "+" : "") + fNum(x.change, 1)}</b></button>`).join(" ") : `<span class="muted small">nessuna oltre la soglia</span>`;
  return `${scopeNote("Screening esplorativo, non consulenza finanziaria · regole non validate.",
      `Parte dalle esposizioni (mercati, settori, obbligazioni) e mostra quali condizioni sono soddisfatte e quali mancano: nessun «Compra» o «Vendi»,
      nessuna probabilità. Le regole non sono validate: il momentum sulle categorie di ETF non ha superato il test (Fase 24).`)}${head}
    <div class="kpis eo-kpis">${kpi(`Esposizioni monitorate ${info(EXPOSURES_HELP)}`, O.exposures, `${O.products} ETF del catalogo`)}${kpi("Da approfondire", O.counts["Esposizione da approfondire"], `al massimo ${D.params.max_selected} mostrate`)}
      ${kpi("Rischio elevato", O.counts["Rischio elevato"], "segnali favorevoli o contrari con rischio oltre soglia")}${kpi("Dati insufficienti", O.counts["Dati insufficienti"], "non giudicabili")}
      ${kpi("Ultima seduta", D.session ? esc(dayIT(D.session)) : "n.d.", D.pricesFetched ? "prezzi scaricati " + esc(D.pricesFetched.slice(0, 16).replace("T", " ")) : "")}</div>
    <div class="card"><h3>Panoramica</h3>
      <p class="small"><b>In miglioramento</b> (forza relativa ${D.mode === "breve" ? "a 1 mese rispetto a 5 sedute fa" : "a 6 mesi rispetto a 21 sedute fa"}, punti): ${chg(O.improving, "pos")}</p>
      <p class="small"><b>In peggioramento</b>: ${chg(O.worsening, "neg")}</p>
      <p class="small"><b>Rischi principali</b>: ${O.risks.length ? O.risks.slice(0, 6).map(r => `<button class="cat-chip bad" data-eoopen="${esc(r.key)}">${esc(r.label)}</button>`).join(" ") : "nessuno oltre le soglie"}</p>
      ${O.world ? `<p class="small muted">Mercato azionario mondiale (VWCE): 1 mese ${eoPct(O.world.returns?.["1m"])}, 6 mesi ${eoPct(O.world.returns?.["6m"])}, 12 mesi ${eoPct(O.world.returns?.["12m"])}, trend ${esc(O.world.trend || "n.d.")}.</p>` : ""}</div>
    <div class="card"><h3>Opportunità da approfondire <span class="muted small">(${esc(EO_MODES[D.mode])})</span></h3>
      ${sel.length ? `<div class="eo-grid">${sel.map(o => eoCard(o, D.mode)).join("")}</div>` : `<p class="small">${esc(D.noneText)}</p>`}
      <p class="muted small">${esc(D.orderRule)} Altre ${O.counts["Trend favorevole da monitorare"]} esposizioni hanno un trend favorevole da monitorare: sono nell'elenco sotto.</p></div>
    ${eoDetailHTML()}
    <div class="card"><h3>Tutte le esposizioni</h3><p class="small muted">Tocca una riga per la scheda. Una riga per esposizione: lo stesso fondo quotato su più borse non conta due volte.</p>${eoListHTML(D)}</div>
    <details class="fold" data-k="eo-method"><summary><span class="small">Metodo, soglie e dati usati</span></summary>
      <ul class="why small"><li><b>Stati</b>: «Esposizione da approfondire» tutte le condizioni favorevoli e nessuna contraria; se il rischio supera le soglie diventa «Rischio elevato».
        «Trend favorevole da monitorare» almeno 2 favorevoli e nessuna contraria; «Condizioni contrastanti» almeno una favorevole e una contraria. Una condizione non valutabile non conta mai come soddisfatta.</li>
        <li><b>Rendimenti</b>: totali in euro (chiusure rettificate per i dividendi), stesse date del benchmark, solo dati fino alla seduta indicata; la «rilevazione precedente» è ricalcolata con i soli dati di allora.</li>
        <li><b>Benchmark coerenti</b>: mondo (VWCE), USA (S&P 500), Europa (MSCI Europe), emergenti (MSCI EM IMI), settori e temi globali (MSCI World), settori USA (S&P 500). Mai QQQ per tutti.</li>
        <li><b>Obbligazioni</b>: duration, rendimento a scadenza, rating e costi dalla pagina dell'emittente con la loro data; niente medie mobili come metodo principale.
          Modello E2 (dal 5 novembre 2026): il rapporto rendimento ÷ duration è solo descrittivo (nel modello E1 era la condizione O1, soglia 1 senza giustificazione solida).
          Qualità del credito e costi descrivono il prodotto, non un'opportunità: senza condizioni contrarie lo stato è «${esc(EO_INS)}», mai «Esposizione da approfondire».
          La sensibilità ai tassi (±1 punto) è un'approssimazione con la duration, non una previsione, e non si somma al rendimento a scadenza.</li>
        <li><b>Valutazioni</b>: solo P/E e P/B pubblicati dall'emittente; mai stimati dai singoli titoli, mai DCF sugli ETF.</li>
        <li>Prezzi: ${esc(D.pricesSource || "")}. Catalogo del ${esc((D.catalogBuilt || "").replace("T", " "))}. Modello ${esc(D.version)}: cambiare soglie o condizioni richiede una nuova versione.</li>
        <li><b>Diario</b>: ${D.diary?.started ? `${D.diary.days} sedute registrate (dal ${esc(dayIT(D.diary.first))} al ${esc(dayIT(D.diary.last))}), ${D.diary.observations} osservazioni` : "nessuna seduta ancora registrata"}; si registra dopo la chiusura di Borsa Italiana, anche con la pagina chiusa (server acceso o job serale).</li></ul></details>
    <p class="muted small">${esc(D.disclaimer)}</p>`;
}
document.addEventListener("click", e => {
  if (!e.target.closest("#oppsBody")) return;
  const h = e.target.closest("[data-dkh]:not([data-dketf])");
  if (h) { DK.h = h.dataset.dkh; LS.set("dk.h", DK.h); DK.open = null; renderOpps(); return; }
  const k = e.target.closest("[data-dkk]");
  if (k) { DK.k = k.dataset.dkk; LS.set("dk.k", DK.k); DK.open = null; renderOpps(); return; }
  if (e.target.closest("[data-dkclose]")) { DK.open = null; renderOpps(); return; }
  const st = e.target.closest("[data-dkstock]");
  if (st) { openDetail(st.dataset.dkstock); return; }
  const et = e.target.closest("[data-dketf]");
  if (et) { opps.mode = "etf"; LS.set("opp.view", "etf"); EO.mode = et.dataset.dkh === "breve" ? "breve" : "lungo"; LS.set("eo.mode", EO.mode); loadEoDetail(et.dataset.dketf); return; }
  const dk = e.target.closest("tr[data-dkopen]");
  if (dk) { loadDeskDetail(dk.dataset.dkopen); return; }
  const md = e.target.closest("[data-eomode]");
  if (md) { EO.mode = md.dataset.eomode; LS.set("eo.mode", EO.mode); EO.open = null; renderOpps(); return; }
  if (e.target.closest("[data-eoclose]")) { EO.open = null; renderOpps(); return; }
  const op = e.target.closest("[data-eoopen]");
  if (op) { loadEoDetail(op.dataset.eoopen); return; }
});
document.addEventListener("click", e => {
  const b = e.target.closest("[data-oppetf]");
  if (!b) return;
  etfC.mode = "cat"; LS.set("etfMode", "cat");
  const keys = b.dataset.oppetf;
  setView("etf");
  loadEtfCat().then(() => {
    if (!keys || !etfC.data?.rows) return;
    const isins = keys.split(",").map(k => etfC.data.rows.find(r => r.isin === k || r.tickers.includes(k))?.isin).filter(Boolean);
    if (isins.length === 1) { etfCatOpen(isins[0]); return; }
    etfC.sel = isins; etfCatRefreshList(); etfCatCompare(isins);
  });
});
const ETF_DIV_INFO = `<b>Cosa diversifica di più</b>: per ogni ETF calcola come cambierebbero tecnologia, USA e dollaro (stimato dagli USA) se investissi il 10% del
  portafoglio. In cima gli ETF che abbassano di più la tua concentrazione più alta; esclusi quelli che ne farebbero salire anche una sola, i temi e i prodotti a leva.
  A parità di effetto (stesso valore al decimo di punto) viene prima chi abbassa di più anche le altre due, poi il TER più basso. Un ETF per categoria.
  <b>È una misura dell'effetto sul portafoglio, non una previsione di rendimento</b>: un ETF può diversificare e perdere.`;
function diversifyHTML(D) {
  const V = D.diversify;
  if (!V) return D.portfolioLoaded ? "" : `<div class="card empty small">Carica il portafoglio per vedere cosa lo diversifica di più.</div>`;
  const row = x => `<tr data-etf="${esc(x.isin)}"><td class="l"><b>${esc(x.category)}</b><div class="muted small">${esc(x.sentence)}</div></td>
      ${["tecnologia", "USA", "dollaro (stima)"].map(k => `<td class="${sign(x.delta[k])}">${fChg(x.delta[k])}</td>`).join("")}
      <td class="p2">${isNum(x.ter) ? fNum(x.ter, 2) + "%" : "—"}</td><td class="p2">${isNum(x.sizeEurM) ? fNum(x.sizeEurM, 0) + " mln €" : "—"}</td></tr>`;
  const table = (title, xs) => `<h4 class="bt-h">${title}</h4>${xs.length ? `<div class="table-wrap"><table class="scr mini div-tbl"><thead><tr><th class="l">ETF</th><th>Tecnologia</th><th>USA</th><th>Dollaro</th><th class="p2">TER</th><th class="p2">Patrimonio</th></tr></thead>
      <tbody>${xs.map(row).join("")}</tbody></table></div>` : `<p class="muted small">Nessun ETF dell'elenco abbassa la concentrazione senza farne salire un'altra.</p>`}`;
  const top = (V.equity[0] || V.defensive[0])?.top;
  return `<div class="card"><div class="card-h"><h2>Cosa diversifica di più il tuo portafoglio ${info(ETF_DIV_INFO)}</h2>
      <span class="card-meta">investendo il 10% del portafoglio · la tua concentrazione più alta oggi: ${esc(top || "—")} · differenze in punti</span></div>
    <div class="rad-cols"><div>${table("Azionari", V.equity)}</div><div>${table("Obbligazionari e difensivi (oro compreso)", V.defensive)}</div></div>
    <p class="muted small">Misura l'effetto sul portafoglio, non è una previsione di rendimento né un'indicazione di acquisto.</p></div>`;
}
// panel of one ETF
function openEtf(isin) {
  const r = etfRow(isin);
  if (!r) return;
  const f = etfFit(isin), J = r.justetf;
  state.detail = null; state.macro = null; state.panel = "etf"; etfS.open = isin;
  const pc = v => `<span class="${sign(v)}">${isNum(v) ? fPct(v, 1) : "—"}</span>`;
  const H = ETF_PER.map(x => x[0]), HL = Object.fromEntries(ETF_PER), B = etfS.data.buy?.[isin];
  const hp = k => ["r2w", "r6m", "r3y"].includes(k) ? "p4" : "";   // on phones: 1 week, 1 month, 3 months, 1 year
  const loc = k => isNum(r[k]) && r.fx && isNum(r.fx[k]) ? ((1 + r[k] / 100) / (1 + r.fx[k] / 100) - 1) * 100 : null;
  const list = rows => rows?.length ? rows.map(([n, p]) => `${esc(etfIt(n))} <b>${fNum(p, 1)}%</b>`).join(" · ") : "—";
  const conc = f ? Object.keys(f.before).map(k => `<tr><td class="l">${esc(k)}</td><td>${fNum(f.before[k], 1)}%</td><td>${fNum(f.after[k], 1)}%</td><td class="${sign(f.after[k] - f.before[k])}">${fChg(f.after[k] - f.before[k])}</td></tr>`).join("") : "";
  drawer.classList.remove("full");
  drawer.innerHTML = `<div class="d-top"><div class="d-head"><div><div class="tt">${esc(r.category)}</div><div class="nm">${esc(r.name || "")}</div>
        <div class="sec">${esc(r.isin)} · ${esc(r.yahoo || "")} · ${esc(r.provider || "")} · ${esc(r.group)}</div></div>
      <div class="actions"><button class="icon-btn star ${state.watch.has(r.yahoo) ? "on" : ""}" data-star="${esc(r.yahoo)}" title="${state.watch.has(r.yahoo) ? "Togli dai Preferiti" : "Aggiungi ai Preferiti"}" aria-pressed="${state.watch.has(r.yahoo)}">${state.watch.has(r.yahoo) ? "★" : "☆"}</button>
        <button class="icon-btn close-btn" id="dClose" aria-label="Chiudi">×</button></div></div></div>
    <div class="d-rest etf-d">
      <div class="d-sec"><h3>Per il mio portafoglio ${info(ETF_FIT_INFO)}</h3>
        ${f && !etfS.data.fitComplete ? `<p class="muted">In attesa dei prezzi storici del tuo portafoglio${etfS.data.pricesRetryAt ? ` (nuovo tentativo alle ${hm(etfS.data.pricesRetryAt)})` : ""}: senza correlazione il verdetto non è completo.</p>` : f ? `<p>${fitBadge(f)} <span class="muted">${esc(f.why)}</span></p>${f.held ? `<p><b>Lo possiedi</b> (${fNum(f.heldWeight, 1)}% del portafoglio). <button class="link-btn" data-pos="${esc(r.isin)}">Apri la sua posizione →</button></p>` : ""}
          ${f.notes.length ? `<p class="small">${f.notes.map(esc).join("<br>")}</p>` : ""}` : `<p class="muted">${etfS.data.portfolioLoaded ? "In calcolo." : "Portafoglio non caricato."}</p>`}</div>
      ${buySection(r, B)}
      <div class="d-sec"><h3>Perché si muove</h3><div id="etfWhy" class="small">${whyHTML(r, etfS.why[isin])}</div></div>
      <div class="d-sec"><h3>Rendimenti in euro</h3>
        <div class="table-wrap"><table class="scr ret-tbl"><thead><tr><th class="l"></th>${H.map(k => `<th class="${hp(k)}">${HL[k]}</th>`).join("")}</tr></thead><tbody>
          <tr><td class="l wrap"><b>In euro</b></td>${H.map(k => `<td class="${hp(k)}"><b>${pc(r[k])}</b></td>`).join("")}</tr>
          ${r.fx ? `<tr><td class="l wrap">di cui cambio</td>${H.map(k => `<td class="${hp(k)}">${pc(r.fx[k])}</td>`).join("")}</tr><tr><td class="l wrap">nella valuta del sottostante</td>${H.map(k => `<td class="${hp(k)}">${pc(loc(k))}</td>`).join("")}</tr>` : ""}</tbody></table></div>
        <p class="muted small">${esc(r.fxNote || "")} · Storico: ${esc(r.historySource || "—")}${r.fallback ? ` <b>(ripiego: rendimenti con *)</b> ${info(ETF_FALLBACK_INFO)}` : ""}
          · ETF nato il ${r.launchIso ? dayIT(r.launchIso) : esc(etfIt(r.launch) || "—")}</p>
        <div class="trend-big">${trendWord(r)} ${info(ETF_TREND_INFO)} ${sparkSVG(r.spark, 300, 70)}<span class="muted small">ultimi 6 mesi · media 200 tratteggiata</span></div>
        ${r.noPrices ? `<p class="down"><b>Prezzi non disponibili oggi</b> (Yahoo non li ha dati): rendimenti, trend e piano non calcolabili.</p>` : ""}
        <p>Trend: ${isNum(r.vs50) ? `${fPct(r.vs50, 1)} dalla media 50` : "—"} · ${isNum(r.vs200) ? `${fPct(r.vs200, 1)} dalla media 200` : "—"} · momentum 12-1 ${pc(r.mom12_1)}
          (${momText(r.momTercile, r.momMonths)}) ${info(ETF_MOM_INFO)}<br>Volatilità ${isNum(r.vol) ? fNum(r.vol, 0) + "%" : "—"} · perdita massima 3 anni ${isNum(r.maxDD3y) ? fPct(r.maxDD3y, 0) : "—"}
          ${r.group === "Temi" ? ` · ${info(ETF_SAT_INFO)} satellite` : ""}</p></div>
      <details class="d-sec fold"><summary><h3>Arrivati tardi e storia</h3></summary>
        <p>${lateText(r.late)} ${info(ETF_LATE_INFO)}${isNum(r.maxDDhist) ? `. Perdita massima nella storia disponibile (${fNum(r.longYears, 0)} anni, ${esc(r.longSource || "")}): ${fPct(r.maxDDhist, 0)}` : ""}${(r.longYears || 0) < 5 ? ". <b>Tema giovane</b>: meno di 5 anni di storia" : ""}.</p>
        <p class="small">Momentum (M1) e sopra la media 200 (M2) non hanno superato il test sulle categorie: <b>non verificati</b>.</p></details>
      <details class="d-sec fold"><summary><h3>Sovrapposizione, correlazione, concentrazione</h3></summary>
        ${f ? `<p>Sovrapposizione ${info(ETF_OVERLAP_INFO)}: <b>${isNum(f.overlap) ? fNum(f.overlap, 1) + " punti" : "non calcolabile (" + esc(r.holdings?.none || "composizione non disponibile") + ")"}</b>
            ${isNum(f.share) ? ` · quota dell'ETF in titoli che già possiedi ${info(ETF_SHARE_INFO)}: <b>${fNum(f.share, 0)}%</b>` : ""}</p>
          ${f.common.length ? `<div class="table-wrap"><table class="scr mini"><thead><tr><th class="l">Titoli in comune (primi 10 dell'ETF)</th><th>Peso nell'ETF</th><th>Peso nel tuo portafoglio</th></tr></thead>
            <tbody>${f.common.map(c => `<tr><td class="l">${esc(c.name)}</td><td>${fNum(c.etf, 1)}%</td><td>${fNum(c.mine, 2)}%</td></tr>`).join("")}</tbody></table></div>` : ""}
          <p>Correlazione con il tuo portafoglio (settimanale, 2 anni, in euro): <b>${isNum(f.corr) ? fNum(f.corr, 2) : "in calcolo"}</b></p>
          <div class="table-wrap"><table class="scr"><thead><tr><th class="l">Se investissi il 10% del portafoglio</th><th>Oggi</th><th>Dopo</th><th>Differenza</th></tr></thead><tbody>${conc}</tbody></table></div>
          <p class="muted small">Pesi sull'esposizione effettiva. Composizione dell'ETF da justETF (primi 5 paesi e settori). Il dollaro è stimato dal peso degli USA.</p>` : `<p class="muted">Portafoglio non caricato.</p>`}</details>
      <details class="d-sec fold"><summary><h3>Composizione</h3></summary>
        <p><b>Primi 10 titoli:</b> ${list(J.top10)}<br><b>Paesi:</b> ${list(J.countries)}<br><b>Settori:</b> ${list(J.sectors)}</p>
        <p class="muted small">Paesi e settori: ${esc(etfIt(J.holdingsDate) || "")}, fonte justETF.
          Primi 10 titoli per il confronto con il tuo portafoglio: ${r.holdings?.top ? `<a href="${esc(r.holdings.source)}" target="_blank" rel="noopener">${esc(r.holdings.label)}</a>, dati al ${dayIT(r.holdings.asOf || r.holdings.fetched)}` : esc(r.holdings?.none || "non disponibili")}.</p></details>
      <details class="d-sec fold"><summary><h3>Dati dell'ETF</h3></summary>
        <div class="d-stats">${[["TER", isNum(r.ter) ? fNum(r.ter, 2) + "%" : "—"], ["Patrimonio", isNum(r.sizeEurM) ? fNum(r.sizeEurM, 0) + " mln €" : "—"], ["Dividendi", etfIt(r.distribution) || "—"],
          ["Replica", [etfIt(r.replication), etfIt(J.replicationMethod)].filter(Boolean).join(", ") || "—"], ["Cambio", etfIt(r.hedge) || "—"], ["Struttura", r.legal || "—"], ["Indice", r.index || "—"], ["Lancio", etfIt(r.launch) || "—"],
          ["Valuta del sottostante", r.underlyingCurrency], ["P/E (ETF americano " + (r.usProxy || "—") + ")", isNum(r.pe) ? fNum(r.pe, 1) : "—"]].map(([l, v]) => `<div><span>${esc(l)}</span><span>${esc(v)}</span></div>`).join("")}</div>
        <p class="muted small">Fonte: <a href="${esc(J.source)}" target="_blank" rel="noopener">justETF</a>, letto il ${dayIT(J.date)}${r.stale ? ` · <b class="down">dati con più di 6 mesi: da aggiornare</b>` : ""}.
          ${r.usProxy ? `L'ETF americano ${esc(r.usProxy)} è usato solo come fonte di dati, mai come prodotto da comprare.` : ""}${r.note ? `<br>${esc(r.note)}` : ""}</p></details>
      <p class="small">${info(ETF_FISCAL_INFO)} Tasse, accumulazione e distribuzione, cambio coperto.</p>
      <p class="disclaimer">Dati e confronti a scopo di studio, non verificati come indicazioni di acquisto. Non è una consulenza finanziaria.</p></div>`;
  drawer.classList.add("open"); drawer.setAttribute("aria-hidden", "false"); scrim.hidden = false;
  $("#dClose").onclick = closeDetail;
  if (!etfS.why[isin]) getJSON(`/api/etf/why/${encodeURIComponent(isin)}`).then(w => { etfS.why[isin] = w; const el = $("#etfWhy"); if (el && etfS.open === isin) el.innerHTML = whyHTML(r, w); })
    .catch(() => { const el = $("#etfWhy"); if (el) el.textContent = "Non disponibile al momento."; });
}
// "Perché si muove": contribution of the first holdings of the US equivalent, the most similar category, headlines
function whyHTML(r, w) {
  const mw = r.movesWith ? `<p>${esc(r.movesWith.text[0].toUpperCase() + r.movesWith.text.slice(1))} (rendimenti giornalieri in euro).</p>` : "";
  if (!w) return mw + `<p class="muted">Calcolo il contributo dei primi titoli…</p>`;
  const c = ["r1m", "r3m", "r1y"].map(k => w.contrib?.[k]?.text).filter(Boolean);
  return mw + (c.length ? `<ul class="why">${c.map(t => `<li>${esc(t)}</li>`).join("")}</ul>`
      : `<p class="muted">${w.proxy ? `I primi titoli dell'ETF americano equivalente (${esc(w.proxy)}) non spiegano almeno il 10% del movimento: nessuna frase sul contributo.` : "Nessun ETF americano equivalente: contributo dei titoli non calcolabile."}</p>`)
    + (w.news?.length ? `<p class="muted">Notizie: ${w.news.map(n => `${esc(n.symbol)} · ${n.url ? `<a href="${esc(n.url)}" target="_blank" rel="noopener">${esc(n.title)}</a>` : esc(n.title)}`).join(" — ")}</p>` : "");
}
// "Ha senso comprare?" in the panel: verdict, the market-only line, every rule with ✅/❌, the plan
function buySection(r, B) {
  if (!B) return "";
  const mk = B.market, ck = c => `<li>${c.ok ? "✅" : "❌"} <b>${c.id}</b> ${esc(c.label)}: ${esc(c.value)}${c.personal ? ` <span class="muted small">(tuo portafoglio)</span>` : ""}</li>`;
  const p = B.plan;
  const qtyTxt = q => !q ? "quantità non calcolabile (portafoglio non caricato)" : `${q.qty} quote ≈ ${fEur(q.eur)} (${fNum(q.weight, 1)}% del portafoglio)`;
  const planHTML = !p ? (B.plan === null ? `<p class="muted small">Piano non disponibile: prezzi di Borsa Italiana insufficienti per entrata e stop.</p>` : "") : `
      <h4 class="bt-h">Piano operativo ${p.kind === "now" ? "(Entra ora)" : "(Entra su ritracciamento)"}${B.planFor === "solo mercato" ? " · secondo il solo mercato" : ""}</h4>
      <div class="d-stats">${[["Entrata", `${fNum(p.entry, 2)} € · ${esc(p.entryNote)}`], ["Stop", `${fNum(p.stop, 2)} €`], ["Obiettivo (2 volte il rischio)", `${fNum(p.target, 2)} €`],
        ["Quantità", qtyTxt(p.qty)], ["Borsa", `${esc(r.planLevels.market)} (${esc(p.listing || "")}) · prezzi del ${dayIT(p.date)}`]].map(([l, v]) => `<div><span>${l}</span><span>${v}</span></div>`).join("")}</div>
      ${isNum(r.planLevels.mismatch) ? `<p class="small down"><b>Attenzione:</b> nei dati di Yahoo l'ultimo prezzo di Borsa Italiana e quello di Xetra differiscono del ${fNum(Math.abs(r.planLevels.mismatch), 1)}%:
        uno dei due è sbagliato. Il piano usa ${esc(r.planLevels.market)}; controlla il prezzo su Fineco prima di inserire l'ordine.</p>` : ""}
      <p class="small">${p.qty ? esc(p.qty.sentence[0].toUpperCase() + p.qty.sentence.slice(1)) + ". " : ""}Stop: ${esc(p.opts.find(o => o.id === p.def).label)}, perché ${esc(p.why)} ${esc(p.spread)}.</p>
      <details class="fold"><summary><span class="small">Altri stop possibili</span></summary><div class="table-wrap"><table class="scr mini stop-tbl"><thead><tr><th class="l">Stop</th><th>Livello</th><th>Obiettivo</th><th class="l">Quantità</th></tr></thead>
        <tbody>${p.opts.map(o => `<tr${o.id === p.def ? ' class="on"' : ""}><td class="l wrap">${esc(o.label)}</td><td>${fNum(o.v, 2)} €</td><td>${fNum(o.target, 2)} €</td><td class="l wrap">${qtyTxt(o.qty)}</td></tr>`).join("")}</tbody></table></div></details>`;
  return `<div class="d-sec buy-sec"><h3>Ha senso comprare? ${info(BUY_INFO)}</h3>
      <p>${B.verdict ? buyBadge(B.verdict, true) : buyBadge(mk.verdict, true)} <span class="muted small">non verificato</span> · ${esc(B.verdict ? B.why : mk.why)}
        <span class="muted small">(regola ${esc(B.verdict ? B.by : mk.by)})</span></p>
      <p class="small muted">${B.verdict ? `Solo mercato (senza considerare il tuo portafoglio): <b>${esc(mk.verdict)}</b> · ${esc(mk.why)} (regola ${esc(mk.by)})`
        : etfS.data.portfolioLoaded ? "Il verdetto per il tuo portafoglio è in calcolo (serve la correlazione): sopra c'è quello del solo mercato." : "Portafoglio non caricato: sopra c'è il verdetto del solo mercato."}</p>
      <ul class="checks">${B.checks.map(ck).join("")}</ul>
      <p class="small">Momentum 12-1: ${isNum(B.momentum) ? fPct(B.momentum, 1) : "—"} (${momText(r.momTercile, r.momMonths)}) ${info(ETF_MOM_INFO)} · solo informazione.</p>
      ${planHTML}</div>`;
}
// ETFs I follow (★): a closed section of the ETF tab, shown only with at least one star
function etfWatchHTML(D) {
  const mine = (D.rows || []).filter(r => state.watch.has(r.yahoo));
  if (!mine.length) return "";
  const pc = v => `<span class="${sign(v)}">${isNum(v) ? fPct(v, 1) : "—"}</span>`;
  const v = r => D.fitComplete ? D.buy?.[r.isin]?.verdict : D.buy?.[r.isin]?.market.verdict;
  return `<details class="card fold"><summary><span class="small"><b>ETF preferiti</b> (${mine.length}): quelli con la ★</span></summary>
    <div class="table-wrap"><table class="scr"><thead><tr><th class="l">ETF</th><th class="p3">1 sett.</th><th class="p3">1 mese</th><th>3 mesi</th><th class="p3">1 anno</th><th class="l p4">Trend</th><th class="l">Ha senso comprare?</th></tr></thead>
    <tbody>${mine.map(r => `<tr data-etf="${esc(r.isin)}"><td class="l"><b>${esc(r.category)}</b> <span class="muted small">${esc(r.yahoo)}</span></td><td class="p3">${pc(r.r1w)}</td><td class="p3">${pc(r.r1m)}</td><td>${pc(r.r3m)}</td><td class="p3">${pc(r.r1y)}</td>
      <td class="l trend-c p4">${trendWord(r)}</td><td class="l">${buyBadge(v(r))}</td></tr>`).join("")}</tbody></table></div></details>`;
}
document.addEventListener("click", e => {
  const g =e.target.closest("[data-etfgrp]");
  if (g) { etfS.grp = g.dataset.etfgrp; LS.set("etfGrp", etfS.grp); return renderEtf(); }
  if (e.target.closest("[data-etfclear]")) { etfS.ft = etfS.fb = ""; LS.set("etfTrend", ""); LS.set("etfBuy", ""); return renderEtf(); }
  const s = e.target.closest("[data-etfsort]");
  if (s && !e.target.closest(".info")) { const k = s.dataset.etfsort; etfS.sort = etfS.sort.key === k ? { key: k, dir: -etfS.sort.dir } : { key: k, dir: k === "name" ? 1 : -1 }; LS.set("etfSort", k); return renderEtf(); }
  const o = e.target.closest("[data-etf]");
  if (o && !e.target.closest(".info, a")) openEtf(o.dataset.etf);
});

// ------------------------------------------------------------ Diario dei segnali (diary.py): live check of the verdicts
const DIARY_INFO = `Analisti, valutazione e notizie non hanno uno storico gratuito, quindi i verdetti della sezione Decisione non si possono provare sul passato.
  Il diario li verifica <b>da oggi in avanti</b>: dopo ogni chiusura salva il verdetto di ogni titolo del Nasdaq-100 e delle tue posizioni, e dopo 1, 3 e 6 mesi misura com'è andata
  ogni categoria rispetto a QQQ e a tutti i titoli dello stesso giorno. <b>Il diario non si modifica mai a posteriori.</b>`;
const diary = { data: null, hz: "1M", at: 0 };
async function loadDiary() {
  if (!diary.data || Date.now() - diary.at > 5 * 60_000) {
    diary.at = Date.now();
    try { diary.data = await getJSON("/api/diary"); } catch { diary.data = null; }
  }
  renderDiary();
}
function renderDiary() {
  const el = $("#diaryBody"), D = diary.data;
  if (!D) { el.innerHTML = `<div class="card empty">Diario non disponibile al momento.</div>`; return; }
  const hzLab = { "1M": "1 mese", "3M": "3 mesi", "6M": "6 mesi" };
  const intro = `<p class="warn-box"><b>Verifica dal vivo, non un backtest.</b> ${D.days ? `Il diario ha ${D.days} ${D.days === 1 ? "giorno" : "giorni"} (dal ${dayIT(D.first)} al ${dayIT(D.last)}).` : "Il diario è ancora vuoto: il primo salvataggio avviene dopo la prossima chiusura della borsa, con la dashboard accesa."}
    Finché una categoria ha meno di ${D.minCases} casi o meno di ${D.minDays} giorni diversi, i numeri possono essere solo caso e <b>non vanno usati per decidere</b>. Non è una consulenza finanziaria.</p>
    ${D.excluded?.length ? `<p class="muted small">Esclusi dalle statistiche (i file restano com'erano): ${D.excluded.map(x => `${dayIT(x.date)} — ${esc(x.why)}`).join(" · ")}.</p>` : ""}
    ${D.missing?.length ? `<p class="muted small">Sedute senza diario (la dashboard o il job serale non erano attivi dopo la chiusura): ${D.missing.map(dayIT).join(", ")}.</p>` : ""}`;
  const today = D.today.length ? `<div class="card"><div class="card-h"><h2>Verdetti dell'ultimo giorno salvato</h2><span class="card-meta">${dayIT(D.last)} · titoli del Nasdaq-100 e mie posizioni</span></div>
    <div class="pt-stocks">${D.today.map(x => `<span class="act ${VERDICT_CLS[x.category] || "hold"}">${esc(x.category)} · ${x.n}</span>`).join("")}</div></div>` : "";
  const H = D.horizons[diary.hz], rows = H?.rows || [];
  const pc = v => `<span class="${sign(v)}">${fPct(v, 2)}</span>`, pp = v => `<span class="${sign(v)}">${ptPts(v)}</span>`;
  const wait = D.pending[diary.hz];
  const table = rows.length ? `<div class="table-wrap"><table class="scr"><thead><tr><th class="l">Verdetto</th><th>Casi</th><th>Giorni</th><th>Rendimento medio</th><th>Mediano</th><th>Extra vs QQQ (media)</th><th>Extra vs QQQ (mediana)</th>
      <th>% volte meglio di QQQ</th><th>Extra vs tutti i titoli (media)</th><th>(mediana)</th><th class="l">Affidabilità</th></tr></thead>
    <tbody>${rows.map(r => `<tr class="${r.enough ? "" : "muted"}"><td class="l"><span class="act ${VERDICT_CLS[r.category] || "hold"}">${esc(r.category)}</span></td><td>${fNum(r.n, 0)}</td><td>${r.days}</td>
      <td>${pc(r.ret)}</td><td>${pc(r.retMedian)}</td><td>${pp(r.excess)}</td><td>${pp(r.excessMedian)}</td><td>${fNum(r.beat, 1)}%</td><td><b>${pp(r.vsAll)}</b></td><td>${pp(r.vsAllMedian)}</td>
      <td class="l">${r.enough ? "casi sufficienti" : `<b>troppo pochi casi</b>`}</td></tr>`).join("")}</tbody></table></div>
    ${rows.some(r => !r.enough) ? `<p class="small"><b>Attenzione:</b> le righe in grigio hanno ancora troppo pochi casi (servono almeno ${D.minCases} casi in almeno ${D.minDays} giorni diversi): non se ne possono trarre conclusioni.</p>` : ""}`
    : `<div class="empty">${D.days ? `Nessun risultato a ${hzLab[diary.hz]} ancora: servono ${H?.sessions} sedute di borsa dal primo giorno del diario${isNum(wait) && wait > 0 ? ` (ne mancano circa ${wait})` : ""}.` : "Nessun giorno salvato."}</div>`;
  el.innerHTML = `${intro}${today}
    <div class="card"><div class="card-h"><h2>Com'è andata ogni categoria di verdetto ${info(DIARY_INFO)}</h2>
      <div class="seg small">${Object.keys(hzLab).map(h => `<button data-dz="${h}" class="${h === diary.hz ? "on" : ""}">${hzLab[h]}</button>`).join("")}</div>
      <span class="card-meta">${H ? `${H.days} giorni misurati` : ""}</span></div>
      ${table}
      ${H?.byRule?.length ? `<details class="fold"><summary><span class="small">Per regola che ha deciso il verdetto (per esempio «Attendi» per trimestrale o per media 200)</span></summary>
        <div class="table-wrap"><table class="scr"><thead><tr><th class="l">Verdetto</th><th class="l">Deciso da</th><th>Casi</th><th>Giorni</th><th>Extra vs QQQ (media)</th><th>% volte meglio di QQQ</th><th>Extra vs tutti (media)</th><th>(mediana)</th><th class="l">Affidabilità</th></tr></thead>
        <tbody>${H.byRule.map(r => `<tr class="${r.enough ? "" : "muted"}"><td class="l">${esc(r.category)}</td><td class="l">${esc(r.ruleName)}</td><td>${fNum(r.n, 0)}</td><td>${r.days}</td>
          <td>${pp(r.excess)}</td><td>${fNum(r.beat, 1)}%</td><td><b>${pp(r.vsAll)}</b></td><td>${pp(r.vsAllMedian)}</td><td class="l">${r.enough ? "casi sufficienti" : "<b>troppo pochi casi</b>"}</td></tr>`).join("")}</tbody></table></div></details>` : ""}
      <p class="muted small">Rendimento del titolo dalla chiusura del giorno del verdetto a ${H?.sessions || ""} sedute dopo; «extra vs tutti» = rendimento meno la media di tutti i titoli del Nasdaq-100 salvati lo stesso giorno, come nel test dei pattern.</p>
      <h4 class="bt-h">Limiti: leggili prima di fidarti dei numeri</h4><ul class="why bt-lim">${D.limits.map(l => `<li><b>${esc(l.title)}.</b> ${esc(l.text)}</li>`).join("")}</ul>
      <p class="muted small">Dati salvati in <code>portafoglio/diario/</code>, un file per seduta, solo su questo Mac. Ogni giorno contiene, per ogni titolo: prezzo, verdetto, livelli del piano e regole soddisfatte o no.</p></div>`;
}
// ETF diary (etf_buy.py): both verdicts of every ETF, measured against all the ETFs of the same day
function etfDiaryHTML(E, hz) {
  if (!E) return "";
  if (!E.days) return `<p class="muted small">Nessun giorno salvato ancora: il primo dopo le 18:00 di una giornata di borsa, con la dashboard accesa (o dal job serale).</p>`;
  const pp = v => `<span class="${sign(v)}">${ptPts(v)}</span>`;
  const tab = (title, S) => {
    const rows = Object.entries(S?.[hz] || {});
    return `<h4 class="bt-h">${title}</h4>${rows.length ? `<div class="table-wrap"><table class="scr mini"><thead><tr><th class="l">Verdetto</th><th>Casi</th><th>Giorni</th><th>Rendimento medio</th><th>Extra vs tutti gli ETF</th><th>% volte meglio</th><th class="l">Affidabilità</th></tr></thead>
      <tbody>${rows.map(([v, r]) => `<tr class="${r.enough ? "" : "muted"}"><td class="l">${buyBadge(v)}</td><td>${r.cases}</td><td>${r.days}</td><td>${fPct(r.mean, 2)}</td><td><b>${pp(r.extra)}</b></td><td>${fNum(r.beat, 1)}%</td>
        <td class="l">${r.enough ? "casi sufficienti" : "<b>troppo pochi casi</b>"}</td></tr>`).join("")}</tbody></table></div>` : `<p class="muted small">Nessun risultato a ${hz} ancora.</p>`}`;
  };
  return `<p class="small">${E.days} ${E.days === 1 ? "giorno salvato" : "giorni salvati"} · risultati a ${hz}</p>
    ${tab("Verdetto per il tuo portafoglio", E.personal)}${tab("Solo mercato (senza il tuo portafoglio)", E.market)}
    <p class="muted small">Rendimento dell'ETF su Borsa Italiana dalla chiusura del giorno del verdetto a ${hz}; «extra» = meno la media di tutti gli ETF salvati lo stesso giorno.
      Servono almeno 100 casi in almeno 20 giorni diversi. Dati in <code>portafoglio/diario_etf/</code>, un file per seduta, mai modificato dopo.</p>`;
}
etfDiaryHTML.more = "";
document.addEventListener("click", e => { const b = e.target.closest("[data-dz]"); if (b) { diary.hz = b.dataset.dz; renderDiary(); } });

// ------------------------------------------------------------ Opportunità (phases O1-O2, opportunity_scanner.py)
// Two exploratory rankings computed by the server on closed sessions: stocks to study, never a buy signal.
// Phase O2: relative strength, absolute direction and market context shown apart; coverage of the data; the
// "Monitoraggio risultati" panel of the opportunity diary (opportunity_diary.py), closed by default.
const opps = { data: null, at: 0, err: null, mode: LS.get("opp.view", "desk"), open: new Set(), diary: null, diaryErr: null,
  inv: null, invAt: 0, invErr: null, invLoading: false, invFilter: "all", invSort: { k: "order", dir: 1 },
  val: null, valAt: 0, valErr: null, valLoading: false, valFilter: "all" };
const OPP_MODES = { desk: "Decision Desk · azioni ed ETF", trading: "Trading · breve periodo", invest: "Investimento · medio-lungo periodo", etf: "ETF · esposizioni e prodotti" };
const OPP_LIMITS = [
  ["Condizioni non verificate", "Nessuna condizione è stata provata con un backtest. Nel test della Fase 11 i pattern di forza (Leader di momentum, momentum 12-1, massimi a 52 settimane) non hanno superato le condizioni: la classifica Trading usa misure simili, quindi indica solo titoli da guardare, non titoli che salgono."],
  ["Classifica relativa", "«Più forte del Nasdaq-100» vuol dire meglio di QQQ: in un mercato in calo può significare «scende meno». Per questo la tabella mostra a parte il rendimento del titolo e quello rispetto a QQQ, e segnala chi è più forte di QQQ ma in calo."],
  ["Dati di oggi", "Analisti, valutazione, notizie e date delle trimestrali sono quelli di oggi: non hanno uno storico gratuito e non si possono provare sul passato. Il diario delle opportunità li salva da ora in avanti."],
  ["Fondamentali da Yahoo Finance", "Bilanci, stime e consenso possono mancare o arrivare in ritardo; Yahoo dà pochi anni di bilanci. Un dato mancante non conta mai come condizione soddisfatta."],
  ["Solo i titoli di oggi", "La classifica guarda i titoli che oggi sono nel Nasdaq-100: niente altri mercati e niente ETF in questa fase."],
];
async function loadOpps() {
  if (!opps.data || Date.now() - opps.at > 5 * 60_000) {
    opps.at = Date.now();
    try {
      const r = await fetch("/api/opportunities", { cache: "no-store" });
      if (r.status === 503) { opps.err = "loading"; opps.at = 0; }
      else if (!r.ok) { opps.err = (await r.json().catch(() => ({}))).error || r.statusText; opps.at = 0; }
      else { opps.data = await r.json(); opps.err = null; }
    } catch (e) { opps.err = e.message; opps.at = 0; }
    try { opps.diary = await getJSON("/api/opportunities/diary"); opps.diaryErr = null; } catch (e) { opps.diaryErr = e.message; }
    try { opps.dstatus = await getJSON("/api/diaries/status"); } catch (e) { opps.dstatus = null; }
    try { opps.lab = await getJSON("/api/opportunities/validation"); } catch (e) { opps.lab = null; }
    try { opps.strat = await getJSON("/api/opportunities/strategies"); } catch (e) { opps.strat = null; }
  }
  renderOpps();
}
const oppTime = iso => iso ? new Date(iso).toLocaleString("it-IT", { timeZone: tz, day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) + " ora NY" : "";
const oppPct = v => `<span class="${sign(v)}">${fPct(v, 1)}</span>`;
function oppMarketLine(M) {
  if (!M || !isNum(M.qqq1m)) return "";
  return `<p class="small opp-mkt"><b>Mercato (QQQ, sedute chiuse):</b> 1 mese ${oppPct(M.qqq1m)} · 3 mesi ${oppPct(M.qqq3m)} · trend ${esc((M.qqqTrend || "non calcolabile").toLowerCase())}
    (${fPct(M.qqqVs50, 1)} dalla media 50, ${fPct(M.qqqVs200, 1)} dalla media 200)${isNum(M.above200) ? ` · titoli sopra la media 200: ${fNum(M.above200, 0)}% di ${M.above200n}` : ""}</p>`;
}
// Phase 6C: state of the four diaries (diaries_status.py, read only): official records, excluded test records, missing
// sessions and next update, in one small table inside the closed "Monitoraggio risultati" panel.
function diaryStatusHTML() {
  const D = opps.dstatus;
  if (!D || !D.diaries) return "";
  const rows = D.diaries.map(r => `<tr><td class="l">${esc(r.name)}</td><td>${r.last ? esc(dayIT(r.last.session)) : "—"}</td>
    <td>${fNum(r.official.observations, 0)}</td><td>${r.excluded.observations ? `<span class="warn">${fNum(r.excluded.observations, 0)}</span>` : "0"}</td>
    <td>${r.missing.length ? `<span class="warn">${r.missing.length}</span>` : "0"}</td><td class="l small">${esc(r.next || "")}</td></tr>`).join("");
  const notes = D.diaries.flatMap(r => [...(r.notes || []), ...r.errors.map(e => "⚠ " + e)]);
  return `<h4 class="bt-h">Stato dei diari</h4>
    <div class="table-wrap"><table class="scr mini ds-tbl"><thead><tr><th class="l">Diario</th><th>Ultima seduta ufficiale</th><th>Osservazioni ufficiali</th>
      <th>Prove escluse</th><th>Sedute mancanti</th><th class="l">Prossimo aggiornamento</th></tr></thead><tbody>${rows}</tbody></table></div>
    <p class="muted small">Contano solo le registrazioni di origine ${D.officialSources.map(x => "«" + esc(x) + "»").join(", ")}; prove, test e anteprime restano nel file
      ma sono escluse dalle statistiche. Job serale: ${esc(D.eveningJob)}.${notes.length ? " " + notes.map(esc).join(" ") : ""}</p>`;
}
function oppDiaryHTML() {
  return diaryStatusHTML() + oppDiaryBody();
}
function oppDiaryBody() {
  const S = opps.diary;
  if (!S) return `<p class="muted small">Diario non leggibile al momento${opps.diaryErr ? ` (${esc(opps.diaryErr)})` : ""}.</p>`;
  if (!S.started) return `<p class="small">Il diario non ha ancora registrato nessuna seduta: la prima registrazione avviene dopo la prossima chiusura di Wall Street, con la dashboard accesa o con il job serale. I risultati si misurano solo quando sono passate le sedute necessarie.</p>`;
  const lab = { trading: "Trading", invest: "Investimento" };
  const cell = g => g.enough ? `${fPct(g.mean, 2)} · mediana ${fPct(g.median, 2)}` : `<span class="muted">in raccolta</span>`;
  const vs = g => g.enough ? `${ptPts(g.excess)} · mediana ${ptPts(g.excessMedian)}` : "—";
  const lists = Object.entries(S.lists).map(([k, L]) => `<h4 class="bt-h">${lab[k]} <span class="muted">· ${fNum(L.observations, 0)} osservazioni, di cui ${fNum(L.selected, 0)} in classifica e ${fNum(L.insufficient, 0)} con dati insufficienti</span></h4>
    <div class="table-wrap"><table class="scr mini"><thead><tr><th class="l">Orizzonte</th><th>Maturate</th><th>In attesa</th><th>Prezzo mancante</th><th>Casi usati (in classifica)</th>
      <th>Rendimento in classifica</th><th>Differenza con QQQ (punti)</th><th>Rispetto alla mediana dei titoli</th><th>Altri titoli: differenza con QQQ</th></tr></thead>
    <tbody>${Object.entries(L.horizons).map(([h, H]) => { const g = H.groups.selected, o = H.groups.others;
      return `<tr><td class="l">${h} sedute</td><td>${fNum(H.matured, 0)}</td><td>${fNum(H.pending, 0)}</td><td>${fNum(H.missingPrice, 0)}</td>
        <td>${g.n} casi in ${g.days} ${g.days === 1 ? "giorno" : "giorni"}</td><td>${cell(g)}</td><td>${vs(g)}</td><td>${g.enough && isNum(g.vsUniverse) ? ptPts(g.vsUniverse) : "—"}</td>
        <td>${o.enough ? ptPts(o.excess) : `<span class="muted">${o.n} casi: in raccolta</span>`}</td></tr>`; }).join("")}</tbody></table></div>`).join("");
  return `<p class="small">Attivo dal <b>${esc(dayIT(S.first))}</b> · <b>${S.days}</b> ${S.days === 1 ? "giornata registrata" : "giornate registrate"} · ultima: ${esc(dayIT(S.last))}
      (calcolo ${esc(oppTime(S.lastComputedAt))}, ${esc(S.lastSource)}) · versione del modello ${esc(S.versions.join(", "))}</p>
    <p class="small">Le medie compaiono solo con almeno ${S.minCases} casi maturati in almeno ${S.minDays} giornate diverse; prima i dati sono <b>in raccolta</b>.
      «Maturate» = osservazioni per cui sono passate le sedute dell'orizzonte. Riferimenti: QQQ nello stesso intervallo e mediana di tutti i titoli salvati lo stesso giorno.</p>
    ${lists}
    <h4 class="bt-h">Limiti</h4><ul class="why bt-lim">${S.limits.map(l => `<li><b>${esc(l.title)}.</b> ${esc(l.text)}</li>`).join("")}</ul>
    <p class="muted small">Dati in <code>data/opportunita.sqlite3</code>: solo dati pubblici di mercato, separati dal portafoglio. Non è un backtest e non è una consulenza finanziaria.</p>`;
}
// phase 4A: validation state of the rule behind the list shown (documented criteria, computed by the server)
function oppStateLine(trading) {
  const R = opps.lab?.reliability;
  const it = R?.items?.find(x => x.id === (trading ? "C4" : "INV"));
  const extra = trading ? R?.items?.find(x => x.id === "C5") : null;
  if (!it) return `<p class="small opp-state"><b>Screening esplorativo</b> · stato di validazione non disponibile al momento.
    Il numero di condizioni soddisfatte non è una previsione di rendimento.</p>`;
  return `<p class="small opp-state"><b>${esc(R.screening)}</b> · regola ${trading ? "4 su 5" : "5 su 6"}: <b>${esc(it.shortLabel)}</b> (${esc(it.short)})${extra ? `
    · tutte e 5: <b>${esc(extra.shortLabel)}</b>` : ""}. Il numero di condizioni soddisfatte non è una previsione di rendimento. Dettagli in «Qualità dei segnali».</p>`;
}
function oppReliabilityHTML(R) {
  if (!R) return "";
  return `<h4 class="bt-h">Stato di affidabilità</h4>
    <div class="table-wrap"><table class="scr mini"><thead><tr><th class="l">Regola</th><th class="l">Stato</th><th class="l">Perché</th></tr></thead>
    <tbody><tr><td class="l">Classifiche Trading e Investimento</td><td class="l"><b>${esc(R.screening)}</b></td><td class="l small wrap">${esc(R.note)}</td></tr>
    ${R.items.map(x => `<tr><td class="l">${esc(x.name)}</td><td class="l"><b>${esc(x.label)}</b></td><td class="l small wrap">${esc(x.reason)}</td></tr>`).join("")}</tbody></table></div>
    <details class="fold" data-k="labcrit"><summary><span class="small">Criteri degli stati</span></summary>
      <ul class="why">${R.criteria.map(c => `<li><b>${esc(c.title)}</b>: ${esc(c.text)}</li>`).join("")}</ul></details>`;
}
const oppVerdict = x => !x ? "—" : x.startsWith("Evidenza") ? "insufficiente" : x.includes("non credibile") ? "non credibile"
  : x.includes("credibile nello") ? (x.includes("peggiore") ? "peggiore, credibile" : "migliore, credibile")
  : x.includes("non confermata") ? "non confermata" : "verifica impossibile";
// phase 4B: experimental strategies (opportunity_strategies.py), separate from the current rule and from the diary
function oppStratHTML() {
  const X = opps.strat;
  const head = `<h4 class="bt-h">2 · Strategie sperimentali (ricerca 4B, non usate dalla classifica)</h4>`;
  if (!X) return `${head}<p class="muted small">Riepilogo non leggibile al momento.</p>`;
  if (!X.available) return `${head}<p class="small">Nessuno studio salvato. Si avvia a mano dal Terminale: <code>.venv/bin/python opportunity_strategies.py run</code>.</p>`;
  const S = X.summary, pt = x => x && isNum(x.mean) ? `${ptPts(x.mean)} <span class="muted">(t ${fNum(x.t, 1)})</span>` : "—";
  const row = r => r.id === "C"
    ? `<tr><td class="l">${esc(r.name)}</td><td class="l"><b>${esc(r.state)}</b></td><td colspan="3" class="l small wrap">Episodi ribassisti ${r.episodes.dev} nello sviluppo e ${r.episodes.ver} nella verifica
        (ne servono ${r.episodes.need[0]} e ${r.episodes.need[1]}). Filtro «nessun ingresso con QQQ sotto la media 200»: ${r.filter.map(f => `${esc({ A_TOP: "A", B: "B", C4: "regola 4/5" }[f.strategy] || f.strategy)} rendimento/rischio ${fNum(f.raWithout, 2)} → ${fNum(f.raWith, 2)}`).join(" · ")}.</td>
        <td class="l small wrap">${esc(r.note)}</td></tr>`
    : `<tr><td class="l">${esc(r.name)}</td><td class="l"><b>${esc(r.state)}</b></td><td>${ptPts(r.dev)} → ${ptPts(r.ver)}</td>
        <td>${pt(r.key)}<div class="muted small">${esc(r.key.label)}</div></td><td>${pt(r.vsOld)}</td><td class="l small wrap">${esc(r.note)}</td></tr>`;
  return `${head}<details class="fold" data-k="labstrat"><summary><span class="small">A · forza nel settore — <b>${esc(S.rows[0].state)}</b> · B · ritracciamento nel trend — <b>${esc(S.rows[1].state)}</b> · C · contesto di mercato — <b>${esc(S.rows[2].state)}</b></span></summary>
    <p class="small">Tre ipotesi scritte e registrate <b>prima</b> dei risultati (configurazione ${esc(S.version)}, impronta <code>${esc(S.configHash)}</code>), una sola configurazione ciascuna,
      sugli stessi dati congelati della Fase 3 e solo fino al ${esc(dayIT(S.finalStart))} escluso: il periodo finale non viene letto. ${esc(S.label)}. Studio del ${esc(oppTime(S.createdAt))}.</p>
    <div class="table-wrap"><table class="scr mini"><thead><tr><th class="l">Strategia (orizzonte ${S.horizon} sedute)</th><th class="l">Stato</th>
      <th>Contro i non scelti: sviluppo → verifica (punti)</th><th>Confronto chiave</th><th>Contro la regola 4/5</th><th class="l">Limite</th></tr></thead>
      <tbody>${S.rows.map(row).join("")}</tbody></table></div>
    <p class="small">Stati possibili: ipotesi non verificabile, evidenza insufficiente, nessun vantaggio rilevato, risultato esplorativo promettente, candidato a verifica prospettica.
      Nessuno stato significa «validata» e nessuna strategia sperimentale cambia la classifica o dà indicazioni di acquisto o vendita.</p>
    <p class="muted small">Protocollo: <code>.venv/bin/python opportunity_strategies.py ipotesi</code> · report: <code>.venv/bin/python opportunity_strategies.py show</code> · registro: <code>.venv/bin/python opportunity_strategies.py registro</code></p>
    </details>`;
}
// phase O3: summary of the last historical study (opportunity_validation.py), kept apart from the diary above
function oppLabHTML() {
  const L = opps.lab;
  if (!L) return `<p class="muted small">Riepilogo non leggibile al momento (se in alto compare l'avviso del server vecchio, usa «Riavvia server»).</p>`;
  const D = L.diary, X = L.recheck, S = L.sim;
  const diary = `${oppStratHTML()}<h4 class="bt-h">3 · Diario prospettico (dal vivo, senza survivorship bias)</h4>
    <p class="small">${!D ? "Stato del diario non leggibile." : D.started ? `Registra dal ${esc(dayIT(D.first))}: ${D.days} ${D.days === 1 ? "giornata" : "giornate"}, ultima ${esc(dayIT(D.last))}.`
      : "Non ha ancora registrato sedute: la prima registrazione avviene dopo una chiusura di Wall Street, con la dashboard accesa o con il job serale (se installato)."}
      È l'unica verifica senza informazioni future e con i titoli scelti davvero ogni giorno; i risultati sono in «Monitoraggio risultati» e non si mescolano con lo studio storico.</p>`;
  if (!L.available) return `${oppReliabilityHTML(L.reliability)}<h4 class="bt-h">1 · Studio storico esplorativo</h4>
    <p class="small">Nessuno studio salvato. Si avvia a mano dal Terminale: <code>.venv/bin/python opportunity_validation.py run --scarica</code>. Il calcolo non avviene mai dentro la dashboard.</p>${diary}`;
  return `${oppReliabilityHTML(L.reliability)}
    <h4 class="bt-h">1 · Studio storico esplorativo (con survivorship bias)</h4>
    <p class="small"><b>${esc(L.label)}.</b> Le ${L.universe} azioni di oggi del Nasdaq-100 su tutto il periodo: mancano quelle uscite dall'indice,
      quindi i rendimenti sono spinti verso l'alto. Non è una validazione e non dice cosa comprare.</p>
    <p class="small">Giorni di segnale usati ${esc(dayIT(L.segments.tutto.from))} → ${esc(dayIT(L.segments.tutto.to))} (sviluppo e verifica; il periodo finale dal
      ${esc(dayIT(L.segments.finale.from))} ${L.finalOpened ? "è stato aperto" : "resta sigillato"}) · ${fNum(L.observations, 0)} osservazioni · studio del ${esc(oppTime(L.createdAt))} · laboratorio ${esc(L.version)}, modello ${esc(L.scannerModel)}</p>
    <div class="table-wrap"><table class="scr mini"><thead><tr><th class="l">Gruppo (orizzonte ${L.horizon} sedute)</th><th>Segnali</th>
      <th>Rispetto agli altri titoli dello stesso giorno (punti)</th><th>Rispetto a QQQ (punti)</th><th class="l">Giudizio a 5 · 10 · 21 sedute</th></tr></thead>
    <tbody>${L.rows.map(r => `<tr><td class="l">${esc(r.name)}</td><td>${fNum(r.n, 0)}</td><td>${ptPts(r.vsOthers)}</td><td>${ptPts(r.vsQqq)}</td>
      <td class="l small">${Object.values(r.verdicts).map(x => `<span title="${esc(x || "")}">${esc(oppVerdict(x))}</span>`).join(" · ")}</td></tr>`).join("")}</tbody></table></div>
    <p class="small">Rendimenti dalla chiusura del giorno del segnale (non ottenibili: il segnale si conosce dopo la chiusura); differenze medie di ogni giorno.
      Giudizio per orizzonte (passa sopra con il mouse per il testo intero). «Credibile» solo con abbastanza periodi indipendenti, |t| almeno 2, fuori dal 95% delle scelte a caso e confermato nel periodo di verifica.
      Battere QQQ di qualche decimo riesce a quasi tutti i gruppi, anche ai titoli deboli: viene dai sopravvissuti, non dalla selezione.</p>
    ${X ? `<p class="small"><b>Rielaborazione con dati verificati</b> (${esc(X.reviews)}, ${esc(oppTime(X.at))}): esclusi ${X.removed.map(r => `${esc(r.ticker)} dal ${esc(dayIT(r.from))} al ${esc(dayIT(r.to))}`).join(" e ")}
      (prezzi che non erano il titolo quotato regolarmente al Nasdaq). Studio originale ${X.reproducedOriginal ? "riprodotto identico" : "<b>non riprodotto</b>"};
      differenza massima ${fNum(X.maxAbsDiff, 2)} punti; giudizi cambiati: ${X.verdictsChanged}${X.changes.length ? ` (${X.changes.map(c => `${esc(c.name)} a ${c.h} sedute: ${esc(oppVerdict(c.verdict[1]))}`).join("; ")})` : ""}.
      I report originali restano invariati.</p>` : ""}
    ${S ? `<p class="small"><b>Simulazione sperimentale — non è una prova di redditività.</b> Con la regola 4 su 5 (ingresso all'apertura dopo, 21 sedute, massimo 10 titoli, costo ipotetico ${fNum(S.cost, 2)}% per lato)
      il totale è ${fPct(S.total, 0)}, ma una scelta <b>a caso</b> con le stesse regole fa ${fPct(S.randomMedian, 0)} (da ${fPct(S.randomP10, 0)} a ${fPct(S.randomP90, 0)}) e QQQ ${fPct(S.qqqTotal, 0)}:
      il risultato viene soprattutto dall'universo dei sopravvissuti e dalla volatilità, non dalle condizioni.</p>` : ""}
    ${diary}
    <details class="fold" data-k="lablim"><summary><span class="small">Limiti dello studio storico</span></summary><ul class="why bt-lim">${L.limits.map(l => `<li>${esc(l)}</li>`).join("")}</ul></details>
    <p class="muted small">Report completo: <code>.venv/bin/python opportunity_validation.py show</code>; qualità dei dati: <code>.venv/bin/python market_data_quality.py</code>. Non è una consulenza finanziaria.</p>`;
}
// ------------------------------------------------------------ Opportunità → Investimento: fundamental analysis (phase 5A)
// investment_engine.py: six separate dimensions and an analytic profile per company. Descriptions, never buy/sell
// signals; the Pagella ranking above is unchanged and only shown next to it for comparison.
const INV_DIMS = [["quality", "Qualità"], ["growth", "Crescita"], ["solidity", "Solidità"], ["valuation", "Valutazione"], ["expectations", "Aspettative"], ["trend", "Trend"]];
const INV_FILTERS = [
  ["all", "Tutte", () => true],
  ["qc", "Qualità e crescita", x => x.profile.id === "qualita_crescita"],
  ["care", "Solide ma care", x => ["qualita_cara", "buona_cara"].includes(x.profile.id)],
  ["risk", "Contenute con rischi", x => x.profile.id === "contenuta_rischi" || (x.dims.valuation.state === "Contenuta" && x.balance.neg > 0)],
  ["crit", "Con criticità", x => x.balance.neg > 0],
  ["nd", "Dati insufficienti o parziali", x => x.profile.id === "dati_insufficienti" || x.completeness.state !== "Completa"],
];
const INV_LIMITS = [
  ["Non è un segnale", "Il profilo descrive i bilanci e il prezzo di oggi. Non dice se il titolo salirà: nessuna regola del motore è stata provata sul passato, e non si può farlo con i bilanci di oggi senza barare (il diario salva i giudizi da ora in avanti)."],
  ["Fonte unica e gratuita", "Bilanci, calendario delle trimestrali, stime e capitalizzazioni vengono da Yahoo Finance: possono mancare, arrivare in ritardo di alcuni giorni dopo la trimestrale o essere riclassificati. Un dato mancante resta mancante, non diventa zero."],
  ["Data di fine e data di pubblicazione", "Un trimestre chiuso il 30 settembre è diventato pubblico solo all'annuncio dei risultati: la scheda mostra entrambe le date. Quando l'annuncio non è nel calendario della fonte la data di pubblicazione è «non verificabile»."],
  ["Confronti tra comparabili", "La valutazione è relativa: «Contenuta» vuol dire multipli più bassi del gruppo, non «sottovalutata». Gruppi con meno di 5 società non vengono confrontati."],
  ["Valute e ADR", "Per i bilanci in un'altra valuta (EUR, CNY) i multipli usano il cambio del giorno; il P/E atteso di questi titoli non è calcolato."],
  ["Ordine sperimentale", "L'ordine della tabella (completezza, poi giudizi positivi meno negativi su 5 dimensioni con lo stesso peso) è una scelta di lettura, non validata e non una probabilità."],
];
const invRank = (k, s) => { const D = opps.inv?.model?.dims?.find(d => d.id === k); const i = D ? D.states.indexOf(s) : -1; return i < 0 ? 99 : i; };
const invCls = p => p === 1 ? "acc" : p === -1 ? "red" : "";
const invBadge = (d, label) => d ? `<span class="act ${invCls(d.polarity)}" title="${esc(label)}${d.partial ? ": giudizio parziale" : ""}">${esc(d.state)}${d.partial ? "*" : ""}</span>` : "—";
async function loadInv() {
  if (opps.invLoading || (opps.inv && Date.now() - opps.invAt < 5 * 60_000)) return;
  opps.invLoading = true;
  try { opps.inv = await getJSON("/api/investment"); opps.invErr = null; opps.invAt = opps.inv.available ? Date.now() : Date.now() - 4 * 60_000; }
  catch (e) { opps.invErr = e.message; opps.invAt = Date.now() - 4 * 60_000; }
  opps.invLoading = false;
  renderOpps();
}
function invCardHTML() {
  const V = opps.inv;
  const head = `<div class="card-h"><h2>Analisi fondamentale</h2><span class="card-meta">motore ${esc(V?.model?.version || "")} · <b>sperimentale</b> · sei giudizi separati per società, non un voto</span></div>`;
  if (!V) return `<div class="card">${head}<div class="empty">${opps.invErr ? `Analisi non disponibile (${esc(opps.invErr)}).` : "Carico l'analisi fondamentale…"}</div></div>`;
  if (!V.available) return `<div class="card">${head}<div class="empty">Analisi non ancora disponibile: ${esc(V.reason)}.${V.fundamentals?.running ? " Download dei bilanci in corso." : ""} Riprova tra qualche minuto.</div></div>`;
  const f = INV_FILTERS.find(x => x[0] === opps.invFilter) || INV_FILTERS[0];
  const S = opps.invSort || { k: "order", dir: 1 };
  const key = {
    order: x => x.order, ticker: x => x.ticker, sector: x => x.sector || "", comp: x => -x.completeness.share,
    pag: x => -(x.pagella?.ok ?? -1), profile: x => x.profile.label,
    ...Object.fromEntries(INV_DIMS.map(([k]) => [k, x => invRank(k, x.dims[k].state)])),
  }[S.k] || (x => x.order);
  const rows = V.items.filter(f[2]).sort((a, b) => { const x = key(a), y = key(b); return (x < y ? -1 : x > y ? 1 : a.order - b.order) * S.dir; });
  const th = (k, l, cls = "") => `<th class="${cls}"><button class="link-btn inv-s" data-isort="${k}">${esc(l)}${S.k === k ? (S.dir > 0 ? " ▲" : " ▼") : ""}</button></th>`;
  const comp = c => `${esc(c.state)}<div class="muted small">${c.available} su ${c.applicable} dati</div>`;
  const pag = p => p ? `${p.ok} su ${p.n}${p.rank ? `<div class="muted small">${p.rank}° in classifica</div>` : ""}` : "non calcolata";
  const table = rows.length ? `<div class="table-wrap"><table class="scr opp-tbl inv-tbl"><thead><tr>${th("ticker", "Titolo", "l")}${th("sector", "Settore", "l")}<th>Prezzo</th>
      ${INV_DIMS.map(([k, l]) => th(k, l)).join("")}${th("profile", "Profilo e punti principali", "l")}${th("comp", "Completezza")}${th("pag", "Pagella")}</tr></thead>
    <tbody>${rows.map(x => `<tr data-t="${esc(x.ticker)}"><td class="l tk">${esc(x.ticker)}<div class="muted small">${esc(x.name)}</div></td>
      <td class="l">${esc(x.sector || "settore non indicato")}<div class="muted small">${esc(x.model.label)}</div></td>
      <td>${fPrice(x.price)} $<div class="muted small">chiusura ${x.priceDate ? esc(dayIT(x.priceDate)) : "non disponibile"}</div></td>
      ${INV_DIMS.map(([k, l]) => `<td>${invBadge(x.dims[k], l)}${x.dims[k].shift ? `<div class="muted small">${esc(x.dims[k].shift)}</div>` : ""}</td>`).join("")}
      <td class="l why-c"><b>${esc(x.profile.label)}</b><div class="small" title="${esc(x.mainStrength)}">+ ${esc(x.mainStrength)}</div><div class="small" title="${esc(x.mainWeakness)}">− ${esc(x.mainWeakness)}</div>
        ${x.lagging ? `<div class="muted small">risultati del ${esc(dayIT(x.lagging))} non ancora nei bilanci della fonte</div>` : ""}</td>
      <td>${comp(x.completeness)}</td><td>${pag(x.pagella)}</td></tr>`).join("")}</tbody></table></div>`
    : `<div class="empty">Nessuna società in questo gruppo oggi.</div>`;
  const M = V.model, dd = V.dataDates || {};
  const covLow = (V.coverage || []).filter(c => c.applicable && c.ok < c.applicable);
  const D = V.diary;
  return `<div class="card">${head}
    <p class="small">Per ogni società: <b>qualità</b> (redditività e cassa), <b>crescita</b>, <b>solidità</b> finanziaria, <b>valutazione</b> rispetto a società comparabili,
      <b>aspettative</b> degli analisti e <b>trend</b> del prezzo, giudicati separatamente. Verde = giudizio favorevole, rosso = critico, * = giudizio parziale.
      Il profilo è una descrizione, <b>non un'indicazione di acquisto o di vendita</b>. Clic su una riga per la scheda completa con indicatori, periodi e limiti.</p>
    <p class="muted small">Bilanci scaricati il ${dd.statements ? esc(oppTime(dd.statements)) : "data non disponibile"} · capitalizzazioni del ${dd.marketData ? esc(dayIT(dd.marketData)) : "giorno non disponibile"} · analisti del ${dd.analysts ? esc(dayIT(dd.analysts)) : "giorno non disponibile"} · calcolo delle ${esc(oppTime(V.generated))}</p>
    <div class="chips">${INV_FILTERS.map(([k, l, fn]) => `<button data-ifil="${k}" class="${k === f[0] ? "on" : ""}">${esc(l)}<span>${V.items.filter(fn).length}</span></button>`).join("")}</div>
    <p class="muted small">I gruppi sono modi di filtrare la tabella, <b>non strategie validate</b>: anche i casi negativi restano visibili.</p>
    ${table}
    <details class="fold" data-k="invrules"><summary><span class="small">Come funziona il motore (regole e soglie)</span></summary>
      <ul class="why">${M.params.map(p => `<li><b>${esc(p.name)}</b>: ${esc(p.text)}</li>`).join("")}</ul>
      <h4 class="bt-h">Profili, nell'ordine in cui vengono controllati</h4>
      <ul class="why">${M.profiles.map(p => `<li><b>${esc(p.label)}</b>: ${esc(p.rule)}</li>`).join("")}</ul>
      <h4 class="bt-h">Modelli per settore</h4>
      <ul class="why">${Object.values(M.models).map(m => `<li><b>${esc(m.label)}</b>: ${esc(m.note)}</li>`).join("")}</ul>
      <p class="small">Ordine iniziale della tabella (<b>sperimentale</b>): prima le analisi complete, poi il numero di giudizi favorevoli meno quelli critici
        su qualità, crescita, solidità, valutazione e aspettative, tutti con lo stesso peso. Il trend è mostrato a parte e non entra nell'ordine.</p></details>
    <details class="fold" data-k="invcov"><summary><span class="small">Copertura dei dati e gruppi di confronto</span></summary>
      ${covLow.length ? `<ul class="why">${covLow.map(c => `<li>${esc(c.label)}: disponibile per ${c.ok} società su ${c.applicable} a cui si applica</li>`).join("")}</ul>` : `<p class="small">Ogni indicatore è disponibile per tutte le società a cui si applica.</p>`}
      <p class="small"><b>Gruppi di confronto</b> (almeno 5 società con lo stesso modello): ${V.groups.map(g => `${esc(g.name)} (${esc(g.kind)}, ${g.size})`).join(" · ")}.</p>
      ${Object.keys(V.fx || {}).length ? `<p class="small"><b>Cambi usati</b> per i bilanci non in dollari: ${Object.entries(V.fx).map(([c, r]) => `1 ${esc(c)} = ${fNum(r.rate, 4)} USD (${esc(dayIT(r.date))})`).join(" · ")}.</p>` : ""}
      <p class="small"><b>Diario</b>: ${D?.started ? `giudizi salvati per ${D.days} ${D.days === 1 ? "seduta" : "sedute"} (dal ${esc(dayIT(D.first))})` : "nessun giudizio salvato finora: si registra solo nelle sedute già salvate dal diario delle opportunità"}.</p></details>
    <details class="fold" data-k="invlim"><summary><span class="small">Limiti dell'analisi</span></summary>
      <ul class="why bt-lim">${INV_LIMITS.map(([a, b]) => `<li><b>${esc(a)}.</b> ${esc(b)}</li>`).join("")}</ul></details>
  </div>`;
}
// detail drawer: "Analisi investimento" (loaded after the rest, so the other sections are not slowed down)
async function loadDetailInv(t) {
  const el = $("#dInv");
  if (!el) return;
  let X;
  try { X = await getJSON(`/api/investment/${encodeURIComponent(t)}`); }
  catch (e) { if (state.detail === t && $("#dInv")) $("#dInv").innerHTML = `<h3>Analisi investimento</h3><div class="muted small">Analisi fondamentale non disponibile per ora (i bilanci si scaricano in background).</div>`; return; }
  if (state.detail !== t || !$("#dInv")) return;
  $("#dInv").innerHTML = invDetailHTML(X);
}
function invPeriod(p) {
  if (!p) return "";
  if (!p.end) return esc(p.label);
  const pub = p.announced ? `risultati annunciati il ${dayIT(p.announced)}` : "data di pubblicazione non verificabile";
  const seen = p.firstSeen && !p.firstSeenInitial ? ` · nella fonte dal ${dayIT(p.firstSeen)}` : "";
  return `${esc(p.label)}<div class="muted small">${esc(pub)}${esc(seen)}</div>`;
}
function invDetailHTML(X) {
  const dimLab = Object.fromEntries(INV_DIMS);
  const li = a => a.length ? a.map(s => `<li>${esc(s)}</li>`).join("") : "<li>nessuno</li>";
  const ind = X.indicators.map(i => `<tr><td class="l">${esc(i.label)}</td>
      <td>${i.status === "ok" ? esc(i.text ?? fNum(i.value, 2)) : `<span class="muted">${esc(i.status)}</span>`}${i.note ? `<div class="muted small">${esc(i.note)}</div>` : ""}</td>
      <td class="l">${invPeriod(i.period)}</td><td class="l">${esc(i.source)}</td></tr>`).join("");
  const peer = X.peers?.length ? `<div class="table-wrap"><table class="scr mini"><thead><tr><th class="l">Multiplo</th><th>${esc(X.ticker)}</th><th>Mediana del gruppo</th><th>Società confrontate</th><th>Più cara del</th></tr></thead>
      <tbody>${X.peers.map(p => `<tr><td class="l">${esc(p.label)}</td><td>${p.key === "fcfYield" ? fNum(p.value, 1) + "%" : fNum(p.value, 1)}</td>
        <td>${p.key === "fcfYield" ? fNum(p.median, 1) + "%" : fNum(p.median, 1)}</td><td>${p.n} su ${p.groupSize}</td><td>${fNum(p.rich * 100, 0)}% del gruppo</td></tr>`).join("")}</tbody></table></div>`
    : `<p class="small">Nessun confronto: ${esc(X.dims.valuation.reasons[0] || "gruppo di società comparabili troppo piccolo")}.</p>`;
  const g = X.dims.valuation.group;
  const dims = INV_DIMS.map(([k, l]) => { const d = X.dims[k]; return `<li><b>${esc(l)}: ${esc(d.state)}${d.partial ? " (giudizio parziale)" : ""}</b>${d.shift ? ` · ${esc(d.shift)}` : ""}
      <ul>${d.reasons.map(r => `<li>${esc(r)}</li>`).join("")}</ul><div class="muted small">Regola: ${esc(d.rule)}</div></li>`; }).join("");
  const P = X.pagella;
  return `<h3>Analisi investimento <span class="muted small">motore ${esc(X.engineVersion)}, sperimentale · modello «${esc(X.model?.label || "")}»</span></h3>
    <p><b>${esc(X.profile.label)}.</b> ${esc(X.view)}</p>
    <div class="chip-row">${INV_DIMS.map(([k, l]) => `<span class="small">${esc(l)}</span> ${invBadge(X.dims[k], l)}`).join(" ")}</div>
    <p class="muted small">Completezza: ${esc(X.completeness.state)} (${X.completeness.available} indicatori su ${X.completeness.applicable})
      ${P ? ` · Pagella (classifica Investimento): ${P.ok} condizioni su ${P.n}` : ""}. Descrizione dei dati, non un'indicazione di acquisto o di vendita.</p>
    <details class="fold"><summary><span class="small">Punti di forza e di debolezza</span></summary>
      <div class="opp-cols"><div><h4>Punti di forza</h4><ul class="why">${li(X.strengths)}</ul></div><div><h4>Punti critici</h4><ul class="why">${li(X.weaknesses)}</ul></div></div></details>
    <details class="fold"><summary><span class="small">Perché questi giudizi</span></summary><ul class="why">${dims}</ul>
      <p class="muted small">Profilo «${esc(X.profile.label)}»: ${esc(X.profile.rule)}.</p></details>
    <details class="fold"><summary><span class="small">Indicatori, con periodo e data di pubblicazione</span></summary>
      <div class="table-wrap"><table class="scr mini"><thead><tr><th class="l">Indicatore</th><th>Valore</th><th class="l">Periodo</th><th class="l">Fonte</th></tr></thead><tbody>${ind}</tbody></table></div>
      <p class="muted small">Bilanci in ${esc(X.currency?.accounts || "valuta non indicata")}, prezzo in ${esc(X.currency?.price || "USD")}. «12 mesi» = somma degli ultimi 4 trimestri consecutivi.
        Dati: bilanci scaricati il ${X.dataDates?.statements ? esc(oppTime(X.dataDates.statements)) : "data non disponibile"}, prezzi fino al ${X.dataDates?.prices ? esc(dayIT(X.dataDates.prices)) : "giorno non disponibile"}.</p></details>
    <details class="fold"><summary><span class="small">Confronto con le società comparabili${g ? ` (${esc(g.name)}, ${g.size})` : ""}</span></summary>${peer}
      <p class="muted small">Multipli più bassi del gruppo non vogliono dire «sottovalutata»: possono riflettere più rischi o meno crescita.</p></details>
    <details class="fold"><summary><span class="small">Dati mancanti e limiti (${X.missing.length + X.limits.length + (X.dataIssues?.length || 0)})</span></summary>
      <ul class="why">${[...(X.dataIssues || []).map(esc), ...X.limits.map(esc), ...X.missing.map(m => `${esc(m.label)}: ${esc(m.status)}${m.note ? ` (${esc(m.note)})` : ""}`)].map(s => `<li>${s}</li>`).join("") || "<li>nessuno</li>"}</ul></details>
    <details class="fold"><summary><span class="small">Da monitorare</span></summary><ul class="why">${li(X.monitor)}</ul>
      ${X.nextEarnings ? `<p class="small">Prossima trimestrale: ${esc(dayIT(String(X.nextEarnings).slice(0, 10)))}.</p>` : ""}</details>`;
}
// ------------------------------------------------------------ Valutazione e scenari (phase 5B, experimental)
// investment_valuation.py: DCF (FCFF) with three scenarios, implied expectations and sensitivity, next to the phase 5A
// analysis. Ranges conditional on explicit assumptions: never a target price, a buy/sell signal or a probability.
const VAL_FILTERS = [["all", "Tutte"], ["qualita_approfondire", "Qualità, prezzo da approfondire"], ["qualita_impegnativa", "Qualità, valutazione impegnativa"],
  ["incerta", "Elevata incertezza"], ["nessuna_stima", "Nessuna stima affidabile"], ["altre", "Altre valutate"]];
const VAL_LIMITS = [
  ["Ipotesi, non previsioni", "Ogni valore dipende dalle ipotesi mostrate (crescita, margini, reinvestimenti, tasso di sconto). Cambiando le ipotesi cambia il valore: per questo ci sono tre scenari e la tabella di sensibilità. Nessuno scenario ha una probabilità."],
  ["Non è un prezzo obiettivo", "I 5 anni sono la durata della previsione esplicita, non un orizzonte di prezzo. Il valore per azione è arrotondato apposta: le cifre in più sarebbero una precisione falsa."],
  ["Parametri severi rispetto al mercato", "Con il tasso privo di rischio di oggi, un premio per il rischio del 4,5%, 5 anni di crescita esplicita e una crescita terminale del 2,5%, molti prezzi risultano sopra anche lo scenario favorevole. La verifica della Fase 5C ha escluso errori di calcolo come causa: il prezzo è compatibile con tassi di sconto più bassi o con una crescita che dura più di 5 anni. Il modello non dice quale delle due cose sia giusta, né che il mercato sbagli."],
  ["Leasing e investimenti", "La fonte non separa i leasing operativi (il cui costo è già nel margine) da quelli finanziari: restano tutti nel debito, una scelta prudente; quando pesano molto la scheda lo dice. Gli investimenti finanziari a lungo termine sono aggiunti al valore di bilancio, non di mercato."],
  ["Date dei dati", "Gli anni previsti partono dalla fine degli ultimi dati completi (12 mesi o esercizio) e sono scontati fino a oggi. Se la fonte pubblica un periodo incompleto si usano i periodi completi precedenti."],
  ["Valore terminale", "Con 5 anni espliciti gran parte del valore viene dagli anni successivi: la scheda mostra quanto pesa e la valutazione è «molto sensibile» quando supera l'85%."],
  ["Società escluse", "Banche, assicurazioni, società di pagamento e utility non hanno un DCF industriale; nemmeno le società con utile operativo negativo o margini molto instabili: «non valutabile» è un risultato, non un errore."],
  ["Compensi in azioni", "L'utile operativo GAAP sottrae già i compensi in azioni: il modello non li toglie una seconda volta e usa le azioni diluite di oggi. Il flusso di cassa «economico» (cassa libera − compensi in azioni) è una misura rettificata di questa dashboard, non una grandezza contabile standard."],
  ["Valute", "Bilanci in EUR o CNY convertiti al cambio del giorno (fonte e data indicate), lo stesso per tutti gli anni; il rischio paese non è nel tasso di sconto."],
  ["Nessuna verifica storica", "I gruppi sono categorie di lettura, non una classifica predittiva: il diario salva le valutazioni da ora in avanti per verificarle più avanti."],
];
const valNum = v => isNum(v) ? fNum(v, Math.abs(v) < 10 ? 1 : 0) : "non calcolabile";
const valPct = (v, d = 0) => isNum(v) ? fPct(v * 100, d) : "non calcolabile";
const valPlain = (v, d = 0) => isNum(v) ? fNum(v * 100, d) + "%" : "non calcolabile";
const vscCls = s => s === "adeguata" ? "acc" : s === "parziale" ? "" : s === "sensibile" ? "warn" : "red";
const vscBadge = (s, l) => `<span class="act ${vscCls(s)}">${esc(l)}</span>`;
async function loadVal() {
  if (opps.valLoading || (opps.val && Date.now() - opps.valAt < 5 * 60_000)) return;
  opps.valLoading = true;
  try { opps.val = await getJSON("/api/valuation"); opps.valErr = null; opps.valAt = opps.val.available ? Date.now() : Date.now() - 4 * 60_000; }
  catch (e) { opps.valErr = e.message; opps.valAt = Date.now() - 4 * 60_000; }
  opps.valLoading = false;
  renderOpps();
}
// range bar: prudent → favourable shaded, base tick, price marker; values ≤ 0 are drawn at the left edge and said in words
function valBar(v, price, big = false) {
  if (!v || !isNum(v.base)) return "";
  const pts = [v.prudente, v.base, v.favorevole, price].filter(isNum);
  const hi = Math.max(...pts) * 1.08, lo = Math.max(0, Math.min(...pts) * 0.85);
  const x = n => `${Math.max(0, Math.min(100, (n - lo) / (hi - lo) * 100)).toFixed(1)}%`;
  const a = Math.min(v.prudente, v.favorevole), b = Math.max(v.prudente, v.favorevole);
  return `<div class="vbar${big ? " big" : ""}" role="img" aria-label="Scenari da ${valNum(v.prudente)} a ${valNum(v.favorevole)} USD, base ${valNum(v.base)}, prezzo ${valNum(price)}">
    <i class="rng" style="left:${x(a)};width:calc(${x(b)} - ${x(a)})"></i><i class="tick" style="left:${x(v.base)}"></i>${isNum(price) ? `<i class="px" style="left:${x(price)}"></i>` : ""}
    ${big ? `<span class="lb" style="left:${x(a)}">prudente ${valNum(v.prudente)}</span><span class="lb mid" style="left:${x(v.base)}">base ${valNum(v.base)}</span><span class="lb end" style="left:${x(b)}">favorevole ${valNum(v.favorevole)}</span>` : ""}</div>`;
}
function valPriceLine(p) {
  if (!p || !isNum(p.value)) return "prezzo non disponibile";
  return `${fPrice(p.value)} $<div class="muted small">${p.kind === "quotazione" ? `quotazione ${p.time ? esc(oppTime(p.time)) : "ora non disponibile"}` : `chiusura ${p.date ? esc(dayIT(p.date)) : "giorno non disponibile"}`}</div>`;
}
function valCardHTML() {
  const V = opps.val;
  const head = `<div class="card-h"><h2>Valutazione e scenari</h2><span class="card-meta">modello ${esc(V?.model?.version || "")} · <b>sperimentale</b> · intervalli condizionati alle ipotesi, non prezzi obiettivo</span></div>`;
  if (!V) return `<div class="card">${head}<div class="empty">${opps.valErr ? `Valutazione non disponibile (${esc(opps.valErr)}).` : "Carico le valutazioni…"}</div></div>`;
  if (!V.available) return `<div class="card">${head}<div class="empty">Valutazione non ancora disponibile: ${esc(V.reason)}. Riprova tra qualche minuto.</div></div>`;
  const f = opps.valFilter || "all";
  const rows = V.items.filter(x => f === "all" || x.group === f);
  const G = Object.fromEntries(V.model.groups.map(g => [g.id, g]));
  const rf = V.rates?.rf;
  const implied = x => isNum(x.impliedGrowth) ? `${fPct(x.impliedGrowth * 100, 0)} il 1° anno<div class="muted small">ipotesi base ${valPct(x.baseGrowth)}</div>` : `<span class="muted small">${x.values ? "non univoca o fuori intervallo" : "—"}</span>`;
  const table = rows.length ? `<div class="table-wrap"><table class="scr opp-tbl val-tbl"><thead><tr><th class="l">Titolo</th><th class="l">Profilo (Fase 5A)</th><th>Prezzo</th>
      <th class="l">Scenari per azione (USD)</th><th class="l">Dove sta il prezzo</th><th>Crescita implicita nel prezzo</th><th class="l">Affidabilità</th></tr></thead>
    <tbody>${rows.map(x => `<tr data-t="${esc(x.ticker)}"><td class="l tk">${esc(x.ticker)}<div class="muted small">${esc(x.name)}</div></td>
      <td class="l">${esc(x.fundamental.profile.label)}<div class="muted small">qualità ${esc(x.fundamental.quality.toLowerCase())}</div></td>
      <td>${valPriceLine(x.price)}</td>
      <td class="l">${x.values ? `${valBar(x.values, x.price?.value)}<div class="small">${x.display.map(valNum).join(" · ")}</div>` : `<span class="muted small">nessuno scenario</span>`}</td>
      <td class="l">${x.position ? esc(x.position.label) : `<span class="muted small">${esc(x.reason || "")}</span>`}</td>
      <td>${implied(x)}</td>
      <td class="l">${vscBadge(x.status, x.statusLabel)}${x.status !== "adeguata" && x.values && x.reason ? `<div class="muted small" title="${esc(x.reason)}">${esc(x.reason)}</div>` : ""}</td></tr>`).join("")}</tbody></table></div>`
    : `<div class="empty">Nessuna società in questo gruppo oggi.</div>`;
  const D = V.diary, C = V.counts || {};
  const computed = (C.status?.adeguata || 0) + (C.status?.parziale || 0) + (C.status?.sensibile || 0);
  return `<div class="card">${head}
    <p class="small">Per le società con dati e modello adatti: valore per azione in <b>tre scenari</b> (prudente, base, favorevole) da un flusso di cassa scontato, confrontato con il prezzo.
      Barra: tratto colorato = da prudente a favorevole, linea = scenario base, punto = prezzo. <b>Non è un prezzo obiettivo né un'indicazione di acquisto o di vendita.</b>
      Clic su una riga per ipotesi, sensibilità e limiti.</p>
    ${V.model.disclaimer ? `<p class="warn-box small">${esc(V.model.disclaimer)}</p>` : ""}
    <p class="muted small">Valutate ${computed} società su ${V.items.length} · Treasury a 10 anni ${rf ? `${valPlain(rf.rate, 2)} (${esc(dayIT(rf.date))})` : "non disponibile"}
      ${Object.keys(V.fx || {}).length ? ` · cambi: ${Object.entries(V.fx).map(([c, r]) => `1 ${esc(c)} = ${fNum(r.rate, 4)} USD (${esc(dayIT(r.date))})`).join(", ")}` : ""} · calcolo delle ${esc(oppTime(V.generated))}</p>
    <div class="chips">${VAL_FILTERS.map(([k, l]) => `<button data-vfil="${k}" class="${k === f ? "on" : ""}" title="${esc(G[k]?.rule || "tutte le società")}">${esc(l)}<span>${k === "all" ? V.items.length : (C.group?.[k] || 0)}</span></button>`).join("")}</div>
    <p class="muted small">${f === "all" ? "I gruppi sono categorie di lettura, <b>non una classifica predittiva validata</b>; la Pagella e la classifica sopra non cambiano." : `<b>${esc(G[f]?.label || "")}</b>: ${esc(G[f]?.rule || "")}. Categoria di lettura, non una classifica predittiva.`}</p>
    ${table}
    <details class="fold" data-k="valrules"><summary><span class="small">Metodo e parametri</span></summary>
      <ul class="why">${V.model.params.map(p => `<li><b>${esc(p.name)}</b>: ${esc(p.text)}</li>`).join("")}</ul>
      <h4 class="bt-h">Stati di affidabilità</h4><ul class="why">${Object.entries(V.model.statuses).map(([k, l]) => `<li>${vscBadge(k, l)}</li>`).join("")}</ul>
      <p class="muted small">Gli stati descrivono dati e metodo: <b>non sono probabilità</b> che la stima sia giusta.</p>
      ${V.model.corrections ? `<h4 class="bt-h">Modello ${esc(V.model.version)} rispetto a ${esc(V.model.previous)} (verifica della Fase 5C)</h4><ul class="why">${V.model.corrections.map(c => `<li><b>${esc(c.kind)}</b>: ${esc(c.text)}</li>`).join("")}</ul>
      <p class="muted small">Le valutazioni registrate con ${esc(V.model.previous)} restano com'erano: ogni versione è salvata a parte.</p>` : ""}</details>
    <details class="fold" data-k="vallim"><summary><span class="small">Limiti della valutazione</span></summary>
      <ul class="why bt-lim">${VAL_LIMITS.map(([a, b]) => `<li><b>${esc(a)}.</b> ${esc(b)}</li>`).join("")}</ul>
      <p class="small"><b>Diario</b>: ${D?.started ? `valutazioni salvate per ${D.days} ${D.days === 1 ? "seduta" : "sedute"} (dal ${esc(dayIT(D.first))})` : "nessuna valutazione salvata finora: si registra solo dopo la chiusura, nelle sedute già salvate dal diario delle opportunità"}.</p></details>
  </div>`;
}
async function loadDetailVal(t) {
  if (!$("#dVal")) return;
  let X;
  try { X = await getJSON(`/api/valuation/${encodeURIComponent(t)}`); }
  catch (e) { if (state.detail === t && $("#dVal")) $("#dVal").innerHTML = `<h3>Valutazione e scenari</h3><div class="muted small">Valutazione non disponibile per ora (serve l'analisi fondamentale, che si calcola dai bilanci scaricati in background).</div>`; return; }
  if (state.detail !== t || !$("#dVal")) return;
  $("#dVal").innerHTML = valDetailHTML(X);
}
function valDetailHTML(X) {
  const li = a => (a || []).length ? a.map(s => `<li>${esc(s)}</li>`).join("") : "<li>nessuno</li>";
  const F = X.fundamental;
  const head = `<h3>Valutazione e scenari <span class="muted small">modello ${esc(X.modelVersion)}, sperimentale</span></h3>
    <p class="small">Prezzo ${valPriceLine(X.price).replace("<div", " <span").replace("</div>", "</span>")} · profilo fondamentale (Fase 5A): <b>${esc(F.profile.label)}</b>, qualità ${esc(F.quality.toLowerCase())}, solidità ${esc(F.solidity.toLowerCase())}.</p>`;
  if (!X.scenarios) return `${head}<p>${vscBadge(X.status, X.statusLabel)}</p><ul class="why">${li(X.reasons)}</ul>
    ${X.disclaimer ? `<p class="muted small">${esc(X.disclaimer)}</p>` : ""}
    <p class="muted small">Nessuno scenario: mostrare un valore qui sarebbe una stima senza basi sufficienti.</p>
    <details class="fold"><summary><span class="small">Rischi e condizioni da monitorare</span></summary><h4>Rischi</h4><ul class="why">${li(X.risks)}</ul><h4>Da monitorare</h4><ul class="why">${li(X.monitor)}</ul></details>`;
  const S = X.scenarios, K = [["prudente", "Prudente"], ["base", "Base"], ["favorevole", "Favorevole"]];
  const I = X.inputs, d = I.discount, R = X.reverse || {};
  const vals = Object.fromEntries(K.map(([k], i) => [k, X.range.display[i]]));      // rounded, as in the table
  const row = (lab, fn, note = "") => `<tr><td class="l">${esc(lab)}${note ? `<div class="muted small">${esc(note)}</div>` : ""}</td>${K.map(([k]) => `<td>${fn(S[k], S[k].assumptions)}</td>`).join("")}</tr>`;
  const scTable = `<div class="table-wrap"><table class="scr mini val-sc"><thead><tr><th class="l">Ipotesi e risultato</th>${K.map(([, l]) => `<th>${l}</th>`).join("")}</tr></thead><tbody>
    ${row("Crescita dei ricavi, 1° anno", (s, a) => valPct(a.g1), "poi in calo lineare fino alla crescita terminale")}
    ${row("Ricavi dopo 5 anni", s => `${fNum(s.revMultiple, 1)} volte oggi`)}
    ${row("Margine operativo", (s, a) => `${valPlain(a.m0, 1)} → ${valPlain(a.mT, 1)}`, "oggi → a regime (in 5 anni)")}
    ${row("Tasse", (s, a) => valPlain(a.tax, 0))}
    ${row("Ricavi per ogni dollaro investito", (s, a) => fNum(a.s2c, 2), "più alto = serve meno capitale per crescere")}
    ${row("Reinvestimenti in 5 anni", s => isNum(s.reinvestShare) ? `${valPlain(s.reinvestShare, 0)} dell'utile operativo netto` : "non calcolabile")}
    ${row("Rendimento del capitale a regime", (s, a) => valPlain(a.roicT, 1))}
    ${row("Tasso di sconto (WACC)", (s, a) => valPlain(a.wacc, 1), "uguale nei tre scenari")}
    ${row("Crescita terminale", (s, a) => valPlain(a.gT, 1))}
    ${row("Peso del valore terminale", s => valPlain(s.tvShare, 0))}
    ${row("Valore per azione (arrotondato)", s => `<b>${valNum(Number(X.range.display[K.findIndex(([k]) => k === s.kind)]))} $</b>`)}
    ${row("Prezzo rispetto al valore", s => isNum(s.priceVsValue) ? `${fPct(s.priceVsValue * 100, 0)}` : "non calcolabile", "+ = prezzo sopra il valore dello scenario")}
    </tbody></table></div>`;
  const sens = `<div class="table-wrap"><table class="scr mini"><thead><tr><th class="l">Ipotesi dello scenario base</th><th>Più bassa</th><th>Più alta</th></tr></thead><tbody>
    ${X.sensitivity.map(r => `<tr><td class="l">${esc(r.label)} (${r.key === "gT" ? "±0,5" : r.key === "g1" ? "±5" : r.key === "mT" ? "±2" : "±1"} punti)</td>${r.cells.map(c => `<td>${isNum(c.change) ? fPct(c.change * 100, 0) : `<span class="muted small">${esc(c.invalid || "non calcolabile")}</span>`}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
  const rev = `<ul class="why">
    <li>${isNum(R.growth) ? `Con i margini dello scenario base, il prezzo corrisponde a ricavi in crescita del <b>${fPct(R.growth * 100, 0)}</b> il primo anno (poi in calo fino al 2,5%), cioè ${fNum(R.growthRevMultiple, 1)} volte i ricavi di oggi in 5 anni. Lo scenario base ipotizza ${valPct(I.g1)}.` : `Crescita implicita: ${esc(R.growthNote || "non calcolabile")}.`}</li>
    <li>${isNum(R.margin) ? `Con la crescita dello scenario base, il prezzo corrisponde a un margine operativo a regime del <b>${valPlain(R.margin, 0)}</b> (oggi ${valPlain(I.m0, 1)}).` : `Margine implicito: ${esc(R.marginNote || "non calcolabile")}.`}</li>
    <li>${isNum(R.wacc) ? `Con crescita e margini dello scenario base, il prezzo corrisponde a un tasso di sconto del <b>${valPlain(R.wacc, 1)}</b> (modello ${valPlain(d.wacc, 1)}).` : `Tasso di sconto implicito: ${esc(R.waccNote || "non calcolabile")}.`}</li></ul>
    ${R.combinations?.length ? `<p class="small"><b>Combinazioni che danno lo stesso prezzo</b> (${esc(R.identification)}):</p><ul class="why">${R.combinations.map(c => `<li>${esc(c.text)}</li>`).join("")}</ul>` : ""}
    <p class="muted small">Non è una previsione: dice quali risultati il prezzo di oggi sembra già incorporare, con il tasso di sconto del modello.</p>`;
  const lv = X.levels?.length ? `<ul class="why">${X.levels.map(l => `<li>${esc(l.text)}</li>`).join("")}</ul>`
    : `<p class="small">${["adeguata", "parziale"].includes(X.status) ? "Il prezzo è già sotto il valore dello scenario base." : "Non mostrati: con una valutazione molto sensibile alle ipotesi un livello di prezzo darebbe una precisione che la stima non ha."}</p>`;
  const B = I.bridge, C = I.cash || {}, H = I.fcffHist;
  const big = v => isNum(v) ? fBig(v) + " $" : "non disponibile";
  const wacc = `<ul class="why">
    <li>Costo del capitale proprio ${valPlain(d.ke, 1)} = Treasury 10 anni ${valPlain(d.rf, 2)} (${esc(dayIT(d.rfDate))}) + beta ${fNum(d.beta, 2)}${isNum(d.betaRaw) ? ` (Yahoo ${fNum(d.betaRaw, 2)}, corretto verso 1)` : " (non disponibile)"} × premio ${valPlain(d.erp, 1)}</li>
    <li>Costo del debito ${valPlain(d.kd, 1)} prima delle tasse (${esc(d.kdSrc)}), peso del debito ${valPlain(d.wd, 0)} → WACC ${valPlain(d.wacc, 1)}</li>
    ${I.timing ? `<li>Date: ${esc(I.timing.text)}.</li>` : ""}
    <li>Dal valore dell'impresa a quello delle azioni (scenario base): ${big(S.base.ev)} + liquidità ${big(B.cash)}${B.investments ? ` + investimenti a lungo termine ${big(B.investments)}` : ""} − debito con leasing ${big(B.debt)}${isNum(B.leases) ? ` (di cui leasing ${big(B.leases)})` : ""}${B.minority ? ` − minoranze ${big(B.minority)}` : ""}${B.preferred ? ` − privilegiate ${big(B.preferred)}` : ""} = ${big(S.base.equity)}, diviso ${fBig(I.shares)} azioni diluite${I.adr && I.adr > 1 ? ` (1 titolo quotato = ${I.adr} azioni ordinarie)` : ""}</li>
    <li>Rapporto ricavi/capitale: ${esc(I.s2cSrc)}. Tasse: ${esc(I.taxSrc)}.</li>
    <li>Cassa: flusso di cassa libero contabile ${big(C.fcf)}; compensi in azioni ${big(C.sbc)}${isNum(C.sbcShare) ? ` (${valPlain(C.sbcShare, 1)} dei ricavi)` : ""}; flusso «economico» (cassa libera − compensi in azioni, misura rettificata non standard) ${big(C.fcfEconomic)}. Il DCF parte dall'utile operativo, che i compensi li ha già sottratti: non sono tolti due volte.</li>
    ${I.dilution ? `<li>Azioni diluite: ${fPct(I.dilution.perYear * 100, 1)} l'anno dal ${esc(dayIT(I.dilution.from))} al ${esc(dayIT(I.dilution.to))} (${I.dilution.perYear < 0 ? "riacquisti" : "diluizione"}); non entra nel valore per non contarla due volte.</li>` : ""}
    ${H ? `<li>Flusso di cassa per tutti i finanziatori negli ultimi dati: dall'utile operativo ${big(H.fromEbit)}${H.wcMissing ? " (capitale circolante non disponibile)" : ""}; dal flusso di cassa operativo, meno i compensi in azioni ${big(H.fromOcf)}. Primo anno del modello (scenario base): ${big(X.limits?.year1Fcff)}.</li>` : ""}
    ${X.limits?.clamps?.length ? X.limits.clamps.map(c => `<li>Limite attivo: ${esc(c.text)}${isNum(c.change) ? `; senza il limite il valore base cambierebbe del ${fPct(c.change * 100, 0)}` : ""}.</li>`).join("") : ""}
    ${I.fx ? `<li>Cambio ${esc(I.fx.currency)}/USD ${fNum(I.fx.rate, 4)} del ${esc(dayIT(I.fx.date))} (${esc(I.fx.source)}), applicato a tutti gli anni.</li>` : ""}</ul>`;
  return `${head}
    <p>${vscBadge(X.status, X.statusLabel)} ${X.position ? `<b>${esc(X.position.label)}</b>` : ""}</p>
    ${valBar(vals, X.price?.value, true)}
    ${X.disclaimer ? `<p class="muted small">${esc(X.disclaimer)}</p>` : ""}
    <div class="table-wrap"><table class="scr mini val-q"><tbody>
      <tr><td class="l">Qualità fondamentale (Fase 5A)</td><td class="l">${esc(F.quality)} · crescita ${esc((F.growth || "").toLowerCase())}</td></tr>
      <tr><td class="l">Prezzo e valutazione</td><td class="l">${X.position ? esc(X.position.label) : "—"}</td></tr>
      <tr><td class="l">Rischio</td><td class="l">solidità ${esc(F.solidity.toLowerCase())}${X.blockers?.length ? ` · ${X.blockers.length} ${X.blockers.length === 1 ? "criticità" : "criticità"} nella stima` : ""}</td></tr>
      <tr><td class="l">Affidabilità di dati e metodo</td><td class="l">${esc(X.statusLabel)}</td></tr>
      <tr><td class="l">Capacità predittiva</td><td class="l">non ancora dimostrata: si potrà misurare solo con il diario, nei prossimi mesi</td></tr>
    </tbody></table></div>
    <p class="small">${esc(X.summary)}</p>
    ${X.reasons?.length ? `<ul class="why small">${li(X.reasons)}</ul>` : ""}
    <details class="fold" open><summary><span class="small">Tre scenari: ipotesi e risultati</span></summary>${scTable}
      <ul class="why">${K.map(([k, l]) => `<li><b>${l}</b>: plausibile ${esc(S[k].text.plausible)}; poco plausibile ${esc(S[k].text.implausible)}.</li>`).join("")}</ul>
      <p class="muted small">Nessuna probabilità è assegnata agli scenari e non c'è un «valore atteso»: sono condizioni, non previsioni.</p></details>
    <details class="fold"><summary><span class="small">Cosa incorpora il prezzo (calcolo inverso)</span></summary>${rev}</details>
    <details class="fold"><summary><span class="small">Sensibilità del valore base</span></summary>${sens}
      <p class="muted small">Variazione del valore per azione dello scenario base quando cambia una sola ipotesi.</p>
      ${X.limits?.horizon ? `<p class="small">Durata della crescita: nello scenario base i ricavi crescono ancora del ${valPct(X.limits.horizon.growthYear5, 1)} nel 5° anno, poi il 2,5%. ${esc(X.limits.horizon.text)}.</p>` : ""}</details>
    <details class="fold"><summary><span class="small">Livelli di prezzo per una nuova analisi</span></summary>${lv}
      <p class="muted small">Condizioni di valutazione, non ordini né prezzi di esecuzione; non tengono conto del momento di mercato.</p></details>
    <details class="fold"><summary><span class="small">Rischi principali e condizioni da monitorare</span></summary>
      <div class="opp-cols"><div><h4>Rischi</h4><ul class="why">${li(X.risks)}</ul></div><div><h4>Da monitorare</h4><ul class="why">${li(X.monitor)}</ul></div></div></details>
    <details class="fold"><summary><span class="small">Tasso di sconto, valore delle azioni e cassa</span></summary>${wacc}</details>
    <details class="fold"><summary><span class="small">Dati usati e dati mancanti</span></summary>
      <h4>Usati</h4><ul class="why">${li(X.dataUsed)}</ul><h4>Mancanti, stimati o limitati</h4><ul class="why">${li([...(X.dataMissing || []), ...(X.notes || [])])}</ul>
      <p class="muted small">Bilanci scaricati il ${X.dataDates?.statements ? esc(oppTime(X.dataDates.statements)) : "data non disponibile"} · calcolo delle ${esc(oppTime(X.generated))}. Non è una consulenza finanziaria.</p></details>`;
}
// ------------------------------------------------------------ Decision Desk (phase 7A, investment_decision_engine.py)
// Reads the results of the existing engines (T1–T5, Pagella, F1, V2, ETF E2) and shows a transparent state for every
// stock and ETF exposure, per horizon. Never a score, a probability, a buy/sell call or an entry price.
const DK = { h: LS.get("dk.h", "lungo"), k: LS.get("dk.k", "all"), data: null, at: 0, err: null, loading: false, open: null, det: {}, detErr: null };
const DK_ST = { "Da approfondire": "ok", "Attendi condizioni migliori": "wait", "Monitora": "mon", "Monitora — trend esplorativo": "mon", "Condizioni contrastanti": "mix",
  "Rischio elevato": "risk", "Dati insufficienti": "na", "Nessuna opportunità convincente": "none" };
// phase 8B.1: what "Monitora" means, written from RULES of investment_decision_engine.py (rules unchanged)
const MONITOR_HELP = `<b>«Monitora» è uno stato del Decision Desk</b>, ricalcolato a ogni analisi dai motori esistenti con regole fisse:<br>
  · <b>Azioni, medio-lungo (A-M1)</b>: evidenze favorevoli senza contrarie, ma insufficienti per «Da approfondire» (DCF non calcolabile, dimensioni parziali).<br>
  · <b>Azioni, breve (B-M1)</b>: almeno 4 condizioni Trading su 5 senza avvisi. È lo stato massimo nel breve: le regole T1–T5 non hanno mostrato vantaggi nei test.<br>
  · <b>ETF, medio-lungo (E-M1, E-M2)</b>: stato del modello ETF «Trend favorevole da monitorare», oppure esposizione «da approfondire» con date non allineate o dati del fondo datati.<br>
  · <b>ETF, breve (F-M1)</b>: stato del modello ETF nel breve favorevole; è lo stato massimo nel breve.<br>
  · <b>«Monitora — trend esplorativo» (E-M3)</b>: i casi in cui l'esposizione soddisfa le condizioni di trend del modello ETF; il trend da solo non basta per «Da approfondire» perché non è validato come criterio predittivo.<br><br>
  <b>Non è un suggerimento di acquisto</b>: nessuna regola è validata sul passato, non ci sono rendimenti attesi né probabilità. Vuol dire solo «situazione da ricontrollare più avanti».<br><br>
  <b>Non sono i tuoi Preferiti</b>: i Preferiti (★) sono una lista che scegli tu; un titolo «Monitora» non viene aggiunto ai Preferiti e un Preferito non cambia stato.`;
const E2_MON_HELP = `<b>«Trend favorevole da monitorare»</b> è uno stato del modello ETF: almeno 2 condizioni favorevoli soddisfatte e nessuna contraria,
  ma non tutte le favorevoli (con tutte e nessuna contraria lo stato sarebbe «Esposizione da approfondire»). Una condizione non valutabile non conta mai come soddisfatta.<br><br>
  <b>Non è un suggerimento di acquisto</b>: le regole di trend e momentum sulle categorie di ETF non hanno superato il test (Fase 24). Non riguarda i tuoi Preferiti.`;
const EXPOSURES_HELP = `Quante esposizioni (mercati, settori, temi, obbligazioni) lo scanner ETF esamina a ogni analisi. «Monitorate» vuol dire «esaminate dallo scanner»:
  non è una lista di acquisti, non dipende dal tuo portafoglio e non è la lista dei tuoi Preferiti.`;
const dkSt = s => `<span class="eo-st eo-${DK_ST[s] || "none"}">${esc(s)}</span>${/^Monitora/.test(s) ? " " + info(MONITOR_HELP) : ""}`;
const DK_Q = { completa: "completi", parziale: "parziali", insufficiente: "insufficienti" };
async function loadDesk(force) {
  if (DK.loading || (DK.data && !force && Date.now() - DK.at < 5 * 60_000)) return;
  DK.loading = true;
  try {
    const r = await fetch("/api/decisions", { cache: "no-store" });
    if (r.status === 503) DK.err = "loading";
    else { const j = await r.json(); if (r.ok) { DK.data = j; DK.at = Date.now(); DK.err = null; DK.det = {}; } else DK.err = j.error || r.statusText; }
  } catch { DK.err = "server non raggiungibile"; }
  DK.loading = false;
  if (state.view === "opps" && opps.mode === "desk") renderOpps();
}
async function loadDeskDetail(id) {
  DK.open = id; DK.detErr = null;
  if (!DK.det[id]) {
    renderOpps();
    try { const r = await fetch("/api/decisions/" + encodeURIComponent(id)); const j = await r.json(); if (r.ok) DK.det[id] = j; else DK.detErr = j.error; }
    catch { DK.detErr = "server non raggiungibile"; }
  }
  renderOpps();
  document.getElementById("dkDetail")?.scrollIntoView({ behavior: "smooth", block: "start" });
}
function dkRows(D) {
  return D.rows.filter(r => r.horizon === DK.h && (DK.k === "all" || r.kind === DK.k));
}
function dkTable(rows) {
  return `<div class="table-wrap"><table class="scr dk-tbl"><thead><tr><th class="l">Nome</th><th class="l">Stato</th><th class="l">Motivo principale</th>
    <th class="l p3">Rischio principale</th><th class="l">Dati</th><th>Ultima data</th></tr></thead><tbody>${rows.map(r => `<tr data-dkopen="${esc(r.id)}" class="${DK.open === r.id ? "sel" : ""}">
      <td class="l"><b>${esc(r.name)}</b><br><span class="cat-src">${esc(r.kind === "azione" ? r.code : (r.family || "ETF") + (r.code ? " · " + r.code : ""))} · ${r.horizon === "breve" ? "breve" : "medio-lungo"}</span></td>
      <td class="l">${dkSt(r.state)}</td><td class="l small">${esc(r.main)}</td><td class="l p3 small">${esc(r.mainRisk)}</td>
      <td class="l small">${esc(DK_Q[r.dataQuality] || r.dataQuality)}</td><td class="small">${r.lastDate ? esc(dayIT(r.lastDate)) : "n.d."}</td></tr>`).join("")}</tbody></table></div>`;
}
function dkSection(title, rows, sub, open, k) {
  if (!rows.length) return "";
  return `<div class="card"><details class="fold" data-k="${k}" ${open ? "open" : ""}><summary><h3>${title}</h3><span class="card-meta">${rows.length} · ${esc(sub)}</span></summary>${dkTable(rows)}</details></div>`;
}
function dkDetailHTML() {
  if (!DK.open) return "";
  const o = DK.det[DK.open];
  if (!o) return `<div class="card" id="dkDetail">${DK.detErr ? esc(DK.detErr) : "Caricamento della scheda…"}</div>`;
  const li = a => a.length ? a.map(x => `<li>${esc(typeof x === "string" ? x : x.text)}${x.src ? ` <span class="cat-src">${esc(x.src)}</span>` : ""}</li>`).join("") : "<li class=\"muted\">nessuna</li>";
  const ch = d => o.change.filter(c => c.dir === d);
  const C = o.context || {};
  const ctx = o.kind === "etf" && isNum(C.yield) ? `<p class="small"><b>Obbligazioni</b>: rendimento a scadenza ${fNum(C.yield, 2)}% lordo · duration ${isNum(C.duration) ? fNum(C.duration, 1) + " anni" + (C.durationKind ? " (" + esc(C.durationKind) + ")" : "") : "n.d."} · credito ${esc(C.credit || "n.d.")}${isNum(C.aOrBetter) ? `, rating A o superiore ${fNum(C.aOrBetter, 0)}%` : ""} · ${esc(C.hedged || "copertura n.d.")}${C.scenarios ? ` · rendimenti +1 punto → prezzo circa ${fNum(C.scenarios[0].priceChange, 1)}% (approssimazione, non una previsione; non si somma al rendimento)` : ""}${isNum(C.ratio) ? ` · rendimento ÷ duration ${fNum(C.ratio, 2)} (solo descrittivo)` : ""}</p>`
    : o.kind === "azione" && o.horizon === "lungo" ? `<p class="small">${C.profile ? `<b>Profilo fondamentale</b>: ${esc(C.profile)}. ` : ""}${C.view ? esc(C.view) + " " : ""}${C.valuation ? `<b>DCF V2</b>: ${esc(C.valuation)}.` : ""}</p>` : "";
  const prod = o.product ? `<h3>Prodotti (separati dal giudizio sull'esposizione)</h3><p class="small">${o.product.products.map(p => `<b>${esc(p.ticker)}</b> TER ${isNum(p.ter) ? fNum(p.ter, 2) + "%" : "n.d."} (${esc(p.terResolution || "n.d.")})${p.hedged ? ", cambio coperto" : ""}${p.documented ? "" : ` <span class="warn">poco documentato</span>`}`).join(" · ")}</p>
    ${o.product.differences.length ? `<ul class="why small">${o.product.differences.map(d => `<li>${esc(d)}</li>`).join("")}</ul>` : ""}` : "";
  const links = [o.links?.stock ? `<button class="btn" data-dkstock="${esc(o.links.stock)}">Scheda del titolo</button>` : "",
    o.links?.investment ? `<button class="btn ghost" data-opm="invest">Analisi fondamentale e valutazione</button>` : "",
    o.links?.etf ? `<button class="btn" data-dketf="${esc(o.links.etf)}" data-dkh="${esc(o.horizon)}">Scheda dell'esposizione ETF</button>` : "",
    o.links?.compare?.length ? `<button class="btn ghost" data-oppetf="${esc(o.links.compare.join(","))}">${o.links.compare.length > 1 ? "Confronta gli ETF" : "Apri l'ETF nel catalogo"}</button>` : ""].join(" ");
  return `<div class="card eo-detail" id="dkDetail"><div class="card-h"><h2>${esc(o.name)}</h2> ${dkSt(o.state)}<button class="btn ghost" data-dkclose>Chiudi</button></div>
    <p class="small muted">${esc(o.kindLabel)}${o.code ? " · " + esc(o.code) : ""} · ${esc(o.horizonLabel)} · Decision Desk ${esc(o.version)}${o.e2State ? ` · stato del modello ETF ${esc(o.e2Version || "")}: «${esc(o.e2State)}»` : ""}</p>
    <h3>Sintesi</h3><p class="small"><b>${esc(o.main)}</b></p><p class="small muted">Regola ${esc(o.rule)}: ${esc(o.ruleText)}</p>${ctx}
    <div class="opp-cols"><div><h4>Evidenze favorevoli</h4><ul class="why small">${li(o.favourable)}</ul></div><div><h4>Evidenze contrarie</h4><ul class="why small">${li(o.contrary)}</ul></div></div>
    <h3>Rischi</h3><ul class="why small">${o.risks.length ? o.risks.map(r => `<li>${r.blocking ? "⚠ " : ""}${esc(r.text)} <span class="cat-src">${esc(r.src)}</span></li>`).join("") : "<li>Nessun rischio oltre le soglie dei motori.</li>"}</ul>
    <h3>Cosa cambierebbe il giudizio</h3><div class="opp-cols"><div><h4>Migliora se</h4><ul class="why small">${li(ch("migliora"))}</ul></div><div><h4>Peggiora se</h4><ul class="why small">${li(ch("peggiora"))}</ul></div></div>
    ${ch("verifica").length ? `<h4>Da verificare</h4><ul class="why small">${li(ch("verifica"))}</ul>` : ""}
    ${o.kind === "azione" && o.horizon === "lungo" ? `<p class="muted small">I livelli del DCF sono soglie per una nuova analisi, non prezzi ai quali un acquisto è conveniente.</p>` : ""}
    ${prod}
    ${dkFitHTML(o)}
    <h3>Dati</h3><p class="small">Qualità dei dati: <b>${esc(o.dataQuality)}</b>. Date: ${Object.entries(o.dates).map(([k, v]) => `${esc(DK_DATES[k] || k)} ${esc(dayIT(String(v).slice(0, 10)))}`).join(" · ") || "n.d."}.</p>
    ${o.missing.length ? `<h4>Dati mancanti</h4><ul class="why small">${li(o.missing)}</ul>` : ""}
    ${o.notes.length ? `<h4>Note</h4><ul class="why small">${li(o.notes)}</ul>` : ""}
    <h3>Stato della validazione</h3><p class="small">${esc(o.validation)}</p>
    <p class="eo-act">${links}</p>
    <p class="muted small">${esc(o.disclaimer)}</p></div>`;
}
const DK_DATES = { price: "prezzo", statements: "bilanci scaricati", analysts: "stime analisti", latestQuarter: "ultimo trimestre",
  valuationPrices: "prezzi del DCF", latestYear: "ultimo esercizio", latestQuarterAnnounced: "trimestre annunciato", benchmark: "benchmark",
  common: "date comuni con il benchmark", duration: "duration", yield: "rendimento a scadenza", ratings: "rating" };
function deskHTML() {
  const D = DK.data;
  const seg = `<div class="seg">${Object.entries(OPP_MODES).map(([k, l]) => `<button data-opm="${k}" class="${k === "desk" ? "on" : ""}">${esc(l.split(" · ")[0])}</button>`).join("")}</div>`;
  const head = `<div class="card"><div class="card-h"><h2>Decision Desk</h2>${DK.data?.version ? `<span class="card-meta">versione ${esc(DK.data.version)}</span>` : ""}${seg}</div>
    <div class="seg small">${[["lungo", "Medio-lungo periodo"], ["breve", "Breve periodo"]].map(([k, l]) => `<button data-dkh="${k}" class="${k === DK.h ? "on" : ""}">${l}</button>`).join("")}</div>
    <div class="seg small">${[["all", "Azioni ed ETF"], ["azione", "Azioni"], ["etf", "ETF"]].map(([k, l]) => `<button data-dkk="${k}" class="${k === DK.k ? "on" : ""}">${l}</button>`).join("")}</div>
    <p class="small muted">${DK.h === "breve" ? "3–30 sedute: solo descrizione e monitoraggio. Le regole Trading e il momentum degli ETF non hanno mostrato vantaggi nei test: nel breve periodo nessuno stato supera «Monitora»."
      : "3–24 mesi o più: qualità, crescita, solidità, valutazione e scenari DCF per le azioni; esposizione, rischio, costi e prodotti per gli ETF. Il giudizio sull'esposizione è separato dalla qualità del singolo ETF."}</p></div>`;
  if (!D) {
    if (!DK.loading) loadDesk();
    return head + `<div class="card empty">${DK.err === "loading" ? "I dati di mercato si stanno ancora caricando: il Decision Desk compare appena sono pronti."
      : DK.err ? `Decision Desk non disponibile (${esc(DK.err)}). Nuovo tentativo al prossimo aggiornamento della pagina.` : "Caricamento del Decision Desk…"}</div>`;
  }
  const rows = dkRows(D), by = s => rows.filter(r => r.state === s);
  const kpi = (l, v, s) => `<div class="kpi"><div class="l">${l}</div><div class="v">${v}</div><div class="s">${s || ""}</div></div>`;
  const deep = by("Da approfondire");
  const mon = [...by("Attendi condizioni migliori"), ...by("Monitora"), ...by("Monitora — trend esplorativo")];
  const src = D.sources || {}, e = src.etf_lungo || {};
  const cv = D.coverage || {}, cvc = cv.catalog || {};
  const cvLine = (["lungo", "breve"].map(m => cv[m] ? `${m === "lungo" ? "medio-lungo" : "breve"}: ${cv[m].scanner} esposizioni dello scanner = ${cv[m].classified} classificate (di cui ${cv[m].insufficient} con dati insufficienti) + ${cv[m].references.length} riferimenti di mercato + ${cv[m].notAnalysable.length} non analizzabili in questo orizzonte${cv[m].balanced ? "" : " ⚠ conti non in pari"}` : "").filter(Boolean).join("; "))
    + (isNum(cvc.products) ? `. Catalogo: ${cvc.products} ETF nelle esposizioni${cvc.excluded?.length ? `; fuori dal catalogo ordinario ${cvc.excluded.map(x => `${esc(x.name)} (${esc(x.why || "escluso")})`).join(", ")}` : ""}` : "");
  return `${scopeNote("Screening esplorativo, non consulenza finanziaria · nessun giudizio validato sul passato.",
      `Il Decision Desk riassume i motori già esistenti e dice dove concentrare l'attenzione: nessuna indicazione di acquisto o vendita, nessuna
      probabilità, nessun prezzo di ingresso. Nessun giudizio è validato sul passato.`)}${head}
    <div class="kpis eo-kpis">${kpi("Da approfondire", deep.length, "tutte le condizioni, nessuna contraria")}${kpi("Da monitorare", mon.length, "attendi condizioni migliori o monitora")}
      ${kpi("Contrastanti", by("Condizioni contrastanti").length, "evidenze a favore e contro")}${kpi("Rischio elevato", by("Rischio elevato").length, "rischio non compensato")}
      ${kpi("Analisi", esc(oppTime(D.asOf)), `azioni: seduta ${esc(dayIT(D.session || ""))}${e.session ? ` · ETF: ${esc(dayIT(e.session))}` : ""}`)}</div>
    ${dkDetailHTML()}
    <div class="card"><h3>Opportunità da approfondire</h3>${deep.length ? dkTable(deep) : `<p class="small"><b>Nessuna opportunità convincente</b> ${DK.h === "breve" ? "nel breve periodo: per costruzione nessuno stato supera «Monitora»." : "oggi con i filtri scelti: nessuna riga soddisfa tutte le condizioni di «Da approfondire»."}</p>`}
      <p class="muted small">${esc(D.orderRule)}</p></div>
    ${dkSection("Situazioni da monitorare", mon, "«Attendi condizioni migliori»: fondamentali favorevoli ma prezzo o valutazione impegnativi; «Monitora»: evidenze favorevoli ma non sufficienti; «Monitora — trend esplorativo»: ETF con le condizioni di trend soddisfatte, non validate come criterio predittivo (non è un giudizio negativo)", true, "dk-mon")}
    ${dkSection("Condizioni contrastanti", by("Condizioni contrastanti"), "evidenze favorevoli e contrarie insieme: nessun fattore positivo cancella un rischio", false, "dk-mix")}
    ${dkSection("Rischi elevati", by("Rischio elevato"), "un rischio grave non compensato da fattori positivi", false, "dk-risk")}
    ${dkSection("Nessuna opportunità convincente", by("Nessuna opportunità convincente"), "comprese le obbligazioni con evidenza insufficiente (modello E2): qualità del credito e costi bassi non bastano", false, "dk-none")}
    ${dkSection("Dati insufficienti", by("Dati insufficienti"), "analisi non possibile o dati non coerenti: nessun giudizio", false, "dk-na")}
    <div class="card"><details class="fold" data-k="dk-method"><summary><h3>Regole, fonti e diario</h3><span class="card-meta">come nasce ogni stato</span></summary>
      <ul class="why small">${Object.entries(D.rules).map(([k, v]) => `<li><b>${esc(k)}</b> ${esc(v)}</li>`).join("")}</ul>
      <p class="small"><b>Validazione</b></p><ul class="why small">${Object.values(D.validation).map(v => `<li>${esc(v)}</li>`).join("")}</ul>
      <p class="small"><b>Fonti</b>: Trading e Pagella ${esc(src.trading?.model || "n.d.")} (seduta ${esc(src.trading?.session || "n.d.")}) · analisi fondamentale ${esc(src.fundamentals?.model || "n.d.")} · DCF ${esc(src.valuation?.model || "n.d.")} · scanner ETF ${esc(e.model || "n.d.")} (seduta ${esc(e.session || "n.d.")}, prezzi ${esc((e.prices || "n.d.").slice(0, 16).replace("T", " "))}) · Decision Desk ${esc(D.version)}.</p>
      ${D.notAnalysed.length ? `<p class="small"><b>Non analizzati</b>: ${D.notAnalysed.map(x => `${esc(x.what)}${x.horizon === "lungo" ? " (medio-lungo)" : x.horizon === "breve" && !/breve periodo/.test(x.what) ? " (breve)" : ""} (${esc(x.why)})`).join("; ")}.</p>` : ""}
      ${cvLine ? `<p class="small"><b>Copertura ETF</b>: ${cvLine}.</p>` : ""}
      <p class="small"><b>Diario delle decisioni</b>: ${D.diary?.started ? `${D.diary.days} sedute registrate (dal ${esc(dayIT(D.diary.first))} al ${esc(dayIT(D.diary.last))}), ${D.diary.observations} decisioni, versioni ${esc((D.diary.versions || []).join(", "))}` : "nessuna seduta ancora registrata"}; versione attuale ${esc(D.version)}; si registra una volta per seduta dopo la chiusura NYSE, insieme agli altri diari (server acceso o job serale), mai all'apertura della pagina.</p>
      <p class="muted small">${esc(D.disclaimer)}</p></details></div>`;
}
function renderOpps() {
  const el = $("#oppsBody"), D = opps.data;
  if (state.view !== "opps" || !el) return;
  if (opps.mode === "desk") {                                        // phase 7A: Decision Desk
    const keep = [...el.querySelectorAll("details.fold[data-k]")].map(d => [d.dataset.k, d.open]);
    el.innerHTML = deskHTML();
    keep.forEach(([k, o]) => { const d = el.querySelector(`details.fold[data-k="${k}"]`); if (d) d.open = o; });
    return;
  }
  if (opps.mode === "etf") {                                         // phase 6B: scanner of the ETF exposures
    const keep = [...el.querySelectorAll("details.fold[data-k]")].filter(d => d.open).map(d => d.dataset.k);
    el.innerHTML = oppEtfHTML();
    keep.forEach(k => { const d = el.querySelector(`details.fold[data-k="${k}"]`); if (d) d.open = true; });
    return;
  }
  if (!D) {
    el.innerHTML = `<div class="card empty">${opps.err === "loading" ? "I dati di mercato si stanno ancora caricando: le classifiche compaiono appena sono pronti."
      : `Classifiche non disponibili al momento${opps.err ? ` (${esc(opps.err)})` : ""}.`} Nuovo tentativo al prossimo aggiornamento della pagina.</div>`;
    return;
  }
  const keepOpen = [...el.querySelectorAll("details.fold[data-k]")].filter(d => d.open).map(d => d.dataset.k);
  const mode = OPP_MODES[opps.mode] ? opps.mode : "trading", B = D[mode], items = B.items || [];
  const trading = mode === "trading";
  const perfLab = trading ? ["1 mese", "3 mesi"] : ["6 mesi", "1 anno"];
  const ncols = trading ? 12 : 11;
  const n = B.conditions.length;
  const live = s => state.bySym.get(s.ticker);
  const priceCell = s => {
    const q = live(s), p = q?.price ?? s.price, t = state.snap?.lastQuote || state.snap?.asOf || s.priceTime;
    return `${fPrice(p)} $<div class="muted small">${esc(oppTime(t))}</div>`;
  };
  const warnCell = s => s.warnings.length ? esc(s.warnings.map(w => w.short).join(" · ")) : `<span class="muted">nessuno</span>`;
  const status = s => `<span class="act ${s.status === "Dati insufficienti" ? "rev" : ""}">${esc(s.status)}</span>`;
  const flag = s => s.diag?.flag ? `<div class="opp-flag" title="${esc(s.diag.flag)}">⚠ più forte di QQQ ma ${s.diag.flag.includes("ribassista") ? "trend ribassista" : "in calo"}</div>` : "";
  const ck = c => `<li class="ck-${c.state}"><b>${esc(c.id)} ${esc(c.name)}</b>: ${esc(c.detail)}</li>`;
  const dg = d => d ? `<li>Rendimento del titolo: 1 mese ${fPct(d.abs21, 1)}, 3 mesi ${fPct(d.abs63, 1)}${d.direction ? ` (${esc(d.direction)})` : ""}</li>
      <li>Rispetto a QQQ: 1 mese ${ptPts(d.rel21)}, 3 mesi ${ptPts(d.rel63)}</li><li>Trend (prezzo, media 50, media 200): ${esc(d.trend || "non calcolabile")}</li>
      ${d.flag ? `<li><b>${esc(d.flag)}</b></li>` : ""}` : "<li>non disponibile</li>";
  const detailRow = s => `<tr class="opp-x"><td colspan="${ncols}"><div class="opp-cols">
      <div><h4>Condizioni (${s.ok} su ${s.n} soddisfatte)</h4><ul class="why">${s.conditions.map(ck).join("")}</ul></div>
      <div><h4>Forza relativa e andamento</h4><ul class="why">${dg(s.diag)}</ul>
        <h4>Valori misurati</h4><ul class="why">${s.values.map(v => `<li>${esc(v.label)}: ${esc(v.value)}</li>`).join("") || "<li>non disponibili</li>"}</ul></div>
      <div><h4>Segnali contrari e dati mancanti</h4><ul class="why">${s.warnings.map(w => `<li>${esc(w.text)}</li>`).join("")}
        ${s.missing.map(m => `<li>Manca: ${esc(m.name)} (${esc(m.detail)})</li>`).join("")}${!s.warnings.length && !s.missing.length ? "<li>nessuno</li>" : ""}</ul></div></div>
      <p class="muted small">Prezzi: sedute chiuse fino al ${s.closeDate ? esc(dayIT(s.closeDate)) : "—"}. Analisti, valutazione e notizie: dati di oggi. Clic sul nome per aprire la scheda del titolo.</p></td></tr>`;
  const table = items.length ? `<div class="table-wrap"><table class="scr opp-tbl"><thead><tr><th>#</th><th class="l">Titolo</th><th class="l">Settore</th><th>Prezzo</th>
      ${perfLab.map(l => `<th>${l}</th>`).join("")}${trading ? "<th>Rispetto a QQQ (1 mese)</th>" : ""}<th class="l">Trend</th><th>Condizioni</th><th class="l">Motivo principale</th><th class="l">Attenzione</th><th class="l">Stato</th></tr></thead>
    <tbody>${items.map(s => `<tr data-t="${esc(s.ticker)}"><td>${s.rank}</td><td class="l tk">${esc(s.ticker)}<div class="muted small">${esc(s.name)}</div></td>
      <td class="l">${esc(s.sector || "—")}</td><td>${priceCell(s)}</td>
      ${s.perf.map(p => `<td>${oppPct(p.value)}</td>`).join("")}${trading ? `<td><span class="${sign(s.diag?.rel21)}">${ptPts(s.diag?.rel21)}</span></td>` : ""}
      <td class="l">${esc(s.trend)}${flag(s)}</td><td>${s.ok} su ${s.n}</td>
      <td class="l why-c">${esc(s.main)} <button class="opp-more" data-ox="${esc(s.ticker)}">${opps.open.has(mode + s.ticker) ? "Chiudi" : "Dettagli"}</button></td>
      <td class="l warn-c">${warnCell(s)}</td><td class="l">${status(s)}</td></tr>${opps.open.has(mode + s.ticker) ? detailRow(s) : ""}`).join("")}</tbody></table></div>`
    : `<div class="empty">Oggi nessun titolo soddisfa almeno ${B.min} condizioni su ${n}.${mode === "invest" && !D.analystsReady ? " I dati degli analisti non sono ancora stati scaricati: riprova tra qualche minuto." : ""}</div>`;
  const ne = D.notEvaluable || [];
  const cov = (B.coverage || []).filter(c => c.available < c.total);
  const params = D.model?.params || [];
  const S = opps.diary;
  const diarySum = !S ? "" : S.started ? `dal ${dayIT(S.first)} · ${S.days} ${S.days === 1 ? "giornata" : "giornate"} · ${fNum(Object.values(S.lists).reduce((a, L) => a + L.observations, 0), 0)} osservazioni` : "non ancora avviato";
  el.innerHTML = `${scopeNote("Classifica preliminare, non un segnale di acquisto · non è una consulenza finanziaria.",
      `Sono titoli da <b>osservare e approfondire</b>, scelti con condizioni semplici scritte qui sotto e <b>non validate</b>: nessuna probabilità e
      nessun rendimento atteso. Prima di qualsiasi decisione apri la scheda del titolo e leggi la sezione Decisione.`)}
    <div class="card"><div class="card-h"><h2>${esc(OPP_MODES[mode])}</h2>
      <div class="seg">${Object.entries(OPP_MODES).map(([k, l]) => `<button data-opm="${k}" class="${k === mode ? "on" : ""}">${esc(l.split(" · ")[0])}</button>`).join("")}</div>
      <span class="card-meta">orizzonte ${esc(B.horizon)} · prezzi delle sedute chiuse fino al ${D.asOf ? esc(dayIT(D.asOf)) : "—"} · ${B.qualified} titoli con almeno ${B.min} condizioni su ${n}, mostrati i primi ${items.length}${B.complete ? "" : " · <b>classifica incompleta</b>"}</span></div>
      ${oppStateLine(trading)}
      ${oppMarketLine(D.market)}
      ${B.coverageNote ? `<p class="warn-box"><b>Copertura dei dati insufficiente.</b> ${esc(B.coverageNote)} L'elenco dei titoli senza il dato è in «Come è fatta la classifica».</p>` : ""}
      ${table}
      <details class="fold" data-k="rules"><summary><span class="small">Come è fatta la classifica</span></summary>
        <ul class="why">${B.conditions.map(c => `<li><b>${esc(c.id)} ${esc(c.name)}</b>: ${esc(c.rule)}</li>`).join("")}</ul>
        <p class="small">${esc(B.order)} Un dato mancante conta come condizione non soddisfatta e il titolo è segnato «Dati insufficienti».
          ${trading ? "Gli avvisi: tirato (regola D5), sotto la media 200, oscillazione giornaliera oltre il 4%, trimestrale entro 5 giorni, pattern che non ha superato il test della Fase 11. «Più forte di QQQ ma in calo» è solo un'informazione: non cambia l'ordine."
            : "Gli avvisi: più downgrade che upgrade in 30 giorni, stime tagliate oltre il 3% in 30 giorni, trimestrale entro 5 giorni, notizie dal tono negativo, prezzo sotto la media 50."}</p>
        ${cov.length ? `<p class="small"><b>Copertura dei dati:</b> ${cov.map(c => `${esc(c.id)} ${esc(c.name)} valutabile per ${c.available} titoli su ${c.total}${c.missing.length <= 25 ? ` (mancano: ${esc(c.missing.join(", "))})` : ""}`).join("; ")}.</p>` : `<p class="small">Copertura dei dati: ogni condizione è valutabile per tutti i titoli.</p>`}
        <p class="small"><b>Parametri del modello ${esc(D.model?.version || "")}</b> (quelli <b>sperimentali</b> sono proposte non validate, tenute per compatibilità: non sono strategie):
          ${params.map(p => `${esc(p.text)}: ${esc(String(p.value))}${p.experimental ? " <b>(sperimentale)</b>" : ""}`).join(" · ")}.</p>
        <p class="muted small">Titoli valutati: ${D.evaluated} su ${D.universe}${ne.length ? ` · non valutabili: ${ne.map(x => `${esc(x.ticker)} (${esc(x.why)})`).join(", ")}` : ""}.
          ${D.newsReady ? "" : "Notizie non ancora scaricate. "}Calcolo delle ${esc(oppTime(D.generated))}.</p>
        <h4 class="bt-h">Limiti</h4><ul class="why bt-lim">${OPP_LIMITS.map(([a, b]) => `<li><b>${esc(a)}.</b> ${esc(b)}</li>`).join("")}</ul>
      </details></div>
    ${trading ? "" : invCardHTML()}
    ${trading ? "" : valCardHTML()}
    <div class="card"><details class="fold" data-k="diary"><summary><h3>Monitoraggio risultati</h3><span class="card-meta">${esc(diarySum)}</span></summary>${oppDiaryHTML()}</details></div>
    <div class="card"><details class="fold" data-k="lab"><summary><h3>Qualità dei segnali</h3><span class="card-meta">${opps.lab ? "regola attuale, studio storico, strategie sperimentali e diario prospettico" : "non disponibile"}</span></summary>${oppLabHTML()}</details></div>`;
  keepOpen.forEach(k => { const d = el.querySelector(`details.fold[data-k="${k}"]`); if (d) d.open = true; });
  if (!trading) { loadInv(); loadVal(); }
}
document.addEventListener("click", e => {
  const box = e.target.closest("#oppsBody");
  if (!box) return;
  const m = e.target.closest("[data-opm]");
  if (m) { opps.mode = m.dataset.opm; LS.set("opp.view", opps.mode); renderOpps(); return; }
  const fl = e.target.closest("[data-ifil]");
  if (fl) { opps.invFilter = fl.dataset.ifil; renderOpps(); return; }
  const vf = e.target.closest("[data-vfil]");
  if (vf) { opps.valFilter = vf.dataset.vfil; renderOpps(); return; }
  const so = e.target.closest("[data-isort]");
  if (so) { const k = so.dataset.isort; opps.invSort = { k, dir: opps.invSort.k === k ? -opps.invSort.dir : 1 }; renderOpps(); return; }
  const x = e.target.closest("[data-ox]");
  if (x) { const k = opps.mode + x.dataset.ox; opps.open.has(k) ? opps.open.delete(k) : opps.open.add(k); renderOpps(); return; }
  const tr = e.target.closest("tr[data-t]");
  if (tr) openDetail(tr.dataset.t);
});

// ------------------------------------------------------------ search
const qEl = $("#q"), sugg = $("#sugg");
let suggSel = 0, suggList = [];
function renderSugg() {
  const q = qEl.value.trim().toUpperCase();
  if (!q || !state.snap) { sugg.classList.remove("open"); return; }
  const S = stocks();
  suggList = [
    ...S.filter(s => s.ticker.startsWith(q)),
    ...S.filter(s => !s.ticker.startsWith(q) && (s.name.toUpperCase().includes(q) || s.ticker.includes(q))),
  ].slice(0, 8);
  suggSel = Math.min(suggSel, Math.max(0, suggList.length - 1));
  sugg.innerHTML = suggList.map((s, i) => `<button class="${i === suggSel ? "sel" : ""}" data-t="${esc(s.ticker)}"><span class="t">${esc(s.ticker)}</span><span class="n">${esc(s.name)}</span><span class="${sign(s.chgPct)} num">${fPct(s.chgPct)}</span></button>`).join("")
    || `<div class="empty">Nessun titolo del Nasdaq-100 trovato</div>`;
  sugg.classList.add("open");
}
qEl.addEventListener("input", () => { suggSel = 0; renderSugg(); });
qEl.addEventListener("keydown", e => {
  if (e.key === "ArrowDown") { suggSel = Math.min(suggSel + 1, suggList.length - 1); renderSugg(); e.preventDefault(); }
  if (e.key === "ArrowUp") { suggSel = Math.max(suggSel - 1, 0); renderSugg(); e.preventDefault(); }
  if (e.key === "Enter" && suggList[suggSel]) { openDetail(suggList[suggSel].ticker); qEl.value = ""; qEl.blur(); sugg.classList.remove("open"); }
  if (e.key === "Escape") { qEl.value = ""; qEl.blur(); sugg.classList.remove("open"); }
});
qEl.addEventListener("blur", () => setTimeout(() => sugg.classList.remove("open"), 150));
sugg.addEventListener("mousedown", e => { const b = e.target.closest("[data-t]"); if (b) { openDetail(b.dataset.t); qEl.value = ""; } });
document.addEventListener("keydown", e => {
  if (e.key === "/" && document.activeElement.tagName !== "INPUT") { e.preventDefault(); qEl.focus(); }
  if (e.key === "Escape" && (state.detail || state.macro || state.panel)) closeDetail();
});

// ------------------------------------------------------------ Compatibilità con il portafoglio (phase 7B, portfolio_fit.py)
// Nothing personal is requested until the user presses a button: "mio" uses the portfolio already in the server's memory
// (read only), "esempio" a made-up one. Results stay in this page's memory only (never saved, never sent elsewhere).
const FIT = { source: null, data: null, loading: false, err: null, cand: "", amount: "", currency: "EUR", funding: "nuova", reduce: "", limits: {}, sim: null, simErr: null };
const FIT_SRC = { mio: "il mio portafoglio", esempio: "il portafoglio di esempio" };
const FIT_Q = q => Object.entries(q || {}).map(([k, v]) => `${k} ${fNum(v, 0)}%`).join(", ");
async function fitRequest(source, extra = {}) {
  return pfPost("/api/portfolio/fit", { headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ consent: true, source, limits: FIT.limits, ...extra }) });
}
async function loadFit(source) {
  FIT.source = source; FIT.loading = true; FIT.err = null; FIT.sim = null; FIT.simErr = null; renderFit();
  try { FIT.data = await fitRequest(source); } catch (e) { FIT.err = e.message || "server non raggiungibile"; FIT.data = null; }
  FIT.loading = false; renderFit();
}
async function runFitSim() {
  if (!FIT.cand) { FIT.simErr = "scegli uno strumento"; renderFit(); return; }
  FIT.simErr = null; FIT.sim = "loading"; renderFit();
  try {
    const d = await fitRequest(FIT.source, { candidate: FIT.cand, whatif: FIT.amount ? { amount: Number(String(FIT.amount).replace(",", ".")), currency: FIT.currency, funding: FIT.funding, reduce: FIT.reduce || null } : null });
    FIT.sim = d.available ? { compat: d.compat, whatif: d.whatif, err: d.compatError } : null;
    if (!d.available) FIT.simErr = d.why;
  } catch (e) { FIT.sim = null; FIT.simErr = e.message; }
  renderFit();
}
const fitRows = (rows, n = 8) => rows.slice(0, n).map(r => `<tr><td class="l">${esc(r.label)}</td><td>${fNum(r.pct, 1)}%</td><td class="l small muted">${esc(FIT_Q(r.quality))}</td></tr>`).join("");
function fitTable(title, rows, sub) {
  return `<div><h4>${title}</h4><div class="table-wrap"><table class="scr fit-tbl"><thead><tr><th class="l">Voce</th><th>Peso</th><th class="l">Qualità del dato</th></tr></thead><tbody>${fitRows(rows, 10)}</tbody></table></div>${sub ? `<p class="muted small">${esc(sub)}</p>` : ""}</div>`;
}
function fitCompatHTML(c, compact) {
  if (!c) return "";
  const li = a => a.map(x => `<li>${esc(typeof x === "string" ? x : x.text)}</li>`).join("");
  const d2 = c.d2 ? `<p class="small">Stato del Decision Desk ${esc(c.d2.version)}: <b>${esc(c.d2.state)}</b> (regola ${esc(c.d2.rule)}, ${esc(c.d2.horizon)}): <span class="muted">${esc(c.separate)}</span></p>` : "";
  const pres = c.present?.direct ? `Sì, direttamente: ${fNum(c.present.weight, 1)}% (${esc(c.present.how)})` : "No, non direttamente";
  const ind = c.indirect ? (isNum(c.indirect.pct) ? `${fNum(c.indirect.pct, 2)}% tramite ${esc(c.indirect.via.map(v => v.fund).join(", "))} (${esc(c.indirect.kind)})` : esc(c.indirect.text || "non determinabile")) : (c.candidate.class === "azione" ? "nessuna tra i titoli noti degli ETF" : "—");
  const ov = c.overlap ? `${c.overlap.common.length} società in comune, ${fNum(c.overlap.sharedPct, 1)}% del fondo su ${fNum(c.overlap.candidateKnownPct, 1)}% noto${c.overlap.date ? " (composizione del " + esc(dayIT(c.overlap.date)) + ")" : ""}` : null;
  const st = d => (c.strengthen[d] || []).slice(0, 4).map(r => `${esc(r.label)} (${fNum(r.candidate, 0)}% nel candidato, ${fNum(r.portfolio, 1)}% oggi)`).join(", ") || "nessuna";
  const nw = d => (c.new[d] || []).slice(0, 4).map(r => esc(r.label)).join(", ") || "nessuna";
  const lim = c.limits.configured ? c.limits.rows.filter(r => r.limit != null).map(r => `${esc(r.label)}: ${esc(r.state)} (${fNum(r.observed, 1)}% / limite ${fNum(r.limit, 1)}%)`).join("; ") : esc(c.limits.text);
  return `${d2}<ul class="why small">${c.tags.length ? li(c.tags) : "<li>Nessuna sovrapposizione o concentrazione rilevata con i dati disponibili.</li>"}</ul>
    ${compact ? "" : `<div class="table-wrap"><table class="scr fit-tbl"><tbody>
      <tr><td class="l">1. È già presente?</td><td class="l">${pres}${c.equivalent.length ? `; esposizione equivalente: ${esc(c.equivalent.map(e => e.name + " (" + e.how + ")").join(", "))}` : ""}</td></tr>
      <tr><td class="l">2–3. Esposizione diretta / indiretta</td><td class="l">${c.present?.direct ? fNum(c.present.weight, 1) + "%" : "0%"} / ${ind}${ov ? "; sovrapposizione: " + ov : ""}</td></tr>
      <tr><td class="l">4. Rafforzerebbe</td><td class="l">settori: ${st("sector")}; paesi: ${st("country")}; valute: ${st("currency")}</td></tr>
      <tr><td class="l">6. Nuove esposizioni</td><td class="l">settori: ${nw("sector")}; paesi: ${nw("country")}; valute: ${nw("currency")}; classi: ${nw("assetClass")}</td></tr>
      <tr><td class="l">7. Dati non disponibili</td><td class="l">${c.missing.length ? esc(c.missing.join("; ")) : "nessuno rilevato"}</td></tr>
      <tr><td class="l">8. Limiti personali</td><td class="l">${lim}</td></tr></tbody></table></div>
      <p class="muted small">${esc(c.rule)}</p>`}`;
}
function fitSimHTML(w) {
  if (!w) return "";
  if (!w.ok) return `<p class="warn small">Simulazione non eseguibile: ${esc(w.why)}</p>`;
  const B = w.before, A = w.after;
  const row = (l, b, a, d = 1, u = "%") => `<tr><td class="l">${l}</td><td>${fNum(b, d)}${u}</td><td>${fNum(a, d)}${u}</td></tr>`;
  const dl = (dim, t) => (w.delta[dim] || []).slice(0, 6).map(r => `<tr><td class="l">${t}: ${esc(r.label)}</td><td>${fNum(r.before, 1)}%</td><td>${fNum(r.after, 1)}%</td></tr>`).join("");
  const sb = w.stressBefore, sa = w.stressAfter;
  return `<p class="small"><b>Ipotesi</b>: ${fEur(w.amountEUR, 0)} · ${esc(w.fundingText)}. ${esc(w.note)}</p>
    <div class="table-wrap"><table class="scr fit-tbl"><thead><tr><th class="l">Misura</th><th>Prima</th><th>Dopo</th></tr></thead><tbody>
      ${row("Valore totale", B.totalEUR, A.totalEUR, 0, " €")}${row("Prime 5 posizioni", B.top5, A.top5)}${row("Numero equivalente di posizioni", B.effective, A.effective, 1, "")}
      ${row("Parte analizzabile a livello di società", B.coverage.analysed, A.coverage.analysed)}
      ${dl("assetClass", "Classe")}${dl("sector", "Settore")}${dl("country", "Paese")}${dl("currency", "Valuta")}
      ${(w.companies || []).slice(0, 5).map(r => `<tr><td class="l">Società: ${esc(r.name)} <span class="cat-src">${esc(r.kind)}</span></td><td>${fNum(r.before, 2)}%</td><td>${fNum(r.after, 2)}%</td></tr>`).join("")}
      ${sb.map((s, i) => `<tr><td class="l">Ipotesi: ${esc(s.scenario)}</td><td>${fNum(s.impactPct, 1)}%</td><td>${fNum(sa[i]?.impactPct, 1)}%</td></tr>`).join("")}
    </tbody></table></div>
    <h4>Rischi aggiuntivi</h4><ul class="why small">${w.risks.length ? w.risks.map(r => `<li>${esc(r)}</li>`).join("") : "<li>Nessuna voce più pesante aumenta.</li>"}</ul>
    ${w.missing.length ? `<h4>Dati mancanti</h4><ul class="why small">${w.missing.map(r => `<li>${esc(r)}</li>`).join("")}</ul>` : ""}
    <p class="muted small">Le ipotesi su azioni, tassi e dollaro sono spostamenti deterministici scelti a priori: non sono previsioni e non hanno probabilità.</p>`;
}
function fitPageHTML() {
  const D = FIT.data, A = D?.analysis;
  // phase 8B.1: what the page is for, before any button (works without the portfolio); details in «Come funziona»
  const intro = `<div class="card"><div class="card-h"><h2>Compatibilità con il portafoglio</h2></div>
    <p class="fit-lead">Questa analisi ti aiuta a capire come un nuovo investimento cambierebbe il tuo portafoglio: concentrazione, sovrapposizioni fra azioni ed ETF, settori, paesi, valute e rischi.</p>
    <p class="small fit-ex"><b>Esempio</b> (dati inventati): se possiedi già NVIDIA e un ETF Nasdaq-100 che contiene NVIDIA, comprare un altro ETF tecnologico potrebbe aumentare la tua esposizione complessiva alla stessa azienda.</p>
    <details class="scope-note fit-how"><summary><span class="sn-lead">Compatibile non vuol dire buono o cattivo.</span> <span class="sn-more">Come funziona</span></summary><div class="sn-body">
      <p><b>Cosa significa «compatibilità».</b> Quanto un nuovo strumento si somma a quello che hai già: se aggiunge esposizioni nuove (diversifica) oppure
        rafforza quelle che hai (concentra). Non dice se lo strumento è un buon investimento: uno strumento «poco compatibile» può essere valido, uno
        «compatibile» può essere rischioso.</p>
      <p><b>Perché è utile.</b> Molti ETF contengono le stesse grandi società: comprandone più di uno, o comprando anche le azioni, si rischia di puntare
        due o tre volte sulla stessa azienda senza accorgersene.</p>
      <p><b>Cosa misura.</b> Peso delle prime posizioni e numero equivalente di posizioni; le società presenti in più strumenti (anche dentro gli ETF);
        la ripartizione per classe, settore, paese e valuta economica; un rischio descrittivo dalle serie storiche e alcune ipotesi fisse su azioni, tassi e dollaro.</p>
      <p><b>Cosa NON misura.</b> Non prevede rendimenti, non dà probabilità, non valuta prezzo o qualità dell'azienda, non considera tasse e costi di transazione,
        non dice quando comprare o vendere.</p>
      <p><b>Informazioni parziali.</b> Dentro gli ETF la dashboard conosce di solito solo i primi titoli pubblicati dall'emittente (con la loro data): il resto
        resta «non dettagliato» e non viene ripartito per arrivare al 100%. Strumenti senza classificazione o senza prezzi recenti sono segnati come tali.</p>
      <p><b>Cosa fa il simulatore.</b> Aggiunge in memoria un importo che scegli tu a uno strumento e confronta il prima e il dopo: nessun ordine, nessun
        salvataggio, nessun diario. È un giudizio <b>separato</b> dal Decision Desk e non lo cambia.</p></div></details>
    <p class="small muted">I dati del portafoglio si usano solo dopo il tuo clic, in sola lettura e solo in memoria su questo Mac: niente copie, niente diari, niente servizi esterni.</p>
    <p class="eo-act"><button class="btn" data-fit="mio">Analizza compatibilità con il mio portafoglio</button> <button class="btn ghost" data-fit="esempio">Usa un portafoglio di esempio</button></p></div>`;
  if (FIT.loading) return intro + `<div class="card">Analisi di ${esc(FIT_SRC[FIT.source])} in corso…</div>`;
  if (FIT.err) return intro + `<div class="card empty">Analisi non disponibile: ${esc(FIT.err)}.</div>`;
  if (!D) return intro;
  if (!D.available) return intro + `<div class="card empty">${esc(D.why)}</div>`;
  const kpi = (l, v, s) => `<div class="kpi"><div class="l">${l}</div><div class="v">${v}</div><div class="s">${s || ""}</div></div>`;
  const C = A.concentration, L = A.lookthrough, cov = L.coverage;
  const R = A.risk || {};
  const opts = (D.choices || []).map(c => `<option value="${esc(c.ref)}">${esc(c.label)}</option>`).join("");
  const lim = Object.entries({ position: "posizione", company: "società", sector: "settore", country: "paese", currency: "valuta" })
    .map(([k, l]) => `<label class="small">${l} % <input class="fit-lim" data-fitlim="${k}" inputmode="decimal" value="${esc(FIT.limits[k] ?? "")}" placeholder="—"></label>`).join(" ");
  return intro + `<p class="small"><b>Fonte</b>: ${esc(D.sourceLabel)} · analisi ${esc(A.version)} del ${esc(dayIT(A.asOf))}.</p>
    <div class="kpis">${kpi("Valore", fEur(A.totalEUR, 0), A.indicative.length ? "indicativo: prezzi o cambi non recenti" : "valori in euro")}${kpi("Posizioni", C.n, `numero equivalente ${fNum(C.effective, 1)}`)}
      ${kpi("Prime 5", fNum(C.top5, 1) + "%", "del valore")}${kpi("Analizzabile per società", fNum(cov.analysed, 1) + "%", `oltre i titoli noti ${fNum(cov.beyondKnown, 1)}% · non azionario ${fNum(cov.nonEquity, 1)}%`)}</div>
    <div class="card"><h3>Posizioni principali</h3><div class="table-wrap"><table class="scr fit-tbl"><thead><tr><th class="l">Strumento</th><th class="l">Tipo</th><th>Peso</th><th class="l">Dentro il fondo</th></tr></thead><tbody>
      ${A.positions.slice().sort((a, b) => (b.weight || 0) - (a.weight || 0)).map(p => `<tr><td class="l">${esc(p.name)}${p.isin ? `<br><span class="cat-src">${esc(p.isin)}</span>` : ""}</td><td class="l small">${esc(p.classLabel)}${p.indicative ? " · <span class=\"warn\">indicativo</span>" : ""}</td><td>${isNum(p.weight) ? fNum(p.weight, 1) + "%" : "non valutato"}</td><td class="l small">${esc(p.lookthrough)}${p.class === "etf" && p.covered ? ` (${fNum(p.covered * 100, 0)}% noto)` : ""}</td></tr>`).join("")}
    </tbody></table></div><p class="muted small">Date: ${Object.entries(A.dates).map(([k, v]) => `${esc(k)} ${esc(dayIT(String(v).slice(0, 10)))}`).join(" · ")}.</p></div>
    <div class="card"><h3>Composizione</h3><div class="opp-cols">${fitTable("Classe di investimento", A.breakdown.assetClass)}${fitTable("Settori", A.breakdown.sector, A.taxonomy)}</div>
      <div class="opp-cols">${fitTable("Paesi delle società", A.breakdown.country)}${fitTable("Valuta economica", A.breakdown.currency, "La valuta in cui si compra un ETF non è la sua esposizione: qui conta la valuta dei titoli dentro il fondo (stima) o la copertura dichiarata.")}</div>
      <p class="muted small">Le parti «non classificate» o «non dettagliate» restano visibili: nessun dato mancante viene ripartito per arrivare al 100%.</p></div>
    <div class="card"><h3>Sovrapposizioni: stesse società in più strumenti</h3>
      ${L.overlaps.length ? `<div class="table-wrap"><table class="scr fit-tbl"><thead><tr><th class="l">Società</th><th>Diretta</th><th>Dentro gli ETF</th><th>Totale</th><th class="l">Tipo</th></tr></thead><tbody>
        ${L.overlaps.slice(0, 12).map(o => `<tr><td class="l">${esc(o.name)}</td><td>${fNum(o.directEUR / A.totalEUR * 100, 2)}%</td><td>${fNum(o.indirectEUR / A.totalEUR * 100, 2)}%</td><td><b>${fNum(o.pct, 2)}%</b></td><td class="l small">${esc(o.kind)} · ${esc(o.via.map(v => v.fund).join(", "))}</td></tr>`).join("")}</tbody></table></div>` : `<p class="small">Nessuna società presente in più strumenti tra i titoli noti.</p>`}
      ${L.fundPairs.length ? `<ul class="why small">${L.fundPairs.map(p => `<li>${esc(p.a)} e ${esc(p.b)}: ${p.common.length} titoli in comune tra i primi 10, sovrapposizione nota ${fNum(p.overlapKnown, 1)}% (composizioni del ${esc(p.dates.filter(Boolean).map(dayIT).join(" e ") || "n.d.")})</li>`).join("")}</ul>` : ""}
      <p class="muted small">${esc(L.rule)}</p></div>
    <div class="card"><h3>Rischio (descrittivo)</h3>
      ${R.scopeText ? `<div class="fit-scope ${R.scope === "parte investita" ? "" : "partial"}"><p class="small"><b>${R.scope === "parziale" ? "Rischio parziale" : R.scope === "nessuna" ? "Nessuna copertura" : "Copertura"}:</b> ${esc(R.scopeText)}</p>
        ${isNum(R.coverageTotalPct) ? `<p class="small muted">Coperto dalle serie storiche ${fNum(R.coverageTotalPct, 1)}% del portafoglio · non coperto ${fNum(Math.max(0, R.uncoveredTotalPct), 1)}% · liquidità esclusa ${fNum(R.cashPct || 0, 1)}%${R.unvaluedCount ? ` · ${R.unvaluedCount} posizioni senza valore in euro` : ""}.</p>` : ""}</div>` : ""}
      ${R.state === "calcolato" ? `<p class="small">${R.scope === "parziale" ? "Della sola parte coperta" : "Della parte investita"}: volatilità annua ${fNum(R.vol, 1)}% · massima perdita ${fNum(R.maxDrawdown, 1)}% (dal ${esc(dayIT(R.first))} al ${esc(dayIT(R.last))}, ${R.sessions} sedute).</p>
        <p class="small muted">Metodo: ${esc(R.method)}; ${esc(R.weightsNote || "")}.</p>
        ${R.correlations.length ? `<p class="small">Correlazioni settimanali più alte: ${R.correlations.slice(0, 4).map(c => `${esc(c.a)} / ${esc(c.b)} ${fNum(c.corr, 2)}`).join(" · ")}.</p>` : ""}
        <ul class="why small">${R.limits.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : `<p class="small">${esc(R.why || "Non calcolabile con affidabilità sufficiente")}.</p>`}
      ${R.left?.length ? `<p class="small muted">Fuori dal calcolo: ${esc(R.left.map(x => x.name + " (" + x.why + ")").join("; "))}.</p>` : ""}
      <p class="small">${esc(A.duration.text || A.duration.state)}${isNum(A.duration.bondPct) ? ` · obbligazioni ${fNum(A.duration.bondPct, 1)}% del portafoglio` : ""}. <span class="muted">${esc(A.duration.note || "")}</span></p>
      <h4>Ipotesi deterministiche (non previsioni)</h4><ul class="why small">${A.stress.map(s => `<li>${esc(s.scenario)}: ${fEurS(s.impactEUR, 0)} (${fPct(s.impactPct, 1)} del portafoglio)${s.note ? ` — ${esc(s.note)}` : ""}</li>`).join("")}</ul></div>
    <div class="card"><details class="fold" data-k="fit-lim"><summary><h3>Limiti personali (facoltativi)</h3><span class="card-meta">${A.limits.configured ? "impostati per questa analisi" : "non configurati"}</span></summary>
      <p class="small">${esc(A.limits.text)} Valgono solo in questa pagina e non vengono salvati.</p><p>${lim} <button class="btn ghost" data-fitlimapply>Applica</button></p>
      <ul class="why small">${A.limits.rows.map(r => `<li>${esc(r.label)}: ${esc(r.state)}${isNum(r.observed) ? ` (oggi ${fNum(r.observed, 1)}%)` : ""}${r.note ? ` — ${esc(r.note)}` : ""}</li>`).join("")}</ul></details></div>
    <div class="card"><h3>Simulatore (ipotetico)</h3><p class="small muted">Nessun ordine, nessuna modifica al portafoglio, nulla viene salvato.</p>
      <div class="fit-form"><label class="small">Strumento <input list="fitChoices" data-fitin="cand" value="${esc(FIT.cand)}" placeholder="ticker o ISIN"></label><datalist id="fitChoices">${opts}</datalist>
        <label class="small">Importo <input data-fitin="amount" inputmode="decimal" value="${esc(FIT.amount)}" placeholder="es. 3000"></label>
        <label class="small">Valuta <select data-fitin="currency">${["EUR", "USD"].map(c => `<option ${c === FIT.currency ? "selected" : ""}>${c}</option>`).join("")}</select></label>
        <label class="small">Finanziamento <select data-fitin="funding">${[["nuova", "nuova liquidità"], ["liquidita", "liquidità già presente"], ["riduzione", "riduzione di una posizione"]].map(([k, l]) => `<option value="${k}" ${k === FIT.funding ? "selected" : ""}>${l}</option>`).join("")}</select></label>
        ${FIT.funding === "riduzione" ? `<label class="small">Posizione da ridurre <select data-fitin="reduce"><option value="">—</option>${D.positions.map(p => `<option value="${esc(p.id)}" ${p.id === FIT.reduce ? "selected" : ""}>${esc(p.name)}</option>`).join("")}</select></label>` : ""}
        <button class="btn" data-fitsim>Analizza</button></div>
      ${FIT.simErr ? `<p class="warn small">${esc(FIT.simErr)}</p>` : ""}
      ${FIT.sim === "loading" ? `<p class="small">Calcolo…</p>` : FIT.sim ? `${FIT.sim.err ? `<p class="warn small">${esc(FIT.sim.err)}</p>` : ""}${FIT.sim.compat ? `<h4>Compatibilità di ${esc(FIT.sim.compat.candidate.name)}</h4>${fitCompatHTML(FIT.sim.compat)}` : ""}${FIT.sim.whatif ? `<h4>Prima e dopo</h4>${fitSimHTML(FIT.sim.whatif)}` : FIT.sim.compat ? `<p class="small muted">Indica un importo per vedere il prima e dopo.</p>` : ""}` : ""}</div>
    <div class="card"><h3>Dati incompleti</h3><ul class="why small">${A.missing.length ? A.missing.map(m => `<li>${esc(m)}</li>`).join("") : "<li>Nessuno rilevato.</li>"}</ul>${A.notes.length ? `<p class="small muted">${esc(A.notes.join("; "))}</p>` : ""}</div>
    <p class="muted small">${esc(D.disclaimer)}</p>`;
}
function renderFit() {
  const el = $("#pfFit");
  if (!el || state.view !== "pffit") return;
  $("#pfEmpty").hidden = true;
  const keep = [...el.querySelectorAll("details.fold[data-k]")].filter(d => d.open).map(d => d.dataset.k);
  el.innerHTML = fitPageHTML();
  keep.forEach(k => { const d = el.querySelector(`details.fold[data-k="${k}"]`); if (d) d.open = true; });
}
document.addEventListener("click", e => {
  const f = e.target.closest("[data-fit]");
  if (f) { loadFit(f.dataset.fit); return; }
  if (e.target.closest("[data-fitsim]")) { runFitSim(); return; }
  if (e.target.closest("[data-fitlimapply]")) {
    FIT.limits = {};
    $$(".fit-lim").forEach(i => { const v = Number(String(i.value).replace(",", ".")); if (i.value && isNum(v) && v > 0) FIT.limits[i.dataset.fitlim] = v; });
    if (FIT.source) loadFit(FIT.source);
    return;
  }
  const df = e.target.closest("[data-dkfit]");
  if (df) { loadDeskFit(df.dataset.dkfitref, df.dataset.dkfit); return; }
  const go = e.target.closest("[data-dkfitopen]");
  if (go) { FIT.cand = go.dataset.dkfitopen; FIT.source = go.dataset.dkfitsrc; setView("pffit"); loadFit(FIT.source).then(runFitSim); }
});
document.addEventListener("change", e => {
  const i = e.target.closest("[data-fitin]");
  if (!i) return;
  FIT[i.dataset.fitin] = i.value;
  if (i.dataset.fitin === "funding") renderFit();
});
document.addEventListener("input", e => { const i = e.target.closest("[data-fitin]"); if (i && i.tagName === "INPUT") FIT[i.dataset.fitin] = i.value; });
// Decision Desk: compatibility summary of the opened row (only after a click; never part of the D2 state)
async function loadDeskFit(ref, source) {
  DK.fit = DK.fit || {};
  DK.fit[ref] = { source, loading: true };
  renderOpps();
  try {
    const d = await fitRequest(source, { candidate: ref });
    DK.fit[ref] = { source, data: d };
  } catch (e) { DK.fit[ref] = { source, err: e.message }; }
  renderOpps();
}
function dkFitHTML(o) {
  const F = (DK.fit || {})[o.id];
  const btn = `<p class="eo-act"><button class="btn ghost" data-dkfit="mio" data-dkfitref="${esc(o.id)}">Analizza compatibilità con il mio portafoglio</button> <button class="btn ghost" data-dkfit="esempio" data-dkfitref="${esc(o.id)}">con un portafoglio di esempio</button></p>`;
  let body = `<p class="small muted">Giudizio separato dallo stato del Decision Desk: il portafoglio si legge solo dopo il clic, in sola lettura.</p>`;
  if (F?.loading) body = `<p class="small">Analisi in corso…</p>`;
  else if (F?.err) body = `<p class="warn small">${esc(F.err)}</p>`;
  else if (F?.data && !F.data.available) body = `<p class="small">${esc(F.data.why)}</p>`;
  else if (F?.data?.compatError) body = `<p class="small">${esc(F.data.compatError)}</p>`;
  else if (F?.data?.compat) body = `<p class="small muted">Con ${esc(FIT_SRC[F.source])}:</p>${fitCompatHTML(F.data.compat, true)}
    <p class="eo-act"><button class="btn" data-dkfitopen="${esc(o.id)}" data-dkfitsrc="${esc(F.source)}">Dettagli e simulatore</button></p>`;
  return `<h3>Compatibilità con il portafoglio</h3>${body}${btn}`;
}

// ------------------------------------------------------------ views, theme, resize
// Four tabs that follow a manager's work; each groups the older views, whose ids (and saved links) are unchanged.
// Phase 21: three tabs. The Diario dei segnali appears in Ricerca only with about 3 months of data (it keeps recording
// in the background in any case). Removed pages (Report, Pattern tecnici, Le mie regole) send old links to the nearest one.
const DIARY_READY = 63;
// ---------------------------------------------------------------- Alert e cambiamenti (phase 8A)
// Read only: GET /api/alerts never creates alerts. "Consultato" is a mark of this browser only (localStorage).
const AL = { data: null, err: null, loading: false, at: 0, open: null,
  f: LS.get("al.f", { scope: "tutti", family: "tutti", priority: "tutte", when: "attivi", seen: "tutti" }) };
const AL_SCOPE = { tutti: "Tutti", azione: "Azioni", etf: "ETF", operativo: "Operativi" };
const AL_PRIO = { critica: "Criticità da verificare", importante: "Cambiamento importante", ordinaria: "Aggiornamento ordinario" };
const AL_STATUS = { nuovo: "nuovo", persistente: "già segnalato", baseline: "base di partenza", risolto: "risolto", superato: "superato" };
const alSeen = () => new Set(LS.get("al.seen", []));
function alMarkSeen(ids) { const s = alSeen(); ids.forEach(i => s.add(i)); LS.set("al.seen", [...s].slice(-3000)); }
async function loadAlerts(force) {
  if (AL.loading || (!force && AL.data && Date.now() - AL.at < 60000)) { renderAlerts(); return; }
  AL.loading = true; renderAlerts();
  try { const r = await fetch("/api/alerts", { cache: "no-store" }); AL.data = await r.json(); AL.err = r.ok ? null : (AL.data.error || "errore"); }
  catch (e) { AL.err = "server non raggiungibile"; }
  AL.loading = false; AL.at = Date.now(); renderAlerts();
}
function alFiltered(D) {
  const f = AL.f, seen = alSeen(), last = D.lastRun?.inputs?.diaries?.opportunity?.last?.session;
  return D.alerts.filter(a => (f.scope === "tutti" || a.scope === f.scope) && (f.family === "tutti" || a.family === f.family)
    && (f.priority === "tutte" || a.priority === f.priority)
    && (f.when === "attivi" ? a.active : f.when === "seduta" ? a.active && (!last || (a.session || "") >= last) : f.when === "storico" ? !a.active : true)
    && (f.seen === "tutti" || (f.seen === "nuovi" ? !seen.has(a.id) : seen.has(a.id))));
}
const alVal = v => v == null ? "—" : typeof v === "object" ? Object.entries(v).map(([k, x]) => `${esc(k)}: ${esc(Array.isArray(x) ? x.join(", ") : String(x))}`).join(" · ") : esc(String(v));
function alDetailHTML(a) {
  const link = a.link || {};
  const go = link.view === "stock" && link.ticker ? `<button class="btn ghost" data-algo="stock" data-t="${esc(link.ticker)}">Apri la scheda di ${esc(link.ticker)}</button>`
    : link.view ? `<button class="btn ghost" data-algo="${esc(link.view)}">Apri ${link.view === "etf" ? "ETF" : link.view === "opps" ? "Opportunità e Decision Desk" : esc(link.view)}</button>` : "";
  const ca = a.extra?.causes;
  return `<div class="al-detail"><ol class="why small">
    <li><b>Cosa è cambiato</b>: ${esc(a.title)}${a.exploratory ? " <span class=\"warn\">(esplorativo)</span>" : ""} — ${esc(a.reason || "")}</li>
    <li><b>Prima</b>: ${alVal(a.previous)}</li>
    <li><b>Ora</b>: ${alVal(a.current)}</li>
    <li><b>Quando</b>: ${alWhen(a)}</li>
    <li><b>Perché monitorarlo</b>: ${esc((D_RULE(a.rule) || {}).when || "")}. Priorità: ${esc(AL_PRIO[a.priority] || a.priority)} (${esc((D_RULE(a.rule) || {}).priority || "")}).</li>
    <li><b>Dati a supporto</b>: ${esc(a.model?.name || "")} ${esc(a.model?.version || "")}${a.model?.previousSession ? ` (confronto con la seduta ${esc(dayIT(a.model.previousSession))})` : ""}; ${(a.sources || []).filter(s => s.date).map(s => `${esc(s.name)} ${esc(String(s.date).slice(0, 16))}`).join(" · ") || "fonti n.d."}${ca ? `<br>Cause separate: ${Object.entries(ca).map(([k, v]) => `<b>${esc(k)}</b> ${esc(v)}`).join(" · ")}` : ""}</li>
    <li><b>Limiti</b>: ${esc([a.reliability, ...(a.limits || [])].filter(Boolean).join("; ") || "nessuno indicato")}${a.resolveWhen ? `. Si considera risolto quando: ${esc(a.resolveWhen)}` : ""}</li>
    <li><b>Dove approfondire</b>: ${go || "—"}</li></ol></div>`;
}
const D_RULE = id => (AL.data?.rules || []).find(r => r.id === id);
// Phase 8B: the dates of an alert kept apart - period, publication (only from the source, never "verified"), acquisition
// by the system, detection, sessions compared. Never "published today".
const tsIT = x => x ? esc(String(x).slice(0, 16).replace("T", " ")) : "n.d.";
function alWhen(a) {
  const t = a.timeline || {};
  const parts = [];
  if (t.headline) parts.push(`<b>${esc(t.headline)}</b>`);
  if (t.period) parts.push(`periodo di bilancio al ${esc(dayIT(t.period))}`);
  if (t.published) parts.push(`annuncio indicato dalla fonte: ${esc(dayIT(t.published))} (${esc(t.publishedSource || "non verificato")})`);
  else if (t.period) parts.push("data di pubblicazione non nota");
  if (t.acquired) parts.push(`acquisiti dal sistema ${tsIT(t.acquired)}`);
  parts.push(`sedute confrontate ${t.sessions?.previous ? esc(dayIT(t.sessions.previous)) + " → " : ""}${esc(a.session ? dayIT(a.session) : "n.d.")}`);
  parts.push(`diario calcolato ${tsIT(a.observedAt)}`, `rilevato dagli alert ${tsIT(t.detectedAt || a.firstSeen)}`);
  return parts.join(" · ") + (t.activationText ? `<br><span class="warn">${esc(t.activationText)}</span>` : "");
}
function alertsHTML() {
  if (AL.err) return `<div class="card empty">Alert non disponibili: ${esc(AL.err)}.</div>`;
  const D = AL.data;
  if (!D) return `<div class="card">Caricamento degli alert…</div>`;
  const head = `<div class="card"><h2>Alert e cambiamenti</h2><p class="small">Cosa è cambiato dall'ultima osservazione valida dei diari (solo registrazioni ufficiali e ammissibili), con dati pubblici di azioni ed ETF. ${esc(D.disclaimer)}</p>`;
  if (!D.started) return head + `<p class="small muted">${esc(D.note || "nessun controllo registrato")}${D.lastCheck?.msg ? ` · ultimo tentativo: ${esc(D.lastCheck.msg)}` : ""}</p></div>`;
  const C = D.counts, R = D.lastRun, seen = alSeen();
  const kpi = (l, v, s) => `<div class="kpi"><div class="l">${l}</div><div class="v">${v}</div><div class="s">${s}</div></div>`;
  const diaries = Object.entries(R.inputs.diaries || {}).map(([k, x]) => `${esc({ opportunity: "opportunità", investment: "fondamentali", valuation: "DCF", decision: "decisioni", etf: "ETF" }[k] || k)} ${esc(x.comparison)}${x.last ? " " + esc(dayIT(x.last.session)) : ""}`).join(" · ");
  const fams = ["tutti", ...new Set(D.alerts.map(a => a.family))];
  const seg = (k, opts) => `<div class="seg">${Object.entries(opts).map(([v, l]) => `<button data-alf="${k}" data-v="${esc(v)}" class="${AL.f[k] === v ? "on" : ""}">${esc(l)}</button>`).join("")}</div>`;
  const list = alFiltered(D);
  const groups = {};
  list.forEach(a => (groups[a.group] = groups[a.group] || []).push(a));
  const rows = Object.values(groups).map(g => {
    const a0 = g[0];
    const items = g.map(a => `<li class="al-item ${a.priority}${seen.has(a.id) ? " seen" : ""}"><button class="al-row" data-alopen="${esc(a.id)}">
        <span class="al-p">${esc(AL_PRIO[a.priority] || a.priority)}</span> <b>${esc(a.name)}</b>${a.horizon ? ` <span class="muted">${esc(a.horizon)}</span>` : ""} — ${esc(a.title)}${a.exploratory ? " · esplorativo" : ""}
        <span class="al-st">${esc(AL_STATUS[a.status] || a.status)}${seen.has(a.id) ? " · consultato" : ""} · ${esc(a.session ? dayIT(a.session) : "")}</span></button>
        ${AL.open === a.id ? alDetailHTML(a) : ""}</li>`).join("");
    return g.length > 1 ? `<li class="al-group"><div class="small muted">${esc(a0.family)} · ${g.length} eventi collegati</div><ul class="al-list">${items}</ul></li>` : items;
  }).join("");
  const miss = D.alerts.filter(a => a.active && a.scope === "operativo");
  return head + `<p class="small muted">Ultimo controllo registrato ${esc(String(R.at).slice(0, 16).replace("T", " "))} (${esc(R.source)}, motore ${esc(D.version)}) · ultimo tentativo ${esc(String(D.lastCheck?.at || "n.d.").slice(0, 16).replace("T", " "))}${D.lastCheck?.msg ? ": " + esc(D.lastCheck.msg) : ""}<br>Diari: ${diaries}.</p>
    <div class="kpis">${kpi("Nuovi", C.new, "dall'ultimo controllo")}${kpi("Importanti", C.important, "cambiamenti attivi")}${kpi("Azioni", C.stocks, "alert attivi")}${kpi("ETF", C.etf, "alert attivi")}${kpi("Qualità dei dati", C.quality, "problemi seguiti")}${kpi("Aggiornamenti mancanti", C.operational, miss.length ? "da verificare" : "nessuno")}</div></div>
    <div class="card"><div class="al-filters">${seg("scope", AL_SCOPE)}${seg("priority", { tutte: "Tutte le priorità", ...AL_PRIO })}${seg("when", { attivi: "Attivi", seduta: "Ultima seduta", storico: "Storico", tutto: "Tutto" })}${seg("seen", { tutti: "Tutti", nuovi: "Da consultare", visti: "Consultati" })}
      <label class="small">Tipo <select data-alfam>${fams.map(x => `<option ${AL.f.family === x ? "selected" : ""}>${esc(x)}</option>`).join("")}</select></label>
      <button class="btn ghost" data-alallseen>Segna tutti come consultati</button></div>
      ${list.length ? `<ul class="al-list">${rows}</ul>` : `<p class="small">Nessun alert con questi filtri.${C.active === 0 ? " La prima osservazione di ogni diario è solo la base di partenza: gli alert compaiono quando cambia qualcosa." : ""}</p>`}
      <p class="small muted">${esc(D.priorityRule)}</p></div>
    <div class="card"><details class="fold" data-k="al-rules"><summary><h3>Regole di emissione</h3><span class="card-meta">${D.rules.length} regole${D.disabled.length ? ` · disattivate: ${esc(D.disabled.join(", "))}` : ""}</span></summary>
      <ul class="why small">${D.rules.map(r => `<li><b>${esc(r.id)}</b> ${esc(r.title)} (${esc(r.kind)}): ${esc(r.when)}. Priorità: ${esc(r.priority)}.</li>`).join("")}</ul>
      <p class="small muted">Una regola si disattiva in alert_rules.json senza toccare i modelli finanziari.</p></details></div>`;
}
function renderAlerts() {
  const el = $("#alertsBody");
  if (!el || state.view !== "alerts") return;
  const keep = [...el.querySelectorAll("details.fold[data-k]")].filter(d => d.open).map(d => d.dataset.k);
  el.innerHTML = alertsHTML();
  keep.forEach(k => { const d = el.querySelector(`details.fold[data-k="${k}"]`); if (d) d.open = true; });
}
document.addEventListener("click", e => {
  if (state.view !== "alerts") return;
  const f = e.target.closest("[data-alf]");
  if (f) { AL.f[f.dataset.alf] = f.dataset.v; LS.set("al.f", AL.f); renderAlerts(); return; }
  const o = e.target.closest("[data-alopen]");
  if (o) { const id = o.dataset.alopen; AL.open = AL.open === id ? null : id; alMarkSeen([id]); renderAlerts(); return; }
  if (e.target.closest("[data-alallseen]") && AL.data) { alMarkSeen(alFiltered(AL.data).map(a => a.id)); renderAlerts(); return; }
  const g = e.target.closest("[data-algo]");
  if (g) { if (g.dataset.algo === "stock") openDetail(g.dataset.t); else setView(g.dataset.algo); }
});
document.addEventListener("change", e => {
  const s = e.target.closest("[data-alfam]");
  if (s && state.view === "alerts") { AL.f.family = s.value; LS.set("al.f", AL.f); renderAlerts(); }
});

// ---------------------------------------------------------------- Riepilogo del giorno (phase 8B)
// Read only: GET /api/brief. At most 7 important events of the last processed session, never filled with other things;
// "Nessun cambiamento rilevante…" only when the brief is up to date, otherwise "Riepilogo non aggiornato" and why.
const BR = { data: null, err: null, loading: false, at: 0 };
async function loadBrief(force) {
  if (BR.loading || (!force && BR.data && Date.now() - BR.at < 60000)) { renderBrief(); return; }
  BR.loading = true; renderBrief();
  try { const r = await fetch("/api/brief", { cache: "no-store" }); BR.data = await r.json(); BR.err = r.ok ? null : (BR.data.error || "errore"); }
  catch (e) { BR.err = "server non raggiungibile"; }
  BR.loading = false; BR.at = Date.now(); renderBrief();
}
const BR_SECTION = { azioni: "Azioni", etf: "ETF", fondamentali: "Fondamentali e DCF", rischi: "Rischi", dati: "Dati e aggiornamento" };
function brCardHTML(c) {
  const link = c.link || {};
  const go = link.view === "stock" && link.ticker ? `<button class="btn ghost" data-algo="stock" data-t="${esc(link.ticker)}">Apri ${esc(link.ticker)}</button>`
    : link.view ? `<button class="btn ghost" data-algo="${esc(link.view)}">Apri ${link.view === "etf" ? "ETF" : link.view === "opps" ? "Opportunità" : esc(link.view)}</button>` : "";
  const dd = c.dataDate || {};
  const date = [dd.headline ? `<b>${esc(dd.headline)}</b>` : "", dd.session ? `seduta ${esc(dayIT(dd.session))}${c.previousSession ? ` (confronto con ${esc(dayIT(c.previousSession))})` : ""}` : "",
    dd.period && !dd.published ? `periodo al ${esc(dayIT(dd.period))}` : "", dd.acquired && !dd.published ? `acquisiti ${tsIT(dd.acquired)}` : ""].filter(Boolean).join(" · ");
  return `<li class="br-card al-item ${esc(c.priority)}"><div class="br-h"><span class="al-p">${esc(AL_PRIO[c.priority] || c.priority)}</span> <b>${esc(c.name || c.instrument)}</b> — ${esc(c.what || "")}${c.exploratory ? ` <span class="warn">esplorativo</span>` : ""} <span class="muted small">${esc(BR_SECTION[c.section] || "")}</span></div>
    <ul class="why small">
      ${c.grouped ? `<li><b>Società</b>: ${esc(c.grouped.join(", "))}</li>` : `<li><b>Prima</b>: ${alVal(c.before)} · <b>Ora</b>: ${alVal(c.after)}</li>`}
      <li><b>Perché</b>: ${esc(c.why || "")}</li>
      ${c.causes ? `<li><b>Effetto del prezzo</b>: ${esc(c.causes.prezzo || "n.d.")}<br><b>Effetto di ipotesi e bilanci</b>: ${esc(c.causes["ipotesi e bilanci"] || "n.d.")}</li>` : ""}
      <li><b>Data effettiva dei dati</b>: ${date || "n.d."}</li>
      <li><b>Limiti</b>: ${esc((c.limits || []).join("; ") || "nessuno indicato")}</li>
      ${go ? `<li>${go}</li>` : ""}</ul></li>`;
}
function briefHTML() {
  if (BR.err) return `<div class="card empty">Riepilogo non disponibile: ${esc(BR.err)}.</div>`;
  const D = BR.data;
  if (!D) return `<div class="card">Caricamento del riepilogo…</div>`;
  const A = D.alerts, H = D.health;
  const status = D.upToDate
    ? (D.events.length ? `<p><b>Seduta elaborata: ${esc(dayIT(D.session))}</b> · ${A.important} ${A.important === 1 ? "cambiamento importante" : "cambiamenti importanti"}${A.ordinary ? ` · ${A.ordinary} aggiornamenti ordinari` : ""}</p>`
                       : `<p class="br-none"><b>${esc(D.message)}</b> (seduta ${esc(dayIT(D.session))}${A.ordinary ? `; ${A.ordinary} aggiornamenti ordinari in Alert e cambiamenti` : ""})</p>`)
    : `<p class="br-stale"><b>${esc(D.message)}</b>: ${esc(D.reasons.join("; "))}.</p>${D.session ? `<p class="small muted">Ultima seduta elaborata: ${esc(dayIT(D.session))}. Gli eventi sotto valgono per quella seduta.</p>` : ""}`;
  const chain = D.diaries.map(c => `<span class="br-d ${c.state === "registrata" ? "ok" : "no"}" title="${esc(c.next || "")}">${esc(c.name)}: ${esc(c.state)}${c.lastSession && c.state !== "registrata" ? ` (ultima ${esc(dayIT(c.lastSession))})` : ""}</span>`).join("");
  const events = D.events.length ? `<ul class="al-list br-list">${D.events.map(brCardHTML).join("")}</ul>${A.more ? `<p class="small">Altri ${A.more} cambiamenti importanti in <button class="btn ghost" data-algo="alerts">Alert e cambiamenti</button></p>` : ""}` : "";
  const hist = D.historical.length ? `<div class="card"><details class="fold" data-k="br-hist"><summary><h3>Eventi storici rilevati all'attivazione</h3><span class="card-meta">${A.historicalAtActivation} · non sono cambiamenti dell'ultima seduta</span></summary>
      <p class="small muted">Il primo controllo degli alert confronta due sedute già registrate: ciò che trova è un evento storico rilevato all'attivazione del registro, non una novità di oggi.</p>
      <ul class="al-list br-list">${D.historical.map(brCardHTML).join("")}</ul>${D.historicalMore ? `<p class="small">e altri ${D.historicalMore}</p>` : ""}</details></div>` : "";
  const issues = D.dataIssues.length ? `<div class="card"><details class="fold" data-k="br-data"><summary><h3>Problemi di dati e aggiornamento</h3><span class="card-meta">${D.dataIssues.length + D.dataIssuesMore} · separati dagli eventi finanziari</span></summary>
      <ul class="why small">${D.dataIssues.map(c => `<li><b>${esc(c.name || c.instrument)}</b> — ${esc(c.what || "")}: ${esc(c.why || "")}</li>`).join("")}</ul>${D.dataIssuesMore ? `<p class="small">e altri ${D.dataIssuesMore}</p>` : ""}</details></div>` : "";
  const job = H.lastJobCompleted;
  const started = H.lastJobStarted;
  const li = (l, v) => `<li><b>${l}</b>: ${v}</li>`;
  const health = `<div class="card"><details class="fold" data-k="br-health"><summary><h3>Stato del sistema</h3><span class="card-meta">${H.errors.length ? `${H.errors.length} problemi recenti` : "nessun problema recente"}</span></summary>
    <ul class="why small">
      ${li("Ultimo job completato", job ? `${esc(job.mode)}, finito ${tsIT(job.finishedAt)} (seduta ${esc(job.session ? dayIT(job.session) : "n.d.")})${job.stepsWithErrors.length ? ` · passi con errori: ${esc(job.stepsWithErrors.join(", "))}` : ""}` : esc(H.jobNote || "nessuno"))}
      ${started && !started.completed ? li("Ultimo job avviato", `${esc(started.mode)}, ${tsIT(started.startedAt)}: ${esc(started.state)}`) : ""}
      ${li("Programmazione", esc(H.scheduler || "n.d."))}
      ${li("Ultima seduta elaborata", esc(H.lastSession ? dayIT(H.lastSession) : "nessuna"))}
      ${li("Ultimo aggiornamento dei prezzi", tsIT(H.prices))} ${li("Ultimo aggiornamento dei bilanci", tsIT(H.fundamentals))} ${li("Ultimi prezzi ETF", tsIT(H.etfPrices))}
      ${li("Ultime registrazioni dei diari", H.diaries.map(d => `${esc(d.name)} ${esc(d.lastSession ? dayIT(d.lastSession) : "nessuna")}${d.lastComputedAt ? ` (${tsIT(d.lastComputedAt)}, ${esc(d.lastSource || "")})` : ""} — ${d.official.observations ?? 0} osservazioni registrate, ${d.admissible.observations} ammissibili`).join("<br>"))}
      ${li("Ultimo controllo degli alert", `${tsIT(H.alertCheck.lastRun)}${H.alertCheck.serverMsg ? ` · ultimo tentativo del server ${tsIT(H.alertCheck.server)}: ${esc(H.alertCheck.serverMsg)}` : ""}`)}
      ${li("Sedute mancanti", H.missing.length ? H.missing.map(m => `${esc(m.diary)}: ${esc(m.sessions.map(dayIT).join(", "))}`).join("; ") : "nessuna")}
      ${li("Registrazioni escluse (registro delle esclusioni)", H.excluded.length ? H.excluded.map(x => `${esc(x.diary)} ${esc(dayIT(x.session))} (${x.observations} osservazioni): ${esc(x.reason)}`).join("<br>") : "nessuna")}
      ${li("Errori recenti", H.errors.length ? H.errors.map(e => `${tsIT(e.at)} ${esc(e.mode || "")} · ${esc(e.step || "")}${e.error ? ` (${esc(e.error)})` : ""}${e.note ? `: ${esc(e.note)}` : ""}`).join("<br>") : "nessuno")}
      ${li("File aperti dal server", H.openFiles.open != null ? `${H.openFiles.open} su un limite di ${H.openFiles.limit ?? "n.d."} (${esc(H.openFiles.note)})` : (H.openFiles.limit == null && H.openFiles.note ? esc(H.openFiles.note) : "n.d."))}
    </ul><p class="small muted">Problemi operativi: non sono eventi finanziari. Un giorno è completo solo con tutti e cinque i diari registrati.</p></details></div>`;
  return `<div class="card"><h2>Riepilogo del giorno</h2>${status}
      <div class="br-chain">${chain}</div>
      <p class="small muted">${D.complete ? "Tutti e cinque i diari registrati per la seduta." : "Disponibilità parziale: non tutti i diari hanno la seduta."} Alert: ${A.newOfSession} nuovi nella seduta${A.historicalAtActivation ? `, ${A.historicalAtActivation} storici all'attivazione` : ""} · ultimo controllo ${tsIT(A.lastCheck)}.</p>
      ${events}
      <p class="small muted">${esc(D.rules.priorities)}. ${esc(D.disclaimer)}</p></div>${hist}${issues}${health}`;
}
function renderBrief() {
  const el = $("#briefBody");
  if (!el || state.view !== "brief") return;
  const keep = [...el.querySelectorAll("details.fold[data-k]")].filter(d => d.open).map(d => d.dataset.k);
  el.innerHTML = briefHTML();
  keep.forEach(k => { const d = el.querySelector(`details.fold[data-k="${k}"]`); if (d) d.open = true; });
}
document.addEventListener("click", e => {
  if (state.view !== "brief") return;
  const g = e.target.closest("[data-algo]");
  if (g) { if (g.dataset.algo === "stock") openDetail(g.dataset.t); else setView(g.dataset.algo); }
});

const GROUPS = [
  { id: "opportunita", label: "Opportunità", ask: "Quali titoli meritano di essere approfonditi?", views: [["opps", "Opportunità"]] },
  { id: "mercato", label: "Mercato", ask: "Cosa sta succedendo?", views: [["overview", "Oggi"], ["sectors", "Settori"]] },
  { id: "portafoglio", label: "Portafoglio", ask: "Cosa ho e come sta andando?", views: [["portfolio", "Posizioni"], ["pfperf", "Performance"], ["pfconc", "Concentrazione"], ["pfrisk", "Rischio"], ["pffit", "Compatibilità"]] },
  { id: "azioni", label: "Azioni", ask: "Quali azioni del Nasdaq-100 potrei comprare?", views: [["screener", "Screener"], ["watch", "Preferiti"], ["diary", "Diario dei segnali"]] },
  { id: "etf", label: "ETF", ask: "Quali ETF potrei comprare?", views: [["etf", "ETF"]] },
  { id: "alert", label: "Alert", ask: "Cosa è cambiato dall'ultima osservazione?", views: [["brief", "Riepilogo del giorno"], ["alerts", "Alert e cambiamenti"]] },
];
const PF_SUBS = ["portfolio", "pfperf", "pfconc", "pfrisk", "pffit"];
const OLD_LINKS = { map: "sectors", ideas: "sectors", trade: "screener", rules: "portfolio", metodo: "screener", ricerca: "screener" };
const diaryReady = () => (state.snap?.diaryDays || 0) >= DIARY_READY;
const VIEWS = GROUPS.flatMap(g => g.views.map(v => v[0]));
const groupOf = v => GROUPS.find(g => g.views.some(x => x[0] === v));
const shownViews = g => g.views.filter(([id]) => id !== "diary" || diaryReady());
// "#mercato", "#portafoglio", "#ricerca" open the tab (on the sub-tab used last); old links go to the nearest page
const viewFromHash = h => {
  if (OLD_LINKS[h]) return OLD_LINKS[h];
  if (h === "diary") return diaryReady() ? "diary" : "screener";
  if (VIEWS.includes(h)) return h;
  const g = GROUPS.find(x => x.id === h);
  return g ? lastSub(g) : null;
};
// Phase 6C: on a narrow phone the tab row scrolls sideways (never the page): the active tab is brought into view.
function keepTabVisible() {
  const tl = $(".tablist"), at = $(".tab.active");
  if (!tl || !at || tl.scrollWidth <= tl.clientWidth) return;
  const left = at.offsetLeft - tl.offsetLeft, right = left + at.offsetWidth;
  if (left < tl.scrollLeft || right > tl.scrollLeft + tl.clientWidth) tl.scrollLeft = Math.max(0, left - (tl.clientWidth - at.offsetWidth) / 2);
}
function lastSub(g) { const v = LS.get("sub." + g.id, g.views[0][0]); return shownViews(g).some(x => x[0] === v) ? v : g.views[0][0]; }
function setView(v) {
  if (!VIEWS.includes(v) || (v === "diary" && !diaryReady())) v = viewFromHash(v) || "opps";
  const g = groupOf(v);
  if (v === "overview" && state.view !== "overview") closeFolds();      // Mercato always opens with both accordions closed
  state.view = v; LS.set("view", v); LS.set("sub." + g.id, v);
  unpinTip();
  if (location.hash.slice(1) !== v) history.replaceState(null, "", "#" + v);
  $$(".tab").forEach(t => t.classList.toggle("active", t.dataset.main === g.id));
  keepTabVisible();
  const sub = $("#subtabs");
  const subs = shownViews(g);
  sub.hidden = subs.length < 2;
  sub.innerHTML = `<span class="sub-ask">${esc(g.ask)}</span>` + subs.map(([id, label]) => `<button class="subtab ${id === v ? "active" : ""}" data-view="${id}">${esc(label)}</button>`).join("");
  const section = PF_SUBS.includes(v) ? "portfolio" : v;          // the portfolio sub-pages share one section
  $$(".view").forEach(el => el.hidden = !state.snap || el.id !== "view-" + section);
  $$("[data-pfsub]").forEach(el => el.hidden = el.dataset.pfsub !== v);
  setStickyTop();
  if (state.snap) renderAll();
  window.scrollTo({ top: 0 });
}
$$(".tab").forEach(t => t.addEventListener("click", () => setView(lastSub(GROUPS.find(g => g.id === t.dataset.main)))));
// phase O2: a link changed without reloading (only the part after #, e.g. typed in the address bar or the browser's
// back button) opens that page too; the page itself writes the hash with replaceState, which fires no event
addEventListener("hashchange", () => {
  if (!state.snap) return;
  const h = decodeURIComponent(location.hash.slice(1));
  const v = viewFromHash(h);
  if (v) { if (v !== state.view) setView(v); return; }
  if (h && quoteFor(h.toUpperCase())) openDetail(h.toUpperCase());
});
$("#subtabs").addEventListener("click", e => { const b = e.target.closest("[data-view]"); if (b) setView(b.dataset.view); });
document.addEventListener("click", e => { const b = e.target.closest("[data-goto]"); if (b) setView(b.dataset.goto); });

function applyTheme(th) {
  if (th) document.documentElement.dataset.theme = th; else delete document.documentElement.dataset.theme;
}
applyTheme(LS.get("theme", null));
$("#themeBtn").addEventListener("click", () => {
  const cur = document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  const next = cur === "dark" ? "light" : "dark";
  applyTheme(next); LS.set("theme", next);
  if (state.snap) renderAll();
  if (state.detail) loadDetailChart();
});

// page-level sticky table headers sit just below the header + tabs (both sticky only on wide screens)
function setStickyTop() {
  const tabs = $(".tabs"), st = getComputedStyle(tabs);
  document.documentElement.style.setProperty("--sticky-top", st.position === "sticky" ? parseFloat(st.top) + tabs.offsetHeight + "px" : "0px");
}
setStickyTop();
let rz;
addEventListener("resize", () => { clearTimeout(rz); rz = setTimeout(() => { setStickyTop(); if (state.snap) renderAll(); if (state.detail) loadDetailChart(); }, 150); });

// ------------------------------------------------------------ boot
(async function boot() {
  for (let attempt = 0; ; attempt++) {
    try { await load(); break; }
    catch (e) {
      $("#loading p").textContent = attempt > 2 ? `Caricamento ancora in corso… (${e.message})` : "Caricamento dati di mercato…";
      await new Promise(r => setTimeout(r, 3000));
    }
  }
  nextAt = Date.now() + refreshMs();
  await loadWatch();
  const h = decodeURIComponent(location.hash.slice(1));
  setView(viewFromHash(h) || "opps");               // without a link the dashboard opens on Opportunità (phase O1; before: Portafoglio)
  if (h && !viewFromHash(h) && quoteFor(h.toUpperCase())) openDetail(h.toUpperCase());
})();
})();
