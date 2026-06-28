"""Build the aligned daily log-return panel for stocks and factors.

Returns are computed from ClickHouse ``daily_bars`` (NSE equities) and
``macro_bars`` (the locked factor set). Everything downstream operates on this
single date-aligned panel so there is no hidden misalignment between a stock and
its factors.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import config
from .store import query


@dataclass
class Panel:
    dates: list[str]            # trading dates, ascending (length T)
    stocks: list[str]           # stock symbols (length N)
    factors: list[str]          # factor symbols (length F)
    stock_ret: np.ndarray       # (T, N) daily log returns
    factor_ret: np.ndarray      # (T, F) daily log returns

    @property
    def n_obs(self) -> int:
        return len(self.dates)


def _close_frame(table: str, symbols: list[str]) -> pd.DataFrame:
    """Wide date x symbol close-price frame for the given symbols."""
    sym_list = ",".join(f"'{s}'" for s in symbols)
    rows = query(
        f"SELECT symbol, toString(date) AS date, close "
        f"FROM {table} WHERE symbol IN ({sym_list}) ORDER BY date"
    )
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    return df.pivot_table(index="date", columns="symbol", values="close", aggfunc="last")


def load_panel(min_obs: int | None = None) -> Panel:
    """Assemble the aligned stock/factor log-return panel.

    Stocks: every NSE symbol present in daily_bars. Factors: the locked set, with
    INDIAVIX falling back to VIX when the former has no history.
    """
    # discover the NSE stock universe actually present
    uni = query("SELECT DISTINCT symbol FROM daily_bars WHERE exchange = 'NSE' ORDER BY symbol")
    stock_syms = [r["symbol"] for r in uni]
    if not stock_syms:
        raise RuntimeError("daily_bars has no NSE symbols — run src/seed_history.py first.")

    factor_syms = config.factor_symbols()
    stock_px = _close_frame("daily_bars", stock_syms)
    factor_px = _close_frame("macro_bars", factor_syms + [config.VIX_FALLBACK])

    # INDIAVIX fallback: if it never loaded, substitute VIX under the same name.
    if config.SECTOR_FACTORS and "INDIAVIX" in factor_syms:
        if "INDIAVIX" not in factor_px.columns or factor_px["INDIAVIX"].notna().sum() < config.MIN_TRAIN:
            if config.VIX_FALLBACK in factor_px.columns:
                factor_px["INDIAVIX"] = factor_px[config.VIX_FALLBACK]
    factor_px = factor_px.reindex(columns=factor_syms)

    # keep only factors that actually have data; drop fully-empty ones
    factor_px = factor_px.dropna(axis=1, how="all")
    factors = list(factor_px.columns)

    # join on common dates, forward-fill small gaps (holidays differ across series),
    # then drop any remaining rows with missing values so the panel is rectangular.
    px = stock_px.join(factor_px, how="inner", lsuffix="", rsuffix="_f")
    px = px.sort_index().ffill(limit=2).dropna()

    stock_px = px[stock_syms]
    factor_px = px[factors]

    # log returns
    stock_ret = np.log(stock_px / stock_px.shift(1)).dropna()
    factor_ret = np.log(factor_px / factor_px.shift(1)).reindex(stock_ret.index)

    panel = Panel(
        dates=[str(d) for d in stock_ret.index],
        stocks=stock_syms,
        factors=factors,
        stock_ret=stock_ret.to_numpy(dtype=float),
        factor_ret=factor_ret.to_numpy(dtype=float),
    )
    floor = min_obs if min_obs is not None else config.MIN_OBS
    if panel.n_obs < floor:
        raise RuntimeError(
            f"only {panel.n_obs} aligned daily observations; need >= {floor}. "
            "Seed more history (raise HISTORY_YEARS for src/seed_history.py)."
        )
    return panel
