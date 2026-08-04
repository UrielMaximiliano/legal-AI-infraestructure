# Stage 1: Builder
FROM python:3.12-slim AS builder

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN pip install uv && uv sync --frozen --no-dev

# Stage 2: Runtime
FROM python:3.12-slim AS runtime

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libcairo2 \
        libgdk-pixbuf-2.0-0 \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        shared-mime-info \
        fonts-dejavu \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -r appuser \
    && useradd -r -g appuser appuser \
    && mkdir -p /var/lib/legal-ai/exports \
    && chown -R appuser:appuser /var/lib/legal-ai

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY src /app/src
COPY alembic.ini /app/alembic.ini
COPY alembic /app/alembic

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/src"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV EXPORT_STORAGE_ROOT=/var/lib/legal-ai/exports

EXPOSE 8000

USER appuser

CMD ["uvicorn", "legal_ai.main:app", "--host", "0.0.0.0", "--port", "8000"]
