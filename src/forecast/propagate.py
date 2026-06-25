"""Shock propagation as a VAR(1) on residual returns, with a stability clamp.

The learned graph defines a linear map M where next-day residuals evolve as
``eps_t = M @ eps_{t-1} + innovation``. M's diagonal is each stock's own AR(1)
coefficient; off-diagonals are the kept edge coefficients (parent -> target).

Iterating M can be explosive if its spectral radius >= 1, so we rescale it below 1
before simulating (design note: propagation must stay bounded). Uncertainty comes
from a parametric residual bootstrap — per-stock Gaussian innovations with the
empirical residual std — so even unconnected stocks carry their own daily noise.
That is deliberate: it shows when a shock tells you almost nothing about a name.
"""
import numpy as np

from . import config


def build_matrix(
    stocks: list[str], edges: list[dict], ar_coef: dict[str, float]
) -> tuple[np.ndarray, float, bool]:
    """Assemble the VAR(1) matrix M and clamp it to spectral radius < 1.

    Returns (M, spectral_radius_after, was_clamped). ``edges`` use 'src'/'dst'
    symbol names; ``ar_coef`` maps symbol -> own lag-1 coefficient.
    """
    idx = {s: k for k, s in enumerate(stocks)}
    n = len(stocks)
    M = np.zeros((n, n))
    for s in stocks:
        M[idx[s], idx[s]] = ar_coef.get(s, 0.0)
    for e in edges:
        if e["src"] in idx and e["dst"] in idx:
            M[idx[e["dst"]], idx[e["src"]]] = e["coef"]

    radius = float(np.max(np.abs(np.linalg.eigvals(M)))) if n else 0.0
    clamped = False
    if radius >= 1.0:
        M = M * (config.SPECTRAL_CLAMP / radius)
        radius = config.SPECTRAL_CLAMP
        clamped = True
    return M, radius, clamped


def simulate_shock(
    stocks: list[str],
    M: np.ndarray,
    resid_std: dict[str, float],
    shocked: str,
    shock_pct: float,
    horizon: int = config.DEFAULT_HORIZON,
    paths: int = config.MC_PATHS,
    seed: int = 0,
) -> list[dict]:
    """Propagate a one-off shock to ``shocked`` and return per-step, per-stock stats.

    ``shock_pct`` is the initial residual-return impulse in percent (e.g. 5.0).
    Reports cumulative impact (in %) at each step 1..horizon with 50%/90% intervals
    and probabilities, derived from a Monte-Carlo residual bootstrap.
    """
    idx = {s: k for k, s in enumerate(stocks)}
    n = len(stocks)
    if shocked not in idx:
        raise ValueError(f"{shocked} not in universe")

    sigma = np.array([resid_std.get(s, 0.0) for s in stocks])
    shock0 = np.zeros(n)
    shock0[idx[shocked]] = shock_pct / 100.0

    rng = np.random.default_rng(seed)
    large = config.LARGE_MOVE_PCT / 100.0

    # deterministic mean: zero-mean innovations => expectation is the noise-free path
    eps_det = shock0.copy()
    cum_det = np.zeros(n)
    det_by_step = []
    for _ in range(horizon):
        eps_det = M @ eps_det
        cum_det = cum_det + eps_det
        det_by_step.append(cum_det.copy())

    # Monte-Carlo paths for the intervals/probabilities
    cum_paths = np.zeros((paths, horizon, n))
    for p in range(paths):
        eps = shock0.copy()
        cum = np.zeros(n)
        for h in range(horizon):
            noise = rng.normal(0.0, sigma)
            eps = M @ eps + noise
            cum = cum + eps
            cum_paths[p, h] = cum

    out = []
    for h in range(horizon):
        step = cum_paths[:, h, :]                 # (paths, n)
        for k, sym in enumerate(stocks):
            col = step[:, k]
            out.append({
                "affected_symbol": sym,
                "step": h + 1,
                "mean_impact": round(det_by_step[h][k] * 100, 4),
                "p05": round(float(np.percentile(col, 5)) * 100, 4),
                "p25": round(float(np.percentile(col, 25)) * 100, 4),
                "p75": round(float(np.percentile(col, 75)) * 100, 4),
                "p95": round(float(np.percentile(col, 95)) * 100, 4),
                "prob_up": round(float(np.mean(col > 0)), 4),
                "prob_down": round(float(np.mean(col < 0)), 4),
                "prob_large": round(float(np.mean(np.abs(col) >= large)), 4),
            })
    return out
