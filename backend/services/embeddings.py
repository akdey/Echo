import logging
from typing import List

logger = logging.getLogger(__name__)

_model = None

def get_embedding_model():
    global _model
    if _model is None:
        try:
            from sentence_transformers import SentenceTransformer
            logger.info("Loading local sentence-transformer model: all-MiniLM-L6-v2...")
            _model = SentenceTransformer("all-MiniLM-L6-v2")
            logger.info("Local embedding model loaded successfully.")
        except Exception as e:
            logger.error("Failed to load sentence-transformers model: %s", e)
            raise e
    return _model

def generate_embedding(text: str) -> List[float]:
    """Generates a 384-dimensional embedding vector for the given text."""
    if not text:
        return [0.0] * 384
    try:
        model = get_embedding_model()
        embedding = model.encode(text)
        return embedding.tolist()
    except Exception as e:
        logger.error("Error generating embedding: %s", e)
        return [0.0] * 384
