-- W2-C governance metadata, RBAC, audit, backfill queue, and lineage cache.
-- Idempotent: safe on a fresh postgres-core volume and on an existing one.

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE SCHEMA IF NOT EXISTS ops;

CREATE TABLE IF NOT EXISTS ops.dataset_registry (
    id                  text        PRIMARY KEY,
    name                text        NOT NULL,
    layer               text        NOT NULL CHECK (layer IN ('bronze', 'silver', 'gold', 'serving')),
    domain              text        NOT NULL,
    kind                text        NOT NULL CHECK (kind IN ('iceberg', 'postgres')),
    location            text        NOT NULL,
    description         text        NOT NULL,
    owner               text        NOT NULL,
    classification      text        NOT NULL
                        CHECK (classification IN ('public', 'internal', 'confidential', 'restricted', 'pii')),
    retention_days      integer     NOT NULL DEFAULT 0,
    refresh_schedule    text,
    sla                 text,
    license             text,
    contains_pii        boolean     NOT NULL DEFAULT false,
    tags                text[]      NOT NULL DEFAULT '{}',
    columns             jsonb,
    auto_classification text
                        CHECK (auto_classification IS NULL OR auto_classification IN ('public', 'internal', 'confidential', 'restricted', 'pii')),
    status              text        NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'deprecated', 'retired')),
    deprecated_at       timestamptz,
    removal_date        date,
    contract_version    text,
    change_note         text,
    updated_at          timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS dataset_registry_layer_idx
    ON ops.dataset_registry (layer, domain);

CREATE TABLE IF NOT EXISTS ops.api_keys (
    key_id       text        PRIMARY KEY,
    key_hash     text        NOT NULL,
    role         text        NOT NULL CHECK (role IN ('viewer', 'operator', 'admin')),
    owner        text        NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    revoked_at   timestamptz,
    last_used_at timestamptz
);

CREATE TABLE IF NOT EXISTS ops.audit_log (
    id         bigserial   PRIMARY KEY,
    ts         timestamptz NOT NULL DEFAULT now(),
    actor      text        NOT NULL DEFAULT 'anonymous',
    role       text        NOT NULL DEFAULT 'anonymous',
    action     text        NOT NULL,
    target     text,
    method     text        NOT NULL,
    path       text        NOT NULL,
    status     integer     NOT NULL,
    request_id text,
    detail     jsonb       NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS audit_log_ts_idx ON ops.audit_log (ts DESC);
CREATE INDEX IF NOT EXISTS audit_log_actor_idx ON ops.audit_log (actor, ts DESC);

CREATE TABLE IF NOT EXISTS ops.backfill_requests (
    request_id   text        PRIMARY KEY,
    start_ts     timestamptz NOT NULL,
    end_ts       timestamptz NOT NULL,
    status       text        NOT NULL DEFAULT 'queued'
                 CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
    requested_by text,
    role         text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    detail       jsonb       NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS ops.lineage_edges (
    dataset_id     text        NOT NULL,
    upstream_id    text        NOT NULL,
    job_namespace  text,
    job_name       text,
    run_id         text,
    event_type     text,
    updated_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (dataset_id, upstream_id)
);

CREATE INDEX IF NOT EXISTS lineage_edges_upstream_idx
    ON ops.lineage_edges (upstream_id);

DO $$
BEGIN
    IF to_regclass('serving.catalog_datasets') IS NOT NULL THEN
        ALTER TABLE serving.catalog_datasets
            ADD COLUMN IF NOT EXISTS auto_classification text;
    END IF;
END $$;
