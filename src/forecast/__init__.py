"""Controlled NSE dependency-forecasting pipeline.

Models daily NSE *residual* returns (returns with common market/sector/macro
variation removed), learns directed lagged dependencies between them, and
validates every edge walk-forward against fixed baselines before keeping it.

See ``config.py`` for the locked hyper-parameters and the design rationale.
"""
