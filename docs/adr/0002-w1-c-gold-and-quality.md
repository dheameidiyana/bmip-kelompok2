# ADR-002: Gold publish path and the W1-C quality gate

- Status: Accepted
- Date: 2026-11-14
- Owner: Vio (W1-C)
- Supersedes: none
- Related: ARCHITECTURE §9.3, §9.4, §13.3, §13.4; ADR-001

## Context

W1-B left a dbt project that materialised one silver view inside DuckDB. W1-C had
to add three gold marts, a Great Expectations gate that blocks promotion, and a
merge policy that survives replays. The lakehouse must end up with real Iceberg
tables, not local DuckDB artefacts.

## Decisions

### 1. dbt computes in DuckDB, PyIceberg commits the partition

`mart_*` models materialise as tables in the dbt DuckDB target. `GoldWriter`
reads them back as Arrow and overwrites one Iceberg partition per `event_date`.

Why: DuckDB 1.5 writes Iceberg, but partitioned overwrite is still the reliable
path through PyIceberg. This is the same split ARCHITECTURE §9.3 describes
("DuckDB computes, PyIceberg commits") and the same pattern W1-B used for
`silver.market_ohlcv_1m`.

### 2. dbt schemas are verbatim, not prefixed

`dbt/macros/generate_schema_name.sql` returns the custom schema unchanged, so
models land in `staging`, `intermediate`, `silver`, and `gold` instead of
`main_staging`, `main_gold`, and so on.

Why: the publisher, the tests, and any future serving loader must address
`gold.mart_market` by a stable name. The default dbt behaviour of prefixing the
target schema made every path target-dependent.

### 3. The gold gate checks the candidate, not the published copy

`scripts/build_gold.py` and `transform_gold_flow` run the gold suites against
the DuckDB marts plus `silver.market_ohlcv_1m` from Iceberg. Publishing happens
only after the gate passes. `scripts/quality.py` runs the same suites again
against the published Iceberg tables for evidence.

Why: on a first run the Iceberg gold tables are empty, so gating on them would
always fail. Gating the candidate is the actual promotion decision; verifying
the published copy proves the publish step did not corrupt anything.

### 4. Freshness for gold means "not behind silver"

The `gold_market` suite uses a `lag` rule (gold `window_start` versus silver
`window_start`, 90 minutes). Wall-clock staleness is measured by
`bmip_freshness_seconds` and alerted in W2-B.

Why: a replay demo deliberately processes historical data, so a wall-clock
freshness rule would fail for a correct pipeline. The batch SLO that gold owns
is "gold is at most 90 minutes behind silver". T-24 already proves the
end-to-end live freshness of the market path.

### 5. Duplicate rate is a warning and counts extra rows

`duplicate_rate` is `(rows - unique_rows) / rows` on the business key. Above 2%
it fails as a `warning`, so the checkpoint records it and the pipeline
continues. The critical `unique` rule still protects the table itself because
the transform deduplicates before writing.

Why: T-12 requires "2% duplicate rate is a warning, not a blocker". Counting
extra rows (not both copies) makes the 2% threshold match the workplan wording.

### 6. Service credentials follow least privilege

- `svc-dbt` writes `gold.db` (it already owned gold writes).
- `svc-process` reads `gold.db` for the gate; its policy gained read-only gold.
- `svc-api` keeps read-only gold for W1-D.

Why: the quality gate reads silver and gold in one checkpoint, and no existing
service could do both. Granting gold read to the transform identity is smaller
than granting silver read to the API identity.

### 7. The schema-evolution probe is disposable

T-31 creates `silver.schema_evolution_probe_<timestamp>`, appends one row,
adds a nullable column, appends another row, reads the old snapshot, and drops
the table. The name and location include the run timestamp because Lakekeeper
refuses to create a table over leftover files.

Why: testing schema evolution on `silver.social_post` would mutate the demo
data. A disposable probe proves the same Iceberg property without touching the
pipeline.

## Consequences

- A gold publish is idempotent per `event_date`; reruns replace partitions.
- The gate can run without MinIO gold writes, which keeps `make quality`
  usable during local development.
- Replay windows that are days old still pass the gold gate, because the lag
  rule compares two layers instead of comparing to the clock.
- A wall-clock freshness regression will be caught by W2-B alerting, not by
  this gate; that split is explicit in the suite definitions.
- `silver.market_ohlcv_1m` and its writer are untouched, so W1-B's T05 and T24
  evidence stays valid.
