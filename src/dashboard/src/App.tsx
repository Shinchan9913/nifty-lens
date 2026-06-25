import { useState, type ReactNode } from "react";
import MarketDashboard from "./components/MarketDashboard";
import AgentConsole from "./components/AgentConsole";
import Dependencies from "./components/Dependencies";

type Tab = "markets" | "floor" | "dependencies";

const NAV: { id: Tab; label: string; icon: ReactNode }[] = [
  {
    id: "markets",
    label: "Markets",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5">
        <path d="M3 3v18h18" /><path d="m19 9-5 5-4-4-3 3" />
      </svg>
    ),
  },
  {
    id: "floor",
    label: "Trading Floor",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5">
        <rect x="3" y="4" width="18" height="14" rx="2" /><path d="M3 10h18M8 18v3M16 18v3" />
      </svg>
    ),
  },
  {
    id: "dependencies",
    label: "Dependencies",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5">
        <circle cx="5" cy="6" r="2" /><circle cx="19" cy="6" r="2" /><circle cx="12" cy="18" r="2" />
        <path d="M7 6h10M6 8l5 8M18 8l-5 8" />
      </svg>
    ),
  },
];

export default function App() {
  const [tab, setTab] = useState<Tab>("markets");

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-cream text-ink">
      {/* sidebar */}
      <aside className="flex w-16 flex-col items-center gap-2 border-r border-tremor-border bg-parchment py-4 sm:w-56 sm:items-stretch sm:px-3">
        <div className="mb-4 flex items-center gap-2 px-2">
          <div className="grid h-9 w-9 place-items-center rounded-lg bg-terracotta text-parchment">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" className="h-5 w-5"><path d="M4 19V5m0 14h16M8 16l3-4 3 2 4-6" strokeLinecap="round" strokeLinejoin="round" /></svg>
          </div>
          <span className="hidden font-pixel text-[11px] leading-tight text-ink sm:block">nifty<br />lens</span>
        </div>
        {NAV.map((n) => (
          <button
            key={n.id}
            onClick={() => setTab(n.id)}
            className={`flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors ${
              tab === n.id ? "bg-terracotta/15 text-terracotta" : "text-ink/60 hover:bg-cream hover:text-ink"
            }`}
          >
            <span className={tab === n.id ? "text-terracotta" : ""}>{n.icon}</span>
            <span className="hidden sm:block">{n.label}</span>
          </button>
        ))}
        <div className="mt-auto hidden px-3 text-[11px] text-ink/40 sm:block">
          ClickHouse · FastAPI · multi-agent desk
        </div>
      </aside>

      {/* main */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center justify-between border-b border-tremor-border bg-parchment px-6">
          <h1 className="text-base font-semibold text-ink">
            {tab === "markets" ? "Market Analytics" : tab === "floor" ? "Trading Floor" : "NSE Dependency Graph"}
          </h1>
          <span className="flex items-center gap-2 text-xs text-ink/50">
            <span className="h-2 w-2 animate-pulse rounded-full bg-sage" /> live
          </span>
        </header>
        <main className="min-w-0 flex-1 overflow-y-auto p-6">
          {tab === "markets" ? <MarketDashboard /> : tab === "floor" ? <AgentConsole /> : <Dependencies />}
        </main>
      </div>
    </div>
  );
}
