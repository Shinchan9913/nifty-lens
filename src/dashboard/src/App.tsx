import SummaryCards from "./components/SummaryCards";
import VolatileAssets from "./components/VolatileAssets";
import VolumeChart from "./components/VolumeChart";
import "./App.css";

function App() {
  return (
    <div className="dashboard">
      <header className="dashboard-header">
        <h1>📊 Real-Time FinTech Analytics</h1>
        <p className="subtitle">ClickHouse · Redpanda · 5,000 txns/sec</p>
      </header>
      <SummaryCards />
      <div className="dashboard-grid">
        <VolatileAssets />
        <VolumeChart />
      </div>
    </div>
  );
}

export default App;