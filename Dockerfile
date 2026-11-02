FROM python:3.11-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.6.8 /uv /bin/uv

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app

# Install the locked dependencies only; the service code is copied below so that
# code changes do not invalidate this layer
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-dev --no-install-project

COPY intent_disambiguation /app/intent_disambiguation

RUN useradd --system --uid 10001 --no-create-home app
USER 10001

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app
EXPOSE 8000

CMD ["uvicorn", "intent_disambiguation.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
