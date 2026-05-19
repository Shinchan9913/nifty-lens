"""
Trade Simulator — generates 1-minute OHLCV candles directly to ClickHouse.

Simulates realistic tick-level price action for crypto, equity, and commodities.
Aggregates ticks into 1-minute OHLCV candles and inserts into tick_data.
Uses ClickHouse async_insert with JSONEachRow format.
"""
import json
import time
import random
import logging
import math
from datetime import datetime, timezone, timedelta

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# --- Configuration ---
CLICKHOUSE_URL = "http://localhost:8123"
CLICKHOUSE_DB = "default"
CLICKHOUSE_TABLE = "tick_data"

# ClickHouse async insert
INSERT_URL = (
    f"{CLICKHOUSE_URL}"
    f"?async_insert=1"
    f"&wait_for_async_insert=0"
    f"&query=INSERT INTO {CLICKHOUSE_DB}.{CLICKHOUSE_TABLE} FORMAT JSONEachRow"
)

# Realistic instrument pool
INSTRUMENTS = [
    # Crypto
    {"symbol": "BTC/USD", "exchange": "CRYPTO", "base_price": 67500, "volatility": 0.02},
    {"symbol": "ETH/USD", "exchange": "CRYPTO", "base_price": 3500, "volatility": 0.025},
    {"symbol": "SOL/USD", "exchange": "CRYPTO", "base_price": 145, "volatility": 0.03},
    # Indian equities
    {"symbol": "RELIANCE", "exchange": "NSE", "base_price": 2850, "volatility": 0.008},
    {"symbol": "TCS", "exchange": "NSE", "base_price": 4100, "volatility": 0.007},
    {"symbol": "HDFCBANK", "exchange": "NSE", "base_price": 1680, "volatility": 0.009},
    {"symbol": "INFY", "exchange": "NSE", "base_price": 1520, "volatility": 0.01},
    {"symbol": "ICICIBANK", "exchange": "NSE", "base_price": 1150, "volatility": 0.01},
    # US equities
    {"symbol": "AAPL", "exchange": "NSE", "base_price": 210, "volatility": 0.012},
    {"symbol": "TSLA", "exchange": "NSE", "base_price": 245, "volatility": 0.02},
    {"symbol": "GOOGL", "exchange": "NSE", "base_price": 175, "volatility": 0.011},
    # Commodities
    {"symbol": "GOLD", "exchange": "MCX", "base_price": 2350, "volatility": 0.005},
    {"symbol": "SILVER", "exchange": "MCX", "base_price": 28, "volatility": 0.008},
    {"symbol": "CRUDEOIL", "exchange": "MCX", "base_price": 78, "volatility": 0.015},
    # European equities
    {"symbol": "SAP.DE", "exchange": "NSE", "base_price": 180, "volatility": 0.01},
    {"symbol": "SIE.DE", "exchange": "NSE", "base_price": 145, "volatility": 0.009},
]

# Maintain running price for each instrument
prices = {inst["symbol"]: inst["base_price"] for inst in INSTRUMENTS}

# Simulated ticks per minute per symbol (affects OHLC variation)
TICKS_PER_SYMBOL_PER_MIN = 1000


def generate_tick(symbol: str, base_price: float, volatility: float) -> float:
    """Generate a single tick price via random walk."""
    delta = prices[symbol] * random.gauss(0, volatility)
    prices[symbol] = max(prices[symbol] + delta, base_price * 0.1)
    return prices[symbol]


def generate_candle(symbol: str, exchange: str, base_price: float, volatility: float) -> dict:
    """Simulate ticks for one minute and return an OHLCV candle."""
    ticks = [generate_tick(symbol, base_price, volatility) for _ in range(TICKS_PER_SYMBOL_PER_MIN)]

    open_price = ticks[0]
    high_price = max(ticks)
    low_price = min(ticks)
    close_price = ticks[-1]
    volume = sum(
        random.choice([
            random.randint(1, 100),      # retail
            random.randint(100, 1000),   # HNI
            random.randint(1000, 10000), # institutional
        ])
        for _ in ticks
    )

    # Use Asia/Kolkata timezone — matches the ClickHouse column's DateTime64 timezone
    IST = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(IST)
    # Round down to the nearest minute for the candle timestamp
    ts = now.replace(second=0, microsecond=0)

    return {
        "symbol": symbol,
        "exchange": exchange,
        "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
        "open": round(open_price, 2),
        "high": round(high_price, 2),
        "low": round(low_price, 2),
        "close": round(close_price, 2),
        "volume": volume,
    }


def main():
    logger.info("🚀 Starting OHLCV candle simulator — %d symbols, 1-min candles to ClickHouse", len(INSTRUMENTS))

    total_candles = 0
    next_minute = math.ceil(time.time() / 60) * 60

    try:
        while True:
            # Sleep until the start of the next minute
            now = time.time()
            sleep_seconds = next_minute - now
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)

            # Generate one candle per symbol for this minute
            candles = []
            for inst in INSTRUMENTS:
                candle = generate_candle(
                    symbol=inst["symbol"],
                    exchange=inst["exchange"],
                    base_price=inst["base_price"],
                    volatility=inst["volatility"],
                )
                candles.append(candle)

            # Batch insert all candles for this minute
            for candle in candles:
                try:
                    requests.post(
                        INSERT_URL,
                        data=json.dumps(candle),
                        auth=("default", "admin"),
                        timeout=5,
                    )
                except Exception as e:
                    logger.error("❌ Insert failed: %s | symbol: %s", e, candle["symbol"])

            total_candles += len(candles)
            logger.info(
                "📊 Inserted %d candles at %s (total: %d)",
                len(candles),
                candles[0]["timestamp"],
                total_candles,
            )

            next_minute += 60

    except KeyboardInterrupt:
        logger.info("🛑 Simulator stopped")
    finally:
        logger.info("Total candles sent: %d", total_candles)


if __name__ == "__main__":
    main()