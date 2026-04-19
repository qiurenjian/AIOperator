FROM python:3.11-slim

WORKDIR /app

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

COPY pyproject.toml /app/pyproject.toml
RUN pip install --upgrade pip && pip install \
    "temporalio>=1.7.0" \
    "fastapi>=0.115.0" \
    "uvicorn[standard]>=0.32.0" \
    "httpx>=0.27.0" \
    "anthropic>=0.39.0" \
    "pydantic>=2.9.0" \
    "pydantic-settings>=2.6.0" \
    "python-dotenv>=1.0.1" \
    "structlog>=24.4.0"

COPY aiop /app/aiop
COPY activities /app/activities
COPY workflows /app/workflows
COPY apps /app/apps

EXPOSE 8000
CMD ["uvicorn", "apps.ingress.main:app", "--host", "0.0.0.0", "--port", "8000"]
