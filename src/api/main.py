"""
FastAPI Backend — serves ClickHouse OHLCV queries to the React dashboard.

Endpoints:
  GET /api/volatile?minutes=5&limit=10  — Top movers by (high-low)/open %
  GET /api/volume?minutes=5              — Volume by exchange
  GET /api/dashboard/summary             — Overall dashboard stats
"""
import asyncio
import json
import logging
import re
from datetime import datetime, timezone

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import requests

from src.agents.bus import EventBus
from src.agents.orchestrator import run_analysis
from src.agents.team import AGENT_META

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
    WHERE timestamp >= (SELECT max(timestamp) FROM tick_data) - INTERVAL {minutes} MINUTE
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
    WHERE timestamp >= (SELECT max(timestamp) FROM tick_data) - INTERVAL {minutes} MINUTE
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
        count() AS total_candles,
        toString(max(timestamp)) AS as_of
    FROM tick_data
    WHERE timestamp >= (SELECT max(timestamp) FROM tick_data) - INTERVAL 10 MINUTE
    """
    rows = query_clickhouse(sql)
    stats = {"total_symbols": 0, "total_exchanges": 0, "total_candles": 0, "as_of": None}
    if rows and rows[0][0]:
        stats = {
            "total_symbols": int(rows[0][0]),
            "total_exchanges": int(rows[0][1]),
            "total_candles": int(rows[0][2]),
            "as_of": rows[0][3],
        }
    return stats


@app.get("/api/candles")
def candles(
    symbol: str = Query(..., description="Symbol to fetch a price series for"),
    minutes: int = Query(45, description="Lookback window in minutes"),
):
    """Recent close-price series for one symbol — powers the price line chart."""
    safe = re.sub(r"[^A-Za-z0-9_./-]", "", symbol)[:32]
    sql = f"""
    SELECT toString(timestamp) AS t, close, volume
    FROM tick_data
    WHERE symbol = '{safe}'
      AND timestamp >= (SELECT max(timestamp) FROM tick_data WHERE symbol = '{safe}') - INTERVAL {int(minutes)} MINUTE
    ORDER BY timestamp
    """
    rows = query_clickhouse(sql)
    series = [{"time": r[0][11:16], "close": float(r[1]), "volume": float(r[2])} for r in rows]
    return {"symbol": symbol, "candles": series}


@app.get("/api/agents/meta")
def agents_meta():
    """Static info about each agent so the UI can render the cards (name, emoji, color)."""
    return {"agents": AGENT_META}


@app.get("/api/agents/stream")
async def agents_stream(
    query: str = Query(..., description="The market question to analyze"),
    depth: str = Query("balanced", description="Analysis depth: quick | balanced | deep"),
):
    """Run one multi-agent analysis and stream every step to the browser as SSE.

    Flow: make a per-run EventBus -> kick off run_analysis() as a background task
    (it pushes events onto the bus) -> drain the bus and yield each event in SSE
    format until the closing `None` sentinel arrives.
    """
    bus = EventBus()

    async def runner():
        try:
            await bus.emit("run_started", query=query, depth=depth)
            await run_analysis(query, bus, depth=depth)
        except Exception as exc:  # never let a crash hang the open connection
            logger.exception("Agent run failed")
            await bus.emit("error", message=str(exc))
        finally:
            await bus.emit("run_finished")
            await bus.close()  # puts the None sentinel on the queue

    async def event_stream():
        task = asyncio.create_task(runner())  # runs concurrently with this loop
        try:
            while True:
                event = await bus.queue.get()
                if event is None:  # sentinel: producer is finished
                    break
                yield f"data: {json.dumps(event, default=str)}\n\n"
        finally:
            task.cancel()  # if the browser disconnects, stop the run

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}