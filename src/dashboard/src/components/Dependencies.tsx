import { useEffect, useState, useCallback } from "react";

const API_BASE = "http://localhost:8000";

type Edge = {
  src: string; dst: string; lag: number; coef: number;
  sign_consistency: number; improve_ar: number; improve_factor: number;
  dir_acc_full: number; folds_improved: number; folds_total: number;
};
type GraphResp = {
  run_id: string | null; as_of?: string; n_obs?: number; n_folds?: number;
  n_candidates?: number; factors?: string[];
  nodes?: { symbol: string; in_degree: number; out_degree: number }[];
  edges?: Edge[]; note?: string;
};
type Overall = {
  mse_zero: number; mse_ar: number; mse_factor: number;
  dir_acc_ar: number; dir_acc_factor: number; rank_ic: number;
};
type Mover = {
  affected_symbol: string; step: number; mean_impact: number;
  p05: number; p95: number; prob_up: number; prob_large: number;
};
type ComoveEdge = { a: string; b: string; partial_corr: number; corr: number; in_mst: number };

const pct = (x: number, d = 2) => (x == null ? "—" : `${(x * 100).toFixed(d)}%`);

function Card({ title, children, sub }: { title: string; sub?: string; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-tremor-border bg-parchment p-4">
      <div className="mb-3">
        <h3 className="text-sm font-semibold text-ink">{title}</h3>
        {sub && <p className="mt-0.5 text-[11px] leading-snug text-ink/50">{sub}</p>}
      </div>
      {children}
    </section>
  );
}

const POS = "#6f8f6a"; // sage  — positive coefficient
const NEG = "#b9763f"; // terracotta — negative coefficient

/** Circular-layout network of the dependency graph (inline SVG, no libs).
 *  directed=true draws arrowheads (lead-lag); false draws plain links (co-movement). */
function NetworkGraph({
  nodes, edges, selected, onSelect, directed = true,
}: {
  nodes: { symbol: string; in_degree: number; out_degree: number }[];
  edges: { src: string; dst: string; coef: number }[];
  selected: string;
  onSelect: (s: string) => void;
  directed?: boolean;
}) {
  const W = 680, H = 460, cx = W / 2, cy = H / 2, R = 168;
  const n = nodes.length;
  const pos = new Map<string, { x: number; y: number; a: number }>();
  nodes.forEach((node, i) => {
    const a = (2 * Math.PI * i) / Math.max(n, 1) - Math.PI / 2;
    pos.set(node.symbol, { x: cx + R * Math.cos(a), y: cy + R * Math.sin(a), a });
  });
  const deg = (s: string) => {
    const nd = nodes.find((x) => x.symbol === s);
    return nd ? nd.in_degree + nd.out_degree : 0;
  };
  const touchesSel = (e: { src: string; dst: string }) => selected && (e.src === selected || e.dst === selected);
  const anySel = !!selected && deg(selected) > 0;

  if (!edges.length) {
    return (
      <div className="grid h-48 place-items-center text-center text-xs text-ink/50">
        No links strong enough to show.<br />That's normal — day-to-day moves are mostly unpredictable.
      </div>
    );
  }

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" style={{ maxHeight: 460 }}>
      {/* click empty space to clear the selection */}
      <rect x={0} y={0} width={W} height={H} fill="transparent" onClick={() => onSelect("")} />
      <defs>
        {[["arrPos", POS], ["arrNeg", NEG], ["arrDim", "#cdc4b0"]].map(([id, c]) => (
          <marker key={id} id={id} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0 0 L10 5 L0 10 z" fill={c} />
          </marker>
        ))}
      </defs>

      {/* edges */}
      {edges.map((e, i) => {
        const a = pos.get(e.src), b = pos.get(e.dst);
        if (!a || !b) return null;
        const dx = b.x - a.x, dy = b.y - a.y, len = Math.hypot(dx, dy) || 1;
        const ux = dx / len, uy = dy / len;
        const r = 9;
        const x1 = a.x + ux * r, y1 = a.y + uy * r;
        const x2 = b.x - ux * (r + 4), y2 = b.y - uy * (r + 4);
        // gentle curve so reciprocal edges don't overlap
        const mx = (x1 + x2) / 2 - uy * 26, my = (y1 + y2) / 2 + ux * 26;
        const active = !anySel || touchesSel(e);
        const col = !active ? "#cdc4b0" : e.coef >= 0 ? POS : NEG;
        const mk = !active ? "arrDim" : e.coef >= 0 ? "arrPos" : "arrNeg";
        return (
          <path key={i} d={`M${x1} ${y1} Q${mx} ${my} ${x2} ${y2}`} fill="none"
            stroke={col} strokeWidth={active ? 1.5 + Math.min(Math.abs(e.coef) * 4, 3) : 1}
            opacity={active ? 0.9 : 0.25} markerEnd={directed ? `url(#${mk})` : undefined} />
        );
      })}

      {/* nodes */}
      {nodes.map((node) => {
        const p = pos.get(node.symbol)!;
        const connected = deg(node.symbol) > 0;
        const isSel = node.symbol === selected;
        const dim = anySel && !isSel && !edges.some((e) => touchesSel(e) && (e.src === node.symbol || e.dst === node.symbol));
        const r = isSel ? 8 : connected ? 6 : 3.5;
        const right = Math.cos(p.a) >= 0;
        return (
          <g key={node.symbol} className="cursor-pointer" onClick={() => onSelect(node.symbol)} opacity={dim ? 0.3 : 1}>
            <circle cx={p.x} cy={p.y} r={r}
              fill={isSel ? "#b9763f" : connected ? "#3a342a" : "#bdb39c"}
              stroke="#fbf8f0" strokeWidth={1.5} />
            <text x={p.x + (right ? r + 4 : -(r + 4))} y={p.y + 3}
              textAnchor={right ? "start" : "end"}
              fontSize={isSel ? 11 : 9.5}
              fontWeight={isSel || connected ? 600 : 400}
              fill={isSel ? "#b9763f" : connected ? "#3a342a" : "#8a8067"}>
              {node.symbol}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

export default function Dependencies() {
  const [graph, setGraph] = useState<GraphResp | null>(null);
  const [overall, setOverall] = useState<Overall | null>(null);
  const [comove, setComove] = useState<{ nodes: { symbol: string; degree: number }[]; edges: ComoveEdge[] } | null>(null);
  const [mode, setMode] = useState<"lead" | "comove">("lead");
  const [sel, setSel] = useState<string>("");
  const [symData, setSymData] = useState<any>(null);
  const [shockPct, setShockPct] = useState(5);
  const [horizon, setHorizon] = useState(5);
  const [movers, setMovers] = useState<Mover[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [rebuilding, setRebuilding] = useState(false);

  const load = useCallback(async () => {
    const [g, m, c] = await Promise.all([
      fetch(`${API_BASE}/api/dependencies/graph`).then((r) => r.json()),
      fetch(`${API_BASE}/api/dependencies/metrics`).then((r) => r.json()),
      fetch(`${API_BASE}/api/dependencies/comovement`).then((r) => r.json()),
    ]);
    setGraph(g);
    setOverall(m.overall || null);
    setComove({ nodes: c.nodes || [], edges: c.edges || [] });
    if (g.nodes?.length && !sel) setSel(g.nodes[0].symbol);
  }, [sel]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (!sel) { setSymData(null); setMovers(null); return; }
    fetch(`${API_BASE}/api/dependencies/symbol/${encodeURIComponent(sel)}`)
      .then((r) => r.json()).then(setSymData).catch(() => setSymData(null));
  }, [sel, graph?.run_id]);

  const rebuild = async () => {
    setRebuilding(true);
    try { await fetch(`${API_BASE}/api/dependencies/rebuild`, { method: "POST" }); await load(); }
    finally { setRebuilding(false); }
  };

  const runShock = async () => {
    if (!sel) return;
    setBusy(true);
    try {
      const r = await fetch(`${API_BASE}/api/dependencies/shock`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol: sel, shock_pct: shockPct, horizon }),
      }).then((x) => x.json());
      setMovers(r.top_movers || []);
    } finally { setBusy(false); }
  };

  const edges = graph?.edges || [];
  const emptyGraph = graph?.run_id && edges.length === 0;
  // honest quality read: is AR even beating a zero forecast?
  const arBeatsZero = overall && overall.mse_ar < overall.mse_zero;

  // mode-aware inputs for the network diagram
  const comoveGEdges = (comove?.edges || []).map((e) => ({ src: e.a, dst: e.b, coef: e.partial_corr }));
  const comoveNodes = (comove?.nodes || []).map((n) => ({ symbol: n.symbol, in_degree: n.degree, out_degree: 0 }));
  const gNodes = mode === "lead" ? (graph?.nodes || []) : comoveNodes;
  const gEdges = mode === "lead" ? edges : comoveGEdges;

  if (!graph) return <div className="text-sm text-ink/50">Loading…</div>;

  if (!graph.run_id) {
    return (
      <div className="rounded-xl border border-tremor-border bg-parchment p-6 text-sm text-ink/70">
        <p>No graph built yet.</p>
        <button onClick={rebuild} disabled={rebuilding}
          className="mt-3 rounded-lg bg-terracotta px-4 py-2 text-sm font-medium text-parchment disabled:opacity-50">
          {rebuilding ? "Building…" : "Build graph"}
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* header / run meta */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-tremor-border bg-parchment p-4">
        <div className="text-xs text-ink/60">
          Built from <span className="font-semibold text-ink">{graph.n_obs} trading days</span> of data, up to {graph.as_of}.{" "}
          Kept <span className="font-semibold text-ink">{edges.length}</span> link{edges.length === 1 ? "" : "s"} out of {graph.n_candidates} tested.
        </div>
        <button onClick={rebuild} disabled={rebuilding}
          className="rounded-lg bg-terracotta px-4 py-1.5 text-xs font-medium text-parchment disabled:opacity-50">
          {rebuilding ? "Rebuilding…" : "Rebuild"}
        </button>
      </div>

      {/* honesty banner — mode-aware */}
      {mode === "lead" ? (
        <div className={`rounded-xl border p-3 text-xs leading-relaxed ${arBeatsZero ? "border-sage/40 bg-sage/10 text-ink/80" : "border-amber-400/50 bg-amber-50 text-amber-900"}`}>
          {arBeatsZero
            ? "These links passed our checks — on data they'd never seen, they called next-day moves a bit better than simpler methods. The effect is small, so treat them as weak hints, not sure things."
            : "⚠ Heads up: day-to-day moves here are close to unpredictable — even simple methods barely beat guessing \"no change.\" Treat any links below as faint patterns, never as one stock causing another to move."}
        </div>
      ) : (
        <div className="rounded-xl border border-sage/40 bg-sage/10 p-3 text-xs leading-relaxed text-ink/80">
          Same-day structure: which names move together once market, sector &amp; macro swings are stripped out. This is <b>association</b> (how they co-move), not prediction. Negative links = <b>substitutes</b> — e.g. money rotating between two big banks.
        </div>
      )}

      {/* network graph with mode toggle */}
      <Card
        title={mode === "lead" ? "Lead-lag network (next-day)" : "Co-movement network (same-day)"}
        sub={mode === "lead"
          ? "An arrow A→B means A's move today tends to come just before B's tomorrow. Green = same way, orange = opposite. Thicker = stronger. Tap a stock to focus; tap again or empty space to clear."
          : "A line A—B means the two move together the SAME day even after removing market, sector & every other stock (a direct link). Green = move together, orange = move oppositely. Tap a stock to focus."}>
        <div className="mb-3 inline-flex rounded-lg border border-tremor-border bg-cream p-0.5 text-xs font-medium">
          <button onClick={() => setMode("lead")}
            className={`rounded-md px-3 py-1 transition-colors ${mode === "lead" ? "bg-terracotta text-parchment" : "text-ink/60"}`}>
            Lead-lag (predictive)
          </button>
          <button onClick={() => setMode("comove")}
            className={`rounded-md px-3 py-1 transition-colors ${mode === "comove" ? "bg-terracotta text-parchment" : "text-ink/60"}`}>
            Co-movement (same-day)
          </button>
        </div>
        <NetworkGraph nodes={gNodes} edges={gEdges} selected={sel} directed={mode === "lead"}
          onSelect={(s) => setSel((prev) => (prev === s ? "" : s))} />
      </Card>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* diagnostics */}
        <Card title="Can we actually predict tomorrow?"
          sub="How often each simple method calls the next day's direction (up or down) correctly.">
          {overall ? (
            <table className="w-full text-xs">
              <thead><tr className="text-left text-ink/50">
                <th className="py-1">Method</th><th className="text-right">Got direction right</th></tr></thead>
              <tbody>
                <tr className="border-t border-tremor-border/50"><td className="py-1">Just guess "no change"</td><td className="text-right text-ink/40">—</td></tr>
                <tr className="border-t border-tremor-border/50"><td className="py-1">From the stock's own recent moves</td><td className="text-right font-mono">{pct(overall.dir_acc_ar, 0)}</td></tr>
                <tr className="border-t border-tremor-border/50"><td className="py-1">From market &amp; sector trends</td><td className="text-right font-mono">{pct(overall.dir_acc_factor, 0)}</td></tr>
              </tbody>
            </table>
          ) : <p className="text-xs text-ink/50">No data yet.</p>}
          <p className="mt-2 text-[11px] leading-snug text-ink/50">
            Around 50% is a coin flip — and that's roughly what daily moves are. A link only makes it
            into the graph if it beats these methods consistently on data it had never seen.
          </p>
        </Card>

        {/* edges — mode-aware */}
        {mode === "lead" ? (
          <Card title={`Links found (${edges.length})`}
            sub="“A → B” means A's move today hints at B's move the next day.">
            {emptyGraph ? (
              <p className="text-xs text-ink/60">No links were strong enough to keep. That's expected, not a bug — most day-to-day moves just aren't predictable.</p>
            ) : (
              <div className="max-h-64 space-y-1 overflow-y-auto">
                {edges.map((e, i) => (
                  <div key={i} className="flex items-center justify-between rounded-lg bg-cream/60 px-3 py-1.5 text-xs">
                    <span className="font-medium text-ink">
                      {e.src} <span className="text-ink/40">→</span> {e.dst}
                    </span>
                    <span className="text-ink/60">
                      <span className={e.coef >= 0 ? "text-sage" : "text-terracotta"}>
                        {e.coef >= 0 ? "same direction" : "opposite"}
                      </span>
                      {" · "}consistent {pct(e.sign_consistency, 0)} of the time
                    </span>
                  </div>
                ))}
              </div>
            )}
          </Card>
        ) : (
          <Card title={`Co-movement links (${comove?.edges.length || 0})`}
            sub="Direct same-day links, strongest first. “MST” marks the backbone tree that keeps the network connected.">
            <div className="max-h-64 space-y-1 overflow-y-auto">
              {(comove?.edges || []).slice(0, 200).map((e, i) => (
                <div key={i} className="flex items-center justify-between rounded-lg bg-cream/60 px-3 py-1.5 text-xs">
                  <span className="font-medium text-ink">
                    {e.a} <span className="text-ink/40">—</span> {e.b}
                    {e.in_mst ? <span className="ml-1.5 text-[9px] uppercase text-ink/40">mst</span> : null}
                  </span>
                  <span className={e.partial_corr >= 0 ? "text-sage" : "text-terracotta"}>
                    {e.partial_corr >= 0 ? "together" : "opposite"} {e.partial_corr.toFixed(2)}
                  </span>
                </div>
              ))}
            </div>
          </Card>
        )}
      </div>

      {/* symbol drilldown + shock */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card title="What moves with this stock"
          sub="Stocks whose moves tend to come just before or just after the one you pick.">
          <select value={sel} onChange={(e) => setSel(e.target.value)}
            className="mb-3 w-full rounded-lg border border-tremor-border bg-cream px-2 py-1.5 text-sm">
            <option value="">— pick a stock —</option>
            {graph.nodes?.map((n) => <option key={n.symbol} value={n.symbol}>{n.symbol}</option>)}
          </select>
          <div className="grid grid-cols-2 gap-3 text-xs">
            <div>
              <p className="mb-1 font-semibold text-ink/70">Moves just after these</p>
              {symData?.upstream_drivers?.length
                ? symData.upstream_drivers.map((d: any, i: number) => (
                    <div key={i} className="flex justify-between rounded bg-cream/60 px-2 py-1">
                      <span>{d.driver}</span>
                      <span className={d.coef >= 0 ? "text-sage" : "text-terracotta"}>{d.coef >= 0 ? "same way" : "opposite"}</span>
                    </div>))
                : <p className="text-ink/40">nothing clear</p>}
            </div>
            <div>
              <p className="mb-1 font-semibold text-ink/70">Moves just before these</p>
              {symData?.downstream_dependents?.length
                ? symData.downstream_dependents.map((d: any, i: number) => (
                    <div key={i} className="flex justify-between rounded bg-cream/60 px-2 py-1">
                      <span>{d.dependent}</span>
                      <span className={d.coef >= 0 ? "text-sage" : "text-terracotta"}>{d.coef >= 0 ? "same way" : "opposite"}</span>
                    </div>))
                : <p className="text-ink/40">nothing clear</p>}
            </div>
          </div>
        </Card>

        <Card title="What if this stock suddenly jumps?"
          sub="Imagine the stock you picked moves sharply, then see which others have tended to follow. A rough what-if — not a prediction or advice.">
          <div className="flex flex-wrap items-end gap-2">
            <label className="text-xs text-ink/60">Jump %
              <input type="number" value={shockPct} step={1} onChange={(e) => setShockPct(+e.target.value)}
                className="mt-0.5 block w-20 rounded border border-tremor-border bg-cream px-2 py-1 text-sm" /></label>
            <label className="text-xs text-ink/60">Days ahead
              <input type="number" value={horizon} min={1} max={10} onChange={(e) => setHorizon(+e.target.value)}
                className="mt-0.5 block w-20 rounded border border-tremor-border bg-cream px-2 py-1 text-sm" /></label>
            <button onClick={runShock} disabled={busy || !sel}
              className="rounded-lg bg-terracotta px-3 py-1.5 text-xs font-medium text-parchment disabled:opacity-50">
              {busy ? "Working…" : sel ? `See what follows ${sel}` : "Pick a stock"}
            </button>
          </div>
          {movers && (
            <div className="mt-3 max-h-52 space-y-1 overflow-y-auto text-xs">
              {movers.filter((m) => m.affected_symbol !== sel).map((m, i) => {
                const informative = Math.abs(m.prob_up - 0.5) > 0.05;
                return (
                  <div key={i} className="flex items-center justify-between rounded bg-cream/60 px-2 py-1">
                    <span className="font-medium">{m.affected_symbol}</span>
                    <span className={informative ? (m.mean_impact >= 0 ? "text-sage" : "text-terracotta") : "text-ink/40"}>
                      {informative
                        ? <>{m.mean_impact >= 0 ? "+" : ""}{m.mean_impact.toFixed(2)}% typical · usually {m.p05.toFixed(1)}% to {m.p95.toFixed(1)}%</>
                        : "little to no effect"}
                    </span>
                  </div>
                );
              })}
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
