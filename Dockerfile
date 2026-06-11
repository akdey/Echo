# Use official Python image
FROM python:3.11-slim

# Install system dependencies and curl
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set up project workspace
WORKDIR /app

# Install uv package manager
RUN pip install --no-cache-dir uv

# Build Python Backend
COPY backend/pyproject.toml backend/uv.lock* ./backend/
RUN cd backend && uv sync --frozen

COPY backend/ ./backend/

# Expose default Hugging Face Space port
EXPOSE 7860

# Start Uvicorn pointing to exposed port
CMD ["/app/backend/.venv/bin/uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "7860"]
