-- ─────────────────────────────────────────────────────────────────────────────
-- Phase 13: Hybrid BM25 + pgvector Search
-- Run this in the Supabase SQL Editor ONCE after applying phase12_conviction_schema.sql
-- ─────────────────────────────────────────────────────────────────────────────

-- 1. GIN index for full-text search on companies table
--    This makes BM25 (ts_rank_cd) sub-millisecond even on 50k rows.
CREATE INDEX IF NOT EXISTS idx_companies_fts
    ON companies
    USING GIN (to_tsvector('english', coalesce(name, '') || ' ' || coalesce(description, '')));

-- 2. Hybrid search function (BM25 + pgvector cosine similarity)
--    semantic_weight + bm25_weight should sum to 1.0.
--    The default 70/30 split favours semantic meaning but ensures exact keywords
--    like "Titanium sponge" or "IGBT module" rank above generic sector matches.
CREATE OR REPLACE FUNCTION match_companies_hybrid(
    query_embedding  vector(384),
    query_text       text,
    match_threshold  float   DEFAULT 0.15,
    match_count      int     DEFAULT 10,
    semantic_weight  float   DEFAULT 0.7,
    bm25_weight      float   DEFAULT 0.3
)
RETURNS TABLE (
    symbol          text,
    name            text,
    description     text,
    semantic_score  float,
    bm25_score      float,
    combined_score  float
)
LANGUAGE sql STABLE AS $$
    WITH semantic AS (
        SELECT
            c.symbol,
            c.name,
            c.description,
            (1 - (c.description_embedding <=> query_embedding))::float AS semantic_score
        FROM companies c
        WHERE (1 - (c.description_embedding <=> query_embedding)) > match_threshold
    ),
    bm25 AS (
        SELECT
            c.symbol,
            ts_rank_cd(
                to_tsvector('english',
                    coalesce(c.name, '') || ' ' || coalesce(c.description, '')
                ),
                plainto_tsquery('english', query_text),
                32  -- normalise by document length
            )::float AS bm25_score
        FROM companies c
        -- Only score companies that appear in the semantic set or BM25 matches
        WHERE to_tsvector('english',
                coalesce(c.name, '') || ' ' || coalesce(c.description, '')
              ) @@ plainto_tsquery('english', query_text)
    )
    SELECT
        s.symbol,
        s.name,
        s.description,
        s.semantic_score,
        coalesce(b.bm25_score, 0.0) AS bm25_score,
        (
            (s.semantic_score * semantic_weight) +
            (coalesce(b.bm25_score, 0.0) * bm25_weight)
        ) AS combined_score
    FROM semantic s
    LEFT JOIN bm25 b ON s.symbol = b.symbol
    ORDER BY combined_score DESC
    LIMIT match_count;
$$;

-- 3. Also ensure the original pure-semantic function exists as a fallback.
--    thematic_engine.py falls back to this if the hybrid function call fails.
CREATE OR REPLACE FUNCTION match_companies(
    query_embedding  vector(384),
    match_threshold  float  DEFAULT 0.20,
    match_count      int    DEFAULT 10
)
RETURNS TABLE (
    symbol      text,
    name        text,
    description text,
    similarity  float
)
LANGUAGE sql STABLE AS $$
    SELECT
        c.symbol,
        c.name,
        c.description,
        (1 - (c.description_embedding <=> query_embedding))::float AS similarity
    FROM companies c
    WHERE (1 - (c.description_embedding <=> query_embedding)) > match_threshold
    ORDER BY similarity DESC
    LIMIT match_count;
$$;

-- 4. Add a GIN index on insider_disclosures for fast symbol + date lookups
CREATE INDEX IF NOT EXISTS idx_insider_symbol_date
    ON insider_disclosures (symbol, trade_date DESC);

-- 5. Add a partial index on conviction_matrix for high-conviction queries
CREATE INDEX IF NOT EXISTS idx_conviction_high_score
    ON conviction_matrix (conviction_score DESC)
    WHERE conviction_score >= 50;

-- Verify functions exist
SELECT
    routine_name,
    routine_type
FROM information_schema.routines
WHERE routine_schema = 'public'
  AND routine_name IN ('match_companies', 'match_companies_hybrid');
