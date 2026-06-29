# Glass Desk — Engineering Plan

> Status doc for the nifty-lens multi-agent quantitative analysis platform.
> Last updated: 2026-06-29. Branch: `feat/glass-desk-provenance`.

## 0. RESUME HERE (current progress)

**GOAL RESET (2026-06-29):** the project's purpose is to be a *resume-grade AI-AGENT
project* — proof the author can build, use, and explain agents. NOT quant correctness for
its own sake. Finance is just the domain skin. We are de-emphasising the quant/dependency-
graph track (the dependency graph underperforms and isn't the story) and building the
**agent-craft track** below.

Phase 1 contracts (`src/shared/contracts.py`) are DONE and pass `pytest`.

### Agent-craft roadmap (current work — build in this order)

Each item proves one agent competency a recruiter probes for. Tests-first where possible.

- **A. Reflexion loop** *(self-correcting agents)* — a `refuted` Verifier verdict triggers
  ONE bounded re-investigation by the originating specialist (critique + evidence fed back),
  then re-verify. Emit `claim_correction` events so the UI shows the loop. Files:
  `orchestrator.py` (+ `team.py` verifier prompt emits source agent). Bound by `max_rounds`.
- **B. Planner agent** *(planning / decomposition)* — DONE. `PLANNER` (team.py) decomposes the
  question into a JSON task list `[{specialist, focus}]`; `_parse_plan` (orchestrator.py, pure +
  unit-tested) sanitises it (known specialists, dedupe, cap, truncate) with a fallback to all
  specialists on junk. Executor fans out over the plan with each specialist's focus. `plan` SSE
  event → "Plan" panel in the UI. Tests: `tests/test_planner.py`.
- **C. Deliberation cache** *(memory, done right)* — cross-run cache keyed by
  `(normalized_question, depth, snapshot_anchor)`. Same question at the same frozen moment
  reuses the prior briefing instead of re-spending tokens. Ties into point-in-time below.
- **D. Eval harness** *(measurement, not vibes)* — a small offline scorer: fixture
  questions + a rubric / LLM-judge that scores groundedness (every claim cites evidence) and
  verifier agreement. Run it as a pytest target so quality is regression-tested.
- **E. Guardrails** *(safe agents)* — keep hard `max_iterations`; add an untrusted-content
  guard that sanitizes/quarantines `web_search` text before it enters a prompt
  (prompt-injection surface) and tags each fact with its source.

**Supporting brag (cheap, high-credibility, fold in alongside A–E):**
- **Point-in-time correctness** — DONE. `src/agents/snapshot.py` holds a per-run anchor `T`
  in a `ContextVar`; ClickHouse tools read it via `now_expr`/`asof_filter` so every data read
  is filtered `<= T` (no lookahead, reproducible). Orchestrator freezes `T = max(timestamp)`
  at kickoff, emits a `snapshot_anchor` SSE event, clears it in a `finally`. UI shows an
  "as of T" pill. Tests: `tests/test_snapshot.py` (helper SQL) + `tests/test_tools_pit.py`
  (tools actually use it, live vs anchored). `T` is also the cache key for C.
- **Token/latency telemetry** — count tokens + wall-time per agent/run; expose a metrics
  endpoint. (Maps to the author's day-job cost-attribution work.)

**DROPPED / de-scoped:** State-Node-Router refactor (author already runs LangGraph in
prod — hand-rolling it proves little and complicates the story); dependency-graph as a
headline (underperforms — keep as a minor tool only); deep quant nodes (CAR/order-flow)
unless a domain anchor is needed.

**DONE so far:** A. Reflexion loop; Point-in-time correctness (snapshot anchor wired through
tools + orchestrator + UI pill); B. Planner agent (runtime decomposition + UI plan panel).

**NEXT ACTION:** implement **C. Deliberation cache**. Cross-run cache keyed by
`(normalized_question, depth, snapshot_anchor)` — the same question at the same frozen `T`
reuses the prior briefing instead of re-spending tokens. The anchor from the point-in-time
work is the cache key. Tests-first for the key-normalisation + hit/miss logic.

Housekeeping: add `pytest`, `pytest-asyncio` to `requirements.txt`.

## 1. Vision

**"Glass Desk": the reasoning chain is the product.** Every analytical claim an agent
makes must be traceable to a deterministic data snapshot or a cited web source, and any
run must be reproducible from its snapshot anchor. The platform takes a market question
(and, in v2, a structured strategy) and returns an auditable briefing where each claim
carries its evidence and a confirmed / uncertain / refuted verdict.

## 2. Architecture decision (read before adding any dependency)

We **hand-roll** the agent runtime. No CrewAI, LangChain, LangGraph, or OpenClaw.

- **Why:** full control over the tool-calling loop, token budget, and state; the system
  *is* the engineering story. Frameworks would hide the very mechanics this project exists
  to demonstrate.
- **OpenClaw / LangChain / CrewAI** are general-purpose agent *runtimes* — alternatives to
  our loop, not layers on top. Adopting one means deleting `base.py`/`orchestrator.py`.
- **LangGraph-ready:** we keep the design portable by moving toward a State-Node-Router
  shape (agents as functions over a shared state) so a later LangGraph port is mechanical.
- **Standards-aligned, not framework-bound:** tool schemas follow MCP-style clean,
  decoupled contracts; we may expose `tools.py` as a real MCP server later (Phase 5).
- **Honest framing for interviews:** "deterministic, auditable state and bounded token
  cost on a hand-rolled async loop over the OpenAI tool-calling spec" — NOT
  "sub-millisecond rollbacks" (every step is gated on seconds-scale 70B HTTP calls).

## 3. Tech stack — what to use

| Layer | Choice | Notes |
|---|---|---|
| Language | Python 3.13 | async throughout |
| LLM | NVIDIA NIM (Llama 3.3 70B), OpenAI-compatible | swappable via `src/.env` (`LLM_*`); free tier. Groq/OpenRouter/Gemini also work |
| API | FastAPI + SSE | streaming via custom `EventBus` |
| DB | ClickHouse (Docker), MergeTree | `ORDER BY (ticker/symbol, timestamp)` always |
| Contracts | Pydantic v2 (`model_config`, not `class Config`) | single source of truth |
| Technicals | `pandas-ta` (local lib) | NEVER let the LLM compute math |
| Frontend | React + Vite + Tremor + TypeScript | SSE consumer + provenance drawer |
| Data | yfinance, SEC EDGAR, DuckDuckGo, pytrends | free/keyless; broker API for L2 depth (see §7) |
| Tests | pytest + pytest-asyncio | test async state transitions first |

**Hard rules for every agent loop:** `max_iterations = 5`; all math in Python/SQL, never
in an LLM prompt; every tool result appended to an evidence ledger.

## 4. What's already built (v1 — done)

- ClickHouse schema: `tick_data`, `daily_bars`, `macro_bars`, `tick_data_5min` MV.
- Ingestion: `groww_ingestor.py` (live), `producer.py` (synthetic 24/7), seed scripts.
- Hand-rolled streaming tool-loop (`agents/base.py`) on OpenAI-compatible LLMs.
- Agents (`agents/team.py`): Technical, Risk, Research specialists + Strategist + Verifier.
- Orchestrator (`agents/orchestrator.py`): `asyncio.gather` fan-out, then adversarial
  verify (confirmed/uncertain/refuted, emits `finding_verified`), then synthesize.
  Depth/effort profiles (quick/balanced/deep).
- 14 tools (`agents/tools.py`): ClickHouse queries + yfinance + EDGAR + Trends + web search.
- Evidence ledger per tool call; SSE `EventBus`; REST + `/api/agents/stream`.
- React dashboard: market cards, agent console, provenance drawer, pixel office.

## 5. Roadmap — v2 (the strategy-execution platform)

Each phase lists deliverable files and how to verify. Build in order; later phases
depend on earlier contracts.

### Phase 1 — Unified contracts  `src/shared/contracts.py`
Pydantic v2 models, single source of truth for API + agents:
- `ConditionBlock` — indicator, operator (`>` `<` `==` `crosses_above` `crosses_below`), value.
- `StrategyPayload` — name, ticker, timeframe (`1m`/`5m`/`15m`/`1d`), entry_rules,
  exit_rules, stop_loss_pct.
- `EvidenceItem` — source (`clickhouse`/`web_search`), query_string, extracted_fact,
  snapshot_timestamp.
- `ProvenanceClaim` — claim_id, agent_name, assertion, confidence, evidence_ledger.
- `OrderBookLevel` / `MarketDepthPayload` — top-5 L2 depth (for Phase 4).
- **Verify:** `pytest` round-trips; reject bad operators/timeframes.
- **Write tests first** (`tests/test_contracts.py`).

### Phase 2 — Strategy endpoint  `src/api/routes.py`
- `POST /api/strategies/execute` accepting `StrategyPayload`.
- Query ClickHouse `MAX(timestamp)` for the ticker → immutable **snapshot anchor**
  (point-in-time correctness; everything downstream reads as-of this time).
- Initialize shared session state; return SSE `StreamingResponse` driven by the EventBus.
- Mount the router in `src/api/main.py` (keep existing endpoints).
- **Verify:** the `curl` POST in §8 yields structured SSE chunks.

### Phase 3 — State-Node-Router refactor (the LangGraph-ready step)
- Introduce a `SessionState` dataclass/Pydantic model carrying question/strategy,
  snapshot anchor, per-agent findings, evidence ledger, and provenance claims.
- Re-shape agents as async functions `node(state) -> state` (wrap existing `Agent.run`).
- A simple router decides node order; orchestrator becomes a graph walk.
- **Decision point:** can be deferred — keep class-based agents and ship features first,
  OR do it now so new nodes are built the right way. (Tradeoff: it touches every file.)
- **Verify:** existing `/api/agents/stream` behavior unchanged; tests on state transitions.

### Phase 4 — New specialist nodes
- **Dynamic Event Discovery**  `src/agents/discovery.py`
  - Phase A: LLM generates exploratory search queries for the ticker's historical
    catalysts (earnings drops, regulatory news, structural shifts).
  - Phase B: regex/cheap-LLM extract ISO dates → windowed ClickHouse query computing
    **Cumulative Abnormal Returns over [-3, +3] days** around each date (point-in-time,
    no lookahead). Return a deterministic truth-table string to the orchestrator.
- **Order Flow**  `src/agents/order_flow.py` (needs Phase 4-schema below)
  - `order_book_depth` table (MergeTree, `ORDER BY (ticker, timestamp)`).
  - Tool computes Bid-Ask Imbalance `(buy_qty - sell_qty)/(buy_qty + sell_qty)`; if
    `|imbalance| > 0.15` in the session window, emit a liquidity-wall finding.
- Add both to the `asyncio.gather` fan-out alongside the Technical specialist
  (now using `pandas-ta`).
- **Verify:** unit tests with a synthetic depth/dates fixture; no network in tests.

### Phase 5 — Hardening + polish (the differentiators, see §6)
Point-in-time replay, web-content guard, telemetry, verifier self-correction,
deliberation cache, spillover node, MCP server. Pick by signal-per-effort.

## 6. Differentiating features (Phase 5 menu, ranked)

1. **Point-in-time replay** — persist each run's snapshot anchor + inputs; replay
   reproduces the exact briefing. Strongest quant-credibility win; nearly free given
   the anchor exists. Build the no-lookahead discipline into Phase 4 from day one.
2. **Untrusted-content guard** — sanitize/quarantine `web_search` text before it enters
   a prompt (prompt-injection surface); tag each fact with its source URL. Defensive-sec
   signal, low effort.
3. **Token/cost + latency telemetry** — count tokens + wall-time per agent/run; expose a
   small metrics endpoint. Do BEFORE the cache so you can prove its effect.
4. **Verifier self-correction loop** — a `refuted` claim is regenerated once, bounded by
   `max_iterations`. Completes the adversarial loop.
5. **Deliberation cache** — start with an exact/normalized key
   `(query, depth, snapshot_candle)`; upgrade to semantic (embeddings) only if you want
   the keyword. Cuts repeat-query token spend.
6. **Cross-Asset Spillover node** — reads `get_macro` (crude/gold/USD/rates), flags
   intermarket anomalies, broadcasts a risk-adjust alert. Natural new specialist.
7. **MCP server** for `tools.py` — exposes the tool layer over MCP; "standards-aligned
   tool architecture" without framework bloat.
8. **Execution feasibility / slippage guard** — extends Order Flow: position-size vs
   liquidity → expected slippage → downgrade execution rating on thin books.

## 7. Data sourcing reality (NSE options + order book)

- **L1 (best bid/offer):** free via yfinance.
- **L2 (5-deep order book):** retail broker WebSocket — Groww Quote, Zerodha Kite, Fyers,
  Dhan (free or ~Rs 2,000/mo). This is what `order_book_depth` is built for.
- **L3 (20-deep) / full tick-by-tick:** institutional, gated/expensive — out of scope.
- **Option chains:** `nsepython` (unofficial, IP-blocked/rate-limited — dev only) or a
  broker API (clean, legal). yfinance options work for US names only.
- **For off-market dev:** extend `producer.py` to synthesize realistic L2 depth + option
  chains into ClickHouse so the pipeline runs 24/7 without a live feed. **Recommended
  first** — get the agents working on synthetic depth, wire a real broker later.

## 8. How to verify v2

```bash
curl -X POST "http://localhost:8000/api/strategies/execute" \
  -H "Content-Type: application/json" \
  -d '{
    "strategy_name": "Event Driven Mean Reversion",
    "ticker": "RELIANCE",
    "timeframe": "5m",
    "entry_rules": [
      {"indicator": "RSI", "operator": "<", "value": "35"},
      {"indicator": "Event_Probability", "operator": ">", "value": "75"}
    ],
    "exit_rules": [{"indicator": "RSI", "operator": ">", "value": "70"}],
    "stop_loss_pct": 2.5
  }'
```
Expect SSE chunks: Discovery spawning search tools, CAR truth-table, then the
zero-temperature Verifier auditing claims line-by-line into `ProvenanceClaim` objects.

## 9. Guardrails when feeding tasks to Claude Code

- Pin ClickHouse: `Engine = MergeTree() ORDER BY (ticker, timestamp)`.
- Pydantic **v2** syntax only (`model_config`, not `class Config`).
- Every agent loop: hard `max_iterations = 5`.
- Math in Python/SQL (`pandas-ta`), never in an LLM prompt.
- No heavy frameworks (LangChain/CrewAI/OpenClaw) pulled in.
- Tests before implementation; keep `base.py` streaming + `EventBus` intact.
- Use the synthetic producer for test data; no live network in unit tests.
