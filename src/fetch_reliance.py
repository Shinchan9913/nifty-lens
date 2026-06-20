"""
Simple script: fetch RELIANCE 1-minute candles from Groww API
and insert into ClickHouse (tick_data table).

Run:  source .venv/bin/activate && python src/fetch_reliance.py
"""
import sys
import logging
from datetime import datetime, timedelta

import requests

from src.config import get_groww_credentials
from growwapi import GrowwAPI
import pyotp

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

CLICKHOUSE_URL = "http://localhost:8123"


def get_groww_client():
    """Authenticate with Groww and return a GrowwAPI client."""
    creds = get_groww_credentials()
    api_key = creds["GROWW_API_KEY"]
    secret = creds["GROWW_API_SECRET"]

    if api_key == "YOUR_API_KEY" or not api_key:
        print("❌  ERROR: Update GROWW_API_KEY and GROWW_API_SECRET in .env")
        sys.exit(1)

    logger.info("🔑 Authenticating with Groww...")
    try:
        totp = pyotp.TOTP(secret)
        token = GrowwAPI.get_access_token(api_key=api_key, totp=totp.now())
    except Exception:
        token = GrowwAPI.get_access_token(api_key=api_key, secret=secret)

    logger.info("✅ Authenticated successfully")
    return GrowwAPI(token)


def insert_candle(symbol: str, exchange: str, candle: dict):
    """Insert a single 1-min candle into ClickHouse."""
    timestamp = candle.get("timestamp") or candle.get("dateTime") or candle.get("time")
    if not timestamp:
        logger.warning("⚠️  Candle missing timestamp, skipping")
        return False

    # The candle format from Groww: {"open": ..., "high": ..., ...}
    open_ = candle.get("open", 0)
    high = candle.get("high", 0)
    low = candle.get("low", 0)
    close = candle.get("close", 0) or candle.get("ltp", 0)
    volume = candle.get("volume", 0) or candle.get("vol", 0)

    # Convert timestamp to proper format
    if isinstance(timestamp, (int, float)):
        # epoch ms
        ts = datetime.fromtimestamp(timestamp / 1000).strftime("%Y-%m-%d %H:%M:%S")
    else:
        ts = str(timestamp)[:19]  # yyyy-MM-dd HH:mm:ss

    sql = f"""
    INSERT INTO tick_data (symbol, exchange, timestamp, open, high, low, close, volume)
    VALUES ('{symbol}', '{exchange}', '{ts}', {open_}, {high}, {low}, {close}, {volume})
    """
    try:
        resp = requests.post(CLICKHOUSE_URL, data=sql, params={"database": "default"}, timeout=10)
        resp.raise_for_status()
        return True
    except Exception as e:
        logger.error("❌ Insert failed: %s", e)
        return False


def main():
    groww = get_groww_client()

    # Fetch last 7 days of 1-minute candles for RELIANCE
    end = datetime.now()
    start = end - timedelta(days=7)
    symbol = "RELIANCE"
    exchange = "NSE"
    segment = "CASH"

    logger.info("📊 Fetching %s 1-min candles from %s to %s...", symbol, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))

    try:
        data = groww.get_historical_candles(
            exchange=exchange,
            segment=segment,
            groww_symbol=symbol,
            start_time=start.strftime("%Y-%m-%d 09:15:00"),
            end_time=end.strftime("%Y-%m-%d %H:%M:%S"),
            candle_interval="1minute",
        )
    except Exception as e:
        logger.error("❌ Failed to fetch data: %s", e)
        sys.exit(1)

    # The response structure — try common patterns
    candles = []
    if isinstance(data, dict):
        # Try known response keys
        for key in ["candles", "data", "results", "candleData", "candle_data"]:
            if key in data and isinstance(data[key], list):
                candles = data[key]
                break
        if not candles and "payload" in data:
            payload = data["payload"]
            if isinstance(payload, list):
                candles = payload
            elif isinstance(payload, dict):
                for key in ["candles", "data", "results"]:
                    if key in payload and isinstance(payload[key], list):
                        candles = payload[key]
                        break
        if not candles and "candle" in data:
            candles = [data["candle"]]
    elif isinstance(data, list):
        candles = data

    if not candles:
        logger.warning("⚠️  No candles found. Raw response: %s", str(data)[:500])
        sys.exit(0)

    logger.info("✅ Got %d candles", len(candles))

    # Insert all candles
    inserted = 0
    for candle in candles:
        if insert_candle(symbol, exchange, candle):
            inserted += 1

    logger.info("✅ Inserted %d / %d candles into ClickHouse", inserted, len(candles))

    # Show a quick verification
    count = requests.post(CLICKHOUSE_URL, data="SELECT count() FROM tick_data WHERE symbol = 'RELIANCE'", params={"database": "default"}, timeout=5)
    total = count.text.strip()
    logger.info("📊 Total RELIANCE rows in ClickHouse: %s", total)


if __name__ == "__main__":
    main()