# syntax=docker/dockerfile:1.7
# BMIP dashboard image (W1-D). Reads the Query API over HTTP only.
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
    pip wheel --wheel-dir /wheels ".[dashboard]"

FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/app \
    BMIP_API_BASE_URL=http://api:8000

RUN addgroup --gid 10001 app \
    && adduser --uid 10001 --gid 10001 --disabled-password --gecos "" app \
    && mkdir -p /app \
    && chown -R 10001:10001 /app

COPY --from=build /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links=/wheels "bmip[dashboard]" \
    && rm -rf /wheels

# Streamlit reads .streamlit/config.toml from the working directory.
COPY --chown=10001:10001 .streamlit/config.toml /app/.streamlit/config.toml
COPY --chown=10001:10001 deploy/dashboard/entrypoint.sh /usr/local/bin/bmip-dashboard
RUN chmod 0755 /usr/local/bin/bmip-dashboard

USER 10001:10001
WORKDIR /app
EXPOSE 8501

CMD ["/usr/local/bin/bmip-dashboard"]
