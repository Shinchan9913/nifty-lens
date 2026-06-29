"""Runs one market-analysis session.

Pipeline:
  1. Fan out (parallel, from our side): all specialists work concurrently; we collect
     each one's findings AND its evidence ledger (the exact tool calls + data it pulled).
  2. Verify (adversarial): the Verifier audits the findings against that evidence and
     rates each checkable claim confirmed / uncertain / refuted -> `finding_verified` events.
  3. Synthesize: the Strategist writes the briefing, told which claims survived verification.

The `depth` control is a full EFFORT PROFILE — rounds + model + prompt directive.
"""
import asyncio
import json
import re

from .bus import EventBus
from .clickhouse import query
from .llm import API_KEY, DEFAULT_MODEL, FAST_MODEL, get_client
from .snapshot import clear_anchor, set_anchor
from .team import PLANNER, SPECIALISTS, STRATEGIST, VERIFIER

# force_model: override every agent's model. None = use each agent's own default.
DEPTH_PROFILES = {
    "quick": {
        "rounds": 2, "force_model": FAST_MODEL,
        "note": "QUICK mode: be fast and decisive. Use only the 1-2 most relevant tools. "
                "At most 3 short findings.",
    },
    "balanced": {
        "rounds": 3, "force_model": None,
        "note": "BALANCED mode: check the key tools for your mandate. At most 5 findings.",
    },
    "deep": {
        "rounds": 5, "force_model": DEFAULT_MODEL,
        "note": "DEEP mode: be thorough. Consult all relevant tools — including fundamentals, "
                "filings, options and the macro regime. Up to 8 findings with supporting detail.",
    },
}


# Reflexion: at most this many refuted claims get a re-investigation pass (bounds token cost).
MAX_CORRECTIONS = 3

# Planner: never fan out to more than this many specialist tasks (bounds the run).
MAX_PLAN_TASKS = 3


def _parse_plan(text: str, specialist_ids: set[str]) -> list[dict]:
    """Extract the Planner's task list ``[{specialist, focus}]``, defensively.

    Keeps only tasks aimed at a real specialist with a non-empty focus, dedupes to one
    task per specialist (first focus wins), caps the fan-out, and truncates focus text.
    Returns ``[]`` when nothing is usable — the caller then falls back to consulting every
    specialist with the raw question, so a junk plan can never silently drop the analysis.
    """
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        return []
    try:
        arr = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for item in arr:
        if not isinstance(item, dict):
            continue
        sid = str(item.get("specialist", "")).strip().lower()
        focus = str(item.get("focus", "")).strip()
        if sid in specialist_ids and focus and sid not in seen:
            seen.add(sid)
            out.append({"specialist": sid, "focus": focus[:300]})
        if len(out) >= MAX_PLAN_TASKS:
            break
    return out


def _parse_verdicts(text: str) -> list[dict]:
    """Extract the Verifier's JSON array of verdicts, defensively.

    Each verdict may carry an `agent` (the specialist the claim came from) so the
    Reflexion loop knows who to send a refuted claim back to.
    """
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        return []
    try:
        arr = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    out = []
    for v in arr:
        if isinstance(v, dict) and v.get("claim") and v.get("verdict") in ("confirmed", "uncertain", "refuted"):
            out.append({
                "claim": str(v["claim"])[:220],
                "verdict": v["verdict"],
                "reason": str(v.get("reason", ""))[:240],
                "agent": str(v.get("agent", "")).strip().lower(),
            })
    return out


def _refuted_for_correction(verdicts: list[dict], specialist_ids: set[str]) -> list[dict]:
    """Refuted claims we can actually re-investigate — i.e. attributed to a real specialist."""
    return [v for v in verdicts if v["verdict"] == "refuted" and v.get("agent") in specialist_ids][:MAX_CORRECTIONS]


def _apply_corrections(verdicts: list[dict], corrections: list[dict]) -> list[dict]:
    """Fold re-verified corrections back into the verdict list (pure; unit-tested).

    A correction matches its original verdict by (agent, claim); the matched entry's
    verdict/reason are replaced with the re-verified outcome and tagged `corrected`.
    Unmatched verdicts pass through unchanged.
    """
    by_key = {(c["agent"], c["claim"]): c for c in corrections}
    out = []
    for v in verdicts:
        c = by_key.get((v.get("agent"), v["claim"]))
        if c is None:
            out.append(v)
            continue
        merged = dict(v)
        merged.update(verdict=c["verdict"], reason=c["reason"],
                      revised_claim=c.get("revised_claim", ""), corrected=True)
        out.append(merged)
    return out


async def _reinvestigate(client, bus: EventBus, verdict: dict, ledgers: dict, p: dict) -> dict:
    """Send one refuted claim back to its author specialist, then re-verify the fix.

    Returns a correction record (same agent+claim key as the original verdict) carrying the
    re-verified outcome. Bounded to a couple of tool rounds so the loop can't run away.
    """
    aid = verdict["agent"]
    agent = SPECIALISTS[aid]
    ledger = ledgers.get(aid, [])
    evidence = "\n".join(
        f"{e['tool']}({e['input']}) -> {json.dumps(e['data'], default=str)[:200]}" for e in ledger
    )[:1500]

    await bus.emit("agent_message", **{"from": "verifier", "to": aid, "content": f"REFUTED: {verdict['claim']}"})
    fix_task = (
        "A claim you made was REFUTED by the desk's fact-checker.\n"
        f"Your claim: {verdict['claim']}\n"
        f"Why it was refuted: {verdict['reason']}\n\n"
        f"Your prior evidence:\n{evidence or '(none captured)'}\n\n"
        "Re-investigate THIS specific point with your tools. Reply with ONE corrected, "
        "evidence-backed sentence — or, if the refutation is right, say so plainly."
    )
    revised = await agent.run(client, bus, fix_task, max_rounds=2, model=p["force_model"], ledger=ledger)

    # Re-verify the corrected statement against the (now-extended) evidence.
    re_evidence = "\n".join(
        f"{e['tool']}({e['input']}) -> {json.dumps(e['data'], default=str)[:200]}" for e in ledger
    )[:1800]
    reverify = await VERIFIER.run(
        client, bus, f"Claim: {revised}\n\nEVIDENCE:\n{re_evidence or '(none)'}",
        max_rounds=1, model=p["force_model"],
    )
    rv = _parse_verdicts(reverify)
    return {
        "agent": aid,
        "claim": verdict["claim"],
        "revised_claim": revised.strip()[:220],
        "verdict": rv[0]["verdict"] if rv else "uncertain",
        "reason": rv[0]["reason"] if rv else "re-verified after correction",
        "corrected": True,
    }


async def _freeze_anchor() -> str:
    """The run's point-in-time clock: the newest tick we have at kickoff.

    Every ClickHouse read downstream is filtered ``<=`` this ``T`` (see ``snapshot.py``),
    so the run sees the market exactly as it stood now — no lookahead, fully reproducible.
    Best-effort: if the DB is unreachable we return "" and the run stays live (unanchored).
    """
    try:
        rows = await query("SELECT toString(max(timestamp)) AS t FROM tick_data")
    except Exception:
        return ""
    return (rows[0].get("t") or "").strip() if rows else ""


async def run_analysis(question: str, bus: EventBus, depth: str = "balanced") -> None:
    if not API_KEY:
        await bus.emit("error", message="LLM_API_KEY is not set. Add LLM_* to the root .env and restart the API.")
        return

    p = DEPTH_PROFILES.get(depth, DEPTH_PROFILES["balanced"])
    client = get_client()

    # Freeze the run's clock BEFORE any agent fans out. Child tasks inherit this anchor
    # (contextvars are copied at task creation), so every tool call reads as-of the same T.
    anchor = await _freeze_anchor()
    set_anchor(anchor)
    if anchor:
        await bus.emit("snapshot_anchor", timestamp=anchor)

    async def consult(item: dict) -> tuple[str, str, list]:
        agent = SPECIALISTS[item["specialist"]]
        focus = item["focus"]
        await bus.emit("agent_message", **{"from": "strategist", "to": agent.id, "content": focus})
        task = f"{p['note']}\n\nUser question: {question}\n\nYour focus for this question: {focus}"
        ledger: list = []
        answer = await agent.run(client, bus, task, max_rounds=p["rounds"], model=p["force_model"], ledger=ledger)
        await bus.emit("agent_message", **{"from": agent.id, "to": "strategist", "content": answer})
        return agent.id, answer, ledger

    try:
        # 0. plan: the Planner decomposes the question into a focused task per specialist.
        # If it returns nothing usable we fall back to consulting everyone with the raw question,
        # so planning can sharpen the run but never silently drop a specialist.
        plan_text = await PLANNER.run(client, bus, f"User question: {question}", max_rounds=1, model=p["force_model"])
        plan = _parse_plan(plan_text, set(SPECIALISTS))
        if not plan:
            plan = [{"specialist": aid, "focus": question} for aid in SPECIALISTS]
        await bus.emit("plan", tasks=[{"agent": t["specialist"], "focus": t["focus"]} for t in plan])

        # 1. fan out: planned specialists in parallel, collecting findings + evidence
        results = await asyncio.gather(*[consult(item) for item in plan])
        ledgers = {aid: ledger for aid, _, ledger in results}
        # The agent_id is shown to the Verifier so it can attribute each claim back to its author.
        findings = "\n\n".join(f"## {SPECIALISTS[aid].name} [agent_id: {aid}] findings\n{ans}" for aid, ans, _ in results)

        # 2. verify: audit the findings against the captured evidence
        evidence_lines = [
            f"[{aid}] {e['tool']}({e['input']}) -> {json.dumps(e['data'], default=str)[:300]}"
            for aid, _, ledger in results for e in ledger
        ][:40]
        verify_task = (
            f"User question: {question}\n\n"
            f"FINDINGS:\n{findings}\n\nEVIDENCE (tool calls + data):\n" + ("\n".join(evidence_lines) or "(no tool data captured)")
        )
        verdict_text = await VERIFIER.run(client, bus, verify_task, max_rounds=1, model=p["force_model"])
        verdicts = _parse_verdicts(verdict_text)
        for v in verdicts:
            await bus.emit("finding_verified", **v)

        # 2b. REFLEXION: each refuted claim goes back to its author for one bounded re-investigation,
        # then gets re-verified. This closes the adversarial loop instead of just reporting failures.
        to_fix = _refuted_for_correction(verdicts, set(SPECIALISTS))
        if to_fix:
            corrections = await asyncio.gather(
                *[_reinvestigate(client, bus, v, ledgers, p) for v in to_fix]
            )
            verdicts = _apply_corrections(verdicts, corrections)
            for c in corrections:
                await bus.emit("claim_correction", **c)

        # 3. synthesize: Strategist writes the briefing, aware of the verification
        verification = "\n".join(f"- [{v['verdict']}] {v['claim']} — {v['reason']}" for v in verdicts) or "(no verdicts)"
        synthesis_task = (
            f"User question: {question}\n\n{p['note']}\n\n"
            f"Specialist findings:\n{findings}\n\n"
            f"Verifier verdicts (trust these — call out anything refuted or only uncertain):\n{verification}\n\n"
            "Synthesize the briefing."
        )
        final = await STRATEGIST.run(client, bus, synthesis_task, max_rounds=2, model=p["force_model"])
        await bus.emit("final_report", content=final)
    finally:
        # Drop back to live mode so this task's contextvar can't leak into a later run.
        clear_anchor()
