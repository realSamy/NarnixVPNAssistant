# --- Build stage: resolve dependencies with uv into a relocatable .venv ---
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev
COPY app ./app

# --- Runtime: slim interpreter + the built venv, nothing else ---
FROM python:3.12-slim-bookworm
RUN useradd --create-home narnix
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/app /app/app
USER narnix
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
