
### Task: Implement Phase 5 - The Frontend Dashboard Visualizer


**Objective:** Build a responsive, local-first single-page dashboard using React, Vite, and Tailwind CSS. The UI must cleanly display the multi-agent execution state machine, stream RAG forensic text logs, and chart Kronos's predictive probability matrices.
**Instructions for this phase:**
1. **Update the `README.md` File First:**
* Strictly adhere to the immutable document rule. Use markdown strikethrough (`~~old text~~`) for modifications, and add a final phase log: `"June 2026: Commenced Phase 5 - Implementing React/Vite local dashboard UI and integrating Recharts multi-trajectory vector visualization modules."`


2. **Establish the Backend API Bridge (`backend/main.py`):**
* Expose an aggregate FastAPI SSE (Server-Sent Events) or WebSocket endpoint `/api/stream_pipeline` that listens directly to the active LangGraph compilation context.
* When the state graph switches nodes (e.g., transitions from `fundamental_analysis_node` to `simulation_gate_node`), stream the state updates instantly to the client.


3. **Design the Visualizer Interface (`frontend/src/App.jsx`):**
* **The Operational Radar Panel:** Create a header showcasing virtual portfolio balance, active paper-traded holdings, total trailing stop-loss values, and overall market regime indicators (e.g., GIFT Nifty opening direction).
* **The Agent Thought Logs Matrix:** Display a multi-column layout showing real-time text analysis:
* *Column A (Fundamental Desk):* Displays text chunks pulled by Ollama alongside the extracted `fundamental_conviction_score` and critical audit warning strings.
* *Column B (Sentiment Desk):* Renders the FinBERT sentiment distribution and highlights if the system tripped the morning invalidation circuit breaker due to late-stage euphoria.


* **The Latent Physics Engine Canvas:** Integrate **Recharts** (or an open-source Canvas alternative) to chart the 30 Monte Carlo forecasting paths returned by the local Kronos microservice. Draw a clear, bold horizontal threshold line marking the support boundary to visually illustrate how many trajectories survived.


4. **Add the Paper Trading Controls:**
* Provide a clean input component to trigger a manual paper-trading analysis loop on any specified NSE/BSE ticker symbol (e.g., `TATOMOTORS`, `RELIANCE`).
* Include a table displaying the simulated positions sized by the Arbiter, tracking active PnL and automated trailing stop levels in real-time.




**Execution Controls:**
* Keep all UI elements accessible locally at `http://localhost:5173`. Leverage clean Tailwind utility patterns for maximum visual clarity and scannability.
* Maintain mock storage boundaries so that if a paper-trading order is submitted, it updates the state cache in Redis instead of attempting a live execution broker handshake.


Once completed, start the Vite development server, trigger a complete automated analysis loop from the UI, and verify that the system correctly maps the semantic logs and Kronos vector graphs. Never clear or overwrite prior historical lines inside `README.md`.
