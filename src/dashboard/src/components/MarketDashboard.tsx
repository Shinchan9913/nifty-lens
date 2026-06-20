import { useEffect, useState } from "react";
import {
  Card, Grid, Metric, Text, Title, Flex, BadgeDelta, AreaChart, BarList,
} from "@tremor/react";

const API_BASE = "http://localhost:8000";

interface Mover { symbol: string; change_pct: number; range_pct: number; close: number; total_volume: number; }
interface Summary { total_symbols: number; total_exchanges: number; total_candles: number; as_of: string | null; }

const compact = (n: number) => Intl.NumberFormat("en-IN", { notation: "compact", maximumFractionDigits: 1 }).format(n);
const rupee = (n: number) => `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;

function freshness(asOf: string | null): { text: string; stale: boolean } {
  if (!asOf) return { text: "no data — run the seeder", stale: true };
  const t = new Date(asOf.replace(" ", "T"));
  const mins = (Date.now() - t.getTime()) / 60000;
  const hhmm = t.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" });
  const day = t.toLocaleDateString("en-IN", { day: "2-digit", month: "short" });
  if (mins > 20) return { text: `last session · ${day} ${hhmm} (markets closed)`, stale: true };
  return { text: `live · as of ${hhmm}`, stale: false };
}

export default function MarketDashboard() {
  const [summary, setSummary] = useState<Summary>({ total_symbols: 0, total_exchanges: 0, total_candles: 0, as_of: null });
  const [movers, setMovers] = useState<Mover[]>([]);
  const [volume, setVolume] = useState<{ exchange: string; total_volume: number }[]>([]);
  const [series, setSeries] = useState<{ symbol: string; data: { time: string; close: number }[] }>({ symbol: "", data: [] });

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const [s, v, vol] = await Promise.all([
          fetch(`${API_BASE}/api/dashboard/summary`).then((r) => r.json()),
          fetch(`${API_BASE}/api/volatile?minutes=10&limit=8`).then((r) => r.json()),
          fetch(`${API_BASE}/api/volume?minutes=10`).then((r) => r.json()),
        ]);
        if (!alive) return;
        setSummary(s);
        setMovers(v.assets || []);
        setVolume(vol.data || []);
        const top = (v.assets || [])[0]?.symbol;
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

  const gainers = movers.filter((m) => m.change_pct >= 0).length;
  const losers = movers.filter((m) => m.change_pct < 0).length;
  const top = movers[0];
  const netUp = series.data.length >= 2 ? series.data[series.data.length - 1].close >= series.data[0].close : true;
  const pct = (n: number) => `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;

  const moverBars = movers.map((m) => ({
    name: m.symbol,
    value: Math.round(Math.abs(m.change_pct) * 100) / 100,
    color: m.change_pct >= 0 ? "emerald" : "rose",
  }));
  const volBars = volume.map((v) => ({ name: v.exchange, value: Math.round(v.total_volume) }));

  const fresh = freshness(summary.as_of);

  return (
    <div className="space-y-6">
      {/* freshness banner */}
      <div className="flex items-center gap-2 text-sm">
        <span className={`h-2 w-2 rounded-full ${fresh.stale ? "bg-amber-500" : "animate-pulse bg-emerald-500"}`} />
        <span className="text-ink/60">{fresh.text}</span>
      </div>

      {/* KPI row */}
      <Grid numItemsSm={2} numItemsLg={4} className="gap-5">
        <KpiCard label="Symbols tracked" value={String(summary.total_symbols)} hint={`${summary.total_candles.toLocaleString()} candles · 10m`} />
        <KpiCard label="Gainers" value={String(gainers)} delta="increase" deltaText="up" />
        <KpiCard label="Losers" value={String(losers)} delta="decrease" deltaText="down" />
        <KpiCard label="Most volatile" value={top ? top.symbol : "—"} hint={top ? `${top.range_pct.toFixed(2)}% range` : ""} />
      </Grid>

      <Grid numItemsLg={3} className="gap-5">
        {/* price chart spans 2 */}
        <Card className="lg:col-span-2">
          <Flex>
            <div>
              <Title>{series.symbol || "Price"}</Title>
              <Text>Close price · last 45 minutes</Text>
            </div>
            {series.data.length >= 2 && (
              <BadgeDelta deltaType={netUp ? "increase" : "decrease"}>
                {pct(((series.data[series.data.length - 1].close - series.data[0].close) / series.data[0].close) * 100)}
              </BadgeDelta>
            )}
          </Flex>
          <AreaChart
            className="mt-4 h-60"
            data={series.data}
            index="time"
            categories={["close"]}
            colors={[netUp ? "emerald" : "rose"]}
            showLegend={false}
            showAnimation
            curveType="monotone"
            yAxisWidth={56}
            valueFormatter={rupee}
          />
        </Card>

        {/* volume */}
        <Card>
          <Title>Volume by exchange</Title>
          <Text>Traded volume · last 10 minutes</Text>
          <BarList data={volBars} color="amber" className="mt-4" valueFormatter={compact} />
        </Card>
      </Grid>

      {/* top movers with green/red bars */}
      <Card>
        <Title>Top movers</Title>
        <Text>Absolute change % · last 10 minutes (green up · red down)</Text>
        <div className="mt-4 space-y-3">
          {moverBars.length === 0 && <Text>No data yet — run the seeder.</Text>}
          {movers.map((m) => {
            const up = m.change_pct >= 0;
            const w = Math.min(100, Math.abs(m.change_pct) * 28);
            return (
              <div key={m.symbol} className="flex items-center gap-3">
                <span className="w-24 shrink-0 truncate text-sm font-medium text-ink">{m.symbol}</span>
                <div className="h-5 flex-1 overflow-hidden rounded bg-tremor-background-subtle">
                  <div className={`h-full rounded ${up ? "bg-emerald-500" : "bg-rose-500"}`} style={{ width: `${Math.max(4, w)}%` }} />
                </div>
                <span className={`w-20 shrink-0 text-right text-sm font-semibold ${up ? "text-emerald-600" : "text-rose-600"}`}>{pct(m.change_pct)}</span>
              </div>
            );
          })}
        </div>
      </Card>
    </div>
  );
}

function KpiCard({ label, value, hint, delta, deltaText }: { label: string; value: string; hint?: string; delta?: "increase" | "decrease"; deltaText?: string; }) {
  return (
    <Card>
      <Flex alignItems="start">
        <Text>{label}</Text>
        {delta && <BadgeDelta deltaType={delta}>{deltaText}</BadgeDelta>}
      </Flex>
      <Metric className="mt-2">{value}</Metric>
      {hint && <Text className="mt-1">{hint}</Text>}
    </Card>
  );
}
