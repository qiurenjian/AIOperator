FROM python:3.11-slim

WORKDIR /app

# 安装依赖
COPY pyproject.toml /app/pyproject.toml
RUN pip install --upgrade pip && pip install \
    "temporalio>=1.7.0" \
    "anthropic>=0.39.0" \
    "pydantic>=2.9.0" \
    "pydantic-settings>=2.6.0" \
    "python-dotenv>=1.0.1" \
    "structlog>=24.4.0" \
    "lark-oapi>=1.3.0" \
    "asyncpg>=0.29.0"

# 复制代码
COPY aiop /app/aiop
COPY activities /app/activities
COPY workflows /app/workflows
COPY apps /app/apps

# 启动
CMD ["python", "-m", "apps.feishu_connector.main"]
