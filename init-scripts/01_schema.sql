-- Groww tick data: one-minute candles per symbol
CREATE TABLE IF NOT EXISTS tick_data (
    symbol          String,
    exchange        String,
    timestamp       DateTime64(3, 'Asia/Kolkata'),
    open            Float64,
    high            Float64,
    low             Float64,
    close           Float64,
    volume          Float64
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(timestamp)
ORDER BY (symbol, timestamp);

-- Multi-day daily bars (US + NSE equities) for trend/regime/event context
CREATE TABLE IF NOT EXISTS daily_bars (
    symbol      String,
    exchange    String,
    date        Date,
    open        Float64,
    high        Float64,
    low         Float64,
    close       Float64,
    volume      Float64
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(date)
ORDER BY (symbol, date);

-- Macro / cross-asset daily series (indices, commodities, FX, rates, crypto, vol)
CREATE TABLE IF NOT EXISTS macro_bars (
    symbol      String,
    category    String,
    date        Date,
    open        Float64,
    high        Float64,
    low         Float64,
    close       Float64
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(date)
ORDER BY (symbol, date);

-- Materialized view: 5-min candles from 1-min data
CREATE MATERIALIZED VIEW IF NOT EXISTS tick_data_5min
ENGINE = MergeTree()
PARTITION BY toYYYYMM(window_start)
ORDER BY (symbol, window_start)
AS SELECT
    symbol,
    exchange,
    toStartOfFiveMinutes(timestamp) AS window_start,
    argMin(open, timestamp) AS open,
    max(high) AS high,
    min(low) AS low,
    argMax(close, timestamp) AS close,
    sum(volume) AS volume
FROM tick_data
GROUP BY symbol, exchange, window_start;

-- ============================================================================
-- Dependency forecasting pipeline (derived layer).
--
-- These tables hold ONLY model outputs. Residual returns are deliberately NOT
-- stored: residualisation is fold-local (factor betas are fit on each
-- walk-forward training window) so a persisted global residual series would
-- re-introduce look-ahead leakage. See src/forecast/.
-- ============================================================================

-- One row per rebuild. The audit header for a graph: universe, locked factor
-- set, sample window, and the pre-registered hyper-parameters used.
CREATE TABLE IF NOT EXISTS forecast_runs (
    run_id        String,
    created_at    DateTime DEFAULT now(),
    universe      Array(String),
    factors       Array(String),
    n_obs         UInt32,
    date_start    Date,
    date_end      Date,
    lag           UInt8,
    min_train     UInt32,
    n_folds       UInt16,
    n_candidates  UInt32,
    n_edges       UInt32,
    params        String,        -- JSON of the locked gating thresholds
    notes         String
)
ENGINE = MergeTree()
ORDER BY (run_id);

-- Directed lagged dependency edges (src drives dst) that PASSED walk-forward
-- gating: the full model (own AR lag + this parent's lagged residual) beat both
-- the AR-only and lagged-factor-only baselines out of sample, with a stable sign.
CREATE TABLE IF NOT EXISTS dependency_edges (
    run_id           String,
    src              String,     -- driver / parent symbol (j)
    dst              String,     -- target symbol (i): src -> dst at lag
    lag              UInt8,
    coef             Float64,     -- parent's lagged-residual coefficient in the full model
    sign_consistency Float64,     -- fraction of folds where coef kept its sign
    mse_full         Float64,
    mse_ar           Float64,
    mse_factor       Float64,
    improve_ar       Float64,     -- (mse_ar - mse_full) / mse_ar
    improve_factor   Float64,     -- (mse_factor - mse_full) / mse_factor
    dir_acc_full     Float64,
    folds_improved   UInt16,
    folds_total      UInt16,
    n_obs            UInt32,
    created_at       DateTime DEFAULT now()
)
ENGINE = MergeTree()
ORDER BY (run_id, dst, src);

-- Per-symbol and overall model quality vs the locked baselines. scope is
-- 'symbol' or 'overall'. ar_coef / resid_std are kept so the shock simulator
-- can rebuild the VAR(1) propagation map without re-reading prices.
CREATE TABLE IF NOT EXISTS forecast_metrics (
    run_id         String,
    scope          String,        -- 'symbol' | 'overall'
    symbol         String,
    mse_zero       Float64,
    mse_ar         Float64,
    mse_factor     Float64,
    mse_full       Float64,
    dir_acc_ar     Float64,
    dir_acc_factor Float64,
    dir_acc_full   Float64,
    brier_full     Float64,
    rank_ic        Float64,        -- cross-sectional Spearman of pred vs actual (overall scope)
    ar_coef        Float64,        -- own lag-1 residual coefficient (for propagation)
    resid_std      Float64,        -- std of full-model residuals (for bootstrap)
    n_obs          UInt32,
    created_at     DateTime DEFAULT now()
)
ENGINE = MergeTree()
ORDER BY (run_id, scope, symbol);

-- Undirected co-movement network: contemporaneous (same-day) partial correlations
-- between residual returns — a DESCRIPTIVE graphical-model view, distinct from the
-- predictive directed edges above. in_mst flags the correlation MST backbone.
CREATE TABLE IF NOT EXISTS comovement_edges (
    run_id       String,
    a            String,
    b            String,
    partial_corr Float64,
    corr         Float64,
    in_mst       UInt8,
    created_at   DateTime DEFAULT now()
)
ENGINE = MergeTree()
ORDER BY (run_id, a, b);

-- Materialised shock-propagation scenarios (also computable on demand by the API).
CREATE TABLE IF NOT EXISTS shock_results (
    run_id          String,
    shocked_symbol  String,
    shock_pct       Float64,
    horizon         UInt8,
    affected_symbol String,
    step            UInt8,
    mean_impact     Float64,
    p05             Float64,
    p25             Float64,
    p75             Float64,
    p95             Float64,
    prob_up         Float64,
    prob_down       Float64,
    prob_large      Float64,
    created_at      DateTime DEFAULT now()
)
ENGINE = MergeTree()
ORDER BY (run_id, shocked_symbol, affected_symbol, step);