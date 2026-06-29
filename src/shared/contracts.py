"""Unified data contracts — the single source of truth for the Glass Desk platform.

These Pydantic v2 models define the shapes that data must have as it crosses every
boundary in the system:

  - the frontend POSTs a `StrategyPayload` to /api/strategies/execute
  - specialist agents emit `ProvenanceClaim`s, each carrying an `EvidenceItem` ledger
  - the order-flow node reads `MarketDepthPayload`s from ClickHouse

Validation happens at construction: bad operators, unknown timeframes, out-of-range
stop-losses, or stray fields are rejected immediately rather than surfacing as a crash
deep in an agent loop. All deterministic math (e.g. the bid-ask imbalance) lives here in
Python — never inside an LLM prompt.

Pydantic v2 note: configuration uses `model_config = ConfigDict(...)`, not the v1
`class Config:` inner class.
"""
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

# Reused literal types so the allowed values live in exactly one place.
Operator = Literal[">", "<", "==", "crosses_above", "crosses_below"]
Timeframe = Literal["1m", "5m", "15m", "1d"]
EvidenceSource = Literal["clickhouse", "web_search"]
Confidence = Literal["confirmed", "uncertain", "refuted"]


class ConditionBlock(BaseModel):
    """One rule in a strategy, e.g. RSI < 35 or Volume_Spike crosses_above 2.

    `value` is a string because the frontend sends form inputs as text and a value may
    be expressed as "35" or "75%". Whoever evaluates the rule parses it deterministically
    in Python; the LLM never does the comparison.
    """

    model_config = ConfigDict(extra="forbid")

    indicator: str = Field(description="e.g. RSI, Volume_Spike, Event_Probability")
    operator: Operator
    value: str


class StrategyPayload(BaseModel):
    """A custom strategy submitted by the user and executed by the desk."""

    model_config = ConfigDict(extra="forbid")

    strategy_name: str
    ticker: str
    timeframe: Timeframe
    entry_rules: list[ConditionBlock] = Field(min_length=1)
    exit_rules: list[ConditionBlock] = Field(default_factory=list)
    # A percentage: must be positive and at most 100.
    stop_loss_pct: float = Field(gt=0, le=100)

    @field_validator("ticker")
    @classmethod
    def _normalize_ticker(cls, v: str) -> str:
        # Match the symbol convention used across tools.py (upper-case, trimmed).
        return v.strip().upper()


class EvidenceItem(BaseModel):
    """A single, immutable piece of evidence backing a claim.

    Captures *exactly* what was run and what came back, anchored to a snapshot time so
    the run is reproducible — the core of the "Glass Desk" promise.
    """

    model_config = ConfigDict(extra="forbid")

    source: EvidenceSource
    query_string: str = Field(description="The exact SQL or search query executed.")
    extracted_fact: str = Field(description="The raw fact pulled from the result.")
    snapshot_timestamp: str = Field(description="Immutable as-of anchor (ISO string).")


class ProvenanceClaim(BaseModel):
    """An agent's assertion, its verification verdict, and the evidence behind it.

    `confidence` defaults to "uncertain": until the Verifier audits a claim against its
    evidence, we assume nothing. `claim_id` is auto-generated so producers don't have to.
    """

    model_config = ConfigDict(extra="forbid")

    claim_id: str = Field(default_factory=lambda: uuid4().hex)
    agent_name: str
    assertion: str
    confidence: Confidence = "uncertain"
    evidence_ledger: list[EvidenceItem] = Field(default_factory=list)


class OrderBookLevel(BaseModel):
    """One price level in a Level-2 order book (a single bid or ask)."""

    model_config = ConfigDict(extra="forbid")

    price: float
    quantity: int
    orders_count: int = 0  # broker feeds don't always report this


class MarketDepthPayload(BaseModel):
    """A Level-2 (5-deep) order book snapshot for one ticker at one instant."""

    model_config = ConfigDict(extra="forbid")

    ticker: str
    timestamp: str
    total_buy_quantity: int
    total_sell_quantity: int
    bids: list[OrderBookLevel] = Field(default_factory=list)
    asks: list[OrderBookLevel] = Field(default_factory=list)

    @computed_field  # serialized alongside the model; computed in Python, not the LLM
    @property
    def bid_ask_imbalance(self) -> float:
        """(buy - sell) / (buy + sell), in [-1, 1]; 0.0 for an empty book.

        Positive => buy-side pressure, negative => sell-side. The order-flow node flags
        |imbalance| > 0.15 as a liquidity wall.
        """
        total = self.total_buy_quantity + self.total_sell_quantity
        if total == 0:
            return 0.0
        return (self.total_buy_quantity - self.total_sell_quantity) / total
