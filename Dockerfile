# FastAPI app for Railway (and other container platforms).
# Railway sets PORT — do not hardcode it in the platform UI.
#
# Root directory: repository root (this Dockerfile lives next to pyproject.toml).
# Health: GET /health or /ready
#
# Set required env vars in Railway (see src/settings.py), e.g. OPENAI_API_KEY,
# POSTGRES_*, REDIS_*, OPENAI_BASE_URL, etc.
#
# Base image: Astral’s uv distro image — includes both Python and the `uv` CLI
# (no separate “install uv” step). Matches .python-version (3.10).

FROM ghcr.io/astral-sh/uv:python3.10-bookworm-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# build-essential: some wheels compile from sdist; curl: optional health/debug
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock ./

RUN uv sync --frozen --no-install-project

COPY src/ ./src/
COPY streamlit_utils.py ./

ENV PYTHONPATH=/app
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8055

CMD ["sh", "-c", "exec uvicorn src.main:app --host 0.0.0.0 --port ${PORT:-8055}"]
