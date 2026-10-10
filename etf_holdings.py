"""First 10 holdings of the ETFs (plan phase 24, corrections): for the "Ha senso per il mio portafoglio?" overlap.

Sources, in the order approved by the user, each with its address and date:
  1. the holdings files published by the issuer: iShares (full CSV from the Italian site), Xtrackers (CSV with the
     ISIN of every holding), SPDR (daily Excel file with ISIN);
  2. the US ETF on the SAME index (Yahoo, first 10 holdings), only where the index is really the same (SAME_INDEX_US);
  3. justETF as a last resort, with few requests: at most once every 6 months per ETF, a pause between them, and it
     stops at the first refusal (justETF blocks too many requests in a row).
Gold, silver and bond ETFs have no stock holdings to compare (NO_STOCKS).

Public ETFs of the list are kept in cache/etf_holdings.json; the ETFs I own that are not in the list go in
portafoglio/etf_composizioni.json (the list of ISINs tells what I own: never in Git).

Companies are matched by ISIN when both sides have it, otherwise by the normalized company name ("Samsung Electronics
Co., Ltd." = "SAMSUNG ELECTRONICS LTD"): the two share classes of the same company (Samsung common and preferred,
Alphabet A and C) become one company.
"""
from __future__ import annotations

import html
import io
import json
import logging
import os
import re
import threading
import time
import unicodedata
import zipfile
from datetime import date, datetime

import requests

log = logging.getLogger("ndx")
ROOT = os.path.dirname(os.path.abspath(__file__))
PUBLIC = os.path.join(ROOT, "cache", "etf_holdings.json")
PRIVATE = os.path.join(ROOT, "portafoglio", "etf_composizioni.json")
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"}
TOP = 10
MAX_AGE = {"emittente": 30, "ETF americano": 30, "justETF": 183}     # days before downloading again
JUSTETF_PAUSE = 6                                                    # seconds between two justETF pages

ISHARES_LIST = ("https://www.ishares.com/it/investitore-privato/it/product-screener/product-screener-v3.1.jsn?dcrPath=/templatedata/"
                "config/product-screener-v3/data/it/it/product-screener/ishares-product-screener-backend-config&siteEntryPassthrough=true")
ISHARES_FILE = "https://www.ishares.com{page}/1506575546154.ajax?fileType=csv&fileName={ticker}_holdings&dataType=fund"
XTRACKERS_FILE = "https://etf.dws.com/etfdata/export/GBR/ENG/csv/product/constituent/{isin}/"
SPDR_FILE = "https://www.ssga.com/library-content/products/fund-data/etfs/emea/holdings-daily-emea-en-{ticker}-gy.xlsx"
JUSTETF_PAGE = "https://www.justetf.com/en/etf-profile.html?isin={isin}"

# US ETFs that follow the same index (checked by hand on 10 Oct 2026): (symbol, index)
SAME_INDEX_US = {
    "IE00B3XXRP09": ("VOO", "S&P 500"),                                   # Vanguard S&P 500
    "IE0032077012": ("QQQ", "Nasdaq-100"),                                # Invesco EQQQ
    "IE00BMC38736": ("SMH", "MarketVector US Listed Semiconductor 25"),   # VanEck Semiconductor
    "XS3091657729": ("SOXQ", "PHLX Semiconductor"),                       # WisdomTree PHLX Semiconductor 3x (leverage counted by the position)
    "IE000JCW3DZ3": ("SHLD", "Global X Defense Tech"),                    # Global X Defence Tech
    "IE00BFD2H405": ("SKYY", "ISE CTA Cloud Computing"),                  # First Trust Cloud Computing
    "IE00BWTNM743": ("NXTG", "Indxx 5G & NextG Thematic"),                # First Trust Indxx NextG
}
# no stocks inside: nothing to compare (gold, silver, government and corporate bonds, money market)
NO_STOCKS = {"IE00B579F325", "JE00B1VS3333", "IE00B14X4Q57", "LU0290356871", "IE00B1FZS913", "IE00B0M62X26", "IE00B3F81R35",
             "IE00BDBRDM35", "LU0290358497", "LU1598691217", "IE00BDFL4P12"}       # ... and broad commodities

NO_STOCKS_REASON = "nessuna azione dentro (oro, argento, obbligazioni o monetario)"

_lock = threading.Lock()
_state = {"running": False, "blocked": None}


# ---------------------------------------------------------------- company names (pure, tested)

LEGAL = {"inc", "incorporated", "corp", "corporation", "co", "company", "ltd", "limited", "plc", "sa", "ag", "nv", "se", "spa",
         "holding", "holdings", "group", "class", "cl", "a", "b", "c", "adr", "ads", "the", "reg", "registered", "shs", "pref",
         "preferred", "non", "voting", "pre", "pfd", "de", "cv", "ab", "asa", "oyj", "kgaa", "of", "and", "ordinary", "shares",
         "share", "common", "stock", "npv", "sponsored", "gdr", "bhd", "tbk", "pcl", "lp"}


def company_key(name):
    """'Samsung Electronics Co., Ltd.' -> 'samsung electronics'; 'ALPHABET INC CLASS A' -> 'alphabet'.
    Legal forms and share classes are dropped, then the first two words are kept."""
    n = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode().lower()
    words = [w for w in re.sub(r"[^a-z0-9]+", " ", n).split() if w not in LEGAL and len(w) > 1]
    return " ".join(words[:2])


def merge_classes(rows):
    """[{"name", "isin", "weight"}] with the share classes of the same company added together (largest first)."""
    out = {}
    for r in rows:
        k = company_key(r["name"])
        if not k:
            continue
        if k in out:
            out[k]["weight"] += r["weight"]
            out[k]["isins"] += [r["isin"]] if r.get("isin") else []
        else:
            out[k] = {"key": k, "name": r["name"], "weight": r["weight"], "isins": [r["isin"]] if r.get("isin") else []}
    return sorted(out.values(), key=lambda r: -r["weight"])


def _num(s):
    """'5,81' or '1.234,5' (Italian) or '0.64325' -> float."""
    s = str(s).strip().replace("%", "")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


# ---------------------------------------------------------------- sources (network)

def _get(url, timeout=60):
    r = requests.get(url, headers=UA, timeout=timeout)
    r.raise_for_status()
    return r


_ishares_index = {}


def _ishares(isin):
    if not _ishares_index:
        data = _get(ISHARES_LIST).json()
        _ishares_index.update({v.get("isin"): v for v in data.values() if v.get("isin")})
    f = _ishares_index.get(isin)
    if not f:
        return None
    url = ISHARES_FILE.format(page=f["productPageUrl"], ticker=f["localExchangeTicker"])
    lines = _get(url).text.lstrip("﻿").splitlines()
    import csv
    as_of = next((l.split(",", 1)[1].strip('"') for l in lines[:3] if l.startswith("Al,")), None)
    start = next(i for i, l in enumerate(lines) if l.startswith("Ticker"))
    rows = []
    for r in csv.DictReader(lines[start:]):
        w = _num(r.get("Ponderazione (%)") or "")
        if w is None or (r.get("Asset Class") or "") not in ("Azionario", "Equity"):
            continue
        rows.append({"name": r.get("Nome", ""), "ticker": r.get("Ticker dell'emittente"), "weight": w / 100})
    return {"source": url, "label": "iShares, file delle composizioni", "kind": "emittente",
            "asOf": _it_date(as_of), "holdings": rows}


def _xtrackers(isin):
    url = XTRACKERS_FILE.format(isin=isin)
    r = requests.get(url, headers=UA, timeout=60)
    if r.status_code != 200 or len(r.text) < 200:
        return None
    import csv
    lines = r.text.lstrip("﻿").splitlines()
    rd = csv.reader(lines, delimiter=";")
    head = next(rd)
    col = {h: i for i, h in enumerate(head)}
    w_col = next(h for h in head if h.startswith("Constituent Weighting"))
    rows, as_of = [], None
    for x in rd:
        if len(x) < len(head):
            continue
        w = _num(x[col[w_col]])
        if w is None:
            continue
        rows.append({"name": x[col["Constituent Name"]], "isin": x[col["Constituent ISIN"]], "weight": w})
        as_of = as_of or next((x[i] for h, i in col.items() if "Date" in h and x[i]), None)
    if not rows:
        return None
    total = sum(r["weight"] for r in rows)
    if total > 2:                                    # weights in percent
        for r in rows:
            r["weight"] /= 100
    return {"source": url, "label": "Xtrackers, file delle composizioni", "kind": "emittente", "asOf": as_of, "holdings": rows}


def xlsx_rows(content):
    """Rows of the first sheet of an .xlsx file, without extra libraries."""
    z = zipfile.ZipFile(io.BytesIO(content))
    ss = []
    if "xl/sharedStrings.xml" in z.namelist():
        ss = [html.unescape(re.sub(r"<[^>]+>", "", m)) for m in re.findall(r"<si>(.*?)</si>", z.read("xl/sharedStrings.xml").decode(), re.S)]
    out = []
    for row in re.findall(r"<row[^>]*>(.*?)</row>", z.read("xl/worksheets/sheet1.xml").decode(), re.S):
        cells = []
        for m in re.finditer(r'<c r="[A-Z]+\d+"([^>]*?)(?:/>|>(.*?)</c>)', row, re.S):
            v = re.search(r"<v>(.*?)</v>", m.group(2) or "")
            if v:
                cells.append(ss[int(v.group(1))] if 't="s"' in m.group(1) else html.unescape(v.group(1)))
            else:
                cells.append(html.unescape(re.sub(r"<[^>]+>", "", m.group(2) or "")))
        out.append(cells)
    return out


def _spdr(isin, ticker_de):
    if not ticker_de:
        return None
    url = SPDR_FILE.format(ticker=ticker_de.lower())
    r = requests.get(url, headers=UA, timeout=60)
    if r.status_code != 200 or not r.content.startswith(b"PK"):
        return None
    rows = xlsx_rows(r.content)
    if not any(isin in c for x in rows[:6] for c in x):
        return None                                   # another fund behind that ticker
    as_of = next((x[1] for x in rows[:8] if x and x[0].startswith("Holdings As Of")), None)
    i = next(k for k, x in enumerate(rows) if x[:1] == ["ISIN"])
    head = rows[i]
    c = {h: j for j, h in enumerate(head)}
    out = []
    for x in rows[i + 1:]:
        if len(x) <= c["Percent of Fund"]:
            continue
        w = _num(x[c["Percent of Fund"]])
        if w is not None and x[c["Security Name"]]:
            out.append({"name": x[c["Security Name"]], "isin": x[c["ISIN"]], "weight": w / 100})
    return {"source": url, "label": "SPDR, file delle composizioni", "kind": "emittente", "asOf": _it_date(as_of), "holdings": out}


def _us_same_index(isin):
    if isin not in SAME_INDEX_US:
        return None
    import yfinance as yf
    sym, index = SAME_INDEX_US[isin]
    h = yf.Ticker(sym).funds_data.top_holdings
    rows = [{"name": str(r.get("Name") or s), "ticker": str(s), "weight": float(r["Holding Percent"])} for s, r in h.iterrows()]
    return {"source": f"https://finance.yahoo.com/quote/{sym}/holdings", "label": f"ETF americano {sym} sullo stesso indice ({index})",
            "kind": "ETF americano", "asOf": None, "holdings": rows}


def _justetf(isin):
    with _lock:
        if _state["blocked"] and (time.time() - _state["blocked"]) < 3600:
            return None
    url = JUSTETF_PAGE.format(isin=isin)
    r = requests.get(url, headers=UA, timeout=30)
    if r.status_code in (403, 429):
        with _lock:
            _state["blocked"] = time.time()
        log.warning("justETF refused the request (%s): stopping for an hour", r.status_code)
        return None
    if r.status_code != 200 or isin not in r.text:
        return None
    t = r.text
    i = t.find('data-testid="etf-holdings_top-holdings_table"')
    j = t.find("</table>", i)
    rows = []
    for row in re.findall(r'etf-holdings_top-holdings_row"(.*?)</tr>', t[i:j], re.S) if i >= 0 else []:
        h = re.search(r'stock-profiles/([A-Z0-9]{12})"[^>]*title="([^"]*)"', row)
        n = h.group(2) if h else re.sub(r"<[^>]+>", " ", (re.search(r'_name"[^>]*>(.*?)</', row, re.S) or [None, ""])[1]).strip()
        p = re.search(r'value_percentage">([\d.,]+)%', row)
        if n and p:
            rows.append({"name": html.unescape(n), "isin": h.group(1) if h else None, "weight": float(p.group(1).replace(",", "")) / 100})
    as_of = re.search(r'tl_etf-holdings_reference-date"[^>]*>(.*?)</', t, re.S)
    time.sleep(JUSTETF_PAUSE)
    return {"source": url, "label": "justETF", "kind": "justETF",
            "asOf": _it_date(re.sub(r"<[^>]+>|As of", "", as_of.group(1)).strip()) if as_of else None, "holdings": rows}


def _it_date(s):
    """'08/10/2026', '08-Oct-2026', '31/08/2026' -> '2026-10-08' (unknown formats stay as they are)."""
    for fmt in ("%d/%m/%Y", "%d-%b-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(str(s).strip(), fmt).date().isoformat()
        except (TypeError, ValueError):
            continue
    return s


def fetch(isin, provider=None, ticker_de=None):
    """The first 10 holdings of one ETF from the best available source, or {"none": reason}."""
    if isin in NO_STOCKS:
        return {"none": NO_STOCKS_REASON, "fetched": date.today().isoformat()}
    steps = []
    if provider in (None, "iShares"):
        steps.append(lambda: _ishares(isin))
    if provider in (None, "Xtrackers"):
        steps.append(lambda: _xtrackers(isin))
    if provider in (None, "State Street"):
        steps.append(lambda: _spdr(isin, ticker_de))
    steps += [lambda: _us_same_index(isin), lambda: _justetf(isin)]
    for step in steps:
        try:
            d = step()
        except Exception as e:
            log.info("holdings of %s: %s", isin, e)
            d = None
        if d and d["holdings"]:
            top = merge_classes(d.pop("holdings"))[:TOP]
            return {**d, "fetched": date.today().isoformat(), "top": top}
    return {"none": "composizione non disponibile", "fetched": date.today().isoformat()}


# ---------------------------------------------------------------- storage

def _read(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(path + ".tmp", path)


def stale(entry, today=None):
    """True when an entry must be downloaded again (missing, too old for its source, or failed more than a week ago)."""
    if not entry or not entry.get("fetched"):
        return True
    age = ((today or date.today()) - date.fromisoformat(entry["fetched"])).days
    if entry.get("none"):
        return entry["none"] != NO_STOCKS_REASON and age > 7
    return age > MAX_AGE.get(entry.get("kind"), 30)



def update(etfs, path):
    """Download what is missing or old for [{"isin", "provider"?, "tickerDE"?}] and save it in path. Returns all entries."""
    data = _read(path)
    for e in etfs:
        if stale(data.get(e["isin"])):
            data[e["isin"]] = fetch(e["isin"], e.get("provider"), e.get("tickerDE"))
            _write(path, data)
    return data


def public(universe):
    """Holdings of the ETFs of the list (cache/etf_holdings.json, downloaded when missing or old)."""
    return update([{"isin": e["isin"], "provider": e["justetf"].get("provider"), "tickerDE": e["justetf"].get("tickerDE")}
                   for e in universe], PUBLIC)


def held(isins):
    """Holdings of the ETFs I own that are not in the list (portafoglio/etf_composizioni.json), or {} while they
    are downloaded in the background the first time."""
    data = _read(PRIVATE)
    todo = [i for i in isins if stale(data.get(i))]
    if todo:
        with _lock:
            start = not _state["running"]
            _state["running"] = True
        if start:
            def job():
                try:
                    update([{"isin": i} for i in todo], PRIVATE)
                except Exception:
                    log.exception("holdings of my ETFs failed")
                finally:
                    with _lock:
                        _state["running"] = False
            threading.Thread(target=job, daemon=True).start()
    return {i: data[i] for i in isins if i in data}
