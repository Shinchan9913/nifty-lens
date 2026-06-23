"""Backfill multi-day history + macro/cross-asset series from Yahoo Finance (free).

- daily_bars: ~1y of daily OHLCV for the US-led equity universe + a few NSE names
  (trend/regime/event-study context).
- macro_bars: ~1y of daily closes for indices, commodities, FX, rates, crypto, vol
  (the intermarket / risk-regime lens).

Run:  source .venv/bin/activate && python src/seed_history.py
"""
import json

import requests
import yfinance as yf

CLICKHOUSE_URL = "http://localhost:8123"
AUTH = ("default", "admin")
PERIOD = "1y"

# Yahoo ticker -> (our symbol, exchange)
US_EQUITIES = {
    "AAPL": ("AAPL", "US"), "MSFT": ("MSFT", "US"), "NVDA": ("NVDA", "US"),
    "AMZN": ("AMZN", "US"), "GOOGL": ("GOOGL", "US"), "META": ("META", "US"),
    "TSLA": ("TSLA", "US"), "JPM": ("JPM", "US"), "XOM": ("XOM", "US"), "JNJ": ("JNJ", "US"),
}
NSE_EQUITIES = {
    "RELIANCE.NS": ("RELIANCE", "NSE"), "TCS.NS": ("TCS", "NSE"),
    "INFY.NS": ("INFY", "NSE"), "HDFCBANK.NS": ("HDFCBANK", "NSE"),
}
# Yahoo ticker -> (our symbol, category)
MACRO = {
    "^GSPC": ("SP500", "index"), "^IXIC": ("NASDAQ", "index"), "^DJI": ("DOW", "index"),
    "^NSEI": ("NIFTY", "index"), "^VIX": ("VIX", "volatility"),
    "^TNX": ("US10Y", "rates"),
    "INR=X": ("USDINR", "fx"), "DX-Y.NYB": ("DXY", "fx"), "EURUSD=X": ("EURUSD", "fx"),
    "CL=F": ("WTI", "commodity"), "BZ=F": ("BRENT", "commodity"), "GC=F": ("GOLD", "commodity"),
    "SI=F": ("SILVER", "commodity"), "HG=F": ("COPPER", "commodity"),
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
        return yf.Ticker(yt).history(period=PERIOD, interval="1d").dropna(subset=["Close"])
    except Exception as e:
        print(f"  skip {yt}: {e!r}")
        return None


def main() -> None:
    # idempotent: derived data, safe to reset
    for t in ("daily_bars", "macro_bars"):
        requests.post(CLICKHOUSE_URL, data=f"TRUNCATE TABLE default.{t}", auth=AUTH, timeout=30).raise_for_status()

    eq_rows = []
    for yt, (sym, exch) in {**US_EQUITIES, **NSE_EQUITIES}.items():
        df = _hist(yt)
        if df is None or df.empty:
            continue
        for ts, bar in df.iterrows():
            eq_rows.append({
                "symbol": sym, "exchange": exch, "date": ts.strftime("%Y-%m-%d"),
                "open": round(float(bar["Open"]), 4), "high": round(float(bar["High"]), 4),
                "low": round(float(bar["Low"]), 4), "close": round(float(bar["Close"]), 4),
                "volume": float(bar.get("Volume", 0) or 0),
            })
        print(f"  {sym}: {len(df)} daily bars")
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
