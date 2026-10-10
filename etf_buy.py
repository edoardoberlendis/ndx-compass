"""Ricerca → ETF, "Ha senso comprare?" (plan phase 24, part C): a verdict for every ETF like the Decisione section of
the stocks, with explicit rules shown under the verdict with ✅/❌, an operating plan and the ETF diary.

Rules approved by the user (10 Oct 2026), checked in this order, the first that applies decides:
  E1 leveraged product                     -> "Solo informazione" (never "Entra ora")
  E2 trend Ribassista                       -> Evita
  E3 "si sovrappone" to my portfolio        -> Evita (personal)
  E4 fund size below 100 million           -> Evita
  A0 trend not computable                   -> Attendi
  A1 trend Laterale                         -> Attendi
  A2 TER above 0.50%                        -> Attendi
  A3 "neutro" for my portfolio              -> Attendi (personal)
  R1 risk of arriving late "alto"           -> Entra su ritracciamento (entry at the 50-day average)
  N  everything else                        -> Entra ora
The second line "Solo mercato" uses the same rules without E3 and A3. Momentum 12-1 is shown as information only.
Nothing here is verified: the momentum rules failed the test (etf_backtest.py), so every verdict says "non verificato".

Plan: entry (price, or the 50-day average for R1), stop with the same rule as the stocks (decision.stops), target at
twice the risk, quantity from the risk per trade (regole.json) capped at 10% of the portfolio for each ETF (only for
the ETFs; the stocks keep their rules). The ETFs of the list trade in euro (Borsa Italiana or Xetra): no exchange spread.

Diary: portafoglio/diario_etf/AAAA-MM-GG.json, one file per session of Borsa Italiana, written once and never rewritten,
with both verdicts; statistics at 1, 3 and 6 months against all the ETFs of the same day.
"""
from __future__ import annotations

import json
import math
import os
from datetime import date

ROOT = os.path.dirname(os.path.abspath(__file__))
DIR = os.path.join(ROOT, "portafoglio", "diario_etf")
SIZE_MIN, TER_MAX = 100.0, 0.50
CAP = 10.0                                   # % of the portfolio, at most, in one ETF
HORIZONS = {"1 mese": 21, "3 mesi": 63, "6 mesi": 126}
MIN_CASES, MIN_DAYS = 100, 20                # as the stock diary: fewer cases -> "troppo pochi casi"


def it(x, d=1):
    return f"{x:.{d}f}".replace(".", ",")


def eur(x):
    return it(x, 2) + " €"


# ---------------------------------------------------------------- the verdict (pure, tested)

def pct_text(p):
    """Percentile with a decimal near the thresholds 70 and 90 (90,4 is "alto": never written as 90)."""
    return it(p, 1 if any(abs(p - t) < 1 for t in (70, 90)) else 0)


def checks(row, fit):
    """[{id, label, ok, value, personal}] of every rule; ok=True means the rule does NOT stop the purchase."""
    late = (row.get("late") or {}).get("level")
    t = row.get("trend")
    lev = row.get("leverage") or 1
    fv = (fit or {}).get("verdict")
    out = [
        {"id": "E1", "label": "Prodotto senza leva", "ok": lev == 1, "value": "senza leva" if lev == 1 else f"leva {it(lev, 0)}x", "personal": False},
        {"id": "E2", "label": "Trend non ribassista", "ok": t != "Ribassista", "value": t or "non calcolabile", "personal": False},
        {"id": "E3", "label": "Non si sovrappone al tuo portafoglio", "ok": fv != "si sovrappone", "value": fv or "portafoglio non caricato", "personal": True},
        {"id": "E4", "label": f"Patrimonio almeno {it(SIZE_MIN, 0)} milioni", "ok": (row.get("sizeEurM") or 0) >= SIZE_MIN,
         "value": f"{it(row['sizeEurM'], 0)} mln €" if row.get("sizeEurM") is not None else "non disponibile", "personal": False},
        {"id": "A0", "label": "Trend calcolabile (medie 50 e 200)", "ok": t is not None, "value": t or "storia troppo breve", "personal": False},
        {"id": "A1", "label": "Trend non laterale", "ok": t != "Laterale", "value": t or "—", "personal": False},
        {"id": "A2", "label": f"TER al massimo {it(TER_MAX, 2)}%", "ok": row.get("ter") is not None and row["ter"] <= TER_MAX,
         "value": f"{it(row['ter'], 2)}%" if row.get("ter") is not None else "non disponibile", "personal": False},
        {"id": "A3", "label": "Diversifica il tuo portafoglio (non «neutro»)", "ok": fv not in ("neutro", None), "value": fv or "portafoglio non caricato", "personal": True},
        {"id": "R1", "label": "Rischio di essere arrivati tardi non alto", "ok": late != "alto",
         "value": f"{late} ({pct_text(row['late']['percentile'])}° percentile)" if late else "non calcolabile", "personal": False},
    ]
    return out


VERDICT_OF = {"E1": "Solo informazione", "E2": "Evita", "E3": "Evita", "E4": "Evita", "A0": "Attendi", "A1": "Attendi",
              "A2": "Attendi", "A3": "Attendi", "R1": "Entra su ritracciamento"}
WHY = {"E1": "prodotto a leva: solo informazione", "E2": "trend ribassista", "E3": "si sovrappone al tuo portafoglio: compreresti di più quello che hai",
       "E4": "patrimonio piccolo: rischio di chiusura e spread alti", "A0": "storia troppo breve per il trend", "A1": "trend laterale",
       "A2": "costoso: guarda le altre versioni", "A3": "non migliora la diversificazione del tuo portafoglio",
       "R1": "rischio di essere arrivati tardi alto: meglio aspettare un ritorno verso la media 50"}


def verdict(cks, personal=True):
    """(verdict, rule id, why) from the checks; personal=False skips E3 and A3 ("Solo mercato")."""
    for c in cks:
        if not personal and c["personal"]:
            continue
        if not c["ok"]:
            return VERDICT_OF[c["id"]], c["id"], WHY[c["id"]]
    return "Entra ora", "N", "tutte le condizioni sono soddisfatte"


def quantity(entry, stop, total, risk_pct, cap_pct=CAP):
    """Shares so that the stop loses at most risk_pct% of the portfolio, capped at cap_pct% of the portfolio.
    Returns {qty, eur, weight, risk, capped, wanted (weight the risk alone would need), sentence}."""
    if not total or entry <= stop or entry <= 0:
        return None
    by_risk = math.floor(total * risk_pct / 100 / (entry - stop) + 1e-9)
    by_cap = math.floor(total * cap_pct / 100 / entry + 1e-9)
    qty = min(by_risk, by_cap)
    out = {"qty": qty, "eur": qty * entry, "weight": qty * entry / total * 100, "risk": qty * (entry - stop) / total * 100,
           "capped": by_cap < by_risk, "wanted": by_risk * entry / total * 100}
    out["sentence"] = (f"quantità limitata al {it(cap_pct, 0)}% del portafoglio: con questo stop l'{it(risk_pct, 0)}% di rischio richiederebbe "
                       f"il {it(out['wanted'], 0)}%; rischio effettivo {it(out['risk'], 2)}% del portafoglio"
                       if out["capped"] else f"rischio {it(out['risk'], 2)}% del portafoglio se scatta lo stop")
    return out


def plan(row, kind, total, risk_pct):
    """Entry, stop options (decision.stops, in euro), target at 2x the risk and quantity. None without levels."""
    from decision import stops
    lv = row.get("planLevels")
    if not lv or not lv.get("atr"):
        return None
    entry = lv["price"] if kind == "now" else lv["sma50"]
    opts, default, why = stops(entry, lv, money=eur)
    if not default:
        return None
    for o in opts:
        o["qty"] = quantity(entry, o["v"], total, risk_pct)
        o["target"] = entry + 2 * (entry - o["v"])
    st = next(o for o in opts if o["id"] == default)
    return {"kind": kind, "entry": entry, "entryNote": "prezzo di chiusura" if kind == "now" else "media 50 (ordine limite)",
            "listing": lv.get("listing"), "date": lv.get("date"), "opts": opts, "def": default, "why": why, "stop": st["v"],
            "target": st["target"], "qty": st["qty"], "spread": f"ETF in euro su {lv.get('market') or 'Borsa Italiana'}: nessuno spread di cambio"}


def decide(row, fit, total=None, risk_pct=1.0):
    """Everything the page shows under "Ha senso comprare?"."""
    cks = checks(row, fit)
    v, by, why = verdict(cks, personal=True)
    mv, mby, mwhy = verdict(cks, personal=False)
    out = {"verdict": v if fit else None, "by": by if fit else None, "why": why if fit else None,
           "market": {"verdict": mv, "by": mby, "why": mwhy}, "checks": cks, "momentum": row.get("mom12_1")}
    main = v if fit else mv
    kind = {"Entra ora": "now", "Entra su ritracciamento": "pullback"}.get(main) or {"Entra ora": "now", "Entra su ritracciamento": "pullback"}.get(mv)
    if kind:
        out["plan"] = plan(row, kind, total, risk_pct)
        out["planFor"] = "verdetto" if fit and v in ("Entra ora", "Entra su ritracciamento") else "solo mercato"
    return out


# ---------------------------------------------------------------- the ETF diary

def path(day):
    return os.path.join(DIR, f"{day}.json")


def exists(day):
    return os.path.exists(path(day))


def entry(row, d):
    """One ETF of one day: price of the listing, both verdicts, the rule that decided them and the plan."""
    lv = row.get("planLevels") or {}
    p = d.get("plan") or {}
    return {"isin": row["isin"], "category": row["category"], "listing": lv.get("listing"), "price": lv.get("price"),
            "verdict": d.get("verdict"), "by": d.get("by"), "market": d["market"]["verdict"], "marketBy": d["market"]["by"],
            "trend": row.get("trend"), "late": (row.get("late") or {}).get("level"), "mom12_1": row.get("mom12_1"),
            "entry": p.get("entry"), "stop": p.get("stop")}


def save(day, entries):
    """Write the day once; an existing day is never rewritten. True if written."""
    if exists(day) or not entries:
        return False
    os.makedirs(DIR, exist_ok=True)
    tmp = path(day) + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"day": day, "saved": date.today().isoformat(), "etfs": entries}, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path(day))
    return True


def days():
    if not os.path.isdir(DIR):
        return []
    return sorted(f[:-5] for f in os.listdir(DIR) if f.endswith(".json") and len(f) == 15)


def load(day):
    with open(path(day)) as f:
        return json.load(f)


def forward(closes, day, n):
    """% change of a close series from the session `day` to n sessions later, or None if not there yet."""
    if closes is None:
        return None
    idx = [str(d.date()) for d in closes.index]
    if day not in idx:
        return None
    i = idx.index(day)
    if i + n >= len(closes):
        return None
    return float(closes.iloc[i + n] / closes.iloc[i] - 1) * 100


def stats(closes, key="verdict"):
    """{horizon: {verdict: {cases, days, mean, extra, beat, enough}}}: how each verdict did against all the ETFs of
    the same day (extra = return minus the mean of all ETFs that day). closes: {isin: daily closes of the listing}."""
    out = {}
    for h, n in HORIZONS.items():
        acc = {}
        for day in days():
            rows = load(day)["etfs"]
            moves = {r["isin"]: forward(closes.get(r["isin"]), day, n) for r in rows}
            ok = [m for m in moves.values() if m is not None]
            if not ok:
                continue
            avg = sum(ok) / len(ok)
            for r in rows:
                m = moves.get(r["isin"])
                if m is None or not r.get(key):
                    continue
                a = acc.setdefault(r[key], {"cases": 0, "days": set(), "sum": 0.0, "extra": 0.0, "beat": 0})
                a["cases"] += 1
                a["days"].add(day)
                a["sum"] += m
                a["extra"] += m - avg
                a["beat"] += m > avg
        out[h] = {v: {"cases": a["cases"], "days": len(a["days"]), "mean": a["sum"] / a["cases"], "extra": a["extra"] / a["cases"],
                      "beat": a["beat"] / a["cases"] * 100, "enough": a["cases"] >= MIN_CASES and len(a["days"]) >= MIN_DAYS}
                  for v, a in acc.items()}
    return out
