"""Side-by-side comparison of 2-4 UCITS ETFs from the catalogue (phase 6A).

What it does NOT do: no winner, no single score, no buy/sell signal, no return forecast. Each dimension is shown
apart (identity, index and exposure, currency, costs, structure, size and liquidity, risks, data dates), with the
source and date of every value, and a comparability level that says how far the comparison makes sense:
  1  same index (and same currency hedging): they should behave almost the same; differences are costs,
     structure, size, share class;
  2  very similar exposure (different index on the same market, or the same index with/without hedging);
  3  same category, different index: related but different portfolios;
  4  not directly comparable (different asset class or market).
Holdings overlap is only shown from dated issuer data and only as "which of the first 10 are in common":
with the top 10 alone no overall percentage can be computed.
"""
from __future__ import annotations

import etf_catalog as cat

LEVELS = {1: "Stesso indice", 2: "Esposizione molto simile", 3: "Stessa categoria, indice diverso", 4: "Non comparabili direttamente"}
LEVEL_TEXT = {
    1: "Replicano lo stesso indice: dovrebbero muoversi quasi allo stesso modo. Le differenze da guardare sono costi, "
       "struttura, dimensione, classe (accumulo/distribuzione) e quotazioni.",
    2: "Investono sullo stesso mercato con regole simili ma non identiche (o con una diversa copertura del cambio): "
       "i risultati possono divergere, soprattutto nei periodi di forti movimenti.",
    3: "Appartengono alla stessa categoria ma seguono indici diversi: portafogli e rischi possono essere molto diversi. "
       "Il confronto dei costi da solo non basta.",
    4: "Non sono alternative l'una all'altra: espongono a mercati o tipi di attività diversi. Il confronto serve solo a "
       "vedere le differenze, non a scegliere tra i due.",
}
MAX_ETFS = 4
DISCLAIMER = ("Confronto informativo, non una consulenza finanziaria né un invito a comprare o vendere. Un costo più basso "
              "non rende un ETF automaticamente migliore: contano anche indice, struttura, valuta, liquidità e rischi.")


def _k(e):
    return e.get("classification") or {}


def pair_level(a, b):
    """(level, reasons) for two catalogue entries."""
    if a.get("exclusion") or b.get("exclusion"):
        return 4, ["almeno uno è un prodotto escluso dal catalogo ordinario (" + (a.get("exclusion") or b.get("exclusion")) + ")"]
    ka, kb = _k(a), _k(b)
    ha, hb = cat.val(a["fund"].get("hedged")), cat.val(b["fund"].get("hedged"))
    reasons = []
    if ka.get("assetClass") != kb.get("assetClass"):
        return 4, [f"tipo di attività diverso: {ka.get('assetClass')} e {kb.get('assetClass')} non si confrontano sugli stessi indicatori"]
    same_fund = cat.val(a["identity"].get("fundKey")) == cat.val(b["identity"].get("fundKey"))
    if ka.get("indexKey") and ka.get("indexKey") == kb.get("indexKey"):
        if ha == hb or ha is None or hb is None:
            level = 1
            reasons.append("classi dello stesso fondo" if same_fund else "fondi diversi che replicano lo stesso indice")
            if ha is None or hb is None:
                reasons.append("copertura del cambio non nota per uno dei due: verificare")
        else:
            level = 2
            reasons.append("stesso indice, ma uno ha la copertura del cambio verso l'euro e l'altro no: "
                           "con il cambio che si muove i risultati in euro possono differire molto")
    elif ka.get("exposure") and ka.get("exposure") == kb.get("exposure"):
        level = 2
        reasons.append("indici diversi sullo stesso mercato")
    elif ka.get("family") and ka.get("family") == kb.get("family"):
        level = 3
        reasons.append(f"stessa famiglia ({ka.get('familyLabel') or ka.get('family')}), indici e portafogli diversi")
    else:
        return 4, ["mercati o categorie diverse"]
    da, db = cat.val(a["fund"].get("distribution")), cat.val(b["fund"].get("distribution"))
    if da and db and da != db:
        reasons.append("uno accumula e l'altro distribuisce i proventi: i rendimenti di solo prezzo non sono confrontabili direttamente")
    if ha != hb and level == 1:
        reasons.append("copertura del cambio diversa")
    return level, reasons


# ---------------------------------------------------------------- formatting of one value

def cell(field, fmt=None):
    """{"text", "src", "asOf", "note"} for one stored value; "n.d." when missing."""
    if not isinstance(field, dict):
        field = {"v": field}
    v = field.get("v")
    if v is None or v == [] or v == {}:
        text = "n.d."
    elif fmt:
        text = fmt(v)
    elif isinstance(v, bool):
        text = "sì" if v else "no"
    else:
        text = str(v)
    return {"text": text, "src": field.get("src"), "asOf": field.get("asOf"), "note": field.get("note"), "missing": text == "n.d."}


def pct(x, d=2):
    return f"{x:.{d}f}%".replace(".", ",")


def money_m(x):
    return f"{x:,.0f} mln".replace(",", ".")


MESI = ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"]


def day(iso):
    y, m, d = str(iso)[:10].split("-")
    return f"{int(d)} {MESI[int(m) - 1]} {y}"


def num(x):
    return f"{x:,.0f}".replace(",", ".")


IT = {"United States": "USA", "Japan": "Giappone", "United Kingdom": "Regno Unito", "Canada": "Canada", "Germany": "Germania",
      "France": "Francia", "Switzerland": "Svizzera", "Netherlands": "Paesi Bassi", "Italy": "Italia", "Ireland": "Irlanda", "Spain": "Spagna",
      "South Korea": "Corea del Sud", "China": "Cina", "Taiwan": "Taiwan", "India": "India", "Brazil": "Brasile", "Mexico": "Messico",
      "Australia": "Australia", "Other": "Altri", "Technology": "Tecnologia", "Finance": "Finanza", "Industrials": "Industria",
      "Healthcare": "Sanità", "Consumer Non-Cyclicals": "Beni di prima necessità", "Consumer Cyclicals": "Consumi discrezionali",
      "Non-Energy Materials": "Materiali", "Energy": "Energia", "Utilities": "Utility", "Telecommunication": "Telecomunicazioni",
      "Real Estate": "Immobiliare", "Basic Materials": "Materiali"}


def top_list(items, n=4):
    return ", ".join(f"{IT.get(i['name'], i['name'])} {pct(i['weight'], 1)}" for i in items[:n] if i.get("weight") is not None)


def holdings_text(top):
    return ", ".join(f"{t['name'].title()} {pct(t['weight'] * 100, 1)}" for t in top[:5] if t.get("weight") is not None)


def listing_text(e):
    out = []
    for l in e.get("listings") or []:
        c = cat.val(l.get("currency")) or "?"
        out.append(f"{l['ticker']} ({l['mic']}, {c})")
    return " · ".join(out) or "n.d."


def liquidity_text(e):
    out = []
    for l in e.get("listings") or []:
        t = cat.val(l.get("avgTurnover3m"))
        out.append(f"{l['ticker']} {l['mic']}: " + (f"{num(t)} {cat.val(l.get('currency')) or ''}/giorno" if t is not None else "n.d."))
    return " · ".join(out) or "n.d."


def spread_text(e, now=None):
    for l in e.get("listings") or []:
        s = l.get("spread")
        if s:
            st, txt = cat.spread_state(s, now)
            return txt.replace("book letto", f"book di {l['ticker']} letto").replace("% (", f"% ({l['ticker']}, ", 1)
    return "n.d. (serve il book reale con prezzi in acquisto e vendita)"


# ---------------------------------------------------------------- risks (descriptive, per ETF)

def risks(e):
    k, f, ex, b = _k(e), e.get("fund") or {}, e.get("exposure") or {}, e.get("bond") or {}
    out = []
    ac = k.get("assetClass")
    if ac == "azionario":
        out.append("rischio azionario: il valore può scendere molto nelle fasi di mercato negative")
        w = cat.val(ex.get("top10Weight"))
        if w is not None and w >= 0.4:
            out.append(f"concentrazione: i primi 10 titoli pesano {pct(w * 100, 0)} del fondo")
        if k.get("family") == "paese":
            out.append("un solo paese: dipende dall'economia e dalla politica di quel paese")
        if k.get("family") in ("tecnologia", "sanita", "finanza", "energia", "beni_primari", "industria", "utility_infrastrutture") or k.get("theme"):
            out.append("settore o tema specifico: meno diversificato di un indice ampio" + (" (tema: può passare di moda)" if k.get("theme") else ""))
        if k.get("family") == "emergenti" or k.get("exposure") in ("cina", "india", "corea", "taiwan", "brasile", "messico"):
            out.append("mercati emergenti: rischi politici, di liquidità e di cambio più alti")
    if ac in ("obbligazionario", "monetario"):
        d = cat.val(b.get("duration"))
        if d is not None:
            out.append(f"rischio di tasso: con una duration di {str(round(d, 1)).replace('.', ',')} anni, un rialzo dei tassi dell'1% "
                       f"farebbe scendere il prezzo di circa {str(round(d, 1)).replace('.', ',')}%")
        elif ac == "obbligazionario":
            out.append("rischio di tasso: duration non disponibile nelle fonti lette")
        cr = cat.val(b.get("credit"))
        if cr:
            out.append(f"rischio di credito: {cr}")
    hedged = cat.val(f.get("hedged"))
    ccy = cat.val(f.get("baseCurrency"))
    if hedged:
        out.append("cambio coperto verso l'euro: la copertura ha un costo e non è perfetta")
    elif ac == "azionario" or (ac == "obbligazionario" and ccy and ccy != "EUR"):
        out.append("rischio di cambio: il fondo possiede titoli in valute diverse dall'euro (anche se lo compri in euro)")
    if (f.get("counterpartyRisk") or "").startswith("sì"):
        out.append("rischio di controparte: replica sintetica tramite swap")
    size = cat.val(f.get("sizeFund"))
    if size is not None and size < 100:
        out.append("fondo piccolo (meno di 100 milioni): rischio più alto di chiusura o fusione")
    launch = cat.val(f.get("launch"))
    if launch and cat.age_days(launch) is not None and cat.age_days(launch) < 3 * 365:
        out.append("fondo recente (meno di 3 anni): storico breve")
    return out


# ---------------------------------------------------------------- overlap of the top 10

def overlap(entries):
    """Common names among the first 10 holdings, only when every ETF has dated issuer (or same-index) data."""
    tops = []
    for e in entries:
        t = (e.get("exposure") or {}).get("top10") or {}
        if not t.get("v"):
            return {"available": False, "reason": f"{e['isin']}: composizione non disponibile"}
        tops.append(t)
    days = [cat.age_days(t.get("asOf")) for t in tops]
    if any(d is None for d in days):
        return {"available": False, "reason": "composizione senza data: non confrontabile"}
    keys = [{h.get("key") or h["name"].lower(): h for h in t["v"]} for t in tops]
    common = set(keys[0]).intersection(*keys[1:]) if len(keys) > 1 else set()
    rows = [{"name": keys[0][c]["name"].title(), "weights": [k[c].get("weight") for k in keys]} for c in common]
    rows.sort(key=lambda r: -min(w or 0 for w in r["weights"]))
    dates = [t.get("asOf") for t in tops]
    warn = []
    if max(days) - min(days) > 45:
        warn.append("le composizioni hanno date distanti più di 45 giorni")
    if max(days) > cat.MAX_AGE["holdings"]:
        warn.append("almeno una composizione è datata")
    if any(t.get("dateKind") == "download" for t in tops):
        warn.append("per almeno un ETF il file dell'emittente non ha la data: si usa quella del download")
    for e in entries:
        if (e.get("exposure") or {}).get("top10Kind") not in (None, "emittente"):
            warn.append(f"{e['isin']}: composizione presa da {(e['exposure']['top10'].get('note') or 'una fonte indiretta')}")
    same_fund = len({cat.val(e["identity"].get("fundKey")) for e in entries}) == 1
    return {"available": True, "partial": True, "common": rows, "count": len(rows), "dates": dates, "warnings": warn,
            "sameFund": same_fund,
            "note": ("Classi dello stesso fondo: il portafoglio è lo stesso." if same_fund else
                     f"Confronto parziale: {len(rows)} dei primi 10 titoli in comune. Con i soli primi 10 non si può calcolare "
                     "una sovrapposizione complessiva.")}


# ---------------------------------------------------------------- the comparison

def row_(key, label, entries, getter, note=None):
    vals = [getter(e) for e in entries]
    texts = [v["text"] for v in vals]
    return {"key": key, "label": label, "values": vals, "same": len(set(texts)) == 1 and "n.d." not in texts, "note": note}


def plain(text, **kw):
    return dict({"text": text, "src": None, "asOf": None, "note": None, "missing": text in (None, "n.d.")}, **kw)


def compare(data, keys):
    """The full comparison for 2-4 ISINs or tickers; {"error"} when not possible."""
    if not data:
        return {"error": "Catalogo non ancora costruito."}
    keys = [k for k in dict.fromkeys(k.strip().upper() for k in keys if k and k.strip())]
    if len(keys) < 2:
        return {"error": "Scegli almeno 2 ETF da confrontare."}
    if len(keys) > MAX_ETFS:
        return {"error": f"Al massimo {MAX_ETFS} ETF alla volta."}
    entries, missing = [], []
    for k in keys:
        e = cat.find(data, k) or data["excluded"].get(k)
        (entries.append(e) if e else missing.append(k))
    if missing:
        return {"error": "Non trovati nel catalogo: " + ", ".join(missing)}
    if len({e["isin"] for e in entries}) < len(entries):
        return {"error": "Hai scelto due volte lo stesso ETF (stesso ISIN, magari con ticker diversi)."}
    pairs, worst = [], 1
    for i in range(len(entries)):
        for j in range(i + 1, len(entries)):
            lv, why = pair_level(entries[i], entries[j])
            worst = max(worst, lv)
            pairs.append({"a": entries[i]["isin"], "b": entries[j]["isin"], "level": lv, "label": LEVELS[lv], "reasons": why})
    bond = all(_k(e).get("assetClass") in ("obbligazionario", "monetario") for e in entries)
    equity = all(_k(e).get("assetClass") == "azionario" for e in entries)
    I = lambda f: (lambda e: cell(e["identity"].get(f)))  # noqa: E731
    F = lambda f, fmt=None: (lambda e: cell(e["fund"].get(f), fmt))  # noqa: E731
    X = lambda f, fmt=None: (lambda e: cell((e.get("exposure") or {}).get(f), fmt))  # noqa: E731
    Bd = lambda f, fmt=None: (lambda e: cell((e.get("bond") or {}).get(f), fmt))  # noqa: E731
    dims = [
        {"key": "identita", "label": "Identità", "rows": [
            row_("isin", "ISIN (identifica la classe)", entries, lambda e: plain(e["isin"])),
            row_("name", "Nome", entries, I("name")),
            row_("issuer", "Emittente", entries, I("issuer")),
            row_("legal", "Società (Borsa Italiana)", entries, I("legalEntity")),
            row_("domicile", "Domicilio", entries, I("domicile")),
            row_("ucits", "UCITS", entries, I("ucits")),
            row_("type", "Tipo di prodotto", entries, I("productType")),
            row_("class", "Classe", entries, lambda e: plain(", ".join(x for x in [
                cat.val(e["fund"].get("distribution")), "coperta" if cat.val(e["fund"].get("hedged")) else
                ("non coperta" if cat.val(e["fund"].get("hedged")) is False else None), cat.val(e["fund"].get("baseCurrency"))] if x) or "n.d.")),
            row_("status", "Nel catalogo", entries, lambda e: plain(e.get("status") or "n.d.")),
        ]},
        {"key": "indice", "label": "Indice ed esposizione", "rows": [
            row_("index", "Indice", entries, I("index")),
            row_("category", "Categoria", entries, lambda e: plain(_k(e).get("label") or "n.d.")),
            row_("holdingsCount", "Numero di titoli", entries, X("holdingsCount", num)),
            row_("top10Weight", "Peso dei primi 10", entries, X("top10Weight", lambda v: pct(v * 100, 1))),
            row_("top10", "Primi titoli", entries, X("top10", holdings_text)),
            row_("countries", "Paesi principali", entries, X("countries", top_list)),
            row_("sectors", "Settori principali", entries, X("sectors", top_list)),
            row_("fx", "Esposizione valutaria (stima)", entries, X("currencyExposure", lambda v: ", ".join(
                f"{c['currency']}" + (f" {pct(c['weight'], 0)}" if c.get("weight") is not None else "") for c in v))),
        ] if not bond else [
            row_("index", "Indice", entries, I("index")),
            row_("category", "Categoria", entries, lambda e: plain(_k(e).get("label") or "n.d.")),
            row_("bondKind", "Tipo di obbligazioni", entries, Bd("bondKind")),
            row_("duration", "Duration (anni)", entries, Bd("duration", lambda v: str(round(v, 2)).replace(".", ","))),
            row_("yield", "Rendimento a scadenza (al peggio)", entries, Bd("yield", lambda v: pct(v))),
            row_("credit", "Qualità del credito", entries, Bd("credit")),
            row_("bondCcy", "Valuta delle obbligazioni", entries, Bd("currency")),
            row_("holdingsCount", "Numero di titoli", entries, X("holdingsCount", num)),
        ]},
        {"key": "valuta", "label": "Valuta e copertura", "rows": [
            row_("base", "Valuta della classe (NAV)", entries, F("baseCurrency")),
            row_("hedged", "Copertura del cambio", entries, F("hedged")),
            row_("trading", "Quotazioni (ticker, mercato, valuta di negoziazione)", entries, lambda e: plain(listing_text(e))),
        ], "note": "La valuta in cui compri l'ETF non è la sua esposizione: un ETF sull'S&P 500 comprato in euro resta esposto al dollaro, "
                   "a meno che la classe sia coperta."},
        {"key": "costi", "label": "Costi", "rows": [
            row_("ter", "TER / costi correnti annui", entries, lambda e: dict(cell(e["costs"].get("ter"), lambda v: pct(v)),
                                                                           state=e["costs"].get("terState"))),
            row_("td", "Tracking difference", entries, lambda e: cell(e["costs"].get("trackingDifference"))),
            row_("te", "Tracking error", entries, lambda e: cell(e["costs"].get("trackingError"))),
            row_("spread", "Spread denaro/lettera", entries, lambda e: plain(spread_text(e))),
            row_("broker", "Commissioni del broker", entries, lambda e: cell(e["costs"].get("brokerFees"))),
        ], "note": "Il TER è solo una parte del costo: contano anche tracking difference, spread e commissioni. "
                   "La tracking difference misura quanto l'ETF resta indietro rispetto all'indice; il tracking error quanto oscilla quella distanza."},
        {"key": "struttura", "label": "Struttura", "rows": [
            row_("replication", "Replica", entries, F("replication")),
            row_("counterparty", "Controparte", entries, lambda e: plain(e["fund"].get("counterpartyRisk") or "n.d.")),
            row_("distribution", "Proventi", entries, F("distribution")),
            row_("frequency", "Frequenza dei proventi", entries, F("distributionFrequency")),
            row_("launch", "Data di lancio", entries, F("launch", day)),
            row_("kid", "Data del KID", entries, F("kidDate", day)),
        ]},
        {"key": "liquidita", "label": "Dimensione e liquidità", "rows": [
            row_("size", "Patrimonio del fondo", entries, lambda e: dict(cell(e["fund"].get("sizeFund"), money_m),
                 text=(money_m(cat.val(e["fund"]["sizeFund"])) + " " + (e["fund"]["sizeFund"].get("unit") or "")).strip()
                 if cat.val(e["fund"].get("sizeFund")) is not None else "n.d.")),
            row_("sizeClass", "Patrimonio della classe", entries, F("sizeClass", money_m)),
            row_("turnover", "Scambi medi in borsa (3 mesi)", entries, lambda e: plain(liquidity_text(e))),
        ], "note": "La liquidità di un ETF dipende soprattutto da quella dei titoli che possiede e dai market maker: "
                   "pochi scambi su una borsa non significano da soli che sia difficile comprarlo o venderlo."},
        {"key": "rischi", "label": "Rischi principali", "rows": [
            row_("risks", "Rischi", entries, lambda e: plain(" · ".join(risks(e)) or "n.d."))]},
        {"key": "dati", "label": "Stato e date dei dati", "rows": [
            row_("complete", "Completezza", entries, lambda e: plain(f"{e['completeness']['state']} ({round(e['completeness']['share'] * 100)}%)"
                                                                 + (": mancano " + ", ".join(e['completeness']['missingLabels']) if e['completeness']['missing'] else ""))),
            row_("stale", "Dati datati", entries, lambda e: plain(", ".join(e["freshness"]["stale"]) or "nessuno")),
        ]},
    ]
    if not equity and not bond:
        dims[1]["note"] = "Tipi di attività diversi: gli indicatori di esposizione non sono gli stessi."
    diffs = differences(entries) if worst <= 2 else []
    return {"items": [cat.row(e) for e in entries], "level": worst, "levelLabel": LEVELS[worst], "levelText": LEVEL_TEXT[worst],
            "pairs": pairs, "dimensions": dims, "differences": diffs, "overlap": overlap(entries) if equity else
            {"available": False, "reason": "sovrapposizione dei titoli calcolata solo tra ETF azionari"},
            "risks": {e["isin"]: risks(e) for e in entries}, "disclaimer": DISCLAIMER, "builtAt": data.get("builtAt")}


def differences(entries):
    """For very similar ETFs: plain sentences on what changes between them, without saying which is better."""
    out = []
    ters = [(e["isin"], cat.val(e["costs"].get("ter"))) for e in entries]
    if all(t is not None for _, t in ters) and len({t for _, t in ters}) > 1:
        lo, hi = min(t for _, t in ters), max(t for _, t in ters)
        out.append(f"TER da {pct(lo)} a {pct(hi)}: su 10.000 € la differenza vale circa {round((hi - lo) * 100):d} € all'anno "
                   "(senza contare tracking difference e spread, che possono compensarla o ampliarla).")
    for f, lab in (("distribution", "politica dei proventi"), ("hedged", "copertura del cambio"), ("replication", "replica"),
                   ("baseCurrency", "valuta della classe")):
        vs = {cat.val(e["fund"].get(f)) for e in entries}
        if len(vs) > 1:
            out.append(f"Cambia la {lab}: " + ", ".join(f"{e['isin']} {cat.val(e['fund'].get(f)) if cat.val(e['fund'].get(f)) is not None else 'n.d.'}"
                                                       .replace(" True", " coperta").replace(" False", " non coperta") for e in entries) + ".")
    doms = {cat.val(e["identity"].get("domicile")) for e in entries}
    if len(doms) > 1:
        out.append("Domicilio diverso (" + ", ".join(str(d) for d in doms) + "): può cambiare il trattamento fiscale dei dividendi esteri dentro il fondo.")
    sizes = [cat.val(e["fund"].get("sizeFund")) for e in entries]
    if all(s is not None for s in sizes) and len({cat.val(e["identity"].get("fundKey")) for e in entries}) > 1 and max(sizes) > 5 * min(sizes):
        out.append("Dimensioni molto diverse: il fondo più piccolo ha in genere meno scambi, ma non per questo è più rischioso se supera qualche centinaio di milioni.")
    return out
