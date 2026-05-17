"""
Consumer — reads trades from Redpanda and batch-inserts into ClickHouse.

Consumes the `trades_raw` topic and writes to ClickHouse in batches
for high-throughput ingestion.
"""
import json
import time
import logging
from typing import List
from datetime import datetime

from kafka import KafkaConsumer
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# --- Configuration ---
REDPANDA_BROKER = "localhost:9092"
TOPIC = "trades_raw"
GROUP_ID = "clickhouse-consumer"

CLICKHOUSE_HOST = "http://localhost:8123"
CLICKHOUSE_DB = "default"
CLICKHOUSE_TABLE = "trades_raw"

BATCH_SIZE = 5000          # rows per batch insert
FLUSH_INTERVAL = 0.5       # max wait before flushing (seconds)


def insert_batch(rows: List[dict]) -> None:
    """Insert a batch of trades into ClickHouse via HTTP API."""
    if not rows:
        return

    # Build ClickHouse values string
    values = []
    for row in rows:
        trade_id = row["trade_id"]
        symbol = row["symbol"].replace("'", "\\'")
        price = row["price"]
        quantity = row["quantity"]
        side = row["side"]
        region = row["region"].replace("'", "\\'")
        asset_class = row["asset_class"].replace("'", "\\'")
        exchange = row["exchange"].replace("'", "\\'")
        timestamp = row["timestamp"]

        values.append(
            f"('{trade_id}', '{symbol}', {price}, {quantity}, '{side}', "
            f"'{region}', '{asset_class}', '{exchange}', '{timestamp}')"
        )

    query = (
        f"INSERT INTO {CLICKHOUSE_DB}.{CLICKHOUSE_TABLE} "
        f"(trade_id, symbol, price, quantity, side, region, asset_class, exchange, timestamp) "
        f"VALUES {', '.join(values)}"
    )

    try:
        resp = requests.post(
            CLICKHOUSE_HOST,
            data=query,
            params={"database": CLICKHOUSE_DB},
            timeout=30,
        )
        resp.raise_for_status()
        logger.debug("✅ Inserted %d rows", len(rows))
    except Exception as e:
        logger.error("❌ Insert failed: %s | sample: %s", e, rows[0] if rows else "N/A")


def main():
    logger.info("🚀 Starting ClickHouse consumer — topic: %s", TOPIC)

    consumer = KafkaConsumer(
        TOPIC,
        bootstrap_servers=REDPANDA_BROKER,
        group_id=GROUP_ID,
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        auto_offset_reset="latest",
        enable_auto_commit=False,
        max_poll_records=BATCH_SIZE,
    )

    batch: List[dict] = []
    last_flush = time.monotonic()
    total_inserted = 0

    try:
        for message in consumer:
            batch.append(message.value)

            if len(batch) >= BATCH_SIZE or (time.monotonic() - last_flush >= FLUSH_INTERVAL and batch):
                insert_batch(batch)
                total_inserted += len(batch)
                logger.info("📊 Inserted %d rows (total: %d)", len(batch), total_inserted)
                consumer.commit()
                batch = []
                last_flush = time.monotonic()

    except KeyboardInterrupt:
        logger.info("🛑 Consumer stopped")
        if batch:
            insert_batch(batch)
            total_inserted += len(batch)
            logger.info("📊 Final flush: %d rows (total: %d)", len(batch), total_inserted)
            consumer.commit()
    finally:
        consumer.close()


if __name__ == "__main__":
    main()