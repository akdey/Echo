import os
import re
import logging
import asyncio
import threading
import multiprocessing
from typing import Optional

logger = logging.getLogger(__name__)

# Global flag to track llama_cpp availability
HAS_LLAMA_CPP = False
try:
    import llama_cpp
    HAS_LLAMA_CPP = True
    logger.info("llama-cpp-python imported successfully.")
except Exception as e:
    # Do not raise error - it might not be installed in the local dev environment
    logger.warning(f"Failed to import llama-cpp-python: {e}")

class LocalLLMEngine:
    def __init__(self):
        self._model = None
        self._lock = threading.Lock()
        
        # Locate backend directory relative to this file
        services_dir = os.path.dirname(os.path.abspath(__file__))
        backend_dir = os.path.dirname(services_dir)
        self.model_path = os.path.abspath(os.path.join(backend_dir, "models", "google_gemma-4-E4B-it-Q4_K_M.gguf"))
        
    def _ensure_model(self):
        with self._lock:
            if self._model:
                return self._model
            
            if not HAS_LLAMA_CPP:
                logger.error("llama-cpp-python is not available on this system.")
                return None
                
            try:
                if not os.path.exists(self.model_path):
                    logger.error(f"Gemma model file not found at {self.model_path}")
                    return None
                    
                from llama_cpp import Llama
                threads = max(2, multiprocessing.cpu_count())
                logger.info(f"Initializing Llama model from {self.model_path} with {threads} threads...")
                self._model = Llama(
                    model_path=self.model_path,
                    n_ctx=2048,
                    n_threads=threads,
                    n_gpu_layers=0, # Force CPU
                    logits_all=False,
                    flash_attn=True,
                    verbose=False
                )
                logger.info("Llama model initialized successfully.")
                return self._model
            except Exception as e:
                logger.error(f"Failed to load local LLM engine: {e}")
                return None

    def _strip_thoughts(self, text: str) -> str:
        if not text:
            return text
        # Gemma 4 thought pattern: <|channel>thought ... <channel|>
        text = re.sub(r'<\|channel>thought.*?<channel\|>', '', text, flags=re.DOTALL)
        return text.strip()

    def generate(self, prompt: str, system_prompt: Optional[str] = None, temperature: float = 0.2) -> Optional[str]:
        model = self._ensure_model()
        if not model:
            return None
            
        try:
            system_val = system_prompt or "You are a helpful financial assistant."
            # Format prompt for Gemma 4
            formatted_prompt = f"<|turn>system\n{system_val} <turn|>\n<|turn>user\n{prompt} <turn|>\n<|turn>model\n"
            
            output = model(
                formatted_prompt,
                max_tokens=1024,
                temperature=temperature,
                stop=["<turn|>", "<|turn>", "<|im_end|>", "<|endoftext|>"],
                echo=False
            )
            raw_text = output['choices'][0]['text'].strip()
            return self._strip_thoughts(raw_text)
        except Exception as e:
            logger.error(f"Error during local Gemma inference: {e}")
            return None

# Singleton-like instance
_local_engine = LocalLLMEngine()

async def query_llm(prompt: str, system_instruction: str = None) -> Optional[str]:
    """
    Unified entry point to query Gemma model locally via llama-cpp-python.
    Executes inference in a threadpool to prevent blocking the async event loop.
    """
    global HAS_LLAMA_CPP
    if not HAS_LLAMA_CPP:
        logger.error("Local LLM engine is unavailable (llama_cpp import failed).")
        return None
        
    try:
        loop = asyncio.get_event_loop()
        res = await loop.run_in_executor(
            None,
            _local_engine.generate,
            prompt,
            system_instruction
        )
        return res
    except Exception as e:
        logger.error(f"Inference run failed: {e}")
        return None
