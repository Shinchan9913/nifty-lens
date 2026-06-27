# NSE Dependency Forecasting Pipeline

A statistically *controlled* dependency graph for NSE daily returns — not a raw
correlation graph. Each directed edge is a lagged relationship between **residual**
returns (returns with common market/sector/macro variation removed) that has been
validated walk-forward against fixed baselines before being kept.

```
python -m src.forecast.pipeline          # rebuild graph + metrics + propagation map
```

## Pipeline

| Phase | Module | What it does |
|------|--------|--------------|
| 1 | `data.py` | Align daily log returns for the NSE universe + the locked factor set into one panel. |
| 2 | `model.py`, `graph.py` | Fold-local residualisation → screen candidates → walk-forward nested model comparison → gate edges. |
| 3 | `propagate.py` | Build a VAR(1) propagation map from kept edges + AR coefficients; clamp for stability; shock-simulate with a residual bootstrap. |

Outputs land in ClickHouse: `forecast_runs`, `dependency_edges`, `forecast_metrics`,
`shock_results`. API: `src/api/dependencies.py`. Agent tools: `get_dependency_*`.

## Design decisions (why this differs from a naive plan)

1. **Fold-local residualisation, no global residual table.** Factor betas are
   estimated on each walk-forward *training* window only. Persisting one global
   residual series would leak the future into the past and silently invalidate the
   validation — so there is deliberately no `residual_returns` table.
2. **Lag-1 only.** At daily frequency with ~250 observations, multi-lag models
   overfit. One lag also makes propagation a clean VAR(1).
3. **Small, locked factor set.** Market (NIFTY) + 3 sector indices + USDINR + crude
   + gold + India VIX. No "if available" — a factor set that varies run-to-run
   changes the residuals run-to-run.
4. **OOS + persistence gating, not p-values.** With O(N²) candidate edges,
   significance tests false-discover heavily. An edge survives only if the full
   model (own lag + parent lag) beats **both** the AR-only and factor-only baselines
   out of sample, with a sign-consistent coefficient across folds.
5. **Zero edges is a valid outcome.** Thresholds are pre-registered in `config.py`
   and never loosened to manufacture a graph. Daily large-cap lead-lag is mostly
   arbitraged away; an empty or sparse graph is the honest result.
6. **Liquidity-comparable universe.** The seeded NSE names are liquid large/mid caps,
   which limits the non-synchronous-trading artefacts that create spurious daily
   lead-lag between names of very different liquidity.
7. **Stability-clamped propagation.** If the VAR(1) spectral radius ≥ 1, the matrix
   is rescaled below 1 before simulation so shocks stay bounded.

All outputs are **probabilistic scenario analysis, not causal claims or investment
advice.** Granger-style lead-lag ≠ causation; the shock simulator is a what-if, not
an intervention.

## Known V1 limits

- ~1 year of daily history (~250 obs) → statistical power is low; runs with
  `n_folds < MIN_FOLDS` are flagged `low_power`.
- India VIX falls back to US VIX when its history is too short.
- Screening uses full-sample residual correlation to *rank* candidates (cheap); it
  cannot make a bad edge pass, since validity is decided purely out of sample.
- Later phases (deferred): news/event factors, regime-aware graphs, multi-lag/GNN.
