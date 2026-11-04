"""Builds etf_catalog/ (phase 6A): a manual, reproducible update, never scheduled.

    .venv/bin/python etf_catalog_build.py              # full update (Borsa Italiana pages ~5 min, gentle pauses)
    .venv/bin/python etf_catalog_build.py --offline    # rebuild only from what is already saved (no network)
    .venv/bin/python etf_catalog_build.py --book       # also read the order book again (use it while the market is open)

Inputs, in order of trust (each value keeps its source and date):
  1. the issuer: iShares' public product list (one JSON file, the same one etf_holdings.py already reads) for TER,
     size, share class, distribution, hedging, domicile, duration and yield; top-10 holdings already saved by
     etf_holdings.py from the issuers' files (cache/etf_holdings.json);
  2. the exchange: Borsa Italiana's public ETF pages (scheda + dettaglio) for instrument type, ticker, MIC, TER,
     denomination currency, legal issuer, benchmark, dividend policy, KID/prospectus dates, volumes and book;
  3. justETF: ONLY the snapshot already saved in etf_universe.json (8 Oct 2026). Never downloaded again here
     (its terms of use probably do not allow automatic downloads);
  4. Yahoo Finance: trading currency and average volumes of each listing (.MI, .DE).
Raw pages are kept in cache/etf_catalog/ (not versioned): a second run in the same days reuses them.
Politeness: one request at a time, PAUSE seconds between pages, stop at the first refusal (403/429).
Nothing here reads portafoglio/ or writes the files of the phase-24 ETF tab.
"""
from __future__ import annotations

import argparse
import html as htmlmod
import json
import os
import re
import sys
import time
from datetime import date, datetime

import requests

import etf_catalog as cat

ROOT = cat.ROOT
UNIVERSE = os.path.join(ROOT, "etf_universe.json")
HOLDINGS = os.path.join(ROOT, "cache", "etf_holdings.json")
VERIFY = os.path.join(ROOT, "etf_catalog_verifiche.json")
RAW = os.path.join(ROOT, "cache", "etf_catalog")
PAUSE = 2.0
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"}
ISHARES_LIST = ("https://www.ishares.com/it/investitore-privato/it/product-screener/product-screener-v3.1.jsn?dcrPath=/templatedata/"
                "config/product-screener-v3/data/it/it/product-screener/ishares-product-screener-backend-config&siteEntryPassthrough=true")
BI_SCHEDA = "https://www.borsaitaliana.it/borsa/etf/scheda/{isin}.html?lang=it"
BI_BOOK = "https://www.borsaitaliana.it/borsa/etf/dettaglio.html?isin={isin}&mic=ETFP&lang=it"
JUSTETF_PAGE = "https://www.justetf.com/it/etf-profile.html?isin={isin}"
RAW_MAX_AGE = {"scheda": 30, "book": 1}

# Share classes added in phase 6A to show fund vs class (acc/dist, hedged) and one more bond index. All found in
# iShares' official product list on 4 Nov 2026; they are NOT in the ETF tab's universe and wait for approval.
ADDED = {
    "IE00BKBF6H24": "classe con copertura del cambio in EUR, a distribuzione, dello stesso fondo di SWDA",
    "IE00BYVQ9F29": "classe con copertura del cambio in EUR dello stesso fondo di CSNDX",
    "IE0031442068": "fondo distinto da CSSPX che replica lo stesso indice S&P 500, a distribuzione",
    "IE00BF11F565": "classe ad accumulazione dello stesso fondo di IEAC (obbligazioni societarie in euro)",
    "IE00B4WXJJ64": "governativi dell'area euro su tutte le scadenze, per confronto con quelli 1-3 anni",
}

# Manual classification, one line per ISIN: asset class, family, exposure key, short label, index key (normalized
# index, hedging excluded: hedging is read from the data), theme flag. Two ETFs with the same index key and the same
# hedging follow the same index (level 1); same exposure key = very similar exposure (level 2); same family = same
# category with a different index (level 3).
C = {}


def _c(isins, ac, family, exposure, label, index_key, theme=False, bond_kind=None, credit=None):
    for i in isins.split():
        C[i] = {"assetClass": ac, "family": family, "exposure": exposure, "label": label, "indexKey": index_key,
                "theme": theme, "bondKind": bond_kind, "credit": credit}


A, B, M, R = "azionario", "obbligazionario", "monetario", "materie_prime"
_c("IE00B4L5Y983 IE00BJ0KDQ92 IE00BKBF6H24", A, "globale", "mondo_sviluppati", "Mondo sviluppato", "msci world")
_c("IE00BK5BQT80", A, "globale", "mondo_tutto", "Mondo (sviluppati + emergenti)", "ftse all world")
_c("IE00B3YLTY66", A, "globale", "mondo_tutto", "Mondo con small cap", "msci acwi imi")
_c("IE00B5BMR087 IE00B3XXRP09 IE00B3ZW0K18 IE0031442068", A, "usa", "usa_large", "USA grandi società", "s&p 500")
_c("IE00B53SZB19 IE0032077012 IE00BYVQ9F29", A, "usa", "usa_nasdaq100", "USA Nasdaq-100", "nasdaq 100")
_c("IE00BLNMYC90", A, "usa", "usa_equal", "USA pesi uguali", "s&p 500 equal weight")
_c("IE00B4K48X80", A, "europa", "europa", "Europa", "msci europe")
_c("IE00B53QG562", A, "europa", "eurozona", "Eurozona", "msci emu")
_c("LU0380865021", A, "europa", "eurozona_50", "Eurozona 50 grandi", "euro stoxx 50")
_c("IE00BKM4GZ66", A, "emergenti", "emergenti", "Mercati emergenti (con small cap)", "msci em imi")
_c("IE00BK5BR733", A, "emergenti", "emergenti", "Mercati emergenti", "ftse emerging")
for isin, exp, lab, key in [("IE00B53L4X51", "italia", "Italia", "ftse mib"), ("IE00B4L5YX21", "giappone", "Giappone", "msci japan imi"),
                            ("IE00BJ5JPG56", "cina", "Cina", "msci china"), ("IE00BZCQB185", "india", "India", "msci india"),
                            ("IE00BHZRR030", "corea", "Corea del Sud", "ftse korea 30/18 capped"),
                            ("IE000CM02H85", "taiwan", "Taiwan", "ftse taiwan 30/18 capped"),
                            ("DE000A0Q4R85", "brasile", "Brasile", "msci brazil"), ("LU0476289466", "messico", "Messico", "msci mexico"),
                            ("IE0005042456", "regno_unito", "Regno Unito", "ftse 100"),
                            ("LU0977261329", "svizzera", "Svizzera", "msci switzerland 20/35"), ("DE0005933931", "germania", "Germania", "dax")]:
    _c(isin, A, "paese", exp, lab, key)
_c("IE00B3WJKG14", A, "tecnologia", "tech_usa", "Tecnologia USA", "s&p 500 capped 35/20 information technology")
_c("IE00BM67HT60", A, "tecnologia", "tech_mondo", "Tecnologia mondo", "msci world information technology 20/35")
_c("IE00BMC38736", A, "tecnologia", "semiconduttori", "Semiconduttori", "marketvector us listed semiconductor 10% capped")
_c("LU2023678282", A, "tecnologia", "chip_memoria", "Chip di memoria", "solactive global memory chips", theme=True)
_c("IE00BGV5VN51", A, "tecnologia", "intelligenza_artificiale", "Intelligenza artificiale", "nasdaq global ai and big data", theme=True)
_c("IE00BG0J4C88", A, "tecnologia", "cybersicurezza", "Cybersicurezza", "stoxx global digital security", theme=True)
_c("IE00BYZK4552", A, "tecnologia", "robotica", "Robotica e automazione", "istoxx factset automation & robotics", theme=True)
_c("IE00BM67HK77", A, "sanita", "sanita_mondo", "Sanità mondo", "msci world health care")
_c("IE00B43HR379", A, "sanita", "sanita_usa", "Sanità USA", "s&p 500 capped 35/20 health care")
_c("IE00BM67HL84", A, "finanza", "finanza_mondo", "Finanziari mondo", "msci world financials")
_c("IE00BM67HN09", A, "beni_primari", "beni_primari_mondo", "Beni di prima necessità mondo", "msci world consumer staples")
_c("IE00BM67HV82", A, "industria", "industriali_mondo", "Industriali mondo", "msci world industrials")
_c("IE000YYE6WK5", A, "industria", "difesa", "Difesa", "marketvector global defense industry", theme=True)
_c("IE000YU9K6K2", A, "industria", "spazio", "Spazio", "marketvector global space industry", theme=True)
_c("IE00BM67HM91", A, "energia", "energia_mondo", "Energia mondo (petrolio e gas)", "msci world energy")
_c("IE00B1XNHC34", A, "energia", "energia_pulita", "Energia pulita", "s&p global clean energy transition", theme=True)
_c("IE00BMYDM794", A, "energia", "idrogeno", "Idrogeno", "solactive hydrogen economy", theme=True)
_c("IE000M7V94E1", A, "energia", "nucleare", "Uranio e nucleare", "marketvector global uranium and nuclear", theme=True)
_c("IE00BM67HQ30", A, "utility_infrastrutture", "utility_mondo", "Utility mondo", "msci world utilities")
_c("IE00B1FZS467", A, "utility_infrastrutture", "infrastrutture", "Infrastrutture mondo", "ftse global core infrastructure", theme=True)
for isin, exp, lab, key in [("IE00BP3QZB59", "valore", "Fattore valore (mondo)", "msci world enhanced value"),
                            ("IE00BP3QZ601", "qualita", "Fattore qualità (mondo)", "msci world sector neutral quality"),
                            ("IE00BP3QZ825", "momentum", "Fattore momentum (mondo)", "msci world momentum"),
                            ("IE00B8FHGS14", "bassa_volatilita", "Bassa volatilità (mondo)", "msci world minimum volatility"),
                            ("IE00B8GKDB10", "dividendi", "Alti dividendi (mondo)", "ftse all world high dividend yield"),
                            ("IE00BCBJG560", "small_cap", "Small cap mondo", "msci world small cap")]:
    _c(isin, A, "fattori", exp, lab, key)
GOV, IG = "titoli di Stato", "investment grade (regola dell'indice)"
_c("IE00B14X4Q57", B, "governativi_euro", "gov_euro_1_3", "Stato euro 1-3 anni", "bloomberg euro government 1-3", bond_kind=GOV, credit=IG)
_c("LU0290356871", B, "governativi_euro", "gov_euro_1_3", "Stato euro 1-3 anni", "iboxx eur eurozone 1-3", bond_kind=GOV, credit=IG)
_c("IE00B4WXJJ64", B, "governativi_euro", "gov_euro_tutte", "Stato euro tutte le scadenze", "bloomberg euro government", bond_kind=GOV, credit=IG)
_c("IE00B1FZS913", B, "governativi_euro", "gov_euro_15_30", "Stato euro 15-30 anni", "bloomberg euro government 15-30", bond_kind=GOV, credit=IG)
_c("IE00B0M62X26", B, "governativi_euro", "gov_euro_inflazione", "Stato euro legati all'inflazione",
   "bloomberg euro government inflation linked", bond_kind=GOV + " indicizzati all'inflazione", credit=IG)
_c("LU1598691217", B, "governativi_euro", "btp_10", "BTP 10 anni", "mts italy 10y target maturity", bond_kind="BTP (un solo emittente: Repubblica Italiana)",
   credit="un solo emittente: rating dell'Italia")
_c("IE00B3F81R35 IE00BF11F565", B, "societarie_euro", "corporate_euro", "Obbligazioni societarie euro", "bloomberg euro corporate",
   bond_kind="obbligazioni societarie", credit=IG)
_c("IE00BDBRDM35", B, "aggregato_globale", "aggregato_globale", "Aggregato globale", "bloomberg global aggregate",
   bond_kind="Stato, societarie e cartolarizzate", credit=IG)
_c("LU0290358497", M, "monetario_euro", "monetario_euro", "Monetario euro (€STR)", "solactive €str +8.5 daily",
   bond_kind="tasso overnight €STR tramite swap", credit="rischio di controparte dello swap")
_c("IE00BDFL4P12", R, "materie_prime", "materie_prime_diversificate", "Materie prime diversificate", "bloomberg commodity")
_c("IE00B579F325", R, "metalli", "oro", "Oro (ETC)", "oro")
_c("JE00B1VS3333", R, "metalli", "argento", "Argento (ETC)", "argento")

FAMILY = {"globale": "Azionari globali", "usa": "Azionari USA", "europa": "Azionari Europa", "emergenti": "Azionari emergenti",
          "paese": "Paesi singoli", "tecnologia": "Tecnologia (settori e temi)", "sanita": "Sanità", "finanza": "Finanziari",
          "beni_primari": "Beni di prima necessità", "industria": "Industria, difesa e spazio", "energia": "Energia (tradizionale e transizione)",
          "utility_infrastrutture": "Utility e infrastrutture", "fattori": "Stili e fattori", "governativi_euro": "Titoli di Stato in euro",
          "societarie_euro": "Obbligazioni societarie in euro", "aggregato_globale": "Obbligazioni globali",
          "monetario_euro": "Monetario in euro", "materie_prime": "Materie prime", "metalli": "Metalli preziosi"}
BRANDS = ["iShares", "Vanguard", "Xtrackers", "SPDR", "State Street", "Invesco", "VanEck", "L&G", "Amundi", "Franklin", "UBS", "WisdomTree"]
COUNTRY_CCY = {"United States": "USD", "USA": "USD", "Japan": "JPY", "United Kingdom": "GBP", "Canada": "CAD", "Switzerland": "CHF",
               "France": "EUR", "Germany": "EUR", "Netherlands": "EUR", "Italy": "EUR", "Spain": "EUR", "Ireland": "EUR", "Belgium": "EUR",
               "Finland": "EUR", "Austria": "EUR", "Portugal": "EUR", "Australia": "AUD", "China": "CNY/HKD", "Hong Kong": "HKD",
               "Taiwan": "TWD", "India": "INR", "South Korea": "KRW", "Korea": "KRW", "Brazil": "BRL", "Mexico": "MXN",
               "Sweden": "SEK", "Denmark": "DKK", "Norway": "NOK", "Saudi Arabia": "SAR", "South Africa": "ZAR", "Israel": "ILS",
               "Singapore": "SGD", "Indonesia": "IDR", "Thailand": "THB", "Malaysia": "MYR", "Chile": "CLP", "Poland": "PLN"}
TODAY = date.today().isoformat()


# ---------------------------------------------------------------- small helpers

def num_it(s):
    """'1.234,56%' -> 1234.56; None when it is not a number."""
    if s is None:
        return None
    t = str(s).strip().replace("%", "").replace(".", "").replace(",", ".").replace("+", "")
    try:
        return float(t)
    except ValueError:
        return None


def date_it(s):
    """'14/09/2026' or '03/11/26' -> '2026-09-14'."""
    m = re.search(r"(\d{2})/(\d{2})/(\d{2,4})", s or "")
    if not m:
        return None
    y = int(m.group(3))
    y = y + 2000 if y < 100 else y
    return f"{y:04d}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"


def date_num(r):
    """20261103 -> '2026-11-03'."""
    try:
        s = str(int(r))
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    except (TypeError, ValueError):
        return None


def date_en(s):
    """'25 September 2009' or 'As of 31/08/2026' -> ISO date."""
    if not s:
        return None
    if "/" in s:
        return date_it(s)
    try:
        return datetime.strptime(s.strip(), "%d %B %Y").date().isoformat()
    except ValueError:
        return None


def rd(d, k):
    """iShares numbers come as {"d": display, "r": raw}; '-' means missing."""
    x = d.get(k)
    if isinstance(x, dict):
        return x.get("r")
    return None if x in (None, "-", "", "- ") else x


def page_text(html):
    t = re.sub(r"<script.*?</script>|<style.*?</style>", "", html, flags=re.S)
    t = htmlmod.unescape(re.sub(r"<[^>]+>", "|", t))
    return re.sub(r"\s*\|[\s|]*", " | ", t)


def after(txt, label):
    m = re.search(r"\| " + re.escape(label) + r":? \| ([^|]+?) \|", txt)
    return m.group(1).strip() if m else None


# ---------------------------------------------------------------- downloads (gentle, cached)

class Refused(Exception):
    pass


def raw_path(kind, isin):
    return os.path.join(RAW, f"bi_{kind}_{isin}.html")


def bi_page(kind, isin, offline, force):
    """(text, fetched date, final url) of a Borsa Italiana page; None when missing. Reuses the saved copy if recent."""
    p = raw_path(kind, isin)
    meta = p + ".json"
    if os.path.exists(p) and os.path.exists(meta):
        m = cat._read(meta)
        if offline or (not force and cat.age_days(m["fetched"]) <= RAW_MAX_AGE[kind]):
            with open(p, encoding="utf-8") as f:
                return f.read(), m["fetched"], m["url"], m.get("at")
    if offline:
        return None
    url = (BI_SCHEDA if kind == "scheda" else BI_BOOK).format(isin=isin)
    time.sleep(PAUSE)
    r = requests.get(url, headers=UA, timeout=30)
    if r.status_code in (401, 403, 429):
        raise Refused(f"Borsa Italiana ha risposto {r.status_code}: mi fermo")
    if r.status_code != 200:
        return None
    os.makedirs(RAW, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(r.text)
    at = datetime.now().isoformat(timespec="minutes")
    with open(meta, "w") as f:
        json.dump({"fetched": TODAY, "url": r.url, "at": at}, f)
    return r.text, TODAY, r.url, at


ISH_PAGE_MAX_AGE = 7
ISH_SITE = "https://www.ishares.com"


def ishares_page(isin, path, offline, force=False):
    """(html, fetched date, url) of the issuer's product page of one iShares class (phase 6B), or None. Reuses the
    saved copy for ISH_PAGE_MAX_AGE days; one page at a time with a pause; stops at the first refusal."""
    p = os.path.join(RAW, f"ish_page_{isin}.html")
    meta = p + ".json"
    if os.path.exists(p) and os.path.exists(meta):
        m = cat._read(meta)
        if offline or (not force and cat.age_days(m["fetched"]) <= ISH_PAGE_MAX_AGE):
            with open(p, encoding="utf-8") as f:
                return f.read(), m["fetched"], m["url"]
    if offline or not path:
        return None
    url = ISH_SITE + path + "?switchLocale=y&siteEntryPassthrough=true"
    time.sleep(PAUSE)
    r = requests.get(url, headers=UA, timeout=40)
    if r.status_code in (401, 403, 429):
        raise Refused(f"iShares ha risposto {r.status_code}: mi fermo")
    if r.status_code != 200:
        return None
    os.makedirs(RAW, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(r.text)
    with open(meta, "w") as f:
        json.dump({"fetched": TODAY, "url": r.url.split("?")[0]}, f)
    return r.text, TODAY, r.url.split("?")[0]


def _clean(s):
    return " ".join(htmlmod.unescape(re.sub(r"<button.*?</button>|<[^>]+>", " ", s, flags=re.S)).split())


def _chart(t, var):
    """The first series of an iShares breakdown chart ([{name, y}]), or []."""
    m = re.search(r"var " + var + r"\s*=\s*(\[.*?\]);", t, re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
        return [{"name": x["name"], "weight": x["y"]} for x in (data[0]["data"] if data else [])]
    except (ValueError, KeyError, IndexError, TypeError):
        return []


def _series(block, name):
    m = re.search(r"name\s*:\s*'" + re.escape(name) + r"'\s*,\s*data\s*:\s*\[(.*?)\]", block, re.S)
    if not m:
        return None
    return [float(y) if y not in ("null", "") else None for y in re.findall(r"\{\s*y\s*:\s*(-?[\d.]+|null)", m.group(1))]


def parse_ishares_page(html):
    """What phase 6B reads from an iShares product page: the key facts with their 'al gg/mm/aaaa' date, the class
    (hedged or not), the listings table, calendar-year total returns of the fund and of its benchmark (same currency,
    same years: the base of the tracking difference), credit-rating and maturity breakdowns. None if not a fund page."""
    if not html or "product-data-item" not in html:
        return None
    facts = {}
    for m in re.finditer(r'<div class="product-data-item col-(\w+)[^"]*">\s*<div class="caption"[^>]*>(.*?)</div>\s*</div>\s*'
                         r'<div class="data">(.*?)</div>', html, re.S):
        cap = m.group(2)
        d = re.search(r'<div class="as-of-date">\s*al\s*(\d{2}/\d{2}/\d{4})', cap)
        label = _clean(re.sub(r'<div class="as-of-date">.*', "", cap, flags=re.S))
        facts[m.group(1)] = {"label": label, "asOf": date_it(d.group(1)) if d else None, "value": _clean(m.group(3))}
    if not facts.get("isin"):
        return None
    sc = re.search(r'productShareClass:\s*"([^"]*)"', html)
    title = re.search(r'<meta property="og:title" content="([^"]*)"', html)
    hedged = bool(sc and "hedged" in sc.group(1).lower()) or bool(title and title.group(1).lower().endswith("hedged"))
    pid = re.search(r'portfolioId:\s*"(\d+)"', html)
    cls = re.search(r'<option[^>]*data-link-event="share class ([^"]*)"[^>]*value="[^"]*/prodotti/' + (pid.group(1) if pid else "x") + r'/', html)
    listings = []
    tb = re.search(r'<table id="listingsTable".*?<tbody>(.*?)</tbody>', html, re.S)
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", tb.group(1) if tb else "", re.S):
        cells = [_clean(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        if len(cells) >= 4:
            listings.append({"exchange": cells[0], "ticker": cells[1], "currency": cells[2], "listingDate": date_it(cells[3])})
    cal = []
    yrs = re.search(r"var returnsCalChartCategories\s*=\s*\[([^\]]*)\]", html)
    blk = re.search(r"var returnsCalChartData\s*=\s*\[(.*?)\];", html, re.S)
    if yrs and blk:
        years = [int(y) for y in re.findall(r"\d{4}", yrs.group(1))]
        fund, bench = _series(blk.group(1), "Rendimento totale (%)"), _series(blk.group(1), "Benchmark (%)")
        if fund and bench and len(fund) == len(bench) == len(years):
            cal = [{"year": y, "fund": f, "bench": b} for y, f, b in zip(years, fund, bench) if f is not None and b is not None]
    bench_name = re.search(r'title="Indice: ([^"]+)"', html)
    ccy_f = re.search(r"Rendimento totale \(%\) ([A-Z]{3})", html)
    ccy_b = re.search(r"Benchmark \(%\) ([A-Z]{3})", html)
    rat_as = re.search(r'id="tabsRating".*?al (\d{2}/\d{2}/\d{4})', html, re.S)
    mat_as = re.search(r'id="tabsMaturity".*?al (\d{2}/\d{2}/\d{4})', html, re.S)
    return {"isin": facts["isin"]["value"], "facts": facts, "hedged": hedged, "classLabel": htmlmod.unescape(cls.group(1)) if cls else None,
            "listings": listings, "calendar": cal, "benchmarkName": re.split(r"\.?<br", htmlmod.unescape(bench_name.group(1)))[0].strip() if bench_name else None,
            "returnCurrency": {"fund": ccy_f.group(1) if ccy_f else None, "benchmark": ccy_b.group(1) if ccy_b else None},
            "rating": {"rows": _chart(html, "tabsRatingDataChart"), "asOf": date_it(rat_as.group(1)) if rat_as else None},
            "maturity": {"rows": _chart(html, "tabsMaturityDataChart"), "asOf": date_it(mat_as.group(1)) if mat_as else None}}


def page_num(s):
    """'3,34%' / '1,94 yrs' / 'EUR 1.804.995.637' / '25,33' -> float, None if not a number."""
    m = re.search(r"-?[\d.]+(?:,\d+)?", (s or "").replace(" ", ""))
    return num_it(m.group(0)) if m else None


def tracking_difference(cal, launch_year=None):
    """Calendar-year tracking difference = fund total return − benchmark total return, the same year and the same
    currency (as published by the issuer, NAV with income reinvested). Only full years after the launch year."""
    rows = [r for r in cal or [] if launch_year is None or r["year"] > launch_year]
    rows = [dict(r, td=round(r["fund"] - r["bench"], 3)) for r in rows]
    if not rows:
        return None
    last = rows[-1]
    recent = rows[-5:]
    return {"years": rows, "last": last, "avg": round(sum(r["td"] for r in recent) / len(recent), 3), "n": len(recent)}


def ishares_list(offline):
    p = os.path.join(RAW, "ishares_list.json")
    if os.path.exists(p) and (offline or cat.age_days(cat._read(p + ".meta")["fetched"]) <= 7):
        return cat._read(p), cat._read(p + ".meta")["fetched"]
    if offline:
        return {}, None
    r = requests.get(ISHARES_LIST, headers=UA, timeout=60)
    r.raise_for_status()
    os.makedirs(RAW, exist_ok=True)
    data = r.json()
    with open(p, "w") as f:
        json.dump(data, f)
    with open(p + ".meta", "w") as f:
        json.dump({"fetched": TODAY}, f)
    return data, TODAY


def yahoo_listings(symbols, offline):
    """{symbol: {currency, days, avgVolume, avgTurnover, zeroDays, last}} over the last 3 months (cached one day)."""
    p = os.path.join(RAW, "yahoo_listings.json")
    old = cat._read(p) if os.path.exists(p) else {}
    if offline or (old.get("fetched") == TODAY and set(symbols) <= set(old.get("items", {}))):
        return old.get("items", {}), old.get("fetched")
    import yfinance as yf
    out = {}
    for s in symbols:
        try:
            t = yf.Ticker(s)
            h = t.history(period="3mo", interval="1d", auto_adjust=False)
            meta = t.history_metadata or {}
        except Exception:
            h, meta = None, {}
        if h is None or h.empty:
            out[s] = None
            continue
        h = h.dropna(subset=["Close"])
        vol = h["Volume"].fillna(0)
        out[s] = {"currency": meta.get("currency"), "exchange": meta.get("fullExchangeName") or meta.get("exchangeName"),
                  "days": int(len(h)), "avgVolume": float(vol.mean()), "avgTurnover": float((vol * h["Close"]).mean()),
                  "zeroDays": int((vol == 0).sum()), "last": h.index[-1].date().isoformat(), "close": float(h["Close"].iloc[-1])}
        time.sleep(0.3)
    os.makedirs(RAW, exist_ok=True)
    with open(p, "w") as f:
        json.dump({"fetched": TODAY, "items": out}, f)
    return out, TODAY


# ---------------------------------------------------------------- Borsa Italiana parsing

def parse_scheda(txt):
    if not txt:
        return None
    isin = after(txt, "Codice Isin")
    if not isin:
        return None
    docs = {}
    for lab, key in [("Prospetto", "prospectus"), ("KIID", "kid"), ("KID", "kid")]:
        m = re.search(r"\| " + lab + r" \| (\d{2}/\d{2}/\d{4})", txt)
        if m and key not in docs:
            docs[key] = date_it(m.group(1))
    bench = re.search(r"\| Benchmark:? \| ([^|]+?) \| (?:Stile Benchmark|Area Benchmark)", txt)
    return {"isin": isin, "type": after(txt, "Tipo strumento"), "classe": after(txt, "Classe"), "ticker": after(txt, "Codice Alfanumerico"),
            "mic": after(txt, "MIC"), "lot": num_it(after(txt, "Lotto Minimo")), "ter": num_it(after(txt, "Commissioni totali annue")),
            "currency": after(txt, "Valuta di Denominazione"), "issuer": after(txt, "Emittente"), "segment": after(txt, "Segmento"),
            "benchmark": bench.group(1).strip() if bench else None, "style": after(txt, "Stile Benchmark"),
            "area": after(txt, "Area Benchmark"), "dividends": after(txt, "Dividendi"), "docs": docs}


def parse_book(txt):
    if not txt or not after(txt, "Codice Isin"):
        return None
    levels = []
    m = re.search(r"Numero Proposte \| Volume Acquisto \| Prezzo Acquisto \| Prezzo Vendita \| Volume Vendita \| Numero Proposte \|(.*?)\| (?:Legenda|Dati|Prezzo|Benchmark)", txt)
    if m:
        cells = [c.strip() for c in m.group(1).split("|") if c.strip()]
        for i in range(0, len(cells) - 6, 7):
            lv, nb, vb, bid, ask, va, na = cells[i:i + 7]
            if not lv.isdigit():
                break
            levels.append({"level": int(lv), "bidVol": num_it(vb), "bid": num_it(bid), "ask": num_it(ask), "askVol": num_it(va)})
    last = after(txt, "Data - Ora Ultimo Contratto")
    off = after(txt, "Prezzo ufficiale")
    return {"phase": after(txt, "Fase di Mercato"), "levels": levels[:5], "volume": num_it(after(txt, "Volume totale")),
            "trades": num_it(after(txt, "Numero Contratti")), "turnover": num_it(after(txt, "Controvalore")),
            "lastTrade": last, "official": num_it((off or "").split(" - ")[0]), "officialDate": date_it(off)}


def spread_of(book, at):
    """Bid/ask spread in % of the mid price, from the best level. Representative only while the market is open."""
    if not book or not book["levels"]:
        return None
    b, a = book["levels"][0]["bid"], book["levels"][0]["ask"]
    if not b or not a or a <= b:
        return None
    phase = (book.get("phase") or "").lower()
    open_ = phase in ("continuous trading", "negoziazione continua", "open", "continua")
    return {"v": round((a - b) / ((a + b) / 2) * 100, 3), "bid": b, "ask": a, "phase": book.get("phase"), "at": at,
            "representative": open_, "delayMin": 15, "src": "Borsa Italiana, book del miglior livello",
            "note": None if open_ else "letto a mercato chiuso: non rappresenta lo spread normale durante le contrattazioni"}


# ---------------------------------------------------------------- one entry

def norm_dist(s):
    s = (s or "").lower()
    if any(w in s for w in ("accum", "capitali", "acc")):
        return "accumulazione"
    if "distr" in s or s.startswith("dist") or "dividend" in s:
        return "distribuzione"
    return None


def replication(j):
    kind, method = (j.get("replication") or "").lower(), (j.get("replicationMethod") or "").lower()
    if "synthetic" in kind:
        return "sintetica (swap)", method or None
    if "physically backed" in method:
        return "fisica (metallo depositato)", method
    if "full" in method:
        return "fisica completa", method
    if "sampling" in method:
        return "fisica a campione", method
    return None, method or None


def brand(name):
    for b in BRANDS:
        if b.lower() in (name or "").lower():
            return "SPDR (State Street)" if b in ("SPDR", "State Street") else b
    return None


def fund_key(fund_name, name):
    """Share classes of the same fund share this key: the issuer's fund name, else the name without class words."""
    base = fund_name or re.sub(r"\b(acc|dist|accumulating|distributing|1c|1d|usd|eur|gbp|chf|\(.*?\)|a)\b", " ", (name or "").lower(), flags=re.I)
    return re.sub(r"[^a-z0-9&]+", " ", base.lower()).strip()


def state(values, tol=0.006):
    """Reliability of a value read from several sources: verificato / fonte unica / discordante / mancante."""
    vs = [v for v in values if v is not None]
    if not vs:
        return "mancante"
    if len(vs) == 1:
        return "fonte unica"
    if all(isinstance(v, (int, float)) for v in vs):
        return "verificato" if max(vs) - min(vs) <= tol else "discordante"
    return "verificato" if len({str(v).lower() for v in vs}) == 1 else "discordante"


def ter_reference(isin, ter_i, s_i, as_i, ter_p, s_p, as_p, ter_b, s_b, ter_j, s_j, as_j, verif):
    """(value, source, date, note, resolution, readings, state) of the TER. Reference = the issuer: iShares' list or page,
    else a document of the issuer checked by hand (etf_catalog_verifiche.json). Without the issuer, two other sources
    that agree are enough; if they disagree the conflict stays unresolved and NO value is chosen (never the lowest)."""
    readings = [{"src": s, "v": v, "kind": k} for s, v, k in ((s_i, ter_i, "emittente"), (s_p, ter_p, "emittente"), (s_b, ter_b, "borsa"),
                                                             (s_j, ter_j, "aggregatore")) if s and v is not None]
    man = ((verif or {}).get("ter") or {}).get(isin)
    if man:
        readings.append({"src": f"verifica:{isin}", "v": man["v"], "kind": "emittente (documento letto a mano)"})
    st = state([r["v"] for r in readings])
    if ter_i is not None:
        return ter_i, s_i, as_i, "TER/OCF dell'emittente", "riferimento dell'emittente", readings, st
    if ter_p is not None:
        return ter_p, s_p, as_p, "TER dell'emittente (pagina prodotto)", "riferimento dell'emittente", readings, st
    if man:
        return (man["v"], f"verifica:{isin}", man["asOf"], f"{man['definition']} dal documento dell'emittente: {man['document']}",
                "documento dell'emittente verificato a mano", readings, st)
    if st == "discordante":
        un = ((verif or {}).get("terUnresolved") or {}).get(isin) or {}
        return (None, None, None, "fonti discordanti e nessun documento dell'emittente: conflitto non risolto" +
                (f" ({un['note']})" if un.get("note") else ""), "non risolto", readings, st)
    if ter_b is not None:
        return ter_b, s_b, TODAY, "Commissioni totali annue (Borsa Italiana)", "borsa", readings, st
    return ter_j, s_j, as_j, "TER secondo justETF", "aggregatore", readings, st


def fact(page, key):
    """(number, date) of one key fact of an iShares page, or (None, None)."""
    f = ((page or {}).get("facts") or {}).get(key) or {}
    return page_num(f.get("value")), f.get("asOf")


def td_comparable(page, hedged):
    """None if the issuer's fund and benchmark returns are comparable (same currency; a hedged class against a hedged
    index), else the reason why a tracking difference cannot be computed from them."""
    rc = (page or {}).get("returnCurrency") or {}
    if rc.get("fund") and rc.get("benchmark") and rc["fund"] != rc["benchmark"]:
        return (f"l'emittente confronta il fondo in {rc['fund']} con l'indice in {rc['benchmark']}: valute diverse, "
                "la differenza conterrebbe l'effetto del cambio")
    if hedged and "hedged" not in ((page or {}).get("benchmarkName") or "").lower():
        return "classe coperta confrontata con l'indice non coperto: la differenza conterrebbe l'effetto della copertura"
    return None


def td_field(page, launch, src, as_of, hedged=False):
    """Tracking difference from the issuer's calendar-year returns of fund and benchmark (same currency and years)."""
    ly = int(launch[:4]) if launch else None
    why = td_comparable(page, hedged) if page else None
    if why:
        return cat.fv(None, None, None, "non calcolabile: " + why)
    td = tracking_difference((page or {}).get("calendar"), ly)
    if not td:
        return cat.fv(None, None, None, "non verificabile: serve il rendimento dell'indice nella stessa valuta e periodo"
                      + (" (la pagina dell'emittente non riporta anni completi)" if page else " (nessun documento dell'emittente letto)"))
    out = cat.fv(td["last"]["td"], src, f"{td['last']['year']}-12-31",
                 f"anno {td['last']['year']}: fondo {td['last']['fund']:.2f}% − indice {td['last']['bench']:.2f}% (rendimento totale, "
                 f"stessa valuta, dati dell'emittente); media degli ultimi {td['n']} anni {td['avg']:+.2f} punti")
    out.update(years=td["years"], avg=td["avg"], n=td["n"], benchmark=(page or {}).get("benchmarkName"),
               definition="differenza di rendimento annuo fondo − indice (tracking difference), non la volatilità della differenza (tracking error)")
    return out


def bond_block(k, ish, s_i, page, s_p, hedged, dist):
    """Bond data (phase 6B, part B5): the issuer's page first (each value with its own date), else iShares' list.
    Yield to maturity, coupon and distribution yield are three different things and stay separate."""
    as_n = date_num(rd(ish, "navAmountAsOf")) if ish else None
    def pick(page_key, list_key, note):
        v, d = fact(page, page_key) if page else (None, None)
        if v is not None:
            return cat.fv(v, s_p, d or TODAY, note)
        lv = rd(ish, list_key) if ish and list_key else None
        return cat.fv(lv, s_i if lv is not None else None, as_n if lv is not None else None, note + (" (elenco prodotti, senza data propria)" if lv is not None else ""))
    rat = (page or {}).get("rating") or {}
    mat = (page or {}).get("maturity") or {}
    return {"bondKind": cat.fv(k["bondKind"], "manuale", None, "dalla definizione dell'indice"),
            "credit": cat.fv(k["credit"], "manuale", None, "dalla definizione dell'indice, non un rating del fondo"),
            "duration": pick("modelOad", "effectiveDuration", "duration effettiva, anni: circa la perdita % per +1 punto dei tassi"),
            "yield": pick("yieldToWorst", "yieldToWorst", "rendimento a scadenza medio ponderato (al peggio per i titoli richiamabili), "
                          "% annuo lordo, senza spese: non è una previsione né un rendimento netto garantito"),
            "maturity": pick("weightedAvgLife", None, "scadenza media ponderata, anni"),
            "coupon": pick("weightedAvgCoupon", None, "cedola media ponderata dei titoli, %: non è il rendimento"),
            "distYield": pick("twelveMonTrlYld", "distYield", "rendimento delle distribuzioni degli ultimi 12 mesi, %: guarda indietro, non è il rendimento a scadenza")
                         if dist != "accumulazione" else cat.fv(None, None, None, "classe ad accumulazione: nessuna distribuzione"),
            "ratings": cat.fv(rat.get("rows") or None, s_p if rat.get("rows") else None, rat.get("asOf"), "qualità del credito dei titoli, % del fondo"),
            "maturities": cat.fv(mat.get("rows") or None, s_p if mat.get("rows") else None, mat.get("asOf"), "fasce di scadenza, % del fondo"),
            "currency": cat.fv("EUR" if k["family"] != "aggregato_globale" else "varie, coperte in EUR" if hedged else "varie",
                               "manuale", None, "dalla definizione dell'indice"),
            "hedged": hedged}


def build_entry(isin, uni, ish, bi, bk, bk_at, holdings, sources, report, twins_of, page=None, verif=None):
    j = (uni or {}).get("justetf") or {}
    k = C.get(isin)
    if not k:
        report.append({"isin": isin, "problema": "manca nella classificazione manuale"})
        return None
    s_j = "justetf_2026-10-08" if j else None
    s_i, s_b = ("ishares_lista" if ish else None), (f"bi_scheda:{isin}" if bi else None)
    as_i = date_num(rd(ish, "totalFundSizeInMillionsAsOf")) if ish else None
    as_j = (j.get("date") or "2026-10-08")[:10] if j else None

    name = j.get("name") or (ish or {}).get("fundName")
    if ish and isin in ADDED:
        cls = (ish.get("investorClassName") or "").strip(" -")
        name = f"{ish['fundName']}" + (f" ({cls})" if cls else "") + f" — {ish.get('useOfProfits')}, {ish.get('seriesBaseCurrencyCode')}"
    ptype = (bi or {}).get("type") or (j.get("legal") if j else None) or ("ETF" if ish else None)
    ucits = True if "ucits" in (name or "").lower() or "ucits" in ((ish or {}).get("fundName") or "").lower() else (False if ptype in ("ETC", "ETN") else None)
    excl = cat.exclusion(name, ptype, ucits)
    idx_name = j.get("index") or (bi or {}).get("benchmark")
    hedged_vals = [bool(re.search(r"\bhedged", (j.get("hedge") or "").lower())) if j.get("hedge") else None,
                   ("hedged" == (ish or {}).get("investorClassName", "").strip().lower()) if ish else None]
    if ish and isin in ADDED and "hedged" in (ish.get("investorClassName") or "").lower():
        hedged_vals[1] = True
    hedged = next((v for v in hedged_vals if v is not None), None)
    dist_vals = [norm_dist(j.get("distribution")), norm_dist((ish or {}).get("useOfProfits")), norm_dist((bi or {}).get("dividends"))]
    dist = next((v for v in dist_vals if v), None)
    rep, rep_detail = replication(j) if j else (("fisica a campione" if ish and "campion" in str(ish).lower() else None), None)
    ter_i = rd(ish, "ter_ocf") if ish else None
    ter_b, ter_j = (bi or {}).get("ter"), j.get("ter")
    s_p = f"ishares_pagina:{isin}" if page else None
    ter_p, as_p = fact(page, "emeaMgt") if page else (None, None)
    ter_v, ter_src, ter_as, ter_note, ter_res, ter_read, ter_state = ter_reference(
        isin, ter_i, s_i, as_i, ter_p, s_p, as_p or TODAY, ter_b, s_b, ter_j, s_j, as_j, verif)
    if ter_state == "discordante":
        report.append({"isin": isin, "problema": "TER diverso tra le fonti", "emittente": ter_i if ter_i is not None else ter_p,
                       "borsa": ter_b, "justETF": ter_j, "riferimento": ter_v, "risoluzione": ter_res})
    ccy_vals = [(ish or {}).get("seriesBaseCurrencyCode"), (bi or {}).get("currency"), (j.get("fundCurrency") or "")[:3] or None]
    ccy = next((v for v in ccy_vals if v), None)
    if state(ccy_vals) == "discordante":
        report.append({"isin": isin, "problema": "valuta della classe diversa tra le fonti", "valori": ccy_vals})
    if state(dist_vals) == "discordante":
        report.append({"isin": isin, "problema": "politica dei proventi diversa tra le fonti", "valori": dist_vals})
    dom = (ish or {}).get("domicile")
    dom_f = cat.fv(dom, s_i, as_i) if dom else cat.fv(cat.domicile_from_isin(isin), "isin", None, "dedotto dal prefisso dell'ISIN")
    size_f = cat.fv(rd(ish, "totalFundSizeInMillions"), s_i, as_i, "milioni, patrimonio dell'intero fondo (tutte le classi) secondo iShares") \
        if ish and rd(ish, "totalFundSizeInMillions") is not None else \
        cat.fv(j.get("sizeEurM"), s_j, as_j, "milioni di euro, patrimonio del fondo secondo justETF") if j.get("sizeEurM") is not None else cat.fv(None)
    if size_f.get("v") is not None:
        size_f["unit"] = (ish or {}).get("seriesBaseCurrencyCode") if ish and rd(ish, "totalFundSizeInMillions") is not None else "EUR"
    size_cls = cat.fv(round(rd(ish, "totalNetAssets") / 1e6, 1), s_i, as_i, "milioni, solo questa classe") if ish and rd(ish, "totalNetAssets") else cat.fv(None)
    launch = date_num(rd(ish, "inceptionDate")) if ish and rd(ish, "inceptionDate") else date_en(j.get("launch"))
    synthetic = rep and rep.startswith("sintetica")
    fk = fund_key((ish or {}).get("fundName"), name)

    entry = {
        "isin": isin, "isinValid": cat.isin_valid(isin), "exclusion": excl, "exclusionReason": cat.EXCLUDED.get(excl),
        "status": "aggiunto Fase 6A, da approvare" if isin in ADDED else "universo ETF (approvato 8 ott 2026)",
        "statusNote": ADDED.get(isin),
        "identity": {
            "name": cat.fv(name, s_j or s_i, as_j or as_i), "fundName": cat.fv((ish or {}).get("fundName"), s_i, as_i),
            "fundKey": cat.fv(fk, "calcolato", None, "nome del fondo senza le parole della classe"),
            "issuer": cat.fv(brand(name), "calcolato", None, "marchio letto dal nome"),
            "legalEntity": cat.fv((bi or {}).get("issuer"), s_b, TODAY if bi else None),
            "domicile": dom_f, "ucits": cat.fv(ucits, s_j or s_i, None, "la sigla UCITS compare nel nome ufficiale" if ucits else None),
            "productType": cat.fv(ptype, s_b or s_j, None), "index": cat.fv(idx_name, s_j or s_b, as_j),
            "benchmarkExchange": cat.fv((bi or {}).get("benchmark"), s_b, TODAY if bi else None, "nome del benchmark su Borsa Italiana"),
            "shareClass": cat.fv(((ish or {}).get("investorClassName") or "").strip(" -") or None, s_i, as_i),
            "segment": cat.fv((bi or {}).get("segment"), s_b, None), "biClass": cat.fv((bi or {}).get("classe"), s_b, None),
        },
        "fund": {
            "baseCurrency": cat.fv(ccy, s_i or s_b or s_j, as_i or as_j, "valuta in cui è calcolato il valore della classe (NAV), non quella in cui si compra"),
            "baseCurrencyState": state(ccy_vals),
            "hedged": cat.fv(hedged, s_j or s_i, as_j or as_i), "hedgedState": state(hedged_vals),
            "distribution": cat.fv(dist, s_j or s_i or s_b, as_j or as_i), "distributionState": state(dist_vals),
            "distributionFrequency": (cat.fv(fq, s_p, as_p or TODAY, "frequenza delle distribuzioni (pagina dell'emittente)")
                                      if (fq := (((page or {}).get("facts") or {}).get("distributionFrequency") or {}).get("value"))
                                      and dist == "distribuzione" else
                                      cat.fv(None, None, None, "classe ad accumulazione: nessuna distribuzione") if dist == "accumulazione" else
                                      cat.fv(None, None, None, "frequenza delle cedole non disponibile nelle fonti lette")),
            "replication": cat.fv(rep, s_j, as_j), "replicationDetail": rep_detail,
            "counterpartyRisk": "sì: l'ETF riceve il rendimento dell'indice da uno swap con una banca" if synthetic else
                                ("possibile prestito titoli: verificare sul documento dell'emittente" if rep else None),
            "sizeFund": size_f, "sizeClass": size_cls, "launch": cat.fv(launch, s_i if ish and rd(ish, "inceptionDate") else s_j, None),
            "kidDate": cat.fv(((bi or {}).get("docs") or {}).get("kid"), s_b, None, "data del KID depositato in Borsa"),
            "prospectusDate": cat.fv(((bi or {}).get("docs") or {}).get("prospectus"), s_b, None),
        },
        "costs": {
            "ter": cat.fv(ter_v, ter_src, ter_as, ter_note),
            "terState": ter_state, "terResolution": ter_res, "terChecks": ter_read,
            "trackingDifference": td_field(page, launch, s_p, as_p, bool(hedged)),
            "trackingError": cat.fv(None, None, None, "non verificabile con le fonti gratuite lette"),
            "brokerFees": cat.fv(None, None, None, "commissioni del broker non note"),
            "brokerAvailability": "non verificata",
        },
        "bond": {},
        "classification": dict(k, familyLabel=FAMILY.get(k["family"]), assetClassLabel=cat.ASSET_CLASSES.get(k["assetClass"])),
    }
    if k["assetClass"] in ("obbligazionario", "monetario"):
        entry["bond"] = bond_block(k, ish, s_i, page, s_p, hedged, dist)
    if k["assetClass"] == "azionario" and page:
        val = {}
        for key, lab in (("priceEarnings", "P/E"), ("priceBook", "P/B")):
            v, d = fact(page, key)
            if v is not None:
                val[key] = cat.fv(v, s_p, d, f"{lab} del portafoglio calcolato dall'emittente sui titoli del fondo (non una stima di questo programma)")
        if val:
            entry["valuation"] = val
    # exposure
    ex = {}
    h = holdings.get(isin)
    twin = None
    if not h:
        twin = next((t for t in twins_of.get(fk, []) if t != isin and holdings.get(t)), None)
        h = holdings.get(twin) if twin else None
    if h and h.get("top"):
        top = [{"name": x["name"], "key": x.get("key"), "weight": x.get("weight")} for x in h["top"][:10]]
        note = h.get("label")
        if twin:
            note = f"{note} — composizione della classe {twin} dello stesso fondo"
        h_as = h.get("asOf") or h.get("fetched")
        if not h.get("asOf"):
            note = f"{note} — il file non riporta la data: uso quella del download"
        ex["top10"] = cat.fv(top, f"holdings:{twin or isin}", h_as, note)
        ex["top10"]["dateKind"] = "composizione" if h.get("asOf") else "download"
        ex["top10Kind"] = h.get("kind")
        w = [x["weight"] for x in top if x.get("weight") is not None]
        ex["top10Weight"] = cat.fv(round(sum(w), 4) if len(w) == len(top) else None, f"holdings:{twin or isin}", h_as,
                                   "somma dei pesi dei primi 10 titoli (concentrazione)")
        sources[f"holdings:{twin or isin}"] = {"publisher": h.get("label"), "kind": h.get("kind"), "url": h.get("source"),
                                              "asOf": h.get("asOf"), "fetched": h.get("fetched")}
    hd = date_en((j.get("holdingsDate") or "").replace("As of", "").strip()) if j else None
    if j.get("holdingsCount") is not None:
        ex["holdingsCount"] = cat.fv(int(j["holdingsCount"]), s_j, hd)
    for key in ("countries", "sectors"):
        if j.get(key):
            ex[key] = cat.fv([{"name": n, "weight": w} for n, w in j[key]], s_j, hd, "primi 4 più 'altri', % del fondo")
    if k["assetClass"] == "azionario":
        if hedged:
            ex["currencyExposure"] = cat.fv([{"currency": "EUR (coperta)", "weight": None}], "calcolato", None,
                                            "classe coperta: l'effetto dei cambi verso l'euro è in gran parte neutralizzato")
        elif j.get("countries"):
            agg = {}
            for n, w in j["countries"]:
                cc = COUNTRY_CCY.get(n, "altre")
                agg[cc] = agg.get(cc, 0) + (w or 0)
            ex["currencyExposure"] = cat.fv([{"currency": c, "weight": round(w, 2)} for c, w in sorted(agg.items(), key=lambda x: -x[1])],
                                            "calcolato", hd, "stima dai primi 5 paesi: la valuta dei titoli, non quella in cui si compra l'ETF")
    entry["exposure"] = ex
    # listings
    lst = []
    venues = []
    if (bi or {}).get("ticker") or (j or {}).get("tickerMI"):
        venues.append(("Borsa Italiana (ETFplus)", "ETFP", (bi or {}).get("ticker") or j.get("tickerMI"), "MI"))
    if j.get("tickerDE"):
        venues.append(("Xetra (Francoforte)", "XETR", j.get("tickerDE"), "DE"))
    entry["_venues"] = venues
    if bk:
        entry["_book"] = (bk, bk_at)
    return entry


VENUES = {"Borsa Italiana": ("Borsa Italiana (ETFplus)", "ETFP", "MI"), "Xetra": ("Xetra (Francoforte)", "XETR", "DE")}


def verify_added(e, page):
    """Checks of an added class against the issuer's own page (phase 6B, part B1): ISIN, class (hedged or not),
    index, use of income and listings. Returns the list of checks; each one says what the page and the catalog say."""
    if not page:
        return [{"what": "pagina dell'emittente", "ok": False, "page": None, "catalog": None}]
    f = page["facts"]
    k = e["classification"]
    idx_page = (f.get("indexSeriesName") or {}).get("value") or ""
    norm = lambda x: re.sub(r"[^a-z0-9&]+", " ", x.lower()).replace("treasury bond", "government").replace("govt", "government").replace("bbg ", "bloomberg ")
    words = [w for w in norm(k["indexKey"]).split() if w not in ("&",)]
    use = (f.get("useOfProfitsCode") or {}).get("value")
    hedged = cat.val(e["fund"]["hedged"])
    out = [{"what": "ISIN", "ok": page["isin"] == e["isin"], "page": page["isin"], "catalog": e["isin"]},
           {"what": "classe (copertura del cambio)", "ok": page["hedged"] == bool(hedged), "page": page.get("classLabel") or ("coperta" if page["hedged"] else "non coperta"),
            "catalog": "coperta" if hedged else "non coperta"},
           {"what": "indice", "ok": all(w in norm(idx_page) for w in words), "page": idx_page, "catalog": k["indexKey"]},
           {"what": "politica dei proventi", "ok": norm_dist(use) == cat.val(e["fund"]["distribution"]), "page": use,
            "catalog": cat.val(e["fund"]["distribution"])},
           {"what": "quotazioni", "ok": bool(page["listings"]), "page": ", ".join(f"{l['exchange']} {l['ticker']}" for l in page["listings"]) or None,
            "catalog": None}]
    return out


def approve_added(e, page, verif, report):
    """The user approved the 5 added classes on 4 Nov 2026 on condition that the issuer's documents confirm them.
    Listings on Borsa Italiana / Xetra that the issuer's page shows and the catalog lacks are added (same ISIN: never
    a new row)."""
    checks = verify_added(e, page)
    approved = e["isin"] in ((verif or {}).get("approved") or {}).get("isins", [])
    ok = all(c["ok"] for c in checks)
    e["verification"] = {"checks": checks, "ok": ok, "src": f"ishares_pagina:{e['isin']}" if page else None}
    if approved and ok:
        e["status"], e["statusNote"] = ("approvata dall'utente il 4 nov 2026, verificata sulla pagina dell'emittente",
                                        (e.get("statusNote") or ""))
    elif approved:
        bad = ", ".join(c["what"] for c in checks if not c["ok"])
        e["status"] = "approvata con condizione non ancora soddisfatta"
        e["statusNote"] = f"verifica sulla documentazione dell'emittente non completa: {bad}"
        report.append({"isin": e["isin"], "problema": "classe aggiunta non verificata del tutto", "dettaglio": bad})
    have = {v[1] for v in e.get("_venues", [])}
    for l in (page or {}).get("listings", []):
        v = VENUES.get(l["exchange"])
        if v and v[1] not in have and l.get("ticker"):
            e["_venues"].append((v[0], v[1], l["ticker"], v[2]))
            have.add(v[1])


def inherit_from_twins(entries, uni, twins_of):
    """A class added in phase 6A takes from a sibling class of the SAME fund what belongs to the fund (index,
    replication, number of holdings, countries, sectors), saying so. Never between different funds."""
    for isin in ADDED:
        e = entries.get(isin)
        if not e:
            continue
        fk = cat.val(e["identity"]["fundKey"])
        twin = next((t for t in twins_of.get(fk, []) if t != isin and t in uni and t in entries), None)
        if not twin:
            continue
        t = entries[twin]
        why = f"dalla classe {twin} dello stesso fondo"
        for block, f in (("identity", "index"), ("fund", "replication")):
            if cat.val(e[block].get(f)) is None and cat.val(t[block].get(f)) is not None:
                e[block][f] = dict(t[block][f], note=why)
        if e["fund"].get("replicationDetail") is None:
            e["fund"]["replicationDetail"] = t["fund"].get("replicationDetail")
            e["fund"]["counterpartyRisk"] = t["fund"].get("counterpartyRisk")
        for f in ("holdingsCount", "countries", "sectors"):
            if f not in e["exposure"] and f in t["exposure"]:
                e["exposure"][f] = dict(t["exposure"][f], note=((t["exposure"][f].get("note") or "") + " — " + why).strip(" —"))
        e["identity"]["twin"] = twin
        sf, tf = e["fund"].get("sizeFund") or {}, t["fund"].get("sizeFund") or {}
        if sf.get("v") is not None and sf.get("v") == tf.get("v"):      # the same fund total: it is in the fund's currency
            sf["unit"] = tf.get("unit")
            sf["note"] = f"milioni, patrimonio dell'intero fondo (tutte le classi), valuta {tf.get('unit')}"


def add_listings(entry, yahoo, yahoo_date):
    out = []
    for venue, mic, ticker, suf in entry.pop("_venues"):
        sym = f"{ticker}.{suf}"
        y = yahoo.get(sym)
        l = {"venue": venue, "mic": mic, "ticker": ticker, "yahoo": sym,
             "currency": cat.fv(y.get("currency") if y else None, f"yahoo:{sym}" if y else None, y.get("last") if y else None,
                                "valuta di negoziazione: quella in cui si compra, non l'esposizione"),
             "avgVolume3m": cat.fv(round(y["avgVolume"]) if y else None, f"yahoo:{sym}" if y else None, y.get("last") if y else None,
                                   "quote al giorno, media 3 mesi (Yahoo, indicativo)"),
             "avgTurnover3m": cat.fv(round(y["avgTurnover"]) if y else None, f"yahoo:{sym}" if y else None, y.get("last") if y else None,
                                     "controvalore medio giornaliero, valuta di negoziazione"),
             "zeroVolumeDays": y.get("zeroDays") if y else None, "days": y.get("days") if y else None,
             "quoteAvailable": bool(y)}
        if mic == "ETFP" and entry.get("_book"):
            bk, at = entry["_book"]
            l["book"] = {"phase": bk["phase"], "at": at, "levels": bk["levels"], "volume": bk["volume"], "trades": bk["trades"],
                         "turnover": bk["turnover"], "lastTrade": bk["lastTrade"], "official": bk["official"], "officialDate": bk["officialDate"],
                         "src": f"bi_book:{entry['isin']}", "note": "dati ritardati di 15 minuti"}
            l["spread"] = spread_of(bk, at)
            if l["spread"]:
                l["spread"].update(venue=venue, currency=cat.val(l["currency"]))
        out.append(l)
    entry.pop("_book", None)
    return out


# ---------------------------------------------------------------- main

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--offline", action="store_true", help="niente rete: solo le pagine già salvate")
    ap.add_argument("--book", action="store_true", help="rilegge il book di negoziazione (da usare a mercato aperto)")
    ap.add_argument("--out", default=cat.DIR)
    a = ap.parse_args(argv)
    t0 = time.time()
    universe = cat._read(UNIVERSE)["etfs"]
    uni = {e["isin"]: e for e in universe}
    isins = list(uni) + [i for i in ADDED if i not in uni]
    bad = [i for i in isins if not cat.isin_valid(i)]
    if bad:
        sys.exit(f"ISIN non validi: {bad}")
    ish_raw, ish_date = ishares_list(a.offline)
    ish = {v.get("isin"): v for v in (ish_raw or {}).values() if isinstance(v, dict)}
    holdings = cat._read(HOLDINGS) if os.path.exists(HOLDINGS) else {}
    sources = {
        "justetf_2026-10-08": {"publisher": "justETF (copia salvata in etf_universe.json, non riscaricata)", "kind": "aggregatore",
                               "url": "https://www.justetf.com/it/", "asOf": "2026-10-08", "fetched": "2026-10-08",
                               "note": "dati del profilo ETF; paesi e settori con la data indicata da justETF"},
        "ishares_lista": {"publisher": "iShares (BlackRock), elenco prodotti Italia", "kind": "emittente",
                          "url": "https://www.ishares.com/it/investitore-privato/it/prodotti/etf-investments", "asOf": None, "fetched": ish_date},
        "manuale": {"publisher": "classificazione manuale (etf_catalog_build.py)", "kind": "manuale", "url": None, "asOf": "2026-11-04"},
        "calcolato": {"publisher": "calcolo del catalogo", "kind": "calcolo", "url": None, "asOf": None},
        "isin": {"publisher": "prefisso del codice ISIN", "kind": "calcolo", "url": None, "asOf": None},
    }
    report, entries, stopped = [], {}, None
    # Borsa Italiana pages, one at a time
    bi_data = {}
    for n, isin in enumerate(isins, 1):
        typ = ((uni.get(isin) or {}).get("justetf") or {}).get("legal")
        if typ == "ETC":
            continue
        if stopped:
            break
        try:
            sc = bi_page("scheda", isin, a.offline or stopped, False)
            bk = bi_page("book", isin, a.offline or stopped, a.book)
        except (Refused, requests.RequestException) as e:
            stopped = str(e)
            report.append({"problema": "download interrotto", "dettaglio": stopped})
            break
        bi_data[isin] = (sc, bk)
        if n % 10 == 0:
            print(f"  Borsa Italiana: {n}/{len(isins)}", flush=True)
    for isin in isins:
        sc, bk = bi_data.get(isin, (None, None))
        sch = parse_scheda(page_text(sc[0])) if sc else None
        if sch and sch["isin"] != isin:
            report.append({"isin": isin, "problema": "la pagina di Borsa Italiana riporta un altro ISIN", "valore": sch["isin"]})
            sch = None
        if sc and sch:
            sources[f"bi_scheda:{isin}"] = {"publisher": "Borsa Italiana, scheda ETF", "kind": "borsa", "url": sc[2], "asOf": sc[1], "fetched": sc[1]}
        book = parse_book(page_text(bk[0])) if bk else None
        if bk and book:
            sources[f"bi_book:{isin}"] = {"publisher": "Borsa Italiana, book e dati di mercato (ritardati 15 min)", "kind": "borsa",
                                         "url": bk[2], "asOf": bk[1], "fetched": bk[1], "at": bk[3]}
        if not sch and ((uni.get(isin) or {}).get("justetf") or {}).get("legal") != "ETC":
            report.append({"isin": isin, "problema": "non trovato su Borsa Italiana (ETFplus)"})
        bi_data[isin] = (sch, book, bk[3] if bk else None)
    # issuer pages (phase 6B): one iShares page per class, gentle, stop at the first refusal
    verif = cat._read(VERIFY) if os.path.exists(VERIFY) else {}
    pages = {}
    ish_stopped = None
    for n, isin in enumerate([i for i in isins if ish.get(i)], 1):
        if ish_stopped:
            break
        try:
            pg = ishares_page(isin, ish[isin].get("productPageUrl"), a.offline)
        except (Refused, requests.RequestException) as e:
            ish_stopped = str(e)
            report.append({"problema": "pagine iShares interrotte", "dettaglio": ish_stopped})
            break
        parsed = parse_ishares_page(pg[0]) if pg else None
        if parsed and parsed["isin"] != isin:
            report.append({"isin": isin, "problema": "la pagina iShares riporta un altro ISIN", "valore": parsed["isin"]})
            parsed = None
        if parsed:
            pages[isin] = parsed
            sources[f"ishares_pagina:{isin}"] = {"publisher": "iShares (BlackRock), pagina prodotto della classe", "kind": "emittente",
                                                "url": pg[2], "asOf": pg[1], "fetched": pg[1]}
        if n % 10 == 0:
            print(f"  iShares: {n} pagine", flush=True)
    for isin, v in (verif.get("ter") or {}).items():
        sources[f"verifica:{isin}"] = {"publisher": v["document"], "kind": "emittente (verifica manuale)", "url": v["url"],
                                       "asOf": v["asOf"], "fetched": verif.get("checked")}
    twins_of = {}
    for isin in isins:
        i = ish.get(isin)
        fk = fund_key((i or {}).get("fundName"), ((uni.get(isin) or {}).get("justetf") or {}).get("name"))
        twins_of.setdefault(fk, []).append(isin)
    for isin in isins:
        sch, book, at = bi_data.get(isin, (None, None, None))
        if isin in ADDED and not ish.get(isin) and not sch:
            report.append({"isin": isin, "problema": "classe aggiunta non confermata da nessuna fonte: scartata"})
            continue
        e = build_entry(isin, uni.get(isin), ish.get(isin), sch, book, at, holdings, sources, report, twins_of, pages.get(isin), verif)
        if e:
            if isin in ADDED:
                approve_added(e, pages.get(isin), verif, report)
            entries[isin] = e
    # Yahoo, one symbol at a time
    syms = sorted({f"{t}.{s}" for e in entries.values() for _, _, t, s in e["_venues"]})
    yahoo, ydate = yahoo_listings(syms, a.offline)
    listings = {}
    for isin, e in entries.items():
        listings[isin] = add_listings(e, yahoo, ydate)
        for l in listings[isin]:
            if l["quoteAvailable"]:
                sources[f"yahoo:{l['yahoo']}"] = {"publisher": "Yahoo Finance (quotazioni giornaliere)", "kind": "dati di mercato",
                                                 "url": f"https://finance.yahoo.com/quote/{l['yahoo']}", "asOf": yahoo[l["yahoo"]]["last"], "fetched": ydate}
            elif l["mic"]:
                report.append({"isin": isin, "problema": f"nessuna quotazione Yahoo per {l['yahoo']}"})
    inherit_from_twins(entries, uni, twins_of)
    exposure = {i: e.pop("exposure") for i, e in entries.items()}
    if ish_date:
        dates = sorted({date_num(rd(v, "totalFundSizeInMillionsAsOf")) for v in ish.values() if rd(v, "totalFundSizeInMillionsAsOf")})
        sources["ishares_lista"]["asOf"] = dates[-1] if dates else None
    # duplicates: the same ISIN twice cannot happen (dict); a ticker used by two ISINs is reported
    seen = {}
    for isin, ls in listings.items():
        for l in ls:
            seen.setdefault((l["mic"], l["ticker"]), []).append(isin)
    for (mic, t), owners in seen.items():
        if len(owners) > 1:
            report.append({"problema": "stesso ticker per due ISIN", "mic": mic, "ticker": t, "isin": owners})
    os.makedirs(a.out, exist_ok=True)
    built = datetime.now().isoformat(timespec="minutes")
    notes = ["Disponibilità presso il broker (es. Fineco): non verificata.",
             "Tracking difference e tracking error: non verificabili con le fonti lette.",
             "Lo spread è letto dal book di Borsa Italiana: se letto a mercato chiuso non è rappresentativo."]
    out = {"instruments": {"schema": cat.SCHEMA, "builtAt": built, "notes": notes, "items": entries},
           "listings": {"schema": cat.SCHEMA, "builtAt": built, "items": listings},
           "exposure": {"schema": cat.SCHEMA, "builtAt": built, "items": exposure},
           "sources": {"schema": cat.SCHEMA, "builtAt": built, "items": sources}}
    for k, f in cat.FILES.items():
        with open(os.path.join(a.out, f), "w") as fh:
            json.dump(out[k], fh, ensure_ascii=False, indent=1, sort_keys=False)
    with open(os.path.join(a.out, "controlli.json"), "w") as fh:
        json.dump({"builtAt": built, "seconds": round(time.time() - t0, 1), "stopped": stopped, "problems": report}, fh, ensure_ascii=False, indent=1)
    data = cat.load(a.out)
    s = cat.summary(data)
    print(f"Catalogo scritto in {a.out}: {s['etfs']} ETF UCITS, {s['excluded']} esclusi, {s['listings']} quotazioni, "
          f"completezza media {s['completenessAvg'] * 100:.0f}%, {len(report)} segnalazioni, {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
