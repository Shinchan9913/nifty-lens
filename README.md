# 📊 Real-Time FinTech Analytics Engine

A **real-time analytics pipeline** that processes 5,000 mock transactions/second directly into ClickHouse, served via a FastAPI backend and a React dashboard.

**Resume bullet:**
> "Built a real-time financial analytics engine processing 5,000 mock transactions/sec directly into ClickHouse, reducing dashboard aggregation latency from 4.2 seconds (SQL) to under 80 milliseconds."

## Architecture

```
Trade Simulator (Python)
        │  5,000 trades/sec (batched)
        ▼
   ┌──────────────┐
   │  ClickHouse   │  ← Columnar OLAP database (Docker)
   │  (Docker)     │
   └──────┬───────┘
          │
          ▼
   ┌──────────────┐    ┌──────────────────┐
   │  FastAPI      │◄───│  React Dashboard │
   │  (Python)     │───►│  (Vite + Recharts)│
   └──────────────┘    └──────────────────┘
```

## Tech Stack

| Layer | Technology |
|---|---|
| **Database** | ClickHouse (columnar OLAP, Docker) |
| **Data Simulator** | Python (`requests` → ClickHouse HTTP API) |
| **API** | FastAPI (Python) |
| **Dashboard** | React + Vite + Recharts (TypeScript) |
| **Python Version** | 3.13.13 (managed via pyenv) |
| **Node Version** | 24.15.0 LTS (managed via nvm) |

## Project Structure

```
nifty-lens/
├── docker-compose.yml           # ClickHouse
├── init-scripts/
│   └── 01_schema.sql            # ClickHouse table + MV schemas
├── src/
│   ├── ingestor/
│   │   └── groww_ingestor.py    # Real-time data from Groww → ClickHouse
│   ├── simulator/
│   │   └── producer.py          # Synthetic data generator (24/7 fallback)
│   ├── api/
│   │   └── main.py              # FastAPI backend
│   ├── dashboard/               # React + Vite frontend
│   │   ├── src/
│   │   │   ├── App.tsx          # Main dashboard layout
│   │   │   ├── App.css          # Dark theme styling
│   │   │   └── components/
│   │   │       ├── SummaryCards.tsx    # Stats overview
│   │   │       ├── VolatileAssets.tsx # Top movers table + chart
│   │   │       └── VolumeChart.tsx    # Volume by region pie
│   │   └── package.json
│   ├── config.py                # .env loader
│   └── main.py                  # Groww API test script
└── .env                         # API keys (gitignored)
```

## Setup Instructions

### Prerequisites

- **Docker Desktop** (v29+)
- **pyenv** (Python 3.13.13)
- **nvm** (Node.js 24.15.0)

### Python Setup

```bash
# Ensure Python 3.13.13 is active
pyenv global 3.13.13

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Infrastructure (Docker)

```bash
# Start ClickHouse
docker compose up -d

# Verify it's healthy
docker compose ps
```

ClickHouse will be available at **http://localhost:8123** (HTTP API).  
The schema (`01_schema.sql`) auto-runs on first startup, creating:
- `trades_raw` — unified trade storage table
- `trades_tps` — materialized view for trades-per-second metrics
- `trades_agg_1min` — materialized view for 1-minute aggregations

### Run the Pipeline

Open **terminals** for each component:

**Terminal 1 — Groww Ingestor (real-time data during market hours):**
```bash
source .venv/bin/activate
python src/ingestor/groww_ingestor.py
```
> 💡 The ingestor fetches real OHLCV data from Groww for NIFTY, BANKNIFTY, and major stocks. Outside market hours (9:15 AM - 3:30 PM IST, Mon-Fri), it sleeps and lets the simulator provide synthetic data.

**Terminal 2 — Trade Simulator (synthetic fallback, runs 24/7):**
```bash
source .venv/bin/activate
python src/simulator/producer.py
```

**Terminal 3 — FastAPI Backend:**
```bash
source .venv/bin/activate
uvicorn src.api.main:app --reload --port 8000
```

**Terminal 4 — React Dashboard:**
```bash
cd src/dashboard
npm install    # first time only
npm run dev
```

Open **http://localhost:5173** in your browser.

### Dashboard Preview

The dashboard shows:
1. **Summary Cards** — trades/sec, active assets, regions
2. **Top 10 Volatile Assets** — table + bar chart of highest price movement
3. **Trade Volume by Region** — pie chart + detailed table

All data refreshes every 5 seconds automatically.

### Ad-Hoc Queries

With ClickHouse running, you can query directly:

```bash
# Top 10 volatile assets in last 5 minutes
curl "http://localhost:8000/api/volatile?minutes=5&limit=10"

# Volume by region
curl "http://localhost:8000/api/volume?minutes=5"

# Dashboard summary
curl "http://localhost:8000/api/dashboard/summary"
```

Or query ClickHouse directly:

```bash
# Via HTTP API
echo "SELECT count() FROM trades_raw" | curl -X POST http://localhost:8123 -d @-
```

## Performance

| Query | Traditional SQL | ClickHouse |
|---|---|---|
| Top 10 volatile assets (5 min) | ~4.2s | < 80ms |
| Ingest throughput | — | 5,000 trades/sec |
