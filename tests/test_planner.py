"""Planner: the pure logic that turns the Planner agent's JSON into a fan-out task list.

The orchestrator's planning step is: ask the Planner to decompose the question -> parse its
JSON into [{specialist, focus}] -> run exactly those specialists with their focus (falling
back to everyone if the plan is unusable). The LLM call is integration-tested by hand; here
we lock down `_parse_plan` so a model that returns junk, dupes, or unknown specialists can't
silently break the fan-out.
"""
from src.agents.orchestrator import MAX_PLAN_TASKS, _parse_plan

SPECIALISTS = {"technical", "risk", "research"}


def test_parse_plan_extracts_specialist_and_focus():
    text = '[{"specialist": "technical", "focus": "RSI and trend on NVDA"}]'
    assert _parse_plan(text, SPECIALISTS) == [{"specialist": "technical", "focus": "RSI and trend on NVDA"}]


def test_parse_plan_normalizes_specialist_case():
    plan = _parse_plan('[{"specialist": "Research", "focus": "news catalysts"}]', SPECIALISTS)
    assert plan[0]["specialist"] == "research"


def test_parse_plan_drops_unknown_specialist():
    assert _parse_plan('[{"specialist": "macro", "focus": "x"}]', SPECIALISTS) == []


def test_parse_plan_drops_empty_focus():
    assert _parse_plan('[{"specialist": "risk", "focus": "  "}]', SPECIALISTS) == []


def test_parse_plan_dedupes_to_one_task_per_specialist():
    text = '[{"specialist":"risk","focus":"first"},{"specialist":"risk","focus":"second"}]'
    assert _parse_plan(text, SPECIALISTS) == [{"specialist": "risk", "focus": "first"}]


def test_parse_plan_survives_surrounding_prose():
    text = 'Here is the plan:\n[{"specialist":"technical","focus":"trend"}]\nthanks'
    assert len(_parse_plan(text, SPECIALISTS)) == 1


def test_parse_plan_returns_empty_on_garbage():
    assert _parse_plan("no json at all", SPECIALISTS) == []
    assert _parse_plan("[not, valid, json]", SPECIALISTS) == []


def test_parse_plan_caps_at_max_tasks():
    big = {f"s{i}" for i in range(10)}
    items = ",".join(f'{{"specialist":"s{i}","focus":"f{i}"}}' for i in range(10))
    assert len(_parse_plan(f"[{items}]", big)) == MAX_PLAN_TASKS


def test_parse_plan_truncates_long_focus():
    long = "x" * 500
    plan = _parse_plan(f'[{{"specialist":"technical","focus":"{long}"}}]', SPECIALISTS)
    assert len(plan[0]["focus"]) == 300


def test_parse_plan_ignores_non_dict_items():
    text = '["technical", {"specialist":"risk","focus":"downside"}]'
    assert _parse_plan(text, SPECIALISTS) == [{"specialist": "risk", "focus": "downside"}]
