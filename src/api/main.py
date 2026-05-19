"""
FastAPI Backend — serves ClickHouse OHLCV queries to the React dashboard.

Endpoints:
  GET /api/volatile?minutes=5&limit=10  — Top movers by (high-low)/open %
  GET /api/volume?minutes=5              — Volume by exchange
  GET /api/dashboard/summary             — Overall dashboard stats
"""
import logging
from datetime import datetime, timezone

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="FinTech Analytics API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

CLICKHOUSE_URL = "http://localhost:8123"


def query_clickhouse(sql: str) -> list:
    """Execute a ClickHouse query and return rows as dicts."""
    resp = requests.post(CLICKHOUSE_URL, data=sql, params={"database": "default"}, auth=("default", "admin"), timeout=30)
    if resp.status_code != 200:
        logger.error("ClickHouse returned %d: %s", resp.status_code, resp.text)
    resp.raise_for_status()
    if not resp.text.strip():
        return []
    rows = []
    for line in resp.text.strip().split("\n"):
        parts = line.split("\t")
        rows.append(parts)
    return rows


@app.get("/api/volatile")
def top_volatile(
    minutes: int = Query(5, description="Lookback window in minutes"),
    limit: int = Query(10, description="Number of results"),
):
    """Top N most volatile assets in the last X minutes by (high-low)/open."""
    sql = f"""
    SELECT
        symbol,
        exchange,
        argMax(open, timestamp) AS open,
        max(high) AS high,
        min(low) AS low,
        argMax(close, timestamp) AS close,
        sum(volume) AS total_volume
    FROM tick_data
    WHERE timestamp >= now() - INTERVAL {minutes} MINUTE
    GROUP BY symbol, exchange
    ORDER BY (high - low) / open DESC
    LIMIT {limit}
    """
    rows = query_clickhouse(sql)
    results = []
    for row in rows:
        open_price = float(row[2])
        high_price = float(row[3])
        low_price = float(row[4])
        close_price = float(row[5])
        change_pct = round(((close_price - open_price) / open_price) * 100, 2)
        range_pct = round(((high_price - low_price) / open_price) * 100, 2)
        results.append({
            "symbol": row[0],
            "exchange": row[1],
            "open": open_price,
            "high": high_price,
            "low": low_price,
            "close": close_price,
            "change_pct": change_pct,
            "range_pct": range_pct,
            "total_volume": float(row[6]),
        })
    return {"minutes": minutes, "assets": results}


@app.get("/api/volume")
def volume_by_exchange(
    minutes: int = Query(5, description="Lookback window in minutes"),
):
    """Trade volume grouped by exchange."""
    sql = f"""
    SELECT
        exchange,
        count() AS candle_count,
        round(sum(volume), 2) AS total_volume
    FROM tick_data
    WHERE timestamp >= now() - INTERVAL {minutes} MINUTE
    GROUP BY exchange
    ORDER BY total_volume DESC
    """
    rows = query_clickhouse(sql)
    results = []
    for row in rows:
        results.append({
            "exchange": row[0],
            "candle_count": int(row[1]),
            "total_volume": float(row[2]),
        })
    return {"minutes": minutes, "data": results}


@app.get("/api/dashboard/summary")
def dashboard_summary():
    """High-level dashboard stats from tick_data."""
    sql = """
    SELECT
        count(DISTINCT symbol) AS total_symbols,
        count(DISTINCT exchange) AS total_exchanges,
        count() AS total_candles
    FROM tick_data
    WHERE timestamp >= now() - INTERVAL 10 MINUTE
    """
    rows = query_clickhouse(sql)
    stats = {"total_symbols": 0, "total_exchanges": 0, "total_candles": 0}
    if rows:
        stats = {
            "total_symbols": int(rows[0][0]),
            "total_exchanges": int(rows[0][1]),
            "total_candles": int(rows[0][2]),
        }
    return stats


@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}