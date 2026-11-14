# syntax=docker/dockerfile:1.7
FROM python:3.11-slim AS build

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update \
    && apt-get install -y --no-install-recommends build-essential

COPY pyproject.toml README.md ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/pip \
    pip wheel --wheel-dir /wheels .

FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/app \
    API_PORT=8000 \
    DUCKDB_EXTENSION_DIR=/app/.duckdb/extensions

RUN addgroup --gid 10001 api \
    && adduser --uid 10001 --gid 10001 --disabled-password --gecos "" api \
    && mkdir -p /app \
    && chown -R 10001:10001 /app

COPY --from=build /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links=/wheels bmip \
    && rm -rf /wheels

USER 10001:10001
RUN python -c "import duckdb; c = duckdb.connect(config={'extension_directory': '/app/.duckdb/extensions'}); c.execute('INSTALL iceberg'); c.execute('INSTALL httpfs'); c.close()"

WORKDIR /app
EXPOSE 8000

CMD ["uvicorn", "bmip.api.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
