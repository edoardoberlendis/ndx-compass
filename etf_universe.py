"""The ETF universe of the Ricerca → ETF tab (plan phase 24): builds etf_universe.json from the justETF profile pages.

    .venv/bin/python etf_universe.py            # rebuild etf_universe.json (about 1 request per ETF, a few minutes)

Only UCITS ETFs and ETCs an Italian investor can buy at Fineco (listed on Borsa Italiana or Xetra), no leveraged or
short products. The list (SEED) is chosen by hand and approved by the user; every number read from justETF is stored
with its source and date, so the page can warn when it is older than 6 months. Fields that are not on justETF
(category, underlying currency, US equivalent used only as a data source) are marked as manual choices.
The user checks the file before it is used.
"""
from __future__ import annotations

import html
import json
import os
import re
import time
from datetime import date

import requests

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "etf_universe.json")
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
      "Accept-Language": "en"}
PAGE = "https://www.justetf.com/en/etf-profile.html?isin={}"


def _text(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def _val(t, testid):
    m = re.search(r'data-testid="' + re.escape(testid) + r'"[^>]*>(.*?)</(?:div|span|td|a)>', t, re.S)
    return _text(m.group(1)) if m else None


def _table(t, section):
    """[(name, percent)] of a justETF holdings table: top-holdings, countries or sectors."""
    i = t.find(f'data-testid="etf-holdings_{section}_table"')
    if i < 0:
        return []
    j = t.find("</table>", i)
    rows = []
    for row in re.findall(r'data-testid="etf-holdings_' + section + r'_row"(.*?)</tr>', t[i:j], re.S):
        name = re.search(r'data-testid="tl_etf-holdings_' + section + r'_(?:value|link)_name"[^>]*>(.*?)</', row, re.S)
        pct = re.search(r'data-testid="tl_etf-holdings_' + section + r'_value_percentage"[^>]*>(.*?)</', row, re.S)
        if name and pct:
            try:
                rows.append((_text(name.group(1)), float(_text(pct.group(1)).rstrip("%").replace(",", ""))))
            except ValueError:
                continue
    return rows


def _listing(t, venue):
    """Ticker on a venue (xmil = Borsa Italiana, xetr = Xetra) from the stock exchange table, or None."""
    m = re.search(r'data-testid="etf-trade-data-panel_row-' + venue + r'_listing"(.*?)</tr>', t, re.S)
    if not m:
        return None
    cells = [_text(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", m.group(1), re.S)]
    return next((c for c in cells[1:3] if re.fullmatch(r"[A-Z0-9]{2,8}", c or "")), None)


def _number(s):
    m = re.search(r"([\d,.]+)", s or "")
    return float(m.group(1).replace(",", "")) if m else None


def fetch(isin):
    """Everything the tab needs from one justETF profile, or {"error": ...}."""
    url = PAGE.format(isin)
    try:
        r = requests.get(url, headers=UA, timeout=25)
    except Exception as e:
        return {"error": str(e), "source": url}
    if r.status_code != 200 or isin not in r.text:
        return {"error": f"HTTP {r.status_code}", "source": url}
    t = r.text
    ter = _val(t, "tl_etf-basics_value_ter")
    size = _val(t, "etf-profile-header_fund-size-value-wrapper")
    return {
        "source": url, "date": date.today().isoformat(),
        "name": (_val(t, "etf-profile-header_etf-name") or "").split(" /*")[0].strip() or None,
        "provider": _val(t, "tl_etf-basics_value_fund-provider"),
        "index": _val(t, "tl_etf-basics_value_index-name"),
        "focus": _val(t, "tl_etf-basics_value_investment-focus"),
        "ter": _number(ter) if ter and "%" in ter else None,
        "sizeEurM": _number(size) if size and "EUR" in size else None,
        "distribution": _val(t, "tl_etf-basics_value_distribution-policy"),
        "replication": _val(t, "tl_etf-basics_value_replication"),
        "replicationMethod": _val(t, "tl_etf-basics_value_replication-method"),
        "legal": _val(t, "tl_etf-basics_value_legal-structure"),
        "strategy": _val(t, "tl_etf-basics_value_strategy-risk"),
        "fundCurrency": _val(t, "tl_etf-basics_value_fund-currency"),
        "hedge": _val(t, "tl_etf-basics_value_currency-hedge"),
        "launch": _val(t, "tl_etf-basics_value_launch-date"),
        "holdingsCount": _number(_val(t, "etf-profile-header_holdings-value")),
        "holdingsDate": _val(t, "tl_etf-holdings_reference-date"),
        "top10": _table(t, "top-holdings"), "countries": _table(t, "countries"), "sectors": _table(t, "sectors"),
        "tickerMI": _listing(t, "xmil"), "tickerDE": _listing(t, "xetr"),
    }


# ---------------------------------------------------------------- the list (phase 24)
# All approved by the user (8 Oct 2026): the phase 24 list without Xtrackers MSCI China, plus BTP, themes and
# countries chosen as the largest and cheapest UCITS on justETF (rule: the biggest fund, unless one at least 0.10
# points cheaper has at least half its size; BTP Amundi 10Y and iShares Core DAX confirmed by the user). usProxy: a US ETF used ONLY as a data source
# (long price history, P/E), never as a product to buy. cur: currency of the underlying ("multi" = several).
def _e(isin, group, cat, cur, proxy, status="approvato", note=None):
    return {"isin": isin, "group": group, "category": cat, "underlyingCurrency": cur, "usProxy": proxy, "status": status, "note": note}


SEED = [
    _e("IE00B4L5Y983", "Globali", "Mondo", "multi", "URTH"),
    _e("IE00BK5BQT80", "Globali", "All-World", "multi", "VT"),
    _e("IE00BJ0KDQ92", "Globali", "Mondo", "multi", "URTH"),
    _e("IE00B3YLTY66", "Globali", "All-World (con small cap)", "multi", "ACWI"),
    _e("IE00B5BMR087", "Aree e paesi", "USA", "USD", "IVV"),
    _e("IE00B3XXRP09", "Aree e paesi", "USA", "USD", "VOO"),
    _e("IE00B3ZW0K18", "Aree e paesi", "USA (cambio coperto)", "EUR (hedged)", "IVV"),
    _e("IE00B53SZB19", "Aree e paesi", "USA Nasdaq-100", "USD", "QQQ"),
    _e("IE0032077012", "Aree e paesi", "USA Nasdaq-100", "USD", "QQQ"),
    _e("IE00BLNMYC90", "Stili e fattori", "USA equal weight", "USD", "RSP"),
    _e("IE00B4K48X80", "Aree e paesi", "Europa", "multi", "IEUR"),
    _e("IE00B53QG562", "Aree e paesi", "Eurozona", "EUR", "EZU"),
    _e("LU0380865021", "Aree e paesi", "Eurozona (Euro Stoxx 50)", "EUR", "FEZ"),
    _e("IE00B53L4X51", "Aree e paesi", "Italia", "EUR", "EWI"),
    _e("IE00B4L5YX21", "Aree e paesi", "Giappone", "JPY", "EWJ"),
    _e("IE00BKM4GZ66", "Aree e paesi", "Emergenti", "multi", "IEMG"),
    _e("IE00BK5BR733", "Aree e paesi", "Emergenti", "multi", "VWO"),
    _e("IE00BJ5JPG56", "Aree e paesi", "Cina", "HKD/CNY", "MCHI"),
    _e("IE00BZCQB185", "Aree e paesi", "India", "INR", "INDA"),
    _e("IE00B3WJKG14", "Settori", "Tecnologia USA", "USD", "XLK"),
    _e("IE00BM67HT60", "Settori", "Tecnologia mondo", "multi", "IXN"),
    _e("IE00BMC38736", "Settori", "Semiconduttori", "multi", "SMH"),
    _e("IE00BM67HK77", "Settori", "Sanità mondo", "multi", "IXJ"),
    _e("IE00B43HR379", "Settori", "Sanità USA", "USD", "XLV"),
    _e("IE00BM67HL84", "Settori", "Finanziari", "multi", "IXG"),
    _e("IE00BM67HM91", "Settori", "Energia", "multi", "IXC"),
    _e("IE00BM67HN09", "Settori", "Beni di prima necessità", "multi", "KXI"),
    _e("IE00BM67HV82", "Settori", "Industriali", "multi", "EXI"),
    _e("IE00BM67HQ30", "Settori", "Utility", "multi", "JXI"),
    _e("IE000YYE6WK5", "Settori", "Difesa", "multi", "ITA"),
    _e("IE00B1XNHC34", "Temi", "Energia pulita", "multi", "ICLN"),
    _e("IE00BP3QZB59", "Stili e fattori", "Valore", "multi", "IVLU"),
    _e("IE00BP3QZ601", "Stili e fattori", "Qualità", "multi", "QUAL"),
    _e("IE00BP3QZ825", "Stili e fattori", "Momentum", "multi", "MTUM"),
    _e("IE00B8FHGS14", "Stili e fattori", "Bassa volatilità", "multi", "ACWV"),
    _e("IE00B8GKDB10", "Stili e fattori", "Dividendi", "multi", "VYMI"),
    _e("IE00BCBJG560", "Stili e fattori", "Small cap", "multi", "VSS"),
    _e("IE00B14X4Q57", "Obbligazionari", "Governativi euro 1-3 anni", "EUR", None),
    _e("LU0290356871", "Obbligazionari", "Governativi euro 1-3 anni", "EUR", None),
    _e("IE00B1FZS913", "Obbligazionari", "Governativi euro 15-30 anni", "EUR", "TLT"),
    _e("IE00B0M62X26", "Obbligazionari", "Inflazione euro", "EUR", "TIP"),
    _e("IE00B3F81R35", "Obbligazionari", "Corporate euro", "EUR", "LQD"),
    _e("IE00BDBRDM35", "Obbligazionari", "Aggregato globale (cambio coperto)", "EUR (hedged)", "BNDW"),
    _e("LU0290358497", "Obbligazionari", "Monetario euro", "EUR", None),
    _e("LU1598691217", "Obbligazionari", "Titoli di Stato italiani (BTP 10 anni)", "EUR", None, "approvato",
       "Tassazione agevolata al 12,5% sulla parte in titoli di Stato: da verificare con Fineco. Alternativa su tutta la curva: iShares Italy Govt Bond (IE00B7LW6Y90, TER 0,20%)."),
    _e("IE00B579F325", "Oro e materie prime", "Oro (ETC)", "USD", "GLD"),
    _e("JE00B1VS3333", "Oro e materie prime", "Argento (ETC)", "USD", "SLV"),
    _e("IE00BDFL4P12", "Oro e materie prime", "Materie prime", "USD", "DBC"),
    # ---- themes (proposed)
    _e("IE00BMYDM794", "Temi", "Idrogeno", "multi", None, "approvato", "Tema giovane: storia dal 2021."),
    _e("IE000M7V94E1", "Temi", "Uranio e nucleare", "multi", "URA", "approvato", "Comprende anche tecnologie nucleari; solo minatori di uranio: Global X Uranium (IE000NDWFGA5, TER 0,65%). Tema giovane: dal 2023."),
    _e("IE00BGV5VN51", "Temi", "Intelligenza artificiale", "multi", "AIQ", "approvato"),
    _e("IE00BYZK4552", "Temi", "Robotica e automazione", "multi", "BOTZ", "approvato"),
    _e("IE00BG0J4C88", "Temi", "Cybersicurezza", "multi", "HACK", "approvato", "Più economico del L&G Cyber Security (TER 0,69%, più grande)."),
    _e("IE000YU9K6K2", "Temi", "Spazio", "multi", "UFO", "approvato", "Tema giovane: dal 2022."),
    _e("LU2023678282", "Temi", "Chip di memoria", "multi", None, "approvato"),
    _e("IE00B1FZS467", "Temi", "Infrastrutture", "multi", "IGF", "approvato"),
    # ---- countries (proposed)
    _e("IE00BHZRR030", "Aree e paesi", "Corea del Sud", "KRW", "EWY", "approvato"),
    _e("IE000CM02H85", "Aree e paesi", "Taiwan", "TWD", "EWT", "approvato", "Più economico dell'iShares MSCI Taiwan (TER 0,74%, più grande); storia dal 2022."),
    _e("DE000A0Q4R85", "Aree e paesi", "Brasile", "BRL", "EWZ", "approvato"),
    _e("LU0476289466", "Aree e paesi", "Messico", "MXN", "EWW", "approvato", "Patrimonio sotto i 300 milioni: il più grande disponibile."),
    _e("IE0005042456", "Aree e paesi", "Regno Unito", "GBP", "EWU", "approvato"),
    _e("LU0977261329", "Aree e paesi", "Svizzera", "CHF", "EWL", "approvato"),
    _e("DE0005933931", "Aree e paesi", "Germania", "EUR", "EWG", "approvato", "Alternativa più economica: Xtrackers DAX (LU0274211480, TER 0,09%)."),
]


def yahoo_ticker(d):
    """The Yahoo ticker with a price history: Borsa Italiana (.MI) first, then Xetra (.DE)."""
    import yfinance as yf
    for t in ([d["tickerMI"] + ".MI"] if d.get("tickerMI") else []) + ([d["tickerDE"] + ".DE"] if d.get("tickerDE") else []):
        try:
            h = yf.Ticker(t).history(period="1mo")
            if len(h) >= 5:
                return t
        except Exception:
            continue
    return None


def build(seed=SEED, pause=1.5):
    out = []
    for s in seed:
        d = fetch(s["isin"])
        y = yahoo_ticker(d) if not d.get("error") else None
        out.append({**s, "yahoo": y, "yahooChecked": date.today().isoformat(), "justetf": d})
        time.sleep(pause)                                # be gentle with the site
    with open(OUT, "w") as f:
        json.dump({"generated": date.today().isoformat(), "etfs": out}, f, ensure_ascii=False, indent=1)
    return out


if __name__ == "__main__":
    build()
