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

## 1. System Architecture & Flow

Echo utilizes a multi-layered, asynchronous intelligence pipeline:

```mermaid
graph TD
    A[Background Crawler Daemon] -->|Scrapes Daily at 7:00 PM IST| B[(Redis Digital Twin)]
    C[React Dashboard Visualizer] <-->|Rest APIs & SSE Transitions| D[FastAPI Gateway]
    D <-->|Read Cache & Logs| B
    D -->|Autoregressive Monte Carlo| E[Kronos Simulation Service]
    
    subgraph LangGraph Decision Committee
        D --> F[1. Discovery Node]
        F --> G[2. Technical & SMC Node]
        G --> H[3. Fundamental Audit Node]
        H -->|Surveillance Router| I[4. News & Sentiment Node]
        I -->|Circuit Breaker Router| J[5. Kronos Simulation Gate]
        J -->|Regime Router| K[6. Risk Arbiter Node]
        K --> L[7. simulated Paper Order]
    end
```

---

## 2. Exhaustive Indicator Index & Formulae

### A. Warren Buffett Moat & Quality Indicators
Echo implements fundamental screening metrics to verify the operational resilience and pricing power of compounders:
1. **ROCE (Return on Capital Employed)**:
   $$\text{ROCE} = \frac{\text{EBIT}}{\text{Total Assets} - \text{Current Liabilities}}$$
   *Standard:* $\ge 15\%$ average over 3 years. Verifies high pricing power (Moat).
2. **ROE (Return on Equity)**:
   $$\text{ROE} = \frac{\text{Net Income}}{\text{Shareholders' Equity}}$$
   *Standard:* $\ge 15\%$. Evaluates efficiency in compounding shareholder capital.
3. **Cash Flow Integrity Ratio**:
   $$\text{Integrity} = \frac{\text{Cash Flow from Operations (CFO)}}{\text{Net Income}}$$
   *Standard:* $\ge 1.0$. Confirms that reported net profit is fully backed by operating cash, detecting accounting manipulation.
4. **Debt-to-Equity (D/E)**:
   $$\text{D/E} = \frac{\text{Total Liabilities}}{\text{Shareholders' Equity}}$$
   *Standard:* $<0.5$ (excluding banks and NBFCs) to protect capital during high-interest repo rate cycles.
5. **Operating Margin Stability (Moat Rating)**:
   Calculates the standard deviation of EBITDA margins over a 5-year period. A low standard deviation indicates a stable business moat with predictable pricing power.

### B. Benjamin Graham Valuation & Margin of Safety
Calculates the asset's intrinsic value using Benjamin Graham's revised formulation:
$$V^* = \frac{\text{EPS} \times (8.5 + 2g) \times 4.4}{Y}$$
*   **EPS**: Trailing Twelve Months (TTM) Earnings Per Share.
*   **g**: Expected earnings growth rate over 5 years.
*   **Y**: Yield on AAA corporate bonds in India (set to a conservative baseline of $7.5\%$).
*   **Margin of Safety**:
    $$\text{Margin of Safety} = \frac{V^* - \text{Current Price}}{V^*}$$
    Echo flags an asset as **Undervalued** if the Margin of Safety is $\ge 30\%$.

### C. Stan Weinstein & William O'Neil (CAN SLIM) Trend Models
1. **Weinstein Stage Analysis**:
   *   **Stage 1 (Accumulation)**: Price consolidates around a flat 150-day Simple Moving Average (SMA).
   *   **Stage 2 (Markup/Uptrend)**: Price breaks out above a rising 150-day SMA, supported by expanding volume.
   *   **Stage 3 (Distribution)**: Price fluctuates in a broad range as the 150-day SMA flattens.
   *   **Stage 4 (Markdown/Downtrend)**: Price declines below a sloping downwards 150-day SMA.
2. **Uptrend Score**: Evaluates if the price is above the 150-day SMA, the SMA slope is positive, and the price is within $10\%$ of its 52-week high.
3. **CAN SLIM Technical Score**: Evaluates quarterly/annual EPS growth ($\ge 20\%$), volume accumulation (up-volume exceeds down-volume over the last 20 sessions), relative strength outperforming Nifty 50, and institutional held percentage.

### D. Wyckoff & Smart Money Concepts (SMC)
1. **Swing Pivots**: Detects swing highs and swing lows using a 5-candle rolling fractal window.
2. **Liquidity Sweeps**:
   *   **Sellside Sweep**: Price wick pierces below a previous swing low to grab stop-loss liquidity, but the candle close remains above the support level (signaling institutional accumulation).
   *   **Buyside Sweep**: Price wick breaks above a previous swing high but closes back below it (signaling retail trap distribution).
3. **Displacement Candles**: Identifies strong institutional intent candles where the body size (Close - Open) is $\ge 1.5\times$ the 20-candle average.
4. **Fair Value Gaps (FVG)**: Shaded imbalance zones left behind by displacement candles (`Low(t) > High(t-2)` for bullish or `High(t) < Low(t-2)` for bearish).

### E. News, Sentiment, and Transcript Disclosures
1. **FinBERT News Sentiment**: Scrapes headlines from RSS feeds (Yahoo Finance, Moneycontrol) and parses positive, negative, and neutral sentiment ratios.
2. **Unscripted Q&A Sentiment Divergence**:
   $$\text{Divergence} = \text{Prepared Remarks Sentiment} - \text{Analyst Q\&A Sentiment}$$
   High divergence ($>0.35$) flags that management is evasive or hiding operational headwinds during unscripted analyst probing.

### F. Order Book Surveillance (Level 2/3)
1. **Weighted Order Flow Imbalance (WOFI)**:
   Calculates buy-wall vs. sell-wall imbalances, weighting limit orders inversely proportional to their distance from the Last Traded Price (LTP).
2. **Iceberg Order Detection**: Monitors executions at a specific price level. If total executed trade volume exceeds $3\times$ the displayed limit size while price remains stagnant, it flags hidden institutional absorption.
3. **Spoofing Alert**: Tracks **Liquidity Fade Velocity** (cancellation-to-submission ratios). A high fade velocity close to the LTP indicates manipulative walls.

---

## 3. SEBI 2026 Algorithmic Framework Compliance

To remain legally deployable on Indian broker APIs (effective April 2026), Echo enforces strict compliance parameters:
*   **The 10 OPS Rate Limiter**: Implements a leaky-bucket queuing algorithm that throttles API order placement under 9 Orders Per Second (OPS) to prevent High-Frequency Trading (HFT) classification.
*   **Market Price Protection (MPP)**: Blocks naked market orders (`ORDER_TYPE_MARKET`). Orders are automatically rewritten as limit orders with a $\pm 1.5\%$ buffer offset (`LTP * 1.015` for buy, `LTP * 0.985` for sell) to eliminate slippage during flash crashes.
*   **Surveillance Watchlists (ASM/GSM)**: Automatically filters candidates against SEBI's Additional Surveillance Measure (ASM) and Graded Surveillance Measure (GSM) stages to prevent trapping capital in Trade-to-Trade (T2T) segments.

---

## 4. LangGraph Decision Committee Nodes

When a ticker is submitted for deep audit, the LangGraph orchestrator steps through these specialized desks:
1. **`discovery` (Discovery Desk)**: Loads the ticker profile and checks sector benchmarks.
2. **`technical_analysis` (Technical Desk)**: Calculates Weinstein stages, CAN SLIM ratings, sweeps, and active FVGs.
3. **`fundamental_evaluation` (Fundamental Desk)**: Calculates Buffett ROCE/integrity, Graham values, and checks SEBI ASM/GSM watchlists. If blocked by surveillance, it routes to `abort_trade`.
4. **`sentiment_validation` (Sentiment Desk)**: Scrapes news and earnings call transcripts, computing Q&A sentiment divergence. If divergence is excessive or news is highly negative, it routes to `abort_trade`.
5. **`simulation_gate` (Simulation Desk)**: Quantizes historical OHLCV data and runs a 24-step Monte Carlo autoregressive projection using the local **Kronos** model.
6. **`risk_arbiter` (Risk Desk)**: Calculates optimal position size (scaled up to $2.0\%$ of capital based on Kronos success probability), verifies SEBI compliance headers, and routes a paper trade execution.

---

## 5. Next-Gen Dashboard Interface Features

Designed to be beginner-friendly while providing institutional-grade analytical depth:
*   **Timing Assessment Card**: Beginner-friendly badge advising on entry risk:
    *   **Optimal Buy**: Stage 2 markup triggered close to support.
    *   **Accumulation**: Sideways consolidation. Safe for value investors but requires patience.
    *   **Train Has Left**: Overextended price ($>15\%$ above SMA). Pullbacks recommended.
    *   **Avoid**: Stage 3/4 distributions and markdowns.
*   **Glossary Help Tooltips**: Hovering over any scorecard metric (ROCE, WOFI, FVG, Q&A Divergence) displays a popup explaining what the metric is, why it is audited, and what values constitute a green flag.
*   **Dual Chart Layout**: Displays historical closing prices overlaid with SMA support floors alongside Kronos Monte Carlo projection bands ($68\%$, $95\%$ probability zones).
*   **Live Reasoning Terminal**: Streaming node logs via Server-Sent Events (SSE) reflecting the active thoughts of the Investment Committee.
