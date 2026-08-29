# Build context = repo root (so we can COPY runtime/ from root).
#   docker build -f eks/app/Dockerfile -t ada-eks:latest .

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY eks/app/pyproject.toml /app/pyproject.toml
RUN pip install --no-cache-dir \
      "fastapi>=0.115.0" \
      "uvicorn[standard]>=0.32.0" \
      "deepagents>=0.6.12" \
      "langchain>=1.3.12,<2.0.0" \
      "langchain-anthropic>=1.5.4,<2.0.0" \
      "mirage-ai[s3]>=0.0.5" \
      "boto3>=1.40.0"

COPY runtime/ /app/runtime/
COPY eks/app/agent.py eks/app/main.py /app/

RUN mkdir -p /tmp/sandbox

EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
