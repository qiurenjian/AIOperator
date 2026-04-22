FROM python:3.11-slim

WORKDIR /app

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    NODE_VERSION=20.x

# git, curl, ca-certs + Node.js for Claude Code CLI
RUN apt-get update && apt-get install -y --no-install-recommends \
        git curl ca-certificates gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Claude Code CLI (OAuth state will be persisted via /root/.config volume)
RUN npm install -g @anthropic-ai/claude-code@latest

RUN pip install --upgrade pip && pip install \
    "temporalio>=1.7.0" \
    "httpx>=0.27.0" \
    "anthropic>=0.39.0" \
    "pydantic>=2.9.0" \
    "pydantic-settings>=2.6.0" \
    "python-dotenv>=1.0.1" \
    "structlog>=24.4.0" \
    "jinja2>=3.1.4" \
    "lark-oapi>=1.3.0" \
    "asyncpg>=0.29.0"

COPY aiop /app/aiop
COPY activities /app/activities
COPY workflows /app/workflows
COPY apps /app/apps

CMD ["python", "-m", "apps.worker_runtime.main"]
