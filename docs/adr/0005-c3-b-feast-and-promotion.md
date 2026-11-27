# ADR 0005 - Feast online store and automatic promotion

## Status

Accepted for C3-B.

## Decision

- Use a Feast repository in `feature_repo/` with a PostgreSQL online store in a
  dedicated `feast` database on `postgres-ml`.
- Use Parquet offline sources generated from the frozen `mart_ml` snapshot and
  `serving.market_hourly`. This is the compatibility path for the local
  Iceberg/DuckDB setup and is recorded as a deliberate fallback.
- Add `feature_ts_epoch` to `market_features_1m` so online reads can compute
  feature age without a second timestamp lookup.
- Keep the pooled model as champion. Per-symbol E3 models are comparison-only.
- Promotion is automatic only after the existing gate passes; the old champion
  receives the `archived` alias and the decision is written to
  `serving.model_decisions`.
- Drift reports are persisted in `serving.drift_metrics`; a PSI above 0.2 on any
  of the top-5 model features triggers the training deployment.

## Consequences

- Online and offline feature definitions are explicit and testable.
- A new `feast` database and a Feast dependency are required.
- API and batch can fall back to the gold path when Feast is unavailable.
- The per-symbol experiment does not change production routing.

## Alternatives considered

- Direct Iceberg offline source: rejected for the first C3-B implementation
  because the local Feast/DuckDB combination is less predictable.
- Reusing the `prefect` database for Feast: rejected to avoid coupling
  orchestration metadata and online feature tables.
- Promoting per-symbol models automatically: rejected; the experiment is
  comparison-only and pooled wins on test MAE.
