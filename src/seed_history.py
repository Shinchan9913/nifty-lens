"""Backfill multi-day history + macro/cross-asset series.

- daily_bars: ~3y (HISTORY_YEARS) of daily OHLCV for the US-led equity universe +
  the NSE universe (trend/regime/event-study context + the dependency graph).
- macro_bars: ~3y of daily closes for indices, commodities, FX, rates, crypto, vol
  (the intermarket / risk-regime lens + the locked dependency factor set).

Sources: Yahoo Finance (free) by default. Set USE_GROWW=1 to pull the NSE equities
from the Groww API instead (NSE-native, more authoritative), with automatic
per-symbol Yahoo fallback. Groww's historical API is a PAID add-on — with an
un-entitled key the seeder logs that and silently uses Yahoo. Global factors
(S&P, crude, gold, VIX, USDINR) always come from Yahoo; Groww does not carry them.

Run:  source .venv/bin/activate && python src/seed_history.py
      HISTORY_YEARS=2 python src/seed_history.py  # lighter run
      USE_GROWW=1 python src/seed_history.py       # once the Groww key is entitled
"""
import json
import os
import sys
from datetime import datetime, timedelta

import requests
import yfinance as yf

# Allow running directly as `python src/seed_history.py` (puts the project root,
# not src/, on sys.path so the `from src import ...` below resolves).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import groww_history

CLICKHOUSE_URL = "http://localhost:8123"
AUTH = ("default", "admin")
# Years of daily history to pull. More observations => more walk-forward folds
# => more reliable dependency edges, but heavier to fetch. 3y is a good balance;
# set HISTORY_YEARS=2 for a lighter run. (Groww's daily API caps at ~3y/request.)
HISTORY_YEARS = float(os.getenv("HISTORY_YEARS", "3"))
USE_GROWW = os.getenv("USE_GROWW", "0") == "1"

# Yahoo ticker -> (our symbol, exchange)
US_EQUITIES = {
    "AAPL": ("AAPL", "US"), "MSFT": ("MSFT", "US"), "NVDA": ("NVDA", "US"),
    "AMZN": ("AMZN", "US"), "GOOGL": ("GOOGL", "US"), "META": ("META", "US"),
    "TSLA": ("TSLA", "US"), "JPM": ("JPM", "US"), "XOM": ("XOM", "US"), "JNJ": ("JNJ", "US"),
}
# NSE cash-equity universe for the dependency graph: the NIFTY 100 (NIFTY 50 +
# NIFTY Next 50). All large-cap and liquid, which keeps the non-synchronous-trading
# artefacts that contaminate daily lead-lag low (see src/forecast/README, note #3).
# Index membership drifts and a few tickers may be missing on Yahoo — the seeder
# skips failures and the pipeline drops empty series, so the set is self-healing.
NSE_EQUITIES = {
    # --- NIFTY 50 -------------------------------------------------------------
    "ADANIENT.NS": ("ADANIENT", "NSE"), "ADANIPORTS.NS": ("ADANIPORTS", "NSE"),
    "APOLLOHOSP.NS": ("APOLLOHOSP", "NSE"), "ASIANPAINT.NS": ("ASIANPAINT", "NSE"),
    "AXISBANK.NS": ("AXISBANK", "NSE"), "BAJAJ-AUTO.NS": ("BAJAJ-AUTO", "NSE"),
    "BAJFINANCE.NS": ("BAJFINANCE", "NSE"), "BAJAJFINSV.NS": ("BAJAJFINSV", "NSE"),
    "BEL.NS": ("BEL", "NSE"), "BHARTIARTL.NS": ("BHARTIARTL", "NSE"),
    "BRITANNIA.NS": ("BRITANNIA", "NSE"), "CIPLA.NS": ("CIPLA", "NSE"),
    "COALINDIA.NS": ("COALINDIA", "NSE"), "DRREDDY.NS": ("DRREDDY", "NSE"),
    "EICHERMOT.NS": ("EICHERMOT", "NSE"), "GRASIM.NS": ("GRASIM", "NSE"),
    "HCLTECH.NS": ("HCLTECH", "NSE"), "HDFCBANK.NS": ("HDFCBANK", "NSE"),
    "HDFCLIFE.NS": ("HDFCLIFE", "NSE"), "HEROMOTOCO.NS": ("HEROMOTOCO", "NSE"),
    "HINDALCO.NS": ("HINDALCO", "NSE"), "HINDUNILVR.NS": ("HINDUNILVR", "NSE"),
    "ICICIBANK.NS": ("ICICIBANK", "NSE"), "INDUSINDBK.NS": ("INDUSINDBK", "NSE"),
    "INFY.NS": ("INFY", "NSE"), "ITC.NS": ("ITC", "NSE"),
    "JSWSTEEL.NS": ("JSWSTEEL", "NSE"), "KOTAKBANK.NS": ("KOTAKBANK", "NSE"),
    "LT.NS": ("LT", "NSE"), "LTIM.NS": ("LTIM", "NSE"),
    "M&M.NS": ("MM", "NSE"), "MARUTI.NS": ("MARUTI", "NSE"),
    "NESTLEIND.NS": ("NESTLEIND", "NSE"), "NTPC.NS": ("NTPC", "NSE"),
    "ONGC.NS": ("ONGC", "NSE"), "POWERGRID.NS": ("POWERGRID", "NSE"),
    "RELIANCE.NS": ("RELIANCE", "NSE"), "SBILIFE.NS": ("SBILIFE", "NSE"),
    "SBIN.NS": ("SBIN", "NSE"), "SHRIRAMFIN.NS": ("SHRIRAMFIN", "NSE"),
    "SUNPHARMA.NS": ("SUNPHARMA", "NSE"), "TATACONSUM.NS": ("TATACONSUM", "NSE"),
    "TATAMOTORS.NS": ("TATAMOTORS", "NSE"), "TATASTEEL.NS": ("TATASTEEL", "NSE"),
    "TCS.NS": ("TCS", "NSE"), "TECHM.NS": ("TECHM", "NSE"),
    "TITAN.NS": ("TITAN", "NSE"), "TRENT.NS": ("TRENT", "NSE"),
    "ULTRACEMCO.NS": ("ULTRACEMCO", "NSE"), "WIPRO.NS": ("WIPRO", "NSE"),
    # --- NIFTY Next 50 --------------------------------------------------------
    "ABB.NS": ("ABB", "NSE"), "ADANIENSOL.NS": ("ADANIENSOL", "NSE"),
    "ADANIGREEN.NS": ("ADANIGREEN", "NSE"), "ADANIPOWER.NS": ("ADANIPOWER", "NSE"),
    "AMBUJACEM.NS": ("AMBUJACEM", "NSE"), "BAJAJHLDNG.NS": ("BAJAJHLDNG", "NSE"),
    "BANKBARODA.NS": ("BANKBARODA", "NSE"), "BERGEPAINT.NS": ("BERGEPAINT", "NSE"),
    "BOSCHLTD.NS": ("BOSCHLTD", "NSE"), "CANBK.NS": ("CANBK", "NSE"),
    "CGPOWER.NS": ("CGPOWER", "NSE"), "CHOLAFIN.NS": ("CHOLAFIN", "NSE"),
    "COLPAL.NS": ("COLPAL", "NSE"), "DABUR.NS": ("DABUR", "NSE"),
    "DIVISLAB.NS": ("DIVISLAB", "NSE"), "DLF.NS": ("DLF", "NSE"),
    "DMART.NS": ("DMART", "NSE"), "GAIL.NS": ("GAIL", "NSE"),
    "GODREJCP.NS": ("GODREJCP", "NSE"), "HAL.NS": ("HAL", "NSE"),
    "HAVELLS.NS": ("HAVELLS", "NSE"), "ICICIGI.NS": ("ICICIGI", "NSE"),
    "ICICIPRULI.NS": ("ICICIPRULI", "NSE"), "INDHOTEL.NS": ("INDHOTEL", "NSE"),
    "INDIGO.NS": ("INDIGO", "NSE"), "IOC.NS": ("IOC", "NSE"),
    "IRCTC.NS": ("IRCTC", "NSE"), "JINDALSTEL.NS": ("JINDALSTEL", "NSE"),
    "JIOFIN.NS": ("JIOFIN", "NSE"), "JUBLFOOD.NS": ("JUBLFOOD", "NSE"),
    "LICI.NS": ("LICI", "NSE"), "MARICO.NS": ("MARICO", "NSE"),
    "MOTHERSON.NS": ("MOTHERSON", "NSE"), "MUTHOOTFIN.NS": ("MUTHOOTFIN", "NSE"),
    "NAUKRI.NS": ("NAUKRI", "NSE"), "NMDC.NS": ("NMDC", "NSE"),
    "PFC.NS": ("PFC", "NSE"), "PIDILITIND.NS": ("PIDILITIND", "NSE"),
    "PNB.NS": ("PNB", "NSE"), "POLYCAB.NS": ("POLYCAB", "NSE"),
    "RECLTD.NS": ("RECLTD", "NSE"), "SAIL.NS": ("SAIL", "NSE"),
    "SHREECEM.NS": ("SHREECEM", "NSE"), "SIEMENS.NS": ("SIEMENS", "NSE"),
    "SRF.NS": ("SRF", "NSE"), "TATAPOWER.NS": ("TATAPOWER", "NSE"),
    "TORNTPHARM.NS": ("TORNTPHARM", "NSE"), "TVSMOTOR.NS": ("TVSMOTOR", "NSE"),
    "UNITDSPR.NS": ("UNITDSPR", "NSE"), "VBL.NS": ("VBL", "NSE"),
    "VEDL.NS": ("VEDL", "NSE"), "ZYDUSLIFE.NS": ("ZYDUSLIFE", "NSE"),
}
# Yahoo ticker -> (our symbol, category).
#
# The block tagged "nse_factor" is the LOCKED factor set the dependency pipeline
# residualises against: market (NIFTY), three sector proxies, FX, crude, gold and
# India VIX. It is intentionally small — with ~1y of daily bars (~250 obs) a wide
# factor model would overfit. The rest are kept for the existing dashboard tools.
MACRO = {
    # --- locked NSE dependency factor set --------------------------------------
    "^NSEI": ("NIFTY", "index"),          # market
    "^NSEBANK": ("NIFTY_BANK", "sector"),  # bank sector
    "^CNXIT": ("NIFTY_IT", "sector"),      # IT sector
    "^CNXMETAL": ("NIFTY_METAL", "sector"),  # metals sector
    "INR=X": ("USDINR", "fx"),            # rupee
    "BZ=F": ("BRENT", "commodity"),       # crude
    "GC=F": ("GOLD", "commodity"),        # gold
    "^INDIAVIX": ("INDIAVIX", "volatility"),  # India vol (falls back to VIX if empty)
    # --- additional cross-asset context (used by dashboard, not the factor model)
    "^GSPC": ("SP500", "index"), "^IXIC": ("NASDAQ", "index"), "^DJI": ("DOW", "index"),
    "^VIX": ("VIX", "volatility"), "^TNX": ("US10Y", "rates"),
    "DX-Y.NYB": ("DXY", "fx"), "EURUSD=X": ("EURUSD", "fx"),
    "CL=F": ("WTI", "commodity"), "SI=F": ("SILVER", "commodity"), "HG=F": ("COPPER", "commodity"),
    "BTC-USD": ("BTC", "crypto"),
}


def _insert(table: str, rows: list[dict]) -> None:
    if not rows:
        return
    payload = "\n".join(json.dumps(r) for r in rows)
    resp = requests.post(
        f"{CLICKHOUSE_URL}?query=" + requests.utils.quote(f"INSERT INTO default.{table} FORMAT JSONEachRow"),
        data=payload, auth=AUTH, timeout=120,
    )
    resp.raise_for_status()


def _hist(yt: str):
    try:
        end = datetime.now()
        start = end - timedelta(days=int(HISTORY_YEARS * 365))
        return yf.Ticker(yt).history(
            start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d"), interval="1d"
        ).dropna(subset=["Close"])
    except Exception as e:
        print(f"  skip {yt}: {e!r}")
        return None


def main() -> None:
    # idempotent: derived data, safe to reset
    for t in ("daily_bars", "macro_bars"):
        requests.post(CLICKHOUSE_URL, data=f"TRUNCATE TABLE default.{t}", auth=AUTH, timeout=30).raise_for_status()

    # Optionally route the NSE equities through Groww (NSE-native). Falls back to
    # Yahoo per-symbol if Groww is unentitled or a fetch fails.
    groww = None
    if USE_GROWW:
        ok, reason = groww_history.is_available()
        if ok:
            groww = groww_history.get_api()
            print("  Groww historical API: entitled — using it for NSE equities")
        else:
            print(f"  Groww historical API unavailable ({reason}) — using Yahoo for NSE equities")
    # Match the Yahoo window (Groww's daily API allows up to ~3y/request).
    g_end = datetime.now()
    g_start = g_end - timedelta(days=int(HISTORY_YEARS * 365))

    def _yahoo_rows(yt: str, sym: str, exch: str) -> list[dict]:
        df = _hist(yt)
        if df is None or df.empty:
            return []
        return [{
            "symbol": sym, "exchange": exch, "date": ts.strftime("%Y-%m-%d"),
            "open": round(float(bar["Open"]), 4), "high": round(float(bar["High"]), 4),
            "low": round(float(bar["Low"]), 4), "close": round(float(bar["Close"]), 4),
            "volume": float(bar.get("Volume", 0) or 0),
        } for ts, bar in df.iterrows()]

    eq_rows = []
    for yt, (sym, exch) in {**US_EQUITIES, **NSE_EQUITIES}.items():
        rows, source = None, "yahoo"
        if groww is not None and exch == "NSE":
            rows = groww_history.fetch_daily(groww, sym, exch, g_start, g_end)
            if rows:
                source = "groww"
        if not rows:
            rows = _yahoo_rows(yt, sym, exch)
        if not rows:
            continue
        eq_rows.extend(rows)
        print(f"  {sym}: {len(rows)} daily bars ({source})")
    _insert("daily_bars", eq_rows)

    macro_rows = []
    for yt, (sym, cat) in MACRO.items():
        df = _hist(yt)
        if df is None or df.empty:
            continue
        for ts, bar in df.iterrows():
            macro_rows.append({
                "symbol": sym, "category": cat, "date": ts.strftime("%Y-%m-%d"),
                "open": round(float(bar["Open"]), 4), "high": round(float(bar["High"]), 4),
                "low": round(float(bar["Low"]), 4), "close": round(float(bar["Close"]), 4),
            })
        print(f"  {sym} ({cat}): {len(df)} bars")
    _insert("macro_bars", macro_rows)

    print(f"\nInserted {len(eq_rows)} daily equity bars + {len(macro_rows)} macro bars.")


if __name__ == "__main__":
    main()
