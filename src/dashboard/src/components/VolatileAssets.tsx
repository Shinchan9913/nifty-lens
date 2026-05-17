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
  region: string;
  asset_class: string;
  trade_count: number;
  price_range: number;
  avg_price: number;
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
    "Price Range": Math.round(a.price_range * 100) / 100,
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
                <th>Region</th>
                <th>Class</th>
                <th>Trades</th>
                <th>Range</th>
                <th>Avg Price</th>
              </tr>
            </thead>
            <tbody>
              {assets.map((a) => (
                <tr key={a.symbol}>
                  <td><strong>{a.symbol}</strong></td>
                  <td>{a.region}</td>
                  <td>{a.asset_class}</td>
                  <td>{a.trade_count.toLocaleString()}</td>
                  <td>${a.price_range.toFixed(2)}</td>
                  <td>${a.avg_price.toFixed(2)}</td>
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
              <Bar dataKey="Price Range" fill="#ef4444" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}