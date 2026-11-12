#!/bin/bash
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
CREATE SCHEMA IF NOT EXISTS ops;

CREATE TABLE IF NOT EXISTS ops.batch_runs (
    batch_id      text        PRIMARY KEY,
    source        text        NOT NULL,
    window_start  timestamptz NOT NULL,
    window_end    timestamptz NOT NULL,
    row_count     bigint      NOT NULL DEFAULT 0,
    checksum      text        NOT NULL,
    status        text        NOT NULL
                              CHECK (status IN ('running', 'succeeded', 'failed', 'skipped_identical')),
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS batch_runs_source_window_idx
    ON ops.batch_runs (source, window_start DESC);

CREATE TABLE IF NOT EXISTS ops.social_watermark (
    source          text        PRIMARY KEY,
    last_created_at timestamptz,
    updated_at      timestamptz NOT NULL DEFAULT now()
);
SQL

role_exists="$(psql -tAc --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    "SELECT 1 FROM pg_roles WHERE rolname = '${LAKEKEEPER_DB_USER}'")"
if [ "$role_exists" != "1" ]; then
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
        -c "CREATE ROLE \"${LAKEKEEPER_DB_USER}\" LOGIN PASSWORD '${LAKEKEEPER_DB_PASSWORD}'"
fi

db_exists="$(psql -tAc --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    "SELECT 1 FROM pg_database WHERE datname = '${LAKEKEEPER_DB_NAME}'")"
if [ "$db_exists" != "1" ]; then
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
        -c "CREATE DATABASE \"${LAKEKEEPER_DB_NAME}\" OWNER \"${LAKEKEEPER_DB_USER}\""
fi
