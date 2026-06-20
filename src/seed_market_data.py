"""Seed ClickHouse tick_data with REAL 1-minute NSE candles from Yahoo Finance (free, no key).

The Groww market-data API is paywalled (~₹499/mo) and NSE's own endpoints geo-block
non-Indian IPs, so Yahoo Finance (via yfinance) is the free way to get real 1-min
NSE bars. Outside market hours the freshest real bars are hours old — older than the
agents' "last N minutes" tool windows — so we keep the real OHLCV values and shift the
timestamps so the most recent bar lands on the current minute (1-min spacing preserved).

Run:  source .venv/bin/activate && python src/seed_market_data.py
Re-run it before a session to refresh the window (the snapshot ages as real time passes).
"""
import json
from datetime import datetime, timedelta, timezone

import requests
import yfinance as yf

CLICKHOUSE_URL = "http://localhost:8123"
AUTH = ("default", "admin")
IST = timezone(timedelta(hours=5, minutes=30))
BARS_PER_SYMBOL = 45

# Yahoo ticker -> (our symbol, exchange). Add/remove freely.
TICKERS = {
    "RELIANCE.NS": ("RELIANCE", "NSE"),
    "TCS.NS": ("TCS", "NSE"),
    "HDFCBANK.NS": ("HDFCBANK", "NSE"),
    "INFY.NS": ("INFY", "NSE"),
    "ICICIBANK.NS": ("ICICIBANK", "NSE"),
    "SBIN.NS": ("SBIN", "NSE"),
    "TATASTEEL.NS": ("TATASTEEL", "NSE"),
    "BAJFINANCE.NS": ("BAJFINANCE", "NSE"),
    "^NSEI": ("NIFTY", "NSE"),
}


def main() -> None:
    now_min = datetime.now(IST).replace(second=0, microsecond=0)
    rows = []
    for yt, (sym, exch) in TICKERS.items():
        try:
            df = yf.Ticker(yt).history(period="5d", interval="1m").dropna(subset=["Open", "High", "Low", "Close"])
        except Exception as exc:
            print(f"  skip {yt}: {exc!r}")
            continue
        if df.empty:
            print(f"  skip {yt}: no data")
            continue
        tail = df.tail(BARS_PER_SYMBOL)
        n = len(tail)
        for i, (_, bar) in enumerate(tail.iterrows()):
            ts = now_min - timedelta(minutes=(n - 1 - i))  # newest bar -> now_min
            vol = bar.get("Volume", 0)
            rows.append({
                "symbol": sym, "exchange": exch,
                "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
                "open": round(float(bar["Open"]), 2),
                "high": round(float(bar["High"]), 2),
                "low": round(float(bar["Low"]), 2),
                "close": round(float(bar["Close"]), 2),
                "volume": float(vol) if vol == vol else 0.0,  # NaN guard (NaN != NaN)
            })
        print(f"  {sym}: {n} real bars (last close {float(tail['Close'].iloc[-1]):.2f})")

    if not rows:
        print("No data fetched — nothing inserted.")
        return

    # Reset first so re-running doesn't stack overlapping snapshots (this table
    # holds only seeded/simulated demo data). Drop this TRUNCATE if you run the
    # live simulator alongside and want to keep its candles.
    requests.post(CLICKHOUSE_URL, data="TRUNCATE TABLE default.tick_data", auth=AUTH, timeout=30).raise_for_status()

    payload = "\n".join(json.dumps(r) for r in rows)
    resp = requests.post(
        f"{CLICKHOUSE_URL}?query=" + requests.utils.quote("INSERT INTO default.tick_data FORMAT JSONEachRow"),
        data=payload, auth=AUTH, timeout=60,
    )
    resp.raise_for_status()
    print(f"\nInserted {len(rows)} real candles across {len(TICKERS)} symbols, ending at {now_min:%H:%M} IST")


if __name__ == "__main__":
    main()
