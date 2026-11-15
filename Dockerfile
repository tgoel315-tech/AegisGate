# AegisGate RAG agent — container for Maritime (maritime.sh).
# Maritime builds the Dockerfile at the repo root and injects PORT at runtime.
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY rag/requirements.txt rag/requirements.txt
RUN pip install --no-cache-dir -r rag/requirements.txt
COPY rag/ rag/

ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "rag.start"]
