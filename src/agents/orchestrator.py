"""Runs one market-analysis session: the Strategist coordinates the specialists.

The trick that makes "agents talk to each other" real: the Strategist is given a
``consult_specialist`` tool whose *handler* is a closure defined here. When the
Strategist calls it, we (1) emit a strategist -> specialist message, (2) actually
run that specialist agent (which streams its own thinking/tools), and (3) emit the
specialist -> strategist reply. To the Strategist it looks like a normal tool; to
the UI it looks like a conversation between agents.
"""
from .bus import EventBus
from .llm import API_KEY, get_client
from .team import CONSULT_TOOL, SPECIALISTS, STRATEGIST


async def run_analysis(question: str, bus: EventBus) -> None:
    if not API_KEY:
        await bus.emit(
            "error",
            message="LLM_API_KEY is not set. Add LLM_API_KEY / LLM_BASE_URL / LLM_MODEL to the root .env and restart the API.",
        )
        return

    client = get_client()

    async def consult_specialist(specialist: str, question: str) -> str:
        agent = SPECIALISTS.get(specialist)
        if agent is None:
            return f"No such specialist: {specialist}"
        # strategist -> specialist (the delegation)
        await bus.emit("agent_message", **{"from": "strategist", "to": specialist, "content": question})
        answer = await agent.run(client, bus, question)
        # specialist -> strategist (the findings come back)
        await bus.emit("agent_message", **{"from": specialist, "to": "strategist", "content": answer})
        return answer

    final = await STRATEGIST.run(
        client,
        bus,
        question,
        extra_tools=[CONSULT_TOOL],
        extra_handlers={"consult_specialist": consult_specialist},
    )
    await bus.emit("final_report", content=final)
