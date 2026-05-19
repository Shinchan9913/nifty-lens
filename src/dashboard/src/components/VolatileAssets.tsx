import { useState, useEffect } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

interface Asset {
  symbol: string;
  exchange: string;
  open: number;
  high: number;
  low: number;
  close: number;
  change_pct: number;
  range_pct: number;
  total_volume: number;
}

const API_BASE = "http://localhost:8000";

export default function VolatileAssets() {
  const [assets, setAssets] = useState<Asset[]>([]);

  const fetchData = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/volatile?minutes=5&limit=10`);
      const data = await res.json();
      setAssets(data.assets ?? []);
    } catch {
      // API not ready yet
    }
  };

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 5000);
    return () => clearInterval(interval);
  }, []);

  const chartData = assets.map((a) => ({
    name: a.symbol,
    "Range %": Math.round(a.range_pct * 100) / 100,
  }));

  return (
    <div className="card">
      <h3>🔥 Top 10 Most Volatile Assets (Last 5 min)</h3>
      <div className="volatile-grid">
        <div className="volatile-table">
          <table>
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Exchange</th>
                <th>Open</th>
                <th>High</th>
                <th>Low</th>
                <th>Close</th>
                <th>Change %</th>
                <th>Range %</th>
              </tr>
            </thead>
            <tbody>
              {assets.map((a) => (
                <tr key={a.symbol}>
                  <td><strong>{a.symbol}</strong></td>
                  <td>{a.exchange}</td>
                  <td>${a.open.toFixed(2)}</td>
                  <td>${a.high.toFixed(2)}</td>
                  <td>${a.low.toFixed(2)}</td>
                  <td>${a.close.toFixed(2)}</td>
                  <td style={{ color: a.change_pct >= 0 ? "#10b981" : "#ef4444" }}>
                    {a.change_pct >= 0 ? "+" : ""}{a.change_pct}%
                  </td>
                  <td>{a.range_pct}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="volatile-chart">
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
              <XAxis dataKey="name" stroke="#9ca3af" fontSize={12} />
              <YAxis stroke="#9ca3af" fontSize={12} />
              <Tooltip
                contentStyle={{ background: "#1f2937", border: "1px solid #374151", borderRadius: 8 }}
              />
              <Bar dataKey="Range %" fill="#ef4444" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}