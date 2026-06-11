### Task: Implement Phase 3 - The Semantic Intelligence Layer (Fundamental RAG & News Sentiment)


**Objective:** Build two decoupled backend modules to analyze text data for the shortlisted stocks. Module A creates a local forensic accounting RAG system using Ollama. Module B scrapes financial news and NSE/BSE corporate filings to calculate sentiment and execute pre-market circuit breakers.
**Instructions for this phase:**
1. **Update the `README.md` File:**
* Adhere strictly to the immutable documentation rule. Use markdown strikethrough (`~~old text~~`) for any changed architecture plans, and append a new timestamped log entry: `"June 2026: Commenced Phase 3 - Building local Ollama-powered Fundamental RAG pipeline and FinBERT morning news sentiment scraping nodes."`


2. **Build the Fundamental Investigator Desk (`backend/services/fundamental_rag.py`):**
* Set up a connection to the local `ChromaDB` client (vector store).
* Write an asynchronous pipeline that ingests financial PDF text chunks (quarterly earnings reports, SEBI disclosures, audit results).
* Use a local sentence-transformers model (via Hugging Face) to embed the text chunks into ChromaDB.
* Implement a query function utilizing a local **Ollama** LLM instantiation (configured to pull `llama3:8b` or `mistral`).
* Code strict prompts forcing the LLM to act as a forensic accountant. It must search the document chunks specifically for: *qualified remarks by auditors, massive spikes in promoter share pledging, or drops in operating cash flow*.
* The module must output a normalized `fundamental_conviction_score` from `0.0` to `1.0`.


3. **Build the News & Pre-Market Circuit Breaker (`backend/services/sentiment_analyzer.py`):**
* Implement a lightweight, asynchronous RSS/Web scraper that aggregates the latest headlines for a given ticker from *Moneycontrol, Economic Times, and Livemint*.
* Integrate a local Hugging Face pipeline loading `ProsusAI/finbert` (or a similar open-source, highly efficient financial sentiment transformer).
* Write logic to calculate an aggregate morning sentiment score.
* **The Anti-Bubble / Invalidation Filter:** If the sentiment shows extreme retail hype (e.g., positive sentiment $95\%$ paired with a massive volume spike, signaling late-stage mania) OR if it detects highly critical overnight corporate text disclosures from the exchange, it flags `is_invalidated = True`.




**Execution Controls:**
* Keep everything free and local. Ensure all embedding tasks and FinBERT inference tasks are written using standard PyTorch pipeline syntax, leveraging local execution.
* Cache finalized daily sentiment scores and RAG results directly into **Redis** under temporary keys mapped to the ticker name to allow the upcoming LangGraph layer to read them instantly.


When completed, demonstrate that your script can successfully process an Indian stock news feed, extract the sentiment, and run a mock query against a sample financial PDF chunk using Ollama. Do not delete any historical text lines in the `README.md`.
