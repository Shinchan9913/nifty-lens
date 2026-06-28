"""FastAPI router for the dependency-forecasting pipeline.

Reads the derived ClickHouse tables and serves the graph, per-symbol drivers,
on-demand shock scenarios, and model-quality metrics. The shock simulator
reconstructs the VAR(1) map from stored coefficients — no price re-read needed.

Every payload carries the run_id and the model's own quality numbers so the UI
can show *how trustworthy* a graph is, not just what it claims.
"""
import asyncio
import re

from fastapi import APIRouter, Body, HTTPException

from src.agents.clickhouse import query
from src.forecast.pipeline import rebuild as _rebuild
from src.forecast.propagate import build_matrix, simulate_shock
from src.forecast.store import insert

router = APIRouter(prefix="/api/dependencies", tags=["dependencies"])


def _safe(sym: str) -> str:
    return re.sub(r"[^A-Za-z0-9_./-]", "", str(sym))[:32]


async def _latest_run() -> dict | None:
    rows = await query("SELECT * FROM forecast_runs ORDER BY created_at DESC LIMIT 1")
    return rows[0] if rows else None


@router.post("/rebuild")
async def rebuild():
    """Recompute residuals, the dependency graph, and the propagation map."""
    try:
        summary = await asyncio.to_thread(_rebuild)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return summary


@router.get("/graph")
async def graph():
    """Latest dependency graph: nodes (universe) + gated directed edges."""
    run = await _latest_run()
    if not run:
        return {"run_id": None, "nodes": [], "edges": [], "note": "no run yet — POST /rebuild"}
    edges = await query(
        f"SELECT src, dst, lag, coef, sign_consistency, improve_ar, improve_factor, "
        f"dir_acc_full, folds_improved, folds_total "
        f"FROM dependency_edges WHERE run_id = '{run['run_id']}' ORDER BY improve_ar DESC"
    )
    deg: dict[str, dict] = {s: {"in": 0, "out": 0} for s in run["universe"]}
    for e in edges:
        deg.setdefault(e["dst"], {"in": 0, "out": 0})["in"] += 1
        deg.setdefault(e["src"], {"in": 0, "out": 0})["out"] += 1
    nodes = [{"symbol": s, "in_degree": deg[s]["in"], "out_degree": deg[s]["out"]} for s in run["universe"]]
    return {
        "run_id": run["run_id"],
        "as_of": run["date_end"],
        "n_obs": run["n_obs"],
        "n_folds": run["n_folds"],
        "n_candidates": run["n_candidates"],
        "factors": run["factors"],
        "nodes": nodes,
        "edges": edges,
        "note": (
            "Directed lag-1 residual edges that beat AR-only and factor-only baselines "
            "out of sample. Sparse/empty graphs are expected at daily frequency."
        ),
    }


@router.get("/comovement")
async def comovement():
    """Contemporaneous co-movement network: undirected partial-correlation edges.

    Descriptive same-day structure (direct co-movement after removing factors AND
    every other stock), distinct from the predictive directed graph.
    """
    run = await _latest_run()
    if not run:
        return {"run_id": None, "nodes": [], "edges": [], "note": "no run yet — POST /rebuild"}
    edges = await query(
        f"SELECT a, b, partial_corr, corr, in_mst FROM comovement_edges "
        f"WHERE run_id = '{run['run_id']}' ORDER BY abs(partial_corr) DESC"
    )
    deg: dict[str, int] = {s: 0 for s in run["universe"]}
    for e in edges:
        deg[e["a"]] = deg.get(e["a"], 0) + 1
        deg[e["b"]] = deg.get(e["b"], 0) + 1
    nodes = [{"symbol": s, "degree": deg.get(s, 0)} for s in run["universe"]]
    return {
        "run_id": run["run_id"], "as_of": run["date_end"], "n_obs": run["n_obs"],
        "nodes": nodes, "edges": edges,
        "note": (
            "Same-day partial-correlation network: a direct co-movement link after "
            "removing the factors AND every other stock. Negative = substitutes. "
            "Association, not prediction, and not causal."
        ),
    }


@router.get("/symbol/{symbol}")
async def symbol(symbol: str):
    """Upstream drivers (edges into) and downstream dependents (edges out of) a symbol."""
    run = await _latest_run()
    if not run:
        raise HTTPException(status_code=404, detail="no run yet — POST /rebuild")
    sym = _safe(symbol)
    rid = run["run_id"]
    drivers = await query(
        f"SELECT src AS driver, coef, lag, improve_ar, sign_consistency, dir_acc_full "
        f"FROM dependency_edges WHERE run_id='{rid}' AND dst='{sym}' ORDER BY improve_ar DESC"
    )
    dependents = await query(
        f"SELECT dst AS dependent, coef, lag, improve_ar, sign_consistency, dir_acc_full "
        f"FROM dependency_edges WHERE run_id='{rid}' AND src='{sym}' ORDER BY improve_ar DESC"
    )
    metrics = await query(
        f"SELECT mse_zero, mse_ar, mse_factor, mse_full, dir_acc_ar, dir_acc_full, "
        f"ar_coef, resid_std, n_obs FROM forecast_metrics "
        f"WHERE run_id='{rid}' AND scope='symbol' AND symbol='{sym}' LIMIT 1"
    )
    return {
        "run_id": rid, "symbol": sym,
        "upstream_drivers": drivers,
        "downstream_dependents": dependents,
        "metrics": metrics[0] if metrics else None,
        "note": "Drivers lead this symbol by 1 trading day in residual space. Not causal proof.",
    }


@router.get("/metrics")
async def metrics():
    """Model quality vs the locked baselines (overall + per symbol) for the latest run."""
    run = await _latest_run()
    if not run:
        return {"run_id": None, "note": "no run yet — POST /rebuild"}
    rid = run["run_id"]
    overall = await query(
        f"SELECT * FROM forecast_metrics WHERE run_id='{rid}' AND scope='overall' LIMIT 1"
    )
    per_symbol = await query(
        f"SELECT symbol, mse_zero, mse_ar, mse_factor, mse_full, dir_acc_ar, dir_acc_full, n_obs "
        f"FROM forecast_metrics WHERE run_id='{rid}' AND scope='symbol' ORDER BY symbol"
    )
    return {
        "run_id": rid,
        "as_of": run["date_end"],
        "n_obs": run["n_obs"],
        "n_folds": run["n_folds"],
        "n_edges": run["n_edges"],
        "n_candidates": run["n_candidates"],
        "params": run["params"],
        "overall": overall[0] if overall else None,
        "per_symbol": per_symbol,
        "note": (
            "Baselines: zero / AR-only / factor-only. An edge is only kept when the full "
            "model beats AR-only AND factor-only out of sample. Directional accuracy near "
            "0.5 and rank IC near 0 are normal for daily horizons."
        ),
    }


async def _reconstruct(run: dict) -> tuple[list[str], list[dict], dict, dict]:
    """Pull universe, edges, AR coefs and residual stds for the propagation map."""
    rid = run["run_id"]
    universe = run["universe"]
    edges = await query(f"SELECT src, dst, coef FROM dependency_edges WHERE run_id='{rid}'")
    coefs = await query(
        f"SELECT symbol, ar_coef, resid_std FROM forecast_metrics "
        f"WHERE run_id='{rid}' AND scope='symbol'"
    )
    ar = {c["symbol"]: float(c["ar_coef"]) for c in coefs}
    rsd = {c["symbol"]: float(c["resid_std"]) for c in coefs}
    return universe, edges, ar, rsd


@router.post("/shock")
async def shock(payload: dict = Body(...)):
    """Simulate a one-off shock to one symbol and propagate it through the graph.

    Body: {"symbol": "RELIANCE", "shock_pct": 5.0, "horizon": 5, "persist": false}
    """
    run = await _latest_run()
    if not run:
        raise HTTPException(status_code=404, detail="no run yet — POST /rebuild")
    sym = _safe(payload.get("symbol", ""))
    shock_pct = float(payload.get("shock_pct", 5.0))
    horizon = int(payload.get("horizon", 5))
    universe, edges, ar, rsd = await _reconstruct(run)
    if sym not in universe:
        raise HTTPException(status_code=400, detail=f"{sym} not in universe {universe}")

    def _run():
        M, radius, clamped = build_matrix(universe, edges, ar)
        series = simulate_shock(universe, M, rsd, sym, shock_pct, horizon)
        return series, radius, clamped

    series, radius, clamped = await asyncio.to_thread(_run)

    if payload.get("persist"):
        await asyncio.to_thread(insert, "shock_results", [{
            "run_id": run["run_id"], "shocked_symbol": sym, "shock_pct": shock_pct,
            "horizon": horizon, **{k: r[k] for k in (
                "affected_symbol", "step", "mean_impact", "p05", "p25", "p75", "p95",
                "prob_up", "prob_down", "prob_large")},
        } for r in series])

    # surface only the materially-affected names at the final horizon up top
    final = [r for r in series if r["step"] == horizon]
    movers = sorted(final, key=lambda r: abs(r["mean_impact"]), reverse=True)
    return {
        "run_id": run["run_id"], "shocked_symbol": sym, "shock_pct": shock_pct,
        "horizon": horizon, "spectral_radius": round(radius, 4), "clamped": clamped,
        "top_movers": movers[:10],
        "series": series,
        "note": (
            "Scenario analysis, not a causal intervention or advice. Wide intervals / "
            "prob_up near 0.5 mean the shock carries little information about that name."
        ),
    }
