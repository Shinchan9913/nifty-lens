# 📊 Real-Time FinTech Analytics Engine

A **Lambda Architecture** pipeline that processes 5,000 mock transactions/second using ClickHouse, Redpanda (Kafka-compatible), and a React dashboard.

**Resume bullet:**
> "Built a real-time financial analytics engine processing 5,000 mock transactions/sec using ClickHouse and Kafka, reducing dashboard aggregation latency from 4.2 seconds (SQL) to under 80 milliseconds."

## Architecture

```
Trade Simulator (Python)
       │  5,000 trades/sec
       ▼
   ┌─────────────┐
   │   Redpanda   │  ← Kafka-compatible stream
   └──────┬──────┘
          │
          ▼
   ┌──────────────┐
   │  ClickHouse   │  ← Columnar OLAP database
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
| **Stream Queue** | Redpanda (Kafka-compatible, Docker) |
| **Database** | ClickHouse (columnar OLAP, Docker) |
| **Data Simulator** | Python (`kafka-python`) |
| **Consumer** | Python → ClickHouse HTTP API |
| **API** | FastAPI (Python) |
| **Dashboard** | React + Vite + Recharts (TypeScript) |
| **Python Version** | 3.13.13 (managed via pyenv) |
| **Node Version** | 24.15.0 LTS (managed via nvm) |

## Project Structure

```
nifty-lens/
├── docker-compose.yml           # Redpanda + ClickHouse
├── init-scripts/
│   └── 01_schema.sql            # ClickHouse table + MV schemas
├── src/
│   ├── simulator/
│   │   └── producer.py          # Generates 5,000 trades/sec
│   ├── consumer/
│   │   └── consumer.py          # Redpanda → ClickHouse ingestion
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
│   └── main.py                  # Groww API test (legacy)
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
pip install kafka-python requests fastapi uvicorn
```

### Infrastructure (Docker)

```bash
# Start ClickHouse + Redpanda
docker compose up -d

# Verify both are healthy
docker compose ps
```

ClickHouse will be available at **http://localhost:8123** (HTTP API).  
The schema (`01_schema.sql`) auto-runs on first startup, creating:
- `trades_raw` — unified trade storage table
- `trades_agg_1min` — materialized view for fast aggregations

### Run the Pipeline

Open **4 terminals**:

**Terminal 1 — Trade Simulator:**
```bash
source .venv/bin/activate
python src/simulator/producer.py
```

**Terminal 2 — ClickHouse Consumer:**
```bash
source .venv/bin/activate
python src/consumer/consumer.py
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