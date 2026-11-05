"""Daily closes of the catalog's ETFs (phase 6B, part I) kept in cache/etf_prices.pkl.

Downloaded only in the background (server loop, once after each close of Borsa Italiana) or with the manual command
`.venv/bin/python etf_prices.py aggiorna`; the page and the scanner only READ the cache, so opening the dashboard never
waits for Yahoo.

Rules (written down because the stock studies of phases 3-4 taught them):
- one series per share class (ISIN): the listing of Borsa Italiana (ETFP) when Yahoo has it, else Xetra. The same fund
  is never counted twice because it trades on two exchanges;
- closes adjusted by Yahoo for dividends and splits (auto_adjust): for a distributing class the series is a total
  return only if Yahoo recorded its dividends, so the number of recorded dividends is kept and checked;
- every series in EUR: a listing traded in another currency is converted with the exchange rate of the same day;
- nothing before the launch date of the class (from the catalog), nothing invented to fill holes;
- these are prices of the real funds, never index proxies: the US ETFs used by the phase-24 tab are not used here.
"""
from __future__ import annotations

import logging
import os
import pickle
import sys
import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(ROOT, "cache", "etf_prices.pkl")
PERIOD = "3y"
ROME = ZoneInfo("Europe/Rome")
CLOSE_ROME = (18, 0)            # Borsa Italiana closes at 17:30: after 18:00 the day's closes are final
RETRY_S = 1800                  # after a failed download, wait 30 minutes
FX = {"USD": "EURUSD=X", "GBP": "EURGBP=X", "CHF": "EURCHF=X", "JPY": "EURJPY=X"}
SOURCE = ("Yahoo Finance, chiusure giornaliere rettificate per dividendi e frazionamenti (auto_adjust), "
          "quotazione di Borsa Italiana o, se assente, di Xetra; valori in euro")
log = logging.getLogger("etf_prices")
_lock = threading.Lock()
_state = {"running": False, "failedAt": 0.0, "error": None}
_mem = {"mtime": None, "data": None}


MIN_MAIN = 504                  # Borsa Italiana is used when it has at least 2 years of closes, else the longer listing

# Phase 6C: each listing with its exchange, calendar, time zone and closing time. A daily bar of a day is final only
# after the close of ITS exchange + FINAL_MARGIN_MIN: "after 18:00 in Rome" is right for Milan and Xetra (17:30 CET),
# not for an exchange that closes later (a US listing closes at 22:00 Rome time).
FINAL_MARGIN_MIN = 30
VENUES = {".MI": ("ETFP", "Borsa Italiana (ETFplus)", "Europe/Rome", (17, 30)),
          ".DE": ("XETR", "Xetra (Francoforte)", "Europe/Berlin", (17, 30)),
          ".F": ("XFRA", "Borsa di Francoforte", "Europe/Berlin", (20, 0)),
          ".L": ("XLON", "London Stock Exchange", "Europe/London", (16, 30)),
          ".AS": ("XAMS", "Euronext Amsterdam", "Europe/Amsterdam", (17, 30)),
          ".PA": ("XPAR", "Euronext Parigi", "Europe/Paris", (17, 30)),
          ".SW": ("XSWX", "SIX Swiss Exchange", "Europe/Zurich", (17, 30)),
          "": ("XNYS/XNAS", "borsa americana", "America/New_York", (16, 0))}
DELAY = ("chiusure giornaliere di Yahoo Finance: il prezzo di un giorno è definitivo solo dopo la chiusura della sua borsa; "
         "i prezzi durante la seduta sono ritardati di circa 15 minuti")


def venue_info(symbol):
    """(mic, exchange, time zone, (hour, minute) of the close) from the Yahoo suffix of the listing."""
    suf = "." + symbol.rsplit(".", 1)[1] if symbol and "." in symbol else ""
    return VENUES.get(suf, VENUES[""] if not suf else (None, f"borsa sconosciuta ({suf})", None, None))


def final_at(symbol, day):
    """The moment (aware) after which the daily bar of `day` on the exchange of `symbol` is final, or None."""
    mic, _, tz, close = venue_info(symbol)
    if not tz or not close:
        return None
    d = pd.Timestamp(day).date()
    return datetime(d.year, d.month, d.day, close[0], close[1], tzinfo=ZoneInfo(tz)) + timedelta(minutes=FINAL_MARGIN_MIN)


def candidates(listings):
    """[(yahoo symbol, trading currency, venue)] of the listings with a Yahoo quote: ETFP first, then Xetra."""
    ok = [l for l in listings or [] if l.get("quoteAvailable") and l.get("yahoo")]
    order = {"ETFP": 0, "XETR": 1}
    ok.sort(key=lambda l: order.get(l.get("mic"), 9))
    return [(l["yahoo"], (l.get("currency") or {}).get("v") or "EUR", l.get("venue")) for l in ok]


def pick_listing(listings):
    """The first candidate (kept for callers that need one symbol without downloading)."""
    c = candidates(listings)
    return c[0] if c else (None, None, None)


def plan(catalog):
    """{isin: {symbol, currency, venue, launch}} for every ETF of the catalog (excluded products left out)."""
    out = {}
    for isin, e in (catalog.get("items") or {}).items():
        if e.get("exclusion"):
            continue
        cands = candidates(e.get("listings"))
        sym, ccy, venue = cands[0] if cands else (None, None, None)
        out[isin] = {"symbol": sym, "currency": ccy, "venue": venue, "candidates": cands,
                     "launch": ((e.get("fund") or {}).get("launch") or {}).get("v"),
                     "distribution": ((e.get("fund") or {}).get("distribution") or {}).get("v")}
    return out


def _naive(s):
    s = s.dropna()
    s.index = pd.to_datetime(s.index).tz_localize(None).normalize() if getattr(s.index, "tz", None) else pd.to_datetime(s.index).normalize()
    return s[~s.index.duplicated(keep="last")].sort_index()


def to_eur(s, ccy, fx):
    """A series in EUR. EUR stays as it is; other currencies use the EUR/xxx rate of the same day (last known rate
    for a missing day). None when the rate is not available (never a guess)."""
    if ccy in (None, "EUR"):
        return s
    pair = fx.get(FX.get(ccy, ""))
    if pair is None or not len(pair):
        return None
    rate = pair.reindex(s.index, method="ffill")
    return (s / rate).dropna()


def assemble(frames, p, now):
    """Pure: from the downloaded frames ({symbol: DataFrame with Close and maybe Dividends}) to the cache content."""
    now = now if now.tzinfo else now.replace(tzinfo=ROME)
    fx = {sym: _naive(frames[sym]["Close"]) for sym in FX.values() if sym in frames and "Close" in frames[sym]}
    closes, meta = {}, {}
    for isin, x in p.items():
        cands = x.get("candidates") or ([(x["symbol"], x["currency"], x["venue"])] if x.get("symbol") else [])
        got = [(c, frames[c[0]]) for c in cands if c[0] in frames and "Close" in frames[c[0]] and len(frames[c[0]]["Close"].dropna())]
        chosen = None
        if got:
            first = got[0]
            longest = max(got, key=lambda g: len(g[1]["Close"].dropna()))
            chosen = first if len(first[1]["Close"].dropna()) >= MIN_MAIN else longest
        sym, ccy, venue = chosen[0] if chosen else (x.get("symbol"), x.get("currency"), x.get("venue"))
        df = chosen[1] if chosen else None
        x = dict(x, symbol=sym, currency=ccy, venue=venue)
        info = {"symbol": sym, "currency": ccy, "venue": venue, "launch": x["launch"], "series": None, "mic": venue_info(sym)[0] if sym else None,
                "choice": None if not chosen or chosen is got[0] else f"{got[0][0][0]} ha meno di {MIN_MAIN} sedute: uso {sym}, più lunga"}
        if df is None:
            info["missing"] = "nessuna quotazione Yahoo" if sym else "nessuna quotazione disponibile nel catalogo"
            meta[isin] = info
            continue
        s = _naive(df["Close"].astype(float))
        if x["launch"]:
            s = s[s.index >= pd.Timestamp(x["launch"])]
        mic, exch, tz, close = venue_info(sym)
        dropped = None
        fin = final_at(sym, s.index[-1]) if len(s) else None
        if fin is not None and now < fin:              # the last bar is of a session still open (or just closed): not final
            dropped = str(s.index[-1].date())
            s = s.iloc[:-1]
        eur = to_eur(s, x["currency"], fx)
        if eur is None or not len(eur):
            info["missing"] = f"cambio EUR/{x['currency']} non disponibile: serie non convertita"
            meta[isin] = info
            continue
        divs = 0
        if "Dividends" in df:
            d = _naive(df["Dividends"].fillna(0))
            divs = int((d > 0).sum())
        info.update(series="ok", first=str(eur.index[0].date()), last=str(eur.index[-1].date()), n=int(len(eur)),
                    converted=x["currency"] not in (None, "EUR"), dividends=divs,
                    totalReturn=(x["distribution"] != "distribuzione") or divs > 0,
                    mic=mic, exchange=exch, tz=tz, closeLocal=f"{close[0]:02d}:{close[1]:02d}" if close else None,
                    finalAfter=final_at(sym, eur.index[-1]).isoformat(timespec="minutes") if final_at(sym, eur.index[-1]) else None,
                    fetched=now.isoformat(timespec="seconds"), delay=DELAY, droppedPartial=dropped,
                    fxNote=("cambio EUR/" + x["currency"] + " dell'ultimo giorno letto al momento del download: il cambio non ha "
                            "una chiusura alle 17:30, quindi l'ultimo valore in euro è provvisorio") if x["currency"] not in (None, "EUR") else None)
        closes[isin] = eur
        meta[isin] = info
    return {"fetched": now.isoformat(timespec="seconds"), "source": SOURCE, "period": PERIOD, "closes": closes, "meta": meta}


def close_mark(now):
    """The most recent moment when a Borsa Italiana session became final (weekday at 18:00 Rome) not after `now`."""
    t = now.astimezone(ROME)
    d = t.replace(hour=CLOSE_ROME[0], minute=CLOSE_ROME[1], second=0, microsecond=0)
    if t < d:
        d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def due(data, now):
    """True when the cache does not yet contain the last final session."""
    if not data or not data.get("fetched"):
        return True
    try:
        fetched = datetime.fromisoformat(data["fetched"])
    except ValueError:
        return True
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=ROME)
    return fetched < close_mark(now)


def load(path=None):
    """The cache (kept in memory until the file changes), or None."""
    path = path or CACHE
    try:
        mt = os.path.getmtime(path)
    except OSError:
        return None
    if _mem["mtime"] == (path, mt):
        return _mem["data"]
    try:
        with open(path, "rb") as f:
            data = pickle.load(f)
    except Exception:
        log.exception("ETF price cache unreadable")
        return None
    _mem.update(mtime=(path, mt), data=data)
    return data


def save(data, path=None):
    path = path or CACHE
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        pickle.dump(data, f)
    os.replace(tmp, path)


def build(download, catalog, now=None):
    """Downloads (one request for all symbols) and assembles; raises when Yahoo gives nothing."""
    now = now or datetime.now(ROME)
    p = plan(catalog)
    syms = sorted({c[0] for x in p.values() for c in x["candidates"]} | set(FX.values()))
    frames = download(syms, period=PERIOD, interval="1d", actions=True)
    if not frames:
        raise RuntimeError("Yahoo non ha dato prezzi")
    return assemble(frames, p, now)


def refresh_async(download, catalog_loader, now=None):
    """Starts the download in a thread when the cache is due (and no recent failure): never blocks the caller."""
    now = now or datetime.now(ROME)
    with _lock:
        if _state["running"] or (_state["failedAt"] and time.time() - _state["failedAt"] < RETRY_S):
            return False
        if not due(load(), now):
            return False
        _state["running"] = True

    def job():
        try:
            data = build(download, catalog_loader())
            save(data)
            with _lock:
                _state.update(error=None, failedAt=0.0)
            log.info("ETF prices: %d series", len(data["closes"]))
        except Exception as e:
            log.exception("ETF prices failed")
            with _lock:
                _state.update(error=str(e), failedAt=time.time())
        finally:
            with _lock:
                _state["running"] = False
    threading.Thread(target=job, daemon=True).start()
    return True


def status():
    d = load()
    with _lock:
        return {"fetched": (d or {}).get("fetched"), "series": len((d or {}).get("closes") or {}), "running": _state["running"],
                "error": _state["error"]}


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    cmd = argv[0] if argv else "stato"
    if cmd == "aggiorna":
        import etf_catalog
        from server import download
        data = build(download, etf_catalog.load())
        save(data)
        miss = {i: m.get("missing") for i, m in data["meta"].items() if m.get("missing")}
        print(f"{len(data['closes'])} serie salvate in {CACHE}; mancanti: {len(miss)}")
        for i, why in miss.items():
            print(f"  {i}: {why}")
    else:
        d = load()
        if not d:
            print("cache dei prezzi ETF assente: `.venv/bin/python etf_prices.py aggiorna`")
            return
        print(f"aggiornata {d['fetched']}: {len(d['closes'])} serie")
        for i, m in d["meta"].items():
            print(f"  {i} {m.get('symbol')}: {m.get('first')} → {m.get('last')} ({m.get('n')} sedute)"
                  f"{' convertita in EUR' if m.get('converted') else ''}{'' if m.get('totalReturn', True) else ' SOLO PREZZO'}"
                  f"{' — ' + m['missing'] if m.get('missing') else ''}")


if __name__ == "__main__":
    main()
