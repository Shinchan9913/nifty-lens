import { useState, useEffect } from "react";
import {
  PieChart,
  Pie,
  Cell,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";

const COLORS = ["#6366f1", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899"];

interface VolumeData {
  region: string;
  asset_class: string;
  trade_count: number;
  total_volume: number;
}

const API_BASE = "http://localhost:8000";

export default function VolumeChart() {
  const [data, setData] = useState<VolumeData[]>([]);

  const fetchData = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/volume?minutes=5`);
      const json = await res.json();
      setData(json.data ?? []);
    } catch {
      // API not ready yet
    }
  };

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 5000);
    return () => clearInterval(interval);
  }, []);

  // Aggregate by region for the pie chart
  const regionTotals = data.reduce<Record<string, number>>((acc, d) => {
    acc[d.region] = (acc[d.region] || 0) + d.total_volume;
    return acc;
  }, {});

  const pieData = Object.entries(regionTotals).map(([name, value]) => ({
    name,
    value: Math.round(value),
  }));

  return (
    <div className="card">
      <h3>💹 Trade Volume by Region (Last 5 min)</h3>
      <div className="volume-grid">
        <div className="volume-table">
          <table>
            <thead>
              <tr>
                <th>Region</th>
                <th>Asset Class</th>
                <th>Trades</th>
                <th>Volume ($)</th>
              </tr>
            </thead>
            <tbody>
              {data.map((d, i) => (
                <tr key={i}>
                  <td>{d.region}</td>
                  <td>{d.asset_class}</td>
                  <td>{d.trade_count.toLocaleString()}</td>
                  <td>${d.total_volume.toLocaleString(undefined, { maximumFractionDigits: 2 })}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="volume-pie">
          <ResponsiveContainer width="100%" height={280}>
            <PieChart>
              <Pie
                data={pieData}
                dataKey="value"
                nameKey="name"
                cx="50%"
                cy="50%"
                outerRadius={100}
                label={({ name, value }) => `${name}: $${(value / 1e6).toFixed(1)}M`}
              >
                {pieData.map((_, i) => (
                  <Cell key={i} fill={COLORS[i % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip
                contentStyle={{ background: "#1f2937", border: "1px solid #374151", borderRadius: 8 }}
              />
              <Legend />
            </PieChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}