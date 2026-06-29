"""Reflexion loop: the decision + merge logic that closes the adversarial loop.

The orchestrator's Reflexion step is: parse the Verifier's verdicts -> pick the refuted
ones that belong to a real specialist -> re-investigate -> fold the re-verified result back
in. The LLM calls are integration-tested by hand; here we lock down the *pure* logic that
decides which claims get retried and how a correction is merged, so it can't silently drift.
"""
from src.agents.orchestrator import (
    MAX_CORRECTIONS,
    _apply_corrections,
    _parse_verdicts,
    _refuted_for_correction,
)

SPECIALISTS = {"technical", "risk", "research"}


# --- _parse_verdicts ----------------------------------------------------------
def test_parse_verdicts_captures_agent():
    text = '[{"claim": "NVDA broke 50d SMA", "agent": "Technical", "verdict": "refuted", "reason": "price above SMA"}]'
    v = _parse_verdicts(text)[0]
    assert v["agent"] == "technical"  # normalized to lower-case
    assert v["verdict"] == "refuted"


def test_parse_verdicts_agent_defaults_to_empty():
    v = _parse_verdicts('[{"claim": "x", "verdict": "uncertain", "reason": "y"}]')[0]
    assert v["agent"] == ""


def test_parse_verdicts_ignores_bad_verdict_value():
    assert _parse_verdicts('[{"claim": "x", "verdict": "maybe", "reason": "y"}]') == []


def test_parse_verdicts_survives_surrounding_prose():
    text = 'Here you go:\n[{"claim": "a", "verdict": "confirmed", "reason": "b"}]\nThanks!'
    assert len(_parse_verdicts(text)) == 1


# --- _refuted_for_correction --------------------------------------------------
def test_refuted_picks_only_refuted_with_known_agent():
    verdicts = [
        {"claim": "a", "verdict": "refuted", "reason": "r", "agent": "technical"},
        {"claim": "b", "verdict": "confirmed", "reason": "r", "agent": "risk"},
        {"claim": "c", "verdict": "refuted", "reason": "r", "agent": "research"},
    ]
    picked = _refuted_for_correction(verdicts, SPECIALISTS)
    assert [v["claim"] for v in picked] == ["a", "c"]


def test_refuted_excludes_unknown_or_missing_agent():
    verdicts = [
        {"claim": "a", "verdict": "refuted", "reason": "r", "agent": ""},
        {"claim": "b", "verdict": "refuted", "reason": "r", "agent": "strategist"},
    ]
    assert _refuted_for_correction(verdicts, SPECIALISTS) == []


def test_refuted_is_capped_to_max_corrections():
    verdicts = [
        {"claim": f"c{i}", "verdict": "refuted", "reason": "r", "agent": "technical"}
        for i in range(MAX_CORRECTIONS + 3)
    ]
    assert len(_refuted_for_correction(verdicts, SPECIALISTS)) == MAX_CORRECTIONS


# --- _apply_corrections -------------------------------------------------------
def test_apply_corrections_replaces_matched_verdict():
    verdicts = [
        {"claim": "a", "verdict": "refuted", "reason": "old", "agent": "technical"},
        {"claim": "b", "verdict": "confirmed", "reason": "keep", "agent": "risk"},
    ]
    corrections = [
        {"agent": "technical", "claim": "a", "verdict": "confirmed",
         "reason": "now backed", "revised_claim": "NVDA above SMA"},
    ]
    out = _apply_corrections(verdicts, corrections)
    fixed = next(v for v in out if v["claim"] == "a")
    assert fixed["verdict"] == "confirmed"
    assert fixed["reason"] == "now backed"
    assert fixed["revised_claim"] == "NVDA above SMA"
    assert fixed["corrected"] is True
    # the untouched verdict passes through unchanged and untagged
    kept = next(v for v in out if v["claim"] == "b")
    assert kept == {"claim": "b", "verdict": "confirmed", "reason": "keep", "agent": "risk"}


def test_apply_corrections_no_match_is_noop():
    verdicts = [{"claim": "a", "verdict": "refuted", "reason": "r", "agent": "technical"}]
    corrections = [{"agent": "risk", "claim": "zzz", "verdict": "confirmed", "reason": "x"}]
    assert _apply_corrections(verdicts, corrections) == verdicts


def test_apply_corrections_matches_on_both_agent_and_claim():
    # same claim text from two agents must not cross-contaminate
    verdicts = [
        {"claim": "same", "verdict": "refuted", "reason": "r", "agent": "technical"},
        {"claim": "same", "verdict": "refuted", "reason": "r", "agent": "risk"},
    ]
    corrections = [{"agent": "risk", "claim": "same", "verdict": "confirmed", "reason": "fixed"}]
    out = _apply_corrections(verdicts, corrections)
    tech = next(v for v in out if v["agent"] == "technical")
    risk = next(v for v in out if v["agent"] == "risk")
    assert tech["verdict"] == "refuted" and "corrected" not in tech
    assert risk["verdict"] == "confirmed" and risk["corrected"] is True
