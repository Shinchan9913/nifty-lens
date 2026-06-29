import { useEffect, useRef, useState, type CSSProperties } from "react";
import {
  ResponsiveContainer, BarChart, Bar, Cell, XAxis, YAxis, Tooltip,
  AreaChart, Area,
} from "recharts";
import PixelOffice from "./PixelOffice";
import "./AgentConsole.css";

const API_BASE = "http://localhost:8000";
const UP = "#22c55e";
const DOWN = "#ef4444";
const NEUTRAL = "#6b7280";

type AgentId = "strategist" | "planner" | "technical" | "risk" | "research";

interface AgentMeta { id: AgentId; name: string; emoji: string; role: string; x: number; y: number; }

const AGENTS: AgentMeta[] = [
  { id: "strategist", name: "Strategist", emoji: "", role: "Lead · coordinates the desk", x: 50, y: 18 },
  { id: "planner", name: "Planner", emoji: "", role: "Plans the investigation", x: 80, y: 18 },
  { id: "technical", name: "Technical", emoji: "", role: "Price · momentum · volume", x: 16, y: 70 },
  { id: "risk", name: "Risk", emoji: "", role: "Downside · risk ratings", x: 50, y: 82 },
  { id: "research", name: "Research", emoji: "", role: "News · web sentiment", x: 84, y: 70 },
];
const AGENT_BY_ID = Object.fromEntries(AGENTS.map((a) => [a.id, a])) as Record<AgentId, AgentMeta>;

const EXAMPLES = [
  "What's moving in the market right now, and is anything risky?",
  "Brief me on the most volatile symbols in the last few minutes.",
  "Should I be cautious about any symbol right now? Check the news too.",
];

type Status = "idle" | "working" | "thinking" | "done";

interface TimelineItem { kind: "message" | "tool_call" | "tool_result"; agent: AgentId; to?: AgentId; label: string; ok?: boolean; tool?: string; input?: unknown; data?: unknown; }
interface Mover { symbol: string; change_pct: number; range_pct: number; close: number; }

// ---------- minimal markdown ----------
function renderInline(text: string): React.ReactNode[] {
  const nodes: React.ReactNode[] = [];
  const re = /(\*\*([^*]+)\*\*|`([^`]+)`|\[([^\]]+)\]\(([^)]+)\)|https?:\/\/[^\s)]+)/g;
  let last = 0, key = 0, m: RegExpExecArray | null;
  while ((m = re.exec(text))) {
    if (m.index > last) nodes.push(text.slice(last, m.index));
    if (m[2] !== undefined) nodes.push(<strong key={key++}>{m[2]}</strong>);
    else if (m[3] !== undefined) nodes.push(<code key={key++}>{m[3]}</code>);
    else if (m[4] !== undefined) nodes.push(<a key={key++} href={m[5]} target="_blank" rel="noreferrer">{m[4]}</a>);
    else nodes.push(<a key={key++} href={m[0]} target="_blank" rel="noreferrer">{m[0]}</a>);
    last = re.lastIndex;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}
function Markdown({ text }: { text: string }) {
  const out: React.ReactNode[] = [];
  let bullets: string[] = [], key = 0;
  const flush = () => { if (bullets.length) { out.push(<ul key={key++}>{bullets.map((b, i) => <li key={i}>{renderInline(b)}</li>)}</ul>); bullets = []; } };
  for (const raw of (text || "").split("\n")) {
    const line = raw.replace(/\s+$/, "");
    if (/^#{1,6}\s/.test(line)) {
      flush();
      const lv = (line.match(/^#+/) as RegExpMatchArray)[0].length;
      const c = renderInline(line.replace(/^#+\s/, ""));
      out.push(lv <= 1 ? <h3 key={key++}>{c}</h3> : lv === 2 ? <h4 key={key++}>{c}</h4> : <h5 key={key++}>{c}</h5>);
    }
    else if (/^\s*[-*]\s/.test(line)) bullets.push(line.replace(/^\s*[-*]\s/, ""));
    else if (line.trim() === "") flush();
    else { flush(); out.push(<p key={key++}>{renderInline(line)}</p>); }
  }
  flush();
  return <div className="md">{out}</div>;
}

export default function AgentConsole() {
  const [query, setQuery] = useState(EXAMPLES[0]);
  const [depth, setDepth] = useState<"quick" | "balanced" | "deep">("balanced");
  const [running, setRunning] = useState(false);
  const [status, setStatus] = useState<Record<string, Status>>({});
  const [thinking, setThinking] = useState<Record<string, string>>({});
  const [output, setOutput] = useState<Record<string, string>>({});
  const [timeline, setTimeline] = useState<TimelineItem[]>([]);
  const [report, setReport] = useState("");
  const [error, setError] = useState("");
  const [bubbles, setBubbles] = useState<Record<string, string>>({});
  const [lastMsg, setLastMsg] = useState<{ from: AgentId; to: AgentId; seq: number } | null>(null);
  const [modal, setModal] = useState<{ kind: "agent"; id: AgentId } | { kind: "briefing" } | null>(null);
  const [verdicts, setVerdicts] = useState<{ claim: string; agent?: string; verdict: "confirmed" | "uncertain" | "refuted"; reason: string; corrected?: boolean; revised_claim?: string }[]>([]);
  const [anchor, setAnchor] = useState("");  // point-in-time clock T this run was frozen at
  const [plan, setPlan] = useState<{ agent: AgentId; focus: string }[]>([]);  // Planner's task list

  // live market data for the charts
  const [movers, setMovers] = useState<Mover[]>([]);
  const [volume, setVolume] = useState<{ exchange: string; total_volume: number }[]>([]);
  const [series, setSeries] = useState<{ symbol: string; data: { time: string; close: number }[] }>({ symbol: "", data: [] });

  const esRef = useRef<EventSource | null>(null);
  const msgSeq = useRef(0);

  useEffect(() => () => esRef.current?.close(), []);

  // poll the market endpoints for the charts (independent of agent runs)
  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const [v, vol] = await Promise.all([
          fetch(`${API_BASE}/api/volatile?minutes=10&limit=8`).then((r) => r.json()),
          fetch(`${API_BASE}/api/volume?minutes=10`).then((r) => r.json()),
        ]);
        if (!alive) return;
        const assets: Mover[] = v.assets || [];
        setMovers(assets);
        setVolume(vol.data || []);
        const top = assets[0]?.symbol;
        if (top) {
          const c = await fetch(`${API_BASE}/api/candles?symbol=${encodeURIComponent(top)}&minutes=45`).then((r) => r.json());
          if (alive) setSeries({ symbol: top, data: c.candles || [] });
        }
      } catch { /* api warming up */ }
    };
    load();
    const t = setInterval(load, 8000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  const flash = (setter: React.Dispatch<React.SetStateAction<Record<string, string>>>, agent: string, value: string, ms: number) => {
    setter((s) => ({ ...s, [agent]: value }));
    setTimeout(() => setter((s) => { const n = { ...s }; if (n[agent] === value) delete n[agent]; return n; }), ms);
  };

  const run = () => {
    if (running || !query.trim()) return;
    setRunning(true);
    setStatus({}); setThinking({}); setOutput({}); setTimeline([]);
    setReport(""); setError(""); setBubbles({}); setLastMsg(null); setModal(null); setVerdicts([]); setAnchor(""); setPlan([]);

    const es = new EventSource(`${API_BASE}/api/agents/stream?query=${encodeURIComponent(query)}&depth=${depth}`);
    esRef.current = es;
    es.onmessage = (e) => {
      const ev = JSON.parse(e.data);
      switch (ev.type) {
        case "agent_status": setStatus((s) => ({ ...s, [ev.agent]: ev.status })); break;
        case "thinking": setThinking((t) => ({ ...t, [ev.agent]: (t[ev.agent] || "") + ev.text })); break;
        case "text": setOutput((o) => ({ ...o, [ev.agent]: (o[ev.agent] || "") + ev.text })); break;
        case "agent_message":
          setTimeline((tl) => [...tl, { kind: "message", agent: ev.from, to: ev.to, label: ev.content }]);
          setLastMsg({ from: ev.from, to: ev.to, seq: ++msgSeq.current });
          flash(setBubbles, ev.from, ev.content.slice(0, 90), 3200);
          break;
        case "tool_call":
          setTimeline((tl) => [...tl, { kind: "tool_call", agent: ev.agent, label: `${ev.tool}(${fmtInput(ev.input)})` }]);
          break;
        case "tool_result":
          setTimeline((tl) => [...tl, { kind: "tool_result", agent: ev.agent, label: `${ev.tool} → ${ev.summary}`, ok: ev.ok, tool: ev.tool, input: ev.input, data: ev.data }]);
          break;
        case "snapshot_anchor": setAnchor(ev.timestamp); break;
        case "plan": setPlan(ev.tasks || []); break;
        case "finding_verified": setVerdicts((v) => [...v, { claim: ev.claim, agent: ev.agent, verdict: ev.verdict, reason: ev.reason }]); break;
        case "claim_correction":
          // Reflexion: a refuted claim came back re-investigated — update it in place.
          setVerdicts((v) => v.map((row) =>
            row.claim === ev.claim && row.agent === ev.agent
              ? { ...row, verdict: ev.verdict, reason: ev.reason, corrected: true, revised_claim: ev.revised_claim }
              : row));
          break;
        case "final_report": setReport(ev.content); break;
        case "error": setError(ev.message); break;
        case "run_finished": es.close(); setRunning(false); break;
      }
    };
    es.onerror = () => { es.close(); setRunning(false); setError((p) => p || "Lost connection to the agent stream."); };
  };

  const ms = movers || [];
  const gainers = ms.filter((m) => m.change_pct >= 0).length;
  const losers = ms.filter((m) => m.change_pct < 0).length;
  const topVol = ms[0];
  const netUp = series.data.length >= 2 ? series.data[series.data.length - 1].close >= series.data[0].close : true;
  const briefShort = report.split("\n").filter((l) => l.trim() && !/^#{1,6}\s/.test(l))[0] || report.slice(0, 220);

  return (
    <div className="office">
      <div className="controls">
        <input className="inp" value={query} disabled={running}
          onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === "Enter" && run()}
          placeholder="Ask the desk about the market…" />
        <div className="depth-seg" title="How much the desk digs in (caps each analyst's tool rounds)">
          {(["quick", "balanced", "deep"] as const).map((d) => (
            <button key={d} className={depth === d ? "active" : ""} disabled={running} onClick={() => setDepth(d)}>{d}</button>
          ))}
        </div>
        <button className="run" onClick={run} disabled={running}>{running ? "Working…" : "Run analysis"}</button>
      </div>
      <div className="chips">{EXAMPLES.map((ex) => <button key={ex} className="chip" disabled={running} onClick={() => !running && setQuery(ex)}>{ex}</button>)}</div>
      {error && <div className="err-banner">⚠ {error}</div>}

      {/* ---------- pixel office ---------- */}
      <PixelOffice statuses={status} speech={bubbles} lastMsg={lastMsg} onSelect={(id) => setModal({ kind: "agent", id })} />

      {/* ---------- market stats + charts ---------- */}
      <div className="stat-row">
        <Stat label="Gainers" value={String(gainers)} tone="up" />
        <Stat label="Losers" value={String(losers)} tone="down" />
        <Stat label="Most volatile" value={topVol ? topVol.symbol : "—"} sub={topVol ? `${topVol.range_pct.toFixed(2)}% range` : ""} />
        <Stat label="Symbols live" value={String(movers.length)} />
      </div>

      <div className="charts">
        <div className="chart-card">
          <div className="cc-head">Top movers <span className="cc-sub">change %, last 10m</span></div>
          <ResponsiveContainer width="100%" height={150}>
            <BarChart data={movers.map((m) => ({ symbol: m.symbol, change: m.change_pct }))} margin={{ top: 4, right: 6, bottom: 0, left: -18 }}>
              <XAxis dataKey="symbol" tick={{ fontSize: 9, fill: "#8a8a93" }} interval={0} angle={-30} textAnchor="end" height={42} />
              <YAxis tick={{ fontSize: 9, fill: "#8a8a93" }} />
              <Tooltip cursor={{ fill: "#ffffff10" }} contentStyle={tipStyle} />
              <Bar dataKey="change" radius={[2, 2, 0, 0]}>
                {movers.map((m, i) => <Cell key={i} fill={m.change_pct >= 0 ? UP : DOWN} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="chart-card">
          <div className="cc-head">{series.symbol || "Price"} <span className="cc-sub">close, last 45m</span></div>
          <ResponsiveContainer width="100%" height={150}>
            <AreaChart data={series.data} margin={{ top: 4, right: 6, bottom: 0, left: -18 }}>
              <defs>
                <linearGradient id="pg" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={netUp ? UP : DOWN} stopOpacity={0.35} />
                  <stop offset="100%" stopColor={netUp ? UP : DOWN} stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis dataKey="time" tick={{ fontSize: 9, fill: "#8a8a93" }} interval={Math.ceil(series.data.length / 6)} />
              <YAxis domain={["auto", "auto"]} tick={{ fontSize: 9, fill: "#8a8a93" }} />
              <Tooltip contentStyle={tipStyle} />
              <Area type="monotone" dataKey="close" stroke={netUp ? UP : DOWN} strokeWidth={1.6} fill="url(#pg)" />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        <div className="chart-card">
          <div className="cc-head">Volume <span className="cc-sub">by exchange, last 10m</span></div>
          <ResponsiveContainer width="100%" height={150}>
            <BarChart data={volume} layout="vertical" margin={{ top: 4, right: 10, bottom: 0, left: 10 }}>
              <XAxis type="number" hide />
              <YAxis type="category" dataKey="exchange" tick={{ fontSize: 10, fill: "#c4c4cc" }} width={56} />
              <Tooltip cursor={{ fill: "#ffffff10" }} contentStyle={tipStyle} />
              <Bar dataKey="total_volume" fill="#52525b" radius={[0, 2, 2, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* ---------- point-in-time anchor ---------- */}
      {anchor && (
        <div className="anchor" title="Every data read in this run is filtered <= this moment — no lookahead, fully reproducible.">
          <span className="anchor-dot" /> point-in-time · as of <strong>{anchor}</strong>
        </div>
      )}

      {/* ---------- plan (Planner's decomposition) ---------- */}
      {plan.length > 0 && (
        <div className="plan">
          <div className="plan-head">
            <span>Plan</span>
            <span className="plan-sub">{plan.length} specialist{plan.length > 1 ? "s" : ""} assigned</span>
          </div>
          {plan.map((t, i) => (
            <div key={i} className={`prow p-${t.agent}`}>
              <span className="ptag">{AGENT_BY_ID[t.agent]?.name || t.agent}</span>
              <span className="pfocus">{t.focus}</span>
            </div>
          ))}
        </div>
      )}

      {/* ---------- verification ---------- */}
      {verdicts.length > 0 && (
        <div className="verify">
          <div className="verify-head">
            <span>Verification</span>
            <span className="verify-sub">
              {verdicts.filter((v) => v.verdict === "confirmed").length} confirmed ·{" "}
              {verdicts.filter((v) => v.verdict === "uncertain").length} uncertain ·{" "}
              {verdicts.filter((v) => v.verdict === "refuted").length} refuted
            </span>
          </div>
          {verdicts.map((v, i) => (
            <div key={i} className={`vrow v-${v.verdict}`}>
              <span className="vbadge">{v.verdict}</span>
              <span className="vclaim">{v.corrected && v.revised_claim ? v.revised_claim : v.claim}</span>
              {v.corrected && <span className="vfixed" title={`Original: ${v.claim}`}>self-corrected</span>}
              {v.reason && <span className="vreason">{v.reason}</span>}
            </div>
          ))}
        </div>
      )}

      {/* ---------- briefing (short, expandable) ---------- */}
      {report && (
        <div className="brief">
          <div className="brief-head"><span>Strategist's briefing</span>
            <button className="link-btn" onClick={() => setModal({ kind: "briefing" })}>Read full →</button>
          </div>
          <p className="brief-short">{briefShort}</p>
        </div>
      )}

      {/* ---------- activity ticker ---------- */}
      <div className="ticker">
        <div className="tk-title">Desk activity</div>
        <div className="tk-rows">
          {timeline.length === 0 && <span className="muted">Messages and tool calls scroll here as the desk works.</span>}
          {timeline.slice(-24).map((it, i) => {
            const a = AGENT_BY_ID[it.agent];
            if (it.kind === "message") {
              const to = it.to ? AGENT_BY_ID[it.to] : undefined;
              return <div className="tk-row" key={i}><span className="tk-who">{a?.name}</span><span className="arr">→</span><span className="tk-who">{to?.emoji} {to?.name}</span><span className="tk-msg">{it.label.slice(0, 70)}</span></div>;
            }
            return <div className="tk-row" key={i}><span className="tk-who">{a?.name}</span><span className="tk-verb">{it.kind === "tool_call" ? "calls" : "got"}</span><code className={it.ok === false ? "err" : ""}>{it.label.slice(0, 64)}</code></div>;
          })}
        </div>
      </div>

      {/* ---------- modal ---------- */}
      {modal && (
        <div className="overlay" onClick={() => setModal(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <button className="modal-x" onClick={() => setModal(null)}>✕</button>
            {modal.kind === "briefing" ? (
              <><div className="modal-title">Strategist's Briefing</div><div className="modal-body"><Markdown text={report} /></div></>
            ) : (
              <AgentModal id={modal.id} status={status[modal.id] || "idle"} thinking={thinking[modal.id] || ""} output={output[modal.id] || ""}
                evidence={timeline.filter((t) => t.agent === modal.id && t.kind === "tool_result")} />
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function AgentModal({ id, status, thinking, output, evidence }: { id: AgentId; status: Status; thinking: string; output: string; evidence: TimelineItem[]; }) {
  const a = AGENT_BY_ID[id];
  return (
    <>
      <div className="modal-title">{a.name} <span className="modal-role">{a.role}</span> <span className={`pl-stat s-${status}`}>{status}</span></div>
      <div className="modal-body">
        {thinking && (<><div className="ml">Reasoning</div><pre className="reason">{thinking}</pre></>)}
        <div className="ml">Findings</div>
        {output ? <Markdown text={output} /> : <span className="muted">No findings yet — this analyst hasn't reported.</span>}
        {evidence.length > 0 && (
          <>
            <div className="ml">Evidence ({evidence.length} tool {evidence.length === 1 ? "call" : "calls"}) — the data behind the findings</div>
            {evidence.map((e, i) => (
              <details key={i} className={`evi ${e.ok === false ? "err" : ""}`}>
                <summary><code>{e.tool}({fmtInput(e.input)})</code> <span className="evi-sum">{e.ok === false ? "failed" : "→ " + e.label.split(" → ")[1]}</span></summary>
                <pre className="evi-data">{e.ok === false ? "(no data — see summary)" : JSON.stringify(e.data, null, 2)}</pre>
              </details>
            ))}
          </>
        )}
      </div>
    </>
  );
}

function Stat({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: "up" | "down" }) {
  const color = tone === "up" ? UP : tone === "down" ? DOWN : undefined;
  return (
    <div className="stat">
      <div className="st-label">{label}</div>
      <div className="st-value" style={{ color }}>{value}</div>
      {sub && <div className="st-sub">{sub}</div>}
    </div>
  );
}

const tipStyle: CSSProperties = { background: "#111114", border: "1px solid #2a2a2e", borderRadius: 8, fontSize: 12, color: "#f4f4f5" };
function fmtInput(input: unknown): string {
  if (!input || typeof input !== "object") return "";
  return Object.entries(input as Record<string, unknown>).map(([k, v]) => `${k}=${typeof v === "string" ? v.slice(0, 24) : v}`).join(", ");
}
void NEUTRAL;
