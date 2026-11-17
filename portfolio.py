"""Portfolio from the broker export in portafoglio/ (Fineco "Portafoglio sintesi" .xls): positions, Yahoo tickers,
live prices and values in EUR.

Personal data: the export and everything derived from it stay in memory (and in portafoglio/, which Git ignores);
nothing is written to cache/ or to the reports. Only ticker symbols are sent to Yahoo, to get prices; an ISIN is sent
only as a last resort when no ticker rule works.

Values follow Fineco's own formulas (checked on the export): value in EUR = quantity × price ÷ EUR/USD rate
(rate 1 for EUR), cost = "Valore di carico" (quantity × average cost ÷ rate on the purchase days).
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

import yfinance as yf

log = logging.getLogger("ndx")
ROOT = os.path.dirname(os.path.abspath(__file__))
PORTFOLIO_DIR = os.path.join(ROOT, "portafoglio")
OVERRIDES = os.path.join(PORTFOLIO_DIR, "ticker.json")      # optional {ISIN: Yahoo ticker}, written by the user
FX = "EURUSD=X"                                             # USD per 1 EUR, same convention as Fineco's "cambio"
CLASS_FILE = os.path.join(PORTFOLIO_DIR, "classificazione.json")   # ETF/ETC and extra stock themes, edited by the user
THEMES_FILE = os.path.join(ROOT, "themes.json")
PRICE_TOL = 0.25            # Yahoo price vs the export's price: a larger gap means a wrong listing (the file may be days old)

# Fineco symbol suffix (Reuters style) -> Yahoo suffix; ".FRA" depends on the market column (Xetra or Frankfurt floor)
SUFFIX = {"O": "", "OQ": "", "N": "", "A": "", "MI": ".MI", "PAR": ".PA", "AMS": ".AS", "MAD": ".MC", "LON": ".L",
          "SWX": ".SW", "BRU": ".BR", "VIE": ".VI", "LIS": ".LS", "HEL": ".HE", "STO": ".ST", "CPH": ".CO", "OSL": ".OL"}
COLUMNS = {"name": "Titolo", "isin": "ISIN", "symbol": "Simbolo", "market": "Mercato", "kind": "Strumento",
           "currency": "Valuta", "qty": "Quantità", "costPrice": "P.zo medio di carico", "costFx": "Cambio di carico",
           "costValue": "Valore di carico", "filePrice": "P.zo di mercato", "fileFx": "Cambio di mercato",
           "fileValue": "Valore di mercato €"}

# Yahoo sectors (GICS-like) -> the dashboard's Italian sector names; Yahoo countries -> Italian
YAHOO_SECTOR_IT = {"Technology": "Tecnologia", "Communication Services": "Telecomunicazioni", "Consumer Cyclical": "Consumi discrezionali",
                   "Consumer Defensive": "Beni di prima necessità", "Healthcare": "Sanità", "Industrials": "Industria",
                   "Utilities": "Utility", "Financial Services": "Finanza", "Basic Materials": "Materiali di base",
                   "Energy": "Energia", "Real Estate": "Immobiliare"}
COUNTRY_IT = {"United States": "USA", "Israel": "Israele", "Italy": "Italia", "Netherlands": "Paesi Bassi",
              "Cayman Islands": "Isole Cayman", "Canada": "Canada", "United Kingdom": "Regno Unito", "Germany": "Germania",
              "France": "Francia", "Switzerland": "Svizzera", "Ireland": "Irlanda", "Taiwan": "Taiwan", "China": "Cina",
              "Japan": "Giappone", "South Korea": "Corea del Sud", "Luxembourg": "Lussemburgo", "Denmark": "Danimarca",
              "Sweden": "Svezia", "Spain": "Spagna", "Belgium": "Belgio", "Australia": "Australia", "Bermuda": "Bermuda"}
LOOK_THROUGH_NDX = "come il Nasdaq-100"     # ETF sector split like the index (sector weights from the dashboard)

on_quotes = None            # set by the server: called after every price refresh (saves the day's picture, history.py)
_lock = threading.Lock()
_meta = {}      # Yahoo ticker -> {"sector", "country"} of stocks outside the Nasdaq-100 (memory only)
_state = {"path": None, "mtime": None, "positions": [], "error": None, "resolving": False,
          "quotes": {}, "fx": None, "quotesAt": None}


# ---------------------------------------------------------------- reading the export

def _in_folder(path):
    """True when `path` is a file of the current portfolio folder: memory read from another folder (a test that changed
    folder in the same process) is never shown. In a running dashboard the folder never changes: always True."""
    norm = lambda p: os.path.normcase(os.path.abspath(p))
    return norm(os.path.dirname(path)) == norm(PORTFOLIO_DIR)


def latest_file():
    """Newest .xls / .xlsx in portafoglio/ (the one exported last), or None."""
    if not os.path.isdir(PORTFOLIO_DIR):
        return None
    files = [os.path.join(PORTFOLIO_DIR, f) for f in os.listdir(PORTFOLIO_DIR)
             if f.lower().endswith((".xls", ".xlsx")) and not f.startswith(("~$", "."))]
    return max(files, key=os.path.getmtime) if files else None


def _rows(path):
    if path.lower().endswith(".xls"):
        import xlrd
        sh = xlrd.open_workbook(path).sheet_by_index(0)
        return [[sh.cell_value(r, c) for c in range(sh.ncols)] for r in range(sh.nrows)]
    try:
        import openpyxl
    except ImportError:
        raise ValueError("il file è .xlsx: per leggerlo serve la libreria openpyxl (aggiungila a requirements.txt)")
    ws = openpyxl.load_workbook(path, read_only=True, data_only=True).worksheets[0]
    return [["" if v is None else v for v in row] for row in ws.iter_rows(values_only=True)]


def read_export(path):
    """Positions of a Fineco export: the header row is the one containing "ISIN"; positions end at the first row
    without an ISIN (the "Totale" line)."""
    rows = _rows(path)
    head = next((i for i, r in enumerate(rows) if any(str(v).strip() == "ISIN" for v in r)), None)
    if head is None:
        raise ValueError("non trovo la riga con le intestazioni (colonna ISIN)")
    idx = {str(v).strip(): i for i, v in enumerate(rows[head])}
    missing = [h for h in COLUMNS.values() if h not in idx]
    if missing:
        raise ValueError("mancano le colonne: " + ", ".join(missing))
    out = []
    for r in rows[head + 1:]:
        if not str(r[idx["ISIN"]]).strip():
            break
        p = {k: r[idx[h]] for k, h in COLUMNS.items()}
        for k in ("name", "isin", "symbol", "market", "kind", "currency"):
            p[k] = str(p[k]).strip()
        for k in ("qty", "costPrice", "costFx", "costValue", "filePrice", "fileFx", "fileValue"):
            p[k] = float(p[k] or 0)
        out.append(p)
    return out


# ---------------------------------------------------------------- upload from the dashboard (preview, then confirm)
# The uploaded file waits in a hidden temporary file inside portafoglio/ (latest_file() skips it) until the user
# confirms. Older exports are never deleted: each confirmed file gets its date in the name, so they can later be
# read as the history of the portfolio.

UPLOAD_TMP = os.path.join(PORTFOLIO_DIR, ".caricamento.xls")
MAX_UPLOAD = 5 * 1024 * 1024
_upload = {"token": None}

# Phase 9A: stricter checks of an uploaded file, turned on only by instance.py (the dashboard of another user). The
# personal dashboard keeps the checks it always had.
STRICT_UPLOAD = False
MAX_POSITIONS = 500
ISIN_RX = re.compile(r"[A-Z]{2}[A-Z0-9]{9}[0-9]")
CURRENCY_RX = re.compile(r"[A-Z]{3}")
XLS_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"            # an Excel 97-2003 (.xls) file starts with these 8 bytes


def validate_positions(positions):
    """Strict check of the positions read from an uploaded file (phase 9A). Raises ValueError with a message that names
    only the row and the field, never their content (it could be personal data)."""
    import math
    if len(positions) > MAX_POSITIONS:
        raise ValueError(f"il file ha più di {MAX_POSITIONS} posizioni")
    for n, p in enumerate(positions, 1):
        if not ISIN_RX.fullmatch(p["isin"]):
            raise ValueError(f"riga {n}: codice ISIN non valido")
        if not CURRENCY_RX.fullmatch(p["currency"]):
            raise ValueError(f"riga {n}: valuta non valida (servono 3 lettere, per esempio EUR)")
        if not p["name"] or len(p["name"]) > 200 or len(p["symbol"]) > 40 or len(p["market"]) > 40 or len(p["kind"]) > 60:
            raise ValueError(f"riga {n}: nome, simbolo, mercato o strumento mancante o troppo lungo")
        if any(ord(c) < 32 for k in ("name", "symbol", "market", "kind") for c in p[k]):
            raise ValueError(f"riga {n}: caratteri non ammessi")
        for k in ("qty", "costPrice", "costFx", "costValue", "filePrice", "fileFx", "fileValue"):
            if not math.isfinite(p[k]):
                raise ValueError(f"riga {n}: valore numerico non valido")
        if p["qty"] < 0:
            raise ValueError(f"riga {n}: quantità negativa")


def cancel_upload():
    _upload["token"] = None
    if os.path.exists(UPLOAD_TMP):
        os.remove(UPLOAD_TMP)


def preview_upload(data, filename):
    """Check that the file is a Fineco export and compare it with the positions in use (by ISIN). Nothing is replaced yet.
    Raises ValueError with an Italian message when the file is not acceptable."""
    cancel_upload()
    if not filename.lower().endswith(".xls"):
        raise ValueError("Il file deve essere l'export di Fineco in formato Excel .xls (Portafoglio → Sintesi → esporta).")
    if not data or len(data) > MAX_UPLOAD:
        raise ValueError("Il file è vuoto oppure troppo grande (massimo 5 MB).")
    if STRICT_UPLOAD and not data.startswith(XLS_MAGIC):
        raise ValueError("Il file non è un file Excel .xls: usa l'export di Fineco (Portafoglio → Sintesi → esporta).")
    os.makedirs(PORTFOLIO_DIR, exist_ok=True)
    if STRICT_UPLOAD:                     # phase 9A: a new file of the owner only, never through an existing link
        fd = os.open(UPLOAD_TMP, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0), 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
    else:
        with open(UPLOAD_TMP, "wb") as f:
            f.write(data)
    try:
        new = read_export(UPLOAD_TMP)
        if STRICT_UPLOAD:
            validate_positions(new)
    except Exception as e:
        cancel_upload()
        if STRICT_UPLOAD:                 # never echo the content of the file (Python's messages may quote a cell)
            why = str(e) if isinstance(e, ValueError) and str(e).startswith(("riga ", "il file ", "mancano le colonne",
                                                                                 "non trovo la riga")) else "contenuto non leggibile"
        else:
            why = str(e) if isinstance(e, ValueError) else "non è un file Excel leggibile"
        raise ValueError(f"Non sembra un export Fineco «Portafoglio sintesi»: {why}.")
    if not new:
        cancel_upload()
        raise ValueError("Non sembra un export Fineco «Portafoglio sintesi»: non contiene posizioni.")
    with _lock:
        old, current = list(_state["positions"]), _state["path"]

    def by_isin(positions):
        out = {}
        for p in positions:
            x = out.setdefault(p["isin"], {"name": p["name"], "isin": p["isin"], "qty": 0.0})
            x["qty"] += p["qty"]
        return out
    a, b = by_isin(old), by_isin(new)
    _upload["token"] = os.urandom(8).hex()
    return {
        "token": _upload["token"], "file": os.path.basename(filename), "count": len(new),
        "current": os.path.basename(current) if current else None,
        "new": [b[k] for k in b if k not in a],
        "sold": [a[k] for k in a if k not in b],
        "changed": [{**b[k], "from": a[k]["qty"]} for k in b if k in a and abs(a[k]["qty"] - b[k]["qty"]) > 1e-9],
        "same": sum(1 for k in b if k in a and abs(a[k]["qty"] - b[k]["qty"]) <= 1e-9),
    }


def confirm_upload(token):
    """Move the previewed file into portafoglio/ under a dated name (it becomes the newest one) and read it."""
    if not token or token != _upload["token"] or not os.path.exists(UPLOAD_TMP):
        raise ValueError("Anteprima scaduta: carica di nuovo il file.")
    dest = os.path.join(PORTFOLIO_DIR, f"portafoglio-{datetime.now():%Y-%m-%d_%H%M%S}.xls")
    os.replace(UPLOAD_TMP, dest)
    os.utime(dest, None)
    _upload["token"] = None
    refresh()
    return os.path.basename(dest)


# ---------------------------------------------------------------- Fineco symbol -> Yahoo ticker

def candidates(symbol, market):
    """Yahoo tickers to try, most likely first: META.O -> META, QQQ3.MI -> QQQ3.MI, 3SEM.FRA (XETRA) -> 3SEM.DE."""
    base, _, suf = symbol.rpartition(".")
    if not base:
        return [symbol]
    suf = suf.upper()
    if suf in ("FRA", "DE", "F", "ETR"):
        first, second = (".DE", ".F") if market.upper() == "XETRA" or suf in ("DE", "ETR") else (".F", ".DE")
        return [base + first, base + second]
    if suf in SUFFIX:
        return [base + SUFFIX[suf]]
    return [symbol]


def _probe(ticker, pos):
    """Does this Yahoo ticker look like the position? (data, same currency, price near the export's)."""
    try:
        t = yf.Ticker(ticker)
        h = t.history(period="5d")
        if h.empty:
            return None
        cur = (t.fast_info.get("currency") or "").upper()
        last = float(h["Close"].dropna().iloc[-1])
    except Exception:
        return None
    if cur and cur != pos["currency"].upper():
        return None
    if pos["filePrice"] and abs(last / pos["filePrice"] - 1) > PRICE_TOL:
        return None
    return ticker


def _isin_ticker(isin):
    try:
        t = yf.Ticker(isin).ticker
        return t if t and t != isin else None
    except Exception:
        return None


def resolve(pos, overrides):
    """(Yahoo ticker or None, how): manual override, then the suffix rule (and its alternative), then ISIN search."""
    if pos["isin"] in overrides:
        return overrides[pos["isin"]], "manuale (portafoglio/ticker.json)"
    for c in candidates(pos["symbol"], pos["market"]):
        if _probe(c, pos):
            return c, "regola"
    t = _isin_ticker(pos["isin"])
    if t and _probe(t, pos):
        return t, "ricerca per ISIN"
    return None, "non trovato"


def _load_overrides():
    try:
        with open(OVERRIDES) as f:
            return {str(k).strip(): str(v).strip() for k, v in json.load(f).items()}
    except FileNotFoundError:
        return {}
    except Exception as e:
        log.warning("portafoglio/ticker.json unreadable (%s)", e)
        return {}


def _resolve_all(positions):
    overrides = _load_overrides()
    t0 = time.time()
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(lambda p: resolve(p, overrides), positions))
    for p, (t, how) in zip(positions, res):
        p["ticker"], p["tickerHow"] = t, how
    _fetch_meta([p["ticker"] for p in positions if p["ticker"] and p["kind"].lower().startswith("azion")])
    log.info("portfolio: %d positions, %d tickers found in %.1fs",
             len(positions), sum(1 for p in positions if p["ticker"]), time.time() - t0)


def _fetch_meta(tickers):
    """Sector and country from Yahoo for stocks (once per ticker, kept in memory)."""
    todo = [t for t in tickers if t not in _meta]

    def one(t):
        try:
            i = yf.Ticker(t).info or {}
            return t, {"sector": i.get("sector"), "country": i.get("country")}
        except Exception:
            return t, {}
    with ThreadPoolExecutor(8) as ex:
        for t, m in ex.map(one, todo):
            _meta[t] = m


def _load_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as e:
        log.warning("%s unreadable (%s)", os.path.basename(path), e)
        return {}


def _themes_by_ticker():
    out = {}
    for name, tickers in _load_json(THEMES_FILE).items():
        for t in tickers:
            out.setdefault(t, []).append(name)
    return out


def is_fund(kind):
    """ETF, ETC, ETN and anything Fineco does not call a share ("Azione")."""
    return kind.upper() in ("ETF", "ETC", "ETN") or not kind.lower().startswith("azion")


def classify(p, cls, themes, ndx_rows, ndx_sectors, infos):
    """leverage + {sector|theme|country: {label: share}} for one position (shares add up to 1)."""
    if is_fund(p["kind"]):
        c = cls.get(p["isin"])
        if not c:
            m = re.search(r"\b(\d+)x\b", p["name"], re.I)
            lev = int(m.group(1)) if m else 1
            return lev, {"sector": {"Non classificato": 1}, "theme": {"Non classificato": 1}, "country": {"Non classificato": 1}}, False
        sec = ndx_sectors if c.get("settore") == LOOK_THROUGH_NDX and ndx_sectors else {c.get("settore") or "Non classificato": 1}
        return (c.get("leva") or 1), {"sector": sec, "theme": {c.get("tema") or "Senza tema": 1},
                                      "country": {c.get("paese") or "Non classificato": 1}}, True
    t = p.get("ticker") or ""
    extra = (cls.get("_azioni") or {}).get(t, {})
    row, meta = ndx_rows.get(t), _meta.get(t, {})
    sector = row["sector"] if row else YAHOO_SECTOR_IT.get(meta.get("sector"), meta.get("sector")) or "Non disponibile"
    tl = [extra["tema"]] if extra.get("tema") else themes.get(t) or ["Senza tema"]
    country = extra.get("paese") or COUNTRY_IT.get((infos.get(t) or {}).get("country") or meta.get("country"),
                                                     (infos.get(t) or {}).get("country") or meta.get("country")) or "Non disponibile"
    return 1, {"sector": {sector: 1}, "theme": {x: 1 / len(tl) for x in tl}, "country": {country: 1}}, True


def missing_fields(p, cls, dims, lev, known):
    """What is missing for one position's breakdown (phase 8B.1), in words for the page: [] when complete.
    Funds: the dashboard has no reliable source of their sector / theme / country / leverage, so they come only from
    portafoglio/classificazione.json, written by the user. Stocks: sector and country come from Yahoo or the index."""
    out = []
    if is_fund(p["kind"]):
        if not known:
            return ["nessuna classificazione in portafoglio/classificazione.json (settore, tema, paese)"] + (
                [f"leva dedotta dal nome ({lev}x), non confermata"] if lev != 1 else [])
        c = cls.get(p["isin"]) or {}
        out += [f"{w} non indicato" for k, w in (("settore", "settore"), ("paese", "paese")) if not c.get(k)]
        return out
    if "Non disponibile" in dims["sector"]:
        out.append("settore non disponibile dalla fonte")
    if "Non disponibile" in dims["country"]:
        out.append("paese non disponibile dalla fonte")
    return out


# ---------------------------------------------------------------- classification and ticker written from the page (phase 9A)
# Before phase 9A these two files were edited only by hand on this Mac; a separate instance (another user, from his own
# PC) needs to write them from the page. The dashboard still invents nothing: it stores only what the user typed.

TICKER_RX = re.compile(r"[A-Za-z0-9][A-Za-z0-9.\-^=]{0,19}")
CLASS_FIELDS = ("settore", "tema", "paese")


def _clean_label(v, what):
    if v in (None, ""):
        return None
    if not isinstance(v, str) or len(v.strip()) > 40 or any(ord(c) < 32 or c in "<>{}" for c in v):
        raise ValueError(f"{what}: al massimo 40 caratteri, senza simboli speciali")
    return v.strip() or None


def _load_for_update(path):
    """The current content of a personal JSON file before changing it: {} if missing, ValueError if unreadable (never
    overwritten: the other entries would be lost)."""
    try:
        with open(path) as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        raise ValueError(f"il file {os.path.basename(path)} non è leggibile: non lo sovrascrivo")
    if not isinstance(data, dict):
        raise ValueError(f"il file {os.path.basename(path)} non ha il formato atteso: non lo sovrascrivo")
    return data


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(data, f, indent=1, ensure_ascii=False)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def save_classification(isin, fields, remove=False):
    """Writes (or removes) the classification of one ETF/ETC in classificazione.json: settore, tema, paese, leva.
    Raises ValueError with an Italian message. The other entries of the file are kept as they are."""
    if not isinstance(isin, str) or not ISIN_RX.fullmatch(isin):
        raise ValueError("codice ISIN non valido")
    cls = _load_for_update(CLASS_FILE)
    if remove:
        cls.pop(isin, None)
    else:
        entry = {k: _clean_label((fields or {}).get(k), k) for k in CLASS_FIELDS}
        lev = (fields or {}).get("leva")
        if lev not in (None, ""):
            try:
                lev = int(lev)
            except (TypeError, ValueError):
                raise ValueError("leva: un numero intero da 1 a 5")
            if not 1 <= lev <= 5:
                raise ValueError("leva: un numero intero da 1 a 5")
        entry["leva"] = lev or None
        entry = {k: v for k, v in entry.items() if v is not None}
        if not entry.get("settore"):
            raise ValueError("indica almeno il settore (per un ETF sull'indice scrivi «come il Nasdaq-100»)")
        cls[isin] = entry
    _write_json(CLASS_FILE, cls)
    return cls.get(isin)


def save_ticker(isin, ticker):
    """Writes (or removes, with ticker None) the Yahoo ticker of one position in ticker.json; the export is read again so
    that the new ticker is used at once."""
    if not isinstance(isin, str) or not ISIN_RX.fullmatch(isin):
        raise ValueError("codice ISIN non valido")
    if ticker not in (None, "") and (not isinstance(ticker, str) or not TICKER_RX.fullmatch(ticker.strip())):
        raise ValueError("ticker non valido (lettere, numeri, punto e trattino; per esempio VWCE.DE)")
    data = _load_for_update(OVERRIDES)
    if ticker in (None, ""):
        data.pop(isin, None)
    else:
        data[isin] = ticker.strip().upper()
    _write_json(OVERRIDES, data)
    with _lock:
        _state["mtime"] = None                    # next refresh() reads the export again and resolves the tickers
    return data.get(isin)


def _catalog_index(isin):
    """Index name the public ETF catalogue knows for this ISIN (a hint for the user, never applied automatically)."""
    try:
        import etf_catalog
        e = ((etf_catalog.load() or {}).get("items") or {}).get(isin) or {}
        v = ((e.get("identity") or {}).get("index") or {})
        return v.get("v") if isinstance(v, dict) else None
    except Exception:
        return None


# ---------------------------------------------------------------- refresh (called by the server's worker)

def refresh():
    """Read a new or changed export (tickers resolved in the background), then refresh the prices."""
    path = latest_file()
    if not path:
        with _lock:
            _state.update(path=None, mtime=None, positions=[], error=None)
        return
    mtime = os.path.getmtime(path)
    if (path, mtime) != (_state["path"], _state["mtime"]):
        try:
            positions = read_export(path)
            err = None
        except Exception as e:
            positions, err = [], f"Non riesco a leggere {os.path.basename(path)}: {e}"
            if STRICT_UPLOAD:                     # phase 9A: the message may quote a cell; the log gets only its kind
                log.warning("portfolio: export not readable (%s)", type(e).__name__)
            else:
                log.warning("portfolio: %s", err)
        with _lock:
            _state.update(path=path, mtime=mtime, positions=positions, error=err, resolving=bool(positions),
                          quotes={}, quotesAt=None)
        if positions:
            def job():
                _resolve_all(positions)
                with _lock:
                    _state["resolving"] = False
                refresh_quotes()
            threading.Thread(target=job, daemon=True).start()
        return
    if not _state["resolving"]:
        refresh_quotes()


def _session_quote(daily, intra):
    """Last price and the close of the previous session (for today's change), from 5 days of daily and 5-minute bars."""
    dc = daily["Close"].dropna() if daily is not None and "Close" in daily else None
    ic = intra["Close"].dropna() if intra is not None and "Close" in intra else None
    if dc is None or dc.empty:
        return None
    if ic is not None and not ic.empty:
        price, session = float(ic.iloc[-1]), ic.index[-1].date()
    else:
        price, session = float(dc.iloc[-1]), dc.index[-1].date()
    before = dc[[d.date() < session for d in dc.index]]
    return {"price": price, "prevClose": float(before.iloc[-1]) if len(before) else None}


def refresh_quotes():
    from server import download   # local import: server imports this module
    with _lock:
        tickers = sorted({p["ticker"] for p in _state["positions"] if p.get("ticker")})
    if not tickers:
        return
    daily = download(tickers + [FX], period="5d", interval="1d")
    intra = download(tickers + [FX], period="1d", interval="5m", prepost=False)
    quotes = {t: q for t in tickers + [FX] if (q := _session_quote(daily.get(t), intra.get(t)))}
    with _lock:
        _state["quotes"] = quotes
        _state["fx"] = quotes.get(FX, {}).get("price")
        _state["quotesAt"] = time.time()
    if on_quotes:
        on_quotes()


# ---------------------------------------------------------------- values for the page

def snapshot(ndx_snapshot=None, infos=None):
    """Positions with values in EUR, totals, concentration and warnings, for /api/portfolio.
    ndx_snapshot / infos come from the running server (its store), to reuse sectors and weights of the Nasdaq-100."""
    with _lock:
        st = {k: (list(v) if isinstance(v, list) else dict(v) if isinstance(v, dict) else v) for k, v in _state.items()}
    if not st["path"] or not _in_folder(st["path"]):
        return {"file": None}
    fx_now = st["fx"]
    out, warnings = [], []
    infos = infos or {}
    ndx_rows = {r["ticker"]: r for r in ndx_snapshot["stocks"]} if ndx_snapshot else {}
    ndx_sectors = {}
    for r in ndx_rows.values():
        ndx_sectors[r["sector"]] = ndx_sectors.get(r["sector"], 0) + (r.get("weight") or 0)
    tot_w = sum(ndx_sectors.values())
    ndx_sectors = {k: v / tot_w for k, v in ndx_sectors.items()} if tot_w else {}
    cls, themes = _load_json(CLASS_FILE), _themes_by_ticker()
    agg = {"sector": {}, "theme": {}, "country": {}}
    unclassified = []                       # phase 8B.1: which instruments are not fully classified, and what is missing
    for p in st["positions"]:
        q = st["quotes"].get(p.get("ticker")) if p.get("ticker") else None
        usd = p["currency"].upper() != "EUR"
        live = q is not None and (not usd or fx_now)
        price = q["price"] if live else p["filePrice"]
        fx = (fx_now if usd else 1.0) if live else (p["fileFx"] or 1.0)
        value = p["qty"] * price / fx
        pnl = value - p["costValue"]
        fx_effect = value - p["qty"] * price / p["costFx"] if usd and p["costFx"] else 0.0   # EUR/USD moves since purchase
        today = p["qty"] * (price - q["prevClose"]) / fx if live and q.get("prevClose") else None
        out.append({
            "name": p["name"], "isin": p["isin"], "symbol": p["symbol"], "market": p["market"], "kind": p["kind"],
            "currency": p["currency"], "ticker": p.get("ticker"), "tickerHow": p.get("tickerHow"),
            "qty": p["qty"], "costPrice": p["costPrice"], "costFx": p["costFx"], "cost": p["costValue"],
            "price": price, "prevClose": q.get("prevClose") if live else None, "live": bool(live),
            "value": value, "pnl": pnl, "pnlPct": pnl / p["costValue"] * 100 if p["costValue"] else None,
            "fxEffect": fx_effect, "priceEffect": pnl - fx_effect, "today": today,
            "leveraged": bool(re.search(r"\b\d+x\b|leverag|short|\bbear\b|\bbull\b|turbo", p["name"], re.I)),
        })
        lev, dims, known = classify(p, cls, themes, ndx_rows, ndx_sectors, infos)
        x = out[-1]
        x.update(leverage=lev, exposure=x["value"] * lev, inNdx=x["ticker"] in ndx_rows,
                 sector=next(iter(dims["sector"])) if len(dims["sector"]) == 1 else LOOK_THROUGH_NDX,
                 themes=list(dims["theme"]), country=next(iter(dims["country"])))
        for dim, parts in dims.items():
            for label, share in parts.items():
                a = agg[dim].setdefault(label, [0.0, 0.0])
                a[0] += x["value"] * share
                a[1] += x["exposure"] * share
        if not known:
            warnings.append(f"{p['name']}: non classificato (aggiungilo in portafoglio/classificazione.json con il suo ISIN {p['isin']})")
        miss = missing_fields(p, cls, dims, lev, known)
        if miss:
            unclassified.append({"name": p["name"], "isin": p["isin"], "kind": p["kind"], "missing": miss,
                                 "catalogIndex": _catalog_index(p["isin"]) if is_fund(p["kind"]) else None})
        if not p.get("ticker") and not st["resolving"]:
            warnings.append(f"{p['name']} ({p['symbol']}): ticker non trovato su Yahoo, uso il prezzo del file")
    total = sum(x["value"] for x in out)
    for x in out:
        x["weight"] = x["value"] / total * 100 if total else None
    cost = sum(x["cost"] for x in out)
    todays = [x["today"] for x in out if x["today"] is not None]
    exposure = sum(x["exposure"] for x in out)
    concentration = {dim: sorted(({"name": k, "value": v, "pct": v / total * 100 if total else None,
                                   "exposure": e, "expPct": e / exposure * 100 if exposure else None}
                                  for k, (v, e) in parts.items()), key=lambda r: -r["exposure"])
                     for dim, parts in agg.items()}
    return {
        "file": os.path.basename(st["path"]), "fileTime": st["mtime"], "error": st["error"],
        "resolving": st["resolving"], "quotesAt": st["quotesAt"], "fx": fx_now,
        "positions": out, "warnings": warnings, "concentration": concentration, "unclassified": unclassified,
        "totals": {"value": total, "cost": cost, "pnl": total - cost, "pnlPct": (total - cost) / cost * 100 if cost else None,
                   "fxEffect": sum(x["fxEffect"] for x in out), "today": sum(todays) if todays else None,
                   "exposure": exposure,
                   "stale": sum(1 for x in out if not x["live"])},
    }
