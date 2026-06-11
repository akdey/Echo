---
title: Echo
emoji: 📈
colorFrom: purple
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# Echo: Multi-Agent Investment Committee for Indian Equity Markets


Echo is a highly secure, ~~local-first~~ Multi-Agent Investment Committee designed specifically for the Indian Equity Markets (BSE/NSE). **[2026-06-11T20:55:00+05:30] Update**: Echo will be deployed directly to Hugging Face Spaces. The system prioritizes strict risk management, probabilistic forecasting over binary guessing, late-stage FOMO exhaustion tracking, and complete data privacy.

---

## Immutable Documentation Protocol
* **The Core Rule**: You are STRICTLY FORBIDDEN from deleting any line of text from this `README.md`.
* **The Update Protocol**: If a feature changes, a bug is fixed, a library is swapped, or a development plan is altered, you must use markdown strikethrough (`~~old text~~`) on the outdated information and write the new updated information or fix details directly below it with a 2026 timestamp. This creates an undeletable, chronological audit trail of Echo's evolution.

---

## Directory Scaffold Layout

~~/echo-engine
├── frontend/                 # React + Vite + Tailwind
├── backend/                  # FastAPI, LangGraph agents, Redis pipelines
├── backend/data_store/       # Local ChromaDB space + persistent directories
└── README.md                 # The immutable audit log (This File)~~

### [2026-06-11T20:48:00+05:30] Updated Layout
```text
/echo-engine (workspace root)
├── frontend/                 # React + Vite + Tailwind
├── backend/                  # Python environment, FastAPI, LangGraph agents, Redis pipelines, pyproject.toml
│   └── data_store/           # Local ChromaDB space + persistent directories
└── README.md                 # The immutable audit log (This File)
```

---

## Zero-Cost Infrastructure & API Integration Stack
* **Market Data & Screening Feed**: OpenBB Terminal SDK (historical structures), YFinance API, and free tier of Alpha Vantage / Twelvedata for daily/hourly BSE/NSE OHLCVA candles.
* **Live Pre-Market & Sentiment Feed**: Scraped live morning metrics via GIFT Nifty, RSS feeds from Moneycontrol, Economic Times, Livemint, and programmatically scraped direct NSE Corporate Disclosures.
* **Local Fundamental AI Engine**: Ollama running locally (`llama3:8b` or `mistral`) for forensic accounting RAG tasks.
* **Local Quantization Tokenizer**: Pre-trained weights of the Kronos foundation model (`shiyu-coder/kronos-base` or `kronos-mini` via Hugging Face transformers) running locally on CPU/GPU via PyTorch for tensor calculations.

---

## Package Management & Core Architecture
* **Package Management**: `uv` is mandatory for all dependencies, virtual environments (`.venv`), and script execution.
* **Backend Framework**: Python with FastAPI (modular microservices).
* **Agent Orchestration**: LangGraph (strictly latest state-graph compilation architecture; legacy langchain/chains are forbidden; state schemas managed via Pydantic).
* **Database & Cache Layer**: ~~Local ChromaDB for fundamental vector space; local Redis Docker container for live tick caching, indicators, and Kronos tokenized tensors.~~
  * **Hugging Face Deployment Update [2026-06-11T20:55:00+05:30]**: Vector DB and models run in Hugging Face Space containers. The database & cache layer utilizes local in-memory fallback states or standard connection strings to cloud-managed Redis instances for high-speed caching.
* **Frontend Dashboard**: React (Vite) + Tailwind CSS + Lucide React showing active agent thoughts, simulated positions, and stop-loss triggers.

---

## Multi-Agent Desks & Temporal Timeline

### A. The Discovery Desk (Runs Evening 7:00 PM IST)
* Scans all liquid NSE/BSE stocks using OpenBB/YFinance.
* Filters for structural breakouts (Stan Weinstein Stage 1 to Stage 2 transitions).
* Excludes any stock overextended past key moving averages (preventing late-stage chasing).

### B. The Fundamental Desk (Runs Evening 7:30 PM IST)
* Automatically fetches recent corporate earnings PDFs or financial statements.
* Ingests chunks into local ChromaDB.
* Uses local Ollama to audit qualified auditor remarks, promoter share pledging increases, or negative changes in operational cash flow. Assigns a Fundamental Conviction Score.

### C. The Sentiment & Pre-Market Invalidation Desk (Runs Morning 8:00 AM - 8:45 AM IST)
* Scans GIFT Nifty direction and morning headlines using a local Hugging Face `FinBERT` model.
* Acts as a **Circuit Breaker**: Invalidates shortlists if negative corporate filings or retail bubble/euphoria is detected.

### D. The Risk Arbiter Desk (Runs Live 9:15 AM IST - Paper Trading Mode)
* Orchestrated with LangGraph hitting a blocking `Simulation Gate Node`.
* Feeds live OHLCVA tensors to a local Kronos endpoint.
* Runs a **24-step to 48-step Monte Carlo autoregressive rollout simulation** in Kronos latent space to compute `upside_probability` and `volatility_amplification`.
* Executes simulated position sizing (max 1-2% virtual equity risk) with trailing stop-losses.

---

## Chronological Audit Trail & Change Log

### [2026-06-11T20:46:00+05:30] - Project Initial Scaffolding
* Initialized project repository using `uv init`.
* Created folder layout: `frontend/`, `backend/`, `backend/data_store/`.
* Created the initial immutable `README.md` defining architecture, constraints, and audit requirements.

### [2026-06-11T20:48:00+05:30] - Relocated Python Backend Configuration
* Moved Python dependencies, virtual environment (`.venv`), `pyproject.toml`, and Python scripts from workspace root to `backend/` directory to keep workspace root clean.
* Initialized `uv` python application environment inside `backend/`.

### [2026-06-11T20:51:30+05:30] - Commenced Phase 1 Implementation
* June 2026: Commenced Phase 1 - Database foundations, Redis pipeline, and data caching layer implementation.

### [2026-06-11T20:55:00+05:30] - Hugging Face Deployment Shift
* Shifted from a purely local-first environment to a Hugging Face Space deployment.
* Configured the Redis Pipeline to support an in-memory fallback state engine when a local Redis service is unavailable, ensuring compatibility with Hugging Face Space environments out of the box.

### [2026-06-11T21:00:00+05:30] - Initiated Phase 2
* June 2026: Initiated Phase 2 - Setting up local Kronos microservice wrapper and Monte Carlo simulation endpoints via FastAPI.

### [2026-06-11T21:03:00+05:30] - Commenced Phase 3
* June 2026: Commenced Phase 3 - Building local Ollama-powered Fundamental RAG pipeline and FinBERT morning news sentiment scraping nodes.

### [2026-06-11T21:22:00+05:30] - Commenced Phase 5
* June 2026: Commenced Phase 5 - Implementing React/Vite local dashboard UI and integrating Recharts multi-trajectory vector visualization modules.




