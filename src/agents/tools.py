"""ClickHouse-backed tools the specialist agents can call.

Each entry in ``TOOL_SCHEMAS`` is an Anthropic tool definition; ``HANDLERS`` maps
the same name to an async function that runs the query and returns plain data
(serialized to JSON before it goes back to the model).
"""
import asyncio
import re

import requests

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


# --- universe helpers ---------------------------------------------------------
_NSE = {"RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN", "BAJFINANCE", "TATASTEEL", "LT", "ADANIPOWER"}


def _yahoo(symbol: str) -> str:
    """Map our stored symbol to a Yahoo Finance ticker (NSE names need a .NS suffix)."""
    s = re.sub(r"[^A-Za-z0-9.\-]", "", str(symbol)).upper()
    return f"{s}.NS" if s in _NSE else s


# --- multi-day history + macro (ClickHouse-backed) ----------------------------
async def get_history(symbol: str, days: int = 60) -> dict:
    """Daily price history + summary for one symbol over the last N trading days."""
    sym = _safe_symbol(symbol)
    rows = await query(
        f"""
        SELECT toString(date) AS dt, open, high, low, close, volume
        FROM daily_bars
        WHERE symbol = '{sym}'
          AND date >= (SELECT max(date) FROM daily_bars WHERE symbol = '{sym}') - INTERVAL {int(days)} DAY
        ORDER BY date
        """
    )
    if not rows:
        return {"symbol": symbol, "error": "no daily history (is it in the seeded universe?)"}
    closes = [r["close"] for r in rows]
    first, last = closes[0], closes[-1]
    return {
        "symbol": symbol,
        "as_of": rows[-1]["dt"],
        "days": len(rows),
        "first_close": first,
        "last_close": last,
        "change_pct": round((last - first) / first * 100, 2) if first else None,
        "period_high": max(r["high"] for r in rows),
        "period_low": min(r["low"] for r in rows),
        "closes": [{"date": r["dt"], "close": r["close"]} for r in rows],
    }


async def get_macro() -> list[dict]:
    """Latest level + 1-day and 5-day % change for every macro / cross-asset series."""
    rows = await query(
        """
        SELECT symbol, category, close
        FROM macro_bars
        WHERE date >= (SELECT max(date) FROM macro_bars) - INTERVAL 9 DAY
        ORDER BY symbol, date
        """
    )
    by_sym: dict[str, list[dict]] = {}
    cats: dict[str, str] = {}
    for r in rows:
        by_sym.setdefault(r["symbol"], []).append(r)
        cats[r["symbol"]] = r["category"]
    out = []
    for sym, series in by_sym.items():
        closes = [s["close"] for s in series]
        last = closes[-1]
        prev = closes[-2] if len(closes) >= 2 else last
        five = closes[-6] if len(closes) >= 6 else closes[0]
        out.append({
            "symbol": sym, "category": cats[sym], "last": round(last, 2),
            "change_1d_pct": round((last - prev) / prev * 100, 2) if prev else None,
            "change_5d_pct": round((last - five) / five * 100, 2) if five else None,
        })
    return out


async def get_breadth() -> dict:
    """Market breadth across the daily-bars universe: advancers/decliners + % above 50d SMA."""
    rows = await query(
        """
        SELECT symbol, close
        FROM daily_bars
        WHERE date >= (SELECT max(date) FROM daily_bars) - INTERVAL 60 DAY
        ORDER BY symbol, date
        """
    )
    by_sym: dict[str, list[float]] = {}
    for r in rows:
        by_sym.setdefault(r["symbol"], []).append(r["close"])
    adv = dec = above = total = 0
    for closes in by_sym.values():
        if len(closes) < 2:
            continue
        total += 1
        if closes[-1] >= closes[-2]:
            adv += 1
        else:
            dec += 1
        sma = sum(closes[-50:]) / len(closes[-50:])
        if closes[-1] >= sma:
            above += 1
    return {
        "universe": total, "advancers": adv, "decliners": dec,
        "pct_up": round(adv / total * 100, 1) if total else None,
        "pct_above_50d_sma": round(above / total * 100, 1) if total else None,
    }


# --- fundamentals / analyst / news (yfinance) ---------------------------------
def _yf_fundamentals(symbol: str) -> dict:
    import yfinance as yf

    info = yf.Ticker(_yahoo(symbol)).info or {}
    keys = [
        "longName", "sector", "industry", "marketCap", "trailingPE", "forwardPE",
        "priceToBook", "profitMargins", "returnOnEquity", "debtToEquity",
        "revenueGrowth", "earningsGrowth", "dividendYield", "beta",
        "fiftyTwoWeekHigh", "fiftyTwoWeekLow", "currentPrice",
    ]
    out = {k: info.get(k) for k in keys if info.get(k) is not None}
    if not out:
        out["note"] = "fundamentals unavailable for this symbol (common for NSE/indices)"
    return out


async def get_fundamentals(symbol: str) -> dict:
    data = await asyncio.to_thread(_yf_fundamentals, symbol)
    return {"symbol": symbol, **data}


def _yf_analyst(symbol: str) -> dict:
    import yfinance as yf

    info = yf.Ticker(_yahoo(symbol)).info or {}
    keys = [
        "recommendationKey", "recommendationMean", "numberOfAnalystOpinions",
        "currentPrice", "targetMeanPrice", "targetHighPrice", "targetLowPrice",
    ]
    out = {k: info.get(k) for k in keys if info.get(k) is not None}
    if not out:
        out["note"] = "no analyst coverage available"
    return out


async def get_analyst(symbol: str) -> dict:
    data = await asyncio.to_thread(_yf_analyst, symbol)
    return {"symbol": symbol, **data}


def _yf_news(symbol: str, limit: int) -> list[dict]:
    import yfinance as yf

    items = yf.Ticker(_yahoo(symbol)).news or []
    out = []
    for it in items[:limit]:
        c = it.get("content", it) if isinstance(it, dict) else {}
        prov = c.get("provider")
        url = c.get("canonicalUrl")
        out.append({
            "title": c.get("title") or it.get("title"),
            "publisher": prov.get("displayName") if isinstance(prov, dict) else it.get("publisher"),
            "url": url.get("url") if isinstance(url, dict) else it.get("link"),
            "date": c.get("pubDate") or it.get("providerPublishTime"),
        })
    return [o for o in out if o.get("title")]


async def get_news(symbol: str, limit: int = 6) -> list[dict]:
    return await asyncio.to_thread(_yf_news, symbol, int(limit))


# --- options (yfinance US; NSE blocked from this env) -------------------------
def _yf_options(symbol: str) -> dict:
    import yfinance as yf

    if symbol.upper() in _NSE:
        return {"available": False, "note": "NSE option chain is blocked/paid from this environment"}
    t = yf.Ticker(_yahoo(symbol))
    exps = list(t.options or [])
    if not exps:
        return {"available": False, "note": "no listed options for this symbol"}
    exp = exps[0]
    ch = t.option_chain(exp)
    calls, puts = ch.calls, ch.puts
    call_oi = float(calls["openInterest"].fillna(0).sum())
    put_oi = float(puts["openInterest"].fillna(0).sum())
    try:
        spot = float(t.history(period="1d")["Close"].iloc[-1])
    except Exception:
        spot = None
    iv = None
    if spot:
        near_c = calls[(calls["strike"] >= spot * 0.95) & (calls["strike"] <= spot * 1.05)]["impliedVolatility"]
        near_p = puts[(puts["strike"] >= spot * 0.95) & (puts["strike"] <= spot * 1.05)]["impliedVolatility"]
        vals = list(near_c.dropna()) + list(near_p.dropna())
        iv = round(sum(vals) / len(vals) * 100, 1) if vals else None
    return {
        "available": True, "expiry": exp, "spot": spot,
        "call_oi": int(call_oi), "put_oi": int(put_oi),
        "put_call_ratio": round(put_oi / call_oi, 2) if call_oi else None,
        "atm_iv_pct": iv, "expiries_available": len(exps),
    }


async def get_option_chain(symbol: str) -> dict:
    data = await asyncio.to_thread(_yf_options, symbol)
    return {"symbol": symbol, **data}


# --- SEC EDGAR filings (US only) ----------------------------------------------
_SEC_HEADERS = {"User-Agent": "nifty-lens research demo (contact: dev@nifty-lens.local)"}
_CIK_MAP: dict | None = None


def _edgar_filings(symbol: str, limit: int) -> dict:
    global _CIK_MAP
    s = symbol.upper()
    if s in _NSE:
        return {"available": False, "note": "SEC EDGAR is US-only"}
    if _CIK_MAP is None:
        r = requests.get("https://www.sec.gov/files/company_tickers.json", headers=_SEC_HEADERS, timeout=20)
        r.raise_for_status()
        _CIK_MAP = {v["ticker"].upper(): (str(v["cik_str"]).zfill(10), v["title"]) for v in r.json().values()}
    if s not in _CIK_MAP:
        return {"available": False, "note": f"{s} not found in SEC ticker registry"}
    cik, title = _CIK_MAP[s]
    r = requests.get(f"https://data.sec.gov/submissions/CIK{cik}.json", headers=_SEC_HEADERS, timeout=20)
    r.raise_for_status()
    rec = r.json().get("filings", {}).get("recent", {})
    forms, dates, descs = rec.get("form", []), rec.get("filingDate", []), rec.get("primaryDocDescription", [])
    keep = {"10-K", "10-Q", "8-K", "S-1", "DEF 14A", "6-K", "20-F"}
    out = []
    for i, form in enumerate(forms):
        if form in keep:
            out.append({"form": form, "date": dates[i], "desc": descs[i] if i < len(descs) else None})
        if len(out) >= limit:
            break
    return {"available": True, "company": title, "cik": cik, "filings": out}


async def get_filings(symbol: str, limit: int = 6) -> dict:
    data = await asyncio.to_thread(_edgar_filings, symbol, int(limit))
    return {"symbol": symbol, **data}


# --- Google Trends (pytrends; flaky, degrades gracefully) ---------------------
def _trends(term: str) -> dict:
    from pytrends.request import TrendReq

    py = TrendReq(hl="en-US", tz=0)
    py.build_payload([term], timeframe="today 3-m")
    df = py.interest_over_time()
    if df is None or df.empty or term not in df:
        return {"available": False, "note": "no Google Trends data for this term"}
    series = [int(x) for x in df[term].tolist()]
    first, last = series[0] or 1, series[-1]
    return {
        "available": True, "term": term, "last": last,
        "avg": round(sum(series) / len(series), 1), "peak": max(series),
        "change_vs_start_pct": round((last - first) / first * 100, 1),
    }


async def get_trends(term: str) -> dict:
    try:
        return await asyncio.to_thread(_trends, term)
    except Exception as e:
        return {"available": False, "term": term, "note": f"trends lookup failed: {e!r}"[:160]}


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


# --- dependency graph (controlled forecasting pipeline) -----------------------
async def _latest_dep_run() -> dict | None:
    rows = await query("SELECT * FROM forecast_runs ORDER BY created_at DESC LIMIT 1")
    return rows[0] if rows else None


async def get_dependency_graph(limit: int = 20) -> dict:
    """The latest validated dependency graph: directed lag-1 residual edges that
    beat AR-only and factor-only baselines out of sample."""
    run = await _latest_dep_run()
    if not run:
        return {"available": False, "note": "no dependency run yet (rebuild needed)"}
    edges = await query(
        f"SELECT src, dst, round(coef,4) AS coef, round(improve_ar,4) AS improve_ar, "
        f"round(sign_consistency,3) AS sign_consistency, round(dir_acc_full,3) AS dir_acc_full "
        f"FROM dependency_edges WHERE run_id='{run['run_id']}' ORDER BY improve_ar DESC LIMIT {int(limit)}"
    )
    return {
        "available": True, "run_id": run["run_id"], "as_of": run["date_end"],
        "n_obs": run["n_obs"], "n_candidates": run["n_candidates"], "n_edges": run["n_edges"],
        "edges": edges,
        "note": "src leads dst by 1 day in residual space. Sparse/empty is normal; not causal.",
    }


async def get_symbol_dependencies(symbol: str) -> dict:
    """Upstream drivers and downstream dependents of one symbol, with its model quality."""
    run = await _latest_dep_run()
    if not run:
        return {"available": False, "note": "no dependency run yet"}
    sym = _safe_symbol(symbol)
    rid = run["run_id"]
    drivers = await query(
        f"SELECT src AS driver, round(coef,4) AS coef, round(improve_ar,4) AS improve_ar "
        f"FROM dependency_edges WHERE run_id='{rid}' AND dst='{sym}' ORDER BY improve_ar DESC"
    )
    dependents = await query(
        f"SELECT dst AS dependent, round(coef,4) AS coef, round(improve_ar,4) AS improve_ar "
        f"FROM dependency_edges WHERE run_id='{rid}' AND src='{sym}' ORDER BY improve_ar DESC"
    )
    m = await query(
        f"SELECT round(mse_ar,8) AS mse_ar, round(mse_full,8) AS mse_full, "
        f"round(dir_acc_full,3) AS dir_acc_full FROM forecast_metrics "
        f"WHERE run_id='{rid}' AND scope='symbol' AND symbol='{sym}' LIMIT 1"
    )
    return {"available": True, "symbol": sym, "upstream_drivers": drivers,
            "downstream_dependents": dependents, "metrics": m[0] if m else None}


async def get_dependency_shock(symbol: str, shock_pct: float = 5.0, horizon: int = 5) -> dict:
    """Propagate a one-off shock to a symbol through the learned graph (scenario only)."""
    from src.forecast.propagate import build_matrix, simulate_shock

    run = await _latest_dep_run()
    if not run:
        return {"available": False, "note": "no dependency run yet"}
    sym = _safe_symbol(symbol)
    rid = run["run_id"]
    universe = run["universe"]
    if sym not in universe:
        return {"available": False, "note": f"{sym} not in dependency universe"}
    edges = await query(f"SELECT src, dst, coef FROM dependency_edges WHERE run_id='{rid}'")
    coefs = await query(
        f"SELECT symbol, ar_coef, resid_std FROM forecast_metrics WHERE run_id='{rid}' AND scope='symbol'"
    )
    ar = {c["symbol"]: float(c["ar_coef"]) for c in coefs}
    rsd = {c["symbol"]: float(c["resid_std"]) for c in coefs}

    def _run():
        M, radius, clamped = build_matrix(universe, edges, ar)
        series = simulate_shock(universe, M, rsd, sym, float(shock_pct), int(horizon))
        final = [r for r in series if r["step"] == int(horizon) and r["affected_symbol"] != sym]
        return sorted(final, key=lambda r: abs(r["mean_impact"]), reverse=True)[:8], radius

    movers, radius = await asyncio.to_thread(_run)
    return {"available": True, "shocked_symbol": sym, "shock_pct": shock_pct,
            "horizon": horizon, "spectral_radius": round(radius, 4), "top_movers": movers,
            "note": "Probabilistic scenario, not causal/advice. prob_up~0.5 => little signal."}


async def get_comovement_network(symbol: str = "", limit: int = 15) -> dict:
    """Same-day co-movement structure (partial-correlation network). If a symbol is
    given, returns its direct co-movement neighbours; else the strongest links overall."""
    run = await _latest_dep_run()
    if not run:
        return {"available": False, "note": "no dependency run yet"}
    rid = run["run_id"]
    if symbol:
        sym = _safe_symbol(symbol)
        rows = await query(
            f"SELECT a, b, round(partial_corr,4) AS partial_corr, round(corr,4) AS corr "
            f"FROM comovement_edges WHERE run_id='{rid}' AND (a='{sym}' OR b='{sym}') "
            f"ORDER BY abs(partial_corr) DESC LIMIT {int(limit)}"
        )
        neighbours = [{"peer": r["b"] if r["a"] == sym else r["a"],
                       "partial_corr": r["partial_corr"], "corr": r["corr"],
                       "relation": "moves together" if r["partial_corr"] >= 0 else "moves opposite (substitute)"}
                      for r in rows]
        return {"available": True, "symbol": sym, "neighbours": neighbours,
                "note": "Same-day direct co-movement (factors + all other names removed). Not predictive, not causal."}
    rows = await query(
        f"SELECT a, b, round(partial_corr,4) AS partial_corr FROM comovement_edges "
        f"WHERE run_id='{rid}' ORDER BY abs(partial_corr) DESC LIMIT {int(limit)}"
    )
    return {"available": True, "strongest_links": rows,
            "note": "Same-day partial-correlation network. Positive=move together, negative=substitutes. Association only."}


async def get_dependency_metrics() -> dict:
    """Overall model quality vs the locked zero/AR-only/factor-only baselines."""
    run = await _latest_dep_run()
    if not run:
        return {"available": False, "note": "no dependency run yet"}
    o = await query(
        f"SELECT round(mse_zero,8) AS mse_zero, round(mse_ar,8) AS mse_ar, "
        f"round(mse_factor,8) AS mse_factor, round(dir_acc_ar,3) AS dir_acc_ar, "
        f"round(rank_ic,4) AS rank_ic FROM forecast_metrics "
        f"WHERE run_id='{run['run_id']}' AND scope='overall' LIMIT 1"
    )
    return {"available": True, "run_id": run["run_id"], "n_obs": run["n_obs"],
            "n_folds": run["n_folds"], "n_edges": run["n_edges"],
            "n_candidates": run["n_candidates"], "overall": o[0] if o else None,
            "note": "dir acc ~0.5 and rank IC ~0 are normal at daily horizon."}


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
    "get_history": {
        "name": "get_history",
        "description": "Daily price history + summary (change %, period high/low) for a symbol over the last N trading days. Use for trend/regime context.",
        "input_schema": {"type": "object", "properties": {
            "symbol": {"type": "string"}, "days": {"type": "integer", "description": "Lookback in trading days (default 60)."}}, "required": ["symbol"]},
    },
    "get_macro": {
        "name": "get_macro",
        "description": "Latest level + 1d/5d % change for macro & cross-asset series (indices, commodities, FX, US10Y, VIX, BTC). Use to read the risk regime and intermarket backdrop.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    "get_breadth": {
        "name": "get_breadth",
        "description": "Market breadth across the tracked universe: advancers/decliners and % of names above their 50-day SMA. Use to judge if a move is broad or narrow.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    "get_fundamentals": {
        "name": "get_fundamentals",
        "description": "Company fundamentals (valuation ratios, margins, growth, sector, 52w range) via Yahoo. Rich for US tickers; partial/empty for NSE & indices.",
        "input_schema": {"type": "object", "properties": {"symbol": {"type": "string"}}, "required": ["symbol"]},
    },
    "get_analyst": {
        "name": "get_analyst",
        "description": "Sell-side analyst consensus: recommendation, mean/high/low price targets vs current price, number of analysts. Mostly US coverage.",
        "input_schema": {"type": "object", "properties": {"symbol": {"type": "string"}}, "required": ["symbol"]},
    },
    "get_news": {
        "name": "get_news",
        "description": "Recent headlines for a symbol (title, publisher, url, date) via Yahoo. Use as catalysts; score sentiment yourself from the titles.",
        "input_schema": {"type": "object", "properties": {"symbol": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["symbol"]},
    },
    "get_option_chain": {
        "name": "get_option_chain",
        "description": "Options positioning: total call/put open interest, put/call ratio, ATM implied volatility, expiry. Works for US tickers; returns available=false for NSE (blocked here).",
        "input_schema": {"type": "object", "properties": {"symbol": {"type": "string"}}, "required": ["symbol"]},
    },
    "get_filings": {
        "name": "get_filings",
        "description": "Recent SEC filings (10-K/10-Q/8-K/etc. with form, date, description) for a US company. Use to ground claims in primary disclosures. US-only.",
        "input_schema": {"type": "object", "properties": {"symbol": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["symbol"]},
    },
    "get_trends": {
        "name": "get_trends",
        "description": "Google Trends search-interest for a term (last value, 3-month avg/peak, % change vs start) as a retail-attention proxy. Pass a company/product name for best results.",
        "input_schema": {"type": "object", "properties": {"term": {"type": "string"}}, "required": ["term"]},
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
    "get_dependency_graph": {
        "name": "get_dependency_graph",
        "description": (
            "The validated NSE dependency graph: directed lag-1 residual-return edges (src leads "
            "dst by one day) that beat both AR-only and factor-only baselines out of sample. "
            "Returns edges with coefficient, OOS improvement and sign consistency. Sparse or empty "
            "is the normal, honest result at daily frequency — these are statistical, not causal."
        ),
        "input_schema": {"type": "object", "properties": {
            "limit": {"type": "integer", "description": "Max edges to return (default 20)."}}, "required": []},
    },
    "get_symbol_dependencies": {
        "name": "get_symbol_dependencies",
        "description": (
            "For one symbol: its upstream drivers (names that lead it) and downstream dependents "
            "(names it leads) in residual space, plus its model quality vs the AR baseline. Use to "
            "explain what statistically precedes or follows a stock's idiosyncratic moves."
        ),
        "input_schema": {"type": "object", "properties": {"symbol": {"type": "string"}}, "required": ["symbol"]},
    },
    "get_dependency_shock": {
        "name": "get_dependency_shock",
        "description": (
            "Scenario analysis: propagate a one-off % shock to one symbol's residual return through "
            "the learned graph over N trading days. Returns the most-affected names with mean impact "
            "and probabilities. Probabilistic scenario only — not causal and not advice."
        ),
        "input_schema": {"type": "object", "properties": {
            "symbol": {"type": "string"},
            "shock_pct": {"type": "number", "description": "Initial shock in %, e.g. 5 (default 5)."},
            "horizon": {"type": "integer", "description": "Trading-day horizon (default 5)."}},
            "required": ["symbol"]},
    },
    "get_dependency_metrics": {
        "name": "get_dependency_metrics",
        "description": (
            "Quality of the dependency forecaster vs its locked baselines (zero / AR-only / "
            "factor-only): out-of-sample MSE, directional accuracy, rank IC, edge counts. Use to "
            "judge HOW MUCH to trust the graph before citing it."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    "get_comovement_network": {
        "name": "get_comovement_network",
        "description": (
            "Same-day co-movement structure: a partial-correlation network where a link means two "
            "NSE names move together (or oppositely, = substitutes) on the same day even after "
            "removing market/sector/macro factors AND every other stock. Pass a symbol for its "
            "direct peers, or omit for the strongest links overall. Descriptive association, not "
            "prediction and not causal — use to explain clusters/peers (business groups, sectors)."
        ),
        "input_schema": {"type": "object", "properties": {
            "symbol": {"type": "string", "description": "Optional: focus on one symbol's co-movement peers."},
            "limit": {"type": "integer", "description": "Max links to return (default 15)."}}, "required": []},
    },
}

HANDLERS = {
    "list_symbols": list_symbols,
    "get_candles": get_candles,
    "get_top_movers": get_top_movers,
    "get_volume_by_exchange": get_volume_by_exchange,
    "get_history": get_history,
    "get_macro": get_macro,
    "get_breadth": get_breadth,
    "get_fundamentals": get_fundamentals,
    "get_analyst": get_analyst,
    "get_news": get_news,
    "get_option_chain": get_option_chain,
    "get_filings": get_filings,
    "get_trends": get_trends,
    "web_search": web_search,
    "get_dependency_graph": get_dependency_graph,
    "get_symbol_dependencies": get_symbol_dependencies,
    "get_dependency_shock": get_dependency_shock,
    "get_dependency_metrics": get_dependency_metrics,
}


def summarize_result(result) -> str:
    """One-line summary of a tool result for the UI timeline."""
    if isinstance(result, list):
        return f"{len(result)} row(s)"
    return str(result)[:120]
