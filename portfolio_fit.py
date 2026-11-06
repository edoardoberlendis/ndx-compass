"""Compatibilità con il portafoglio (phase 7B, model P1): how a candidate stock or ETF fits the positions already held.

Pure functions: they receive the positions, the public ETF catalogue, the public data of the stocks and (optionally)
price series, and return numbers with their explanation. Nothing here reads a file, downloads or writes: the server
passes the data (server.portfolio_fit_inputs), and only after an explicit action of the user in the page.

Two judgements stay apart: the Decision Desk (D2) says whether an instrument deserves attention; this module only
describes how it would change the composition of a portfolio. It never changes a D2 state, never gives a single
compatibility score, never says buy or sell, never computes a probability, a VaR or a future return.

Rules of the numbers (shown in the page):
- values in different currencies are never added: every value is converted to EUR with a declared rate (rate, date,
  source) or left out of the totals with the reason; a stale price or rate makes the value "indicativo";
- the trading currency of an ETF is not its economic currency: the economic currency comes from the countries of its
  holdings (estimate) or from a declared currency hedge;
- look-through: the value of an ETF is SPLIT among its known holdings (first 10, with their date), never added a second
  time; the weight beyond the known holdings stays "non analizzabile", never zero and never redistributed;
- every breakdown keeps its unclassified part visible: no 100% is built by spreading missing data;
- concentration is shown as numbers; it becomes "oltre il limite" only against a limit set by the user (none by
  default: "non configurato");
- risk: historical volatility, drawdown and correlations only with enough aligned prices (otherwise "Non calcolabile
  con affidabilità sufficiente"); duration only on the bond part with a known duration; stress tests are deterministic
  "what if X moved by Y%", never forecasts.
"""
from __future__ import annotations

import math
import re
from datetime import date

VERSION = "P1"
DISCLAIMER = ("Analisi descrittiva della composizione, non consulenza finanziaria: nessuna indicazione di acquisto o "
              "vendita, nessun ordine, nessuna probabilità, nessun rendimento futuro. La compatibilità con il portafoglio "
              "è un giudizio separato dallo stato del Decision Desk e non lo cambia.")
STALE_DAYS = 5          # a price or rate older than this (calendar days) makes the value "indicativo" (data note, not a risk rule)
MIN_DAYS, MIN_WEEKS = 126, 26      # as risk.py: about 6 months of aligned daily prices, 26 common weeks for a correlation
JUMP_UP, JUMP_DOWN = 1.5, -0.75    # as risk.py: a daily move beyond these is a wrong price history
STRESS = [("azioni", -10.0), ("azioni", -20.0), ("tassi", 1.0), ("usd", -10.0)]
LIMIT_KEYS = {"position": "singola posizione", "company": "singola società (guardando dentro gli ETF)",
              "sector": "singolo settore", "country": "singolo paese", "currency": "singola valuta economica"}

CLASS_LABEL = {"azione": "Azione", "etf": "ETF UCITS", "etc_etn": "ETC/ETN", "liquidita": "Liquidità", "sconosciuto": "Non identificato"}
ASSET = {"azionario": "Azioni", "obbligazionario": "Obbligazioni", "monetario": "Monetario", "materie_prime": "Materie prime"}
UNCLASSIFIED = "Non classificato"
OTHER_SECTORS, OTHER_COUNTRIES, OTHER_CCY = "Altri settori (non dettagliati)", "Altri paesi (non dettagliati)", "Altre valute (non dettagliate)"
GENERIC = {UNCLASSIFIED, OTHER_SECTORS, OTHER_COUNTRIES, OTHER_CCY, "Obbligazioni", "Liquidità", "Materie prime", "Monetario",
           "Non applicabile"}

# sector names of the different sources (justETF for the ETFs, ICB for the Nasdaq-100, Yahoo for other stocks) -> one
# Italian label. The taxonomies are not identical: the comparison between stocks and ETFs is indicative (said in the page).
SECTOR_IT = {"Technology": "Tecnologia", "Finance": "Finanza", "Financials": "Finanza", "Financial Services": "Finanza",
             "Industrials": "Industria", "Healthcare": "Sanità", "Health Care": "Sanità",
             "Consumer Non-Cyclicals": "Beni di prima necessità", "Consumer Staples": "Beni di prima necessità",
             "Consumer Defensive": "Beni di prima necessità", "Consumer Cyclicals": "Consumi discrezionali",
             "Consumer Discretionary": "Consumi discrezionali", "Consumer Cyclical": "Consumi discrezionali",
             "Utilities": "Utility", "Energy": "Energia", "Non-Energy Materials": "Materiali di base",
             "Basic Materials": "Materiali di base", "Business Services": "Servizi alle imprese",
             "Telecommunication": "Telecomunicazioni", "Telecommunications": "Telecomunicazioni",
             "Communication Services": "Telecomunicazioni", "Consumer Services": "Servizi al consumatore",
             "Real Estate": "Immobiliare", "Sovereign": "Titoli di Stato", "Non-Corporate": "Emittenti non societari",
             "Other": OTHER_SECTORS}
COUNTRY_IT = {"United States": "USA", "Japan": "Giappone", "United Kingdom": "Regno Unito", "Canada": "Canada",
              "Taiwan": "Taiwan", "Ireland": "Irlanda", "Netherlands": "Paesi Bassi", "Switzerland": "Svizzera",
              "Germany": "Germania", "France": "Francia", "Spain": "Spagna", "Italy": "Italia", "Luxembourg": "Lussemburgo",
              "South Korea": "Corea del Sud", "China": "Cina", "India": "India", "Brazil": "Brasile", "Hong Kong": "Hong Kong",
              "Singapore": "Singapore", "Denmark": "Danimarca", "Israel": "Israele", "Mexico": "Messico",
              "Cayman Islands": "Isole Cayman", "Sweden": "Svezia", "Belgium": "Belgio", "Australia": "Australia",
              "Bermuda": "Bermuda", "Other": OTHER_COUNTRIES}
CCY_IT = {"altre": OTHER_CCY}


def company_key(name):
    from etf_holdings import company_key as ck          # the same normalisation used by the ETF holdings
    return ck(name or "")


def _d(x):
    try:
        return date.fromisoformat(str(x)[:10])
    except (TypeError, ValueError):
        return None


def _age(d, as_of):
    a, b = _d(d), _d(as_of)
    return (b - a).days if a and b else None


def _v(block, key):
    x = (block or {}).get(key)
    return x.get("v") if isinstance(x, dict) else x


def _asof(block, key):
    x = (block or {}).get(key)
    return x.get("asOf") if isinstance(x, dict) else None


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _pct(x, d=1):
    return None if x is None else round(x, d)


def it(x, d=1):
    return "n.d." if x is None else f"{x:,.{d}f}".replace(",", "§").replace(".", ",").replace("§", ".")


# ---------------------------------------------------------------- 1. identity and normalisation

def catalog_index(catalog):
    """ISIN and ticker lookups of the public catalogue (items and excluded products such as ETCs)."""
    items, excluded = (catalog or {}).get("items") or {}, (catalog or {}).get("excluded") or {}
    by_ticker = {}
    for isin, e in list(items.items()) + list(excluded.items()):
        for l in e.get("listings") or []:
            for t in (l.get("yahoo"), l.get("ticker")):
                if t:
                    by_ticker.setdefault(t.upper(), isin)
                    by_ticker.setdefault(t.upper().split(".")[0], isin)
    return {"items": items, "excluded": excluded, "byTicker": by_ticker}


def classify(raw, idx):
    """(class, catalogue entry or None, how it was recognised). Never a guessed match."""
    kind = (raw.get("kind") or "").strip().lower()
    isin = (raw.get("isin") or "").strip().upper() or None
    how = None
    if not isin and raw.get("ticker") and kind not in ("azione", "azioni", "liquidita", "liquidità"):
        isin = idx["byTicker"].get(raw["ticker"].upper()) or idx["byTicker"].get(raw["ticker"].upper().split(".")[0])
        how = f"ISIN dal ticker {raw['ticker']} (quotazione del catalogo)" if isin else None
    if kind in ("liquidita", "liquidità", "cash"):
        return "liquidita", None, isin, "liquidità dichiarata"
    if isin and isin in idx["items"]:
        return "etf", idx["items"][isin], isin, how or "ISIN del catalogo ETF UCITS"
    if isin and isin in idx["excluded"]:
        e = idx["excluded"][isin]
        return ("etc_etn" if e.get("exclusion") in ("etc", "etn") else "sconosciuto"), e, isin, "ISIN escluso dal catalogo ordinario"
    if kind in ("etc", "etn"):
        return "etc_etn", None, isin, "tipo dichiarato (fuori catalogo)"
    if kind.startswith("azion") or kind in ("stock", "share"):
        return "azione", None, isin, "tipo dichiarato «azione»"
    if kind == "etf":
        return "etf", None, isin, "ETF fuori catalogo: composizione non disponibile"
    return "sconosciuto", None, isin, "strumento non riconosciuto con affidabilità: nessuna corrispondenza inventata"


def to_eur(amount, ccy, fx, as_of):
    """(EUR amount, conversion note, stale flag) or (None, reason, None). fx: {ccy: {"rate": units per 1 EUR, "date",
    "source"}}. GBp (pence) is divided by 100 first. Never a guessed rate."""
    if amount is None:
        return None, "valore non disponibile", None
    ccy = (ccy or "").strip()
    if ccy == "GBp" or ccy == "GBX":
        amount, ccy = amount / 100, "GBP"
    ccy = ccy.upper()
    if ccy == "EUR":
        return amount, None, False
    r = (fx or {}).get(ccy)
    if not r or not _num(r.get("rate")) or r["rate"] <= 0:
        return None, f"cambio EUR/{ccy} non disponibile: valore non convertito e fuori dai totali", None
    age = _age(r.get("date"), as_of)
    stale = age is None or age > STALE_DAYS
    note = f"convertito con EUR/{ccy} {it(r['rate'], 4)} del {r.get('date') or 'data n.d.'} ({r.get('source') or 'fonte n.d.'})"
    return amount / r["rate"], note, stale


def normalize(book, catalog):
    """Positions of a portfolio in one coherent form. book = {"asOf", "fx", "positions": [raw]}; raw = {"id", "name",
    "isin"?, "ticker"?, "kind", "qty"?, "price"?, "priceCurrency"?, "priceDate"?, "value"?, "valueCurrency"?,
    "sector"?, "country"?, "currency"? (economic currency of a stock, if known)}. Two listings of the same ISIN become
    one instrument (listings kept); values in EUR only through a declared rate."""
    as_of = book.get("asOf")
    idx = catalog_index(catalog)
    merged, order, notes = {}, [], []
    for raw in book.get("positions") or []:
        cls, entry, isin, how = classify(raw, idx)
        if raw.get("qty") is not None and raw.get("price") is not None:
            local, ccy = raw["qty"] * raw["price"], raw.get("priceCurrency") or raw.get("valueCurrency")
            basis = "quantità × prezzo"
        else:
            local, ccy = raw.get("value"), raw.get("valueCurrency") or raw.get("priceCurrency")
            basis = "valore dichiarato"
        eur, conv, fx_stale = to_eur(local, ccy, book.get("fx"), as_of)
        age = _age(raw.get("priceDate"), as_of)
        price_stale = cls != "liquidita" and (age is None or age > STALE_DAYS)
        listing = {"ticker": raw.get("ticker"), "currency": (raw.get("priceCurrency") or ccy), "qty": raw.get("qty"),
                   "price": raw.get("price"), "priceDate": raw.get("priceDate"), "valueLocal": local, "valueCurrency": ccy,
                   "valueEUR": eur, "conversion": conv or raw.get("conversionNote"), "basis": basis, "id": raw.get("id")}
        key = f"{cls}:{isin}" if isin and cls in ("etf", "etc_etn", "azione") else f"{cls}:{raw.get('id') or raw.get('name')}"
        if key in merged:
            m = merged[key]
            m["listings"].append(listing)
            m["ids"].append(raw.get("id"))
            if eur is None:                    # a listing without a rate: the instrument is only partly valued
                m["unvalued"].append(conv)
            else:
                m["valueEUR"] = (m["valueEUR"] or 0) + eur
            m["indicative"] = m["indicative"] or bool(fx_stale) or price_stale
            notes.append(f"{m['name']}: {len(m['listings'])} quotazioni dello stesso ISIN {isin} unite in un solo strumento")
            continue
        name = raw.get("name") or (_v((entry or {}).get("identity"), "name")) or raw.get("ticker") or isin or "senza nome"
        m = {"id": raw.get("id") or key, "ids": [raw.get("id")], "key": key, "class": cls, "classLabel": CLASS_LABEL[cls],
             "name": name, "isin": isin, "ticker": raw.get("ticker"), "recognised": how, "entry": entry,
             "listings": [listing], "valueEUR": eur, "unvalued": [] if eur is not None else [conv],
             "indicative": bool(fx_stale) or price_stale,
             "meta": {k: raw.get(k) for k in ("sector", "country", "currency") if raw.get(k)},
             "company": company_key(name) if cls == "azione" else None,
             "leveraged": bool(re.search(r"\b\d+x\b|leverag|\bshort\b|\bbear\b|\bbull\b", name, re.I))}
        if cls == "etf" and entry is None:
            m["notes"] = ["ETF fuori catalogo: paesi, settori e partecipazioni non disponibili"]
        merged[key] = m
        order.append(key)
    out = [merged[k] for k in order]
    total = sum(x["valueEUR"] for x in out if x["valueEUR"] is not None)
    for x in out:
        x["weight"] = x["valueEUR"] / total * 100 if total and x["valueEUR"] is not None else None
    return {"asOf": as_of, "positions": out, "totalEUR": total, "notes": notes,
            "unvalued": [{"name": x["name"], "why": "; ".join(u for u in x["unvalued"] if u),
                      "partial": x["valueEUR"] is not None} for x in out if x["unvalued"]],
            "indicative": [x["name"] for x in out if x["indicative"]]}


# ---------------------------------------------------------------- 2. composition of one instrument

def _split(rows, key, labels, other, scale=100.0):
    """{label: share 0-1} from [{"name"/"currency", "weight" %}], with the unexplained rest as UNCLASSIFIED."""
    out = {}
    for r in rows or []:
        w = r.get("weight")
        if not _num(w) or w <= 0:
            continue
        lab = labels.get(r.get(key), r.get(key)) or UNCLASSIFIED
        out[lab] = out.get(lab, 0) + w / scale
    s = sum(out.values())
    if s > 1.0001:                                     # rounding of the source: scale down, never above 100%
        out = {k: v / s for k, v in out.items()}
    elif s < 0.9999:
        out[UNCLASSIFIED] = out.get(UNCLASSIFIED, 0) + (1 - s)
    return out


def profile(inst, stock_meta=None):
    """Composition of one instrument as shares of its value: asset class, sector, country, economic currency and the
    companies inside, each with its quality (osservato / stima / non disponibile) and dates."""
    cls, e = inst["class"], inst.get("entry") or {}
    meta = dict((stock_meta or {}).get(inst.get("ticker") or "", {}), **(inst.get("meta") or {}))
    p = {"assetClass": {UNCLASSIFIED: 1}, "sector": {UNCLASSIFIED: 1}, "country": {UNCLASSIFIED: 1},
         "currency": {UNCLASSIFIED: 1}, "companies": {}, "covered": 0.0, "lookthrough": "non disponibile",
         "quality": {"sector": "non disponibile", "country": "non disponibile", "currency": "non disponibile"},
         "dates": {}, "notes": list(inst.get("notes") or []), "duration": None, "hedged": None, "trading": None,
         "domicile": None, "issuer": None, "exposureKey": None, "fundKey": None}
    if cls == "liquidita":
        ccy = (inst["listings"][0].get("valueCurrency") or "EUR").upper()
        p.update(assetClass={"Liquidità": 1}, sector={"Liquidità": 1}, country={"Liquidità": 1}, currency={ccy: 1},
                 lookthrough="non applicabile", quality={"sector": "osservato", "country": "osservato", "currency": "osservato"})
        return p
    if cls == "azione":
        sec = SECTOR_IT.get(meta.get("sector"), meta.get("sector"))
        cou = COUNTRY_IT.get(meta.get("country"), meta.get("country"))
        ccy = meta.get("currency") or inst["listings"][0].get("currency")
        p.update(assetClass={"Azioni": 1}, sector={sec or UNCLASSIFIED: 1}, country={cou or UNCLASSIFIED: 1},
                 currency={(ccy or UNCLASSIFIED).upper() if ccy else UNCLASSIFIED: 1},
                 companies={inst["company"]: {"name": inst["name"], "w": 1.0}} if inst.get("company") else {},
                 covered=1.0 if inst.get("company") else 0.0, lookthrough="diretta",
                 quality={"sector": "osservato" if sec else "non disponibile", "country": "osservato" if cou else "non disponibile",
                          "currency": "stima" if ccy else "non disponibile"}, trading=ccy)
        if ccy:
            p["notes"].append(f"valuta economica stimata con la valuta di quotazione ({ccy}): i ricavi della società possono essere in altre valute")
        return p
    if not e:
        if cls == "etc_etn":
            p.update(assetClass={"Materie prime": 1}, sector={"Materie prime": 1}, country={"Non applicabile": 1},
                     lookthrough="non applicabile")
        return p
    ident, fund, cl, ex, bond = e.get("identity") or {}, e.get("fund") or {}, e.get("classification") or {}, e.get("exposure") or {}, e.get("bond") or {}
    ac = ASSET.get(cl.get("assetClass")) or ("Materie prime" if cls == "etc_etn" else UNCLASSIFIED)
    hedged = _v(fund, "hedged")
    p.update(assetClass={ac: 1}, hedged=hedged, domicile=_v(ident, "domicile"), issuer=_v(ident, "issuer"),
             exposureKey=cl.get("exposure"), fundKey=_v(ident, "fundKey"),
             trading=sorted({(_v(l, "currency") or "") for l in e.get("listings") or [] if _v(l, "currency")}))
    if ac == "Azioni":
        secs = _v(ex, "sectors")
        if secs:
            p["sector"], p["quality"]["sector"] = _split(secs, "name", SECTOR_IT, OTHER_SECTORS), "osservato"
            p["dates"]["sectors"] = _asof(ex, "sectors")
    else:
        p["sector"] = {ac: 1}
        p["quality"]["sector"] = "osservato"
    cous = _v(ex, "countries")
    if cous:
        p["country"], p["quality"]["country"] = _split(cous, "name", COUNTRY_IT, OTHER_COUNTRIES), "osservato"
        p["dates"]["countries"] = _asof(ex, "countries")
    elif cls == "etc_etn":
        p["country"] = {"Non applicabile": 1}
    base = _v(fund, "baseCurrency")
    if hedged:
        p["currency"] = {(base or "EUR").upper(): 1}
        p["quality"]["currency"] = "osservato"
        p["notes"].append(f"classe con copertura del cambio verso {base or 'EUR'}: il rischio valutario dei titoli è coperto (copertura dichiarata, non perfetta)")
    else:
        cx = _v(ex, "currencyExposure")
        if cx:
            p["currency"] = _split([dict(r, currency=r.get("currency", "").replace(" (coperta)", "")) for r in cx],
                                   "currency", CCY_IT, OTHER_CCY)
            p["quality"]["currency"] = "stima"
            p["dates"]["currency"] = _asof(ex, "currencyExposure")
            p["notes"].append("valuta economica stimata dai paesi dei titoli, non dalla valuta in cui si compra l'ETF")
        elif ac == "Obbligazioni" and base:
            p["currency"] = {base.upper(): 1}
            p["quality"]["currency"] = "stima"
            p["notes"].append(f"valuta economica stimata con la valuta di base del fondo ({base})")
    top = _v(ex, "top10")
    if ac == "Azioni" and top:
        p["companies"] = {}
        for h in top:
            k = company_key(h.get("name")) or h.get("key")       # one rule for stocks and holdings (ADR = local share)
            if k and _num(h.get("weight")):
                c = p["companies"].setdefault(k, {"name": h.get("name"), "w": 0.0})
                c["w"] += h["weight"]
        p["covered"] = min(1.0, sum(c["w"] for c in p["companies"].values()))
        n = _v(ex, "holdingsCount")
        p["lookthrough"] = "completa" if _num(n) and n <= len(top) else "parziale (primi 10 titoli)"
        p["dates"]["holdings"] = _asof(ex, "top10Weight") or _asof(ex, "top10")
    elif ac == "Azioni":
        p["lookthrough"] = "non disponibile"
    else:
        p["lookthrough"] = "non applicabile"
    if ac == "Obbligazioni":
        d = _v(bond, "duration")
        if _num(d):
            p["duration"] = d
            p["dates"]["duration"] = _asof(bond, "duration")
    stale = (e.get("freshness") or {}).get("stale") or []
    if stale:
        p["notes"].append("dati del fondo datati secondo le regole del catalogo: " + ", ".join(stale)
                          + " (la composizione potrebbe essere cambiata)")
    p["stale"] = list(stale)
    return p


# ---------------------------------------------------------------- 3. whole-portfolio analysis

def analyse(norm, stock_meta=None, limits=None, series=None):
    """Concentration, look-through, breakdowns, risk and stress of a normalised portfolio (normalize)."""
    pos = [x for x in norm["positions"]]
    total = norm["totalEUR"] or 0.0
    for x in pos:
        x["profile"] = profile(x, stock_meta)
    valued = [x for x in pos if x["valueEUR"] is not None]
    dims = {}
    for dim in ("assetClass", "sector", "country", "currency"):
        agg = {}
        for x in valued:
            q = x["profile"]["quality"].get(dim, "osservato")
            for lab, sh in x["profile"][dim].items():
                a = agg.setdefault(lab, {"value": 0.0, "quality": {}})
                a["value"] += x["valueEUR"] * sh
                qq = "non disponibile" if lab == UNCLASSIFIED else q
                a["quality"][qq] = a["quality"].get(qq, 0) + x["valueEUR"] * sh
        rows = [{"label": k, "valueEUR": v["value"], "pct": v["value"] / total * 100 if total else None,
                 "quality": {q: round(w / v["value"] * 100, 1) for q, w in v["quality"].items()} if v["value"] else {},
                 "generic": k in GENERIC} for k, v in agg.items()]
        rows.sort(key=lambda r: (r["label"] == UNCLASSIFIED, -r["valueEUR"]))
        dims[dim] = rows
    # positions
    ws = sorted([x["weight"] for x in valued if x["weight"] is not None], reverse=True)
    eff = 1 / sum((w / 100) ** 2 for w in ws) if ws else None
    conc = {"top": [{"id": x["id"], "name": x["name"], "class": x["classLabel"], "weight": x["weight"]}
                    for x in sorted(valued, key=lambda x: -(x["weight"] or 0))][:10],
            "top5": sum(ws[:5]) if ws else None, "top10": sum(ws[:10]) if ws else None, "n": len(ws),
            "effective": eff,
            "effectiveText": "numero equivalente di posizioni di pari peso (1 ÷ somma dei pesi al quadrato): descrittivo"}
    look = lookthrough(valued, total)
    issuers = {}
    for x in valued:
        if x["class"] in ("etf", "etc_etn") and x["profile"].get("issuer"):
            issuers[x["profile"]["issuer"]] = issuers.get(x["profile"]["issuer"], 0) + x["valueEUR"]
    conc["fundIssuers"] = sorted(({"issuer": k, "pct": v / total * 100} for k, v in issuers.items()), key=lambda r: -r["pct"])
    cur_top = next((r for r in dims["currency"] if r["label"] not in GENERIC), None)
    conc["topCurrency"] = {"label": cur_top["label"], "pct": cur_top["pct"], "quality": cur_top["quality"]} if cur_top else None
    out = {"version": VERSION, "asOf": norm["asOf"], "totalEUR": total, "positions": [public_position(x) for x in pos],
           "notes": norm["notes"], "unvalued": norm["unvalued"], "indicative": norm["indicative"],
           "breakdown": dims, "concentration": conc, "lookthrough": look,
           "duration": duration(valued, total), "stress": stress(valued, total), "dates": key_dates(pos, norm["asOf"]),
           "taxonomy": "Settori: azioni dalla classificazione del Nasdaq (ICB) o di Yahoo, ETF da justETF: classificazioni "
                       "diverse, il confronto tra azioni ed ETF è indicativo.",
           "disclaimer": DISCLAIMER}
    out["limits"] = check_limits(out, limits)
    out["risk"] = risk(valued, series, len(norm["unvalued"])) if series is not None else {"state": "non calcolato", "why": "serie storiche non fornite"}
    out["missing"] = missing(out, valued)
    return out


def public_position(x):
    p = x["profile"]
    return {"id": x["id"], "name": x["name"], "class": x["class"], "classLabel": x["classLabel"], "isin": x["isin"],
            "ticker": x["ticker"], "valueEUR": x["valueEUR"], "weight": x["weight"], "indicative": x["indicative"],
            "recognised": x["recognised"], "listings": x["listings"], "unvalued": x["unvalued"],
            "assetClass": next(iter(p["assetClass"])), "lookthrough": p["lookthrough"], "covered": p["covered"],
            "hedged": p["hedged"], "trading": p["trading"], "domicile": p["domicile"], "issuer": p["issuer"],
            "duration": p["duration"], "dates": p["dates"], "notes": p["notes"], "exposureKey": p["exposureKey"],
            "leveraged": x["leveraged"]}


def lookthrough(valued, total):
    """Companies held directly and inside the ETFs: the ETF value is split among its known holdings (never added twice).
    Returns the companies, the overlaps, the ETF-ETF overlap of the known holdings and the share of the portfolio that
    cannot be analysed at company level."""
    comp, analysed, beyond, no_data, non_equity = {}, 0.0, 0.0, 0.0, 0.0
    beyond_items, nodata_items = [], []
    for x in valued:
        p, v = x["profile"], x["valueEUR"]
        equity = p["assetClass"].get("Azioni", 0)
        non_equity += v * (1 - equity)
        if not equity:
            continue
        if p["lookthrough"] in ("non disponibile",) or not p["companies"]:
            no_data += v * equity
            nodata_items.append(x["name"])
            continue
        for k, c in p["companies"].items():
            e = comp.setdefault(k, {"key": k, "name": c["name"], "direct": 0.0, "indirect": {}, "partial": False})
            amt = v * equity * c["w"]
            if x["class"] == "azione":
                e["direct"] += amt
                e["name"] = x["name"]
            else:
                e["indirect"][x["name"]] = e["indirect"].get(x["name"], 0) + amt
                e["partial"] = e["partial"] or p["lookthrough"] != "completa"
            analysed += amt
        rest = v * equity * (1 - p["covered"])
        if rest > 1e-9:
            beyond += rest
            beyond_items.append({"name": x["name"], "covered": p["covered"] * 100, "date": p["dates"].get("holdings")})
    rows = []
    for e in comp.values():
        tot = e["direct"] + sum(e["indirect"].values())
        rows.append({"key": e["key"], "name": e["name"], "directEUR": e["direct"], "indirectEUR": sum(e["indirect"].values()),
                     "via": [{"fund": k, "valueEUR": v, "pct": v / total * 100 if total else None} for k, v in e["indirect"].items()],
                     "totalEUR": tot, "pct": tot / total * 100 if total else None,
                     "kind": "limite inferiore" if e["partial"] else "osservata",
                     "sources": int(e["direct"] > 0) + len(e["indirect"])})
    rows.sort(key=lambda r: -r["totalEUR"])
    overlaps = [r for r in rows if r["sources"] >= 2]
    funds = [x for x in valued if x["class"] in ("etf", "etc_etn") and x["profile"]["companies"]]
    pairs = []
    for i, a in enumerate(funds):
        for b in funds[i + 1:]:
            common = set(a["profile"]["companies"]) & set(b["profile"]["companies"])
            if common:
                pairs.append({"a": a["name"], "b": b["name"], "common": sorted(common),
                              "names": [a["profile"]["companies"][k]["name"] for k in sorted(common)],
                              "overlapKnown": sum(min(a["profile"]["companies"][k]["w"], b["profile"]["companies"][k]["w"])
                                                  for k in common) * 100,
                              "dates": [a["profile"]["dates"].get("holdings"), b["profile"]["dates"].get("holdings")]})
    pct = lambda v: v / total * 100 if total else None
    return {"companies": rows[:25], "overlaps": overlaps, "fundPairs": pairs,
            "coverage": {"analysed": pct(analysed), "beyondKnown": pct(beyond), "noData": pct(no_data), "nonEquity": pct(non_equity),
                         "check": pct(analysed + beyond + no_data + non_equity)},
            "beyondItems": beyond_items, "noDataItems": nodata_items,
            "rule": ("Il valore di ogni ETF è ripartito tra i titoli noti (primi 10, con la loro data): non è sommato una "
                     "seconda volta. La parte oltre i titoli noti resta «non analizzabile»: non vale zero, è solo "
                     "sconosciuta. Con i soli primi 10 titoli l'esposizione a una società è un limite inferiore.")}


def duration(valued, total):
    """Duration of the bond part only (never of the whole portfolio): value-weighted over the bond positions with a
    known duration, with the bond value without a duration declared apart."""
    bonds = [(x, x["valueEUR"] * x["profile"]["assetClass"].get("Obbligazioni", 0)) for x in valued]
    bonds = [(x, v) for x, v in bonds if v > 0]
    if not bonds:
        return {"state": "nessuna obbligazione", "bondPct": 0.0}
    known = [(x, v) for x, v in bonds if _num(x["profile"]["duration"])]
    bv, kv = sum(v for _, v in bonds), sum(v for _, v in known)
    d = sum(x["profile"]["duration"] * v for x, v in known) / kv if kv else None
    return {"state": "calcolata" if d is not None else "non disponibile", "duration": d,
            "bondPct": bv / total * 100 if total else None, "coveredPct": kv / bv * 100 if bv else None,
            "unknown": [x["name"] for x, _ in bonds if not _num(x["profile"]["duration"])],
            "dates": sorted({x["profile"]["dates"].get("duration") for x, _ in known if x["profile"]["dates"].get("duration")}),
            "text": (f"duration media della parte obbligazionaria con dato disponibile: {it(d)} anni (con i rendimenti +1 "
                     f"punto, circa −{it(d)}% su quella parte, approssimazione)") if d is not None else
                    "duration non disponibile per le obbligazioni detenute",
            "note": "la duration riguarda solo le obbligazioni: non si applica alle azioni né al portafoglio intero"}


def stress(valued, total):
    """Deterministic what-if moves (not forecasts, no probabilities): equities −10% and −20% on the equity part, rates
    +1 point on the bonds with a known duration, USD −10% against the euro on the unhedged USD economic exposure."""
    if not total:
        return []
    eq = sum(x["valueEUR"] * x["profile"]["assetClass"].get("Azioni", 0) for x in valued)
    usd = sum(x["valueEUR"] * x["profile"]["currency"].get("USD", 0) for x in valued)
    usd_est = any(x["profile"]["quality"]["currency"] == "stima" and x["profile"]["currency"].get("USD") for x in valued)
    bond_known = [(x["valueEUR"] * x["profile"]["assetClass"].get("Obbligazioni", 0), x["profile"]["duration"]) for x in valued
                  if _num(x["profile"]["duration"])]
    bond_unknown = sum(x["valueEUR"] * x["profile"]["assetClass"].get("Obbligazioni", 0) for x in valued
                       if not _num(x["profile"]["duration"]))
    out = []
    for kind, mv in STRESS:
        if kind == "azioni":
            imp, base, txt = eq * mv / 100, eq, f"azioni {it(mv, 0)}% (sulla parte azionaria, ETF compresi)"
            note = None
        elif kind == "tassi":
            imp = -sum(v * d * mv / 100 for v, d in bond_known)
            base, txt = sum(v for v, _ in bond_known), f"rendimenti obbligazionari +{it(mv, 0)} punto (− duration × variazione)"
            note = f"obbligazioni senza duration non incluse: {it(bond_unknown / total * 100)}% del portafoglio" if bond_unknown else None
        else:
            imp, base, txt = usd * mv / 100, usd, f"dollaro {it(mv, 0)}% contro l'euro (esposizione economica in USD non coperta)"
            note = "esposizione in USD in parte stimata dai paesi dei titoli" if usd_est else None
        out.append({"scenario": txt, "baseEUR": base, "impactEUR": imp, "impactPct": imp / total * 100, "note": note,
                    "kind": "ipotesi deterministica, non una previsione né una probabilità"})
    return out


def key_dates(pos, as_of):
    d = {"analisi": as_of}
    prices = [l.get("priceDate") for x in pos for l in x["listings"] if l.get("priceDate")]
    if prices:
        d["prezzi (più vecchio)"], d["prezzi (più recente)"] = min(prices), max(prices)
    h = [x["profile"]["dates"].get("holdings") for x in pos if x.get("profile") and x["profile"]["dates"].get("holdings")]
    if h:
        d["composizioni ETF (più vecchia)"] = min(h)
    c = [x["profile"]["dates"].get("countries") for x in pos if x.get("profile") and x["profile"]["dates"].get("countries")]
    if c:
        d["paesi e settori ETF (più vecchi)"] = min(c)
    return d


def check_limits(an, limits):
    """Personal limits (only those set by the user; none by default). Each: max observed vs limit."""
    limits = {k: v for k, v in (limits or {}).items() if k in LIMIT_KEYS and _num(v) and v > 0}
    obs = {"position": max((p["weight"] or 0 for p in an["positions"] if p["class"] != "liquidita"), default=None),
           "company": max((c["pct"] or 0 for c in an["lookthrough"]["companies"]), default=None),
           "sector": max((r["pct"] or 0 for r in an["breakdown"]["sector"] if not r["generic"]), default=None),
           "country": max((r["pct"] or 0 for r in an["breakdown"]["country"] if not r["generic"]), default=None),
           "currency": max((r["pct"] or 0 for r in an["breakdown"]["currency"] if not r["generic"]), default=None)}
    rows = []
    for k, label in LIMIT_KEYS.items():
        lim = limits.get(k)
        o = obs[k]
        if lim is None:
            rows.append({"key": k, "label": label, "limit": None, "observed": o, "state": "non configurato"})
        else:
            st = "dati insufficienti" if o is None else "oltre il limite" if o > lim else "entro il limite"
            note = ("esposizione alle società calcolata sui titoli noti: è un limite inferiore, il valore vero può essere più alto"
                    if k == "company" else None)
            rows.append({"key": k, "label": label, "limit": lim, "observed": o, "state": st, "note": note})
    return {"configured": bool(limits), "rows": rows,
            "text": "Nessun limite personale impostato: le percentuali sono solo descritte." if not limits else
                    "Limiti impostati dall'utente per questa analisi (non salvati)."}


def missing(an, valued):
    out = []
    for u in an["unvalued"]:
        out.append(f"{u['name']}: {u['why']}")
    if an["indicative"]:
        out.append("valore indicativo (prezzo o cambio più vecchio di " + str(STALE_DAYS) + " giorni o senza data): "
                   + ", ".join(an["indicative"]))
    lt = an["lookthrough"]
    for b in lt["beyondItems"]:
        out.append(f"{b['name']}: noti solo i titoli che pesano {it(b['covered'])}% del fondo"
                   + (f" (composizione del {b['date']})" if b.get("date") else ""))
    for n in lt["noDataItems"]:
        out.append(f"{n}: composizione non disponibile (sovrapposizione non determinabile)")
    for x in valued:
        for k in ("sector", "country", "currency"):
            if x["profile"]["quality"].get(k) == "non disponibile" and x["class"] != "liquidita" and x["profile"]["assetClass"].get("Azioni"):
                out.append(f"{x['name']}: {dict(sector='settore', country='paese', currency='valuta economica')[k]} non disponibile")
        for s in x["profile"].get("stale") or []:
            out.append(f"{x['name']}: dato «{s}» datato secondo il catalogo")
    if an["duration"].get("unknown"):
        out.append("duration non disponibile: " + ", ".join(an["duration"]["unknown"]))
    if not any(x["class"] == "liquidita" for x in valued):
        out.append("liquidità non nota: non è presente tra le posizioni")
    r = an.get("risk") or {}
    if r.get("state") != "calcolato" and r.get("why"):
        out.append("rischio storico: " + r["why"])
    seen, res = set(), []
    for o in out:
        if o not in seen:
            seen.add(o)
            res.append(o)
    return res


# ---------------------------------------------------------------- 4. historical risk (descriptive)

def risk_scope(cov_invested, covered_eur, total_eur, cash_eur, unvalued=0):
    """Phase 7C: what the risk figures describe, said in numbers before the figures themselves. A statistic computed
    on part of the money is never the risk of the whole portfolio: covered share of the invested part and of the
    whole, uncovered share, cash left out, positions without a value in euro (not even in the total)."""
    tot = total_eur or 0
    cov_total = covered_eur / tot * 100 if tot else None
    cash_pct = cash_eur / tot * 100 if tot else None
    partial = cov_invested is None or cov_invested < 100 - 1e-9 or bool(unvalued)
    if not covered_eur:
        text = "Nessuna parte del portafoglio coperta da serie storiche sufficienti: nessuna statistica di rischio."
    elif partial:
        text = (f"Statistiche della sola parte coperta dalle serie storiche: {it(cov_total)}% del portafoglio "
                f"({it(cov_invested)}% della parte investita). NON rappresentano il rischio complessivo del portafoglio: "
                f"il {it(100 - cov_invested)}% della parte investita non è contato")
        text += (f", la liquidità ({it(cash_pct)}%) è esclusa" if cash_eur else "")
        text += (f", {unvalued} posizioni senza valore in euro non sono nemmeno nel totale" if unvalued else "") + "."
    else:
        text = (f"Statistiche della parte investita, coperta per intero dalle serie storiche ({it(cov_total)}% del "
                "portafoglio)" + (f"; la liquidità ({it(cash_pct)}%) è esclusa, quindi non sono il rischio dell'intero "
                                  "portafoglio" if cash_eur else "") + ".")
    return {"coveragePct": cov_invested, "coverageTotalPct": cov_total,
            "uncoveredPct": None if cov_invested is None else 100 - cov_invested,
            "uncoveredTotalPct": None if cov_total is None else 100 - cov_total - (cash_pct or 0),
            "cashPct": cash_pct, "unvaluedCount": unvalued,
            "scope": "nessuna" if not covered_eur else "parziale" if partial else "parte investita",
            "scopeText": text,
            "weightsNote": "pesi di oggi applicati a tutto il periodo passato: non sono i pesi che il portafoglio aveva allora"}


def risk(valued, series, unvalued=0):
    """Volatility (daily, annualised), max drawdown and weekly correlations of today's weights held constant, on the
    positions with at least MIN_DAYS aligned prices in EUR. Cash is left out (its value does not move in EUR, but its
    real risk is not zero for other currencies: said). Never computed on reconstructed data."""
    import pandas as pd
    inv = [x for x in valued if x["class"] != "liquidita"]
    inv_value = sum(x["valueEUR"] for x in inv)
    total_value = sum(x["valueEUR"] for x in valued)
    cash_value = total_value - inv_value
    if not inv_value:
        return dict(risk_scope(None, 0, total_value, cash_value, unvalued), state="non calcolabile",
                    why="nessuna posizione investita")
    used, left = [], []
    for x in inv:
        s = series.get(x["id"]) if series else None
        if s is None or len(s.dropna()) < MIN_DAYS:
            left.append({"name": x["name"], "why": "meno di circa 6 mesi di prezzi in euro disponibili" if s is not None else
                         "serie storica in euro non disponibile (nessun download per questa analisi)"})
            continue
        r = s.dropna().pct_change().dropna()
        if (r > JUMP_UP).any() or (r < JUMP_DOWN).any():
            left.append({"name": x["name"], "why": "prezzi storici anomali (salti di un giorno oltre +150% o −75%)"})
            continue
        used.append((x, s.dropna()))
    covered = sum(x["valueEUR"] for x, _ in used)
    cov = covered / inv_value * 100
    base = {**risk_scope(cov, covered, total_value, cash_value, unvalued), "left": left, "method": ("pesi di oggi tenuti fissi nel passato; volatilità e massima "
            "perdita su rendimenti giornalieri, correlazioni su rendimenti settimanali; misure del passato, non previsioni"),
            "cashNote": "la liquidità è esclusa dal calcolo"}
    if not used:
        return dict(base, state="non calcolabile", why="Non calcolabile con affidabilità sufficiente: nessuna posizione con prezzi in euro sufficienti")
    df = pd.concat({x["id"]: s for x, s in used}, axis=1, join="inner").dropna()
    if len(df) < MIN_DAYS:
        return dict(base, state="non calcolabile", why=f"Non calcolabile con affidabilità sufficiente: solo {len(df)} sedute in comune (servono almeno {MIN_DAYS})")
    w = pd.Series({x["id"]: x["valueEUR"] for x, _ in used})
    w = w / w.sum()
    rets = df.pct_change().dropna()
    port = (rets * w).sum(axis=1)
    vol = float(port.std() * math.sqrt(252) * 100)
    curve = (1 + port).cumprod()
    dd = float(((curve / curve.cummax()) - 1).min() * 100)
    weekly = df.resample("W-FRI").last().pct_change().dropna()
    corr = []
    names = {x["id"]: x["name"] for x, _ in used}
    ids = list(df.columns)
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            j = weekly[[a, b]].dropna()
            if len(j) >= MIN_WEEKS:
                corr.append({"a": names[a], "b": names[b], "corr": float(j[a].corr(j[b])), "weeks": int(len(j))})
    corr.sort(key=lambda c: -c["corr"])
    singles = [{"name": names[i], "vol": float(rets[i].std() * math.sqrt(252) * 100)} for i in ids]
    return dict(base, state="calcolato", vol=vol, maxDrawdown=dd, sessions=int(len(df)),
                first=str(df.index[0].date()), last=str(df.index[-1].date()), correlations=corr, singles=singles,
                limits=["la volatilità non è una misura completa del rischio (non vede eventi rari, liquidità, emittente)",
                        "le correlazioni del passato cambiano e in una crisi tendono a salire: non sono stabili né garantite",
                        f"calcolato sul {it(cov)}% della parte investita ({it(base['coverageTotalPct'])}% del "
                        "portafoglio): le altre posizioni non sono contate"]
                + (["periodo comune breve: meno di 2 anni di prezzi"] if len(df) < 480 else []))


# ---------------------------------------------------------------- 5. a candidate: compatibility and what-if

def candidate_position(c, catalog):
    """A raw position for a candidate ({"kind": "azione"|"etf", "ticker"?, "isin"?, "name"?, ...}), worth 0 until a
    what-if gives it an amount."""
    raw = {"id": "candidato", "name": c.get("name"), "isin": c.get("isin"), "ticker": c.get("ticker"),
           "kind": c.get("kind"), "value": 0.0, "valueCurrency": "EUR", "priceDate": c.get("asOf")}
    for k in ("sector", "country", "currency"):
        if c.get(k):
            raw[k] = c[k]
    return raw


def _shares(an, dim):
    return {r["label"]: (r["pct"] or 0) / 100 for r in an["breakdown"][dim]}


def compatibility(an, norm, cand, catalog, stock_meta=None, d2=None):
    """Descriptive compatibility of a candidate with the analysed portfolio (analyse): presence, direct and indirect
    exposure, what it would strengthen, what would be new, missing data, current limits. Never a score; never changes
    the Decision Desk state (d2 is shown as it is)."""
    cn = normalize({"asOf": an["asOf"], "fx": {}, "positions": [candidate_position(cand, catalog)]}, catalog)
    ci = cn["positions"][0]
    cp = profile(ci, stock_meta)
    held = norm["positions"]
    total = an["totalEUR"] or 0
    tags, present = [], {"direct": False}
    same = [x for x in held if (ci["isin"] and x["isin"] == ci["isin"]) or
            (ci["class"] == "azione" and x["class"] == "azione" and ci.get("company") and x.get("company") == ci["company"])]
    if same:
        x = same[0]
        how = ("stesso ISIN" if ci["isin"] and x["isin"] == ci["isin"] else
               "stesso ticker" if ci.get("ticker") and x.get("ticker") and ci["ticker"].upper() == x["ticker"].upper() else
               "stessa società (altra quotazione o classe di azioni, riconosciuta dal nome normalizzato)")
        present = {"direct": True, "how": how, "weight": sum(s["weight"] or 0 for s in same), "names": [s["name"] for s in same]}
        tags.append({"code": "C-P1", "text": f"Già presente direttamente ({how}): {it(present['weight'])}% del portafoglio"})
    equiv = []
    if ci["class"] in ("etf", "etc_etn") and cp.get("exposureKey"):
        for x in held:
            if x is not (same[0] if same else None) and x.get("profile") and x["profile"].get("exposureKey") == cp["exposureKey"] \
                    and x["isin"] != ci["isin"]:
                equiv.append({"name": x["name"], "weight": x["weight"],
                              "how": "stesso fondo, altra classe" if x["profile"].get("fundKey") == cp.get("fundKey") else
                                     "stessa esposizione del catalogo, altro prodotto"})
        if equiv:
            tags.append({"code": "C-P2", "text": "Esposizione equivalente già presente: " + ", ".join(
                f"{e['name']} ({it(e['weight'])}%, {e['how']})" for e in equiv)})
    comps = {c["key"]: c for c in an["lookthrough"]["companies"]}
    allcomp = {c["key"]: c for c in an["lookthrough"]["companies"]}
    indirect = None
    if ci["class"] == "azione" and ci.get("company"):
        c = allcomp.get(ci["company"])
        if c and c["indirectEUR"] > 0:
            indirect = {"pct": c["indirectEUR"] / total * 100 if total else None, "via": c["via"], "kind": c["kind"]}
            tags.append({"code": "C-I1", "text": f"Esposizione indiretta già presente: {it(indirect['pct'], 2)}% del portafoglio "
                         f"tramite {', '.join(v['fund'] for v in c['via'])} ({c['kind']})"})
        elif an["lookthrough"]["coverage"]["beyondKnown"] or an["lookthrough"]["coverage"]["noData"]:
            indirect = {"pct": None, "via": [], "kind": "non determinabile",
                        "text": "non trovata tra i titoli noti degli ETF: potrebbe essere presente tra quelli non noti"}
    overlap = None
    if cp["companies"] and ci["class"] != "azione":
        common = [k for k in cp["companies"] if k in comps]
        known = sum(c["w"] for c in cp["companies"].values())
        sh = sum(cp["companies"][k]["w"] for k in common)
        overlap = {"common": [{"name": cp["companies"][k]["name"], "weightInCandidate": cp["companies"][k]["w"] * 100,
                               "portfolioPct": comps[k]["pct"], "kind": comps[k]["kind"]} for k in common],
                   "candidateKnownPct": known * 100, "sharedPct": sh * 100, "date": cp["dates"].get("holdings")}
        if common:
            tags.append({"code": "C-O1", "text": f"Sovrapposizione con le società già detenute: {len(common)} dei primi titoli del "
                         f"candidato, {it(sh * 100)}% del fondo (su {it(known * 100)}% noto)"})
    strengthen, reduce, new = {}, {}, {}
    for dim, lab in (("sector", "settoriale"), ("country", "geografica"), ("currency", "valutaria"), ("assetClass", "per classe")):
        ps, cs = _shares(an, dim), cp[dim]
        top = next((r["label"] for r in an["breakdown"][dim] if not r["generic"]), None)
        strengthen[dim] = sorted(({"label": k, "candidate": v * 100, "portfolio": ps.get(k, 0) * 100}
                                  for k, v in cs.items() if k not in GENERIC and v > ps.get(k, 0) and ps.get(k, 0) > 0),
                                 key=lambda r: -r["candidate"])
        reduce[dim] = sorted(({"label": k, "candidate": cs.get(k, 0) * 100, "portfolio": v * 100}
                              for k, v in ps.items() if k not in GENERIC and v > cs.get(k, 0)), key=lambda r: -r["portfolio"])[:5]
        new[dim] = [{"label": k, "candidate": v * 100} for k, v in sorted(cs.items(), key=lambda kv: -kv[1])
                    if k not in GENERIC and ps.get(k, 0) == 0 and v > 0]
        if top and cs.get(top, 0) > ps.get(top, 0) and top not in GENERIC:
            tags.append({"code": "C-S1" if dim == "sector" else "C-G1" if dim == "country" else "C-V1" if dim == "currency" else "C-A1",
                         "text": f"Aumento della concentrazione {lab}: «{top}», già la voce più pesante ({it(ps[top] * 100)}%), "
                                 f"pesa {it(cs[top] * 100)}% nel candidato"})
        if new[dim] and dim != "assetClass":
            tags.append({"code": {"sector": "C-N2", "country": "C-N1", "currency": "C-N3"}[dim],
                         "text": f"Nuova esposizione {lab}: " + ", ".join(f"{n['label']} ({it(n['candidate'])}% del candidato)" for n in new[dim][:4])})
        if new[dim] and dim == "assetClass":
            tags.append({"code": "C-N4", "text": "Nuova classe di investimento: " + ", ".join(n["label"] for n in new[dim])})
    miss = []
    for k, lab in (("sector", "settori"), ("country", "paesi"), ("currency", "valuta economica")):
        if cp["quality"].get(k) == "non disponibile" and ci["class"] != "liquidita":
            miss.append(f"candidato: {lab} non disponibili")
    if cp["lookthrough"] == "non disponibile":
        miss.append("candidato: composizione non disponibile (sovrapposizione non determinabile)")
    elif cp["lookthrough"].startswith("parziale"):
        miss.append(f"candidato: noti solo i primi titoli ({it(cp['covered'] * 100)}% del fondo)"
                    + (f", composizione del {cp['dates']['holdings']}" if cp["dates"].get("holdings") else ""))
    for s in cp.get("stale") or []:
        miss.append(f"candidato: dato «{s}» datato secondo il catalogo")
    if not total:
        miss.append("portafoglio senza valori in euro: confronto non possibile")
    cov = an["lookthrough"]["coverage"]
    if (cov["beyondKnown"] or 0) + (cov["noData"] or 0) > 0:
        miss.append(f"portafoglio: {it((cov['beyondKnown'] or 0) + (cov['noData'] or 0))}% non analizzabile a livello di società")
    insufficient = not total or (cp["quality"]["sector"] == "non disponibile" and cp["quality"]["country"] == "non disponibile")
    if insufficient:
        tags.append({"code": "C-D1", "text": "Dati insufficienti per determinare la compatibilità"})
    return {"version": VERSION, "candidate": {"name": ci["name"], "class": ci["class"], "classLabel": ci["classLabel"],
                                              "isin": ci["isin"], "ticker": ci["ticker"], "recognised": ci["recognised"],
                                              "lookthrough": cp["lookthrough"], "hedged": cp["hedged"], "trading": cp["trading"],
                                              "domicile": cp["domicile"], "dates": cp["dates"], "notes": cp["notes"]},
            "d2": d2, "present": present, "equivalent": equiv, "indirect": indirect, "overlap": overlap,
            "strengthen": strengthen, "reduce": reduce, "new": new, "tags": tags, "missing": miss,
            "limits": an["limits"], "insufficient": insufficient,
            "rule": ("Descrizioni verificabili, non un punteggio e non una raccomandazione: «rafforza» = la voce pesa nel "
                     "candidato più che nel portafoglio, quindi qualsiasi importo ne aumenterebbe il peso; «nuova» = voce "
                     "assente oggi. Lo stato del Decision Desk resta quello di D2."),
            "separate": "Due giudizi distinti: lo stato del Decision Desk (qualità dell'opportunità) e la compatibilità con il portafoglio."}


def simulate(book, catalog, cand, amount, currency="EUR", funding="nuova", reduce_id=None, stock_meta=None, limits=None):
    """Hypothetical change, never executed nor saved: the portfolio before and after giving `amount` to the candidate.
    funding: "nuova" (new money), "liquidita" (cash already held: only if known and enough), "riduzione" (reduce the
    position reduce_id by the same amount: only if explicitly chosen and large enough)."""
    before_n = normalize(book, catalog)
    eur, conv, _ = to_eur(amount, currency, book.get("fx"), book.get("asOf"))
    if not _num(amount) or amount <= 0:
        return {"ok": False, "why": "importo ipotetico non valido"}
    if eur is None:
        return {"ok": False, "why": conv}
    after = {"asOf": book.get("asOf"), "fx": book.get("fx"), "positions": [dict(p) for p in book.get("positions") or []]}
    if funding == "liquidita":
        cash = [p for p in before_n["positions"] if p["class"] == "liquidita" and p["valueEUR"] is not None]
        avail = sum(p["valueEUR"] for p in cash)
        if not cash:
            return {"ok": False, "why": "liquidità non nota: non posso assumere che sia sufficiente"}
        if avail < eur - 1e-6:
            return {"ok": False, "why": f"liquidità nota {it(avail, 0)} € inferiore all'importo ipotetico {it(eur, 0)} €"}
        left = eur
        for p in after["positions"]:
            cp = next((c for c in cash if p.get("id") in c["ids"]), None)
            if cp and left > 0:
                p_eur = cp["valueEUR"]
                take = min(left, p_eur)
                p["value"] = (p_eur - take) * (p["value"] / p_eur if p_eur else 1)
                p.pop("qty", None)
                p.pop("price", None)
                left -= take
    elif funding == "riduzione":
        tgt = next((p for p in before_n["positions"] if reduce_id in p["ids"]), None)
        if not tgt or tgt["valueEUR"] is None:
            return {"ok": False, "why": "posizione da ridurre non indicata o senza valore in euro"}
        if tgt["valueEUR"] < eur - 1e-6:
            return {"ok": False, "why": f"la posizione {tgt['name']} vale {it(tgt['valueEUR'], 0)} €: meno dell'importo ipotetico"}
        k = (tgt["valueEUR"] - eur) / tgt["valueEUR"]
        for p in after["positions"]:
            if p.get("id") in tgt["ids"]:
                if p.get("qty") is not None:
                    p["qty"] = p["qty"] * k
                else:
                    p["value"] = (p.get("value") or 0) * k
    elif funding != "nuova":
        return {"ok": False, "why": "modalità di finanziamento non riconosciuta"}
    c = candidate_position(cand, catalog)
    c.update(id="ipotesi", value=eur, valueCurrency="EUR", priceDate=book.get("asOf"))
    after["positions"].append(c)
    a0 = analyse(before_n, stock_meta, limits)
    after_n = normalize(after, catalog)
    a1 = analyse(after_n, stock_meta, limits)
    delta = {}
    for dim in ("assetClass", "sector", "country", "currency"):
        b = {r["label"]: r["pct"] or 0 for r in a0["breakdown"][dim]}
        f = {r["label"]: r["pct"] or 0 for r in a1["breakdown"][dim]}
        delta[dim] = sorted(({"label": k, "before": b.get(k, 0), "after": f.get(k, 0), "change": f.get(k, 0) - b.get(k, 0)}
                             for k in set(b) | set(f) if abs(f.get(k, 0) - b.get(k, 0)) >= 0.05),
                            key=lambda r: -abs(r["change"]))
    cb = {c["key"]: c for c in a0["lookthrough"]["companies"]}
    ca = {c["key"]: c for c in a1["lookthrough"]["companies"]}
    comp = sorted(({"name": ca[k]["name"], "before": (cb.get(k) or {}).get("pct") or 0, "after": ca[k]["pct"] or 0,
                    "change": (ca[k]["pct"] or 0) - ((cb.get(k) or {}).get("pct") or 0), "kind": ca[k]["kind"]}
                   for k in ca), key=lambda r: -abs(r["change"]))[:10]
    risks = []
    for dim, lab in (("sector", "settore"), ("country", "paese"), ("currency", "valuta")):
        tb = next((r for r in a0["breakdown"][dim] if not r["generic"]), None)
        ta = next((r for r in a1["breakdown"][dim] if not r["generic"]), None)
        if tb and ta and ta["label"] == tb["label"] and (ta["pct"] or 0) > (tb["pct"] or 0) + 0.05:
            risks.append(f"aumenta la voce più pesante per {lab}: {ta['label']} da {it(tb['pct'])}% a {it(ta['pct'])}%")
        elif tb and ta and ta["label"] != tb["label"]:
            risks.append(f"cambia la voce più pesante per {lab}: da {tb['label']} a {ta['label']} ({it(ta['pct'])}%)")
    tc_b = a0["lookthrough"]["companies"][0] if a0["lookthrough"]["companies"] else None
    tc_a = a1["lookthrough"]["companies"][0] if a1["lookthrough"]["companies"] else None
    if tc_a and (not tc_b or (tc_a["pct"] or 0) > (tc_b["pct"] or 0) + 0.05):
        risks.append(f"la società più pesante (guardando dentro gli ETF) diventa {tc_a['name']} al {it(tc_a['pct'], 2)}% ({tc_a['kind']})")
    lim_b = {r["key"]: r["state"] for r in a0["limits"]["rows"]}
    newly = [r for r in a1["limits"]["rows"] if r["state"] == "oltre il limite" and lim_b.get(r["key"]) != "oltre il limite"]
    if newly:
        risks += [f"supererebbe il limite personale per {r['label']}: {it(r['observed'])}% contro {it(r['limit'])}%" for r in newly]
    return {"ok": True, "version": VERSION, "amountEUR": eur, "conversion": conv, "funding": funding,
            "fundingText": {"nuova": "nuova liquidità (aggiunta al totale)", "liquidita": "liquidità già presente",
                            "riduzione": "riduzione ipotetica di una posizione scelta"}[funding],
            "before": summary(a0), "after": summary(a1), "delta": delta, "companies": comp, "risks": risks,
            "limits": a1["limits"], "stressBefore": a0["stress"], "stressAfter": a1["stress"],
            "durationBefore": a0["duration"], "durationAfter": a1["duration"],
            "missing": [m for m in a1["missing"] if m not in a0["missing"]] or [],
            "note": ("Simulazione ipotetica: non è un ordine, non modifica il portafoglio, non viene salvata e non calcola "
                     "rendimenti futuri.")}


def summary(an):
    return {"totalEUR": an["totalEUR"], "top": an["concentration"]["top"][:5], "top5": an["concentration"]["top5"],
            "top10": an["concentration"]["top10"], "effective": an["concentration"]["effective"],
            "topCompanies": an["lookthrough"]["companies"][:5], "coverage": an["lookthrough"]["coverage"],
            "topSector": next((r for r in an["breakdown"]["sector"] if not r["generic"]), None),
            "topCountry": next((r for r in an["breakdown"]["country"] if not r["generic"]), None),
            "topCurrency": an["concentration"]["topCurrency"]}


# ---------------------------------------------------------------- 6. a synthetic example (never personal data)

def demo_book(as_of):
    """A made-up portfolio on public instruments (values invented, in EUR): three stocks, two ETFs whose holdings
    overlap, one bond ETF and cash. Used by the preview and the examples: never the user's portfolio."""
    P = lambda i, name, kind, value, **k: dict({"id": i, "name": name, "kind": kind, "value": value, "valueCurrency": "EUR",
                                                "priceDate": as_of}, **k)
    return {"asOf": as_of, "fx": {}, "source": "esempio",
            "positions": [P("e1", "NVIDIA", "azione", 6000.0, ticker="NVDA"),
                          P("e2", "Apple", "azione", 4000.0, ticker="AAPL"),
                          P("e3", "Adobe", "azione", 3000.0, ticker="ADBE"),
                          P("e4", "iShares Core MSCI World", "etf", 20000.0, isin="IE00B4L5Y983", ticker="SWDA.MI"),
                          P("e5", "iShares Nasdaq 100", "etf", 12000.0, isin="IE00B53SZB19", ticker="CSNDX.MI"),
                          P("e6", "iShares Euro Government Bond 1-3yr", "etf", 8000.0, isin="IE00B14X4Q57", ticker="IBGS.MI"),
                          P("e7", "Liquidità in euro", "liquidita", 5000.0)]}
