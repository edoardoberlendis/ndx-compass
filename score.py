"""Final signal per stock: technical 40% + analysts 25% + valuation 20% + news 15%.

Every component is a score from -100 (clearly negative) to +100 (clearly positive) with the Italian
reasons behind it. A component without data is left out and the other weights are rescaled, so a
stock with no analyst coverage is judged on the remaining parts (the detail panel says so).

    >= +50 Molto positivo · >= +20 Positivo · between Neutro · <= -20 Negativo · <= -50 Molto negativo

This is a mechanical combination of public data, not investment advice.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timedelta

from server import ET, classify_headline, mentions, name_words, news_time

WEIGHTS = {"tech": 0.40, "analysts": 0.25, "valuation": 0.20, "news": 0.15}
NAMES = {"tech": "Tecnica", "analysts": "Analisti", "valuation": "Valutazione", "news": "Notizie"}
NEWS_DAYS = 3
KEY_NEWS = {"earnings", "guidance", "analyst", "deal", "legal"}   # categories that move prices the most
# market-wide pieces that merely list the stock: their tone is about the market, not the company
MARKET_PIECE = r"futures|stock market|wall street|\bs&p\b|\bdow\b|nasdaq(?!-100 stock)|stocks? (in focus|to (buy|watch))|magnificent seven|mag 7"


def level(score):
    if score >= 50:
        return "Molto positivo"
    if score >= 20:
        return "Positivo"
    if score > -20:
        return "Neutro"
    if score > -50:
        return "Negativo"
    return "Molto negativo"


def _clamp(x, lo=-100, hi=100):
    return max(lo, min(hi, x))


def _it(x, fmt):
    return format(x, fmt).replace(".", ",")


def _blend(parts):
    """Weighted mean of (score, weight) pairs, ignoring missing scores."""
    parts = [(s, w) for s, w in parts if s is not None]
    return sum(s * w for s, w in parts) / sum(w for _, w in parts) if parts else None


# ---------------------------------------------------------------- components

def technical(m):
    """m = signals.metrics(): trend score from the 20/40/60-day averages, RSI and strength vs QQQ."""
    if not m:
        return None
    stack = {"bull": "Medie 20 > 40 > 60 in ordine rialzista", "bear": "Medie 20 < 40 < 60 in ordine ribassista",
             "mixed": "Medie mobili senza un ordine chiaro"}[m["stack"]]
    rel = "meglio" if m["rs1m"] >= 0 else "peggio"
    return {"score": _clamp(m["score"]), "reasons": [
        stack,
        f"Prezzo {_it(m['vs20'], '+.1f')}% vs media 20 · {_it(m['vs40'], '+.1f')}% vs 40 · {_it(m['vs60'], '+.1f')}% vs 60",
        f"Ultimo mese: {rel} di QQQ di {_it(abs(m['rs1m']), '.1f')} punti · RSI {m['rsi']:.0f}"
        + (" (ipercomprato)" if m["rsi"] > 70 else " (ipervenduto)" if m["rsi"] < 30 else ""),
    ]}


def analysts(row):
    """Upside to the mean target, average rating, last-30-day actions and EPS estimate revisions."""
    up, rec, rev = row.get("upside"), row.get("recMean"), row.get("epsRev30")
    has_actions = row.get("up30") is not None
    parts, reasons = [], []
    if up is not None:
        parts.append((math.tanh(up / 20) * 100, 0.30))
        reasons.append(f"Target medio {_it(up, '+.0f')}% rispetto al prezzo")
    if rec is not None:        # 1 = forte acquisto … 5 = forte vendita; 2.5 counts as neutral
        parts.append((_clamp((2.5 - rec) * 100), 0.20))
        reasons.append(f"Giudizio medio {_it(rec, '.1f')} su una scala da 1 (forte acquisto) a 5 (forte vendita)")
    if has_actions:
        net = (row["up30"] - row["down30"]) * 25 + (row.get("ptUp30", 0) - row.get("ptDown30", 0)) * 8
        parts.append((_clamp(net), 0.20))
        if row["up30"] or row["down30"] or row.get("ptUp30") or row.get("ptDown30"):
            reasons.append(f"Ultimi 30 giorni: {row['up30']} upgrade, {row['down30']} downgrade, "
                           f"target alzati {row.get('ptUp30', 0)} e abbassati {row.get('ptDown30', 0)}")
    if rev is not None:
        parts.append((math.tanh(rev / 5) * 100, 0.30))
        reasons.append(f"Stima utile del prossimo anno {_it(rev, '+.1f')}% negli ultimi 30 giorni")
    score = _blend(parts)
    return None if score is None else {"score": score, "reasons": reasons}


def valuation(val):
    """val = analysts.valuation(): combined ratio vs sector and own history, plus PEG."""
    if not val or val.get("ratio") is None:
        return None
    ratio, peg = val["ratio"], val.get("peg")
    score = -math.tanh(math.log(ratio) / 0.25) * 100
    if peg is not None:
        score += 15 if peg < 1 else -15 if peg > 2.5 else 0
    d = (ratio - 1) * 100
    reasons = [f"{val['label']}: in media {_it(abs(d), '.0f')}% {'sopra' if d > 0 else 'sotto'} i confronti con settore e storia"
               if abs(d) >= 3 else f"{val['label']}: in linea con settore e storia"]
    if peg is not None:
        reasons.append(f"PEG {_it(peg, '.2f')}" + (" (crescita a buon prezzo)" if peg < 1 else " (caro rispetto alla crescita)" if peg > 2.5 else ""))
    return {"score": _clamp(score), "reasons": reasons}


def news(ticker, name, items, now=None):
    """Tone of the last NEWS_DAYS days of headlines that name the company (recent and key news weigh more)."""
    if items is None:
        return None
    now = now or datetime.now(ET)
    names, total, pos, neg, best = name_words(ticker, name), 0.0, 0, 0, None
    for n in items:
        t = news_time(n)
        if not t or t < now - timedelta(days=NEWS_DAYS) or not mentions(n["title"], ticker, names):
            continue
        if re.search(MARKET_PIECE, n["title"].lower()):
            continue
        c = classify_headline(n["title"], n.get("summary"))
        if not c["tone"]:
            continue
        w = (1.5 if {k for k, _ in c["cats"]} & KEY_NEWS else 1.0) * 0.5 ** ((now - t).total_seconds() / 86400)
        total += c["tone"] * w
        pos, neg = pos + (c["tone"] > 0), neg + (c["tone"] < 0)
        if best is None or w > best[0]:
            best = (w, n["title"])
    if not pos and not neg:
        return {"score": 0.0, "reasons": [f"Nessuna notizia con un tono chiaro negli ultimi {NEWS_DAYS} giorni"]}
    count = lambda n, one, many: f"{n} {one if n == 1 else many}"
    reasons = [f"Ultimi {NEWS_DAYS} giorni: {count(pos, 'notizia positiva', 'notizie positive')} e "
               f"{count(neg, 'negativa', 'negative')} sul titolo"]
    if best:
        reasons.append(f"La più rilevante: “{best[1]}”")
    # tanh(total / 4): one fresh key headline ≈ ±35, it takes several concordant ones to get near ±100
    return {"score": math.tanh(total / 4) * 100, "reasons": reasons}


# ---------------------------------------------------------------- combine

def combine(tech=None, anl=None, val=None, nws=None):
    comps = {"tech": tech, "analysts": anl, "valuation": val, "news": nws}
    avail = {k: c for k, c in comps.items() if c is not None}
    if "tech" not in avail:                    # without prices there is no meaningful signal
        return None
    wsum = sum(WEIGHTS[k] for k in avail)
    score = sum(c["score"] * WEIGHTS[k] for k, c in avail.items()) / wsum
    return {
        "score": round(score, 1), "signal": level(score),
        "components": [{"key": k, "name": NAMES[k], "weight": WEIGHTS[k], "used": k in avail,
                        "effWeight": WEIGHTS[k] / wsum if k in avail else 0,
                        "score": round(comps[k]["score"], 1) if k in avail else None,
                        "reasons": comps[k]["reasons"] if k in avail else ["Dati non disponibili: peso ridistribuito sulle altre parti"]}
                       for k in WEIGHTS],
    }


def for_stock(row, m, val, items):
    """row: snapshot row (price, upside, recMean, analyst summary…), m: signals.metrics, val: valuation, items: news."""
    return combine(technical(m), analysts(row), valuation(val), news(row["ticker"], row.get("name"), items))
