-- ============================================================
-- Echo Phase 12 — Conviction Matrix Schema Migration
-- Run this in the Supabase SQL Editor (Project > SQL Editor)
-- ============================================================

-- 1. NSE Insider & Promoter Disclosures Table
-- Stores every Buy/Sell filed by promoters/directors with NSE.
-- The UNIQUE constraint prevents duplicate ingest on re-runs.
CREATE TABLE IF NOT EXISTS insider_disclosures (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    symbol              TEXT NOT NULL REFERENCES companies(symbol) ON DELETE CASCADE,
    acquirer_name       TEXT NOT NULL,       -- Full name of promoter / director / KMP / relative
    category_of_person  TEXT,               -- "Promoter", "Director", "KMP", "Relative of Promoter"
    transaction_type    TEXT NOT NULL,       -- "Buy" or "Sell"
    quantity            BIGINT NOT NULL,     -- Number of shares transacted
    value_rs            NUMERIC,            -- Approximate consideration in INR
    mode_of_acquisition TEXT,              -- "Open Market", "Gift", "ESOP", "Off-Market"
    trade_date          DATE NOT NULL,       -- Date the transaction occurred
    disclosure_date     DATE NOT NULL,       -- Date the filing was made with NSE
    created_at          TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(symbol, acquirer_name, trade_date, quantity, transaction_type)
);

CREATE INDEX IF NOT EXISTS idx_insider_symbol
    ON insider_disclosures(symbol);
CREATE INDEX IF NOT EXISTS idx_insider_date
    ON insider_disclosures(trade_date DESC);


-- 2. Sectoral Index Momentum / Rotation Heatmap Table
-- Refreshed daily by the background cron; used by the React heatmap component.
CREATE TABLE IF NOT EXISTS sector_momentum (
    sector_name              TEXT PRIMARY KEY,    -- "NIFTY IT", "NIFTY AUTO", "NIFTY METAL", …
    index_symbol             TEXT,               -- yfinance symbol, e.g. "^CNXIT"
    current_price            NUMERIC NOT NULL,
    sma_50                   NUMERIC,
    sma_150                  NUMERIC,
    rs_score                 NUMERIC NOT NULL,   -- Sector close / Nifty 50 close (ratio)
    rs_change_4w             NUMERIC,            -- RS change over past 4 weeks (momentum direction)
    momentum_regime          TEXT NOT NULL,       -- "LEAD", "IMPROVE", "LAG", "WEAKEN"
    updated_at               TIMESTAMPTZ DEFAULT NOW()
);


-- 3. Private Trade Journal Table
-- Stores personal trade entries and post-mortem outcome notes.
CREATE TABLE IF NOT EXISTS trade_journal (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    symbol           TEXT NOT NULL REFERENCES companies(symbol) ON DELETE CASCADE,
    entry_date       DATE NOT NULL,
    entry_price      NUMERIC NOT NULL,
    quantity         INT NOT NULL,
    conviction_score INT NOT NULL CHECK (conviction_score BETWEEN 0 AND 100),
    catalyst         TEXT,                -- e.g. "Volume breakout + Solar policy"
    stop_loss        NUMERIC NOT NULL,   -- Mandatory: risk before entry
    target_price     NUMERIC,            -- Optional upside target
    exit_date        DATE,
    exit_price       NUMERIC,
    pnl              NUMERIC,            -- Computed on update: (exit-entry)*qty
    outcome_notes    TEXT,              -- Post-trade psychological review
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    updated_at       TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_journal_symbol
    ON trade_journal(symbol);
CREATE INDEX IF NOT EXISTS idx_journal_entry_date
    ON trade_journal(entry_date DESC);


-- 4. Conviction Matrix Cache Table
-- One row per symbol; upserted after each nightly scoring run.
-- conviction_score = technical + smart_money + thematic + fundamental + trap (can be negative)
CREATE TABLE IF NOT EXISTS conviction_matrix (
    symbol              TEXT PRIMARY KEY REFERENCES companies(symbol) ON DELETE CASCADE,
    conviction_score    INT NOT NULL CHECK (conviction_score BETWEEN 0 AND 100),
    technical_score     INT NOT NULL DEFAULT 0,    -- Max +30: Weinstein Stage 1/2 breakout
    smart_money_score   INT NOT NULL DEFAULT 0,    -- Max +30: Bhavcopy delivery spike
    thematic_score      INT NOT NULL DEFAULT 0,    -- Max +20: pgvector theme match
    fundamental_score   INT NOT NULL DEFAULT 0,    -- Max +20: positive CFO + ROCE > 15%
    trap_penalty        INT NOT NULL DEFAULT 0,    -- Up to -50: ASM/GSM, 60% run-up
    verdict             TEXT NOT NULL,             -- Readable actionable text
    stop_loss_level     NUMERIC,                   -- Suggested stop based on recent swing low
    catalyst_tags       TEXT[],                    -- e.g. ["Volume Breakout", "Solar Tailwind"]
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_conviction_score
    ON conviction_matrix(conviction_score DESC);
CREATE INDEX IF NOT EXISTS idx_conviction_updated
    ON conviction_matrix(updated_at DESC);
