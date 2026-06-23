"""Runs one market-analysis session.

Parallel-from-our-side orchestration: instead of letting the model pick specialists
one at a time (sequential, and dependent on fragile parallel model tool-calls), WE
run all specialists concurrently with asyncio.gather, then the Strategist synthesizes
their gathered findings into the briefing. Deterministic, ~3x faster wall-clock.

The `depth` control is a full EFFORT PROFILE — it tunes three things together:
  - rounds: how many tool-loop rounds each specialist may take
  - model:  fast (8B) vs smart (70B) — the dominant latency lever
  - note:   a prompt directive (terse + few tools  ...  thorough + many tools)
"""
import asyncio

from .bus import EventBus
from .llm import API_KEY, DEFAULT_MODEL, FAST_MODEL, get_client
from .team import SPECIALISTS, STRATEGIST

# force_model: override every agent's model. None = use each agent's own default
# (Technical/Research = fast 8B, Risk/Strategist = smart 70B) — the per-role combination.
DEPTH_PROFILES = {
    "quick": {
        "rounds": 2, "force_model": FAST_MODEL,
        "note": "QUICK mode: be fast and decisive. Use only the 1-2 most relevant tools. "
                "At most 3 short findings.",
    },
    "balanced": {
        "rounds": 3, "force_model": None,  # per-role mix: smart where judgment matters, fast elsewhere
        "note": "BALANCED mode: check the key tools for your mandate. At most 5 findings.",
    },
    "deep": {
        "rounds": 5, "force_model": DEFAULT_MODEL,  # max quality: smart model everywhere
        "note": "DEEP mode: be thorough. Consult all relevant tools — including fundamentals, "
                "filings, options and the macro regime. Up to 8 findings with supporting detail.",
    },
}


async def run_analysis(question: str, bus: EventBus, depth: str = "balanced") -> None:
    if not API_KEY:
        await bus.emit("error", message="LLM_API_KEY is not set. Add LLM_* to the root .env and restart the API.")
        return

    p = DEPTH_PROFILES.get(depth, DEPTH_PROFILES["balanced"])
    client = get_client()

    async def consult(agent) -> tuple[str, str]:
        await bus.emit("agent_message", **{"from": "strategist", "to": agent.id, "content": question})
        task = f"{p['note']}\n\nQuestion: {question}"
        # model=None -> agent uses its own role-default
        answer = await agent.run(client, bus, task, max_rounds=p["rounds"], model=p["force_model"])
        await bus.emit("agent_message", **{"from": agent.id, "to": "strategist", "content": answer})
        return agent.id, answer

    # fan out: all specialists work in parallel
    results = await asyncio.gather(*[consult(a) for a in SPECIALISTS.values()])

    # synthesize: hand the gathered findings to the Strategist
    findings = "\n\n".join(f"## {SPECIALISTS[aid].name} findings\n{ans}" for aid, ans in results)
    synthesis_task = (
        f"User question: {question}\n\n{p['note']}\n\n"
        f"Your specialists have reported. Synthesize their findings into the briefing.\n\n{findings}"
    )
    final = await STRATEGIST.run(client, bus, synthesis_task, max_rounds=2, model=p["force_model"])
    await bus.emit("final_report", content=final)
