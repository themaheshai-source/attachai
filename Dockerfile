FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    NODE_ENV=production \
    HOST=0.0.0.0 \
    PORT=3000 \
    DATA_DIR=/app/data
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 orbit
COPY requirements.txt pyproject.toml README.md ./
RUN pip install --no-cache-dir -r requirements.txt
COPY orbit_ai ./orbit_ai
COPY public ./public
COPY supabase ./supabase
COPY docs ./docs
COPY scripts ./scripts
RUN mkdir -p /app/data && chown -R orbit:orbit /app
USER orbit
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 CMD curl -fsS http://127.0.0.1:${PORT:-3000}/health || exit 1
CMD ["sh", "-c", "uvicorn orbit_ai.app:app --host ${HOST:-0.0.0.0} --port ${PORT:-3000}"]
