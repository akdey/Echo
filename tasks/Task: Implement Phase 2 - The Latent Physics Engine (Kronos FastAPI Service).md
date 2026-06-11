### Task: Implement Phase 2 - The Latent Physics Engine (Kronos FastAPI Service)

**Objective:** Set up a standalone, local FastAPI microservice that wraps the pre-trained Kronos model weights to evaluate the structural integrity of market momentum via forward-looking trajectory simulations.
**Instructions for this phase:**
1. **Update the `README.md` File:**
* Remember the immutable log rule. Use markdown strikethrough (`~~old text~~`) for any structural deviations, and append a new timestamped entry: `"June 2026: Initiated Phase 2 - Setting up local Kronos microservice wrapper and Monte Carlo simulation endpoints via FastAPI."`


2. **Build the Kronos Predictor Module (`backend/services/kronos_brain.py`):**
* Create a class that loads the pre-trained weights from the Hugging Face repository `shiyu-coder/kronos-base` (or a local mini checkpoint if memory constraints dictate) using PyTorch and Hugging Face Transformers.
* Implement a tokenization method that map continuous OHLCVA arrays (fetched from Phase 1's Redis cache) into the discrete dual-token (coarse + fine subtokens) format used by the Kronos architecture.
* Implement an autoregressive trajectory generator function. This function must perform a 24-to-48 step Monte Carlo forward simulation (running $N=30$ distinct paths) by adding temperature variance ($0.7$) to the generative decoder loop.


3. **Expose the Simulation Endpoint (`backend/services/kronos_api.py`):**
* Create a dedicated FastAPI instance running on a unique internal port (e.g., `8001`).
* Implement a POST endpoint `/simulate_regime` that accepts a Pydantic payload containing the `ticker` symbol and the historical tensor data.
* The endpoint must trigger the `kronos_brain.py` simulations to calculate:
* `upside_probability`: The percentage of simulated paths where structural Stage 2 momentum survives without breaking support.
* `volatility_amplification`: The variance variance across the generated trajectories, determining if a massive expansion of risk is imminent.
* `is_safe`: A boolean flag that evaluates to `True` *only* if `upside_probability` $\ge 0.85$ and volatility risk is tightly bound.



**Execution Controls:**
* Keep this service decoupled. It should read its arrays using the Redis connection utilities created in Phase 1.
* Ensure heavy mathematical processing (tensor conversions and matrix multiplications) utilizes vectorized NumPy/PyTorch operations for maximum speed.
* Document the calculation logic for the probability distribution inside the code comments.


When completed, demonstrate that the endpoint successfully takes a structured history array of an NSE stock from Redis and responds with the correct validation payload. Do not delete or overwrite historical lines in the `README.md`.

