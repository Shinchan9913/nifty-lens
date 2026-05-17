import { useState, useEffect } from "react";

interface Summary {
  total_trades: number;
  unique_assets: number;
  regions_active: number;
}

const API_BASE = "http://localhost:8000";

export default function SummaryCards() {
  const [summary, setSummary] = useState<Summary | null>(null);

  const fetchSummary = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/dashboard/summary`);
      const data = await res.json();
      setSummary(data);
    } catch {
      // API not ready yet
    }
  };

  useEffect(() => {
    fetchSummary();
    const interval = setInterval(fetchSummary, 5000);
    return () => clearInterval(interval);
  }, []);

  const cards = [
    { label: "Trades (Last 1 min)", value: summary?.total_trades ?? 0, color: "#6366f1" },
    { label: "Active Assets", value: summary?.unique_assets ?? 0, color: "#10b981" },
    { label: "Active Regions", value: summary?.regions_active ?? 0, color: "#f59e0b" },
  ];

  return (
    <div className="summary-cards">
      {cards.map((card) => (
        <div key={card.label} className="summary-card" style={{ borderTop: `4px solid ${card.color}` }}>
          <span className="card-label">{card.label}</span>
          <span className="card-value">{card.value.toLocaleString()}</span>
        </div>
      ))}
    </div>
  );
}