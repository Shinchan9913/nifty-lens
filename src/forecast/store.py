"""ClickHouse read/write helpers for the forecasting pipeline (synchronous).

The pipeline runs as a batch script, so these use blocking ``requests``. The API
layer reads the same tables through the existing async ``agents.clickhouse.query``.
"""
import json

import requests

CLICKHOUSE_URL = "http://localhost:8123"
AUTH = ("default", "admin")


def query(sql: str) -> list[dict]:
    """Run a read query, return rows as dicts."""
    resp = requests.post(
        CLICKHOUSE_URL, data=sql.strip() + "\nFORMAT JSON",
        params={"database": "default"}, auth=AUTH, timeout=120,
    )
    resp.raise_for_status()
    text = resp.text.strip()
    return json.loads(text).get("data", []) if text else []


def insert(table: str, rows: list[dict]) -> None:
    """Bulk-insert dict rows via JSONEachRow."""
    if not rows:
        return
    payload = "\n".join(json.dumps(r) for r in rows)
    resp = requests.post(
        f"{CLICKHOUSE_URL}?query=" + requests.utils.quote(f"INSERT INTO default.{table} FORMAT JSONEachRow"),
        data=payload, auth=AUTH, timeout=120,
    )
    resp.raise_for_status()


def latest_run_id() -> str | None:
    rows = query("SELECT run_id FROM forecast_runs ORDER BY created_at DESC LIMIT 1")
    return rows[0]["run_id"] if rows else None
