---
title: Echo
emoji: 📈
colorFrom: purple
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# Echo: Multi-Agent Investment Committee & Screener for Indian Equities

Echo is an institutional-grade, automated stock screening and real-time risk visualization platform designed specifically for the Indian Equity Markets (BSE/NSE). 

Echo merges **Warren Buffett / Benjamin Graham Value & Moat Quality** fundamentals with **Stan Weinstein / William O'Neil Breakout Momentum** and **Wyckoff / Smart Money Concepts (SMC)** structural price sweeps. Orchestrated with **LangGraph**, it runs a background crawler that caches candidate states in a Redis Digital Twin, serving a high-fidelity Bloomberg-style dashboard with beginner-friendly tooltips and entry timing assessments.

---

## 1. System Architecture

```mermaid
graph TD
    A[Background Crawler Daemon] -->|Scrapes Daily at 7:00 PM IST| B[(Redis Digital Twin)]
    C[React Dashboard Visualizer] <-->|Rest APIs & SSE Transitions| D[FastAPI Gateway]
    D <-->|Read Cache & Logs| B
    D -->|Autoregressive Monte Carlo| E[Kronos Simulation Service]
    D <-->|Thematic Catalyst Engine| H[Local JSON Knowledge Graph]
    
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
        N --> O[7. simulated Paper Order]
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

### B. Thematic Catalyst & Supply Chain Arbitrage Engine (`thematic_engine.py`)
This module automates the process of mapping top-down policy catalysts (e.g. government defense allocations) to listed Indian monopolies/duopolies that supply the raw materials.

1. **Catalyst Ingestion (NLP)**: Ingests unstructured budget speeches or announcements. The local Gemma model acts as an entity extractor, returning a structured JSON containing the sector theme (`DEFENSE`, `RAILWAYS`, `RENEWABLE_ENERGY`, `SEMICONDUCTORS`, `OTHER`), key products, and the budget size.
2. **Dynamic Knowledge Graph Mapping**: Decoupled from Python code into a local JSON database file (`backend/data_store/thematic_knowledge_graph.json`). It maps themes to supplier tickers (e.g., Solar Industries for rocket propellants, MIDHANI for armor alloys). It dynamically loads on startup and creates a default template file if missing.
3. **Smart Money Verification (OBV)**: Calculates On-Balance Volume (OBV) and its 20-day EMA (`obv_ema20`) to verify institutional accumulation.
   $$\text{OBV}_t = \text{OBV}_{t-1} + \text{Volume}_t \quad (\text{if } \text{Close}_t > \text{Close}_{t-1})$$
   $$\text{OBV}_t = \text{OBV}_{t-1} - \text{Volume}_t \quad (\text{if } \text{Close}_t < \text{Close}_{t-1})$$
   *Accumulation* is flagged if OBV is higher than its 20-day EMA and is rising over a rolling 10-day period.
4. **Catalyst Exhaustion Filter (Risk)**: Checks if the supplier's price has already rallied $\ge 50\%$ in the last 90 trading days. If it has, the engine flags it as **"Do Not Buy - Catalyst Exhausted"** to prevent buying at distribution tops where insiders dump shares post-announcement.
5. **Contract Impact Ratio**: Calculates the ratio of the budget size to the supplier's market cap:
   $$\text{Impact \%} = \left(\frac{\text{Budget in Crores}}{\text{Market Cap in Crores}}\right) \times 100$$
   A higher ratio indicates that the catalyst represents a material percentage of the company's total value, raising conviction.

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
