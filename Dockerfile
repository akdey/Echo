# Use official Python image
FROM python:3.12-slim

# Install system dependencies and curl
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    cmake \
    pkg-config \
    libgomp1 \
    libopenblas-dev \
    && rm -rf /var/lib/apt/lists/*

# Set environment variables for compilation stability and wheel configuration
ENV OMP_NUM_THREADS=1
ENV MKL_NUM_THREADS=1
ENV OPENBLAS_NUM_THREADS=1
ENV KMP_DUPLICATE_LIB_OK=TRUE
ENV CMAKE_ARGS="-DGGML_CPU=ON"
ENV CMAKE_BUILD_PARALLEL_LEVEL="1"
ENV UV_EXTRA_INDEX_URL="https://abetlen.github.io/llama-cpp-python/whl/cpu"
ENV UV_INDEX_STRATEGY="unsafe-best-match"

# Set up project workspace
WORKDIR /app

# Install uv package manager
RUN pip install --no-cache-dir uv

# Build Python Backend
COPY backend/pyproject.toml ./backend/
RUN cd backend && uv sync

# Pre-download the model into the image for instant startup on HF Spaces.
# Using Gemma 4 E4B (Instruct-GGUF) - ~2.5GB model file.
RUN mkdir -p /app/backend/models && \
    /app/backend/.venv/bin/python -c "from huggingface_hub import hf_hub_download; hf_hub_download(repo_id='bartowski/google_gemma-4-E4B-it-GGUF', filename='google_gemma-4-E4B-it-Q4_K_M.gguf', local_dir='/app/backend/models')"

# Install Playwright browser binaries and system dependencies
RUN /app/backend/.venv/bin/playwright install --with-deps chromium

COPY backend/ ./backend/

# Expose default Hugging Face Space port
EXPOSE 7860

# Start Uvicorn pointing to exposed port
CMD ["/app/backend/.venv/bin/uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "7860"]
