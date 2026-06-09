FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1-mesa-glx \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-bake models into the image layer to avoid cold-start downloads.
# HF_HOME must also be set as a Railway env var so the running container
# finds the models at the same path baked into the image.
ENV HF_HOME=/app/hf_cache
ENV SENTENCE_TRANSFORMERS_HOME=/app/hf_cache/sentence_transformers

# Embedding model used by vector search (~560 MB)
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('intfloat/multilingual-e5-large')"

# ControlNet LineartDetector used by /artworks/lineart?mode=fine (~1.4 GB)
RUN python -c "from controlnet_aux import LineartDetector; LineartDetector.from_pretrained('lllyasviel/Annotators')"

COPY backend/ .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
