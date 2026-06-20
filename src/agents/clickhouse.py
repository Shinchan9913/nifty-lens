"""Thin async wrapper around the ClickHouse HTTP API.

Mirrors the auth/host used by the FastAPI read endpoints, but returns rows as
dicts (via ``FORMAT JSON``) so the agent tools can hand structured data to Claude.
Blocking ``requests`` calls are pushed to a thread so the event loop stays free.
"""
import asyncio
import json

import requests

CLICKHOUSE_URL = "http://localhost:8123"
AUTH = ("default", "admin")


def _run_sql(sql: str) -> list[dict]:
    resp = requests.post(
        CLICKHOUSE_URL,
        data=sql.strip() + "\nFORMAT JSON",
        params={"database": "default"},
        auth=AUTH,
        timeout=30,
    )
    resp.raise_for_status()
    text = resp.text.strip()
    if not text:
        return []
    return json.loads(text).get("data", [])


async def query(sql: str) -> list[dict]:
    """Run a read query and return rows as a list of dicts."""
    return await asyncio.to_thread(_run_sql, sql)
