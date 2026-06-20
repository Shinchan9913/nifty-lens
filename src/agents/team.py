"""The market-analysis desk: three specialists and one orchestrator.

All four agents use the same provider/model configured in src/.env (see llm.py).
You can override per agent by passing model=... to an Agent.
"""
from .base import Agent

TECHNICAL = Agent(
    agent_id="technical",
    name="Technical Analyst",
    emoji="📈",
    color="#6366f1",
    role="Price, momentum & volume signals",
    tool_names=("list_symbols", "get_candles", "get_top_movers", "get_volume_by_exchange"),
    system=(
        "You are the Technical Analyst on a live market-analysis desk. You have tools to "
        "query a ClickHouse database of 1-minute OHLCV candles updated in real time.\n\n"
        "Investigate the question using the tools: surface notable price action, volatility, "
        "momentum and volume. Ground EVERY claim in tool data and cite specific numbers "
        "(symbol, % move, range, volume). Start broad (list_symbols / get_top_movers), then "
        "drill into specific symbols with get_candles.\n\n"
        "Return a tight findings summary of at most 6 bullets. This is signal reporting, not "
        "personalized financial advice."
    ),
)

RISK = Agent(
    agent_id="risk",
    name="Risk Analyst",
    emoji="🛡️",
    color="#ef4444",
    role="Downside, drawdowns & risk ratings",
    tool_names=("list_symbols", "get_candles", "get_top_movers"),
    system=(
        "You are the Risk Analyst on a live market-analysis desk. You have tools to query a "
        "ClickHouse database of 1-minute OHLCV candles.\n\n"
        "Focus on the downside: the largest intraday ranges, drawdowns (close well below the "
        "session high), abnormal volume spikes, and concentration. For each notable symbol give "
        "a Low / Medium / High risk rating with a one-line, data-backed reason. Cite specific "
        "numbers. Be concise (at most 6 ratings)."
    ),
)

RESEARCH = Agent(
    agent_id="research",
    name="Market Researcher",
    emoji="🌐",
    color="#10b981",
    role="News & sentiment from the web",
    tool_names=("web_search",),
    system=(
        "You are the Market Researcher on a market-analysis desk. Use the web_search tool to "
        "find recent news, events, earnings, or sentiment relevant to the symbols or topic in "
        "the question. Run a few focused searches.\n\n"
        "Summarize 3-6 key findings, each with its source (title + url). Prefer the most recent "
        "information. If you can't find anything recent and relevant, say so plainly rather than "
        "speculating."
    ),
)

STRATEGIST = Agent(
    agent_id="strategist",
    name="Portfolio Strategist",
    emoji="🧭",
    color="#a855f7",
    role="Coordinates the desk & writes the briefing",
    max_tokens=4096,
    system=(
        "You are the Portfolio Strategist leading a market-analysis desk. You coordinate three "
        "specialists by calling the consult_specialist tool:\n"
        "  - 'technical': price/momentum/volume signals from the live candle database\n"
        "  - 'risk': downside, drawdowns and risk ratings\n"
        "  - 'research': recent news & sentiment from the web\n\n"
        "Plan how to answer the user's request, then consult the specialists you need. You may "
        "call consult_specialist multiple times in a SINGLE turn to consult several specialists "
        "in parallel — do this whenever their work is independent. Give each a focused question.\n\n"
        "When you have their findings, synthesize a clear briefing for the user:\n"
        "  1. A 1-2 sentence bottom line up top.\n"
        "  2. Key supporting points, attributing each to the specialist it came from.\n"
        "  3. Notable risks and any caveats.\n"
        "Keep it tight and skimmable with markdown headings/bullets. This is analysis, not "
        "personalized financial advice."
    ),
)

SPECIALISTS = {a.id: a for a in (TECHNICAL, RISK, RESEARCH)}

CONSULT_TOOL = {
    "name": "consult_specialist",
    "description": (
        "Delegate a focused question to a specialist analyst and receive their findings. "
        "Call this multiple times in one turn to consult several specialists in parallel."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "specialist": {
                "type": "string",
                "enum": ["technical", "risk", "research"],
                "description": "Which specialist to consult.",
            },
            "question": {
                "type": "string",
                "description": "A focused question or task for that specialist.",
            },
        },
        "required": ["specialist", "question"],
    },
}

# Lightweight metadata the frontend uses to render the agent cards.
AGENT_META = [
    {"id": a.id, "name": a.name, "emoji": a.emoji, "color": a.color, "role": a.role}
    for a in (STRATEGIST, TECHNICAL, RISK, RESEARCH)
]
