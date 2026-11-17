"""Phase 8B.1: readability, pop-ups, Mercato information, Preferiti, explanations.

Only SYNTHETIC data (made-up tickers AAA, BBB, made-up ETF ISINs XX…), temporary folders, no network: the RSS feed,
BLS values and earnings reports are built here. The financial engines are checked to be byte-identical to Git HEAD."""
import json
import os
import re
import subprocess
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

import app_env

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ET = ZoneInfo("America/New_York")


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


APP, HTML, CSS = read("static/app.js"), read("static/index.html"), read("static/styles.css")


# ------------------------------------------------------------------ 1-2. removed pop-ups and banners, navigation

def test_01_generic_banners_and_popups_are_gone():
    for text in ("<p class=\"warn-box\"><b>Screening esplorativo", "<p class=\"warn-box\"><b>Classifica preliminare",
                 "<p class=\"warn-box\"><b>I verdetti «Ha senso comprare?»", "<p class=\"warn-box\"><b>Catalogo informativo"):
        assert text not in APP, text
    assert "<dialog" not in HTML and "<dialog" not in APP and "showModal" not in APP
    assert "Screening operativo e non consulenza" not in APP + HTML
    # the limits are still written, discreetly, and "non consulenza" is kept
    assert APP.count("scopeNote(") >= 5 and "non è una consulenza finanziaria" in APP
    assert "Non è una consulenza finanziaria" in HTML                     # footer


def test_02_leverage_and_tax_boxes_removed_but_logic_kept():
    assert 'id="pfLev"' not in HTML and 'id="pfTax"' not in HTML
    assert '$("#pfLev")' not in APP
    assert "function renderTaxBox()" in APP and "/api/fiscal" in APP         # code and API kept, only hidden
    assert "LEV_INFO(x.leverage) + levShare(x)" in APP                       # contextual ⓘ on the instrument
    import actions
    assert callable(actions.load_fiscal)


def test_03_navigation_ids_unchanged():
    for v in ("view-overview", "view-watch", "view-sectors", "view-portfolio", "view-etf", "view-opps", "view-brief", "view-alerts"):
        assert f'id="{v}"' in HTML
    assert '["watch", "Preferiti"]' in APP and '["screener", "Screener"]' in APP


def test_04_logo_is_inline_svg_same_mark_as_favicon():
    head = HTML.split("<header")[1].split("</header>")[0]
    assert '<svg class="logo"' in head and "<img" not in head
    # 2026-11-09: the blocks of the favicon (green, red, green, dark grey base), no more candles
    for cls in ("lg-g", "lg-r", "lg-b"):
        assert f'class="{cls}"' in head
    assert "lg-up" not in HTML + CSS and "lg-dn" not in HTML + CSS and "candle" not in head.lower()


# ------------------------------------------------------------------ 3-5. Preferiti

def test_05_preferiti_replaces_in_osservazione():
    assert "In osservazione" not in APP and "In osservazione" not in HTML
    assert "<h2>Preferiti" in HTML and "Aggiungi ai Preferiti" in APP and "Togli dai Preferiti" in APP
    assert 'aria-pressed="${state.watch.has(' in APP                          # clear visual state, also for screen readers


def test_06_watchlist_kept_and_never_duplicated(tmp_path, monkeypatch):
    import server
    wl = tmp_path / "watchlist.json"
    wl.write_text(json.dumps({"tickers": ["AAA", "BBB"]}))                   # earlier choices
    monkeypatch.setattr(server, "WATCHLIST", str(wl))
    cl = server.app.test_client()
    assert cl.get("/api/watchlist").get_json()["tickers"] == ["AAA", "BBB"]
    r = cl.post("/api/watchlist", json={"tickers": ["AAA", "BBB", "aaa", "CCC", "BBB"]}).get_json()
    assert r["tickers"] == ["AAA", "BBB", "CCC"]
    assert json.loads(wl.read_text())["tickers"] == ["AAA", "BBB", "CCC"]


def test_07_preferiti_not_filled_by_models():
    # the star toggles only on a click; no code adds "Monitora" rows to the watchlist
    assert APP.count("state.watch.add(") == 1
    assert re.search(r"function toggleWatch\(t\) \{\s*state\.watch\.has\(t\) \? state\.watch\.delete\(t\) : state\.watch\.add\(t\);", APP)
    assert "Monitora" not in APP[APP.index("function toggleWatch"):APP.index("function toggleWatch") + 400]


# ------------------------------------------------------------------ 6. no inner scrolling in Mercato

def test_08_macro_earnings_movers_have_no_inner_scroll():
    for sel in ("#macro", ".earn-list", ".mv-list", ".macro-card", ".earn-card"):
        for m in re.finditer(r"([^{}]*)\{([^}]*)\}", CSS):
            if sel in m.group(1).split(",")[0] or any(sel == s.strip().split(" ")[0] for s in m.group(1).split(",")):
                assert not re.search(r"overflow-y\s*:\s*(auto|scroll)|max-height", m.group(2)), (sel, m.group(0)[:120])
    assert 'id="macroCard"' in HTML and 'id="earnCard"' in HTML


# ------------------------------------------------------------------ 7. macro events: status, source, missing values

def test_09_macro_period_status_and_missing_values(monkeypatch):
    import macro_calendar as mc
    monkeypatch.setattr(mc, "_bls", {"data": None, "at": 0})
    monkeypatch.setattr(mc, "_auto", {"fomc": [], "pce": [], "rate": "3.75-4.00", "rateAt": "2026-11-06", "checked": "2026-11-06", "errors": {}})
    now = datetime(2026, 11, 6, 12, 0, tzinfo=ET)
    out = mc.upcoming(7, None, past=30, now=now)
    kinds = {(e["kind"], e["date"]): e for e in out["events"]}
    jobs = kinds[("jobs", "2026-11-06")]
    assert jobs["status"] == "pubblicato" and jobs["values"] is None and jobs["consensus"] is None
    assert jobs["source"]["url"].startswith("https://www.bls.gov/")
    assert kinds[("cpi", "2026-11-10")]["status"] == "atteso"
    fomc = kinds[("fomc", "2026-10-28")]
    assert fomc["rate"]["actual"] == "3.75-4.00"                              # Fed page read after the decision
    assert all(e["status"] in ("atteso", "pubblicato", "rinviato") for e in out["events"])
    assert min(e["date"] for e in out["events"]) >= "2026-10-07"


def test_10_macro_rate_unknown_before_the_page_is_read_again(monkeypatch):
    import macro_calendar as mc
    monkeypatch.setattr(mc, "_auto", {"fomc": [], "pce": [], "rate": "4.00-4.25", "rateAt": "2026-10-28", "checked": "2026-10-28", "errors": {}})
    now = datetime(2026, 10, 29, 9, 0, tzinfo=ET)
    e = next(x for x in mc.upcoming(0, None, past=2, now=now)["events"] if x["kind"] == "fomc")
    assert e["rate"]["actual"] is None                                        # never shows the old rate as the new one


def test_11_macro_moved_date_is_rinviato(monkeypatch):
    import macro_calendar as mc
    monkeypatch.setattr(mc, "_auto", {"fomc": [], "pce": [["2026-11-27", "08:30", "2026-10"]], "rate": None, "checked": "2026-11-06", "errors": {}})
    out = mc.upcoming(31, None, now=datetime(2026, 11, 6, 9, 0, tzinfo=ET))
    old = next(e for e in out["events"] if e["kind"] == "pce" and e["date"] == "2026-11-25")
    assert old["status"] == "rinviato" and old["movedTo"] == "2026-11-27"


def test_12_api_macro_period_is_bounded():
    import server
    cl = server.app.test_client()
    with app_env.record_writes() as seen:
        a = cl.get("/api/macro?past=999&days=-5").get_json()
        b = cl.get("/api/macro?past=abc").get_json()
    assert "events" in a and "events" in b and "blsAt" in a
    assert [w for w in seen if "data" in w[1] or "diario" in w[1]] == []


# ------------------------------------------------------------------ 8. earnings: dates kept apart, nothing invented

def _fund(report_iso):
    return {"Q": [{"end": "2026-09-30", "revenue": 1.2e9}, {"end": "2026-06-30", "revenue": 1.1e9}],
            "earnings": [{"date": report_iso, "past": True}, {"date": "2026-08-06T16:00:00-04:00", "past": True}]}


def test_13_published_report_uses_its_own_estimate(monkeypatch):
    import earnings
    reps = {"AAA": [{"ts": "2026-11-05T16:00:00-05:00", "eps": 2.0, "reported": 2.2, "surprise": 10.0},
                    {"ts": "2026-08-06T16:00:00-04:00", "eps": 1.5, "reported": 1.4, "surprise": -6.7}], "BBB": []}
    monkeypatch.setattr(earnings, "reports", lambda tickers: {t: reps.get(t, []) for t in tickers})
    ann = {"AAA": datetime(2026, 11, 5, 16, 0, tzinfo=ET).timestamp(), "BBB": datetime(2026, 11, 10, 8, 0, tzinfo=ET).timestamp()}
    anl = {"AAA": {"eps": {"0q": {"avg": 0.9, "numberOfAnalysts": 9}}, "rev": {"0q": {"avg": 1.3e9}}},
           "BBB": {"eps": {"0q": {"avg": 1.1, "numberOfAnalysts": 5}}}}
    d = earnings.details(["AAA", "BBB"], {}, anl, announce=ann, infos={"BBB": {"isEarningsDateEstimate": True}},
                         fund={"AAA": _fund("2026-11-05T16:00:00-05:00")}, fetched="2026-11-06", analysts_date="2026-11-06",
                         now=datetime(2026, 11, 6, 12, 0, tzinfo=ET).timestamp())
    a, b = d["AAA"], d["BBB"]
    assert a["status"] == "pubblicata" and a["epsExpected"] == 2.0 and a["epsActual"] == 2.2   # not the 0.9 of next quarter
    assert a["revExpected"] is None                                           # analysts downloaded after the report
    assert a["period"] == "2026-09-30" and a["periodExact"] and a["revActual"] == 1.2e9
    assert a["revSurprise"] is None and a["fetched"] == "2026-11-06"
    assert b["status"] == "da pubblicare" and b["dateConfirmed"] is False and b["epsActual"] is None
    assert b["revExpected"] is None and b["revActual"] is None                # missing stays missing, never 0


def test_14_past_date_without_results_is_not_published(monkeypatch):
    import earnings
    monkeypatch.setattr(earnings, "reports", lambda tickers: {"AAA": [{"ts": "2026-08-06T16:00:00-04:00", "eps": 1, "reported": 1, "surprise": 0}]})
    d = earnings.details(["AAA"], {}, {}, announce={"AAA": datetime(2026, 11, 5, 16, 0, tzinfo=ET).timestamp()},
                         now=datetime(2026, 11, 6, 12, 0, tzinfo=ET).timestamp())["AAA"]
    assert d["status"] == "attesa dati" and d["epsActual"] is None and d["dateConfirmed"] is None


# ------------------------------------------------------------------ 9-10. movers: sources, dates, no invented causes

RSS = b"""<?xml version="1.0"?><rss><channel><title>t</title>
<item><title>AAA Stock Falls as Federal Orders Stall</title><link>https://finance.yahoo.com/a.html?.tsrc=rss</link>
<pubDate>Thu, 05 Nov 2026 15:00:00 +0000</pubDate><description>Shares fell 9% after the company cut its outlook. More text.</description></item>
<item><title>Why AAA Shares Are Falling?</title><link>https://www.fool.com/x</link><pubDate>Thu, 05 Nov 2026 16:00:00 +0000</pubDate><description>d</description></item>
</channel></rss>"""


def test_15_rss_parsing_keeps_source_link_and_time():
    import server
    items = server.parse_rss(RSS)
    assert items[0]["publisher"] == "Yahoo Finance" and items[0]["url"] == "https://finance.yahoo.com/a.html"
    assert items[0]["time"].startswith("2026-11-05T15:00") and items[1]["publisher"] == "Motley Fool"
    assert server.parse_rss(b"not xml") == []


def row(chg=-9.0, earn=None):
    return {"ticker": "AAA", "name": "Alfa Corp", "chgPct": chg, "sector": "Tecnologia", "session": "2026-11-05", "earningsTs": earn}


def test_16_evidence_labels_never_invent_a_cause():
    import server
    now = datetime(2026, 11, 6, 9, 0, tzinfo=ET)
    ctx = {"Tecnologia": {"chg": 0.1, "same": 0.2}}
    # nothing at all
    x = server.explain_move(row(), [], ctx, now)
    assert server.move_evidence(x)["key"] == "unverified"
    # only the earnings date in the window: correlated, not a cause
    x = server.explain_move(row(earn=datetime(2026, 11, 4, 16, 0, tzinfo=ET).timestamp()), [], ctx, now)
    ev = server.move_evidence(x)
    assert ev["key"] == "related" and ev["label"] == "EVENTO CORRELATO" and "coincidenza" in ev["meaning"]
    # an explainer article stating the reason, from a news site: documented by the source
    x = server.explain_move(row(), server.parse_rss(RSS)[:1], ctx, now)
    ev = server.move_evidence(x)
    assert ev["key"] == "documented" and x["news"]["clause"] and "non la verifica" in ev["meaning"]
    # the same kind of article from an opinion site / a question headline: only correlated
    x = server.explain_move(row(), server.parse_rss(RSS)[1:], ctx, now)
    assert server.move_evidence(x)["key"] in ("related", "unverified")
    # a sector that moved together, or a macro release the same day: correlated
    x = server.explain_move(row(), [], {"Tecnologia": {"chg": -3.0, "same": 0.9}}, now)
    assert server.move_evidence(x)["key"] == "related"
    assert server.move_evidence(server.explain_move(row(), [], ctx, now), ["inflazione CPI"])["key"] == "related"


def test_17_movers_card_shows_label_source_and_no_probable_cause():
    body = APP[APP.index("function whyItem(x, D)"):APP.index("function ago(t)")]
    assert "x.summary" not in body and "Probabile motivo" not in body
    assert "E.label" in body and "n.url" in body and "n.publisher" in body and "absT(n.time)" in body
    assert 'data-open="${esc(x.ticker)}"' in body                             # opens the stock drawer, page stays


def test_18_news_fallback_only_for_the_movers_card():
    import server
    src = read("server.py")
    assert src.count("news_moves(") == 2                                      # definition + movers_why
    assert "lambda t: news(t, 40)" in src                                     # signals still use the old source


def test_19_news_fallback_uses_the_feed_when_yfinance_is_empty(monkeypatch):
    import server

    class R:
        content = RSS
        def raise_for_status(self): pass
    monkeypatch.setattr(server, "news", lambda t, c=12: [])
    monkeypatch.setattr(server, "_news_down", {"until": 0.0})
    monkeypatch.setattr(server.requests, "get", lambda *a, **k: R())
    items = server.news_moves("AAA")
    assert len(items) == 2 and items[0]["via"] == "rss"


# ------------------------------------------------------------------ 11-12. maps, trend help, state help

def test_20_map_readability_safeguards():
    assert "SEC_SHORT" in APP and "SEC_TINY" in APP and "mapListHTML" in APP and 'id="ovMapList"' in HTML
    rrg = APP[APP.index("function drawRRG"):APP.index("function groupTip")]
    assert "free(b)" in rrg and "rrg-list" in rrg and 'attr("tabindex", 0)' in rrg and '"focus"' in rrg
    assert "b.x >= 0 && b.y >= 0 && b.x + b.w <= iw && b.y + b.h <= ih" in rrg  # labels stay inside the chart


def test_21_trend_help_matches_the_rule():
    import etf
    import etf_opportunity
    for f in (etf.trend_word, etf_opportunity.trend_word):
        assert f(110, 105, 100) == "Rialzista" and f(90, 95, 100) == "Ribassista"
        assert f(110, 95, 100) == "Laterale" and f(100, 105, 100) == "Laterale"
    t = APP[APP.index("const ETF_TREND_INFO"):APP.index("const trendWord")]
    for w in ("ultime <b>50</b> chiusure", "ultime <b>200</b>", "<b>Rialzista</b>: prezzo sopra la media 50 <b>e</b> media 50 sopra la media 200",
              "Cosa NON significa", "forza relativa", "cambio di trend recente", "volatilità", "(L4)", "(S4)"):
        assert w in t, w
    P = etf_opportunity.P if hasattr(etf_opportunity, "P") else etf_opportunity.PARAMS
    assert P["rs_long_up"] == 1.0 and P["rs_short_up"] == 0.5               # the thresholds written in the text


def test_22_monitor_help_cites_existing_rules():
    import investment_decision_engine as ide
    t = APP[APP.index("const MONITOR_HELP"):APP.index("const E2_MON_HELP")]
    for rid in ("A-M1", "B-M1", "E-M1", "E-M2", "F-M1"):
        assert rid in t and ide.RULES_D1[rid].startswith("Monitora")
    assert "E-M3" in t and ide.E_M3.startswith("Monitora — trend esplorativo")
    assert "Non è un suggerimento di acquisto" in t and "Preferiti" in t
    import etf_opportunity
    assert etf_opportunity.state_of([{"ok": True}, {"ok": True}, {"ok": False}], [], "normale") == "Trend favorevole da monitorare"


# ------------------------------------------------------------------ 13. Portafoglio: unclassified, Compatibilità

def test_23_unclassified_list_without_inventing(tmp_path):
    import portfolio
    cls = {"XX0000000002": {"settore": "Tecnologia", "tema": "Chip"}}
    fund = {"name": "ETF FINTO 3X", "isin": "XX0000000001", "kind": "ETF"}
    lev, dims, known = portfolio.classify(fund, {}, {}, {}, {}, {})
    miss = portfolio.missing_fields(fund, {}, dims, lev, known)
    assert dims["sector"] == {"Non classificato": 1} and "classificazione.json" in miss[0] and "3x" in miss[1]
    part = {"name": "ETF FINTO", "isin": "XX0000000002", "kind": "ETF"}
    lev, dims, known = portfolio.classify(part, cls, {}, {}, {}, {})
    assert portfolio.missing_fields(part, cls, dims, lev, known) == ["paese non indicato"]
    assert not os.path.exists(portfolio.CLASS_FILE)                           # nothing written


def test_24_compatibility_intro_and_consent_unchanged():
    page = APP[APP.index("function fitPageHTML()"):APP.index("function fitPageHTML()") + 6000]
    assert "Questa analisi ti aiuta a capire come un nuovo investimento cambierebbe il tuo portafoglio" in page
    assert "dati inventati" in page and "Compatibile non vuol dire buono o cattivo" in page and "Cosa NON misura" in page
    assert 'data-fit="mio">Analizza compatibilità con il mio portafoglio' in page and 'data-fit="esempio"' in page


# ------------------------------------------------------------------ 14-16. engines unchanged, versions, no writes

ENGINES = ["daily_job.py", "schedule.sh", "investment_decision_engine.py", "investment_engine.py", "investment_valuation.py",
           "investment_valuation_v1.py", "etf.py", "etf_opportunity.py", "portfolio_fit.py", "opportunity_scanner.py",
           "opportunity_strategies.py", "signals.py", "score.py", "pillars.py", "alert_engine.py", "decision.py", "rules.py",
           "opportunity_diary.py", "decision_diary.py", "investment_diary.py", "etf_opportunity_diary.py", "valuation_diary.py"]


def test_25_financial_engines_identical_to_git_head():
    try:
        subprocess.run(["git", "-C", ROOT, "rev-parse", "HEAD"], check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError):
        # Phase 9B.1: no git (the build kit on Windows): the engines must be byte-identical to the files that
        # packaging/crea_kit.py found identical to git HEAD on the Mac. Missing fingerprints = FAIL, never a skip.
        import hashlib
        import json
        rec = os.path.join(ROOT, "packaging", "motori_verificati.json")
        assert os.path.isfile(rec), "git non disponibile e packaging/motori_verificati.json assente: kit non valido"
        with open(rec, encoding="utf-8") as fh:
            want = json.load(fh)["files"]
        assert sorted(want) == sorted(ENGINES), "elenco dei motori diverso da quello verificato sul Mac"
        for f in ENGINES:
            with open(os.path.join(ROOT, f), "rb") as fh:
                assert hashlib.sha256(fh.read()).hexdigest() == want[f], f"{f} changed"
        return
    for f in ENGINES:
        head = subprocess.run(["git", "-C", ROOT, "show", f"HEAD:{f}"], capture_output=True).stdout
        with open(os.path.join(ROOT, f), "rb") as fh:
            assert fh.read() == head, f"{f} changed"


def test_26_versions_match():
    import server
    assert re.search(r'const PAGE_VERSION = "([^"]+)"', APP).group(1) == server.DASHBOARD_VERSION


def test_27_browsing_mercato_writes_nothing(monkeypatch):
    import server
    import threading
    monkeypatch.setattr(server, "news_moves", lambda t, c=40: [])
    ready = threading.Event()
    ready.set()                                                               # /api/movers-why waits for the first download
    monkeypatch.setattr(server.store, "ready", ready)
    cl = server.app.test_client()
    with app_env.record_writes() as seen:
        for u in ("/api/macro", "/api/macro?past=30&days=0", "/api/movers-why", "/api/earnings", "/api/portfolio", "/api/watchlist"):
            assert cl.get(u).status_code in (200, 503), u
    bad = [w for w in seen if re.search(r"diar|sqlite|portafoglio|watchlist|job_status", w[1])]
    assert bad == []


# ------------------------------------------------------------------ 2026-11-09: icon, full name, accordions in Mercato

ICON = read("static/icon.svg")


def test_30_favicon_is_local_svg_with_cache_buster():
    links = re.findall(r'<link rel="icon"[^>]*>', HTML)
    assert len(links) == 1 and 'href="/static/icon.svg?v=' in links[0] and "data:image" not in links[0]
    for color in ("#1f9d55", "#d6393b", "#555"):
        assert color in ICON
    assert "http" not in ICON.replace("http://www.w3.org/2000/svg", "")        # no external images


def test_31_full_name_never_abbreviated():
    head = HTML.split("<header")[1].split("</header>")[0]
    assert "<b>Nasdaq-100</b>" in head and "Monitor" in head and "NDX" not in head
    assert "<title>Nasdaq-100 Monitor</title>" in HTML


def test_32_macro_and_earnings_are_accordions_closed_by_default():
    for card, body in (("macroCard", "macroBody"), ("earnCard", "earnBody")):
        m = re.search(r'id="%s"[\s\S]*?<button[^>]*data-fold="%s"[^>]*>' % (card, card), HTML)
        assert m and 'aria-expanded="false"' in m.group(0) and f'aria-controls="{body}"' in m.group(0)
        assert re.search(r'id="%s"[^>]*inert' % body, HTML)
    # filters, tables and their ids stay inside the accordions
    assert HTML.index('id="macroSeg"') > HTML.index('id="macroBody"') and HTML.index('id="earnings"') > HTML.index('id="earnBody"')
    assert 'if (v === "overview" && state.view !== "overview") closeFolds();' in APP
    # the accordions have their own class: "fold" alone is used by other <details> (closing them broke setView)
    assert 'class="card macro-card mfold"' in HTML and 'class="card earn-card mfold"' in HTML
    assert '$$(".mfold").forEach(c => setFold(c, false))' in APP and '$$(".fold")' not in APP


def test_33_accordion_has_no_inner_scroll_or_max_height():
    for m in re.finditer(r"([^{}]*)\{([^}]*)\}", CSS):
        if ".fold" in m.group(1) or ".mfold" in m.group(1):
            assert not re.search(r"overflow-y\s*:\s*(auto|scroll)|max-height", m.group(2)), m.group(0)[:120]
    assert "grid-template-rows: 0fr" in CSS and "grid-template-rows: 1fr" in CSS


def test_34_agenda_links_open_the_accordion_without_changing_page():
    assert 'data-fold-open="macroCard"' in APP and 'data-fold-open="earnCard"' in APP
    assert 'data-goto="macroCard"' not in APP and 'data-goto="earnCard"' not in APP
