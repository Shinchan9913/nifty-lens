"""Candidate screening and the pre-registered edge-gating decision rule.

Screening (cheap, full-sample lagged-residual correlation) only decides *which*
parents get the expensive walk-forward test — it never decides whether an edge is
real. Validity is decided solely by out-of-sample improvement + sign persistence,
so the screening leak cannot manufacture a surviving edge.
"""
import numpy as np

from . import config
from .data import Panel
from .model import _residuals, evaluate_target


def screen_candidates(panel: Panel) -> dict[int, list[int]]:
    """For each target i, the top-k other stocks by |lag-1 residual correlation|."""
    F = panel.factor_ret
    # full-sample residuals, used only to rank candidates
    eps = np.column_stack([
        _residuals(panel.stock_ret[:, k], F, panel.n_obs) for k in range(len(panel.stocks))
    ])
    out: dict[int, list[int]] = {}
    for i in range(len(panel.stocks)):
        target_next = eps[1:, i]
        scores = []
        for j in range(len(panel.stocks)):
            if j == i:
                continue
            parent_lag = eps[:-1, j]
            sd = parent_lag.std() * target_next.std()
            corr = float(np.mean((parent_lag - parent_lag.mean()) * (target_next - target_next.mean())) / sd) if sd else 0.0
            if abs(corr) >= config.SCREEN_MIN_ABS_CORR:
                scores.append((abs(corr), j))
        scores.sort(reverse=True)
        out[i] = [j for _, j in scores[: config.MAX_CANDIDATES_PER_TARGET]]
    return out


def _passes(p: dict, target_dir_acc_ar: float) -> bool:
    """All gates must pass. Zero passing edges is an acceptable outcome."""
    return (
        p["improve_ar"] >= config.MIN_IMPROVE_AR
        and p["improve_factor"] >= config.MIN_IMPROVE_FACTOR
        and p["sign_consistency"] >= config.MIN_SIGN_CONSISTENCY
        and (p["dir_acc_full"] - target_dir_acc_ar) >= config.MIN_DIR_ACC_GAIN
        and p["folds_total"] > 0
        and (p["folds_improved"] / p["folds_total"]) >= config.MIN_FOLD_IMPROVE_FRAC
    )


def build_graph(panel: Panel) -> tuple[list[dict], dict[int, dict], int]:
    """Evaluate every target and return (kept_edges, per_target_results, n_candidates).

    ``per_target_results`` keeps the full walk-forward output per target (for
    metrics + propagation). ``kept_edges`` are the parents that passed all gates.
    """
    candidates = screen_candidates(panel)
    n_candidates = sum(len(v) for v in candidates.values())
    results: dict[int, dict] = {}
    edges: list[dict] = []

    for i in range(len(panel.stocks)):
        res = evaluate_target(panel, i, candidates.get(i, []))
        if not res:
            continue
        results[i] = res
        for j, p in res["parents"].items():
            if _passes(p, res["dir_acc_ar"]):
                edges.append({
                    "src": panel.stocks[j],
                    "dst": panel.stocks[i],
                    "src_idx": j,
                    "dst_idx": i,
                    "lag": config.LAG,
                    "coef": p["coef"],
                    "sign_consistency": p["sign_consistency"],
                    "mse_full": p["mse_full"],
                    "mse_ar": res["mse_ar"],
                    "mse_factor": res["mse_factor"],
                    "improve_ar": p["improve_ar"],
                    "improve_factor": p["improve_factor"],
                    "dir_acc_full": p["dir_acc_full"],
                    "folds_improved": p["folds_improved"],
                    "folds_total": p["folds_total"],
                    "n_obs": res["n_obs"],
                })
    return edges, results, n_candidates


def rank_ic(results: dict[int, dict], stocks: list[str]) -> float:
    """Average cross-sectional Spearman rank IC of AR predictions vs actuals.

    OOS test blocks are identical across targets (folds depend only on n_obs), so
    per-target arrays are position-aligned and can be stacked by date.
    """
    cols = [i for i in results if len(results[i]["pred_ar"])]
    if len(cols) < 3:
        return float("nan")
    n = min(len(results[i]["pred_ar"]) for i in cols)
    pred = np.column_stack([results[i]["pred_ar"][:n] for i in cols])
    actual = np.column_stack([results[i]["actual"][:n] for i in cols])
    ics = []
    for t in range(n):
        pr = _rankdata(pred[t]); ac = _rankdata(actual[t])
        sd = pr.std() * ac.std()
        if sd:
            ics.append(float(np.mean((pr - pr.mean()) * (ac - ac.mean())) / sd))
    return float(np.mean(ics)) if ics else float("nan")


def _rankdata(a: np.ndarray) -> np.ndarray:
    """Average-rank of each element (ties shared), dependency-free Spearman helper."""
    order = a.argsort()
    ranks = np.empty(len(a), dtype=float)
    ranks[order] = np.arange(len(a), dtype=float)
    # resolve ties to average rank
    _, inv, counts = np.unique(a, return_inverse=True, return_counts=True)
    csum = np.cumsum(counts)
    start = csum - counts
    avg = (start + csum - 1) / 2.0
    return avg[inv]
