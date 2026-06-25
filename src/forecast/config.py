"""Locked, pre-registered configuration for the dependency forecaster.

Everything that could be turned into a researcher degree-of-freedom lives here as
a named constant, set ONCE, before looking at any out-of-sample result. This is
the discipline that keeps the walk-forward validation honest: you cannot tune
these against the test folds because they are fixed up front and reviewed in code.

Design notes (the corrections that shaped V1):
  1. LAG = 1 only. At daily frequency with ~250 observations, multi-lag models
     overfit. One lag keeps the parameter count sane and makes the propagation
     map a clean VAR(1).
  2. Residualisation is FOLD-LOCAL (see model.py): factor betas are estimated on
     each training window only. We never persist a global residual series — that
     would leak the future into the past. Hence there is no residual_returns table.
  3. The factor set is SMALL and fixed (market + 3 sectors + FX + crude + gold +
     vol). "If available" is not allowed; a factor set that varies run-to-run
     changes the residuals run-to-run.
  4. Edges are gated by OUT-OF-SAMPLE improvement + sign persistence, NOT by an
     in-sample p-value. With O(N^2) candidate edges, significance tests
     false-discover heavily; persistence across folds is the robust filter.
  5. ZERO surviving edges is a valid, reportable outcome. Thresholds are never
     loosened to manufacture a graph.
"""

# --- factor model -------------------------------------------------------------
# The locked factor set, by our stored macro_bars symbol. Order is stable.
MARKET_FACTOR = "NIFTY"
SECTOR_FACTORS = ["NIFTY_BANK", "NIFTY_IT", "NIFTY_METAL"]
MACRO_FACTORS = ["USDINR", "BRENT", "GOLD", "INDIAVIX"]
# INDIAVIX may be absent for some history; data.py falls back to VIX if so.
VIX_FALLBACK = "VIX"


def factor_symbols() -> list[str]:
    """The full ordered factor list used to residualise stock returns."""
    return [MARKET_FACTOR, *SECTOR_FACTORS, *MACRO_FACTORS]


# --- dynamics -----------------------------------------------------------------
LAG = 1  # see design note 1

# --- walk-forward validation --------------------------------------------------
MIN_TRAIN = 120          # minimum training observations before the first test fold
TEST_BLOCK = 21          # ~1 trading month per expanding-window test block
MIN_FOLDS = 3            # below this the run is flagged low-power (still reported)

# --- candidate screening ------------------------------------------------------
# Cap candidate parents per target to limit the multiple-comparison surface.
MAX_CANDIDATES_PER_TARGET = 6
SCREEN_MIN_ABS_CORR = 0.05   # train-window |lagged residual corr| to be a candidate

# --- edge gating (all must pass) ---------------------------------------------
MIN_IMPROVE_AR = 0.02        # full model must cut AR-only OOS MSE by >= 2%
MIN_IMPROVE_FACTOR = 0.02    # ... and lagged-factor-only OOS MSE by >= 2%
MIN_DIR_ACC_GAIN = 0.0       # full directional accuracy >= AR directional accuracy
MIN_SIGN_CONSISTENCY = 0.70  # parent coef keeps its sign in >= 70% of folds
MIN_FOLD_IMPROVE_FRAC = 0.50  # full beats AR in >= half the folds (persistence)
MIN_OBS = MIN_TRAIN + TEST_BLOCK  # absolute floor on usable observations

# --- co-movement network (contemporaneous partial correlations) ---------------
# Descriptive same-day graph, NOT predictive. Shrinkage stabilises the precision
# matrix (full L1 graphical-lasso is unstable on highly correlated data); we then
# threshold the partial correlations. These are display/exploration knobs, not an
# inferential test, so they may be tuned for readability.
COMOVE_SHRINKAGE = 0.2       # shrink correlation toward identity before inverting
COMOVE_MIN_PCORR = 0.08      # |partial correlation| to draw a direct edge

# --- shock propagation --------------------------------------------------------
DEFAULT_HORIZON = 5          # trading days
MC_PATHS = 2000              # Monte-Carlo / residual-bootstrap paths
LARGE_MOVE_PCT = 1.0         # |cumulative impact| >= this (%) counts as a "large move"
SPECTRAL_CLAMP = 0.95        # if VAR(1) spectral radius >= 1, rescale to this (stability)


def gating_params() -> dict:
    """Serialisable snapshot of the gates, stored on each run for audit."""
    return {
        "lag": LAG,
        "min_train": MIN_TRAIN,
        "test_block": TEST_BLOCK,
        "max_candidates_per_target": MAX_CANDIDATES_PER_TARGET,
        "screen_min_abs_corr": SCREEN_MIN_ABS_CORR,
        "min_improve_ar": MIN_IMPROVE_AR,
        "min_improve_factor": MIN_IMPROVE_FACTOR,
        "min_dir_acc_gain": MIN_DIR_ACC_GAIN,
        "min_sign_consistency": MIN_SIGN_CONSISTENCY,
        "min_fold_improve_frac": MIN_FOLD_IMPROVE_FRAC,
        "spectral_clamp": SPECTRAL_CLAMP,
    }
