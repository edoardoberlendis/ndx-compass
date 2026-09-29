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
  view: LS.get("view", "overview") === "map" ? "sectors" : LS.get("view", "overview"),   // Mappa is now part of Settori
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
const fPct = (v, d = 2) => isNum(v) ? (v > 0 ? "+" : "") + fNum(v, d) + "%" : "—";
const fNum = (v, d = 2) => isNum(v) ? v.toLocaleString("it-IT", { minimumFractionDigits: d, maximumFractionDigits: d }) : "—";
const fPrice = v => isNum(v) ? fNum(v, v >= 1000 ? 2 : 2) : "—";
const fChg = v => isNum(v) ? (v > 0 ? "+" : "") + fNum(v, 2) : "—";
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
const fMetric = (tf, v) => !isNum(v) ? "—" : METRICS[tf].fmt ? METRICS[tf].fmt(v) : fPct(v);
const tz = "America/New_York";
const fTime = t => new Date(t * 1000).toLocaleTimeString("it-IT", { timeZone: tz, hour: "numeric", minute: "2-digit" });
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
async function tick() {
  try { await load(); } catch (e) { console.warn("refresh failed", e); }
  nextAt = Date.now() + 60_000;
}
setInterval(() => {
  if (!state.snap) return;
  const s = Math.max(0, Math.round((nextAt - Date.now()) / 1000));
  const t = new Date(state.snap.lastQuote || state.snap.asOf);
  $("#updated").textContent = `Aggiornato ${t.toLocaleTimeString("it-IT", { timeZone: tz, hour: "numeric", minute: "2-digit", second: "2-digit" })} ora NY · prossimo aggiornamento tra ${s} s`;
  if (s === 0 && Date.now() > nextAt) { nextAt = Date.now() + 60_000; tick(); }
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
    const o = { name, list, n: list.length, mcap: d3.sum(list, s => s.mcap || 0) };
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
  if (state.view === "screener") renderScreener();
  if (state.view === "sectors") renderSectors();
  if (state.view === "ideas" || state.view === "trade") renderIdeas();
  if (state.detail) renderDetailHeader();
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
  const st = state.snap.status;
  const label = { open: "Mercato aperto", pre: "Pre-apertura", post: "Dopo la chiusura", closed: "Mercato chiuso" }[st] || st;
  const el = $("#status");
  el.className = "status " + st;
  el.textContent = label;
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
    <div class="tip-name">${esc(s.name)} · ${fBig(s.mcap)} · ${fNum(s.weight, 2)}% peso</div>
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
      return `<div class="tip-h">${fTime(p.t)} ora NY</div><div class="tip-row"><span>NDX</span><b class="num">${fNum(p.v, 2)}</b></div>
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
  watch: "Solo i titoli che hai segnato con ★ (gli stessi della scheda I miei titoli).",
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
  sigBuy: "Segnale finale Positivo o Molto positivo (punteggio da +20 in su). È una combinazione meccanica, non un consiglio d'acquisto.",
  sigNeutral: "Segnale finale Neutro: punteggio tra −20 e +20.",
  sigSell: "Segnale finale Negativo o Molto negativo (punteggio da −20 in giù). È una combinazione meccanica, non un consiglio di vendita.",
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
}

// earnings of the next 7 days; my stocks first
function renderEarnings() {
  const mine = s => state.watch.has(s.ticker) ? 1 : 0;
  const list = stocks().filter(s => { const d = daysTo(s.earningsTs); return d != null && d <= 7; })
    .sort((a, b) => mine(b) - mine(a) || a.earningsTs - b.earningsTs);
  miniTable($("#earnings"), list, s => {
    const d = Math.round(daysTo(s.earningsTs));
    return `<td class="t">${mine(s) ? '<span class="mine" title="Tra i miei titoli">★</span> ' : ""}${esc(s.ticker)}</td><td class="n">${esc(s.name)}</td>
      <td class="r num">${fDate(s.earningsTs, { weekday: "short", month: "short", day: "numeric" })}</td>
      <td class="r muted num">${d <= 0 ? "oggi" : "tra " + d + " g"}</td><td class="r num muted">${fBig(s.mcap)}</td>`;
  }, "Nessuna trimestrale nei prossimi 7 giorni");
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
const MY_COLS = ["star", "ticker", "name", "price", "chgPct", "perf1M", "perfYTD", "vsSma20", "vsSma40", "vsSma60", "vsSma200", "maOrder", "valLabel", "upside", "signal", "earnings", "news"];
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

// ------------------------------------------------------------ screener
const C = {
  star:   { l: "", cls: "l", sort: s => state.watch.has(s.ticker) ? 1 : 0, html: s => `<button class="star ${state.watch.has(s.ticker) ? "on" : ""}" data-star="${esc(s.ticker)}" aria-label="Preferito">${state.watch.has(s.ticker) ? "★" : "☆"}</button>` },
  ticker: { l: "Ticker", cls: "l tk", sort: s => s.ticker, html: s => esc(s.ticker) },
  name:   { l: "Società", cls: "l nm", sort: s => s.name, html: s => esc(s.name) },
  sector: { l: "Settore", cls: "l", sort: s => s.sector, html: s => esc(s.sector) },
  industry: { l: "Industria", cls: "l", sort: s => s.industry, html: s => esc(s.industry) },
  mcap:   { l: "Capitalizz.", sort: s => s.mcap, html: s => fBig(s.mcap) },
  weight: { l: "Peso", sort: s => s.weight, html: s => fNum(s.weight) + "%" },
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
  signal: { l: "Segnale", cls: "l", sort: s => s.sigScore, html: s => s.signal ? `${sigBadge(s.signal)} <span class="muted num">${fNum(s.sigScore, 0)}</span>` : "—" },
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
  weight: "Peso stimato del titolo nel Nasdaq-100, calcolato dalla capitalizzazione.",
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
  signal: "Segnale finale della dashboard, da −100 a +100: tecnica 40%, analisti 25%, valutazione 20%, notizie 15%. È una combinazione meccanica, non una consulenza finanziaria.",
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
  overview: ["star", "ticker", "name", "sector", "industry", "mcap", "weight", "price", "chgPct", "signal", "volume", "relVol", "d30"],
  performance: ["star", "ticker", "name", "price", "chgPct", "perf1W", "perf1M", "perf3M", "perf6M", "perfYTD", "perf1Y", "vol20", "d30"],
  valuation: ["star", "ticker", "name", "mcap", "signal", "valLabel", "pe", "fpe", "ps", "evEbitda", "peg", "divYield", "revGrowth", "margin", "target", "upside", "rec", "anl30", "epsRev30"],
  technical: ["star", "ticker", "name", "price", "chgPct", "signal", "rsi", "vsSma20", "vsSma40", "vsSma60", "vsSma50", "vsSma200", "range52", "fromHi52", "fromLo52", "gapPct", "relVol", "short"],
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
    "signal", "sigScore", "pe", "fpe", "ps", "evEbitda", "peg", "valLabel", "divYield", "beta", "target", "upside", "up30", "down30", "epsRev30", "rsi", "vsSma20", "vsSma40", "vsSma60", "vsSma50", "vsSma200", "hi52", "lo52", "fromHi52"];
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
  const total = d3.sum(secs, s => s.mcap);
  const maxW = d3.max(secs, s => s.mcap / total);
  $("#matrix").innerHTML = `<thead><tr><th class="l">Settore</th><th>Titoli</th><th class="l">Peso</th>${tfs.map(tf => `<th>${METRICS[tf].label}</th>`).join("")}<th>Rialzo / Ribasso</th></tr></thead>
    <tbody>${secs.map(s => {
      const w = s.mcap / total * 100;
      const adv = s.list.filter(x => x.chgPct > 0).length;
      return `<tr data-sec="${esc(s.name)}" class="${s.name === state.secSel ? "sel" : ""}"><td class="l"><b>${esc(s.name)}</b></td><td>${s.n}</td>
        <td class="l"><span class="wbar" style="width:${(w / (maxW * 100) * 90).toFixed(0)}px"></span>${fNum(w, 1)}%</td>
        ${tfs.map(tf => `<td class="heat" style="background:${colors[tf](s[tf])}">${fPct(s[tf])}</td>`).join("")}
        <td><span class="up">${adv}</span> / <span class="down">${s.list.filter(x => x.chgPct < 0).length}</span></td></tr>`;
    }).join("")}</tbody>`;
  const sec = secs.find(s => s.name === state.secSel);
  $("#secAll").hidden = $("#secStocks").hidden = !sec;
  $("#secDetail").classList.toggle("one", !sec);
  const wr = secs.map(s => ({ name: s.name, v: s.mcap / total * 100, label: fNum(s.mcap / total * 100, 1) + "%", color: css(s.name === state.secSel ? "--series-2" : "--series-1"), s }));
  hbars($("#weights"), wr, { nameW: 170, rowH: 26, click: r => { state.secSel = state.secSel === r.name ? null : r.name; renderSectors(); },
    tip: r => `<div class="tip-h">${esc(r.name)}</div><div class="tip-row"><span>Capitalizzazione</span><b>$${fBig(r.s.mcap)}</b></div><div class="tip-row"><span>I più grandi</span><b>${esc([...r.s.list].sort((a, b) => b.mcap - a.mcap).slice(0, 3).map(x => x.ticker).join(", "))}</b></div>` });
  if (!sec) return;
  const tf = PERF_TFS.includes(state.tf) ? state.tf : "1D";
  $("#secTitle").textContent = `${sec.name} · ${METRICS[tf].label}`;
  const rows = sec.list.filter(s => isNum(val(s, tf))).sort((a, b) => val(b, tf) - val(a, tf))
    .map(s => ({ name: s.ticker, v: val(s, tf), label: fMetric(tf, val(s, tf)), s }));
  hbars($("#secBars"), rows, { rowH: 22, click: r => openDetail(r.s.ticker),
    tip: r => `<div class="tip-h">${esc(r.s.industry)}</div><b>${esc(r.s.name)}</b><div class="tip-row"><span>${METRICS[tf].label}</span><b class="${sign(r.v)}">${r.label}</b></div><div class="tip-row"><span>Peso</span><b>${fNum(r.s.weight)}%</b></div>` });
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
  state.detail = t; dInfo = null; dDaily = null; dRange = "1D";
  drawer.innerHTML = `<div class="d-top"></div><div class="d-sum"></div><div class="d-ctrl"></div><div id="dChart" class="chart"></div><div id="dVol" class="chart"></div><div class="d-rest"><div class="loading" style="padding:40px"><div class="spinner"></div></div></div>`;
  drawer.classList.add("open"); drawer.classList.toggle("full", dFull); drawer.setAttribute("aria-hidden", "false"); scrim.hidden = false;
  renderDetailHeader();
  renderDetailCtrl();
  loadDetailChart();
  loadDetailInfo();
}
function closeDetail() {
  state.detail = null; drawer.classList.remove("open"); drawer.setAttribute("aria-hidden", "true"); scrim.hidden = true; hideTip();
}
scrim.addEventListener("click", closeDetail);

function quoteFor(t) {
  return state.bySym.get(t) || state.snap.indices[t] || null;
}
function renderDetailHeader() {
  const t = state.detail, s = quoteFor(t), top = drawer.querySelector(".d-top");
  if (!top) return;
  const name = s?.name || s?.label || dInfo?.longName || t;
  top.innerHTML = `<div class="d-head"><div><div class="tt">${esc(t)}</div><div class="nm">${esc(dInfo?.longName || name)}</div>
      ${s?.sector ? `<div class="sec">${esc(s.sector)} › ${esc(s.industry)} · capitalizzazione $${fBig(s.mcap)} · ${fNum(s.weight)}% dell'indice</div>` : ""}</div>
      <div class="actions">${state.bySym.has(t) ? `<button class="icon-btn star ${state.watch.has(t) ? "on" : ""}" data-star="${esc(t)}" title="Preferiti">${state.watch.has(t) ? "★" : "☆"}</button>` : ""}
      <button class="icon-btn" id="dFull" title="${dFull ? "Torna al pannello laterale" : "Apri a schermo intero"}" aria-label="${dFull ? "Pannello laterale" : "Schermo intero"}">${dFull ? "⤡" : "⤢"}</button>
      <button class="icon-btn close-btn" id="dClose" aria-label="Chiudi">×</button></div></div>
    ${s ? `<div class="d-price"><span class="p num">${fPrice(s.price)}</span><span class="c ${sign(s.chg)}">${fChg(s.chg)} (${fPct(s.chgPct)})</span>
      <span class="when">${state.snap.status === "open" ? "in tempo reale · " : "ultimo · "}${esc(new Date(state.snap.lastQuote || state.snap.asOf).toLocaleTimeString("it-IT", { timeZone: tz, hour: "numeric", minute: "2-digit" }))} ora NY</span>
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

async function loadDetailInfo() {
  const t = state.detail;
  let data = { info: {}, news: [] };
  try { data = await getJSON(`/api/stock/${encodeURIComponent(t)}`); } catch { /* show what we have */ }
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
  drawer.querySelector(".d-rest").innerHTML = `<div class="d-cols">
      <div class="d-col">${trend}${s.ticker ? valuationHTML(data.valuation, fundamentals) : ""}</div>
      <div class="d-col">${s.ticker ? analystsHTML(data.analysts, s, tgt) : ""}${newsSec}</div></div>${company}`;
  drawer.querySelector(".d-sum").innerHTML = signalHTML(data.signal);
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
const SIG_CLS = { "Molto positivo": "b2", Positivo: "b1", Neutro: "n", Negativo: "s1", "Molto negativo": "s2" };
// reports and backtests saved before the rename still carry the old band names
const SIG_OLD = { "Forte acquisto": "Molto positivo", Acquisto: "Positivo", Vendita: "Negativo", "Forte vendita": "Molto negativo" };
const sigName = l => SIG_OLD[l] || l;
const sigBadge = l => l ? `<span class="sg ${SIG_CLS[sigName(l)]}">${esc(sigName(l))}</span>` : "—";
// "In sintesi": signal plus the first reason of the 3 parts that move the score most (score × effective weight)
function signalHTML(sig) {
  if (!sig) return "";
  const top = sig.components.filter(c => c.used && isNum(c.score))
    .sort((a, b) => Math.abs(b.score * b.effWeight) - Math.abs(a.score * a.effWeight)).slice(0, 3);
  return `<div class="sigbox"><h3>In sintesi</h3>
    <div class="sig-head">${sigBadge(sig.signal)}<span class="sig-score num ${sign(sig.score)}">${sig.score > 0 ? "+" : ""}${fNum(sig.score, 0)}</span>
      <span class="muted small">punteggio da −100 a +100 · ≥ +20 positivo, ≤ −20 negativo</span></div>
    <ol class="top3">${top.map(c => `<li><b>${esc(c.name)}</b> <span class="num ${sign(c.score)}">${c.score > 0 ? "+" : ""}${fNum(c.score, 0)}</span> · ${esc(c.reasons[0] || "")}</li>`).join("")}</ol>
    <details class="fold"><summary><span class="small">Dettaglio del segnale</span></summary>
    <div class="sig-comps">${sig.components.map(c => `<div class="sig-c ${c.used ? "" : "off"}">
      <div class="sig-cn"><b>${esc(c.name)}</b> <span class="muted">${c.used ? `peso ${fNum(c.effWeight * 100, 0)}%` : "non disponibile"}</span></div>
      <div>${c.used ? scoreBar(c.score) : ""}</div>
      <ul class="why">${c.reasons.map(r => `<li>${esc(r)}</li>`).join("")}</ul></div>`).join("")}</div>
    <div class="muted small">Combinazione automatica di dati pubblici (pesi: tecnica 40%, analisti 25%, valutazione 20%, notizie 15%).
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


// ------------------------------------------------------------ ideas (twice-daily trend report)
const ideasState = { report: null, id: LS.get("repId", "latest"), grp: "themes", side: "all", theme: "", maSort: { key: "score", dir: -1 }, loadedId: null };
// "2026-09-28_morning" -> "28 set 2026 · mattina"
const dayIT = iso => new Date(iso + "T12:00:00").toLocaleDateString("it-IT", { day: "numeric", month: "short", year: "numeric" });
const repLabel = id => {
  const [d, s] = id.split("_");
  return `${dayIT(d)} · ${{ morning: "mattina", close: "sera", afternoon: "pomeriggio", intraday: "seduta" }[s] || s}`;
};
const SIDES = [
  { id: "long", label: "Setup di acquisto", desc: "ingressi a favore del trend con rischio definito" },
  { id: "watch", label: "Da osservare", desc: "ipervenduti dentro un trend rialzista più lungo: attendi un'inversione" },
  { id: "manage", label: "Tirati: da gestire", desc: "trend forti molto sopra la media a 20 giorni: alza lo stop, non inseguire" },
  { id: "avoid", label: "Da evitare / candidati short", desc: "medie in discesa e forza relativa debole" },
];
const QCOL = { Leading: "--up", Weakening: "--warn", Lagging: "--down", Improving: "--accent" };

async function renderIdeas() {
  let list = [];
  try { list = (await getJSON("/api/reports")).reports; } catch { /* server without reports */ }
  const sel = $("#repSel");
  sel.innerHTML = `<option value="latest">Ultimo report</option>` + list.map(id => `<option value="${esc(id)}">${esc(repLabel(id))}</option>`).join("");
  sel.value = list.includes(ideasState.id) ? ideasState.id : "latest";
  $("#ideasEmpty").hidden = $("#tradeEmpty").hidden = list.length > 0;
  $("#ideasBody").hidden = $("#tradeBody").hidden = !list.length;
  if (!list.length) return;
  if (ideasState.loadedId !== sel.value || !ideasState.report) {
    try { ideasState.report = await getJSON(`/api/report/${encodeURIComponent(sel.value)}`); ideasState.loadedId = sel.value; }
    catch (e) { $("#brief").innerHTML = `<div class="empty">Impossibile caricare il report (${esc(e.message)})</div>`; return; }
  }
  const R = ideasState.report;
  if (R.prevId && ideasState.prev?.id !== R.prevId) {   // previous report, for the plain-language "Cosa è cambiato"
    try { ideasState.prev = { id: R.prevId, R: await getJSON(`/api/report/${encodeURIComponent(R.prevId)}`) }; }
    catch { ideasState.prev = { id: R.prevId, R: null }; }
  }
  if (state.view === "trade") drawTrade(); else drawIdeas();
}
// setup names of reports saved before the Italian translation (same table as signals.SETUP_OLD_EN)
const SETUP_EN = { Extended: "Tirato", "Bullish crossover": "Incrocio rialzista", "Bearish crossover": "Incrocio ribassista",
  "Pullback in uptrend": "Ritracciamento in trend rialzista", "Momentum leader": "Leader di momentum",
  "Oversold in uptrend": "Ipervenduto in trend rialzista", Downtrend: "Trend ribassista" };
const setupIT = x => SETUP_EN[x] || x;
// one short line, only when some of my stocks (watchlist.json) changed setup since the previous report
function renderMySetupChanges(R) {
  const el = $("#mySetup"), P = ideasState.prev?.id === R.prevId ? ideasState.prev.R : null;
  el.hidden = true;
  if (!P) return;
  const before = new Map(P.ideas.map(i => [i.ticker, setupIT(i.setup)]));
  const now = new Map(R.ideas.map(i => [i.ticker, setupIT(i.setup)]));
  const items = [...state.watch].map(t => {
    const a = before.get(t), b = now.get(t);
    if (a === b) return null;
    const what = b ? (a ? `ora ${b}, prima ${a}` : `ora ${b}`) : `non più ${a}`;
    return `<b class="tlink" data-open="${esc(t)}">${esc(t)}</b> (${esc(what)})`;
  }).filter(Boolean);
  if (!items.length) return;
  el.innerHTML = `${items.length === 1 ? "1 dei tuoi titoli ha" : `${items.length} dei tuoi titoli hanno`} cambiato setup
    rispetto al report ${esc(repLabel(R.prevId))}: ${items.join(", ")}.`;
  el.hidden = false;
}
// Idee: my stocks' setup changes + trade idea cards of the report chosen in Report
function drawTrade() {
  const R = ideasState.report;
  if (!R) return;
  $("#tradeMeta").textContent = `Report: ${repLabel(R.id)} · prezzi del ${dayIT(R.dataAsOf)}`;
  renderMySetupChanges(R);
  renderIdeaCards(R);
}

function drawIdeas() {
  const R = ideasState.report;
  if (!R) return;
  const gen = new Date(R.generated);
  const local = gen.toLocaleString("it-IT", { weekday: "short", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  $("#repMeta").textContent = `${{ morning: "Mattina (pre-apertura)", close: "Sera (dopo la chiusura)" }[R.session] || "Durante la seduta"} · generato ${local} · prezzi del ${dayIT(R.dataAsOf)}${R.intraday ? " (seduta in corso)" : " (chiusura)"}`;
  $("#disclaimer").textContent = R.disclaimer;
  renderBrief(R);
  renderRRG(R);
  renderGroupTable(R);
  renderChanges(R);
  renderMaTable(R);
  loadBacktest();
}

// ------------------------------------------------------------ backtest of the technical score (backtest.py)
const bt = { data: null, hz: "3M" };
async function loadBacktest() {
  if (!bt.data) {
    try { bt.data = await getJSON("/api/backtest"); } catch { return; }   // no backtest yet: keep the hint
  }
  renderBacktest();
}
function renderBacktest() {
  const B = bt.data, rows = B.results[bt.hz];
  $("#btSeg").innerHTML = Object.keys(B.results).map(h => `<button data-bt="${h}" class="${h === bt.hz ? "on" : ""}">${h === "1M" ? "1 mese" : h === "3M" ? "3 mesi" : "6 mesi"}</button>`).join("");
  $("#btMeta").textContent = `${dayIT(B.from)} → ${dayIT(B.to)} · ${B.stocks} titoli di oggi · ${fNum(B.observations, 0)} casi (uno a settimana)`;
  const pc = v => `<span class="${sign(v)}">${fPct(v, 2)}</span>`;
  const table = `<div class="table-wrap"><table class="scr"><thead><tr><th class="l">Segnale tecnico</th><th>Casi</th><th>Rendimento medio</th><th>QQQ stesso periodo</th>
      <th>Extra vs QQQ (media)</th><th>Extra vs QQQ (mediana)</th><th>% volte meglio di QQQ</th><th>vs media di tutti i titoli</th></tr></thead>
    <tbody>${rows.map(x => `<tr class="${x.band === "Tutti i titoli" ? "bt-all" : ""}"><td class="l">${x.band === "Tutti i titoli" ? "<b>Tutti i titoli</b>" : sigBadge(x.band)}</td>
      <td>${fNum(x.n, 0)}</td><td>${pc(x.ret)}</td><td>${pc(x.qqq)}</td><td><b>${pc(x.excess)}</b></td><td>${pc(x.excessMedian)}</td>
      <td>${fNum(x.beat, 1)}%</td><td>${x.band === "Tutti i titoli" ? "—" : pc(x.vsAll)}</td></tr>`).join("")}</tbody></table></div>`;
  const years = `<h4 class="bt-h">Extra-rendimento medio a 3 mesi rispetto a QQQ, anno per anno</h4>
    <div class="table-wrap"><table class="scr"><thead><tr><th class="l">Anno</th>${B.bands.map(b => `<th>${esc(sigName(b))}</th>`).join("")}<th>Tutti</th></tr></thead>
    <tbody>${B.byYear.map(y => `<tr><td class="l">${y.year}</td>${B.bands.map(b => `<td>${isNum(y[b]) ? pc(y[b]) : "—"}</td>`).join("")}<td>${pc(y.all)}</td></tr>`).join("")}</tbody></table></div>`;
  const limits = `<h4 class="bt-h">Limiti: leggili prima di fidarti dei numeri</h4><ul class="why bt-lim">${B.limits.map(l => `<li><b>${esc(l.title)}.</b> ${esc(l.text)}</li>`).join("")}</ul>
    <p class="muted small">Il calcolo del punteggio nel backtest coincide con quello della dashboard (differenza massima su casi di controllo: ${fNum(B.checkMaxDiff, 2)}).
    Per rifarlo: <code>.venv/bin/python backtest.py</code> (circa 10 secondi).</p>`;
  $("#btBody").innerHTML = `<p class="small muted">Ogni settimana, per ogni titolo, il punteggio tecnico (medie 20/40/60, RSI, forza vs QQQ) viene messo nella stessa fascia
    del segnale finale. Poi si misura quanto ha reso il titolo nei ${bt.hz === "1M" ? "21" : bt.hz === "3M" ? "63" : "126"} giorni di borsa successivi, e quanto QQQ negli stessi giorni.</p>${table}${years}${limits}`;
}
$("#btSeg").addEventListener("click", e => { const b = e.target.closest("[data-bt]"); if (b) { bt.hz = b.dataset.bt; renderBacktest(); } });

// explanations adapted to the current values (fixed wording, numbers from the report)
const HORIZON = { 20: "breve", 40: "breve-medio", 60: "medio" };
function qqqInfo(n, vs, slope) {
  if (!isNum(vs)) return "";
  let t = `QQQ (il fondo che replica il Nasdaq-100) è ${fNum(Math.abs(vs), 1)}% ${vs >= 0 ? "sopra" : "sotto"} la sua media degli ultimi ${n} giorni:
    trend di ${HORIZON[n]} periodo <b>${vs >= 0 ? "positivo" : "negativo"}</b>.`;
  if (Math.abs(vs) > 5) t += ` La distanza è ampia: dopo allunghi così a volte il prezzo rallenta o torna verso la media.`;
  if (isNum(slope)) t += `<br><br>La media a ${n} ${slope > 0.05 ? "sale" : slope < -0.05 ? "scende" : "è quasi piatta"} (${fPct(slope, 2)} a settimana):
    ${slope > 0.05 ? "la direzione di fondo è verso l'alto" : slope < -0.05 ? "la direzione di fondo è verso il basso" : "nessuna direzione chiara"}.
    La pendenza dice dove va la media, la distanza dice dove si trova il prezzo rispetto a lei.`;
  return t;
}
function rsiInfo(v) {
  if (!isNum(v)) return "";
  return `RSI a 14 giorni di QQQ: ${fNum(v, 0)} su 100. Misura la forza dei movimenti recenti.
    ${v > 70 ? "Sopra 70 = ipercomprato: è salito molto e in fretta." : v < 30 ? "Sotto 30 = ipervenduto: è sceso molto e in fretta." : "Tra 30 e 70: nessun eccesso."}`;
}
function breadthInfo(n, v, bull, bear) {
  if (!isNum(v)) return "";
  const lvl = v >= 70 ? "partecipazione ampia: il movimento coinvolge la maggior parte dei titoli."
    : v >= 50 ? "più della metà è sopra: partecipazione discreta."
    : v >= 30 ? "meno della metà è sopra: l'indice è sostenuto da pochi titoli, oppure è debole."
    : "partecipazione molto debole: la maggior parte dei titoli è sotto la media.";
  let t = `Il ${Math.round(v)}% dei titoli del Nasdaq-100 ha il prezzo sopra la propria media a ${n} giorni: ${lvl}
    Se l'indice sale ma questa quota scende, il rialzo si sta restringendo.`;
  if (isNum(bull)) t += `<br><br>${Math.round(bull)}% dei titoli ha le medie in ordine rialzista (20 sopra 40 sopra 60), ${Math.round(bear)}% in ordine ribassista.`;
  return t;
}
function renderBrief(R) {
  const g = R.regime, q = g.qqq, b = g.breadth;
  const col = { long: "--up", selective: "--warn", defensive: "--down" }[g.bias] || "--muted";
  const cell = (l, v, s, cls = "", tipHtml = "") => `<div><div class="l">${l} ${info(tipHtml)}</div><div class="v ${cls}">${v}</div><div class="s">${s}</div></div>`;
  $("#brief").innerHTML = `<div>
      <span class="regime"><i style="background:var(${col})"></i>${esc(g.label)}</span>
      <p class="hl">${esc(R.headline)}</p><p class="rt">${esc(g.text)}</p></div>
    <div class="bstats">
      ${cell("QQQ vs media 20", fPct(q.vs20, 1), `pendenza media 20: ${fPct(q.slope20, 2)}/sett.`, sign(q.vs20), qqqInfo(20, q.vs20, q.slope20))}
      ${cell("QQQ vs media 40", fPct(q.vs40, 1), `RSI ${fNum(q.rsi, 0)}`, sign(q.vs40), qqqInfo(40, q.vs40, q.slope40) + "<br><br>" + rsiInfo(q.rsi))}
      ${cell("QQQ vs media 60", fPct(q.vs60, 1), `pendenza media 60: ${fPct(q.slope60, 2)}/sett.`, sign(q.vs60), qqqInfo(60, q.vs60, q.slope60))}
      ${cell("Sopra media 20", pctR(b["20"]), "dei titoli del Nasdaq-100", "", breadthInfo(20, b["20"]))}
      ${cell("Sopra media 40", pctR(b["40"]), "dei titoli del Nasdaq-100", "", breadthInfo(40, b["40"]))}
      ${cell("Sopra media 60", pctR(b["60"]), `${Math.round(g.bullShare)}% medie in ordine rialzista · ${Math.round(g.bearShare)}% ribassista`, "", breadthInfo(60, b["60"], g.bullShare, g.bearShare))}
    </div>`;
}

function renderRRG(R) {
  const el = $("#rrg"), groups = R[ideasState.grp];
  el.innerHTML = "";
  $$("[data-grp-seg] button").forEach(b => b.classList.toggle("on", b.dataset.grp === ideasState.grp));
  const W = el.clientWidth || 500, H = 360, m = { t: 14, r: 16, b: 30, l: 44 }, iw = W - m.l - m.r, ih = H - m.t - m.b;
  const ex = Math.max(3, d3.max(groups, d => Math.abs(d.rs1m)) * 1.15), ey = Math.max(2, d3.max(groups, d => Math.abs(d.rs1w)) * 1.2);
  const x = d3.scaleLinear().domain([-ex, ex]).range([0, iw]).nice(), y = d3.scaleLinear().domain([-ey, ey]).range([ih, 0]).nice();
  const svg = d3.select(el).append("svg").attr("width", W).attr("height", H).attr("role", "img").attr("aria-label", "Mappa di rotazione relativa");
  const g = svg.append("g").attr("transform", `translate(${m.l},${m.t})`);
  g.append("g").attr("class", "gridline").call(d3.axisLeft(y).ticks(5).tickSize(-iw).tickFormat(""));
  g.append("g").attr("class", "axis").call(d3.axisLeft(y).ticks(5).tickSize(0).tickPadding(6).tickFormat(v => (v > 0 ? "+" : "") + v)).select(".domain").remove();
  g.append("g").attr("class", "axis").attr("transform", `translate(0,${ih})`).call(d3.axisBottom(x).ticks(6).tickSize(0).tickPadding(8).tickFormat(v => (v > 0 ? "+" : "") + v)).select(".domain").remove();
  g.append("line").attr("x1", x(0)).attr("x2", x(0)).attr("y1", 0).attr("y2", ih).attr("stroke", css("--baseline"));
  g.append("line").attr("x1", 0).attr("x2", iw).attr("y1", y(0)).attr("y2", y(0)).attr("stroke", css("--baseline"));
  [["Leading", iw - 6, 12, "end"], ["Weakening", iw - 6, ih - 6, "end"], ["Lagging", 6, ih - 6, "start"], ["Improving", 6, 12, "start"]]
    .forEach(([t, px, py, a]) => g.append("text").attr("class", "rrg-q").attr("x", px).attr("y", py).attr("text-anchor", a).text(QLAB[t]));
  const pts = g.selectAll("g.pt").data(groups).join("g").attr("class", "pt").attr("transform", d => `translate(${x(d.rs1m)},${y(d.rs1w)})`).style("cursor", "pointer");
  pts.append("circle").attr("r", 12).attr("fill", "transparent");
  pts.append("circle").attr("r", d => 4 + Math.sqrt(d.n) * 1.3).attr("fill", d => css(QCOL[d.quadrant])).attr("stroke", css("--surface")).attr("stroke-width", 2);
  pts.append("text").attr("class", "rrg-label").attr("x", d => x(d.rs1m) > iw - 120 ? -10 : 10).attr("text-anchor", d => x(d.rs1m) > iw - 120 ? "end" : "start").attr("y", 4).text(d => d.name);
  pts.on("mousemove", (ev, d) => showTip(groupTip(d), ev)).on("mouseleave", hideTip)
    .on("click", (ev, d) => { hideTip(); if (d.kind === "theme") { ideasState.theme = d.name; showIdeas(); } });
  svg.append("text").attr("class", "ref-label").attr("x", m.l + iw).attr("y", H - 2).attr("text-anchor", "end").text("Rendimento relativo a 1 mese vs QQQ (punti) →");
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

function renderGroupTable(R) {
  const groups = R[ideasState.grp];
  $("#grpTitle").textContent = ideasState.grp === "themes" ? "Temi" : "Settori";
  $("#grpTable").innerHTML = `<thead><tr><th class="l">${ideasState.grp === "themes" ? "Tema" : "Settore"}</th><th>Punteggio</th><th>Δ</th><th>Medie rialziste</th><th>&gt;media 20</th><th>&gt;media 40</th><th>&gt;media 60</th><th>vs QQQ 1M</th><th class="l">Fase</th><th class="l">Migliori</th></tr></thead>
    <tbody>${groups.map(g => `<tr data-g="${esc(g.name)}" data-kind="${g.kind}"><td class="l"><b>${esc(g.name)}</b> <span class="muted">${g.n}</span></td><td>${scoreBar(g.score)}</td>
      <td class="${sign(g.dScore)}">${isNum(g.dScore) ? (g.dScore > 0 ? "+" : "") + fNum(g.dScore, 1) : "—"}</td>
      <td>${Math.round(g.bull)}%</td><td>${pctR(g.above20)}</td><td>${pctR(g.above40)}</td><td>${pctR(g.above60)}</td>
      <td class="${sign(g.rs1m)}">${fChg(g.rs1m)}</td><td class="l"><span class="q ${g.quadrant}">${QLAB[g.quadrant]}</span></td><td class="l muted">${esc(g.leaders.join(" · "))}</td></tr>`).join("")}</tbody>`;
}

// "Da stamattina", "Da ieri sera", or "Dal report di …"
function sincePhrase(prevId, curId) {
  const [pd, ps] = prevId.split("_"), [cd] = curId.split("_");
  const days = Math.round((Date.parse(cd) - Date.parse(pd)) / 864e5);
  const today = { morning: "Da stamattina", afternoon: "Da oggi pomeriggio", close: "Da stasera" }[ps];
  const yday = { morning: "Da ieri mattina", afternoon: "Da ieri pomeriggio", close: "Da ieri sera" }[ps];
  return days === 0 && today ? today : days === 1 && yday ? yday : `Dal report di ${repLabel(prevId)}`;
}
// Cosa è cambiato: plain sentences comparing this report with the previous one (display only, same data as the tables)
function renderChanges(R) {
  const c = R.changes;
  $("#changesCard").hidden = !c;
  if (!c) return;
  $("#changesMeta").textContent = `rispetto al report ${repLabel(c.since)}`;
  const since = sincePhrase(c.since, R.id);
  const tk = list => { const shown = list.slice(0, 8).map(t => `<b class="tlink" data-t="${esc(t)}">${esc(t)}</b>`).join(", ");
    return list.length > 8 ? `${shown} e altri ${list.length - 8}` : shown; };
  const n = (k, one, many) => k === 1 ? `1 ${one}` : `${k} ${many}`;
  const out = [];
  const P = ideasState.prev?.id === c.since && ideasState.prev.R ? new Map(ideasState.prev.R.stocks.map(s => [s.ticker, s])) : null;
  // older reports used the 20/30/60 averages: comparing positions or order with them would be wrong
  const sameMAs = P && [...P.values()].some(p => isNum(p.vs40));
  if (P && !sameMAs) out.push(`<span class="muted">Il report precedente usava medie diverse (20/30/60): il confronto su medie e punteggio di trend non è disponibile.</span>`);
  if (sameMAs) {
    const all3 = (s, f) => [s.vs20, s.vs40, s.vs60].every(v => isNum(v) && f(v));
    const has3 = s => [s.vs20, s.vs40, s.vs60].every(isNum);
    const was = (s, f) => { const p = P.get(s.ticker); return p && has3(p) && f(p); };
    const up3 = R.stocks.filter(s => all3(s, v => v > 0) && was(s, p => !all3(p, v => v > 0))).map(s => s.ticker);
    const dn3 = R.stocks.filter(s => all3(s, v => v < 0) && was(s, p => !all3(p, v => v < 0))).map(s => s.ticker);
    const bull = R.stocks.filter(s => s.stack === "bull" && was(s, p => p.stack !== "bull")).map(s => s.ticker);
    const bear = R.stocks.filter(s => s.stack === "bear" && was(s, p => p.stack !== "bear")).map(s => s.ticker);
    if (up3.length) out.push(`${since} ${n(up3.length, "titolo è passato", "titoli sono passati")} sopra le medie 20, 40 e 60: ${tk(up3)}.`);
    if (dn3.length) out.push(`${since} ${n(dn3.length, "titolo è sceso", "titoli sono scesi")} sotto le medie 20, 40 e 60: ${tk(dn3)}.`);
    if (bull.length) out.push(`${n(bull.length, "titolo ha", "titoli hanno")} ora le medie in ordine rialzista (20 sopra 40 sopra 60): ${tk(bull)}.`);
    if (bear.length) out.push(`${n(bear.length, "titolo ha", "titoli hanno")} ora le medie in ordine ribassista (20 sotto 40 sotto 60): ${tk(bear)}.`);
  }
  if (P) {
    const b0 = ideasState.prev.R.regime?.breadth?.["20"], b1 = R.regime?.breadth?.["20"];
    if (isNum(b0) && isNum(b1) && Math.abs(b1 - b0) >= 10)
      out.push(`La quota di titoli sopra la media a 20 giorni è ${b1 > b0 ? "salita" : "scesa"} dal ${pctR(b0)} al ${pctR(b1)}.`);
  }
  const movers = P && !sameMAs ? [] : c.scoreMovers;   // the trend score depends on the averages: not comparable across versions
  const ups = movers.filter(m => m.delta >= 10), dns = movers.filter(m => m.delta <= -10);
  if (ups.length) out.push(`Punteggio di trend salito di più: ${ups.slice(0, 4).map(m => `<b class="tlink" data-t="${esc(m.ticker)}">${esc(m.ticker)}</b> (${m.delta > 0 ? "+" : ""}${fNum(m.delta, 0)}, ora ${fNum(m.score, 0)})`).join(", ")}.`);
  if (dns.length) out.push(`Punteggio di trend sceso di più: ${dns.slice(0, 4).map(m => `<b class="tlink" data-t="${esc(m.ticker)}">${esc(m.ticker)}</b> (${fNum(m.delta, 0)}, ora ${fNum(m.score, 0)})`).join(", ")}.`);
  const isTheme = new Set(R.themes.map(t => t.name));
  c.rotations.forEach(r => out.push(`${isTheme.has(r.name) ? "Il tema" : "Il settore"} <b>${esc(r.name)}</b> è passato da <span class="q ${r.from}">${QLAB[r.from]}</span> a <span class="q ${r.to}">${QLAB[r.to]}</span>.`));
  const real = out.filter(x => !x.startsWith('<span class="muted">'));
  if (!real.length) out.push(`<span class="muted">Nessun cambiamento rilevante rispetto al report ${esc(repLabel(c.since))}.</span>`);
  $("#changes").innerHTML = out.length ? out.map(x => `<li>${x}</li>`).join("")
    : `<li class="muted">Nessun cambiamento rilevante rispetto al report ${esc(repLabel(c.since))}.</li>`;
}

function renderIdeaCards(R) {
  const all = R.ideas.filter(i => !ideasState.theme || i.themes.includes(ideasState.theme));
  $("#sideChips").innerHTML = [{ id: "all", label: "Tutti" }, ...SIDES].map(s => {
    const n = s.id === "all" ? all.length : all.filter(i => i.side === s.id).length;
    return `<button data-side="${s.id}" class="${ideasState.side === s.id ? "on" : ""}">${esc(s.label)}<span>${n}</span></button>`;
  }).join("");
  const ts = $("#themeSel");
  ts.innerHTML = `<option value="">Tutti i temi</option>` + R.themes.map(t => `<option>${esc(t.name)}</option>`).join("");
  ts.value = ideasState.theme;
  $("#maKey").innerHTML = `<span><i style="background:var(--ink)"></i>Prezzo</span><span><i style="background:var(--series-1)"></i>Media 20</span><span><i style="background:var(--series-2)"></i>Media 40</span><span><i style="background:var(--series-3)"></i>Media 60</span>`;
  const host = $("#ideaGroups");
  host.innerHTML = SIDES.filter(s => ideasState.side === "all" || ideasState.side === s.id).map(s => {
    const list = all.filter(i => i.side === s.id);
    if (!list.length) return "";
    return `<div class="idea-group"><h3>${esc(s.label)} <small>${list.length} · ${esc(s.desc)}</small></h3><div class="ideas">${list.map(ideaCard).join("")}</div></div>`;
  }).join("") || `<div class="card empty">Nessun setup per questo filtro.</div>`;
  host.querySelectorAll("[data-chart]").forEach(el => {
    const i = R.ideas.find(x => x.ticker === el.dataset.chart);
    drawIdeaChart(el, i);
  });
}
// clicking a theme (rotation map or table) opens the Idee tab filtered on it
function showIdeas() {
  setView("trade");
}
// report price clearly dated ("chiusura 28 set"), plus today's live price and the change since the report
function ideaPrice(i) {
  const R = ideasState.report, st = i.stats;
  const day = new Date(R.dataAsOf + "T12:00:00").toLocaleDateString("it-IT", { day: "numeric", month: "short" });
  const when = R.intraday ? `prezzo del ${day} (seduta in corso)` : `chiusura ${day}`;
  const live = state.bySym.get(i.ticker)?.price, d = isNum(live) && i.price ? (live / i.price - 1) * 100 : null;
  return `<div class="px-rep"><span class="px-when">${when}</span> <b>${fPrice(i.price)}</b> <span class="${sign(st.ret1d)}">${fPct(st.ret1d)}</span></div>
    ${isNum(live) ? `<div class="px-now">ora ${fPrice(live)} <span class="${sign(d)}">${fPct(d)} dal report</span></div>` : ""}`;
}
function ideaCard(i) {
  const lv = i.levels, st = i.stats;
  const bars = Math.round(i.conviction / 20);
  const lvCell = (l, v, cls = "") => `<div><div class="l">${l}</div><div class="v ${cls}">${v}</div></div>`;
  return `<div class="idea">
    <div class="idea-h"><div style="min-width:0"><span class="tt" data-open="${esc(i.ticker)}">${esc(i.ticker)}</span> <span class="nm">${esc(i.name)}</span><br>
      <span class="setup ${i.side}">${esc(setupIT(i.setup))}</span></div>
      <div class="px">${ideaPrice(i)}
      <div class="conv" title="Convinzione ${i.conviction}/100: punteggio trend, fase del gruppo e allineamento con il mercato">convinzione <span class="m">${[1, 2, 3, 4, 5].map(k => `<i class="${k <= bars ? "on" : ""}"></i>`).join("")}</span></div></div></div>
    <div class="chart" data-chart="${esc(i.ticker)}"></div>
    <div class="lv">${i.side === "manage"
      ? lvCell("Stop mobile", fPrice(lv.stop)) + lvCell("vs media 20", fPct(st.vs20, 1), sign(st.vs20)) + lvCell("RSI", fNum(st.rsi, 0)) + lvCell("vs QQQ 1M", fChg(st.rs1m), sign(st.rs1m)) + lvCell("ATR", fNum(st.atrPct, 1) + "%")
      : lvCell(i.side === "avoid" ? "Short vicino a" : "Entrata", fPrice(lv.entry)) + lvCell("Stop", fPrice(lv.stop), "down") + lvCell("Target", fPrice(lv.target), "up") + lvCell("R : R", fNum(lv.rr, 1)) + lvCell("Rischio", fNum(lv.riskPct, 1) + "%")}</div>
    <ul class="why">${i.why.map(w => `<li>${esc(w)}</li>`).join("")}</ul>
    ${i.signal ? `<div class="idea-sig">Segnale finale: ${sigBadge(i.signal.signal)} <span class="muted num">${fNum(i.signal.score, 0)}</span></div>` : ""}
    <div class="tags"><span>${esc(i.sector)}</span>${i.themes.map(t => `<span>${esc(t)}</span>`).join("")}</div>
  </div>`;
}
function drawIdeaChart(el, i) {
  const c = i.chart, n = c.c.length;
  const pts = k => (c[k] || []).map((v, j) => ({ t: c.t[j], v }));
  const refs = i.side === "manage" ? [{ v: i.levels.stop, label: "stop mobile", color: css("--down") }]
    : [{ v: i.levels.entry, label: "entrata", color: css("--muted") }, { v: i.levels.stop, label: "stop", color: css("--down") }, { v: i.levels.target, label: "target", color: css("--up") }];
  lineChart(el, [
    { pts: pts("c"), color: css("--ink"), width: 1.75 },
    { pts: pts("s20"), color: css("--series-1"), width: 1.5 },
    { pts: pts("s40"), color: css("--series-2"), width: 1.5 },
    { pts: pts("s60"), color: css("--series-3"), width: 1.5 },
  ], {
    height: 160, range: "6M", refs, label: `${i.ticker}: prezzo con medie a 20/40/60 giorni`,
    tip: j => `<div class="tip-h">${fDate(c.t[j], { month: "short", day: "numeric", year: "numeric" })}</div>
      <div class="tip-row"><span>Chiusura</span><b class="num">${fPrice(c.c[j])}</b></div>
      ${[["s20", "Media 20", "--series-1"], ["s40", "Media 40", "--series-2"], ["s60", "Media 60", "--series-3"]].map(([k, l, v]) =>
        `<div class="tip-row"><span><i class="swatch" style="background:var(${v})"></i>${l}</span><span class="num">${fPrice((c[k] || [])[j])}</span></div>`).join("")}`,
  });
}

function renderMaTable(R) {
  const q = ($("#maFind").value || "").trim().toLowerCase();
  const cols = [
    ["ticker", "Ticker", "l tk", s => esc(s.ticker)], ["sector", "Settore", "l", s => esc(s.sector)],
    ["score", "Punteggio", "", s => scoreBar(s.score)],
    ["stack", "Ordine medie", "l", s => `<span class="stack ${s.stack}">${s.stack === "bull" ? "20>40>60" : s.stack === "bear" ? "20<40<60" : "misto"}</span>`],
    ["vs20", "vs media 20", "", s => `<span class="${sign(s.vs20)}">${fPct(s.vs20, 1)}</span>`],
    ["vs60", "vs media 60", "", s => `<span class="${sign(s.vs60)}">${fPct(s.vs60, 1)}</span>`],
    ["rsi", "RSI", "", s => fNum(s.rsi, 0)],
    ["rs1m", "vs QQQ 1M", "", s => `<span class="${sign(s.rs1m)}">${fChg(s.rs1m)}</span>`],
    ["sigScore", "Segnale", "l", s => s.signal ? `${sigBadge(s.signal)} <span class="muted num">${fNum(s.sigScore, 0)}</span>` : "—"],
  ];
  if (!cols.some(c => c[0] === ideasState.maSort.key)) ideasState.maSort = { key: "score", dir: -1 };   // sorted by a removed column
  const { key, dir } = ideasState.maSort;
  const rows = R.stocks.filter(s => !q || s.ticker.toLowerCase().includes(q) || s.name.toLowerCase().includes(q) || s.sector.toLowerCase().includes(q))
    .sort((a, b) => { const va = a[key], vb = b[key]; if (va == null) return 1; if (vb == null) return -1; return (typeof va === "string" ? va.localeCompare(vb) : va - vb) * dir; });
  const head = `<thead><tr>${cols.map(([k, l, c]) => `<th class="${c.split(" ")[0]} ${key === k ? "sorted" + (dir > 0 ? " asc" : "") : ""}" data-mk="${k}">${l}</th>`).join("")}</tr></thead>`;
  $("#maTable").innerHTML = `${head}<tbody>${rows.map(s => `<tr data-t="${esc(s.ticker)}">${cols.map(([, , c, f]) => `<td class="${c}">${f(s)}</td>`).join("")}</tr>`).join("")}</tbody>`;
  $("#maHead").innerHTML = head;
  syncMaHead();
}
// The table scrolls sideways inside its card, so its own header cannot stick to the page: a copy of the header
// is shown fixed under the tabs while the table is on screen, with the same column widths and horizontal offset.
function syncMaHead() {
  const wrap = $("#maWrap"), box = $("#maHeadBox"), table = $("#maTable"), clone = $("#maHead");
  if (!wrap || state.view !== "ideas" || !table.tHead) { box.hidden = true; return; }
  const top = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--sticky-top")) || 0;
  const r = wrap.getBoundingClientRect(), hh = table.tHead.offsetHeight;
  const show = r.top < top && r.bottom > top + hh * 2;
  box.hidden = !show;
  if (!show) return;
  box.style.cssText = `top:${top}px;left:${r.left}px;width:${wrap.clientWidth}px`;
  clone.style.width = table.offsetWidth + "px";
  const src = table.tHead.rows[0].cells, dst = clone.tHead.rows[0].cells;
  for (let k = 0; k < src.length; k++) dst[k].style.width = dst[k].style.minWidth = src[k].getBoundingClientRect().width + "px";
  clone.style.transform = `translateX(${-wrap.scrollLeft}px)`;
  dst[0].style.transform = `translateX(${wrap.scrollLeft}px)`;   // Ticker stays frozen in the copy too
}
addEventListener("scroll", syncMaHead, { passive: true });

$("#repSel").addEventListener("change", e => { ideasState.id = e.target.value; LS.set("repId", ideasState.id); renderIdeas(); });
$("#themeSel").addEventListener("change", e => { ideasState.theme = e.target.value; renderIdeaCards(ideasState.report); });
$("#sideChips").addEventListener("click", e => { const b = e.target.closest("[data-side]"); if (b) { ideasState.side = b.dataset.side; renderIdeaCards(ideasState.report); } });
document.addEventListener("click", e => {
  const b = e.target.closest("[data-grp-seg] button");
  if (b) { ideasState.grp = b.dataset.grp; renderRRG(ideasState.report); renderGroupTable(ideasState.report); }
});
$("#grpTable").addEventListener("click", e => {
  const tr = e.target.closest("tr[data-g]");
  if (tr && tr.dataset.kind === "theme") { ideasState.theme = tr.dataset.g; ideasState.side = "all"; showIdeas(); }
});
$("#view-trade").addEventListener("click", e => {
  const t = e.target.closest("[data-open], .changes [data-t]");
  if (t) openDetail(t.dataset.open || t.dataset.t);
});
$("#view-ideas").addEventListener("click", e => {
  const t = e.target.closest("[data-open], .changes-list [data-t], #maTable tr[data-t]");
  if (t) openDetail(t.dataset.open || t.dataset.t);
  const th = e.target.closest("th[data-mk]");
  if (th) { const k = th.dataset.mk; ideasState.maSort = ideasState.maSort.key === k ? { key: k, dir: -ideasState.maSort.dir } : { key: k, dir: ["ticker", "sector", "stack", "setup"].includes(k) ? 1 : -1 }; renderMaTable(ideasState.report); }
});
$("#maFind").addEventListener("input", () => renderMaTable(ideasState.report));
$("#maWrap").addEventListener("scroll", syncMaHead, { passive: true });
$("#maHeadBox").addEventListener("click", e => {   // sorting from the floating header copy
  const th = e.target.closest("th[data-mk]");
  if (th) $(`#maTable th[data-mk="${th.dataset.mk}"]`).click();
});
$("#runBtn").addEventListener("click", async () => {
  const btn = $("#runBtn");
  btn.disabled = true; btn.textContent = "In esecuzione…";
  try { await fetch("/api/report/run", { method: "POST" }); } catch { /* polled below */ }
  for (let k = 0; k < 90; k++) {
    await new Promise(r => setTimeout(r, 2000));
    const st = await getJSON("/api/reports").catch(() => null);
    if (st && !st.job.running) {
      $("#repJob").textContent = st.job.error ? "Errore: " + st.job.error : "";
      break;
    }
  }
  btn.disabled = false; btn.textContent = "Genera report ora";
  ideasState.id = "latest"; ideasState.loadedId = null; LS.set("repId", "latest");
  renderIdeas();
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
  if (e.key === "Escape" && state.detail) closeDetail();
});

// ------------------------------------------------------------ views, theme, resize
const VIEWS = ["overview", "watch", "screener", "sectors", "ideas", "trade"];
function setView(v) {
  state.view = v; LS.set("view", v);
  if (location.hash.slice(1) !== v) history.replaceState(null, "", "#" + v);
  $$(".tab").forEach(t => t.classList.toggle("active", t.dataset.view === v));
  $$(".view").forEach(el => el.hidden = !state.snap || el.id !== "view-" + v);
  if (state.snap) renderAll();
  window.scrollTo({ top: 0 });
  syncMaHead();
}
$$(".tab").forEach(t => t.addEventListener("click", () => setView(t.dataset.view)));
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
addEventListener("resize", () => { clearTimeout(rz); rz = setTimeout(() => { setStickyTop(); syncMaHead(); if (state.snap) renderAll(); if (state.detail) loadDetailChart(); }, 150); });

// ------------------------------------------------------------ boot
(async function boot() {
  for (let attempt = 0; ; attempt++) {
    try { await load(); break; }
    catch (e) {
      $("#loading p").textContent = attempt > 2 ? `Caricamento ancora in corso… (${e.message})` : "Caricamento dati di mercato…";
      await new Promise(r => setTimeout(r, 3000));
    }
  }
  nextAt = Date.now() + 60_000;
  await loadWatch();
  const h = decodeURIComponent(location.hash.slice(1));
  if (VIEWS.includes(h)) state.view = h;
  if (h === "map") state.view = "sectors";
  setView(state.view);
  if (h && h !== "map" && !VIEWS.includes(h) && quoteFor(h.toUpperCase())) openDetail(h.toUpperCase());
})();
})();
