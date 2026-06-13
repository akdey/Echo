---
title: Echo
emoji: 📈
colorFrom: purple
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# Echo — Retail Equity Intelligence Platform (Indian Markets)

Echo is a **100% free-tier, zero-cost** autonomous stock intelligence system built
for the Indian cash equity market (NSE/BSE).  It is designed specifically for
**retail swing traders and long-term investors** — not HFT, not F&O.

The philosophy: retail investors cannot beat institutions on *speed*, but they can
beat them on *patience* and *structural analysis*.  Echo handles the data pipeline
so you can focus on the trade decision.

---

## Architecture Overview

```
NSE Archives ──→ Bhavcopy Ingest ──→ Database (Postgres + pgvector)
                                          │
                       ┌──────────────────┼──────────────────────┐
                       ↓                  ↓                       ↓
              Conviction Engine   Insider Crawler     Sector Momentum
              (0-100 Score)       (SASTI CSV)         (RS vs Nifty 50)
                       │                  │                       │
                       └──────────────────┴───────────────────────┘
                                          │
                                   FastAPI Gateway
                                    (Port 8000)
                                          │
                             ┌────────────┴────────────┐
                             ↓                          ↓
                    React Dashboard              Alert Dispatcher
                  (Vite + Recharts)          (Telegram / Email SMTP)
```

**Infrastructure cost: ₹0**
- **Database**: Database tier (Neon/Postgres + pgvector)
- **Backend**: FastAPI + `uv` (deployable to Hugging Face Spaces free tier)
- **Frontend**: Vite React (deployable to Vercel free tier)
- **LLM**: Local Gemma-4 GGUF via `llama-cpp-python` + Pydantic schema enforcement
- **HTTP Scraping**: `curl-cffi` Chrome TLS impersonation (replaces Playwright — saves ~400 MB RAM)
- **Data**: NSE open archives, NSE internal JSON APIs (no paid API key required)

---

## Feature Index

### 1. Conviction Matrix Engine (`conviction_engine.py`)

Calculates a **0–100 Conviction Score** for every Nifty 500 stock daily.
Scores are cached in the `conviction_matrix` Database table and served via the
REST API in milliseconds.  Replaces black-box "Buy/Sell" signals with a
transparent, explainable confluence model.

| Layer | Max Points | Signal |
|---|---|---|
| **Technicals** | +30 | Weinstein Stage 1/2 base breakout on daily chart |
| **Smart Money** | +30 | NSE Bhavcopy delivery % ≥ 2× 20-day average AND ≥ 45% |
| **Thematic** | +20 | pgvector cosine similarity ≥ 0.35 to any active macro theme |
| **Fundamentals** | +20 | Positive Operating Cash Flow AND ROCE proxy > 15% |
| **Trap Penalty** | −50 | ASM/GSM list + 60% 90-day run-up + 3 consecutive upper circuits |

**Verdicts**:
- Score ≥ 75: `HIGH CONVICTION BUY` + stop-loss level + catalyst tags
- Score 50–74: `WATCHLIST`
- Trap detected: `DO NOT BUY — Trap Detected (reason)`
- Score < 50: `PASS`

**API**:
```
POST /api/conviction/run          — triggers full scoring run
GET  /api/conviction?min_score=75 — returns cached leaderboard
```

---

### 2. NSE Insider / Promoter Disclosure Tracker (`InsiderDisclosureCrawler`)

Crawls NSE's official **SASTI** (Securities and Exchange Board of India Insider
Trading) archive daily.  Source: `archives.nseindia.com/corporate/sasti/`.

- **Zero manual input**: Automatically scans backward up to 7 calendar days to
  find the latest available CSV (handles weekends and holidays).
- **Normalises inconsistent NSE headers**: The SASTI format changes occasionally.
  A `_COL_ALIASES` dictionary maps all known column name variants to canonical
  field names.
- **Idempotent ingest**: The `insider_disclosures` Database table has a
  `UNIQUE(symbol, acquirer_name, trade_date, quantity, transaction_type)` constraint
  so repeated crawl runs never create duplicates.
- **Tracks**: Promoter category (Promoter / Director / KMP / Relative), transaction
  type (Buy / Sell), quantity, value (INR), mode of acquisition (Open Market /
  ESOP / Gift / Off-Market), trade date vs. disclosure date.

**API**:
```
POST /api/insiders/crawl            — triggers fresh crawl
GET  /api/insiders                  — all recent disclosures (newest first)
GET  /api/insiders?symbol=TCS.NS    — filtered by ticker
```

**Why it matters**: Promoter buying in the open market at current prices is one
of the strongest qualitative buy signals.  Promoter selling is a structural
red flag.

---

### 3. Sector Rotation Heatmap (`sector_momentum_service.py`)

Computes **Relative Strength (RS)** of each Nifty sectoral index vs. the
benchmark Nifty 50 and classifies every sector into one of four quadrants:

| Quadrant | RS Score | 4W RS Direction | Meaning |
|---|---|---|---|
| **LEAD** | > 1.0 | Improving | Outperforming and accelerating |
| **WEAKEN** | > 1.0 | Declining | Was leading, now losing steam |
| **IMPROVE** | ≤ 1.0 | Improving | Recovering, money flowing in |
| **LAG** | ≤ 1.0 | Declining | Underperforming — avoid |

Covers 13 sectoral indices: IT, Bank, Auto, Metal, Pharma, FMCG, Energy,
Realty, Infra, Media, PSU Bank, Consumption, Healthcare.

Data source: yfinance (free, daily, no API key required).
Results are upserted to the `sector_momentum` Database table.

**API**:
```
POST /api/sectors/refresh   — fetch fresh data from yfinance + upsert
GET  /api/sectors           — cached heatmap sorted by regime
```

---

### 4. Alert Dispatcher (`alert_dispatcher.py`)

Sends asynchronous **Telegram and/or email alerts** whenever a stock's nightly
conviction score crosses the threshold (default: 75/100).

**Telegram** (free):
- Requires `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` env vars.
- Uses the Telegram Bot API (`api.telegram.org/bot.../sendMessage`).
- Sends a Markdown-formatted watchlist with symbol, score, catalyst tags,
  and suggested stop-loss.

**Email** (SMTP):
- Requires `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `ALERT_EMAIL_TO`.
- Works with any SMTP provider (Gmail, Brevo, Zoho — all have free tiers).
- Sends a styled HTML email table with one row per high-conviction stock.

**Guardrail**: Stocks with a `DO NOT BUY` verdict (traps) are excluded from
alert dispatch even if their raw score crosses the threshold.

Environment variable `CONVICTION_ALERT_THRESHOLD` controls the cutoff (default: 75).

---

### 5. EOD Bhavcopy Ingest (`data_fetcher.py`)

Downloads NSE's official **end-of-day deliverable positions report**
(`sec_bhavdata_full_DDMMYYYY.csv`) from the open NSE archives daily.

- **Delivery volume**: The actual shares that changed hands and were taken into
  demat (not intraday squares).  High delivery = long-term investors buying.
- **Circuit detection**: Flags upper/lower circuit hits using EOD price vs.
  `PREV_CLOSE` comparison (`pct_change ≥ 1.95%` with `close == high`).
- **250-day sliding window pruning**: After each ingest, dates beyond 250 trading
  sessions are deleted from `daily_bhavcopy` to stay within Database free-tier
  storage limits.
- **Lazy metadata loading**: For each new symbol not in the `companies` table,
  yfinance `.info` is called once to pull the business summary and generate a
  384-dimensional `sentence-transformers` embedding for pgvector search.

---

### 6. pgvector Semantic Search (`thematic_engine.py`)

When a catalyst text is entered (e.g. "Government allocates ₹75,000 Cr to solar
manufacturing"), the engine:

1. **Categorises** the catalyst using local Gemma-4 → theme + product list
2. **Vectorises** the search query via `all-MiniLM-L6-v2` (local, no API cost)
3. **Queries Database** via `match_companies` RPC (cosine similarity in pgvector)
4. **Loads Bhavcopy history** from Database for each matched company
5. **Applies retail guardrails** (liquidity gate, operator trap, exhaustion filter)
6. **Returns a ranked shortlist** sorted by actionability

The `match_companies` RPC must be created in your Database SQL Editor:
```sql
CREATE OR REPLACE FUNCTION match_companies (
  query_embedding vector(384),
  match_threshold float,
  match_count int
)
RETURNS TABLE (
  symbol text, name text, description text, similarity float
)
LANGUAGE sql STABLE AS $$
  SELECT symbol, name, description,
         1 - (description_embedding <=> query_embedding) AS similarity
  FROM companies
  WHERE 1 - (description_embedding <=> query_embedding) > match_threshold
  ORDER BY similarity DESC
  LIMIT match_count;
$$;
```

---

### 7. Private Trade Journal (`trade_journal` table)

A structured, personal trade ledger stored in Database.  Forces discipline:
**you cannot log a trade without specifying a stop-loss**.

**Fields**: symbol, entry date, entry price, quantity, conviction score (at time
of entry), catalyst notes, stop-loss, optional target price, exit date, exit
price, auto-computed P&L, and post-trade outcome review notes.

**API**:
```
GET    /api/journal                     — all entries (newest first)
GET    /api/journal?symbol=TATAMOTORS.NS — filtered by ticker
POST   /api/journal                     — log new trade entry
PATCH  /api/journal/exit                — record exit + auto-compute P&L
DELETE /api/journal/{trade_id}          — delete an entry (UUID)
```

The API validates that `stop_loss < entry_price` before writing.  P&L is
calculated server-side as `(exit_price − entry_price) × quantity`.

---

### 8. Nightly Full-Stack Pipeline (`POST /api/jobs/nightly`)

A single endpoint that chains the full data pipeline in the correct order:

```
1. Bhavcopy ingest        → daily_bhavcopy table
2. Insider crawl          → insider_disclosures table
3. Sector RS refresh      → sector_momentum table
4. Conviction scoring     → conviction_matrix table + alerts dispatched
```

Designed to be triggered at 8:30 PM IST on market days by a free
[cron-job.org](https://cron-job.org) webhook or a Hugging Face Spaces cron.

---

### 9. LangGraph Investment Committee (`agents/`)

A multi-agent state graph orchestrated with LangGraph, running 7 sequential
decision nodes:

| Node | Function |
|---|---|
| Discovery | Fetches candles, caches to Redis |
| Technical & SMC | Weinstein stage, FVGs, liquidity sweeps |
| Fundamental Audit | Buffett scorecard, DCF intrinsic value, moat rating |
| News & Sentiment | FinBERT sentiment on RSS news feed |
| Kronos Simulation | Monte Carlo price simulation |
| Risk Arbiter | Final risk/reward gating |
| Paper Order | Logs simulated trade outcome |

Streamed in real-time via Server-Sent Events (SSE) to the React dashboard
(`GET /api/stream_pipeline`).

---

### 10. Retail Safety Guardrails (Applied in Screener + Conviction Engine)

| Guard | Trigger | Action |
|---|---|---|
| **Illiquid Stock** | 20-day avg daily turnover < ₹5 Cr | `is_blocked = True` |
| **Operator Pump** | 3 consecutive upper circuits + negative CFO | `is_blocked = True` |
| **ASM/GSM List** | Playwright-scraped from NSE surveillance page | `-30 trap penalty` |
| **Catalyst Exhaustion** | ≥ 60% run-up in last 90 trading days | `-20 trap penalty` |

---

### 11. Technical Models (`trend_models.py`)

- **Weinstein Stage Analysis**: Stage 1 (base), Stage 2 (markup), Stage 3
  (distribution), Stage 4 (markdown) using 150-day SMA slope and price position.
- **OBV (On-Balance Volume)**: Cumulative volume confirming price direction.
  Accumulation = OBV > OBV-EMA20 and rising over 10 days.
- **Fair Value Gaps (FVGs)**: Imbalance zones from displacement candles.
- **Liquidity Sweeps (SMC)**: Institutional stop-hunt patterns at swing highs/lows.
- **CANSLIM Score**: Composite growth + momentum scoring.

---

### 12. Compliance & Regulatory Controls (`surveillance_compliance.py`)

- **Leaky-Bucket Rate Limiter**: ≤ 9 orders/second to stay under SEBI HFT threshold.
- **Market Price Protection**: Rewrites market orders as limit orders at
  `LTP × 1.015` (buy) / `LTP × 0.985` (sell), rounded to ₹0.05 tick size.
- **Dynamic Watchlist Sync**: ASM, GSM, T2T lists scraped live from NSE via
  Playwright and synced to the `surveillance` Database table each morning.

---

### 13. Risk Engine & Position Sizing (`risk_engine.py`)

Provides capital preservation rules and trailing stops to protect retail traders from market panics, flash crashes, and oversized losses.

- **Macro Regime Filter**: Gates buy signals. If Nifty 50 closes below 20-day EMA, or Nifty Midcap 150 closes below 50-day EMA, or FII flows are heavily negative (<-60,000 Cr over 5 days), the regime shifts to `RISK_OFF`, suppressing all buy signals.
- **Pre-Market Gap Check (9:15:05 AM IST)**: Automatically runs before market orders. Checks for abnormal gap-ups (>3%, abort buy) and gap-downs (>2%, caution).
- **Chandelier Exit trailing stop**: Trailing stop calculated as `Highest Close Since Entry - 3 * ATR14`.
- **Half-Kelly Position Sizer**: Utilizes historical trade win-rates and average R:R ratios to suggest the mathematically optimal capital allocation.

**API**:
```
GET  /api/risk/regime      — returns macro regime state (RISK_ON / RISK_OFF)
GET  /api/risk/premarket   — batch checks all open positions for opening gaps
GET  /api/risk/exits       — calculates Chandelier stop and checks for exit triggers
POST /api/risk/position-size — returns Kelly allocation percentage and INR value
GET  /api/risk/portfolio   — returns combined results for the risk dashboard
```

---

### 14. Three-Tier News Ingestion Engine (`news_engine.py`)

Bypasses cloud scraping limits and anti-bot systems by using target queries and direct regulatory exchange feeds.

- **Tier 1 (Global Macro)**: Runs 7 targeted DuckDuckGo News queries at 8:30 AM IST (FED, RBI, oil, FII flow, etc.). LLM evaluates sector-level boosts or vetoes (-20 to +20).
- **Tier 2 (Corporate Announcements)**: Fetches the 50 most recent regulatory filings from the NSE corporate announcements API. Triages announcements and triggers temporary conviction overrides (+30 to -30) that expire automatically in 3 trading days.
- **Tier 3 (Watchlist-Targeted Search)**: Dynamic weekly news query per watchlist/holding symbol (capped to 15 to stay under rate limits). LLM extracts net sentiment and adjusts conviction (-15 to +15).

**API**:
```
POST /api/news/pipeline       — runs Tier 1, 2, and 3 news ingestion in sequence
POST /api/news/crawl/{tier}   — triggers a crawl for a specific news tier
GET  /api/news/signals        — returns processed news signals from news_signals table
GET  /api/news/overrides      — returns active overrides from conviction_overrides table
GET  /api/news/catalysts      — returns material corporate catalysts from today
```

---

## Database Schema

Run the migration scripts in `backend/database_migrations/` in your Database SQL Editor to create all tables.

| Table | Purpose |
|---|---|
| `companies` | Symbol metadata + pgvector embeddings |
| `daily_bhavcopy` | EOD price + delivery volume (250-day window) |
| `surveillance` | Live ASM/GSM/T2T watchlist |
| `insider_disclosures` | NSE SASTI promoter/director buy/sell filings |
| `sector_momentum` | Nifty sectoral RS scores + regime classification |
| `trade_journal` | Private trade entries with P&L tracking |
| `conviction_matrix` | Daily 0-100 conviction scores (cached) |
| `news_signals` | Processed news items across all three tiers |
| `conviction_overrides` | Temporary conviction score adjustments with auto-expiry |

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | ✅ | SQLAlchemy database URL (Neon, local SQLite, Postgres) |

| `TELEGRAM_BOT_TOKEN` | Optional | Telegram bot for alerts |
| `TELEGRAM_CHAT_ID` | Optional | Target chat/channel ID |
| `SMTP_HOST` | Optional | SMTP server (default `smtp.gmail.com`) |
| `SMTP_PORT` | Optional | SMTP port (default `587`) |
| `SMTP_USER` | Optional | SMTP login email |
| `SMTP_PASS` | Optional | SMTP password / app password |
| `ALERT_EMAIL_TO` | Optional | Alert recipient email |
| `CONVICTION_ALERT_THRESHOLD` | Optional | Score cutoff for alerts (default `75`) |
| `SCREENER_TICKER_LIMIT` | Optional | Limit tickers in dev mode (e.g. `20`) |

---

## Quick Start (Development)

```bash
# Install dependencies
cd backend && uv sync

# Set environment variables
export DATABASE_URL="postgresql://user:password@host/dbname?sslmode=require"

# Run migrations — paste phase12_conviction_schema.sql into Database SQL Editor

# Start API server
uv run uvicorn backend.main:app --reload --port 8000

# Start React dashboard
cd frontend && npm install && npm run dev
```

---

## Deployment (Hugging Face Spaces — Free Tier)

1. Push to your Hugging Face Space repository.
2. Set `DATABASE_URL` as a Space Secret.
3. Set up a free [cron-job.org](https://cron-job.org) webhook to call
   `POST https://your-space.hf.space/api/jobs/nightly` at 8:30 PM IST on weekdays.
4. Set Telegram vars for alerts if desired.

**Disclaimer**: This is a personal research tool. It is not financial advice.
Always validate all signals with your own analysis before committing capital.


Echo is an institutional-grade, automated stock screening and real-time risk visualization platform designed specifically for the Indian Equity Markets (BSE/NSE). 

Echo merges **Warren Buffett / Benjamin Graham Value & Moat Quality** fundamentals with **Stan Weinstein / William O'Neil Breakout Momentum** and **Wyckoff / Smart Money Concepts (SMC)** structural price sweeps. Orchestrated with **LangGraph**, it runs a background crawler that caches candidate states in a Redis Digital Twin, serving a high-fidelity Bloomberg-style dashboard with beginner-friendly tooltips and entry timing assessments.

---

## 1. System Architecture

```mermaid
graph TD
    A[Background Scrapers] -->|Daily EOD Bhavcopy & Insider SASTI| D[FastAPI Gateway]
    C[React Dashboard Visualizer] <-->|Rest APIs & SSE Transitions| D
    D <-->|Read/Write Cache| B[(Redis Digital Twin)]
    D -->|Autoregressive Monte Carlo| E[Kronos Simulation Service]
    D <-->|Thematic description & vectors| H[(Database pgvector PostgreSQL)]
    
    subgraph Local LLM Gateway
        D -->|ThreadPoolExecutor| F[llama-cpp-python]
        F -->|Local GGUF Weights| G[Gemma-4 E4B Instruct]
    end
    
    subgraph LangGraph Decision Committee
        D --> I[1. Discovery Node]
        I --> J[2. Technical & SMC Node]
        J --> K[3. Fundamental Audit Node]
        K -->|Surveillance Router| L[4. News & Sentiment Node]
        L -->|Circuit Breaker Router| M[5. Kronos Simulation Gate]
        M -->|Regime Router| N[6. Risk Arbiter Node]
        N --> O[7. Simulated Paper Order]
    end
```

---

## 2. Exhaustive Feature Index & Implementation Details

### A. Local Gemma-4 GGUF Gateway (`llm_gateway.py`)
To ensure total data privacy, avoid external API token costs, and maintain zero cold-start latency on Hugging Face Spaces, Echo runs LLM queries entirely locally.
* **Model Loader**: Implements a `LocalLLMEngine` class that lazy-loads `google_gemma-4-E4B-it-Q4_K_M.gguf` (Instruct model) via `llama-cpp-python`.
* **Non-Blocking Inference**: Runs the CPU inference inside a Python `ThreadPoolExecutor` (via `asyncio.get_event_loop().run_in_executor`). This ensures that during heavy inference cycles, the FastAPI async event loop is never blocked and remains fully responsive.
* **Gemma Turn Formatting**: Wraps prompts in the standard Gemma turn tokens:
  ```
  <|turn>system
  {system_instruction} <turn|>
  <|turn>user
  {prompt} <turn|>
  <|turn>model
  ```
* **Thought Stripping**: Uses regex parsing (`re.sub(r'<\|channel>thought.*?<channel\|>', '', text, flags=re.DOTALL)`) to strip Gemma's internal thinking blocks from the output, returning only the parsed result.

---

### B. Persistent & Self-Updating Thematic Engine (pgvector RAG & EOD Bhavcopy)
This module automates the process of mapping top-down policy catalysts (e.g. government budget allocations) to listed Indian suppliers, tracking institutional delivery accumulation, and enforcing retail protection guardrails.

1. **Postgres Database Backend (Neon / Database)**:
   - Replaces the SQLite Graph Store and local yfinance caches with a PostgreSQL database hosted on Database's free tier.
   - **Schema**:
     - `companies`: Holds stock symbols, names, industry, and description.
       - `symbol` TEXT PRIMARY KEY (e.g. `"BEL.NS"`)
       - `name` TEXT NOT NULL
       - `description` TEXT (Business summary, product lines, and raw materials)
       - `description_embedding` vector(384) (Local sentence-transformers embedding)
     - `daily_bhavcopy`: Holds EOD statistics.
       - `trade_date` DATE, `open` NUMERIC, `high` NUMERIC, `low` NUMERIC, `close` NUMERIC, `prev_close` NUMERIC
       - `volume` BIGINT (Traded quantity), `delivery_volume` BIGINT (Deliverable quantity)
       - `delivery_pct` NUMERIC (Delivery volume %), `turnover_cr` NUMERIC (Traded value in Crores)
       - `is_circuit_hit`, `is_upper_circuit`, `is_lower_circuit` BOOLEAN

2. **pgvector Cosine Similarity Match (RAG)**:
   - When a catalyst text is inputted, the system uses a local `all-MiniLM-L6-v2` embedding model to generate a 384-dimensional query vector.
   - Executes a remote procedure call (RPC) `match_companies` in PostgreSQL to calculate cosine similarity matches:
     $$\text{Similarity} = 1 - (\text{description\_embedding} \cdot \text{query\_embedding})$$
   - Instantly retrieves relevant suppliers, bypassing hardcoded graph mappings and resolving supply-chain candidates dynamically.

3. **Daily Bhavcopy Ingestion (The Retail Edge)**:
   - Downloads the official EOD deliverable positions report (`sec_bhavdata_full_ddmmyyyy.csv`) from NSE archives.
   - Synchronizes prices, volume, and deliverable shares to Database.
   - Enforces a **250-day sliding window database retention policy** to prune older rows and remain safely within Database's free-tier storage limits (500MB).

4. **Institutional Accumulation Indicator**:
   - Calculates the 20-day average delivery volume percentage. If the latest EOD delivery percentage is $\ge 45\%$ and represents a $\ge 1.3\text{x}$ spike above its 20-day average, the stock is marked as under active **"Institutional Buying (High Delivery)"**.

5. **Retail safety Guardrails**:
   - **Operator Trap Filter**: Flags a stock with an `Operator Pump Warning` if it hits upper price circuits for 3 consecutive days while operating cash flow (CFO) is negative.
   - **Liquidity Check**: Filters out any stock where the 20-day average daily turnover is less than ₹5 Crores.
   - **ASM/GSM Surveillance Blocks**: Syncs Playwright-scraped watchlists to Database and automatically grays out or blocks trades on Stage 4 GSM/ASM symbols.

6. **Data Anomaly Sanity Filters**:
   - **Zero/Negative Price Filter**: Filters out and ignores daily close prices $\le 0$.
   - **Volume Anomaly Check**: Logs warning logs if daily volume is 0, preventing division-by-zero errors.
   - **Outlier Price check**: If day-on-day price shift exceeds $>100\%$, logs a data corruption warning.

7. **Smart Money Verification (OBV)**:
   - Calculates On-Balance Volume (OBV) and its 20-day EMA (`obv_ema20`):
     $$\text{OBV}_t = \text{OBV}_{t-1} + \text{Volume}_t \times \text{sign}(\text{Close}_t - \text{Close}_{t-1})$$
   - Accumulation is verified only if $\text{OBV} > \text{OBV\_EMA20}$ and is rising over a rolling 10-day window.

8. **Catalyst Exhaustion Filter (Risk)**:
   - Checks if the stock has rallied $\ge 50\%$ in the last 90 trading days. If it has, the engine flags it as **"Do Not Buy - Catalyst Exhausted"** to prevent retail entries at distribution tops.

9. **Thematic REST Management APIs**:
   - `GET /api/thematic/graph`: Retrieves all registered company profiles.
   - `POST /api/thematic/node`: Adds/updates a company profile (auto-vectorizing description).
   - `DELETE /api/thematic/node/{node_id}`: Deletes a company profile.
   - `POST /api/thematic/edge` / `DELETE /api/thematic/edge/{edge_id}`: Deprecated (returns status warning).
   - `POST /api/thematic/crawl`: Manually triggers the daily NSE Bhavcopy crawl and Database ingest.

---

### C. Playwright Compliance & Flows Crawler (`screener_daemon.py`)
* **SEBI Surveillance Watchlists**: To prevent trapping capital in illiquid segments, the crawler uses Playwright to launch a headless Chromium instance, navigate to the official NSE Reports page (`https://www.nseindia.com/reports/adr-res-surveillance-measure`), and parse dynamic tables. Tickers are automatically scraped and loaded into the compliance gatekeeper under **ASM** (Additional Surveillance Measure), **GSM** (Graded Surveillance Measure), and **T2T** (Trade-to-Trade) categories.
* **Institutional Flows Scraper**: Playwright sequentially scrapes FII/DII cash activity tables from three fallback sources: NiftyTrader, Moneycontrol, and StockEdge. It uses a semantic table parser to extract net daily values, converting formatting like negative wicks `(1,234.50)` into floats.

---

### D. SEBI 2026 Algorithmic Compliance Gates (`surveillance_compliance.py`)
Echo enforces strict regulatory guardrails:
* **Leaky-Bucket Rate Limiter**: Ensures order placement rate stays under 9 Orders Per Second (OPS) to prevent being classified as high-frequency trading (HFT).
* **Market Price Protection (MPP)**: Blocks naked market orders. They are rewritten as limit orders with a $\pm 1.5\%$ buffer offset (`LTP * 1.015` for buy, `LTP * 0.985` for sell), rounded to the standard tick size of 5 paise ($0.05$ Rs) in India, eliminating slippage risk.

---

### E. Technical & Structural Models (`trend_models.py`)
Calculates the momentum and market structure indicators:
* **Weinstein Stage Analysis**:
  * **Stage 1 (Accumulation)**: Price consolidates around a flat 150-day SMA.
  * **Stage 2 (Markup/Uptrend)**: Price breakout above a rising 150-day SMA on high volume.
  * **Stage 3 (Distribution)**: Price chops around a flattening 150-day SMA.
  * **Stage 4 (Markdown/Downtrend)**: Price falls below a declining 150-day SMA.
* **SMC Liquidity Sweeps**: Identifies candle wicks that pierce previous 5-candle swing highs/lows but close back inside the range, flagging institutional stop-loss hunts.
* **Fair Value Gaps (FVG)**: Imbalance zones created by displacement candles (`Low(t) > High(t-2)` for bullish or `High(t) < Low(t-2)` for bearish).

---

### F. Recharts Sizing Fix (`App.jsx`)
To resolve the Recharts SVG width/height console warnings in the React dashboard:
* Grids wrapping chart panels are styled with `min-h-0 min-w-0` to allow correct flexbox shrink calculations.
* ResponsiveContainer components are initialized with an explicit `minHeight={224}` prop so size calculations complete correctly on initial layout passes.

---

## 3. Build & Space Deployment Optimizations

* **Python 3.12 Environment**: Upgraded the Docker base image to `python:3.12-slim` and requirements to support modern, high-performance libraries.
* **Unsafe Best Match Wheel Resolution**: To avoid long compilation times during image builds, `pyproject.toml` is configured with `index-strategy = "unsafe-best-match"`, enabling `uv` to pull precompiled CPU wheels for `llama-cpp-python` from the community wheel index.
* **Docker Memory Limit Protection**: Set compilation flags in the Dockerfile (`CMAKE_BUILD_PARALLEL_LEVEL=1` and `CMAKE_ARGS="-DGGML_CPU=ON"`) to prevent the Hugging Face Spaces build server from running out of memory (Exit 137).
* **Pre-Baked Weights**: Downloads the 2.5GB Gemma-4 model GGUF file during the Docker image building phase. This guarantees that when the Hugging Face Space starts, the model is already present locally, ensuring instant cold-starts.
