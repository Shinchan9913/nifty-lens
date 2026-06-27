"""The statistical core: fold-local residualisation + nested walk-forward.

For each target stock we compare four predictors of its *next-day residual return*
out of sample, refitting on an expanding window:

    B0  zero            : predict 0
    B1  AR-only         : own lag-1 residual
    B2  factor-only     : lag-1 factor returns
    full (per parent)   : own lag-1 residual + a candidate parent's lag-1 residual

Residuals themselves are recomputed inside every fold from factor betas fit on
that fold's TRAINING window only (design note 2). A parent edge is only ever
considered real if the full model beats BOTH B1 and B2 out of sample.
"""
import math

import numpy as np

from . import config
from .data import Panel


# --- small numeric helpers ----------------------------------------------------
def _ols(x_tr: np.ndarray, y_tr: np.ndarray, x_te: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Fit OLS with intercept on (x_tr, y_tr); return (coef, predictions on x_te)."""
    a_tr = np.column_stack([np.ones(len(x_tr)), x_tr])
    coef, *_ = np.linalg.lstsq(a_tr, y_tr, rcond=None)
    a_te = np.column_stack([np.ones(len(x_te)), x_te])
    return coef, a_te @ coef


def _residuals(r_col: np.ndarray, factors: np.ndarray, train_end: int) -> np.ndarray:
    """Residual return series for one stock, using factor betas fit on [0:train_end).

    Contemporaneous factor regression (this is the *explanatory* residualisation),
    but the betas only ever see the training window — no look-ahead.
    """
    a_tr = np.column_stack([np.ones(train_end), factors[:train_end]])
    beta, *_ = np.linalg.lstsq(a_tr, r_col[:train_end], rcond=None)
    a_full = np.column_stack([np.ones(len(r_col)), factors])
    return r_col - a_full @ beta


def _mse(actual: np.ndarray, pred: np.ndarray) -> float:
    return float(np.mean((actual - pred) ** 2)) if len(actual) else float("nan")


def _dir_acc(actual: np.ndarray, pred: np.ndarray) -> float:
    """Directional accuracy over observations where the actual move is non-trivial."""
    mask = np.abs(actual) > 1e-12
    if not mask.any():
        return float("nan")
    return float(np.mean(np.sign(pred[mask]) == np.sign(actual[mask])))


def _norm_cdf(x: np.ndarray) -> np.ndarray:
    return 0.5 * (1.0 + np.vectorize(math.erf)(x / math.sqrt(2.0)))


def _brier(actual: np.ndarray, pred: np.ndarray, sigma: float) -> float:
    """Brier score of P(up), where P(up)=Phi(pred/sigma)."""
    if sigma <= 0 or not len(actual):
        return float("nan")
    p_up = _norm_cdf(pred / sigma)
    return float(np.mean((p_up - (actual > 0).astype(float)) ** 2))


# --- per-target walk-forward --------------------------------------------------
def _folds(n_obs: int) -> list[tuple[int, int]]:
    """Expanding-window test blocks: (split, end), train is [1, split), test [split, end)."""
    out = []
    for s in range(config.MIN_TRAIN, n_obs, config.TEST_BLOCK):
        e = min(s + config.TEST_BLOCK, n_obs)
        if e - s >= 2:  # need at least a couple of test points
            out.append((s, e))
    return out


def evaluate_target(panel: Panel, i: int, parents: list[int]) -> dict:
    """Walk-forward evaluate target stock ``i`` and every candidate parent.

    Returns baseline OOS series for the target plus, per parent, the full-model
    OOS series and the per-fold diagnostics used for gating.
    """
    r_i = panel.stock_ret[:, i]
    F = panel.factor_ret
    folds = _folds(panel.n_obs)

    # accumulators (concatenated across folds)
    act, p_zero, p_ar, p_fac = [], [], [], []
    parent_acc = {
        j: {"pred": [], "coefs": [], "folds_improved": 0, "folds_total": 0}
        for j in parents
    }

    for (s, e) in folds:
        eps_i = _residuals(r_i, F, s)            # target residuals, this fold's betas
        # design slices (predictor at t-1, target at t)
        tr = slice(0, s - 1)                     # train t in [1, s)  -> predictors [0, s-1)
        te = slice(s - 1, e - 1)                 # test  t in [s, e)  -> predictors [s-1, e-1)
        y_tr, y_te = eps_i[1:s], eps_i[s:e]

        # B1 AR-only
        _, pr_ar = _ols(eps_i[tr][:, None], y_tr, eps_i[te][:, None])
        # B2 factor-only (lagged factors)
        _, pr_fac = _ols(F[tr], y_tr, F[te])

        act.append(y_te); p_zero.append(np.zeros_like(y_te))
        p_ar.append(pr_ar); p_fac.append(pr_fac)
        mse_ar_fold = _mse(y_te, pr_ar)

        for j in parents:
            eps_j = _residuals(panel.stock_ret[:, j], F, s)
            x_tr = np.column_stack([eps_i[tr], eps_j[tr]])
            x_te = np.column_stack([eps_i[te], eps_j[te]])
            coef, pr_full = _ols(x_tr, y_tr, x_te)
            pa = parent_acc[j]
            pa["pred"].append(pr_full)
            pa["coefs"].append(coef[2])          # [intercept, own, parent]
            pa["folds_total"] += 1
            if _mse(y_te, pr_full) < mse_ar_fold:
                pa["folds_improved"] += 1

    if not folds:
        return {}

    actual = np.concatenate(act)
    pred_ar = np.concatenate(p_ar)
    pred_fac = np.concatenate(p_fac)

    # full-sample AR(1) for the propagation map + bootstrap scale
    eps_full = _residuals(r_i, F, panel.n_obs)
    ar_coef_fs, ar_fit = _ols(eps_full[:-1, None], eps_full[1:], eps_full[:-1, None])
    ar_coef = float(ar_coef_fs[1])
    resid_std = float(np.std(eps_full[1:] - ar_fit))

    out = {
        "actual": actual,
        "pred_zero": np.concatenate(p_zero),
        "pred_ar": pred_ar,
        "pred_factor": pred_fac,
        "mse_zero": _mse(actual, np.zeros_like(actual)),
        "mse_ar": _mse(actual, pred_ar),
        "mse_factor": _mse(actual, pred_fac),
        "dir_acc_ar": _dir_acc(actual, pred_ar),
        "dir_acc_factor": _dir_acc(actual, pred_fac),
        "ar_coef": ar_coef,
        "resid_std": resid_std,
        "n_obs": int(len(actual)),
        "parents": {},
    }
    for j, pa in parent_acc.items():
        if not pa["pred"]:
            continue
        pred_full = np.concatenate(pa["pred"])
        coefs = np.array(pa["coefs"])
        mse_full = _mse(actual, pred_full)
        # sign consistency: fraction of folds whose parent coef matches the mean sign
        mean_sign = np.sign(np.mean(coefs)) or 1.0
        sign_consistency = float(np.mean(np.sign(coefs) == mean_sign))
        out["parents"][j] = {
            "pred_full": pred_full,
            "coef": float(np.mean(coefs)),
            "sign_consistency": sign_consistency,
            "mse_full": mse_full,
            "dir_acc_full": _dir_acc(actual, pred_full),
            "brier_full": _brier(actual, pred_full, resid_std),
            "improve_ar": (out["mse_ar"] - mse_full) / out["mse_ar"] if out["mse_ar"] else 0.0,
            "improve_factor": (out["mse_factor"] - mse_full) / out["mse_factor"] if out["mse_factor"] else 0.0,
            "folds_improved": pa["folds_improved"],
            "folds_total": pa["folds_total"],
        }
    return out


def n_folds(n_obs: int) -> int:
    return len(_folds(n_obs))
