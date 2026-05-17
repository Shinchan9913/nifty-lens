"""
FastAPI Backend — serves ClickHouse aggregation queries to the React dashboard.

Endpoints:
  GET /api/volatile?minutes=5&limit=10  — Top volatile assets
  GET /api/volume?minutes=5              — Volume by region/asset class
  GET /api/dashboard/summary             — Overall dashboard stats
"""
import logging
from typing import Optional
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
    resp = requests.post(CLICKHOUSE_URL, data=sql, params={"database": "default"}, timeout=30)
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
    """Top N most volatile assets in the last X minutes."""
    sql = f"""
    SELECT
        symbol,
        region,
        asset_class,
        count() AS trade_count,
        max(price) - min(price) AS price_range,
        round(avg(price), 2) AS avg_price
    FROM trades_raw
    WHERE timestamp >= now() - INTERVAL {minutes} MINUTE
    GROUP BY symbol, region, asset_class
    ORDER BY price_range DESC
    LIMIT {limit}
    """
    rows = query_clickhouse(sql)
    results = []
    for row in rows:
        results.append({
            "symbol": row[0],
            "region": row[1],
            "asset_class": row[2],
            "trade_count": int(row[3]),
            "price_range": float(row[4]),
            "avg_price": float(row[5]),
        })
    return {"minutes": minutes, "assets": results}


@app.get("/api/volume")
def volume_by_region(
    minutes: int = Query(5, description="Lookback window in minutes"),
):
    """Trade volume grouped by region and asset class."""
    sql = f"""
    SELECT
        region,
        asset_class,
        count() AS trade_count,
        round(sum(price * quantity), 2) AS total_volume
    FROM trades_raw
    WHERE timestamp >= now() - INTERVAL {minutes} MINUTE
    GROUP BY region, asset_class
    ORDER BY total_volume DESC
    """
    rows = query_clickhouse(sql)
    results = []
    for row in rows:
        results.append({
            "region": row[0],
            "asset_class": row[1],
            "trade_count": int(row[2]),
            "total_volume": float(row[3]),
        })
    return {"minutes": minutes, "data": results}


@app.get("/api/dashboard/summary")
def dashboard_summary():
    """High-level dashboard stats."""
    sql = """
    SELECT
        count() AS total_trades,
        countDistinct(symbol) AS unique_assets,
        countDistinct(region) AS regions_active
    FROM trades_raw
    WHERE timestamp >= now() - INTERVAL 1 MINUTE
    """
    rows = query_clickhouse(sql)
    stats = {"total_trades": 0, "unique_assets": 0, "regions_active": 0}
    if rows:
        stats = {
            "total_trades": int(rows[0][0]),
            "unique_assets": int(rows[0][1]),
            "regions_active": int(rows[0][2]),
        }
    return stats


@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}