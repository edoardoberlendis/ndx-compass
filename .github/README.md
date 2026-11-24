# NDX Compass

**A personal investment dashboard for Nasdaq-100 stocks and UCITS ETFs, built in Python, which I use for my own allocation decisions.**

It runs locally on my Mac (the app is called *Nasdaq-100 Monitor*; the interface is in Italian) and pulls public market data every day. The guiding rule of the project: **no signal is shown as "favourable" unless it has passed a backtest whose pass criteria were fixed before looking at the results.**

> Mechanical screening and research tool, not financial advice.

---

## What it does

| Area | What it answers |
|---|---|
| **Opportunities** | Which stocks deserve a closer look? Two exploratory rankings (short-term trading, medium/long-term investment), each with the rule that produced it |
| **Market** | What is happening today? Daily movers with documented causes, sector rotation map, US macro calendar (FOMC, CPI, PCE, jobs) and earnings |
| **Stocks** | Screener for the Nasdaq-100, fundamental scorecard, DCF valuation (FCFF discounted at WACC, three scenarios) and a rule-based decision section with risk-based position sizing |
| **ETFs** | Catalogue of 60+ UCITS ETFs with costs, tracking difference and exposures; overlap and correlation with my portfolio |
| **Portfolio** | Positions from my broker export, time-weighted performance vs. QQQ and VWCE, concentration, volatility, beta and drawdown |
| **Alerts** | What changed since yesterday in signals, valuations and data quality |

Every evening a scheduled job records signals and decisions in append-only diaries (SQLite with triggers that block edits), so each rule can later be measured **forward**, on data it has never seen.

## Research: what the backtests found

All tests use rules and pass thresholds committed *before* running them, plus a random-control check (200 fake rules) to make sure the bar cannot be cleared by luck.

**200-day trend filter on the Nasdaq-100 (QQQ, 2000–2026, monthly, no costs)**

| | Trend filter | Buy and hold |
|---|---:|---:|
| Annual return (CAGR) | **9.3%** | 9.2% |
| Volatility | **18.6%** | 26.7% |
| Maximum drawdown | **−45%** | −83% |

Same return with about 30% less volatility, and the dot-com drawdown almost halved. Across 47 ETF categories the protection was not consistent (it helps in long bear markets, not in fast crashes), so the dashboard shows it as information, not as a buy/sell signal.

**9 classic chart patterns (Nasdaq-100, 2017–2026)**: 8 of 9 failed the pre-set conditions (including 52-week breakouts and pullbacks); only the 50/200 golden cross passed, by a thin margin. None is presented as a reliable signal.

**Technical trend score (41,935 weekly observations)**: both extreme bands outperformed the middle ones, so the score does not separate direction and was removed from the final signal.

Known limits are stated in the app: survivorship bias (today's index members), overlapping cases, no transaction costs in the signal tests.

## Tech stack

- **Python 3.12**: Flask, pandas, NumPy, yfinance, SQLite
- **Frontend**: plain HTML, CSS and JavaScript with D3
- **Testing**: 660+ pytest tests on synthetic data only
- About 100 Python modules, ~38,000 lines of code
- Built with Claude Code as a coding assistant; design, rules and research decisions are mine

## Privacy

Personal data (broker exports, positions, personal diaries) lives only in a local `portafoglio/` folder that is excluded from Git and never leaves the machine. The repository contains code, public-data research outputs and synthetic test data only.

## Run it

```sh
./run.sh   # creates a virtual environment, installs requirements and opens http://localhost:8100
```

Requires Python 3.12. Full technical documentation (in Italian) is in the main `README.md`.

Third-party ETF reference data (fund lists, costs and exposures collected from provider websites) is not included in this repository, so the ETF section starts empty on a fresh install.
