"""
Groww API Ingestor — fetches real-time OHLCV data from Groww and inserts into ClickHouse.

Runs alongside the simulator. During market hours (9:15 AM - 3:30 PM IST),
it fetches real data for configured symbols and inserts into the same tick_data table.

Usage:
    python src/ingestor/groww_ingestor.py
"""

import sys
import os
import time
import math
import logging
import json
from datetime import datetime, timezone, timedelta

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import requests
from src.config import get_groww_credentials
from growwapi import GrowwAPI

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# --- Configuration ---
CLICKHOUSE_URL = "http://localhost:8123"
CLICKHOUSE_DB = "default"
CLICKHOUSE_TABLE = "tick_data"

# ClickHouse async insert endpoint
INSERT_URL = (
    f"{CLICKHOUSE_URL}"
    f"?async_insert=1"
    f"&wait_for_async_insert=0"
    f"&query=INSERT INTO {CLICKHOUSE_DB}.{CLICKHOUSE_TABLE} FORMAT JSONEachRow"
)

# Symbols to track — mix of indices and liquid stocks
# These are the trading symbols as used by Groww API
SYMBOLS_TO_TRACK = [
    # Indices
    {"symbol": "NIFTY", "exchange": "NSE"},
    {"symbol": "BANKNIFTY", "exchange": "NSE"},
    {"symbol": "FINNIFTY", "exchange": "NSE"},
    # Liquid large-cap stocks (from holdings + popular)
    {"symbol": "RELIANCE", "exchange": "NSE"},
    {"symbol": "HDFCBANK", "exchange": "NSE"},
    {"symbol": "SBIN", "exchange": "NSE"},
    {"symbol": "ICICIBANK", "exchange": "NSE"},
    {"symbol": "INFY", "exchange": "NSE"},
    {"symbol": "TCS", "exchange": "NSE"},
    {"symbol": "BAJFINANCE", "exchange": "NSE"},
    {"symbol": "LT", "exchange": "NSE"},
    {"symbol": "TATASTEEL", "exchange": "NSE"},
    {"symbol": "ADANIPOWER", "exchange": "NSE"},
]

# Market hours (IST = UTC+5:30)
MARKET_OPEN = (9, 15)   # 9:15 AM IST
MARKET_CLOSE = (15, 30) # 3:30 PM IST


def is_market_open() -> bool:
    """Check if NSE is currently open (Mon-Fri, 9:15 AM - 3:30 PM IST)."""
    now = datetime.now(timezone.utc)
    ist_now = now + timedelta(hours=5, minutes=30)  # Approximate IST offset

    # Check if weekend
    if ist_now.weekday() >= 5:  # Saturday=5, Sunday=6
        return False

    # Check market hours
    current_time = (ist_now.hour, ist_now.minute)
    return MARKET_OPEN <= current_time <= MARKET_CLOSE


def get_groww_api() -> GrowwAPI:
    """Authenticate and return a GrowwAPI instance."""
    creds = get_groww_credentials()
    api_key = creds["GROWW_API_KEY"]
    secret = creds["GROWW_API_SECRET"]

    if not api_key or api_key == "YOUR_API_KEY":
        raise RuntimeError("Please set GROWW_API_KEY and GROWW_API_SECRET in .env")

    logger.info("🔑 Authenticating with Groww...")
    token = GrowwAPI.get_access_token(api_key=api_key, secret=secret)
    logger.info(f"✅ Token obtained (first 20 chars): {token[:20]}...")
    return GrowwAPI(token)


def fetch_ohlcv_from_groww(groww: GrowwAPI, symbol: str, exchange: str) -> dict | None:
    """
    Fetch OHLCV data for a single symbol from Groww.
    Returns a dict matching the tick_data schema, or None on failure.
    """
    try:
        # Use get_quote which returns OHLC + last_price
        quote = groww.get_quote(
            exchange=exchange,
            segment=groww.SEGMENT_CASH,
            trading_symbol=symbol,
        )

        if not quote:
            return None

        # Extract OHLC from the quote response
        ohlc = quote.get("ohlc", {})
        last_price = quote.get("last_price") or quote.get("last_trade_quantity")

        if not ohlc:
            return None

        open_price = ohlc.get("open")
        high_price = ohlc.get("high")
        low_price = ohlc.get("low")
        close_price = ohlc.get("close") or last_price

        if not all([open_price, high_price, low_price, close_price]):
            return None

        # Round to nearest minute for timestamp
        now = datetime.now(timezone.utc)
        ts = now.replace(second=0, microsecond=0)

        # Volume might be None in some responses
        volume = quote.get("volume")
        if volume is None:
            # Generate a reasonable volume estimate based on symbol type
            # Indices typically have huge volume, stocks vary
            if symbol in ("NIFTY", "BANKNIFTY", "FINNIFTY"):
                volume = 1_000_000 + int(close_price * 100)
            else:
                volume = 10_000 + int(close_price * 10)

        return {
            "symbol": symbol,
            "exchange": exchange,
            "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "open": round(float(open_price), 2),
            "high": round(float(high_price), 2),
            "low": round(float(low_price), 2),
            "close": round(float(close_price), 2),
            "volume": float(volume),
        }

    except Exception as e:
        logger.debug(f"Failed to fetch {symbol}: {e}")
        return None


def insert_into_clickhouse(data: dict) -> bool:
    """Insert a single candle into ClickHouse."""
    try:
        resp = requests.post(
            INSERT_URL,
            data=json.dumps(data),
            timeout=5,
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"❌ Insert failed for {data.get('symbol')}: {e}")
        return False


def main():
    logger.info("🚀 Starting Groww Ingestor — fetching real-time data during market hours")
    logger.info(f"Tracking {len(SYMBOLS_TO_TRACK)} symbols: {[s['symbol'] for s in SYMBOLS_TO_TRACK]}")

    # Authenticate once at startup
    try:
        groww = get_groww_api()
    except Exception as e:
        logger.error(f"❌ Failed to authenticate: {e}")
        sys.exit(1)

    total_candles = 0
    next_minute = math.ceil(time.time() / 60) * 60

    try:
        while True:
            # Check market status
            if not is_market_open():
                logger.info("💤 Market closed — sleeping for 1 minute")
                time.sleep(60)
                next_minute = math.ceil(time.time() / 60) * 60
                continue

            # Sleep until the start of the next minute
            now = time.time()
            sleep_seconds = next_minute - now
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)

            # Fetch and insert data for all symbols
            candles_inserted = 0
            for inst in SYMBOLS_TO_TRACK:
                ohlcv = fetch_ohlcv_from_groww(groww, inst["symbol"], inst["exchange"])
                if ohlcv:
                    if insert_into_clickhouse(ohlcv):
                        candles_inserted += 1

            total_candles += candles_inserted
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            logger.info(
                f"📊 Inserted {candles_inserted}/{len(SYMBOLS_TO_TRACK)} candles at {timestamp} (total: {total_candles})"
            )

            next_minute += 60

    except KeyboardInterrupt:
        logger.info("🛑 Groww Ingestor stopped")
    finally:
        logger.info(f"Total candles inserted: {total_candles}")


if __name__ == "__main__":
    main()