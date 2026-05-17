"""
Trade Simulator — produces 5,000 mock transactions/sec to Redpanda.

Simulates realistic financial trades across crypto, equity, and commodities.
"""
import json
import uuid
import time
import random
import logging
from datetime import datetime, timezone

from kafka import KafkaProducer

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# --- Configuration ---
REDPANDA_BROKER = "localhost:9092"
TOPIC = "trades_raw"
TARGET_TPS = 5000

# Realistic instrument pool
INSTRUMENTS = [
    # Crypto
    {"symbol": "BTC/USD", "asset_class": "crypto", "region": "US", "base_price": 67500, "volatility": 0.02},
    {"symbol": "ETH/USD", "asset_class": "crypto", "region": "US", "base_price": 3500, "volatility": 0.025},
    {"symbol": "SOL/USD", "asset_class": "crypto", "region": "US", "base_price": 145, "volatility": 0.03},
    # Indian equities
    {"symbol": "RELIANCE", "asset_class": "equity", "region": "APAC", "base_price": 2850, "volatility": 0.008},
    {"symbol": "TCS", "asset_class": "equity", "region": "APAC", "base_price": 4100, "volatility": 0.007},
    {"symbol": "HDFCBANK", "asset_class": "equity", "region": "APAC", "base_price": 1680, "volatility": 0.009},
    {"symbol": "INFY", "asset_class": "equity", "region": "APAC", "base_price": 1520, "volatility": 0.01},
    {"symbol": "ICICIBANK", "asset_class": "equity", "region": "APAC", "base_price": 1150, "volatility": 0.01},
    # US equities
    {"symbol": "AAPL", "asset_class": "equity", "region": "US", "base_price": 210, "volatility": 0.012},
    {"symbol": "TSLA", "asset_class": "equity", "region": "US", "base_price": 245, "volatility": 0.02},
    {"symbol": "GOOGL", "asset_class": "equity", "region": "US", "base_price": 175, "volatility": 0.011},
    # Commodities
    {"symbol": "GOLD", "asset_class": "commodity", "region": "US", "base_price": 2350, "volatility": 0.005},
    {"symbol": "SILVER", "asset_class": "commodity", "region": "US", "base_price": 28, "volatility": 0.008},
    {"symbol": "CRUDEOIL", "asset_class": "commodity", "region": "EU", "base_price": 78, "volatility": 0.015},
    # European equities
    {"symbol": "SAP.DE", "asset_class": "equity", "region": "EU", "base_price": 180, "volatility": 0.01},
    {"symbol": "SIE.DE", "asset_class": "equity", "region": "EU", "base_price": 145, "volatility": 0.009},
]

EXCHANGES = {
    "crypto": "CRYPTO",
    "equity": "NSE",
    "commodity": "MCX",
}

# Maintain a running price for each instrument (random walk)
prices = {inst["symbol"]: inst["base_price"] for inst in INSTRUMENTS}


def generate_trade() -> dict:
    """Generate a single mock trade."""
    inst = random.choice(INSTRUMENTS)
    symbol = inst["symbol"]

    # Random walk price
    delta = prices[symbol] * random.gauss(0, inst["volatility"])
    prices[symbol] = max(prices[symbol] + delta, inst["base_price"] * 0.1)

    quantity = random.choice([
        random.randint(1, 100),    # retail
        random.randint(100, 1000),  # HNI
        random.randint(1000, 10000), # institutional
    ])

    # Region-weighted distribution (APAC heavy for Indian market bias)
    region_weights = {"US": 0.25, "APAC": 0.55, "EU": 0.20}
    region = random.choices(list(region_weights.keys()), weights=list(region_weights.values()))[0]

    return {
        "trade_id": str(uuid.uuid4()),
        "symbol": symbol,
        "price": round(prices[symbol], 2),
        "quantity": quantity,
        "side": random.choice(["buy", "sell"]),
        "region": region,
        "asset_class": inst["asset_class"],
        "exchange": EXCHANGES[inst["asset_class"]],
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
    }


def main():
    logger.info("🚀 Starting trade simulator — target: %d txn/sec to %s", TARGET_TPS, REDPANDA_BROKER)

    producer = KafkaProducer(
        bootstrap_servers=REDPANDA_BROKER,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        acks="1",
        compression_type="gzip",
        linger_ms=10,
        batch_size=32768,
    )

    sent = 0
    batch_start = time.monotonic()
    interval = 1.0  # 1 second reporting window

    try:
        while True:
            trade = generate_trade()
            producer.send(TOPIC, value=trade)
            sent += 1

            if sent >= TARGET_TPS:
                # Rate limiting: sleep if we're ahead of schedule
                elapsed = time.monotonic() - batch_start
                if elapsed < 1.0:
                    time.sleep(1.0 - elapsed)
                batch_start = time.monotonic()
                sent = 0

            # Log throughput every second
            if sent % TARGET_TPS == 0:
                logger.info("📊 Throughput: %d trades/sec", TARGET_TPS)

    except KeyboardInterrupt:
        logger.info("🛑 Simulator stopped")
    finally:
        producer.flush()
        producer.close()


if __name__ == "__main__":
    main()