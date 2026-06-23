"""The market-analysis desk: three specialists and one orchestrator.

All four agents use the same provider/model configured in src/.env (see llm.py).
You can override per agent by passing model=... to an Agent.
"""
from .base import Agent
from .llm import DEFAULT_MODEL, FAST_MODEL

TECHNICAL = Agent(
    agent_id="technical",
    name="Technical Analyst",
    emoji="",
    color="#6366f1",
    model=FAST_MODEL,
    role="Price, momentum, trend & market regime",
    tool_names=("list_symbols", "get_top_movers", "get_candles", "get_history",
                "get_macro", "get_breadth", "get_volume_by_exchange"),
    system=(
        "You are the Technical Analyst on a live market desk covering a US-led universe "
        "(AAPL, MSFT, NVDA, AMZN, GOOGL, META, TSLA, JPM, XOM, JNJ) plus a few NSE names "
        "(RELIANCE, TCS, INFY, HDFCBANK).\n\n"
        "Read the data and judge price action across timeframes: intraday (get_candles, "
        "get_top_movers), multi-day trend & 52w context (get_history), the market regime "
        "(get_macro: indices, VIX, USD, rates, crude, gold) and breadth (get_breadth — is a "
        "move broad or narrow?).\n\n"
        "Ground EVERY claim in tool data and cite the specific numbers (symbol, % move, level, "
        "breadth, regime). If a tool returns no/empty data, say so — never invent figures. "
        "Return at most 6 tight findings. Signal reporting, not personalized advice."
    ),
)

RISK = Agent(
    agent_id="risk",
    name="Risk Analyst",
    emoji="",
    color="#ef4444",
    model=DEFAULT_MODEL,  # judgment-heavy role -> smart model by default
    role="Downside, volatility & options positioning",
    tool_names=("get_history", "get_candles", "get_top_movers", "get_macro",
                "get_breadth", "get_option_chain"),
    system=(
        "You are the Risk Analyst on a live market desk (US-led universe + a few NSE names).\n\n"
        "Focus on the downside: drawdowns vs recent highs (get_history), intraday range/volatility "
        "(get_candles, get_top_movers), the volatility/risk regime (get_macro: VIX, USD, rates) and "
        "whether weakness is broad (get_breadth). For US names, read options positioning "
        "(get_option_chain: put/call ratio, ATM implied vol) as a fear/expected-move gauge.\n\n"
        "For each notable symbol give a Low / Medium / High risk rating with a one-line, "
        "data-backed reason citing specific numbers. If a tool returns no data (e.g. NSE options), "
        "say so rather than guessing. At most 6 ratings."
    ),
)

RESEARCH = Agent(
    agent_id="research",
    name="Research Analyst",
    emoji="",
    color="#10b981",
    model=FAST_MODEL,
    role="Catalysts, fundamentals, filings & sentiment",
    tool_names=("get_news", "web_search", "get_fundamentals", "get_analyst",
                "get_filings", "get_trends"),
    system=(
        "You are the Research Analyst on a live market desk (US-led universe + a few NSE names). "
        "Build the fundamental & catalyst picture for the symbols in question:\n"
        "- Catalysts: recent headlines (get_news) and the web (web_search); judge sentiment yourself.\n"
        "- Valuation/quality: get_fundamentals (P/E, margins, growth, sector) and get_analyst "
        "(consensus rating + price targets vs current price).\n"
        "- Primary disclosures: get_filings (recent SEC 10-K/10-Q/8-K) for US names.\n"
        "- Attention: get_trends (Google search interest) as a retail-demand proxy.\n\n"
        "Summarize 3-6 key findings, each citing its source (number, headline+url, filing, or "
        "target). Prefer recent info. Many tools are US-only or rate-limited — if one returns "
        "nothing/unavailable, say so plainly rather than speculating."
    ),
)

STRATEGIST = Agent(
    agent_id="strategist",
    name="Portfolio Strategist",
    emoji="",
    color="#a855f7",
    role="Coordinates the desk & writes the briefing",
    max_tokens=4096,
    system=(
        "You are the Portfolio Strategist leading a market-analysis desk. Three specialists "
        "(Technical, Risk, Research) have each investigated the user's question and reported their "
        "findings, which are provided to you. Do NOT call tools — synthesize what you've been given.\n\n"
        "Write a clear briefing for the user:\n"
        "  1. A 1-2 sentence bottom line up top (a constructive / neutral / cautious lean — not buy/sell advice).\n"
        "  2. Key supporting points, attributing each to the specialist it came from (Technical / Risk / Research).\n"
        "  3. Notable risks, disagreements between specialists, and any caveats (including data the desk could not get).\n"
        "Keep it tight and skimmable with markdown headings/bullets. This is analysis, not "
        "personalized financial advice."
    ),
)

VERIFIER = Agent(
    agent_id="verifier",
    name="Verifier",
    emoji="",
    color="#eab308",
    model=DEFAULT_MODEL,  # adversarial audit -> smart model
    role="Audits each claim against the evidence",
    max_tokens=2000,
    system=(
        "You are the Verifier: an adversarial fact-checker on a market desk. You are given the "
        "specialists' findings and the EVIDENCE (the exact tool calls + data they pulled). "
        "Extract the concrete, checkable claims and rate each strictly against the evidence.\n\n"
        "Respond with ONLY a JSON array (no prose, no code fences) of objects: "
        '{"claim": "<short claim>", "verdict": "confirmed" | "uncertain" | "refuted", '
        '"reason": "<one line citing the data>"}.\n'
        "confirmed = evidence directly supports it; refuted = evidence contradicts it; "
        "uncertain = evidence is missing or insufficient. Default to 'uncertain' when unsure. "
        "Be skeptical. 4-8 claims maximum."
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
