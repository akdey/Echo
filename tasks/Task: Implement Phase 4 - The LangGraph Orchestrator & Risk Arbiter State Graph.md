### Task: Implement Phase 4 - The LangGraph Orchestrator & Risk Arbiter State Graph


**Objective:** Build the core state-machine using the latest LangGraph StateGraph architecture. This orchestrates the discovery, fundamental analysis, sentiment validation, and mathematical simulation gates into a seamless, asynchronous paper-trading workflow.
**Instructions for this phase:**
1. **Update the `README.md` File:**
* Enforce the immutable documentation rule. Use markdown strikethrough (`~~old text~~`) for any structural or framework adjustments, and append a new timestamped log entry: `"June 2026: Initiated Phase 4 - Compiling the LangGraph StateGraph engine, implementing conditional execution routing, and designing the Simulation Gate Node."`


2. **Define the Global State Schema (`backend/agents/state.py`):**
* Create a structured state layout using a Pydantic class or typed dictionary.
* The state must track variables across the lifecycle, including: `ticker`, `current_price`, `fundamental_score`, `sentiment_score`, `kronos_upside_prob`, `kronos_vol_risk`, `is_invalidated`, `allocation_percentage`, and `execution_status`.


3. **Construct the Multi-Agent Committee Graph (`backend/agents/investment_committee.py`):**
* Initialize a LangGraph `StateGraph` passing your global state schema.
* **Node 1: `discovery_node**` - Pulls the daily shortlist candidate from the Discovery service.
* **Node 2: `fundamental_analysis_node**` - Reads the ticker state, queries `fundamental_rag.py`, and maps the score to the graph state.
* **Node 3: `sentiment_validation_node**` - Invokes `sentiment_analyzer.py` to check for overnight structural surprises or extreme retail euphoria.
* **Node 4: `simulation_gate_node**` - The Mathematical Brake. This node temporarily halts execution, extracts the historical tensor from Redis, and makes an asynchronous internal POST request to your local Kronos FastAPI service (`http://localhost:8001/simulate_regime`). It records the returned trajectory distribution metrics.


* **Node 5: `risk_arbiter_node**` - The final execution judge. If the stock passes the Kronos safety threshold, it runs position-sizing math (e.g., maximum 1-2% virtual equity exposure) and generates a simulated buy order with calculated trailing stop-losses.


4. **Implement Conditional Edge Routing:**
* Define clear conditional routing paths using `.add_conditional_edges()`.
* If the sentiment node flags `is_invalidated == True` or the fundamental score drops below a safe floor, route the graph directly to an `abort_trade_node` to protect capital.
* If the simulation node returns an upside probability below $85\%$ or flags high mean-reversion exhaustion risk, drop the execution route instantly and route to a `re_plan_node`.




**Execution Controls:**
* Do not use outdated LangChain agent wrappers or legacy frameworks. Rely strictly on explicit LangGraph compilation paradigms (`graph.compile()`).
* Ensure every node logs its internal reasoning, data values, and execution decisions back to the console to maintain clean local audit loops.


When completed, compile the graph and run a full mock trial starting with a standard Nifty 50 ticker symbol (e.g., "RELIANCE") to show the complete state transition path from discovery to sizing execution. Do not overwrite or clear previous log lines in the `README.md`.
