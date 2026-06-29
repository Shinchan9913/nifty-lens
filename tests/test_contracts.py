"""Phase 1 contracts: validation behavior is the spec.

These tests are written before src/shared/contracts.py and define exactly how the
Pydantic v2 models must accept good data and reject bad data. The frontend POSTs a
StrategyPayload; the agents produce ProvenanceClaims and EvidenceItems; the order-flow
node reads MarketDepthPayloads. If any of these drift, the tests fail.
"""
import pytest
from pydantic import ValidationError

from src.shared.contracts import (
    ConditionBlock,
    EvidenceItem,
    MarketDepthPayload,
    OrderBookLevel,
    ProvenanceClaim,
    StrategyPayload,
)


# --- ConditionBlock -----------------------------------------------------------
def test_condition_block_valid():
    cb = ConditionBlock(indicator="RSI", operator="<", value="35")
    assert cb.operator == "<"
    assert cb.value == "35"


def test_condition_block_rejects_unknown_operator():
    with pytest.raises(ValidationError):
        ConditionBlock(indicator="RSI", operator="=>", value="35")


def test_condition_block_accepts_cross_operators():
    cb = ConditionBlock(indicator="Volume_Spike", operator="crosses_above", value="2")
    assert cb.operator == "crosses_above"


# --- StrategyPayload ----------------------------------------------------------
def _good_strategy(**overrides):
    base = dict(
        strategy_name="Event Driven Mean Reversion",
        ticker="reliance",  # lower-case on purpose: should normalize
        timeframe="5m",
        entry_rules=[{"indicator": "RSI", "operator": "<", "value": "35"}],
        exit_rules=[{"indicator": "RSI", "operator": ">", "value": "70"}],
        stop_loss_pct=2.5,
    )
    base.update(overrides)
    return base


def test_strategy_payload_valid_roundtrip():
    s = StrategyPayload(**_good_strategy())
    assert s.timeframe == "5m"
    assert isinstance(s.entry_rules[0], ConditionBlock)
    # round-trips through JSON without loss
    assert StrategyPayload.model_validate_json(s.model_dump_json()) == s


def test_strategy_payload_normalizes_ticker():
    s = StrategyPayload(**_good_strategy(ticker="  reliance "))
    assert s.ticker == "RELIANCE"


def test_strategy_payload_rejects_bad_timeframe():
    with pytest.raises(ValidationError):
        StrategyPayload(**_good_strategy(timeframe="2h"))


def test_strategy_payload_requires_an_entry_rule():
    with pytest.raises(ValidationError):
        StrategyPayload(**_good_strategy(entry_rules=[]))


@pytest.mark.parametrize("bad", [0, -1, 150])
def test_strategy_payload_stop_loss_bounds(bad):
    with pytest.raises(ValidationError):
        StrategyPayload(**_good_strategy(stop_loss_pct=bad))


def test_strategy_payload_forbids_extra_fields():
    with pytest.raises(ValidationError):
        StrategyPayload(**_good_strategy(leverage=5))


# --- EvidenceItem -------------------------------------------------------------
def test_evidence_item_valid():
    e = EvidenceItem(
        source="clickhouse",
        query_string="SELECT max(timestamp) FROM tick_data",
        extracted_fact="latest tick at 2026-06-26 15:29:00",
        snapshot_timestamp="2026-06-26 15:29:00",
    )
    assert e.source == "clickhouse"


def test_evidence_item_rejects_unknown_source():
    with pytest.raises(ValidationError):
        EvidenceItem(
            source="bloomberg",
            query_string="x",
            extracted_fact="y",
            snapshot_timestamp="2026-06-26",
        )


# --- ProvenanceClaim ----------------------------------------------------------
def test_provenance_claim_defaults_to_uncertain_with_auto_id():
    c = ProvenanceClaim(agent_name="technical", assertion="NVDA broke its 50d SMA")
    assert c.confidence == "uncertain"
    assert c.claim_id  # auto-generated, non-empty
    assert c.evidence_ledger == []


def test_provenance_claim_unique_auto_ids():
    a = ProvenanceClaim(agent_name="risk", assertion="A")
    b = ProvenanceClaim(agent_name="risk", assertion="B")
    assert a.claim_id != b.claim_id


def test_provenance_claim_rejects_bad_confidence():
    with pytest.raises(ValidationError):
        ProvenanceClaim(agent_name="risk", assertion="x", confidence="maybe")


def test_provenance_claim_carries_evidence():
    e = EvidenceItem(
        source="web_search",
        query_string="RELIANCE earnings June 2026",
        extracted_fact="beat estimates",
        snapshot_timestamp="2026-06-26",
    )
    c = ProvenanceClaim(
        agent_name="research", assertion="Earnings beat", confidence="confirmed",
        evidence_ledger=[e],
    )
    assert c.evidence_ledger[0].source == "web_search"


# --- Order book ---------------------------------------------------------------
def test_order_book_level_valid():
    lvl = OrderBookLevel(price=2840.5, quantity=1200, orders_count=14)
    assert lvl.quantity == 1200


def test_market_depth_imbalance_is_deterministic():
    # (1150 - 850) / (1150 + 850) = 300 / 2000 = 0.15
    depth = MarketDepthPayload(
        ticker="RELIANCE",
        timestamp="2026-06-26 15:29:00.123",
        total_buy_quantity=1150,
        total_sell_quantity=850,
        bids=[OrderBookLevel(price=2840.0, quantity=600)],
        asks=[OrderBookLevel(price=2841.0, quantity=500)],
    )
    assert depth.bid_ask_imbalance == pytest.approx(0.15)


def test_market_depth_imbalance_zero_when_empty_book():
    depth = MarketDepthPayload(
        ticker="X", timestamp="2026-06-26", total_buy_quantity=0, total_sell_quantity=0,
        bids=[], asks=[],
    )
    assert depth.bid_ask_imbalance == 0.0
