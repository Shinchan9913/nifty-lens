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
from .llm import API_KEY, DEFAULT_MODEL, FAST_MODEL, get_client
from .team import SPECIALISTS, STRATEGIST, VERIFIER

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


def _parse_verdicts(text: str) -> list[dict]:
    """Extract the Verifier's JSON array of verdicts, defensively."""
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
            out.append({"claim": str(v["claim"])[:220], "verdict": v["verdict"], "reason": str(v.get("reason", ""))[:240]})
    return out


async def run_analysis(question: str, bus: EventBus, depth: str = "balanced") -> None:
    if not API_KEY:
        await bus.emit("error", message="LLM_API_KEY is not set. Add LLM_* to the root .env and restart the API.")
        return

    p = DEPTH_PROFILES.get(depth, DEPTH_PROFILES["balanced"])
    client = get_client()

    async def consult(agent) -> tuple[str, str, list]:
        await bus.emit("agent_message", **{"from": "strategist", "to": agent.id, "content": question})
        task = f"{p['note']}\n\nQuestion: {question}"
        ledger: list = []
        answer = await agent.run(client, bus, task, max_rounds=p["rounds"], model=p["force_model"], ledger=ledger)
        await bus.emit("agent_message", **{"from": agent.id, "to": "strategist", "content": answer})
        return agent.id, answer, ledger

    # 1. fan out: specialists in parallel, collecting findings + evidence
    results = await asyncio.gather(*[consult(a) for a in SPECIALISTS.values()])
    findings = "\n\n".join(f"## {SPECIALISTS[aid].name} findings\n{ans}" for aid, ans, _ in results)

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
