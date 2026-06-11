FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
# Install CPU-only PyTorch before the rest to avoid the 2.2 GB CUDA variant.
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download the embedding model at build time so the container starts without
# hitting HF Hub on every cold start. SENTENCE_TRANSFORMERS_HOME pins the cache
# path so the same location is found at runtime.
# HF Spaces runs as user 1000 — chmod ensures the cache is readable.
ENV SENTENCE_TRANSFORMERS_HOME=/app/.cache/sentence_transformers
ARG EMBEDDING_MODEL=paraphrase-multilingual-MiniLM-L12-v2
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('$EMBEDDING_MODEL')" \
    && chmod -R 755 /app/.cache

COPY backend/ .

EXPOSE 7860
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-7860}"]
