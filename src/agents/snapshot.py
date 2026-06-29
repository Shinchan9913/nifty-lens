"""Point-in-time snapshot anchor — the thing that makes a run honest and reproducible.

Every analysis run freezes ONE timestamp ``T`` ("as of now") at the start. From then on,
all data reads see the market exactly as it stood at ``T``:

  * no row newer than ``T`` is ever read  -> no lookahead bias (the classic backtest sin),
  * the same question at the same ``T`` yields the same data -> reproducible.

``T`` lives in a ``ContextVar`` set once per run by the orchestrator. The ClickHouse tools
never hard-code "now"; they ask this module for it via :func:`now_expr` / :func:`asof_filter`,
so no single query can forget the filter — the discipline is centralised here, not copied
into every tool.

Live mode (no anchor set — e.g. the real-time dashboard endpoints) falls back to the live
``max(...)``, preserving the original behaviour. The whole module is pure string-building,
so it unit-tests without a database.
"""
from contextvars import ContextVar

# ISO 'YYYY-MM-DD HH:MM:SS' string while a run is anchored; "" means live mode.
_anchor: ContextVar[str] = ContextVar("snapshot_anchor", default="")


def set_anchor(ts: str) -> None:
    """Freeze the run's clock at ``ts`` (an ISO 'YYYY-MM-DD HH:MM:SS' string)."""
    _anchor.set((ts or "").strip())


def get_anchor() -> str:
    """The current frozen anchor, or "" if the run is live (unanchored)."""
    return _anchor.get()


def clear_anchor() -> None:
    """Drop back to live mode (used after a run, and by always-live endpoints)."""
    _anchor.set("")


def _literal(col: str, ts: str) -> str:
    """A ClickHouse datetime/date literal for ``ts`` on a column of type ``col``."""
    return f"toDate(toDateTime('{ts}'))" if col == "date" else f"toDateTime('{ts}')"


def now_expr(col: str = "timestamp", table: str = "tick_data", where: str = "") -> str:
    """SQL expression standing in for "now".

    Anchored: the frozen literal ``T`` (narrowed to a date for ``date`` columns).
    Live: ``(SELECT max(col) FROM table [WHERE where])`` — the original moving anchor.
    """
    ts = _anchor.get()
    if ts:
        return _literal(col, ts)
    clause = f" WHERE {where}" if where else ""
    return f"(SELECT max({col}) FROM {table}{clause})"


def asof_filter(col: str = "timestamp") -> str:
    """Upper-bound clause that excludes any row after the anchor; "" in live mode.

    Prepended with ``AND`` so it slots onto an existing ``WHERE``. This is the half that
    actually blocks future rows — ``now_expr`` only anchors the window's *start*.
    """
    ts = _anchor.get()
    if not ts:
        return ""
    return f" AND {col} <= {_literal(col, ts)}"
