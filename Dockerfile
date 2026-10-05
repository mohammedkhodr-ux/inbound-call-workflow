# Worker image for the DDA inbound call workflow.
# Managed workflow deployments build this image and run the worker via CMD.
FROM python:3.12-slim AS build

COPY --from=ghcr.io/astral-sh/uv:0.5.31 /uv /uvx /bin/

WORKDIR /app

ENV UV_PYTHON_PREFERENCE=only-system \
    UV_NO_PYTHON_DOWNLOADS=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

COPY pyproject.toml uv.lock ./
COPY src ./src

RUN uv sync --frozen --no-dev

FROM python:3.12-slim AS runtime

WORKDIR /app

ENV PYTHONPATH=/app/src \
    PATH="/app/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1

RUN groupadd -g 1000 app && useradd -u 1000 -g 1000 -m -s /usr/sbin/nologin app

COPY --from=build --chown=1000:1000 /app /app

USER 1000:1000

CMD ["python", "-m", "entrypoints.worker"]
