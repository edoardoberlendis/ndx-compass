"""Opportunità (plan phases O1-O2): two exploratory rankings of the Nasdaq-100 stocks worth a closer look.

    Trading      (3-30 sessions)  -> price behaviour only: strength against QQQ, averages, volumes
    Investimento (3-24 months)    -> the company: the six checks of the "Pagella" (pillars.py, thresholds approved by
                                     the user on 4 November 2026), with the long trend of rule B2 (actions.py)

This is a SCREENING, not a signal: nothing here has passed a backtest, there is no probability, no expected return and
no "buy". Every stock gets a list of yes/no conditions with the measured value and the threshold; the ranking is the
number of conditions met, then the number of warnings, then one measured value (written in ORDER). A missing figure is
never neutral or positive: it counts as a condition NOT met and the stock is marked "Dati insufficienti".

Prices: only CLOSED daily sessions, cut at `as_of` (nothing after that day is read, see tests). Analyst data,
valuation, news and earnings dates are today's data: they have no history.
The patterns that failed the phase 11 test are never a reason: when a candidate shows one, it becomes a warning.
Pure functions, no download, no file: the server passes the data it already has in memory.

Phase O2: every row also carries a diagnosis that keeps apart relative strength (against QQQ), absolute direction and
the market context, without changing the ranking; the coverage of every condition over the universe; the model
version and its parameters (the experimental ones are marked); with keep_all=True the full list of observations
(every stock, selected or not) for the opportunity diary (opportunity_diary.py).
"""
from __future__ import annotations

import math
import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd

import pillars
from etf import trend_word

ET = ZoneInfo("America/New_York")
TOP = 10                  # rows shown in each ranking
MIN_SESSIONS = 70         # closed sessions needed for the trading conditions (63 for 3 months + the 20-day average slope)
SLOPE_DAYS = 5            # "media 20 in salita": the 20-day average against 5 sessions before
VOL_SHORT, VOL_LONG = 20, 60   # volume ratio, as signals.metrics
VOL_MIN_DAYS = 57         # volumes are trusted only if at least 57 of the last 60 sessions have a volume above zero
ATR_HIGH = 4.0            # warning: average daily range (ATR 14) above 4% of the price
EXTENDED, RSI_MAX = 8.0, 75   # warning "tirato": the same thresholds as rule D5 of decision.py (read, not changed)
EARNINGS_DAYS = 5         # warning: earnings within 5 days, as rule D2 / T5
EPS_CUT_30 = -3.0         # warning: estimates cut more than 3% in 30 days, as rule T3
NEWS_NEG = -20            # warning: news tone at or below the "Negativo" threshold of the signal (score.py)
TRADING_MIN, INVEST_MIN = 4, 5   # conditions to meet (out of 5 and 6) to enter the ranking
COVERAGE_MIN = 0.80       # a condition judged for fewer than 80% of the evaluated stocks makes the ranking "incompleta"
MODEL_VERSION = "O2.1"    # changes whenever a condition, a threshold or the order changes (the diary keeps it per day)

# every parameter of the model, saved with each day of the diary. "experimental": proposed in phase O1 and never
# validated (the user asked to keep them for compatibility and not to change them without a specific evaluation)
PARAMS = [
    {"key": "TRADING_MIN", "value": TRADING_MIN, "text": "condizioni Trading da soddisfare (su 5)", "experimental": True},
    {"key": "INVEST_MIN", "value": INVEST_MIN, "text": "condizioni Investimento da soddisfare (su 6)", "experimental": True},
    {"key": "ATR_HIGH", "value": ATR_HIGH, "text": "avviso di volatilità alta: ATR 14 oltre questa % del prezzo", "experimental": True},
    {"key": "COVERAGE_MIN", "value": COVERAGE_MIN, "text": "quota minima di titoli con il dato perché la classifica sia completa", "experimental": True},
    {"key": "MIN_SESSIONS", "value": MIN_SESSIONS, "text": "sedute chiuse necessarie per le condizioni Trading", "experimental": False},
    {"key": "VOL_MIN_DAYS", "value": VOL_MIN_DAYS, "text": "sedute con volume (su 60) perché i volumi siano attendibili", "experimental": False},
    {"key": "EXTENDED", "value": EXTENDED, "text": "avviso «tirato»: % sopra la media 20 (regola D5)", "experimental": False},
    {"key": "RSI_MAX", "value": RSI_MAX, "text": "avviso «tirato»: RSI (regola D5)", "experimental": False},
    {"key": "EARNINGS_DAYS", "value": EARNINGS_DAYS, "text": "avviso trimestrale: giorni (regole D2 e T5)", "experimental": False},
    {"key": "EPS_CUT_30", "value": EPS_CUT_30, "text": "avviso stime tagliate in 30 giorni, % (regola T3)", "experimental": False},
    {"key": "NEWS_NEG", "value": NEWS_NEG, "text": "avviso notizie: punteggio del tono (soglia «Negativo» del segnale)", "experimental": False},
    {"key": "TOP", "value": TOP, "text": "titoli mostrati per classifica", "experimental": False},
]

TRADING = [
    ("T1", "Più forte del Nasdaq-100 a 1 mese", "Rendimento delle ultime 21 sedute meglio di QQQ (differenza sopra 0 punti)"),
    ("T2", "Più forte del Nasdaq-100 a 3 mesi", "Rendimento delle ultime 63 sedute meglio di QQQ (differenza sopra 0 punti)"),
    ("T3", "Sopra le medie 20 e 50", "Ultima chiusura sopra la media a 20 giorni e sopra la media a 50 giorni"),
    ("T4", "Media 20 in salita", "Media a 20 giorni più alta di 5 sedute prima"),
    ("T5", "Volumi in aumento", "Volume medio delle ultime 20 sedute almeno pari a quello delle ultime 60 (solo con volumi completi)"),
]
INVEST = [
    ("I1", "Ricavi in crescita", "Ricavi dell'ultimo bilancio annuale cresciuti di almeno il 10% (soglia della Pagella)"),
    ("I2", "Margine operativo stabile", "Margine operativo dell'ultimo bilancio non sceso più di 1 punto (soglia della Pagella)"),
    ("I3", "Stime di utile non tagliate", "Stima di utile del prossimo anno non tagliata più del 3% in 90 giorni (soglia della Pagella)"),
    ("I4", "Consenso degli analisti", "Consenso almeno «Acquisto» (soglia della Pagella)"),
    ("I5", "Valutazione non cara", "Giudizio di valutazione della dashboard (settore e storia) diverso da «Cara»"),
    ("I6", "Trend di fondo intatto", "Prezzo sopra la media 200 e media 50 sopra la media 200 (regola B2), su sedute chiuse"),
]
ORDER = {
    "trading": f"Prima i titoli con più condizioni soddisfatte (servono almeno {TRADING_MIN} su 5), poi quelli con meno avvisi, "
               "poi la differenza con QQQ a 1 mese più alta.",
    "invest": f"Prima i titoli con più condizioni soddisfatte (servono almeno {INVEST_MIN} su 6), poi quelli con meno avvisi, "
              "poi la valutazione più bassa rispetto a settore e storia.",
}
MAIN_FIRST = {"trading": ["T1", "T2", "T3", "T4", "T5"], "invest": ["I1", "I5", "I3", "I4", "I2", "I6"]}

it, sgn = pillars.it, pillars.sgn


def _num(x):
    return x is not None and not (isinstance(x, float) and math.isnan(x))


def _ret(s, n):
    """% return over the last n sessions, or None."""
    if len(s) <= n or not _num(s.iloc[-1]) or not _num(s.iloc[-1 - n]) or s.iloc[-1 - n] == 0:
        return None
    return float(s.iloc[-1] / s.iloc[-1 - n] - 1) * 100


def _rsi(c, n=14):
    d = c.diff().iloc[-(n * 3):]
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean().iloc[-1]
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean().iloc[-1]
    return 100.0 if dn == 0 else float(100 - 100 / (1 + up / dn))     # same formula as signals.rsi


def cut(df, as_of):
    """The rows up to as_of included: nothing after that day can be read."""
    if df is None or as_of is None:
        return df
    idx = df.index.tz_localize(None) if getattr(df.index, "tz", None) is not None else df.index
    return df[idx.normalize() <= pd.Timestamp(as_of)]


# ---------------------------------------------------------------- numbers from the closed daily sessions

def tech(df, bench):
    """Price figures of one stock on closed sessions, or None with fewer than MIN_SESSIONS. bench: QQQ closes."""
    if df is None or "Close" not in df:
        return None
    df = df.dropna(subset=["Close"])
    n = len(df)
    if n < MIN_SESSIONS:
        return None
    c, h, lo = df["Close"], df["High"], df["Low"]
    mean = lambda k, end=None: float(c.iloc[-k - (end or 0): len(c) - (end or 0)].mean()) if n >= k + (end or 0) else None
    s20, s50, s200 = mean(20), mean(50), mean(200)
    s20_prev = mean(20, SLOPE_DAYS)
    b = bench.reindex(c.index).ffill() if bench is not None else None
    r = {k: _ret(c, k) for k in (5, 21, 63, 126, 252)}
    q = {k: (_ret(b, k) if b is not None else None) for k in (21, 63)}
    tr = pd.concat([h - lo, (h - c.shift()).abs(), (lo - c.shift()).abs()], axis=1).max(axis=1)
    atr = float(tr.rolling(14).mean().iloc[-1])
    vol_ratio = None
    if "Volume" in df:
        v = df["Volume"].iloc[-VOL_LONG:]
        if len(v) == VOL_LONG and int((v > 0).sum()) >= VOL_MIN_DAYS and v.mean() > 0:
            vol_ratio = float(df["Volume"].iloc[-VOL_SHORT:].mean() / v.mean())
    close = float(c.iloc[-1])
    pc = lambda a: (close / a - 1) * 100 if a else None
    return {
        "date": df.index[-1].date().isoformat(), "close": close, "sessions": n,
        "sma20": s20, "sma50": s50, "sma200": s200, "vs20": pc(s20), "vs50": pc(s50), "vs200": pc(s200),
        "slope20": (s20 / s20_prev - 1) * 100 if s20 and s20_prev else None,
        "ret5": r[5], "ret21": r[21], "ret63": r[63], "ret126": r[126], "ret252": r[252], "q21": q[21], "q63": q[63],
        "rs21": r[21] - q[21] if _num(r[21]) and _num(q[21]) else None,
        "rs63": r[63] - q[63] if _num(r[63]) and _num(q[63]) else None,
        "atrPct": atr / close * 100 if close else None, "rsi": _rsi(c), "volRatio": vol_ratio,
        "trend": trend_word(close, s50, s200),
    }


def sector_medians(techs, universe, key="ret126"):
    """{sector: (median of key, n)} over the stocks with the figure."""
    out = {}
    for u in universe:
        t = techs.get(u["ticker"])
        if t and _num(t.get(key)):
            out.setdefault(u.get("sector") or "", []).append(t[key])
    return {s: (float(pd.Series(v).median()), len(v)) for s, v in out.items()}


# ---------------------------------------------------------------- diagnosis: relative strength is not a rising trend

def diagnose(t):
    """Absolute returns, returns against QQQ and direction kept apart (phase O2). No threshold, no effect on the order:
    only a label when a stock beats QQQ while its own price falls ("scende meno del mercato")."""
    if not t:
        return {"abs21": None, "abs63": None, "rel21": None, "rel63": None, "trend": None, "direction": None, "flag": None}
    a21, a63, r21, r63 = t.get("ret21"), t.get("ret63"), t.get("rs21"), t.get("rs63")
    signs = [x > 0 for x in (a21, a63) if _num(x)]
    direction = None if not signs else "in salita" if all(signs) else "in calo" if not any(signs) else "misto"
    flag = None
    falling = [lab for lab, a, r in (("1 mese", a21, r21), ("3 mesi", a63, r63)) if _num(a) and _num(r) and r > 0 and a < 0]
    if falling:
        flag = f"Più forte di QQQ ma in calo a {' e '.join(falling)}: scende meno del mercato, non sale"
    elif (_num(r21) and r21 > 0) and t.get("trend") == "Ribassista":
        flag = "Più forte di QQQ a 1 mese ma con trend ribassista (prezzo sotto la media 50, media 50 sotto la media 200)"
    return {"abs21": a21, "abs63": a63, "rel21": r21, "rel63": r63, "trend": t.get("trend"), "direction": direction, "flag": flag}


def market_context(bclose, techs):
    """QQQ on the same closed sessions and the share of stocks above their 200-day average."""
    q = tech(pd.DataFrame({"Close": bclose, "High": bclose, "Low": bclose}), None) if bclose is not None else None
    above = [t["vs200"] > 0 for t in techs.values() if t and _num(t.get("vs200"))]
    return {"qqq1m": q["ret21"] if q else None, "qqq3m": q["ret63"] if q else None, "qqqTrend": q["trend"] if q else None,
            "qqqVs50": q["vs50"] if q else None, "qqqVs200": q["vs200"] if q else None,
            "above200": sum(above) / len(above) * 100 if above else None, "above200n": len(above),
            "date": q["date"] if q else None}


def coverage(entries, catalog):
    """How many stocks each condition could be judged for: [{id, name, available, total, missing: [tickers]}]."""
    out = []
    for cid, name, _ in catalog:
        miss = [e["ticker"] for e in entries if next(c for c in e["conditions"] if c["id"] == cid)["state"] == "na"]
        out.append({"id": cid, "name": name, "available": len(entries) - len(miss), "total": len(entries), "missing": miss})
    return out


# ---------------------------------------------------------------- the two lists of conditions

def _cond(cid, catalog, state, detail, short=None):
    """short: the few words shown in the table when the condition is met (the full detail is in the row's panel)."""
    name = next(n for i, n, _ in catalog if i == cid)
    return {"id": cid, "name": name, "state": state, "detail": detail, "short": short or name.lower()}


def trading_conditions(t):
    """Five yes/no/na conditions on prices (t from tech(), or None)."""
    if not t:
        return [_cond(i, TRADING, "na", f"meno di {MIN_SESSIONS} sedute chiuse di prezzi") for i, _, _ in TRADING]
    out = []
    for cid, k, q, n in (("T1", "rs21", "q21", 21), ("T2", "rs63", "q63", 63)):
        rs, own = t.get(k), t.get(f"ret{n}")
        if not _num(rs):
            out.append(_cond(cid, TRADING, "na", f"rendimento a {n} sedute di titolo o QQQ non disponibile"))
        else:
            out.append(_cond(cid, TRADING, "ok" if rs > 0 else "ko",
                             f"{sgn(own)}% contro {sgn(t[q])}% di QQQ in {n} sedute: {sgn(rs)} punti (soglia: sopra 0)",
                             f"{sgn(rs)} punti su QQQ a {'1 mese' if n == 21 else '3 mesi'}"))
    if not (_num(t.get("vs20")) and _num(t.get("vs50"))):
        out.append(_cond("T3", TRADING, "na", "medie 20 e 50 non calcolabili"))
    else:
        out.append(_cond("T3", TRADING, "ok" if t["vs20"] > 0 and t["vs50"] > 0 else "ko",
                         f"chiusura {sgn(t['vs20'])}% dalla media 20 e {sgn(t['vs50'])}% dalla media 50 (soglia: sopra entrambe)",
                         "sopra le medie 20 e 50"))
    if not _num(t.get("slope20")):
        out.append(_cond("T4", TRADING, "na", "media 20 di 5 sedute prima non calcolabile"))
    else:
        out.append(_cond("T4", TRADING, "ok" if t["slope20"] > 0 else "ko",
                         f"media 20 {sgn(t['slope20'], 2)}% rispetto a {SLOPE_DAYS} sedute prima (soglia: sopra 0)"))
    if not _num(t.get("volRatio")):
        out.append(_cond("T5", TRADING, "na", "volumi mancanti o a zero in alcune delle ultime 60 sedute: dato non attendibile"))
    else:
        out.append(_cond("T5", TRADING, "ok" if t["volRatio"] >= 1 else "ko",
                         f"volume medio 20 sedute {it(t['volRatio'], 2)} volte quello di 60 sedute (soglia: almeno 1)",
                         f"volumi {it(t['volRatio'], 2)}× la media di 60 sedute"))
    return out


def invest_conditions(t, f):
    """Six yes/no/na conditions: the Pagella checks (pillars.py, same functions and thresholds) and rule B2."""
    f = f or {}
    first_pct = lambda d: (m.group(0) if (m := re.search(r"[+−]?[\d.]+(,\d+)?%", d)) else "")
    st, d = pillars.revenue_growth(f.get("years"))
    out = [_cond("I1", INVEST, st, d, f"ricavi {first_pct(d)} nell'ultimo bilancio")]
    out.append(_cond("I2", INVEST, *pillars.operating_margin(f.get("years")), "margine operativo stabile"))
    st, d = pillars.estimates(f.get("epsRev90"))
    out.append(_cond("I3", INVEST, st, d, f"stime {first_pct(d)} in 90 giorni"))
    st, d = pillars.consensus(f.get("rec"))
    out.append(_cond("I4", INVEST, st, d, d))
    st, d = pillars.valuation(f.get("valLabel"))
    out.append(_cond("I5", INVEST, st, d, d))
    if not t or not (_num(t.get("sma200")) and _num(t.get("sma50"))):
        out.append(_cond("I6", INVEST, "na", "meno di 200 sedute chiuse di prezzi: media 200 non calcolabile"))
    else:
        ok = t["close"] > t["sma200"] and t["sma50"] > t["sma200"]
        out.append(_cond("I6", INVEST, "ok" if ok else "ko",
                         f"chiusura {sgn(t['vs200'])}% dalla media 200; media 50 {'sopra' if t['sma50'] > t['sma200'] else 'sotto'} la media 200",
                         f"{sgn(t['vs200'])}% sopra la media 200"))
    return out


# ---------------------------------------------------------------- warnings (contrary signals)

def earnings_days(ts, today):
    """Calendar days from today to the next earnings date (epoch seconds), None if unknown or already past."""
    if not _num(ts):
        return None, None
    d = datetime.fromtimestamp(ts, ET).date()
    return ((d - today).days, d) if d >= today else (None, None)


def _earn_warning(f, today):
    days, d = earnings_days(f.get("earningsTs"), today)
    if days is not None and days <= EARNINGS_DAYS:
        day = f"{d.day} {pillars.MONTHS[d.month - 1]}"
        return {"id": "earn", "short": f"trimestrale il {day}", "text": f"Trimestrale il {day} (tra {days} giorni): il prezzo può muoversi molto"}
    return None


def trading_warnings(t, f, patterns, failed, today):
    out = []
    if t:
        if (_num(t.get("vs20")) and t["vs20"] > EXTENDED) or (_num(t.get("rsi")) and t["rsi"] > RSI_MAX):
            vs = f"{sgn(t['vs20'])}% dalla media 20" if _num(t.get("vs20")) else "media 20 non calcolabile"
            rs = f"RSI {it(t['rsi'], 0)}" if _num(t.get("rsi")) else "RSI non calcolabile"
            out.append({"id": "ext", "short": "tirato (regola D5)", "text": f"Tirato: {vs}, {rs} (soglie della regola D5: oltre {it(EXTENDED, 0)}% o RSI oltre {RSI_MAX})"})
        if _num(t.get("vs200")) and t["vs200"] < 0:
            out.append({"id": "below200", "short": "sotto la media 200", "text": f"Sotto la media 200 ({sgn(t['vs200'])}%): trend di fondo negativo"})
        if _num(t.get("atrPct")) and t["atrPct"] > ATR_HIGH:
            out.append({"id": "vol", "short": f"volatilità alta ({it(t['atrPct'])}% al giorno)", "text": f"Volatilità alta: oscillazione media giornaliera (ATR 14) del {it(t['atrPct'])}% del prezzo "
                                             f"(soglia {it(ATR_HIGH, 0)}%)"})
    e = _earn_warning(f or {}, today)
    if e:
        out.append(e)
    for key in patterns or []:
        if key in failed:
            out.append({"id": "pattern", "short": f"«{failed[key]}»: test non superato", "text": f"Coincide con «{failed[key]}», che non ha superato il test dei pattern (Fase 11): "
                                                 "non è un motivo per comprare"})
    return out


def invest_warnings(t, f, today):
    f, out = f or {}, []
    up, down = f.get("up30"), f.get("down30")
    if _num(up) and _num(down) and down > up:
        out.append({"id": "down", "short": "più downgrade che upgrade", "text": f"Più downgrade che upgrade negli ultimi 30 giorni ({down} contro {up})"})
    if _num(f.get("epsRev30")) and f["epsRev30"] < EPS_CUT_30:
        out.append({"id": "cut30", "short": "stime tagliate in 30 giorni", "text": f"Stime di utile tagliate del {it(-f['epsRev30'])}% in 30 giorni (soglia della regola T3: 3%)"})
    e = _earn_warning(f, today)
    if e:
        out.append(e)
    news = f.get("news")
    if news and _num(news.get("score")) and news["score"] <= NEWS_NEG:
        out.append({"id": "news", "short": "notizie dal tono negativo", "text": f"Notizie degli ultimi 3 giorni dal tono negativo (punteggio {it(news['score'], 0)} su ±100)"})
    if t and _num(t.get("vs50")) and t["vs50"] < 0:
        out.append({"id": "below50", "short": f"sotto la media 50 ({sgn(t['vs50'])}%)", "text": f"Sotto la media 50 ({sgn(t['vs50'])}%): debolezza recente"})
    return out


# ---------------------------------------------------------------- measured values shown in the row's detail

def _pct_or(x, d=1):
    return f"{sgn(x, d)}%" if _num(x) else "non disponibile"


def trading_values(t):
    if not t:
        return []
    return [("Rendimento 1 settimana / 1 mese", f"{_pct_or(t['ret5'])} / {_pct_or(t['ret21'])}"),
            ("Distanza dalle medie 20 / 50 / 200", f"{_pct_or(t['vs20'])} / {_pct_or(t['vs50'])} / {_pct_or(t['vs200'])}"),
            ("RSI (14 sedute)", it(t["rsi"], 0) if _num(t.get("rsi")) else "non disponibile"),
            ("Oscillazione media giornaliera (ATR 14)", f"{it(t['atrPct'])}% del prezzo" if _num(t.get("atrPct")) else "non disponibile"),
            ("Volumi 20 / 60 sedute", f"{it(t['volRatio'], 2)}×" if _num(t.get("volRatio")) else "non attendibili")]


def invest_values(t, f, sector, med):
    f, out = f or {}, []
    if t:
        out.append(("Rendimento 6 mesi / 1 anno", f"{_pct_or(t['ret126'])} / {_pct_or(t['ret252'])}"))
        m = med.get(sector or "")
        if m and _num(t.get("ret126")) and m[1] >= 3:
            out.append(("Contro il settore a 6 mesi", f"{sgn(t['ret126'] - m[0])} punti rispetto alla mediana di {sector} ({m[1]} titoli)"))
        else:
            out.append(("Contro il settore a 6 mesi", "non calcolabile (meno di 3 titoli del settore con il dato)"))
    for note in f.get("valNotes") or []:
        out.append(("Valutazione", note))
    for label, k in (("Crescita degli utili (ultimo trimestre sull'anno prima)", "epsGrowth"), ("Margine netto", "margin")):
        out.append((label, f"{sgn(f[k] * 100)}%" if _num(f.get(k)) else "non disponibile"))
    news = f.get("news")
    out.append(("Notizie (3 giorni)", "; ".join(news.get("reasons") or []) if news else "non ancora scaricate"))
    return out


# ---------------------------------------------------------------- the rankings

METRIC_KEYS = ("close", "sessions", "sma20", "sma50", "sma200", "vs20", "vs50", "vs200", "slope20", "ret5", "ret21", "ret63",
               "ret126", "ret252", "q21", "q63", "rs21", "rs63", "atrPct", "rsi", "volRatio", "trend")
FUND_KEYS = ("epsRev90", "epsRev30", "up30", "down30", "rec", "valLabel", "valRatio", "earningsTs", "epsGrowth", "margin")


def _entry(u, conds, warns, values, t, f, kind, quote):
    ok = sum(c["state"] == "ok" for c in conds)
    missing = [c for c in conds if c["state"] == "na"]
    main = [c for i in MAIN_FIRST[kind] for c in conds if c["id"] == i and c["state"] == "ok"][:2]
    q = quote or {}
    if kind == "trading":
        perf = [("1 mese", t["ret21"] if t else None), ("3 mesi", t["ret63"] if t else None)]
        trend = f"{t['trend'] or 'non calcolabile'} · media 20 {'in salita' if (t['slope20'] or 0) > 0 else 'in discesa'}" if t and _num(t.get("slope20")) else "non calcolabile"
    else:
        perf = [("6 mesi", t["ret126"] if t else None), ("1 anno", t["ret252"] if t else None)]
        trend = f"{t['trend'] or 'non calcolabile'} · {sgn(t['vs200'])}% dalla media 200" if t and _num(t.get("vs200")) else "non calcolabile"
    return {
        "ticker": u["ticker"], "name": u.get("name") or u["ticker"], "sector": u.get("sector"),
        "price": q.get("price"), "priceTime": q.get("time"), "closeDate": t["date"] if t else None,
        "perf": [{"label": lab, "value": v} for lab, v in perf], "trend": trend,
        "status": "Dati insufficienti" if missing else "Da approfondire",
        "ok": ok, "n": len(conds), "conditions": conds, "warnings": warns,
        "missing": [{"name": c["name"], "detail": c["detail"]} for c in missing],
        "main": " · ".join(c["short"] for c in main) if main else "nessuna condizione soddisfatta",
        "values": [{"label": a, "value": b} for a, b in values],
        "diag": diagnose(t),
        "metrics": {**{k: (t or {}).get(k) for k in METRIC_KEYS},
                    **{k: (f or {}).get(k) for k in FUND_KEYS}, "newsScore": ((f or {}).get("news") or {}).get("score")},
        "_sort": (-(t or {}).get("rs21") if kind == "trading" and _num((t or {}).get("rs21"))
                  else (f or {}).get("valRatio") if kind == "invest" and _num((f or {}).get("valRatio")) else math.inf),
    }


def _rank(entries, minimum):
    keep = [e for e in entries if e["ok"] >= minimum]
    keep.sort(key=lambda e: (-e["ok"], len(e["warnings"]), e["_sort"], e["ticker"]))
    for i, e in enumerate(keep, 1):
        e["rank"] = i
    for e in entries:
        e.setdefault("rank", None)        # not selected: kept for the diary (comparison with the rest of the universe)
        e.pop("_sort", None)
    return keep


def scan(universe, daily, bench, fund=None, patterns=None, failed=None, quotes=None, as_of=None, today=None, keep_all=False):
    """Both rankings.
    universe: [{"ticker", "name", "sector"}]; daily: {ticker: DataFrame of CLOSED sessions}; bench: DataFrame of QQQ;
    fund: {ticker: {"years", "epsRev90", "epsRev30", "up30", "down30", "rec", "valLabel", "valRatio", "valNotes",
    "earningsTs", "epsGrowth", "margin", "news": {"score", "reasons"} | None}};
    patterns: {ticker: [pattern keys of the last sessions]}; failed: {key: name} of the patterns that FAILED the test;
    quotes: {ticker: {"price", "time"}} (live, only shown); as_of: last day of prices that may be read.
    keep_all: also "all" in each block, every stock with its conditions and figures (for the diary, not for the page)."""
    fund, patterns, failed, quotes = fund or {}, patterns or {}, failed or {}, quotes or {}
    bc = cut(bench, as_of)
    bclose = bc["Close"].dropna() if bc is not None and "Close" in bc else None
    techs = {u["ticker"]: tech(cut(daily.get(u["ticker"]), as_of), bclose) for u in universe}
    days = sorted({t["date"] for t in techs.values() if t})
    last = days[-1] if days else None
    today = today or date.today()
    med = sector_medians(techs, universe)
    trading, invest, not_eval = [], [], []
    for u in universe:
        tk, t, f = u["ticker"], techs[u["ticker"]], fund.get(u["ticker"]) or {}
        if t is None:
            not_eval.append({"ticker": tk, "why": f"meno di {MIN_SESSIONS} sedute chiuse di prezzi"})
        elif t["date"] != last:
            t = None                      # a stock whose prices stop before the others: old data, not comparable
            not_eval.append({"ticker": tk, "why": "prezzi fermi a una seduta precedente alle altre"})
        trading.append(_entry(u, trading_conditions(t), trading_warnings(t, f, patterns.get(tk), failed, today),
                              trading_values(t), t, f, "trading", quotes.get(tk)))
        invest.append(_entry(u, invest_conditions(t, f), invest_warnings(t, f, today),
                             invest_values(t, f, u.get("sector"), med), t, f, "invest", quotes.get(tk)))
    tr, iv = _rank(trading, TRADING_MIN), _rank(invest, INVEST_MIN)

    def block(kind, cat, entries, rk, minimum, horizon):
        cov = coverage(entries, cat)
        low = [c for c in cov if c["total"] and c["available"] < COVERAGE_MIN * c["total"]]
        b = {"horizon": horizon, "conditions": [{"id": i, "name": n, "rule": r} for i, n, r in cat], "min": minimum,
             "order": ORDER[kind], "qualified": len(rk), "items": rk[:TOP], "coverage": cov,
             "complete": bool(entries) and not low,
             "coverageNote": ("Classifica incompleta: " + "; ".join(f"{c['id']} {c['name']} valutabile solo per {c['available']} titoli su {c['total']}"
                                                                    for c in low)
                              + f" (serve almeno il {it(COVERAGE_MIN * 100, 0)}%). I titoli senza il dato non possono soddisfare la condizione: "
                                "la classifica non confronta tutti i titoli alla pari.") if low else None}
        if keep_all:
            b["all"] = entries
        return b
    return finite({
        "asOf": last, "universe": len(universe), "evaluated": len(universe) - len(not_eval), "notEvaluable": not_eval,
        "model": {"version": MODEL_VERSION, "params": PARAMS},
        "market": market_context(bclose, {k: v for k, v in techs.items() if v and v["date"] == last}),
        "trading": block("trading", TRADING, trading, tr, TRADING_MIN, "3–30 sedute"),
        "invest": block("invest", INVEST, invest, iv, INVEST_MIN, "3–24 mesi"),
    })


def finite(x):
    """The same structure with NaN and infinities turned into None (valid JSON, and "missing" never looks like a number)."""
    if isinstance(x, dict):
        return {k: finite(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [finite(v) for v in x]
    if isinstance(x, float) and not math.isfinite(x):
        return None
    return x
