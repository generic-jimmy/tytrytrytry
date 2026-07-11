FROM python:3.14-slim

WORKDIR /app

# Install build dependencies and purge apt cache to minimize layer size
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install packages directly (bypassing requirements.txt)
RUN pip install --no-cache-dir \
    fastapi \
    uvicorn \
    aiogram \
    sqlalchemy \
    asyncpg \
    pydantic-settings \
    httpx \
    jinja2 \
    python-multipart \
    itsdangerous

# Copy application source code
COPY . .

# Prevent Python from writing .pyc files and buffering stdout/stderr
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8080

# Respects platform-injected $PORT variables
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
