-- ─────────────────────────────────────────────────────────────────────────────
-- Phase 14: Risk Engine Tables
-- Run in Supabase SQL Editor after phase13_hybrid_search.sql
-- ─────────────────────────────────────────────────────────────────────────────

-- 1. Risk Events audit log
--    Stores all regime changes, gap aborts, chandelier exit signals,
--    and position sizing calculations for review.
CREATE TABLE IF NOT EXISTS risk_events (
    id             UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type     TEXT         NOT NULL,     -- 'REGIME_CHECK' | 'GAP_ABORT' | 'CHANDELIER_EXIT' | 'POSITION_SIZE'
    symbol         TEXT,                      -- NULL for market-level events
    regime         TEXT,                      -- 'RISK_ON' | 'RISK_OFF' | NULL
    trigger_reason TEXT,
    value          NUMERIC,                   -- e.g. gap %, stop level, chandelier stop price
    metadata       JSONB        DEFAULT '{}',
    created_at     TIMESTAMPTZ  DEFAULT now()
);

-- Index: quickly retrieve latest regime check
CREATE INDEX IF NOT EXISTS idx_risk_events_type_date
    ON risk_events (event_type, created_at DESC);

-- Index: per-symbol exit signals
CREATE INDEX IF NOT EXISTS idx_risk_events_symbol
    ON risk_events (symbol, created_at DESC)
    WHERE symbol IS NOT NULL;

-- 2. Add Chandelier stop column to trade_journal (computed nightly, stored for UI display)
ALTER TABLE trade_journal
    ADD COLUMN IF NOT EXISTS chandelier_stop    NUMERIC,
    ADD COLUMN IF NOT EXISTS atr14              NUMERIC,
    ADD COLUMN IF NOT EXISTS days_in_trade      INTEGER,
    ADD COLUMN IF NOT EXISTS exit_action        TEXT;    -- 'HOLD' | 'EXIT_SIGNAL'

-- 3. Helper view: open positions with their latest risk metrics
CREATE OR REPLACE VIEW open_positions_risk AS
    SELECT
        tj.id,
        tj.symbol,
        tj.entry_date,
        tj.entry_price,
        tj.stop_loss          AS static_stop,
        tj.chandelier_stop    AS dynamic_stop,
        tj.atr14,
        tj.exit_action,
        tj.quantity,
        tj.conviction_score,
        tj.catalyst,
        tj.target_price,
        -- Latest close from bhavcopy
        (
            SELECT bc.close
            FROM daily_bhavcopy bc
            WHERE bc.symbol = tj.symbol
            ORDER BY bc.trade_date DESC
            LIMIT 1
        ) AS current_price,
        -- Unrealised P&L
        (
            (SELECT bc.close FROM daily_bhavcopy bc WHERE bc.symbol = tj.symbol ORDER BY bc.trade_date DESC LIMIT 1)
            - tj.entry_price
        ) * tj.quantity AS unrealised_pnl_inr,
        tj.updated_at
    FROM trade_journal tj
    WHERE tj.exit_date IS NULL
    ORDER BY tj.entry_date DESC;

-- 4. Stored procedure to update Chandelier stops in bulk
--    Called nightly from /api/jobs/nightly endpoint.
CREATE OR REPLACE FUNCTION get_latest_regime()
RETURNS TABLE (
    regime         TEXT,
    trigger_reason TEXT,
    created_at     TIMESTAMPTZ
)
LANGUAGE sql STABLE AS $$
    SELECT regime, trigger_reason, created_at
    FROM risk_events
    WHERE event_type = 'REGIME_CHECK'
    ORDER BY created_at DESC
    LIMIT 1;
$$;

-- Verify
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN ('risk_events', 'trade_journal');
