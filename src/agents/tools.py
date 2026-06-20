"""ClickHouse-backed tools the specialist agents can call.

Each entry in ``TOOL_SCHEMAS`` is an Anthropic tool definition; ``HANDLERS`` maps
the same name to an async function that runs the query and returns plain data
(serialized to JSON before it goes back to the model).
"""
import asyncio
import re

from .clickhouse import query


def _safe_symbol(value) -> str:
    """Whitelist characters so a model-supplied symbol can't break out of the SQL."""
    return re.sub(r"[^A-Za-z0-9_./-]", "", str(value))[:32]


async def list_symbols(minutes: int = 10) -> list[dict]:
    return await query(
        f"""
        SELECT symbol, exchange, count() AS candles, round(avg(close), 2) AS avg_price
        FROM tick_data
        WHERE timestamp >= (SELECT max(timestamp) FROM tick_data) - INTERVAL {int(minutes)} MINUTE
        GROUP BY symbol, exchange
        ORDER BY candles DESC
        """
    )


async def get_candles(symbol: str, minutes: int = 15) -> list[dict]:
    sym = _safe_symbol(symbol)
    return await query(
        f"""
        SELECT toString(timestamp) AS time, open, high, low, close, volume
        FROM tick_data
        WHERE symbol = '{sym}'
          AND timestamp >= (SELECT max(timestamp) FROM tick_data WHERE symbol = '{sym}') - INTERVAL {int(minutes)} MINUTE
        ORDER BY timestamp
        """
    )


async def get_top_movers(minutes: int = 5, limit: int = 10) -> list[dict]:
    rows = await query(
        f"""
        SELECT
            symbol, exchange,
            argMin(open, timestamp) AS open,
            max(high) AS high,
            min(low) AS low,
            argMax(close, timestamp) AS close,
            sum(volume) AS volume
        FROM tick_data
        WHERE timestamp >= (SELECT max(timestamp) FROM tick_data) - INTERVAL {int(minutes)} MINUTE
        GROUP BY symbol, exchange
        ORDER BY (high - low) / open DESC
        LIMIT {int(limit)}
        """
    )
    for r in rows:
        open_price = r.get("open") or 1
        r["range_pct"] = round((r["high"] - r["low"]) / open_price * 100, 2)
        r["change_pct"] = round((r["close"] - open_price) / open_price * 100, 2)
    return rows


async def get_volume_by_exchange(minutes: int = 5) -> list[dict]:
    return await query(
        f"""
        SELECT exchange, count() AS candles, round(sum(volume), 2) AS total_volume
        FROM tick_data
        WHERE timestamp >= (SELECT max(timestamp) FROM tick_data) - INTERVAL {int(minutes)} MINUTE
        GROUP BY exchange
        ORDER BY total_volume DESC
        """
    )


def _web_search_sync(query_text: str, max_results: int = 5) -> list[dict]:
    from ddgs import DDGS

    with DDGS() as ddgs:
        return [
            {"title": r.get("title"), "url": r.get("href"), "snippet": r.get("body")}
            for r in ddgs.text(query_text, max_results=max_results)
        ]


async def web_search(query: str, max_results: int = 5) -> list[dict]:
    """Free, keyless web search via DuckDuckGo. Runs in a thread (the lib is blocking).

    This is a *client-side* tool: unlike Anthropic's hosted web search, we execute
    the search ourselves and hand the results back to the model — which is why it
    works the same across every OpenAI-compatible provider.
    """
    return await asyncio.to_thread(_web_search_sync, query, int(max_results))


TOOL_SCHEMAS: dict[str, dict] = {
    "list_symbols": {
        "name": "list_symbols",
        "description": (
            "List every symbol currently in the live market database, with candle "
            "count and average price over the last N minutes. Call this first to "
            "discover what is tradeable before drilling into specific symbols."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "minutes": {"type": "integer", "description": "Lookback window in minutes (default 10)."}
            },
            "required": [],
        },
    },
    "get_candles": {
        "name": "get_candles",
        "description": "Get the recent 1-minute OHLCV candles for one symbol over the last N minutes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Exact symbol, e.g. 'RELIANCE' or 'BTC/USD'."},
                "minutes": {"type": "integer", "description": "Lookback window in minutes (default 15)."},
            },
            "required": ["symbol"],
        },
    },
    "get_top_movers": {
        "name": "get_top_movers",
        "description": (
            "Rank the most volatile symbols over the last N minutes by intraday range "
            "((high-low)/open). Returns open/high/low/close, total volume, range_pct and change_pct."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "minutes": {"type": "integer", "description": "Lookback window in minutes (default 5)."},
                "limit": {"type": "integer", "description": "Number of symbols to return (default 10)."},
            },
            "required": [],
        },
    },
    "get_volume_by_exchange": {
        "name": "get_volume_by_exchange",
        "description": "Aggregate traded volume and candle counts grouped by exchange over the last N minutes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "minutes": {"type": "integer", "description": "Lookback window in minutes (default 5)."}
            },
            "required": [],
        },
    },
    "web_search": {
        "name": "web_search",
        "description": (
            "Search the web (DuckDuckGo) for recent news, events or sentiment. "
            "Returns a list of {title, url, snippet}. Use specific queries including "
            "the symbol or company name and words like 'news' or 'today'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query."},
                "max_results": {"type": "integer", "description": "How many results (default 5)."},
            },
            "required": ["query"],
        },
    },
}

HANDLERS = {
    "list_symbols": list_symbols,
    "get_candles": get_candles,
    "get_top_movers": get_top_movers,
    "get_volume_by_exchange": get_volume_by_exchange,
    "web_search": web_search,
}


def summarize_result(result) -> str:
    """One-line summary of a tool result for the UI timeline."""
    if isinstance(result, list):
        return f"{len(result)} row(s)"
    return str(result)[:120]
