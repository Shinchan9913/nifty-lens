"""Contemporaneous co-movement network via regularized partial correlations.

Unlike the predictive lag-1 graph, this is a DESCRIPTIVE same-day model: an
(undirected) edge means two stocks' factor-removed returns move together on the
SAME day even after controlling for every other stock in the universe — a direct,
conditional dependency (a partial correlation), not just raw correlation.

This is the graphical-model / partial-correlation-network approach from the
econophysics literature. We regularize the precision (inverse correlation) matrix
by shrinking toward the identity — the stable workhorse; full L1 graphical-lasso
is known to be unstable on highly correlated data — then threshold the partial
correlations. A correlation minimum-spanning-tree backbone is also marked so the
network is always connected and readable.

Association, not prediction, and not causal.
"""
import numpy as np

from . import config
from .data import Panel
from .model import _residuals


def _residual_matrix(panel: Panel) -> np.ndarray:
    """(T, N) factor-removed residual returns, full-sample betas (descriptive use)."""
    F = panel.factor_ret
    return np.column_stack([
        _residuals(panel.stock_ret[:, k], F, panel.n_obs) for k in range(len(panel.stocks))
    ])


def _partial_correlations(corr: np.ndarray, shrink: float) -> np.ndarray:
    """Partial-correlation matrix from a shrinkage-regularized precision matrix."""
    n = corr.shape[0]
    reg = (1 - shrink) * corr + shrink * np.eye(n)
    theta = np.linalg.inv(reg)
    d = np.sqrt(np.diag(theta))
    pcorr = -theta / np.outer(d, d)
    np.fill_diagonal(pcorr, 1.0)
    return pcorr


def _mst_pairs(corr: np.ndarray) -> set[frozenset]:
    """Prim's MST on the correlation distance sqrt(2(1-corr)); returns {i,j} pairs."""
    n = corr.shape[0]
    dist = np.sqrt(np.clip(2.0 * (1.0 - corr), 0.0, None))
    in_tree = np.zeros(n, dtype=bool)
    in_tree[0] = True
    best = dist[0].copy()
    parent = np.zeros(n, dtype=int)
    pairs: set[frozenset] = set()
    for _ in range(n - 1):
        masked = np.where(in_tree, np.inf, best)
        j = int(np.argmin(masked))
        pairs.add(frozenset((int(parent[j]), j)))
        in_tree[j] = True
        upd = (dist[j] < best) & (~in_tree)
        best = np.where(upd, dist[j], best)
        parent = np.where(upd, j, parent)
    return pairs


def build_comovement(panel: Panel) -> list[dict]:
    """Undirected co-movement edges: strong direct partial correlations + MST backbone."""
    resid = _residual_matrix(panel)
    xc = resid - resid.mean(axis=0)
    cov = (xc.T @ xc) / len(xc)
    sd = np.sqrt(np.diag(cov))
    corr = cov / np.outer(sd, sd)
    np.fill_diagonal(corr, 1.0)

    pcorr = _partial_correlations(corr, config.COMOVE_SHRINKAGE)
    mst = _mst_pairs(corr)
    stocks = panel.stocks
    n = len(stocks)

    edges = []
    for i in range(n):
        for j in range(i + 1, n):
            in_mst = frozenset((i, j)) in mst
            if abs(pcorr[i, j]) >= config.COMOVE_MIN_PCORR or in_mst:
                edges.append({
                    "a": stocks[i], "b": stocks[j],
                    "partial_corr": round(float(pcorr[i, j]), 4),
                    "corr": round(float(corr[i, j]), 4),
                    "in_mst": 1 if in_mst else 0,
                })
    return edges
