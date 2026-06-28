"""End-to-end rebuild: returns -> residuals -> graph -> propagation map.

Phase 1  load the aligned return panel (residualisation happens fold-locally
         inside the walk-forward, so there is no global residual table).
Phase 2  screen candidates, walk-forward evaluate, gate edges, score metrics.
Phase 3  build + stability-clamp the VAR(1) propagation matrix.

Run:  source .venv/bin/activate && python -m src.forecast.pipeline
"""
import json
from datetime import datetime

import numpy as np

from . import config
from .comovement import build_comovement
from .data import load_panel
from .graph import build_graph, rank_ic
from .model import n_folds
from .propagate import build_matrix
from .store import insert, query


def rebuild() -> dict:
    """Run all phases, persist to ClickHouse, return a summary."""
    run_id = "run_" + datetime.now().strftime("%Y%m%d_%H%M%S")

    # Phase 1 -----------------------------------------------------------------
    panel = load_panel()
    nf = n_folds(panel.n_obs)

    # Phase 2 -----------------------------------------------------------------
    edges, results, n_candidates = build_graph(panel)
    overall_ic = rank_ic(results, panel.stocks)

    # persist run header
    insert("forecast_runs", [{
        "run_id": run_id,
        "universe": panel.stocks,
        "factors": panel.factors,
        "n_obs": panel.n_obs,
        "date_start": panel.dates[0],
        "date_end": panel.dates[-1],
        "lag": config.LAG,
        "min_train": config.MIN_TRAIN,
        "n_folds": nf,
        "n_candidates": n_candidates,
        "n_edges": len(edges),
        "params": json.dumps(config.gating_params()),
        "notes": (
            f"{len(edges)} edge(s) passed walk-forward gating out of {n_candidates} "
            f"candidates across {nf} folds. Zero edges is a valid outcome."
        ),
    }])

    # persist edges
    insert("dependency_edges", [{
        "run_id": run_id, "src": e["src"], "dst": e["dst"], "lag": e["lag"],
        "coef": e["coef"], "sign_consistency": e["sign_consistency"],
        "mse_full": e["mse_full"], "mse_ar": e["mse_ar"], "mse_factor": e["mse_factor"],
        "improve_ar": e["improve_ar"], "improve_factor": e["improve_factor"],
        "dir_acc_full": e["dir_acc_full"], "folds_improved": e["folds_improved"],
        "folds_total": e["folds_total"], "n_obs": e["n_obs"],
    } for e in edges])

    # per-symbol metrics (mse_full = best kept edge for that target, else AR)
    best_full = {}   # dst symbol -> (mse_full, dir_acc_full, brier_full)
    for e in edges:
        cur = best_full.get(e["dst"])
        if cur is None or e["mse_full"] < cur[0]:
            best_full[e["dst"]] = (e["mse_full"], e["dir_acc_full"])
    metric_rows = []
    for i, res in results.items():
        sym = panel.stocks[i]
        bf = best_full.get(sym)
        metric_rows.append({
            "run_id": run_id, "scope": "symbol", "symbol": sym,
            "mse_zero": res["mse_zero"], "mse_ar": res["mse_ar"],
            "mse_factor": res["mse_factor"],
            "mse_full": bf[0] if bf else res["mse_ar"],
            "dir_acc_ar": res["dir_acc_ar"], "dir_acc_factor": res["dir_acc_factor"],
            "dir_acc_full": bf[1] if bf else res["dir_acc_ar"],
            "brier_full": 0.0, "rank_ic": 0.0,
            "ar_coef": res["ar_coef"], "resid_std": res["resid_std"],
            "n_obs": res["n_obs"],
        })
    # pooled "overall" row
    if results:
        act = np.concatenate([results[i]["actual"] for i in results])
        par = np.concatenate([results[i]["pred_ar"] for i in results])
        pfa = np.concatenate([results[i]["pred_factor"] for i in results])
        def _mse(a, p): return float(np.mean((a - p) ** 2))
        def _da(a, p):
            m = np.abs(a) > 1e-12
            return float(np.mean(np.sign(p[m]) == np.sign(a[m]))) if m.any() else 0.0
        metric_rows.append({
            "run_id": run_id, "scope": "overall", "symbol": "ALL",
            "mse_zero": _mse(act, np.zeros_like(act)), "mse_ar": _mse(act, par),
            "mse_factor": _mse(act, pfa), "mse_full": _mse(act, par),
            "dir_acc_ar": _da(act, par), "dir_acc_factor": _da(act, pfa),
            "dir_acc_full": _da(act, par), "brier_full": 0.0,
            "rank_ic": overall_ic if overall_ic == overall_ic else 0.0,
            "ar_coef": 0.0, "resid_std": 0.0, "n_obs": int(len(act)),
        })
    insert("forecast_metrics", metric_rows)

    # Phase 3 -----------------------------------------------------------------
    ar_coef = {panel.stocks[i]: results[i]["ar_coef"] for i in results}
    _, radius, clamped = build_matrix(panel.stocks, edges, ar_coef)

    # Phase 4: contemporaneous co-movement network (descriptive, undirected) ---
    comove = build_comovement(panel)
    insert("comovement_edges", [{"run_id": run_id, **e} for e in comove])

    return {
        "run_id": run_id,
        "n_obs": panel.n_obs,
        "universe": len(panel.stocks),
        "factors": panel.factors,
        "n_folds": nf,
        "low_power": nf < config.MIN_FOLDS,
        "n_candidates": n_candidates,
        "n_edges": len(edges),
        "edges": [{"src": e["src"], "dst": e["dst"], "coef": round(e["coef"], 5),
                   "improve_ar": round(e["improve_ar"], 4)} for e in edges],
        "overall_rank_ic": None if overall_ic != overall_ic else round(overall_ic, 4),
        "propagation_spectral_radius": round(radius, 4),
        "propagation_clamped": clamped,
        "n_comovement_edges": len(comove),
        "date_range": [panel.dates[0], panel.dates[-1]],
    }


if __name__ == "__main__":
    summary = rebuild()
    print(json.dumps(summary, indent=2))
