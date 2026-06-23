-- Groww tick data: one-minute candles per symbol
CREATE TABLE IF NOT EXISTS tick_data (
    symbol          String,
    exchange        String,
    timestamp       DateTime64(3, 'Asia/Kolkata'),
    open            Float64,
    high            Float64,
    low             Float64,
    close           Float64,
    volume          Float64
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(timestamp)
ORDER BY (symbol, timestamp);

-- Multi-day daily bars (US + NSE equities) for trend/regime/event context
CREATE TABLE IF NOT EXISTS daily_bars (
    symbol      String,
    exchange    String,
    date        Date,
    open        Float64,
    high        Float64,
    low         Float64,
    close       Float64,
    volume      Float64
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(date)
ORDER BY (symbol, date);

-- Macro / cross-asset daily series (indices, commodities, FX, rates, crypto, vol)
CREATE TABLE IF NOT EXISTS macro_bars (
    symbol      String,
    category    String,
    date        Date,
    open        Float64,
    high        Float64,
    low         Float64,
    close       Float64
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(date)
ORDER BY (symbol, date);

-- Materialized view: 5-min candles from 1-min data
CREATE MATERIALIZED VIEW IF NOT EXISTS tick_data_5min
ENGINE = MergeTree()
PARTITION BY toYYYYMM(window_start)
ORDER BY (symbol, window_start)
AS SELECT
    symbol,
    exchange,
    toStartOfFiveMinutes(timestamp) AS window_start,
    argMin(open, timestamp) AS open,
    max(high) AS high,
    min(low) AS low,
    argMax(close, timestamp) AS close,
    sum(volume) AS volume
FROM tick_data
GROUP BY symbol, exchange, window_start;