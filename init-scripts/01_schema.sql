-- ============================================================
-- ClickHouse Schema for Real-Time FinTech Analytics
-- Unified table for both historical (Groww API) + live data
-- ============================================================

-- Raw trades table
CREATE TABLE IF NOT EXISTS trades_raw (
    trade_id        UUID,
    symbol          String,
    price           Float64,
    quantity        Float64,
    side            Enum8('buy' = 1, 'sell' = -1),
    region          LowCardinality(String),
    asset_class     LowCardinality(String),
    exchange        LowCardinality(String),
    timestamp       DateTime64(3, 'Asia/Kolkata'),
    ingested_at     DateTime DEFAULT now()
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(timestamp)
ORDER BY (symbol, toStartOfHour(timestamp), region)
TTL timestamp + INTERVAL 90 DAY DELETE;

-- 1-minute aggregated materialized view
CREATE MATERIALIZED VIEW IF NOT EXISTS trades_agg_1min
ENGINE = SummingMergeTree()
PARTITION BY toYYYYMM(minute)
ORDER BY (symbol, minute, region)
AS SELECT
    symbol,
    toStartOfMinute(timestamp) AS minute,
    region,
    exchange,
    count()                         AS trade_count,
    sum(price * quantity)           AS volume,
    min(price)                      AS price_min,
    max(price)                      AS price_max,
    max(price) - min(price)         AS price_range,
    avg(price)                      AS price_avg
FROM trades_raw
GROUP BY symbol, minute, region, exchange;