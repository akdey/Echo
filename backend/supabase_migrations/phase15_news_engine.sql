-- ─────────────────────────────────────────────────────────────────────────────
-- Phase 15: Three-Tier News Engine Tables
-- Run in Supabase SQL Editor after phase14_risk_engine.sql
-- ─────────────────────────────────────────────────────────────────────────────

-- 1. news_signals — stores every processed news item from all three tiers
CREATE TABLE IF NOT EXISTS news_signals (
    id                     UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    tier                   INTEGER      NOT NULL,   -- 1 (macro), 2 (corporate), 3 (watchlist)
    query                  TEXT,                    -- search query or NSE symbol used
    source_title           TEXT,                    -- original headline from source
    source_url             TEXT,
    -- Tier 1 fields
    theme                  TEXT,                    -- FED_RATE | OIL_PRICE | RBI_POLICY | ...
    affected_sectors       TEXT[],                  -- e.g. {IT, BANKING}
    -- Tier 2 / 3 fields
    symbol                 TEXT,                    -- NSE ticker e.g. TCS.NS
    is_material_catalyst   BOOLEAN,
    event_type             TEXT,
    -- Common
    sentiment              TEXT,                    -- BULLISH | BEARISH | NEUTRAL
    conviction_adjustment  INTEGER      DEFAULT 0,  -- points: negative = veto, positive = boost
    raw_snippet            TEXT,
    llm_summary            TEXT,
    metadata               JSONB        DEFAULT '{}',
    processed_at           TIMESTAMPTZ  DEFAULT now()
);

-- Indexes for news_signals
CREATE INDEX IF NOT EXISTS idx_news_signals_tier_time
    ON news_signals (tier, processed_at DESC);

CREATE INDEX IF NOT EXISTS idx_news_signals_symbol
    ON news_signals (symbol, processed_at DESC)
    WHERE symbol IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_news_signals_material
    ON news_signals (tier, is_material_catalyst, processed_at DESC)
    WHERE is_material_catalyst = true;

-- 2. conviction_overrides — temporary score adjustments from news events
--    Overrides expire automatically (expires_at column checked at query time).
CREATE TABLE IF NOT EXISTS conviction_overrides (
    id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    symbol          TEXT         NOT NULL,          -- NSE ticker e.g. TCS.NS
    override_points INTEGER      NOT NULL,          -- -30 to +30
    reason          TEXT,
    source          TEXT,                           -- TIER1_MACRO | TIER2_CORPORATE | TIER3_WATCHLIST
    expires_at      TIMESTAMPTZ  NOT NULL,          -- auto-expire after 2-3 trading days
    created_at      TIMESTAMPTZ  DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_conviction_overrides_symbol
    ON conviction_overrides (symbol, expires_at DESC);

CREATE INDEX IF NOT EXISTS idx_conviction_overrides_active
    ON conviction_overrides (expires_at)
    WHERE expires_at > now();

-- 3. Helper function: get all active (non-expired) conviction overrides
--    Called by the FastAPI conviction endpoint to apply news adjustments.
CREATE OR REPLACE FUNCTION get_active_conviction_overrides()
RETURNS TABLE (
    symbol          TEXT,
    net_override    INTEGER,
    sources         TEXT[],
    latest_reason   TEXT
)
LANGUAGE sql STABLE AS $$
    SELECT
        symbol,
        SUM(override_points)::INTEGER AS net_override,
        ARRAY_AGG(DISTINCT source)    AS sources,
        MAX(reason)                   AS latest_reason
    FROM conviction_overrides
    WHERE expires_at > now()
    GROUP BY symbol
    HAVING SUM(override_points) != 0;
$$;

-- 4. Cleanup function: delete expired overrides (call weekly to keep table lean)
CREATE OR REPLACE FUNCTION cleanup_expired_overrides()
RETURNS INTEGER
LANGUAGE plpgsql AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM conviction_overrides WHERE expires_at < now();
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$;

-- 5. View: latest material catalysts (last 24 hours)
CREATE OR REPLACE VIEW material_catalysts_today AS
    SELECT
        symbol,
        event_type,
        sentiment,
        conviction_adjustment,
        llm_summary,
        processed_at
    FROM news_signals
    WHERE tier = 2
      AND is_material_catalyst = true
      AND processed_at > now() - INTERVAL '24 hours'
    ORDER BY ABS(conviction_adjustment) DESC, processed_at DESC;

-- 6. View: today's macro sector signals
CREATE OR REPLACE VIEW macro_sector_signals_today AS
    SELECT
        theme,
        UNNEST(affected_sectors) AS sector,
        sentiment,
        conviction_adjustment,
        llm_summary,
        processed_at
    FROM news_signals
    WHERE tier = 1
      AND processed_at > now() - INTERVAL '8 hours'
    ORDER BY ABS(conviction_adjustment) DESC;

-- Verify
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN ('news_signals', 'conviction_overrides');
