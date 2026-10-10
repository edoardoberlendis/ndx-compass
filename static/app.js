/* Nasdaq-100 Monitor — frontend */
(() => {
"use strict";

// ------------------------------------------------------------ state
const LS = {
  get(k, d) { try { const v = localStorage.getItem("ndx." + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem("ndx." + k, JSON.stringify(v)); } catch { /* storage unavailable */ } },
};

const state = {
  snap: null,
  bySym: new Map(),
  view: "portfolio",      // the tab opened at start (a link like #screener or #metodo overrides it, see boot)
  tf: LS.get("tf", "1D"),
  size: "mcap",   // map tiles sized by market cap
  cvd: false,
  zoom: null,
  cols: LS.get("cols", "overview"),
  preset: "all",
  sector: "",
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
const fPct = (v, d = 2) => !isNum(v) ? "—" : zero(v, d) ? "0%" : (v > 0 ? "+" : "") + fNum(v, d) + "%";
const fNum = (v, d = 2) => isNum(v) ? v.toLocaleString("it-IT", { minimumFractionDigits: d, maximumFractionDigits: d }) : "—";
const fPrice = v => isNum(v) ? fNum(v, v >= 1000 ? 2 : 2) : "—";
const fChg = v => !isNum(v) ? "—" : zero(v, 2) ? "0" : (v > 0 ? "+" : "") + fNum(v, 2);
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
function tileColors() {
  return state.cvd
    ? { neg: "#c8561f", mid: "#45454a", pos: "#2a6fc9", na: "#333" }
    : { neg: "#d6393b", mid: "#45454a", pos: "#1f9d55", na: "#333" };
}
function colorFor(tf) {
  const m = METRICS[tf], c = tileColors();
  const range = m.kind === "seq" ? ["#2f2f33", c.mid, c.pos === "#1f9d55" ? "#2a6fc9" : "#2a6fc9"] : [c.neg, c.mid, c.pos];
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
async function load() {
  const r = await fetch("/api/snapshot", { cache: "no-store" });
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
  if (state.view === "overview") renderOverview();
  if (state.view === "watch") renderMyStocks();
  if (PF_SUBS.includes(state.view)) loadPortfolio();
  if (state.view === "screener") renderScreener();
  if (state.view === "sectors") renderSectors();
  if (state.view === "sectors") loadRotation();
  if (state.view === "diary") loadDiary();
  if (state.view === "etf" || state.view === "watch") loadEtf();
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
    html += `<div class="sector-box" style="left:${sec.x0}px;top:${sec.y0}px;width:${w}px;height:${h}px">
      <div class="sector-h" data-sector="${esc(sec.data.name)}" title="Ingrandisci ${esc(sec.data.name)}">${esc(sec.data.name)}${agg && w > 110 ? `<span class="sv">${fMetric(tf, agg[tf])}</span>` : ""}</div></div>`;
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
  watch: "Solo i titoli che hai segnato con ★ (gli stessi di Ricerca → In osservazione).",
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

// earnings of the next 7 days; my stocks first
// Earnings of the next 7 days: one compact line per company, details on click (estimates, last report, usual move).
// Details come from /api/earnings (earnings.py); a missing figure is simply not shown.
const earn = { data: {}, at: 0, open: new Set() };
const EARN_MOVE_INFO = `Quanto si è mosso in media il titolo, in più o in meno, nel giorno di reazione alle ultime trimestrali (la seduta stessa se i conti escono prima dell'apertura,
  quella dopo se escono dopo la chiusura), calcolato dai prezzi giornalieri. <b>Indica quanto si rischia tenendo il titolo durante i conti</b>, non in che direzione andrà.`;
async function loadEarnDetails() {
  if (Date.now() - earn.at < 60_000) return;
  earn.at = Date.now();
  try {
    const d = await getJSON("/api/earnings");
    earn.data = d.data || {};
    if (d.loading) { earn.at = 0; setTimeout(loadEarnDetails, 4000); }
  } catch { return; }
  if (state.view === "overview") renderEarnings();
}
function earnWhen(ts) {          // Yahoo gives a time only when the company announced it
  const h = +new Date(ts * 1000).toLocaleString("en-US", { timeZone: tz, hour: "numeric", hour12: false });
  return h > 0 && h < 12 ? "prima dell'apertura" : h >= 16 ? "dopo la chiusura" : "";
}
function renderEarnings() {
  loadEarnDetails();
  const mine = s => state.watch.has(s.ticker) ? 1 : 0;
  const list = stocks().filter(s => { const d = daysTo(s.earningsTs); return d != null && d <= 7; })
    .sort((a, b) => mine(b) - mine(a) || a.earningsTs - b.earningsTs);
  const el = $("#earnings");
  if (!list.length) { el.innerHTML = `<div class="empty">Nessuna trimestrale nei prossimi 7 giorni</div>`; return; }
  const num = (v, d = 2) => isNum(v) ? fNum(v, d) : null;
  el.innerHTML = list.map(s => {
    const d = Math.round(daysTo(s.earningsTs)), E = earn.data[s.ticker] || {}, L = E.last, when = earnWhen(s.earningsTs);
    const det = [
      isNum(E.epsExpected) ? `<div><span>Utile per azione atteso</span><b>${num(E.epsExpected)} $</b>${E.epsAnalysts ? ` <span class="muted">(${E.epsAnalysts} analisti)</span>` : ""}</div>` : "",
      isNum(E.revExpected) ? `<div><span>Ricavi attesi</span><b>$${fBig(E.revExpected)}</b>${E.revAnalysts ? ` <span class="muted">(${E.revAnalysts} analisti)</span>` : ""}</div>` : "",
      L && isNum(L.reported) ? `<div><span>Ultima trimestrale (${dayShort(L.ts.slice(0, 10))})</span><b>${isNum(L.eps) ? `attesi ${num(L.eps)} $, ` : ""}effettivi ${num(L.reported)} $</b>${isNum(L.surprise) ? ` <span class="${sign(L.surprise)}">sorpresa ${fPct(L.surprise, 1)}</span>` : ""}</div>` : "",
      E.moves?.length ? `<div><span>Movimenti dopo le ultime trimestrali</span><b>${E.moves.map(m => `<span class="${sign(m.move)}">${fPct(m.move, 1)}</span>`).join(" ")}</b></div>` : "",
    ].filter(Boolean).join("");
    const open = earn.open.has(s.ticker) && det;
    return `<div class="earn-it ${open ? "open" : ""}"><button class="earn-row" data-earn="${esc(s.ticker)}" ${det ? "" : "disabled"}>
        <span class="t">${mine(s) ? '<span class="mine" title="Tra i miei titoli">★</span> ' : ""}${esc(s.ticker)}</span><span class="n">${esc(s.name)}</span>
        <span class="r num">${fDate(s.earningsTs, { weekday: "short", month: "short", day: "numeric" })}${when ? ` · <span class="muted">${when}</span>` : ""}</span>
        <span class="r muted num">${d <= 0 ? "oggi" : "tra " + d + " g"}</span>
        <span class="r num">${isNum(E.usualMove) ? `di solito ±${fNum(E.usualMove, 0)}%` : ""}</span></button>
      ${open ? `<div class="earn-det">${det}<p class="muted small">«Di solito ±${fNum(E.usualMove ?? 0, 0)}%» ${info(EARN_MOVE_INFO)} · dati Yahoo Finance</p></div>` : ""}</div>`;
  }).join("");
}
document.addEventListener("click", e => {
  const b = e.target.closest("[data-earn]");
  if (!b || e.target.closest(".info")) return;
  const t = b.dataset.earn;
  earn.open.has(t) ? earn.open.delete(t) : earn.open.add(t);
  renderEarnings();
});

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
// the card stays short (title, date, time, value); everything else is in the side panel (openMacro)
function macroItem(e, rate, k) {
  const w = macroWhen(e);
  return `<div class="mc-it">
    <div class="mc-h"><button class="mc-open" data-macro="${k}"><b>${esc(macroTitle(e))}</b></button><button class="link-btn" data-macro="${k}">Dettagli →</button></div>
    <div class="mc-when">${esc(w.day)} · ${w.ny} di New York (${w.local} ora locale)</div>
    <div class="mc-val">${macroValues(e, rate)}</div></div>`;
}
let macroAt = 0, macroData = null;
async function loadMacro() {
  if (Date.now() - macroAt < 5 * 60_000) return;
  macroAt = Date.now();
  let d;
  try { d = await getJSON("/api/macro"); } catch { macroAt = 0; $("#macro").innerHTML = `<div class="empty">Eventi non disponibili</div>`; return; }
  macroData = d;
  $("#macro").innerHTML = d.events.length ? d.events.map((e, k) => macroItem(e, d.rate, k)).join("") : `<div class="empty">Nessun evento nei prossimi 7 giorni</div>`;
}
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
let whyLoadedAt = 0, whyData = null;
function renderWhy() {
  if (!whyData) return;
  $("#whyNewsOpts").innerHTML = newsOpts();
  $("#whyTop").innerHTML = whyData.top.map(whyItem).join("") || `<div class="empty">Nessun dato</div>`;
  $("#whyFlop").innerHTML = whyData.flop.map(whyItem).join("") || `<div class="empty">Nessun dato</div>`;
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
function whyItem(x) {
  const toneCls = x.tone > 0 ? "pos" : x.tone < 0 ? "neg" : "";
  const tags = x.reasons.map(r => `<span class="${toneCls}">${esc(r)}</span>`).join("")
    + (isNum(x.sectorChg) ? `<span class="sec">${esc(x.sector)} ${fPct(x.sectorChg)}</span>` : "");
  const n = x.news;
  // with opinions hidden the reason stays, but the article it came from is not shown
  const news = !n ? "" : state.hideOpinion && newsKind(n) === "opinion"
    ? `<div class="nm">Motivo ricavato da un articolo d'opinione (nascosto)</div>`
    : `<a class="mv-news" href="${esc(n.url)}" target="_blank" rel="noopener">${esc(n.title)} ↗</a>
      ${n.clause ? `<div class="mv-cl">“${esc(n.clause)}”</div>` : ""}
      <div class="nm">${newsTag(n)} ${esc(n.publisher || "")} · ${esc(ago(n.time))}</div>`;
  return `<div class="mv-it"><div class="mv-h"><b data-open="${esc(x.ticker)}">${esc(x.ticker)}</b><span class="n">${esc(x.name || "")}</span>${pill(x.chgPct)}</div>
    ${tags ? `<div class="mv-tags">${tags}</div>` : ""}<div class="mv-sum">${esc(x.summary)}</div>${news}</div>`;
}
$(".mv-cols").addEventListener("click", e => { const b = e.target.closest("[data-open]"); if (b) openDetail(b.dataset.open); });

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
  $("#myTbl").innerHTML = `<thead><tr>${MY_COLS.map(k => `<th class="${C[k].cls?.split(" ")[0] || ""} ${state.mySort.key === k ? "sorted" + (state.mySort.dir > 0 ? " asc" : "") : ""}" data-k="${k}">${colHead(k)}</th>`).join("")}</tr></thead>
    <tbody>${rows.map(s => `<tr data-t="${esc(s.ticker)}">${MY_COLS.map(k => `<td class="${C[k].cls || ""}">${C[k].html(s)}</td>`).join("")}</tr>`).join("")
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
const pfName = x => `<b>${esc(x.name)}</b>${x.leverage > 1 ? ` <span class="lev-badge">leva ${x.leverage}x</span> ${info(LEV_INFO(x.leverage))}` : ""}
  <div class="muted small">${esc(x.ticker || x.symbol)} · ${esc(x.kind)} · ${esc(x.currency)}</div>`;
// Nasdaq-100 data the dashboard already has (same renderers as the Screener); "—" for the other positions
const ndxCol = (k, l) => ({ k, l, i: COL_INFO[k], sort: x => { const s = state.bySym.get(x.ticker); return s ? C[k].sort(s) : null; },
  html: x => { const s = state.bySym.get(x.ticker); return s ? C[k].html(s) : `<span class="muted">—</span>`; } });
const PF_DASH = () => [
  { k: "name", l: "Titolo", cls: "l", sort: x => x.name, html: pfName },
  { k: "value", l: "Valore", sort: x => x.value, html: x => fEur(x.value) },
  { k: "weight", l: "Peso", sort: x => x.weight, html: x => isNum(x.weight) ? fNum(x.weight, 1) + "%" : "—" },
  { k: "action", l: "Azione", cls: "l", i: "Azione proposta dalle regole (clicca per la tesi e i motivi). Regole di disciplina, non verificate da backtest.", sort: x => ({ "Rivedi la tesi": 2, "Accumula": 1 }[x.action?.action] || 0),
    html: x => x.action ? `<button class="act-btn" data-pos="${esc(x.isin)}" title="${esc(x.action.reasons.join(" · ") || "Nessuna regola scattata")}">${actBadge(x.action)}${x.action.silenced ? ` <span class="muted small">rivista</span>` : ""}${x.thesis ? "" : ` <span class="muted small">senza tesi</span>`}</button>` : "—" },
  { ...ndxCol("trend", "Trend"), cls: "" }, { ...ndxCol("signal", "Segnale"), cls: "l" }, { ...ndxCol("valLabel", "Valutazione"), cls: "l" },
  { ...ndxCol("upside", "Potenziale analisti"), cls: "" }, { ...ndxCol("earnings", "Prossima trimestrale"), cls: "l" },
];
const PF_COLS = [
  { k: "name", l: "Titolo", cls: "l", sort: x => x.name, html: pfName },
  { k: "qty", l: "Quantità", sort: x => x.qty, html: x => fNum(x.qty, x.qty % 1 ? 2 : 0) },
  { k: "costPrice", l: "Prezzo di carico", sort: x => x.costPrice, html: x => fPrice(x.costPrice) },
  { k: "price", l: "Prezzo", sort: x => x.price, html: x => `${fPrice(x.price)}${x.live ? "" : ` <span class="muted small" title="Ticker non trovato: prezzo del file">(file)</span>`}` },
  { k: "value", l: "Valore", sort: x => x.value, html: x => fEur(x.value) },
  { k: "pnl", l: "Guadagno / perdita", sort: x => x.pnl, html: x => `<span class="${sign(x.pnl)}">${fEurS(x.pnl)}</span>` },
  { k: "pnlPct", l: "%", sort: x => x.pnlPct, html: x => `<span class="${sign(x.pnlPct)}">${fPct(x.pnlPct, 1)}</span>` },
  { k: "fxEffect", l: "Di cui cambio", i: FX_INFO, sort: x => x.fxEffect, html: x => x.currency === "EUR" ? `<span class="muted">—</span>` : `<span class="${sign(x.fxEffect)}">${fEurS(x.fxEffect)}</span>` },
  { k: "today", l: "Oggi", i: "Variazione di oggi in euro, dovuta al prezzo (rispetto alla chiusura precedente della sua borsa).", sort: x => x.today, html: x => `<span class="${sign(x.today)}">${fEurS(x.today)}</span>` },
  { k: "weight", l: "Peso", i: "Quota del valore totale del portafoglio.", sort: x => x.weight, html: x => isNum(x.weight) ? fNum(x.weight, 1) + "%" : "—" },
  { k: "action", l: "Azione", cls: "l", i: "Azione proposta dalle regole (clicca per la tesi e i motivi). Regole di disciplina, non verificate da backtest.", sort: x => ({ "Rivedi la tesi": 2, "Accumula": 1 }[x.action?.action] || 0),
    html: x => x.action ? `<button class="act-btn" data-pos="${esc(x.isin)}" title="${esc(x.action.reasons.join(" · ") || "Nessuna regola scattata")}">${actBadge(x.action)}${x.action.silenced ? ` <span class="muted small">rivista</span>` : ""}${x.thesis ? "" : ` <span class="muted small">senza tesi</span>`}</button>` : "—" },
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
  $("#pfWarn").hidden = !D.warnings.length;
  $("#pfWarn").innerHTML = D.warnings.map(w => `<div>⚠ ${esc(w)}</div>`).join("")
    + (D.warnings.length ? `<div class="muted small">Puoi indicare il ticker giusto in <code>portafoglio/ticker.json</code>, per esempio {"ISIN": "TICKER.MI"}.</div>` : "");
  const COLS = pf.cols === "dash" ? PF_DASH() : PF_COLS;
  $$("#pfColSeg button").forEach(b => b.classList.toggle("on", b.dataset.cols === pf.cols));
  const col = COLS.find(c => c.k === pf.sort.key) || COLS.find(c => c.k === "value");
  // leveraged products: how much of the value, and of the effective exposure, they are
  const lev = D.positions.filter(x => x.leverage > 1);
  $("#pfLev").hidden = !lev.length;
  if (lev.length) {
    const v = d3.sum(lev, x => x.value), e = d3.sum(lev, x => x.exposure);
    $("#pfLev").innerHTML = `⚠ <b>${lev.length === 1 ? "1 prodotto a leva" : `${lev.length} prodotti a leva`}</b> (${lev.map(x => esc(x.ticker || x.symbol)).join(", ")}):
      ${fNum(v / T.value * 100, 1)}% del valore, ma <b>${fNum(e / T.exposure * 100, 1)}% dell'esposizione effettiva</b>. ${info(LEV_INFO(lev[0].leverage))}`;
  }
  const rows = [...D.positions].sort((a, b) => {
    const va = col.sort(a), vb = col.sort(b);
    if (va == null) return 1; if (vb == null) return -1;
    return (typeof va === "string" ? va.localeCompare(vb) : va - vb) * pf.sort.dir;
  });
  $("#pfCount").textContent = `${rows.length} posizioni`;
  $("#pfTbl").innerHTML = `<thead><tr>${COLS.map(c => `<th class="${c.cls || ""} ${pf.sort.key === c.k ? "sorted" + (pf.sort.dir > 0 ? " asc" : "") : ""}" data-k="${c.k}">${esc(c.l)}${c.i ? " " + info(c.i) : ""}</th>`).join("")}</tr></thead>
    <tbody>${rows.map(x => `<tr data-t="${esc(x.ticker || "")}" class="${x.leverage > 1 ? "lev" : ""}">${COLS.map(c => `<td class="${c.cls || ""}">${c.html(x)}</td>`).join("")}</tr>`).join("")}</tbody>`;
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
  $("#pfConc").innerHTML = `<thead><tr><th class="l">${DIM_LAB[pf.dim]}</th><th>Valore investito</th><th>%</th><th>Esposizione effettiva</th><th>%</th><th class="l">confronto</th></tr></thead>
    <tbody>${rows.map(r => `<tr><td class="l"><b>${esc(r.name)}</b></td><td>${fEur(r.value, 0)}</td><td>${fNum(r.pct, 1)}%</td>
      <td>${fEur(r.exposure, 0)}</td><td><b>${fNum(r.expPct, 1)}%</b></td>
      <td class="l"><span class="cbar"><i class="v" style="width:${(r.pct / maxPct * 100).toFixed(1)}%"></i><i class="e" style="width:${(r.expPct / maxPct * 100).toFixed(1)}%"></i></span></td></tr>`).join("")}</tbody>`;
  const notes = {
    sector: "Azioni del Nasdaq-100: settore usato dalla dashboard. Altre azioni: settore di Yahoo. ETF ed ETC: portafoglio/classificazione.json (il Nasdaq-100 3x è diviso come i settori dell'indice).",
    theme: "Azioni: temi di themes.json (un titolo in due temi conta metà in ciascuno) oppure la sezione _azioni di portafoglio/classificazione.json. ETF ed ETC: stesso file.",
    country: "Azioni: paese della società secondo Yahoo (corretto in portafoglio/classificazione.json se serve). ETF ed ETC: area a cui sono esposti, non la sede del fondo; «Mondo» non è diviso per paese.",
  };
  $("#pfConcNote").innerHTML = `${notes[pf.dim]} Barra chiara = valore investito, barra scura = esposizione effettiva.`;
}
// ---- thesis and proposed action of each position (actions.py, portafoglio/tesi.json)
const ACT_CLS = { "Rivedi la tesi": "rev", "Accumula": "acc", "Mantieni": "hold" };
const actBadge = a => `<span class="act ${ACT_CLS[a.action] || "hold"}">${esc(a.label || a.action)}</span>`;   // label: "Rivedi · target raggiunto"
const TAX_NOTE = "Stima indicativa, non è una consulenza fiscale: non conta commissioni, minusvalenze che hai già, né casi particolari.";
const actTax = a => a.tax ? `<span class="act-tax">Effetto fiscale stimato: ${esc(a.tax.text)}. ${info(`<b>Effetto fiscale stimato.</b> Guadagno o perdita in euro sulla parte da vendere, in proporzione al «Valore di carico» di Fineco, con l'imposta indicativa del 26%.<br><br>
  <b>Azioni ed ETC/ETN</b>: guadagni e perdite sono «redditi diversi» e si compensano tra loro (le perdite valgono per i 4 anni successivi).<br>
  <b>ETF UCITS</b>: i guadagni sono «redditi di capitale», tassati al 26% senza poterli compensare con le perdite; le perdite sono «redditi diversi».<br><br>${TAX_NOTE}`)}</span>` : "";
const ACT_INFO = `Per ogni posizione la dashboard propone <b>Mantieni</b>, <b>Accumula</b> o <b>Rivedi la tesi</b> con regole esplicite: accanto vedi quali sono scattate e con quali numeri.
  Rivedi la tesi vince su Accumula.<br><br>Sono <b>regole di disciplina scelte da te, non verificate da un backtest</b>: servono a non dimenticare le cose da controllare,
  non dicono cosa farà il prezzo. «Accumula» scatta solo se hai scritto un peso obiettivo nella tesi.`;
// panel of one position: thesis to write or edit, proposed action and the full list of rules
function openPosition(isin) {
  const p = pf.data?.positions?.find(x => x.isin === isin);
  if (!p || !p.action) return;
  const th = p.thesis || {}, A = p.action;
  state.detail = null; state.macro = null; state.panel = "position"; pf.openPos = isin;
  const icon = { on: "✅", off: "—", na: "·" };
  const num = (k, label, hint) => `<label><span>${label}</span><input type="number" step="any" min="0" data-th="${k}" value="${isNum(th[k]) ? th[k] : ""}" placeholder="facoltativo"><span class="muted small">${hint}</span></label>`;
  const txt = (k, label, ph) => `<label class="th-txt"><span>${label}</span><textarea data-th="${k}" rows="3" maxlength="2000" placeholder="${ph}">${esc(th[k] || "")}</textarea></label>`;
  const groups = ["Rivedi la tesi", "Accumula"];
  drawer.classList.remove("full");
  drawer.innerHTML = `<div class="d-top"><div class="d-head"><div><div class="tt">${esc(p.ticker || p.symbol || p.name)}</div><div class="nm">${esc(p.name)} · ${fNum(p.weight, 1)}% del portafoglio</div></div>
      <div class="actions"><button class="icon-btn close-btn" id="dClose" aria-label="Chiudi">×</button></div></div></div>
    <div class="d-rest pos-d">
      <div class="d-sec"><h3>Azione proposta ${info(ACT_INFO)}</h3><p>${actBadge(A)}</p>
        ${A.reasons.length ? `<ul class="why">${A.reasons.map(r => `<li>${esc(r)}</li>`).join("")}</ul>` : `<p class="muted">${A.silenced ? "Motivi già rivisti da te (vedi sotto)." : "Nessuna regola scattata."}</p>`}
        ${A.tax ? `<p class="small">${actTax(A)}<br><span class="muted">${TAX_NOTE}</span></p>` : ""}
        ${A.silenced ? `<div class="rev-box"><b>Tesi rivista il ${dayIT(A.silenced.date)}</b>: «${esc(A.silenced.note)}»<br><span class="muted small">Motivi silenziati ancora per ${A.silenced.until} ${A.silenced.until === 1 ? "giorno" : "giorni"}, a meno che non ne scatti uno nuovo: ${A.silenced.rules.map(esc).join(" · ")}.</span></div>` : ""}
        ${A.canReview ? `<div class="rev-box"><label><b>Ho rivisto la tesi</b> <span class="muted small">scrivi in una riga perché la tieni (o cosa hai deciso): i motivi «Rivedi» scattati restano silenziati per 30 giorni, a meno che non ne scatti uno nuovo.</span>
          <input type="text" id="revNote" maxlength="300" placeholder="Per esempio: il calo dipende dal settore, i conti restano solidi"></label>
          <div class="toolbar"><button class="btn" id="revSave">Ho rivisto la tesi</button><span id="revMsg" class="small"></span></div></div>` : ""}
        ${A.notes.length ? `<p class="muted small">${A.notes.map(esc).join("<br>")}</p>` : ""}</div>
      <div class="d-sec"><h3>La mia tesi</h3>
        <div class="th-form">${txt("why", "Perché la possiedo", "In una o due frasi")}${txt("expect", "Cosa mi aspetto", "Per esempio: crescita dei ricavi, nuovo prodotto, recupero dei margini…")}
          ${txt("sell", "Cosa mi farebbe vendere", "Per esempio: se i ricavi rallentano, se perde il contratto X, se scende sotto…")}
          <div class="th-nums">${num("stop", "Stop", `prezzo in ${esc(p.currency)} · ora ${fPrice(p.price)}`)}${num("target", "Target", `prezzo in ${esc(p.currency)}`)}${num("weight", "Peso obiettivo", `% del portafoglio · ora ${fNum(p.weight, 1)}%`)}</div></div>
        <div class="toolbar" style="margin-top:10px"><button class="btn primary" id="thSave">Salva la tesi</button><span id="thMsg" class="small muted">${th.updated ? `ultima modifica ${dayIT(th.updated)}` : "non ancora scritta"}</span></div></div>
      <div class="d-sec"><h3>Tutte le regole</h3>
        ${groups.map(g => `<h4 class="bt-h">${g}${g === "Accumula" ? " (devono valere tutte)" : ""}</h4><ul class="rule-list">${A.rules.filter(r => r.group === g).map(r =>
          `<li class="${r.state}"><span class="ri">${icon[r.state]}</span><span><b>${r.id}</b> ${esc(r.text)}<span class="muted small"> ${r.state === "na" ? "non valutabile: " : ""}${esc(r.detail)}</span></span></li>`).join("")}</ul>`).join("")}
        <p class="muted small">✅ scattata (per Accumula: soddisfatta) · — non scattata · “non valutabile” quando manca il dato. Regole di disciplina, non verificate da backtest.</p></div>
      ${p.ticker && state.bySym.has(p.ticker) ? `<button class="link-btn" data-mopen="${esc(p.ticker)}">Apri la scheda del titolo →</button>` : ""}
      <p class="disclaimer">Non è una consulenza finanziaria.</p></div>`;
  drawer.classList.add("open"); drawer.setAttribute("aria-hidden", "false"); scrim.hidden = false;
  $("#dClose").onclick = closeDetail;
  if ($("#revSave")) $("#revSave").onclick = async () => {
    const note = $("#revNote").value.trim();
    if (note.length < 3) { $("#revMsg").innerHTML = `<span class="down">Scrivi una riga di motivazione.</span>`; return; }
    try {
      await pfPost("/api/thesis/review", { body: JSON.stringify({ isin, note }), headers: { "Content-Type": "application/json" } });
      await loadPortfolio();
      openPosition(isin);
    } catch (e) { $("#revMsg").innerHTML = `<span class="down">Non salvato: ${esc(e.message)}</span>`; }
  };
  $("#thSave").onclick = async () => {
    const body = { isin };
    drawer.querySelectorAll("[data-th]").forEach(i => { const k = i.dataset.th; body[k] = i.tagName === "TEXTAREA" ? i.value : (i.value.trim() === "" ? null : parseFloat(i.value.replace(",", "."))); });
    if (["stop", "target", "weight"].some(k => body[k] !== null && !(body[k] > 0)) || body.weight > 100) { $("#thMsg").innerHTML = `<span class="down">Stop, target e peso obiettivo devono essere numeri positivi (il peso al massimo 100).</span>`; return; }
    try {
      await pfPost("/api/thesis", { body: JSON.stringify(body), headers: { "Content-Type": "application/json" } });
      await loadPortfolio();
      openPosition(isin);
      $("#thMsg").textContent = "✓ Tesi salvata";
    } catch (e) { $("#thMsg").innerHTML = `<span class="down">Non salvata: ${esc(e.message)}</span>`; }
  };
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
    <h4 class="bt-h">Valore nel tempo (€) <span class="muted" style="text-transform:none;letter-spacing:0">▲ soldi aggiunti · ▼ soldi tolti</span></h4><div id="pfPerfVal" class="chart"></div>
    <h4 class="bt-h">Rendimento dall'inizio del periodo (%)</h4>
    <div class="series-key">${series.map(([, l, c]) => `<span><i style="background:var(${c})"></i>${esc(l)}</span>`).join("")}</div><div id="pfPerfRet" class="chart"></div>
    <div class="table-wrap"><table class="scr"><thead><tr><th class="l">Dal ${dayIT(a.date)} al ${dayIT(z.date)}</th>${series.map(([, l]) => `<th>${esc(l)}</th>`).join("")}<th>Guadagno in euro</th><th>Soldi aggiunti (netti)</th></tr></thead>
      <tbody><tr><td class="l"><b>Rendimento</b> <span class="muted small">ponderato per il tempo</span></td>${series.map(([k]) => `<td><b>${pc(ret(k))}</b></td>`).join("")}
        <td><span class="${sign(gain)}">${fEurS(gain, 0)}</span></td><td>${fEurS(flows, 0)}</td></tr></tbody></table></div>
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
    <h4 class="bt-h">Contributo al rischio ${info(RISK_INFO.rc)} <span class="muted" style="text-transform:none;letter-spacing:0">chi pesa sul rischio più di quanto pesa in euro</span></h4>
    <div class="table-wrap"><table class="scr"><thead><tr><th class="l">Posizione</th><th>Peso in euro</th><th>Quota del rischio</th><th>Rapporto</th><th>Beta</th><th>Volatilità annua</th></tr></thead>
      <tbody>${D.positions.map(p => `<tr><td class="l"><b>${esc(p.name)}</b>${p.fullName !== p.name ? ` <span class="muted small">${esc(p.fullName)}</span>` : ""}</td>
        <td>${fNum(p.weight, 1)}%</td><td><b>${fNum(p.risk, 1)}%</b></td><td class="${p.flag ? "down" : ""}">${fNum(p.ratio, 1)}×${p.flag ? " ⚠" : ""}</td><td>${fNum(p.beta, 2)}</td><td>${fNum(p.vol, 0)}%</td></tr>`).join("")}</tbody></table></div>
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
// ---- zainetto fiscale (actions.py, portafoglio/fiscale.json): optional, used only by the indicative tax estimate
function renderTaxBox() {
  const el = $("#pfTax"), F = pf.data?.fiscal || {};
  if (!el || el.contains(document.activeElement) && document.activeElement.tagName === "INPUT") return;   // typing: do not redraw
  el.innerHTML = `<summary><span class="small"><b>Zainetto fiscale</b> (facoltativo) · ${F.losses ? `minusvalenze disponibili ${fEur(F.losses, 0)}${F.expiry ? `, scadenza più vicina ${dayIT(F.expiry)}` : ""}` : "non indicato"}</span></summary>
    <p class="small">Lo «zainetto» sono le minusvalenze (perdite realizzate) che puoi ancora usare per pagare meno imposte sulle plusvalenze di azioni, ETC e derivati, entro 4 anni.
      Lo trovi nel sito Fineco (area fiscale). Se lo indichi, la stima fiscale accanto a «Rivedi · target raggiunto» ne tiene conto per <b>azioni ed ETC</b>; per gli <b>ETF</b> no,
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
  star:   { l: "", cls: "l", sort: s => state.watch.has(s.ticker) ? 1 : 0, html: s => `<button class="star ${state.watch.has(s.ticker) ? "on" : ""}" data-star="${esc(s.ticker)}" aria-label="Preferito">${state.watch.has(s.ticker) ? "★" : "☆"}</button>` },
  ticker: { l: "Ticker", cls: "l tk", sort: s => s.ticker, html: s => esc(s.ticker) },
  name:   { l: "Società", cls: "l nm", sort: s => s.name, html: s => esc(s.name) },
  sector: { l: "Settore", cls: "l", sort: s => s.sector, html: s => esc(s.sector) },
  industry: { l: "Industria", cls: "l", sort: s => s.industry, html: s => esc(s.industry) },
  mcap:   { l: "Capitalizz.", sort: s => s.mcap, html: s => fBig(s.mcap) },
  weight: { l: "Peso", sort: s => s.weight, html: s => fW(s) },
  price:  { l: "Prezzo", sort: s => s.price, html: s => fPrice(s.price) },
  chgPct: { l: "Var.", sort: s => s.chgPct, html: s => `<span class="${sign(s.chgPct)}">${fPct(s.chgPct)}</span>` },
  volume: { l: "Volume", sort: s => s.volume, html: s => fBig(s.volume) },
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
  signal: { l: "Segnale", cls: "l", sort: s => s.sigScore, html: s => s.signal ? `${sigBadge(s.signal)}${isNum(s.sigScore) ? ` <span class="muted num">${fNum(s.sigScore, 0)}</span>` : ""}` : "—" },
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

function screenerRows() {
  const p = PRESETS.find(x => x.id === state.preset) || PRESETS[0];
  const q = $("#scrFind").value.trim().toLowerCase();
  const col = C[state.sort.key] || C.mcap;
  return stocks().filter(p.f)
    .filter(s => !state.sector || s.sector === state.sector)
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
  const chip = p => `<button data-p="${p.id}" class="${p.id === state.preset ? "on" : ""}">${esc(p.label)}<span>${S.filter(p.f).length}</span>${info(PRESET_INFO[p.id])}</button>`;
  $("#presets").innerHTML = PRESET_GROUPS.map(g => `<div class="chip-row"><span class="chip-g">${esc(g.label)}</span>${g.ids.map(id => chip(PRESETS.find(p => p.id === id))).join("")}</div>`).join("");
  const rows = screenerRows();
  const cols = COLSETS[state.cols];
  $("#scrCount").textContent = `${rows.length} di ${S.length}`;
  $("#scr").innerHTML = `<thead><tr>${cols.map(k => `<th class="${C[k].cls?.split(" ")[0] || ""} ${state.sort.key === k ? "sorted" + (state.sort.dir > 0 ? " asc" : "") : ""}" data-k="${k}">${colHead(k)}</th>`).join("")}</tr></thead>
    <tbody>${rows.map(s => `<tr data-t="${esc(s.ticker)}">${cols.map(k => `<td class="${C[k].cls || ""}">${C[k].html(s)}</td>`).join("")}</tr>`).join("")}</tbody>`;
  if (!rows.length) $("#scr").insertAdjacentHTML("beforeend", `<tbody><tr><td colspan="${cols.length}" class="empty">Nessun titolo corrisponde ai filtri</td></tr></tbody>`);
}
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
  const colors = Object.fromEntries(tfs.map(tf => [tf, colorFor(tf)]));
  const total = d3.sum(secs, s => s.weight) || 100;   // ≈ 100
  const maxW = d3.max(secs, s => s.weight / total);
  $("#matrix").innerHTML = `<thead><tr><th class="l">Settore</th><th>Titoli</th><th class="l">Peso</th>${tfs.map(tf => `<th>${METRICS[tf].label}</th>`).join("")}<th>Rialzo / Ribasso</th></tr></thead>
    <tbody>${secs.map(s => {
      const w = s.weight / total * 100;
      const adv = s.list.filter(x => x.chgPct > 0).length;
      return `<tr data-sec="${esc(s.name)}" class="${s.name === state.secSel ? "sel" : ""}"><td class="l"><b>${esc(s.name)}</b></td><td>${s.n}</td>
        <td class="l"><span class="wbar" style="width:${(w / (maxW * 100) * 90).toFixed(0)}px"></span>${fNum(w, 1)}%</td>
        ${tfs.map(tf => `<td class="heat" style="background:${colors[tf](s[tf])}">${fPct(s[tf])}</td>`).join("")}
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
      <div class="actions">${state.bySym.has(t) ? `<button class="icon-btn star ${state.watch.has(t) ? "on" : ""}" data-star="${esc(t)}" title="Preferiti">${state.watch.has(t) ? "★" : "☆"}</button>` : ""}
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
  "Rivedi la tesi": "rev", "Accumula": "acc", "Mantieni": "hold" };
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
      ${V.owned ? `<p class="small">Lo possiedi: il verdetto è l'azione proposta dalle regole sulle posizioni. <button class="link-btn" data-pos="${esc(V.isin)}">Apri tesi e regole della posizione →</button></p>` : ""}</div>
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
  an.copy = A.orders.map(o => [`${D.ticker} – ${o.type}${o.info ? " (pattern non verificato)" : ""}`, `Prezzo: ${fNum(o.price, 2)} $`, `Quantità: ${o.qty ?? "—"}`,
    `Stop loss: ${fNum(o.stopLoss, 2)} $`, `Take profit: ${fNum(o.takeProfit, 2)} $`, `Scadenza: ${o.expiry} (${o.expiryNote})`,
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
    (macroData ? Promise.resolve() : getJSON("/api/macro").then(d => { macroData = d; })).then(() => openMacro(macroData.events.find(x => x.kind === kind && x.date === day))).catch(() => {});
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
      ${stat("Flusso di cassa libero", "$" + fBig(i.freeCashflow))}${stat("ROE", pctOf(i.returnOnEquity))}
      ${stat("Utile per azione (12 mesi)", fNum(i.trailingEps, 2))}${stat("Utile per azione atteso", fNum(i.forwardEps, 2))}
      ${stat("Ricavi (12 mesi)", "$" + fBig(i.totalRevenue))}${stat("Rendimento dividendo", isNum(i.dividendYield) && i.dividendYield > 0 ? fNum(i.dividendYield, 2) + "%" : "—")}
    </div>`;
  // index stocks: the Trend block lives inside "Decisione" (block 3), not twice
  const hasTA = !!(s.ticker && data.decision);
  Object.assign(dTA, { t, ta: data.ta || null, D: hasTA ? data.decision : null, fx: data.fx, trend: trend.replace('<div class="d-sec"><h3>Trend</h3>', '<div>'), sel: {} });
  drawer.querySelector(".d-rest").innerHTML = `${hasTA ? `<div class="d-sec ta" id="dTA"></div>` : ""}<div class="d-cols">
      <div class="d-col">${hasTA ? "" : trend}${s.ticker ? valuationHTML(data.valuation, fundamentals) : ""}</div>
      <div class="d-col">${s.ticker ? analystsHTML(data.analysts, s, tgt) : ""}${newsSec}</div></div>${company}`;
  drawer.querySelector(".d-sum").innerHTML = signalHTML(data.signal);
  if (hasTA) { renderTA(); taEnsure(); }
  renderDetailNews();
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
function analystsHTML(a, s, tgt = "") {
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
  const cell = (o, big) => o ? `<td class="num">${big ? "$" + fBig(o.avg) : fNum(o.avg, 2)}</td><td class="num ${sign(o.growth)}">${isNum(o.growth) ? fPct(o.growth * 100, 1) : "—"}</td>` : "<td>—</td><td>—</td>";
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
  pts.filter(d => !opts.labels || opts.labels.has(d.name)).append("text").attr("class", "rrg-label").attr("x", d => x(d.rs1m) > iw - 120 ? -10 : 10).attr("text-anchor", d => x(d.rs1m) > iw - 120 ? "end" : "start").attr("y", 4).text(d => d.name);
  pts.on("mousemove", (ev, d) => showTip(tipFn(d), ev)).on("mouseleave", hideTip);
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
const etfS = { data: null, at: 0, grp: LS.get("etfGrp", "Tutti"), sort: { key: "r3m", dir: -1 }, retry: null };
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
  Questa regola <b>non ha superato il test</b> sulle categorie (vedi «Test delle regole»): è un'informazione, <b>non verificata</b>.`;
async function loadEtf() {
  clearTimeout(etfS.retry);
  if (!etfS.data || etfS.data.status !== "ok" || Date.now() - etfS.at > 5 * 60_000) {
    try { etfS.data = await getJSON("/api/etf"); etfS.at = Date.now(); } catch { etfS.data = { status: "error" }; }
  }
  if (state.view === "etf") renderEtf();
  if (state.view === "watch") renderWatchEtf();
  if (etfS.data.status === "loading") etfS.retry = setTimeout(loadEtf, 5000);
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
function radarItem(x) {
  const f = etfFit(x.isin), r = etfRow(x.isin);
  return `<li class="rad-it"><button class="link-btn rad-open" data-etf="${esc(x.isin)}">${esc(x.category)}</button>
      ${r?.group === "Temi" ? info(ETF_SAT_INFO) : ""}
      <div>${esc(x.sentence)}</div>
      ${x.news?.length ? `<div class="muted small">Notizie: ${x.news.map(n => `${esc(n.symbol)} · ${n.url ? `<a href="${esc(n.url)}" target="_blank" rel="noopener">${esc(n.title)}</a>` : esc(n.title)}`).join(" — ")}</div>` : ""}
      <div class="small rad-v">(a) ${momText(x.momTercile, x.momMonths)} ${info(ETF_MOM_INFO)} · (b) ${lateText(x.late)} ${info(ETF_LATE_INFO)}${isNum(x.maxDDhist) ? `; perdita massima storica ${fPct(x.maxDDhist, 0)}` : ""}${x.young ? " · <b>tema giovane</b>: meno di 5 anni di storia" : ""}
        · (c) per il tuo portafoglio: ${f ? `${fitBadge(f)} <span class="muted">${esc(f.why)}</span>` : `<span class="muted">${etfS.data.portfolioLoaded ? "in calcolo" : "portafoglio non caricato"}</span>`}</div></li>`;
}
function renderEtf() {
  const el = $("#etfBody"), D = etfS.data;
  if (!D || D.status === "error") { el.innerHTML = `<div class="card empty">Dati degli ETF non disponibili al momento.</div>`; return; }
  if (D.status === "loading") { el.innerHTML = `<div class="card empty">Calcolo in corso: scarico i prezzi di 63 ETF e i dati degli ETF americani equivalenti (circa un minuto la prima volta al giorno)…</div>`; return; }
  const T = D.test, R = D.radar, stale = D.rows.filter(r => r.stale).length;
  const rowsAll = D.rows.filter(r => etfS.grp === "Tutti" || r.group === etfS.grp);
  const { key, dir } = etfS.sort;
  const val = (r, k) => k === "fit" ? ({ "diversifica": 1, "neutro": 0, "si sovrappone": -1 }[etfFit(r.isin)?.verdict] ?? -2) : k === "name" ? r.name : r[k];
  const rows = rowsAll.slice().sort((a, b) => { const va = val(a, key), vb = val(b, key); if (va == null) return 1; if (vb == null) return -1; return (typeof va === "string" ? va.localeCompare(vb) : va - vb) * dir; });
  const pc = v => `<span class="${sign(v)}">${isNum(v) ? fPct(v, 1) : "—"}</span>`;
  const pcs = (r, k) => `${pc(r[k])}${r.fallback && isNum(r[k]) ? '<sup class="fb">*</sup>' : ""}`;
  const tr = r => `${isNum(r.vs50) ? (r.vs50 >= 0 ? "▲" : "▼") : "—"}${isNum(r.vs200) ? (r.vs200 >= 0 ? "▲" : "▼") : "—"}`;
  const cols = [["name", "ETF", "l"], ["r1m", "1 m"], ["r3m", "3 m"], ["r1y", "1 a"], ["r3y", "3 a"], ["mom12_1", "12-1"], ["vol", "Vol."], ["maxDD3y", "Perd. max 3 a"], ["vs200", "Trend 50/200"], ["ter", "TER"], ["fit", "Per il mio portafoglio", "l"]];
  el.innerHTML = `<p class="warn-box"><b>Nessuna categoria è indicata come «favorevole» o «da comprare».</b> Le regole di momentum provate sulle categorie (${T ? `${dayIT(T.from)} – ${dayIT(T.to)}` : ""})
      non hanno superato il test: momentum e trend sono informazioni <b>non verificate</b>. Rendimenti in euro, quello che guadagni tu. Non è una consulenza finanziaria.${stale ? ` <b>${stale} ETF hanno dati di justETF con più di 6 mesi</b>: rilancia etf_universe.py.` : ""}</p>
    ${diversifyHTML(D)}
    <div class="card"><div class="card-h"><h2>Radar dei temi</h2><span class="card-meta">rendimento in euro a 3 mesi, una categoria per riga · dati del ${dayIT(D.generated.slice(0, 10))}</span></div>
      <div class="rad-cols">
        <div><h4 class="bt-h">Più forti</h4><table class="scr mini"><thead><tr><th class="l">Categoria</th><th>3 mesi</th><th>12-1</th></tr></thead><tbody>${R.strong.map(x => `<tr data-etf="${esc(x.isin)}"><td class="l">${esc(x.category)}</td><td>${pc(x.r3m)}</td><td>${pc(x.mom12_1)}</td></tr>`).join("")}</tbody></table></div>
        <div><h4 class="bt-h">Più deboli</h4><table class="scr mini"><thead><tr><th class="l">Categoria</th><th>3 mesi</th><th>12-1</th></tr></thead><tbody>${R.weak.map(x => `<tr data-etf="${esc(x.isin)}"><td class="l">${esc(x.category)}</td><td>${pc(x.r3m)}</td><td>${pc(x.mom12_1)}</td></tr>`).join("")}</tbody></table></div>
      </div>
      <ul class="rad-list">${R.strong.slice(0, 1).map(radarItem).join("")}</ul>
      <details class="fold"><summary><span class="small">Il «perché» delle altre ${R.strong.length + R.weak.length - 1} categorie del radar</span></summary><ul class="rad-list">${R.strong.slice(1).concat(R.weak).map(radarItem).join("")}</ul></details>
      <p class="muted small">Il «perché» è calcolato: contributo dei primi titoli dell'ETF americano equivalente al suo rendimento, correlazione degli ultimi 6 mesi con le altre categorie, titoli delle notizie quando Yahoo ne fornisce.
        Il momentum 12-1 accanto ai 3 mesi mostra quando un tema sale di recente ma è nella media sull'anno.</p></div>
    <div class="card"><div class="card-h"><h2>Tutti gli ETF</h2><span class="card-meta">${rows.length} ETF · clicca una riga per i dettagli</span></div>
      <div class="chips">${ETF_GROUPS.map(g => `<button data-etfgrp="${esc(g)}" class="${g === etfS.grp ? "on" : ""}">${esc(g)}</button>`).join("")}</div>
      <div class="table-wrap"><table class="scr etf-tbl"><thead><tr>${cols.map(([k, l, c]) => `<th class="${c || ""} ${key === k ? "sorted" + (dir > 0 ? " asc" : "") : ""}" data-etfsort="${k}">${l}${k === "mom12_1" ? " " + info(ETF_MOM_INFO) : k === "fit" ? " " + info(ETF_FIT_INFO) : ""}</th>`).join("")}</tr></thead>
        <tbody>${rows.map(r => `<tr data-etf="${esc(r.isin)}"><td class="l"><b>${esc(r.category)}</b><div class="muted small">${esc(r.name || "")}${state.watch.has(r.yahoo) ? " ★" : ""}${etfFit(r.isin)?.held ? " · <b>lo possiedi</b>" : ""}</div></td>
          <td>${pcs(r, "r1m")}</td><td>${pcs(r, "r3m")}</td><td>${pcs(r, "r1y")}</td><td>${pcs(r, "r3y")}</td><td>${pcs(r, "mom12_1")}</td><td>${isNum(r.vol) ? fNum(r.vol, 0) + "%" : "—"}</td>
          <td class="down">${isNum(r.maxDD3y) ? fPct(r.maxDD3y, 0) : "—"}</td><td title="sopra o sotto la media 50 e la media 200">${tr(r)}</td><td>${isNum(r.ter) ? fNum(r.ter, 2) + "%" : "—"}</td><td class="l">${fitBadge(etfFit(r.isin))}</td></tr>`).join("")}</tbody></table></div>
      <p class="muted small"><b>*</b> = storico di ripiego ${info(ETF_FALLBACK_INFO)} · Rendimenti in euro, dividendi inclusi per gli ETF ad accumulazione. Trend: ▲▼ = sopra o sotto la media 50, poi la media 200. Volatilità a 1 anno.
        ${D.portfolioLoaded ? (!D.corrReady ? "Correlazione con il tuo portafoglio in calcolo (prezzi in scaricamento). "
          : D.pricesMissing ? "<b>Prezzi storici del portafoglio non disponibili al momento</b> (Yahoo): correlazione non calcolata, quindi nessun ETF può risultare «diversifica»; nuovo tentativo tra 15 minuti. " : "") : "Carica il portafoglio per la colonna «Per il mio portafoglio». "}
        ${D.fitMissing?.length ? `${D.fitMissing.length} dei tuoi fondi non hanno ancora una composizione (in scaricamento o non disponibile): i loro titoli non entrano nella sovrapposizione. ` : ""}</p></div>
    <details class="card fold"><summary><span class="small"><b>Mappa di rotazione delle categorie</b> (rispetto all'All-World VWCE)</span></summary><div id="etfRrg" class="chart"></div>
      <p class="muted small">Scritti i nomi delle 10 categorie del radar; le altre compaiono passando con il mouse sul punto.</p></details>
    <details class="card fold"><summary><span class="small"><b>Test delle regole di momentum</b>: M1 e M2 non superati</span></summary>${etfTestHTML(T)}</details>`;
  const rr = $("#etfRrg");
  rr.closest("details").addEventListener("toggle", () => drawRRG(rr, D.rotation, d => `<div class="tip-h">Categoria</div><b>${esc(d.name)}</b> <span class="q ${d.quadrant}">${QLAB[d.quadrant]}</span>
      <div class="tip-row"><span>vs All-World 1 mese / 1 settimana</span><b>${fChg(d.rs1m)} / ${fChg(d.rs1w)}</b></div>`, "Rendimento relativo a 1 mese vs All-World (punti) →",
      { fit: true, labels: new Set(R.strong.concat(R.weak).map(x => x.category)) }), { once: true });
}
const ETF_DIV_INFO = `<b>Cosa diversifica di più</b>: per ogni ETF calcola come cambierebbero tecnologia, USA e dollaro (stimato dagli USA) se investissi il 10% del
  portafoglio. In cima gli ETF che abbassano di più la tua concentrazione più alta; esclusi quelli che ne farebbero salire anche una sola, i temi e i prodotti a leva.
  A parità di effetto (stesso valore al decimo di punto) viene prima chi abbassa di più anche le altre due, poi il TER più basso. Un ETF per categoria.
  <b>È una misura dell'effetto sul portafoglio, non una previsione di rendimento</b>: un ETF può diversificare e perdere.`;
function diversifyHTML(D) {
  const V = D.diversify;
  if (!V) return D.portfolioLoaded ? "" : `<div class="card empty small">Carica il portafoglio per vedere cosa lo diversifica di più.</div>`;
  const row = x => `<tr data-etf="${esc(x.isin)}"><td class="l"><b>${esc(x.category)}</b><div class="muted small">${esc(x.sentence)}</div></td>
      ${["tecnologia", "USA", "dollaro (stima)"].map(k => `<td class="${sign(x.delta[k])}">${fChg(x.delta[k])}</td>`).join("")}
      <td>${isNum(x.ter) ? fNum(x.ter, 2) + "%" : "—"}</td><td>${isNum(x.sizeEurM) ? fNum(x.sizeEurM, 0) + " mln €" : "—"}</td></tr>`;
  const table = (title, xs) => `<h4 class="bt-h">${title}</h4>${xs.length ? `<div class="table-wrap"><table class="scr mini div-tbl"><thead><tr><th class="l">ETF</th><th>Tecnologia</th><th>USA</th><th>Dollaro</th><th>TER</th><th>Patrimonio</th></tr></thead>
      <tbody>${xs.map(row).join("")}</tbody></table></div>` : `<p class="muted small">Nessun ETF dell'elenco abbassa la concentrazione senza farne salire un'altra.</p>`}`;
  const top = (V.equity[0] || V.defensive[0])?.top;
  return `<div class="card"><div class="card-h"><h2>Cosa diversifica di più il tuo portafoglio ${info(ETF_DIV_INFO)}</h2>
      <span class="card-meta">investendo il 10% del portafoglio · la tua concentrazione più alta oggi: ${esc(top || "—")} · differenze in punti</span></div>
    <div class="rad-cols"><div>${table("Azionari", V.equity)}</div><div>${table("Obbligazionari e difensivi (oro compreso)", V.defensive)}</div></div>
    <p class="muted small">Misura l'effetto sul portafoglio, non è una previsione di rendimento né un'indicazione di acquisto.</p></div>`;
}
function etfTestHTML(T) {
  if (!T) return `<p class="muted">Test non disponibile: .venv/bin/python etf_backtest.py</p>`;
  const ck = c => c ? "✅" : "❌", R = T.rules, C = T.control, P = T.m2Protection;
  return `<p class="small">Storico ${dayIT(T.from)} – ${dayIT(T.to)}, categorie misurate con ETF americani. Misura: rendimento a 3 mesi della categoria meno la media di tutte le categorie dello stesso mese.
      Controllo casuale: ${C.m1.passed} su ${C.m1.runs} regole finte superano tutte le condizioni (M1), ${C.m2.passed} su ${C.m2.runs} (M2).</p>
    <div class="table-wrap"><table class="scr"><thead><tr><th class="l">Condizione</th><th>M1 (12-1 nel terzo migliore)</th><th>M2 (sopra la media 200)</th></tr></thead><tbody>
      ${T.conditions.map((c, k) => `<tr><td class="l">${k + 1}. ${esc(c)}</td><td>${ck(R.m1.checks[k])}</td><td>${ck(R.m2.checks[k])}</td></tr>`).join("")}
      <tr><td class="l">Media / mediana dell'extra a 3 mesi</td><td>${fChg(R.m1.mean3)} / ${fChg(R.m1.median3)}</td><td>${fChg(R.m2.mean3)} / ${fChg(R.m2.median3)}</td></tr>
      <tr><td class="l"><b>Esito</b></td><td><b>${R.m1.pass ? "superato" : "non superato"}</b></td><td><b>${R.m2.pass ? "superato" : "non superato"}</b></td></tr></tbody></table></div>
    <p class="small">Il momentum ha mostrato un vantaggio coerente ma piccolo (+0,37 punti ogni 3 mesi, circa 1,5% l'anno prima dei costi), sotto la soglia
      fissata prima del test: resta non verificato.</p>
    <p class="small">M2 come protezione nei crolli (soglia fissata prima del test: ${esc(P.rule)}): perdita massima ridotta di un terzo in ${P.ddCutCount} categorie su ${P.n}, volatilità più bassa in ${P.volLowerCount} su ${P.n}:
      <b>${P.verified ? "verificata" : "non verificata"}</b>.</p>`;
}
// panel of one ETF
function openEtf(isin) {
  const r = etfRow(isin);
  if (!r) return;
  const f = etfFit(isin), J = r.justetf;
  state.detail = null; state.macro = null; state.panel = "etf"; etfS.open = isin;
  const pc = v => `<span class="${sign(v)}">${isNum(v) ? fPct(v, 1) : "—"}</span>`;
  const H = ["r1m", "r3m", "r6m", "r1y", "r3y"], HL = { r1m: "1 mese", r3m: "3 mesi", r6m: "6 mesi", r1y: "1 anno", r3y: "3 anni" };
  const loc = k => isNum(r[k]) && r.fx && isNum(r.fx[k]) ? ((1 + r[k] / 100) / (1 + r.fx[k] / 100) - 1) * 100 : null;
  const list = rows => rows?.length ? rows.map(([n, p]) => `${esc(etfIt(n))} <b>${fNum(p, 1)}%</b>`).join(" · ") : "—";
  const conc = f ? Object.keys(f.before).map(k => `<tr><td class="l">${esc(k)}</td><td>${fNum(f.before[k], 1)}%</td><td>${fNum(f.after[k], 1)}%</td><td class="${sign(f.after[k] - f.before[k])}">${fChg(f.after[k] - f.before[k])}</td></tr>`).join("") : "";
  drawer.classList.remove("full");
  drawer.innerHTML = `<div class="d-top"><div class="d-head"><div><div class="tt">${esc(r.category)}</div><div class="nm">${esc(r.name || "")}</div>
        <div class="sec">${esc(r.isin)} · ${esc(r.yahoo || "")} · ${esc(r.provider || "")} · ${esc(r.group)}</div></div>
      <div class="actions"><button class="icon-btn star ${state.watch.has(r.yahoo) ? "on" : ""}" data-star="${esc(r.yahoo)}" title="In osservazione">${state.watch.has(r.yahoo) ? "★" : "☆"}</button>
        <button class="icon-btn close-btn" id="dClose" aria-label="Chiudi">×</button></div></div></div>
    <div class="d-rest etf-d">
      <div class="d-sec"><h3>Per il mio portafoglio ${info(ETF_FIT_INFO)}</h3>
        ${f ? `<p>${fitBadge(f)} <span class="muted">${esc(f.why)}</span></p>${f.held ? `<p><b>Lo possiedi</b> (${fNum(f.heldWeight, 1)}% del portafoglio). <button class="link-btn" data-pos="${esc(r.isin)}">Apri la sua posizione →</button></p>` : ""}
          ${f.notes.length ? `<p class="small">${f.notes.map(esc).join("<br>")}</p>` : ""}` : `<p class="muted">${etfS.data.portfolioLoaded ? "In calcolo." : "Portafoglio non caricato."}</p>`}</div>
      <div class="d-sec"><h3>Rendimenti in euro</h3>
        <div class="table-wrap"><table class="scr"><thead><tr><th class="l"></th>${H.map(k => `<th>${HL[k]}</th>`).join("")}</tr></thead><tbody>
          <tr><td class="l"><b>In euro</b></td>${H.map(k => `<td><b>${pc(r[k])}</b></td>`).join("")}</tr>
          ${r.fx ? `<tr><td class="l">di cui cambio</td>${H.map(k => `<td>${pc(r.fx[k])}</td>`).join("")}</tr><tr><td class="l">nella valuta del sottostante</td>${H.map(k => `<td>${pc(loc(k))}</td>`).join("")}</tr>` : ""}</tbody></table></div>
        <p class="muted small">${esc(r.fxNote || "")} · Storico: ${esc(r.historySource || "—")}${r.fallback ? ` <b>(ripiego: rendimenti con *)</b> ${info(ETF_FALLBACK_INFO)}` : ""}
          · ETF nato il ${r.launchIso ? dayIT(r.launchIso) : esc(etfIt(r.launch) || "—")}</p>
        <p>Trend: ${isNum(r.vs50) ? `${fPct(r.vs50, 1)} dalla media 50` : "—"} · ${isNum(r.vs200) ? `${fPct(r.vs200, 1)} dalla media 200` : "—"} · momentum 12-1 ${pc(r.mom12_1)}
          (${momText(r.momTercile, r.momMonths)}) ${info(ETF_MOM_INFO)}<br>Volatilità ${isNum(r.vol) ? fNum(r.vol, 0) + "%" : "—"} · perdita massima 3 anni ${isNum(r.maxDD3y) ? fPct(r.maxDD3y, 0) : "—"}
          ${r.group === "Temi" ? ` · ${info(ETF_SAT_INFO)} satellite` : ""}</p></div>
      <details class="d-sec fold"><summary><h3>Ha senso adesso?</h3></summary>
        <p>${lateText(r.late)} ${info(ETF_LATE_INFO)}${isNum(r.maxDDhist) ? `. Perdita massima nella storia disponibile (${fNum(r.longYears, 0)} anni, ${esc(r.longSource || "")}): ${fPct(r.maxDDhist, 0)}` : ""}${(r.longYears || 0) < 5 ? ". <b>Tema giovane</b>: meno di 5 anni di storia" : ""}.</p>
        <p class="small">Momentum (M1) e sopra la media 200 (M2) non hanno superato il test sulle categorie: <b>non verificati</b>. Non è un'indicazione di acquisto.</p></details>
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
}
// ETFs I follow (★), shown under the stocks in Ricerca → In osservazione
function renderWatchEtf() {
  const el = $("#myEtf");
  if (!el) return;
  const mine = (etfS.data?.rows || []).filter(r => state.watch.has(r.yahoo));
  if (!mine.length) { el.hidden = true; if (!etfS.data && [...state.watch].some(t => /\.(MI|DE)$/.test(t))) loadEtf(); return; }
  el.hidden = false;
  const pc = v => `<span class="${sign(v)}">${isNum(v) ? fPct(v, 1) : "—"}</span>`;
  el.innerHTML = `<div class="card-h"><h2>ETF in osservazione</h2><span class="card-meta">dalla scheda ETF · clicca per i dettagli</span></div>
    <div class="table-wrap"><table class="scr"><thead><tr><th class="l">ETF</th><th>1 m</th><th>3 m</th><th>1 a</th><th>12-1</th><th class="l">Per il mio portafoglio</th></tr></thead>
    <tbody>${mine.map(r => `<tr data-etf="${esc(r.isin)}"><td class="l"><b>${esc(r.category)}</b> <span class="muted small">${esc(r.yahoo)}</span></td><td>${pc(r.r1m)}</td><td>${pc(r.r3m)}</td><td>${pc(r.r1y)}</td><td>${pc(r.mom12_1)}</td><td class="l">${fitBadge(etfFit(r.isin))}</td></tr>`).join("")}</tbody></table></div>`;
}
document.addEventListener("click", e => {
  const g = e.target.closest("[data-etfgrp]");
  if (g) { etfS.grp = g.dataset.etfgrp; LS.set("etfGrp", etfS.grp); return renderEtf(); }
  const s = e.target.closest("[data-etfsort]");
  if (s && !e.target.closest(".info")) { const k = s.dataset.etfsort; etfS.sort = etfS.sort.key === k ? { key: k, dir: -etfS.sort.dir } : { key: k, dir: k === "name" ? 1 : -1 }; return renderEtf(); }
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
document.addEventListener("click", e => { const b = e.target.closest("[data-dz]"); if (b) { diary.hz = b.dataset.dz; renderDiary(); } });

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

// ------------------------------------------------------------ views, theme, resize
// Four tabs that follow a manager's work; each groups the older views, whose ids (and saved links) are unchanged.
// Phase 21: three tabs. The Diario dei segnali appears in Ricerca only with about 3 months of data (it keeps recording
// in the background in any case). Removed pages (Report, Pattern tecnici, Le mie regole) send old links to the nearest one.
const DIARY_READY = 63;
const GROUPS = [
  { id: "mercato", label: "Mercato", ask: "Cosa sta succedendo?", views: [["overview", "Oggi"], ["sectors", "Settori"]] },
  { id: "portafoglio", label: "Portafoglio", ask: "Cosa ho e come sta andando?", views: [["portfolio", "Posizioni"], ["pfperf", "Performance"], ["pfconc", "Concentrazione"], ["pfrisk", "Rischio"]] },
  { id: "ricerca", label: "Ricerca", ask: "Cosa potrei comprare?", views: [["screener", "Screener"], ["etf", "ETF"], ["watch", "In osservazione"], ["diary", "Diario dei segnali"]] },
];
const PF_SUBS = ["portfolio", "pfperf", "pfconc", "pfrisk"];
const OLD_LINKS = { map: "sectors", ideas: "sectors", trade: "screener", rules: "portfolio", metodo: "screener" };
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
function lastSub(g) { const v = LS.get("sub." + g.id, g.views[0][0]); return shownViews(g).some(x => x[0] === v) ? v : g.views[0][0]; }
function setView(v) {
  if (!VIEWS.includes(v) || (v === "diary" && !diaryReady())) v = viewFromHash(v) || "portfolio";
  const g = groupOf(v);
  state.view = v; LS.set("view", v); LS.set("sub." + g.id, v);
  if (location.hash.slice(1) !== v) history.replaceState(null, "", "#" + v);
  $$(".tab").forEach(t => t.classList.toggle("active", t.dataset.main === g.id));
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
  setView(viewFromHash(h) || "portfolio");          // without a link the dashboard opens on Portafoglio
  if (h && !viewFromHash(h) && quoteFor(h.toUpperCase())) openDetail(h.toUpperCase());
})();
})();
