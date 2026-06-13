import os
import re
import json
import logging
import asyncio
import threading
import multiprocessing
from typing import Optional, Type, TypeVar
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

# Generic TypeVar for Pydantic model return type
T = TypeVar("T", bound=BaseModel)

# Global flag to track llama_cpp availability
HAS_LLAMA_CPP = False
try:
    import llama_cpp
    HAS_LLAMA_CPP = True
    logger.info("llama-cpp-python imported successfully.")
except Exception as e:
    logger.warning(f"Failed to import llama-cpp-python: {e}")


class LocalLLMEngine:
    def __init__(self):
        self._model = None
        self._lock = threading.Lock()

        # Locate backend directory relative to this file
        services_dir = os.path.dirname(os.path.abspath(__file__))
        backend_dir  = os.path.dirname(services_dir)
        self.model_path = os.path.abspath(
            os.path.join(backend_dir, "models", "google_gemma-4-E4B-it-Q4_K_M.gguf")
        )

    def _ensure_model(self):
        with self._lock:
            if self._model:
                return self._model

            if not HAS_LLAMA_CPP:
                logger.error("llama-cpp-python is not available on this system.")
                return None

            try:
                if not os.path.exists(self.model_path):
                    logger.error("Gemma model file not found at %s", self.model_path)
                    return None

                from llama_cpp import Llama
                threads = max(2, multiprocessing.cpu_count())
                logger.info("Initializing Llama model from %s with %d threads...", self.model_path, threads)
                self._model = Llama(
                    model_path=self.model_path,
                    n_ctx=2048,
                    n_threads=threads,
                    n_gpu_layers=0,   # Force CPU
                    logits_all=False,
                    flash_attn=True,
                    verbose=False,
                )
                logger.info("Llama model initialized successfully.")
                return self._model
            except Exception as e:
                logger.error("Failed to load local LLM engine: %s", e)
                return None

    def _strip_thoughts(self, text: str) -> str:
        """Strips Gemma 4 internal thinking blocks from the output."""
        if not text:
            return text
        text = re.sub(r'<\|channel\>thought.*?<channel\|>', '', text, flags=re.DOTALL)
        return text.strip()

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.2,
    ) -> Optional[str]:
        model = self._ensure_model()
        if not model:
            return None

        try:
            system_val     = system_prompt or "You are a helpful financial assistant."
            # Gemma 4 turn format
            formatted_prompt = (
                f"<|turn>system\n{system_val} <turn|>\n"
                f"<|turn>user\n{prompt} <turn|>\n"
                f"<|turn>model\n"
            )

            output = model(
                formatted_prompt,
                max_tokens=1024,
                temperature=temperature,
                stop=["<turn|>", "<|turn>", "<|im_end|>", "<|endoftext|>"],
                echo=False,
            )
            raw_text = output["choices"][0]["text"].strip()
            return self._strip_thoughts(raw_text)
        except Exception as e:
            logger.error("Error during local Gemma inference: %s", e)
            return None

    def generate_structured(
        self,
        prompt: str,
        schema: Type[T],
        system_prompt: Optional[str] = None,
        max_retries: int = 3,
    ) -> Optional[T]:
        """
        Generates output from the LLM and validates it against a Pydantic schema.
        Retries automatically up to `max_retries` times if the JSON is malformed
        or fails schema validation — equivalent to what the `instructor` library does,
        without requiring a separate OpenAI-compatible server.

        On each retry the prompt is augmented with the previous error to guide the model.
        """
        base_schema_str = json.dumps(schema.model_json_schema(), indent=2)
        system = (
            (system_prompt or "You are a precise financial data extractor.") +
            "\nYou MUST respond with ONLY valid JSON. No markdown, no explanation, no extra text."
        )

        last_error: Optional[str] = None

        for attempt in range(1, max_retries + 1):
            error_guidance = ""
            if last_error:
                error_guidance = (
                    f"\n\nPrevious attempt failed with: {last_error}\n"
                    "Fix the JSON and try again. Ensure all required fields are present."
                )

            full_prompt = (
                f"{prompt}{error_guidance}\n\n"
                f"Required JSON schema:\n```json\n{base_schema_str}\n```\n\n"
                "Respond with only the JSON object:"
            )

            raw = self.generate(full_prompt, system_prompt=system, temperature=0.1)
            if not raw:
                last_error = "Model returned empty response."
                logger.warning("[LLM Structured] Attempt %d: empty response.", attempt)
                continue

            # Extract JSON — try strict match first, then relaxed
            json_str: Optional[str] = None
            # Try fenced code block first
            fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
            if fenced:
                json_str = fenced.group(1)
            else:
                # Grab the first {...} block
                bare = re.search(r"(\{.*\})", raw, re.DOTALL)
                if bare:
                    json_str = bare.group(1)

            if not json_str:
                last_error = f"No JSON object found in model output: {raw[:200]}"
                logger.warning("[LLM Structured] Attempt %d: %s", attempt, last_error)
                continue

            try:
                parsed = schema.model_validate_json(json_str)
                logger.info("[LLM Structured] Schema validation passed on attempt %d.", attempt)
                return parsed
            except (ValidationError, json.JSONDecodeError) as ve:
                last_error = str(ve)[:300]
                logger.warning("[LLM Structured] Attempt %d validation error: %s", attempt, last_error)

        logger.error("[LLM Structured] All %d attempts failed. Last error: %s", max_retries, last_error)
        return None


# ── Singleton engine ──────────────────────────────────────────────────────────
_local_engine = LocalLLMEngine()


# ── Public async API ──────────────────────────────────────────────────────────

async def query_llm(prompt: str, system_instruction: Optional[str] = None) -> Optional[str]:
    """
    Unified entry point to query Gemma model locally via llama-cpp-python.
    Executes inference in a threadpool to prevent blocking the async event loop.
    Returns raw string output.
    """
    if not HAS_LLAMA_CPP:
        logger.error("Local LLM engine is unavailable (llama_cpp import failed).")
        return None

    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            _local_engine.generate,
            prompt,
            system_instruction,
        )
    except Exception as e:
        logger.error("Inference run failed: %s", e)
        return None


async def query_llm_structured(
    prompt: str,
    schema: Type[T],
    system_instruction: Optional[str] = None,
    max_retries: int = 3,
) -> Optional[T]:
    """
    Schema-enforced structured output from the local Gemma model.

    Equivalent to using the `instructor` library but works natively with
    llama-cpp-python's Python API without needing an OpenAI-compatible server.

    Args:
        prompt:            Task prompt for the model.
        schema:            Pydantic BaseModel class defining the required output shape.
        system_instruction: Optional system prompt override.
        max_retries:       Number of self-correction retry loops (default 3).

    Returns:
        Validated Pydantic model instance, or None if all retries fail.

    Example:
        class CatalystData(BaseModel):
            theme: str
            products_or_materials: List[str]
            estimated_budget_cr: Optional[float]

        result = await query_llm_structured(
            prompt="Classify this catalyst: ...",
            schema=CatalystData,
        )
        if result:
            print(result.theme, result.estimated_budget_cr)
    """
    if not HAS_LLAMA_CPP:
        logger.error("Local LLM engine unavailable.")
        return None

    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            _local_engine.generate_structured,
            prompt,
            schema,
            system_instruction,
            max_retries,
        )
    except Exception as e:
        logger.error("Structured inference run failed: %s", e)
        return None
