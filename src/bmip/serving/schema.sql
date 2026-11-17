CREATE SCHEMA IF NOT EXISTS serving;

CREATE TABLE IF NOT EXISTS serving.market_hourly (
    symbol           text        NOT NULL,
    window_start     timestamptz NOT NULL,
    open             numeric(18, 8) NOT NULL,
    high             numeric(18, 8) NOT NULL,
    low              numeric(18, 8) NOT NULL,
    close            numeric(18, 8) NOT NULL,
    volume           numeric(18, 8) NOT NULL,
    quote_volume     numeric(18, 8) NOT NULL,
    trade_count      bigint      NOT NULL,
    vwap             numeric(18, 8) NOT NULL,
    log_return_1h    double precision,
    realized_vol_1h  double precision,
    rv_ewma_24h      double precision,
    source           text        NOT NULL,
    event_date       date        NOT NULL,
    updated_at       timestamptz NOT NULL,
    loaded_at        timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, window_start)
);

CREATE INDEX IF NOT EXISTS market_hourly_window_idx
    ON serving.market_hourly (window_start DESC);

CREATE TABLE IF NOT EXISTS serving.market_latest (
    symbol           text        PRIMARY KEY,
    window_start     timestamptz NOT NULL,
    open             numeric(18, 8) NOT NULL,
    high             numeric(18, 8) NOT NULL,
    low              numeric(18, 8) NOT NULL,
    close            numeric(18, 8) NOT NULL,
    volume           numeric(18, 8) NOT NULL,
    quote_volume     numeric(18, 8) NOT NULL,
    trade_count      bigint      NOT NULL,
    vwap             numeric(18, 8) NOT NULL,
    log_return_1h    double precision,
    realized_vol_1h  double precision,
    rv_ewma_24h      double precision,
    source           text        NOT NULL,
    updated_at       timestamptz NOT NULL,
    loaded_at        timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS serving.sentiment_hourly (
    window_start             timestamptz PRIMARY KEY,
    post_count               integer     NOT NULL,
    unique_authors           integer     NOT NULL,
    mean_sentiment           double precision,
    positive_share           double precision,
    negative_share           double precision,
    neutral_share            double precision,
    total_likes              bigint      NOT NULL,
    total_reposts            bigint      NOT NULL,
    total_replies            bigint      NOT NULL,
    engagement_per_post      double precision,
    top_hashtags             text[],
    sentiment_model_version  text        NOT NULL,
    event_date               date        NOT NULL,
    updated_at               timestamptz NOT NULL,
    loaded_at                timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS sentiment_hourly_window_idx
    ON serving.sentiment_hourly (window_start DESC);

CREATE OR REPLACE VIEW serving.volatility AS
SELECT
    symbol,
    window_start,
    log_return_1h,
    realized_vol_1h,
    rv_ewma_24h,
    event_date,
    updated_at
FROM serving.market_hourly;

CREATE TABLE IF NOT EXISTS serving.predictions (
    symbol                 text        NOT NULL,
    window_start           timestamptz NOT NULL,
    model_version          text        NOT NULL DEFAULT 'none',
    model_name             text        NOT NULL DEFAULT 'none',
    model_alias            text        NOT NULL DEFAULT 'none',
    predicted_rv_next_1h   double precision,
    feature_ts             timestamptz,
    predicted_at           timestamptz NOT NULL DEFAULT now(),
    status                 text        NOT NULL DEFAULT 'ok'
                           CHECK (status IN ('ok', 'error')),
    detail                 text,
    request_id             text,
    input_hash             text,
    PRIMARY KEY (symbol, window_start, model_version)
);

CREATE INDEX IF NOT EXISTS predictions_window_idx
    ON serving.predictions (window_start DESC);

CREATE TABLE IF NOT EXISTS serving.freshness (
    metric       text        PRIMARY KEY,
    data_ts      timestamptz,
    age_seconds  double precision,
    slo_seconds  integer     NOT NULL,
    status       text        NOT NULL
                 CHECK (status IN ('ok', 'warn', 'stale', 'unknown')),
    clock        text        NOT NULL DEFAULT 'live',
    as_of        timestamptz NOT NULL,
    computed_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS serving.dq_runs (
    run_ts            timestamptz PRIMARY KEY,
    status            text        NOT NULL,
    critical_failures integer     NOT NULL DEFAULT 0,
    warning_failures  integer     NOT NULL DEFAULT 0,
    commit_sha        text,
    warning_only      boolean     NOT NULL DEFAULT false,
    report_path       text,
    loaded_at         timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS serving.dq_results (
    run_ts     timestamptz NOT NULL,
    suite      text        NOT NULL,
    dataset    text        NOT NULL,
    rule_id    text        NOT NULL,
    severity   text        NOT NULL,
    status     text        NOT NULL,
    detail     text,
    observed   jsonb,
    expected   text,
    PRIMARY KEY (run_ts, suite, rule_id)
);

CREATE INDEX IF NOT EXISTS dq_results_severity_idx
    ON serving.dq_results (severity, status);

CREATE TABLE IF NOT EXISTS serving.catalog_datasets (
    id               text        PRIMARY KEY,
    name             text        NOT NULL,
    layer            text        NOT NULL,
    domain           text        NOT NULL,
    kind             text        NOT NULL CHECK (kind IN ('iceberg', 'postgres')),
    location         text        NOT NULL,
    description      text        NOT NULL,
    owner            text        NOT NULL,
    classification   text        NOT NULL,
    retention_days   integer     NOT NULL DEFAULT 0,
    refresh_schedule text,
    sla              text,
    license          text,
    contains_pii     boolean     NOT NULL DEFAULT false,
    tags             text[],
    schema_json      jsonb,
    updated_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS serving.model_metrics (
    model_name  text        NOT NULL,
    version     text        NOT NULL,
    alias       text,
    metrics     jsonb       NOT NULL DEFAULT '{}'::jsonb,
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (model_name, version)
);

CREATE TABLE IF NOT EXISTS serving.model_decisions (
    model_name         text        NOT NULL,
    decision_ts        timestamptz NOT NULL,
    champion_version   text,
    challenger_version text,
    decision           text        NOT NULL,
    reason             text,
    metrics            jsonb       NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (model_name, decision_ts)
);
