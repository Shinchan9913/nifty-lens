"""Daily historical candles from the Groww API (preferred NSE source).

Groww is NSE-native, so for the cash-equity universe it is a more authoritative
source than Yahoo. It does NOT carry the global factors (S&P, crude, gold, VIX,
USDINR), so those always stay on Yahoo.

IMPORTANT — entitlement: Groww's Market Data API (live quotes + historical candles)
is a SEPARATE paid subscription from the trading API. A trading-only key
authenticates fine and can read holdings/orders, but every market-data call
(get_ltp / get_quote / get_historical_candles) returns "Access forbidden". So
``is_available()`` does a real one-candle probe — not just a token mint — and
lets callers fall back to Yahoo, making Groww a one-flag switch (``USE_GROWW=1``)
with zero risk to the working Yahoo path.

This module is written against the SDK signatures + the existing ingestor's auth
flow. It has NOT been validated against a live entitled key — the candle-response
parsing is deliberately defensive (handles list-of-lists and list-of-dicts).
"""
from __future__ import annotations

import logging
from datetime import datetime

logger = logging.getLogger(__name__)

_CANDLE_FMT = "%Y-%m-%d %H:%M:%S"


def get_api():
    """Authenticate and return a GrowwAPI, or None if unavailable/unentitled."""
    try:
        from growwapi import GrowwAPI

        from src.config import get_groww_credentials
        creds = get_groww_credentials()
        key, secret = creds["GROWW_API_KEY"], creds["GROWW_API_SECRET"]
        if not key or key == "YOUR_API_KEY" or not secret:
            logger.info("Groww: credentials not set")
            return None
        token = GrowwAPI.get_access_token(api_key=key, secret=secret)
        return GrowwAPI(token)
    except Exception as e:  # auth/permission/import failure -> caller falls back
        logger.info("Groww unavailable (%s): %s", type(e).__name__, str(e)[:160])
        return None


def is_available() -> tuple[bool, str]:
    """(True, 'ok') only if a real historical candle can actually be fetched.

    A trading key mints a token fine but is forbidden from market data, so we
    probe with a tiny 5-day RELIANCE daily request rather than trusting auth alone.
    """
    api = get_api()
    if not api:
        return (False, "could not authenticate with Groww (check GROWW_API_KEY/SECRET)")
    from datetime import timedelta
    end = datetime.now()
    rows = fetch_daily(api, "RELIANCE", "NSE", end - timedelta(days=7), end)
    if rows:
        return (True, "ok")
    return (False, "Groww Market Data API not enabled for this key (historical candles forbidden)")


def _rows_from_candles(candles, symbol: str, exchange: str) -> list[dict]:
    """Normalise Groww's candle payload into daily_bars rows.

    Groww returns either ``[[epoch, o, h, l, c, v], ...]`` or a list of dicts.
    Epochs are seconds (IST). Daily bars key on the date only.
    """
    out = []
    for c in candles or []:
        if isinstance(c, dict):
            ts, o, h, l, cl, v = (
                c.get("timestamp") or c.get("epoch") or c.get("time"),
                c.get("open"), c.get("high"), c.get("low"), c.get("close"),
                c.get("volume", 0),
            )
        else:  # list/tuple
            if len(c) < 5:
                continue
            ts, o, h, l, cl = c[0], c[1], c[2], c[3], c[4]
            v = c[5] if len(c) > 5 else 0
        if None in (ts, o, h, l, cl):
            continue
        try:
            date = datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d")
        except (ValueError, OSError, TypeError):
            # already a date string?
            date = str(ts)[:10]
        out.append({
            "symbol": symbol, "exchange": exchange, "date": date,
            "open": round(float(o), 4), "high": round(float(h), 4),
            "low": round(float(l), 4), "close": round(float(cl), 4),
            "volume": float(v or 0),
        })
    return out


def fetch_daily(api, symbol: str, exchange: str, start: datetime, end: datetime) -> list[dict] | None:
    """Daily OHLCV rows for one NSE symbol, or None on failure (caller falls back).

    Per the Groww docs the daily interval allows up to 1080 days (~3y) per request
    and the response is ``{"candles": [[epoch_s, o, h, l, c, v], ...]}``. We try the
    recommended ``get_historical_candles`` first and fall back to the deprecated
    ``get_historical_candle_data`` (which takes ``trading_symbol`` +
    ``interval_in_minutes=1440``) in case the symbol-id format differs.
    """
    from growwapi import GrowwAPI

    exch = GrowwAPI.EXCHANGE_NSE if exchange == "NSE" else exchange
    # get_historical_candles wants an exchange-prefixed id, e.g. "NSE-WIPRO"
    # (per the Groww docs); the deprecated method takes the bare trading symbol.
    groww_symbol = f"{exch}-{symbol}"
    s, e = start.strftime(_CANDLE_FMT), end.strftime(_CANDLE_FMT)

    def _parse(res):
        candles = res.get("candles") if isinstance(res, dict) else res
        return _rows_from_candles(candles, symbol, exchange) or None

    # Recommended API
    try:
        return _parse(api.get_historical_candles(
            exchange=exch, segment=GrowwAPI.SEGMENT_CASH, groww_symbol=groww_symbol,
            start_time=s, end_time=e, candle_interval=GrowwAPI.CANDLE_INTERVAL_DAY,
        ))
    except Exception as exc1:
        logger.info("Groww get_historical_candles failed for %s (%s): %s",
                    groww_symbol, type(exc1).__name__, str(exc1)[:120])

    # Deprecated fallback (daily = 1440 minutes; takes the bare trading symbol)
    try:
        return _parse(api.get_historical_candle_data(
            trading_symbol=symbol, exchange=exch, segment=GrowwAPI.SEGMENT_CASH,
            start_time=s, end_time=e, interval_in_minutes=1440,
        ))
    except Exception as exc2:
        logger.info("Groww get_historical_candle_data failed for %s (%s): %s",
                    symbol, type(exc2).__name__, str(exc2)[:120])
        return None
