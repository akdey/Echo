import json
import logging
from typing import List, Dict, Any, Optional
import chromadb

from backend.services.llm_gateway import query_llm

logger = logging.getLogger(__name__)

class RealEmbeddingFunction:
    """A real local embedding function using sentence-transformers."""
    def __call__(self, input: List[str]) -> List[List[float]]:
        return self.embed_documents(input)

    def embed_documents(self, input: List[str]) -> List[List[float]]:
        from backend.services.embeddings import generate_embedding
        return [generate_embedding(text) for text in input]

    def embed_query(self, input: List[str]) -> List[List[float]]:
        return self.embed_documents(input)

    def name(self) -> str:
        return "RealEmbeddingFunction"

class FundamentalInvestigator:
    """
    Forensic Accounting RAG Engine utilizing ChromaDB for document storage/retrieval
    and unified LLM gateway for qualitative auditor remark and promoter pledging analyses.
    """
    def __init__(self, db_path: str = "backend/data_store/chromadb"):
        # Set up a persistent local ChromaDB client
        self.chroma_client = chromadb.PersistentClient(path=db_path)
        # Use real local embedding function using sentence-transformers
        self.embedding_function = RealEmbeddingFunction()
        self.collection_name = "forensic_accounting"
        self.collection = self.chroma_client.get_or_create_collection(
            name=self.collection_name,
            embedding_function=self.embedding_function
        )

    async def ingest_document_chunks(self, ticker: str, chunks: List[str]) -> None:
        """Embed and ingest corporate report text chunks into ChromaDB."""
        ids = [f"{ticker}_chunk_{i}" for i in range(len(chunks))]
        metadatas = [{"ticker": ticker, "source": "filing"} for _ in chunks]
        
        self.collection.add(
            documents=chunks,
            metadatas=metadatas,
            ids=ids
        )
        logger.info("Ingested %d text chunks into ChromaDB for ticker %s", len(chunks), ticker)

    def _evaluate_forensics_heuristically(self, text: str) -> Dict[str, Any]:
        """
        Local fallback parser evaluating forensic accounting risks when LLM is offline.
        Scans for keyword signatures of red flags.
        """
        flags = {
            "qualified_remarks": False,
            "promoter_pledging_spike": False,
            "operating_cash_flow_drop": False
        }
        
        low_text = text.lower()
        if any(w in low_text for w in ["qualified opinion", "adverse opinion", "disclaimer of opinion", "auditor remark", "qualified remark", "accounting irregularities"]):
            flags["qualified_remarks"] = True
            
        if any(w in low_text for w in ["pledged", "pledging", "encumbrance", "promoter share pledge"]):
            if any(w in low_text for w in ["increase", "spike", "rise", "elevated", "pledged more"]):
                flags["promoter_pledging_spike"] = True
                
        if any(w in low_text for w in ["cash flow from operating", "operating cash flow", "cash generated from operations"]):
            if any(w in low_text for w in ["decrease", "decline", "drop", "negative", "spilled", "outflow"]):
                flags["operating_cash_flow_drop"] = True
                
        return flags

    async def investigate_ticker(self, ticker: str) -> Dict[str, Any]:
        """
        Queries ChromaDB for corporate records on the ticker, checks for forensic red flags
        via unified LLM (or local fallback), and assigns a Fundamental Conviction Score.
        """
        # Retrieve relevant chunks for forensic analysis
        results = self.collection.query(
            query_texts=["auditor remarks qualified opinions promoter share pledging operating cash flow"],
            n_results=5,
            where={"ticker": ticker}
        )
        
        documents = results.get("documents", [[]])[0]
        if not documents:
            logger.warning("No fundamental document chunks found for %s", ticker)
            return {
                "ticker": ticker,
                "fundamental_conviction_score": 0.5,  # neutral default
                "flags": {},
                "source": "no_data"
            }

        combined_text = "\n\n".join(documents)
        
        # Define forensic prompt
        prompt = f"""
        You are an elite forensic accountant auditing corporate reports for {ticker}.
        Analyze the following text extract carefully:
        ---
        {combined_text}
        ---
        Based on the text, answer the following questions with yes/no:
        1. Are there any qualified remarks, adverse opinions, or concerns raised by the auditor?
        2. Is there a significant increase or high level of promoter share pledging?
        3. Is there a notable drop, deterioration, or negative trend in operating cash flows?
        
        Provide your answers in the JSON format:
        {{"qualified_remarks": true/false, "promoter_pledging_spike": true/false, "operating_cash_flow_drop": true/false}}
        """

        raw_response = await query_llm(prompt)
        
        flags = None
        source = "llm"
        
        if raw_response:
            try:
                # Find JSON payload in response
                start_idx = raw_response.find("{")
                end_idx = raw_response.rfind("}") + 1
                if start_idx != -1 and end_idx != -1:
                    flags = json.loads(raw_response[start_idx:end_idx])
            except Exception as e:
                logger.error("Failed to parse LLM JSON response: %s", str(e))

        if not flags:
            logger.info("Using local heuristic fallback parser for forensic auditing.")
            flags = self._evaluate_forensics_heuristically(combined_text)
            source = "local_heuristic"

        # Calculate dynamic Fundamental Conviction Score
        # Start at 1.0 (perfect) and deduct 0.3 for each red flag triggered. Minimum score is 0.1
        score = 1.0
        if flags.get("qualified_remarks"):
            score -= 0.3
        if flags.get("promoter_pledging_spike"):
            score -= 0.3
        if flags.get("operating_cash_flow_drop"):
            score -= 0.3
            
        final_score = max(0.1, min(1.0, score))
        
        return {
            "ticker": ticker,
            "fundamental_conviction_score": final_score,
            "flags": flags,
            "source": source
        }
