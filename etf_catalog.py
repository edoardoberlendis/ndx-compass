"""Catalogo ETF UCITS (phase 6A): identity of every share class, its listings, costs, structure, exposure and sources.

    .venv/bin/python etf_catalog_build.py            # manual, reproducible update of etf_catalog/ (never scheduled)
    .venv/bin/python etf_catalog.py riepilogo        # what the catalogue contains and how complete it is
    .venv/bin/python etf_catalog.py cerca TESTO      # search by ISIN, ticker, name or issuer

Next to the ETF tab of phase 24 (etf.py, etf_universe.json, etf_buy.py), never in place of it: those files are only
read. The catalogue lives in etf_catalog/ as four separate JSON files written by etf_catalog_build.py:
  strumenti.json    identity of the share class (ISIN), fund data, costs, structure, classification (one per ISIN)
  quotazioni.json   listings: venue, MIC, ticker, trading currency, volumes, book snapshot (many per ISIN)
  esposizione.json  holdings, countries, sectors, bond metrics, each with its date
  fonti.json        every source: who publishes it, address, date of the data, date of download
Returns and prices stay in etf.py (computed once a day): the catalogue does not download anything when a page opens.

Rules:
  * the ISIN identifies the SHARE CLASS: one entry per ISIN, however many tickers, venues or trading currencies it
    has; share classes of the same fund are linked by fundKey, never merged;
  * the trading currency (what I pay) is never the currency exposure (what the fund owns);
  * every value is {"v", "src", "asOf"}: a missing value stays missing (None), never zero or guessed;
  * leveraged, inverse, ETC, ETN and non-UCITS products are kept apart from the ordinary catalogue (EXCLUDED);
  * broker availability (Fineco) is "non verificata" unless a reliable check exists;
  * no buy/sell signal, no score, no winner: the comparison is in etf_comparison.py.
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
from datetime import date

ROOT = os.path.dirname(os.path.abspath(__file__))
DIR = os.path.join(ROOT, "etf_catalog")
FILES = {"instruments": "strumenti.json", "listings": "quotazioni.json", "exposure": "esposizione.json",
         "sources": "fonti.json"}
SCHEMA = 1
# a value older than this is shown as "datato" (days): costs and structure change rarely, holdings and size often
MAX_AGE = {"ter": 400, "size": 45, "holdings": 120, "countries": 200, "quotes": 10, "book": 3, "bond": 45, "kid": 400}
EXCLUDED = {
    "leva": "ETF a leva: amplifica i movimenti giornalieri, non adatto a un catalogo di lungo periodo",
    "inverso": "ETF inverso (short): guadagna quando l'indice scende",
    "etc": "ETC: titolo di debito garantito dal sottostante, non un fondo UCITS",
    "etn": "ETN: titolo di debito dell'emittente, non un fondo UCITS",
    "non_ucits": "fondo non UCITS",
}
ASSET_CLASSES = {"azionario": "Azionari", "obbligazionario": "Obbligazionari", "monetario": "Monetari",
                 "materie_prime": "Materie prime"}
REQUIRED = {   # fields needed for a complete description, by asset class
    "common": ["name", "issuer", "index", "domicile", "ucits", "baseCurrency", "hedged", "distribution", "replication",
               "ter", "sizeFund", "launch", "listings"],
    "azionario": ["holdingsCount", "top10", "countries", "sectors"],
    "obbligazionario": ["duration", "yield", "bondKind", "credit"],
    "monetario": ["bondKind"],
    "materie_prime": [],
}
FAMILY_ORDER = ["globale", "usa", "europa", "emergenti", "paese", "fattori", "tecnologia", "sanita", "finanza", "beni_primari", "industria",
                "energia", "utility_infrastrutture", "governativi_euro", "societarie_euro", "aggregato_globale", "monetario_euro",
                "materie_prime", "metalli"]
LABEL = {"name": "nome", "issuer": "emittente", "index": "indice", "domicile": "domicilio", "ucits": "stato UCITS",
         "baseCurrency": "valuta della classe", "hedged": "copertura valutaria", "distribution": "politica dei proventi",
         "replication": "replica", "ter": "TER", "sizeFund": "patrimonio del fondo", "launch": "data di lancio",
         "listings": "quotazioni", "holdingsCount": "numero di titoli", "top10": "primi 10 titoli",
         "countries": "paesi", "sectors": "settori", "duration": "duration", "yield": "rendimento a scadenza",
         "bondKind": "tipo di obbligazioni", "credit": "qualità del credito"}


# ---------------------------------------------------------------- identifiers

def isin_valid(isin):
    """ISO 6166: 2 letters (country), 9 alphanumerics, 1 check digit (Luhn on the letters turned into numbers)."""
    if not isinstance(isin, str) or not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}[0-9]", isin):
        return False
    digits = "".join(str(int(c, 36)) for c in isin[:-1])
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 0:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return (10 - total % 10) % 10 == int(isin[-1])


def domicile_from_isin(isin):
    """The country prefix of a fund ISIN is the country of the issuing entity (the domicile for UCITS funds)."""
    return {"IE": "Irlanda", "LU": "Lussemburgo", "DE": "Germania", "FR": "Francia", "NL": "Paesi Bassi",
            "JE": "Jersey", "GB": "Regno Unito", "CH": "Svizzera", "AT": "Austria"}.get((isin or "")[:2])


def index_id(name):
    """Normalized index name, to tell whether two funds follow the same index: ("s&p 500", hedged?)."""
    if not name:
        return None, False
    s = name.lower().replace("®", "").replace("™", "")
    hedged = bool(re.search(r"\bhedged|copert", s))
    s = re.sub(r"\((?:eur|usd|gbp|chf)?\s*hedged\)|\beur hedged\b|\bhedged\b", " ", s)
    s = re.sub(r"\b(net total return|total return|net return|trn|tr|nr|index|indice|\(eur\)|\(usd\))\b", " ", s)
    s = s.replace("nasdaq-100", "nasdaq 100").replace("-", " ")
    return re.sub(r"\s+", " ", s).strip(" ()"), hedged


def exclusion(name, product_type=None, ucits=None):
    """Why a product is kept out of the ordinary catalogue (key of EXCLUDED), or None."""
    n = (name or "").lower()
    t = (product_type or "").upper()
    if t == "ETC" or re.search(r"\betc\b", n):
        return "etc"
    if t == "ETN" or re.search(r"\betn\b", n):
        return "etn"
    if re.search(r"\b(short|inverse|bear)\b", n):
        return "inverso"
    if re.search(r"\b(leveraged|[2-5]x|daily 2|ultra)\b", n):
        return "leva"
    if ucits is False:
        return "non_ucits"
    return None


def fv(v, src=None, as_of=None, note=None):
    """A value with its source and date."""
    out = {"v": v, "src": src, "asOf": as_of}
    if note:
        out["note"] = note
    return out


def val(field):
    return field.get("v") if isinstance(field, dict) else field


def age_days(as_of, today=None):
    if not as_of:
        return None
    try:
        return ((today or date.today()) - date.fromisoformat(str(as_of)[:10])).days
    except ValueError:
        return None


def fresh(field, kind, today=None):
    """"aggiornato", "datato", "mancante" or "senza data" for one value."""
    if not isinstance(field, dict) or field.get("v") in (None, [], {}):
        return "mancante"
    a = age_days(field.get("asOf"), today)
    if a is None:
        return "senza data"
    return "datato" if a > MAX_AGE[kind] else "aggiornato"


# ---------------------------------------------------------------- loading (cached on the modification time)

_lock = threading.Lock()
_cache = {"key": None, "data": None}


def _read(path):
    with open(path) as f:
        return json.load(f)


def load(directory=None):
    """The four files joined by ISIN; read again only when a file changes. None if the catalogue was never built."""
    d = directory or DIR
    paths = {k: os.path.join(d, f) for k, f in FILES.items()}
    if not all(os.path.exists(p) for p in paths.values()):
        return None
    key = (d,) + tuple(os.path.getmtime(p) for p in paths.values())
    with _lock:
        if _cache["key"] == key:
            return _cache["data"]
        raw = {k: _read(p) for k, p in paths.items()}
        data = assemble(raw)
        _cache.update(key=key, data=data)
        return data


def assemble(raw, today=None):
    """{"items": {isin: entry}, "excluded": {...}, "sources", "builtAt"} with listings, exposure and completeness."""
    inst = raw["instruments"]
    items, excluded = {}, {}
    for isin, e in inst["items"].items():
        e = dict(e)
        e["listings"] = (raw["listings"].get("items") or {}).get(isin, [])
        e["exposure"] = (raw["exposure"].get("items") or {}).get(isin, {})
        e["completeness"] = completeness(e)
        e["freshness"] = freshness(e, today)
        (excluded if e.get("exclusion") else items)[isin] = e
    return {"schema": inst.get("schema"), "builtAt": inst.get("builtAt"), "items": items, "excluded": excluded,
            "sources": raw["sources"].get("items") or {}, "notes": inst.get("notes") or []}


def _present(e, f):
    ex, ident, fund, costs, bond = e.get("exposure") or {}, e.get("identity") or {}, e.get("fund") or {}, e.get("costs") or {}, e.get("bond") or {}
    if f == "listings":
        return bool(e.get("listings"))
    for block in (ident, fund, costs, bond, ex):
        if f in block:
            v = val(block[f])
            return v not in (None, [], {}, "")
    return False


def completeness(e):
    """Share of the required fields that are present, and the list of the missing ones (in Italian)."""
    ac = (e.get("classification") or {}).get("assetClass")
    need = REQUIRED["common"] + REQUIRED.get(ac, [])
    miss = [f for f in need if not _present(e, f)]
    share = 1 - len(miss) / len(need) if need else 1.0
    state = "completa" if not miss else "parziale" if share >= 0.6 else "insufficiente"
    return {"share": share, "missing": miss, "missingLabels": [LABEL.get(f, f) for f in miss], "state": state}


def freshness(e, today=None):
    c, ex, b, fund = e.get("costs") or {}, e.get("exposure") or {}, e.get("bond") or {}, e.get("fund") or {}
    out = {"ter": fresh(c.get("ter"), "ter", today), "size": fresh(fund.get("sizeFund"), "size", today),
           "holdings": fresh(ex.get("top10"), "holdings", today), "countries": fresh(ex.get("countries"), "countries", today)}
    if (e.get("classification") or {}).get("assetClass") == "obbligazionario":
        out["bond"] = fresh(b.get("duration"), "bond", today)
    out["stale"] = [k for k, s in out.items() if s == "datato"]
    return out


# ---------------------------------------------------------------- list, search, detail

def tickers(e):
    return sorted({(l.get("ticker") or "").upper() for l in e.get("listings") or [] if l.get("ticker")}
                  | {(l.get("yahoo") or "").upper() for l in e.get("listings") or [] if l.get("yahoo")})


def row(e):
    """One compact line of the catalogue list."""
    i, f, c, k = e.get("identity") or {}, e.get("fund") or {}, e.get("costs") or {}, e.get("classification") or {}
    venues = sorted({l.get("venue") for l in e.get("listings") or [] if l.get("venue")})
    return {"isin": e["isin"], "name": val(i.get("name")), "issuer": val(i.get("issuer")), "index": val(i.get("index")),
            "assetClass": k.get("assetClass"), "family": k.get("family"), "familyLabel": k.get("familyLabel"), "exposure": k.get("exposure"),
            "category": k.get("label"), "theme": k.get("theme", False), "ter": val(c.get("ter")),
            "distribution": val(f.get("distribution")), "hedged": val(f.get("hedged")),
            "replication": val(f.get("replication")), "baseCurrency": val(f.get("baseCurrency")),
            "domicile": val(i.get("domicile")), "sizeFund": val(f.get("sizeFund")), "tickers": tickers(e),
            "venues": venues, "completeness": e["completeness"]["state"], "completenessShare": e["completeness"]["share"],
            "stale": e["freshness"]["stale"], "status": e.get("status"), "fundKey": val(i.get("fundKey"))}


def norm(s):
    return re.sub(r"[^a-z0-9&]+", " ", (s or "").lower()).strip()


def search(data, q, filters=None):
    """Rows matching the text (ISIN, ticker, name, fund, issuer, index, category) and the filters."""
    q = norm(q)
    words = q.split()
    out = []
    for e in data["items"].values():
        r = row(e)
        if words:
            hay = " ".join(norm(x) for x in [r["isin"], r["name"], r["issuer"], r["index"], r["category"],
                                             val((e.get("identity") or {}).get("fundName"))] + r["tickers"])
            exact = q.upper() in (r["isin"], *r["tickers"])
            if not exact and not all(w in hay for w in words):
                continue
        ok = True
        for k, want in (filters or {}).items():
            if want in (None, "", "all"):
                continue
            have = r.get(k)
            if k == "hedged":
                ok = ok and (bool(have) == (want in (True, "true", "1", "si")))
            elif str(have) != str(want):
                ok = False
        if ok:
            out.append(r)
    return sorted(out, key=lambda r: (list(ASSET_CLASSES).index(r["assetClass"]) if r["assetClass"] in ASSET_CLASSES else 9,
                                      FAMILY_ORDER.index(r["family"]) if r["family"] in FAMILY_ORDER else 99,
                                      r["category"] or "", r["name"] or ""))


def find(data, key):
    """The entry for an ISIN or a ticker (any venue), or None. A ticker shared by two ISINs is ambiguous: None."""
    if not data or not key:
        return None
    k = key.strip().upper()
    if k in data["items"]:
        return data["items"][k]
    hits = [e for e in data["items"].values() if k in tickers(e)]
    return hits[0] if len(hits) == 1 else None


def facets(data):
    from collections import Counter
    rows = [row(e) for e in data["items"].values()]
    return {"assetClass": dict(Counter(r["assetClass"] for r in rows)), "family": dict(Counter(r["family"] for r in rows)),
            "issuer": dict(Counter(r["issuer"] for r in rows)), "distribution": dict(Counter(r["distribution"] for r in rows)),
            "replication": dict(Counter(r["replication"] for r in rows))}


def summary(data):
    rows = [row(e) for e in data["items"].values()]
    n = len(rows)
    avg = sum(r["completenessShare"] for r in rows) / n if n else 0
    from collections import Counter
    return {"etfs": n, "excluded": len(data["excluded"]), "completenessAvg": avg,
            "states": dict(Counter(r["completeness"] for r in rows)), "builtAt": data["builtAt"],
            "listings": sum(len(e.get("listings") or []) for e in data["items"].values()),
            "staleAny": sum(1 for r in rows if r["stale"])}


def main(argv):
    data = load()
    if not data:
        print("Catalogo non ancora costruito: .venv/bin/python etf_catalog_build.py")
        return
    cmd = argv[1] if len(argv) > 1 else "riepilogo"
    if cmd == "riepilogo":
        s = summary(data)
        print(f"Catalogo del {s['builtAt']}: {s['etfs']} ETF UCITS, {s['listings']} quotazioni, {s['excluded']} esclusi")
        print(f"Completezza media {s['completenessAvg'] * 100:.0f}% · {s['states']} · con dati datati: {s['staleAny']}")
        for r in search(data, ""):
            print(f"{r['isin']} {r['category'] or '':32s} {(r['name'] or '')[:48]:48s} TER {r['ter']} {r['completeness']}")
    elif cmd == "cerca" and len(argv) > 2:
        for r in search(data, " ".join(argv[2:])):
            print(r["isin"], r["name"], r["tickers"])
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv)
