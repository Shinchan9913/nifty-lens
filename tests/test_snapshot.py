"""Point-in-time snapshot anchor: the SQL the helpers emit IS the no-lookahead guarantee.

These tests pin down exactly what `now_expr` / `asof_filter` produce in live vs anchored
mode, so a future edit can't silently let future rows leak into a point-in-time run. Pure
string-building — no ClickHouse needed.
"""
import pytest

from src.agents.snapshot import (
    asof_filter,
    clear_anchor,
    get_anchor,
    now_expr,
    set_anchor,
)

T = "2026-06-23 23:04:00"


@pytest.fixture(autouse=True)
def _reset():
    # Every test starts and ends in live mode so the contextvar can't bleed across tests.
    clear_anchor()
    yield
    clear_anchor()


# --- live mode (no anchor) — preserves original behaviour ---------------------
def test_live_now_expr_is_the_moving_subquery():
    assert now_expr() == "(SELECT max(timestamp) FROM tick_data)"


def test_live_now_expr_keeps_per_symbol_predicate():
    assert now_expr(where="symbol = 'NVDA'") == "(SELECT max(timestamp) FROM tick_data WHERE symbol = 'NVDA')"


def test_live_asof_filter_is_empty():
    # No anchor => no upper bound => current live behaviour is unchanged.
    assert asof_filter() == ""


def test_live_anchor_is_blank():
    assert get_anchor() == ""


# --- anchored mode (point-in-time) --------------------------------------------
def test_anchored_now_expr_is_frozen_literal():
    set_anchor(T)
    assert now_expr() == f"toDateTime('{T}')"


def test_anchored_now_expr_ignores_live_predicate():
    set_anchor(T)
    # Once frozen, the per-symbol live predicate is irrelevant — the anchor is global.
    assert now_expr(where="symbol = 'NVDA'") == f"toDateTime('{T}')"


def test_anchored_date_column_is_narrowed_to_date():
    set_anchor(T)
    assert now_expr(col="date", table="daily_bars") == f"toDate(toDateTime('{T}'))"


def test_anchored_asof_filter_blocks_future_rows():
    set_anchor(T)
    assert asof_filter() == f" AND timestamp <= toDateTime('{T}')"


def test_anchored_asof_filter_for_date_column():
    set_anchor(T)
    assert asof_filter("date") == f" AND date <= toDate(toDateTime('{T}'))"


def test_set_then_clear_returns_to_live():
    set_anchor(T)
    assert get_anchor() == T
    clear_anchor()
    assert get_anchor() == "" and asof_filter() == ""


def test_set_anchor_strips_whitespace():
    set_anchor(f"  {T} ")
    assert get_anchor() == T
