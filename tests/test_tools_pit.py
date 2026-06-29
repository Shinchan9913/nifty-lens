"""Point-in-time wiring: the ClickHouse tools must read as-of the frozen anchor.

`test_snapshot.py` pins the SQL the helpers *emit*; this pins that the tools actually
*use* them. We monkeypatch `query` to capture the SQL each tool builds and assert that:

  * live mode (no anchor) reproduces the original moving `max(...)` and adds no upper bound,
  * anchored mode freezes the literal `T` AND bounds every read `<= T` (no lookahead).

No ClickHouse needed — the captured SQL string is the contract.
"""
import pytest

from src.agents import tools
from src.agents.snapshot import clear_anchor, set_anchor

T = "2026-06-23 23:04:00"


@pytest.fixture
def captured(monkeypatch):
    """Replace the tools' `query` with a stub that records the SQL and returns no rows."""
    seen: list[str] = []

    async def fake_query(sql: str):
        seen.append(sql)
        return []

    monkeypatch.setattr(tools, "query", fake_query)
    return seen


@pytest.fixture(autouse=True)
def _reset():
    clear_anchor()
    yield
    clear_anchor()


# --- live mode: original behaviour preserved ----------------------------------
async def test_live_list_symbols_uses_moving_max(captured):
    await tools.list_symbols()
    sql = captured[-1]
    assert "(SELECT max(timestamp) FROM tick_data)" in sql
    assert "<=" not in sql  # no upper bound when live


async def test_live_get_candles_keeps_per_symbol_max(captured):
    await tools.get_candles("NVDA")
    sql = captured[-1]
    assert "(SELECT max(timestamp) FROM tick_data WHERE symbol = 'NVDA')" in sql
    assert "<=" not in sql


async def test_live_get_history_uses_date_max(captured):
    await tools.get_history("NVDA")
    sql = captured[-1]
    assert "(SELECT max(date) FROM daily_bars WHERE symbol = 'NVDA')" in sql
    assert "<=" not in sql


async def test_live_get_macro_unchanged(captured):
    await tools.get_macro()
    sql = captured[-1]
    assert "(SELECT max(date) FROM macro_bars)" in sql
    assert "<=" not in sql


# --- anchored mode: frozen + bounded (no lookahead) ---------------------------
async def test_anchored_list_symbols_freezes_and_bounds(captured):
    set_anchor(T)
    await tools.list_symbols()
    sql = captured[-1]
    assert f"toDateTime('{T}')" in sql
    assert f"AND timestamp <= toDateTime('{T}')" in sql
    assert "SELECT max(timestamp)" not in sql  # moving anchor is gone


async def test_anchored_get_candles_ignores_symbol_predicate(captured):
    set_anchor(T)
    await tools.get_candles("NVDA")
    sql = captured[-1]
    # The frozen anchor is global — the per-symbol live subquery is dropped.
    assert f"toDateTime('{T}')" in sql
    assert f"AND timestamp <= toDateTime('{T}')" in sql
    assert "SELECT max(timestamp)" not in sql


async def test_anchored_get_history_narrows_to_date(captured):
    set_anchor(T)
    await tools.get_history("NVDA")
    sql = captured[-1]
    assert f"toDate(toDateTime('{T}'))" in sql
    assert f"AND date <= toDate(toDateTime('{T}'))" in sql
    assert "SELECT max(date)" not in sql


async def test_anchored_get_breadth_bounds_date(captured):
    set_anchor(T)
    await tools.get_breadth()
    sql = captured[-1]
    assert f"AND date <= toDate(toDateTime('{T}'))" in sql
    assert "SELECT max(date)" not in sql
