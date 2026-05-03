# LiteLLM proxy for Railway (and other container platforms).
# Railway injects PORT — do not hardcode a fixed listen port in Railway UI.
#
# Set in Railway (minimum for this repo’s config.yaml):
#   - DATABASE_URL          → add Postgres plugin or paste connection string
#   - STORE_MODEL_IN_DB=True
#   - OPENAI_API_KEY_* / REDIS_* / LANGFUSE_* as required by config.yaml
#   - LITELLM_MASTER_KEY    → recommended; align with general_settings.master_key or use os.environ in YAML
#
# Health check path (for Railway HTTP checks): /health/liveliness

FROM ghcr.io/berriai/litellm:main-stable

WORKDIR /app

COPY config.yaml /app/config.yaml

# Official image uses an entrypoint script; replace with a shell so ${PORT} expands at runtime (Railway).
ENTRYPOINT []
# Bind all interfaces; Railway maps its proxy to the container PORT.
CMD ["sh", "-c", "exec litellm --config /app/config.yaml --host 0.0.0.0 --port ${PORT:-4000}"]
