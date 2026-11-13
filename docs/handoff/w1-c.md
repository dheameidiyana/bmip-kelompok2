# Handoff W1-C - Vio

- Owner: Vio
- Branch: `slot/w1-c-vio`
- Handoff to: Anin (W1-D)
- Last update: 2026-11-14
- Base: `feat/silver-lois` (`fdaf360`), the branch that carries W1-A and W1-B

## Status

- CP1: PASS
- CP2: PASS
- CP3: PASS
- Tag: `w1-c-ok`

Gate: silver social is pseudonymized and scored, the three gold marts are
published to Iceberg with partition overwrite, the Great Expectations checkpoint
blocks gold on a critical failure and records a warning otherwise, and
`make e2e-smoke` plus `make lint` are green.

## Yang sudah jalan

### Silver social dan sentiment

- `bmip.transform.social` parses bronze rows, drops raw URI, DID, handle, and
  display name, and stores `post_key` and `author_key` as salted
  HMAC-SHA256 (ADR-011).
- VADER scores every post (`compound`, `pos/neu/neg`, label,
  `sentiment_model_version`). Empty text is rejected, not scored.
- `silver.social_post` and `silver.social_sentiment` are Iceberg tables
  partitioned by `event_date`. Writes merge on `post_key` inside the partition
  and keep the newest `ingest_ts`, so a replay never duplicates a post.
- `python -m bmip.transform.social_pipeline` is wired into `make gold` and the
  Prefect `transform-gold` flow as the `build-silver-social` task.

### Gold marts

- `dbt/models/intermediate`: `int_market_ohlcv_1h` (hourly OHLC, log return,
  realized volatility, recursive EWMA over 24 hours, per-hour `source`),
  `int_market_features_1h` (trailing 5/15/60-minute features at the hour
  boundary), `int_social_sentiment_1h` (hourly aggregate with explicit empty
  hours).
- `dbt/models/marts`: `mart_market`, `mart_sentiment`, `mart_ml`, documented in
  `dbt/models/marts/schema.yml`. `mart_ml` exposes both naming conventions:
  `window_start`/`event_hour` and `feature_snapshot_id`/`snapshot_id` hold the
  same values, because ARCHITECTURE §9.4 and workplan W1-C item 6 disagree.
- `mart_ml` keeps the point-in-time invariant: every feature comes from bars
  strictly before `window_start`; `label_start = window_start` and
  `label_end = window_start + 1 hour`. `dq_status` is `pass` only when
  `ret_60m`, `rv_60m`, and the label are all present.
- `bmip.transform.gold.GoldWriter` reads the dbt DuckDB marts as Arrow and
  overwrites one Iceberg partition per `event_date`. It publishes with the
  `svc-dbt` credentials; the transform gate reads with `svc-process`.

### Quality gate

- `gx/suites/*.yml` hold the rule catalog: critical rules for uniqueness, OHLC
  bounds, score range, label leakage, and PII columns; warning rules for
  duplicate rate and label coverage.
- `bmip.quality.runner` runs Great Expectations 1.x expectations plus the small
  domain checks GX cannot express (freshness, hourly gap, lag against silver,
  duplicate rate, PII columns).
- `scripts/quality.py` writes `evidence/dq/dq_report.json`; a critical failure
  exits non-zero. `--warning-only` keeps the run alive and records the override
  in the report.
- Order in `scripts/build_gold.py` and `transform_gold_flow`: silver build →
  silver gate → gold build → gold gate (against the DuckDB candidate) →
  publish. Bad silver data never reaches `gold.mart_*` in the lakehouse.

### Operational targets

| Target | Command |
| --- | --- |
| `make quality` | `python scripts/quality.py` |
| `make gold` | `python scripts/build_gold.py` |
| `make evidence-w1c` | `python scripts/w1c_evidence.py` |
| Offline dbt + leakage test | `python -m pytest tests/integration -q` |
| Prefect deployments | `transform-gold` (hourly at :50), `backfill-gold` |

On this Windows machine GNU Make is not installed. Use the venv Python
commands above directly, or `.\\scripts\\make.ps1 <target>` after installing
make.

## Angka pada handoff ini

| Dataset | Rows |
| --- | --- |
| `bronze.market_trade_raw` | 304,984 + 5 from the first probe batch |
| `silver.market_trades` | 282,000 |
| `silver.market_ohlcv_1m` | 166 |
| `silver.social_post` | 2 |
| `silver.social_sentiment` | 2 |
| `gold.mart_market` | 3 (14:00, 15:00, 16:00 UTC on 2026-11-10) |
| `gold.mart_sentiment` | 1 (14:00 UTC on 2026-11-10) |
| `gold.mart_ml` | 3 (15:00 pass-history warn, 16:00 pass, 17:00 unlabelled) |

The replay window is real Binance Vision data for 2026-11-10 14:00-17:00 UTC,
cut by `scripts/make_replay_window.py`. Social posts are the W1-A fixture,
which has two posts at 14:05 and 14:06.

## Yang belum jalan / stub

- **Replay backlog.** 22,984 of 304,984 trades are still in `market.trades`
  (consumer group `ohlcv-w1c`). The processor sustains roughly 65 trades/s here
  because `SilverWriter.recompute_ohlcv` rescans the whole `event_date`
  partition for every micro-batch. Finishing the backlog does not change the
  mart shapes, only the number of minute bars. Fixing the scan is W2-D
  benchmark work; `silver.py` was left untouched so T05/T24 stay valid.
- **One sentiment hour.** The fixture only has posts at 14:05 and 14:06, so
  `mart_sentiment` has one row. Do not synthesise posts. For a richer demo,
  harvest live Bluesky (`SOCIAL_FEED=bluesky`) or add a real replay window.
- **Alert delivery for T-11.** The blocking gate is proven; Telegram delivery
  and the runbook are W2-B scope.
- **Prefect worker.** Not permanent, same as W1-B: the pool is `NOT_READY` when
  the worker stops. Run `python -m prefect worker start -p local-process`
  before relying on the schedule. `transform-gold` itself was executed once
  through the worker and is evidenced.
- **Serving, API, dashboard** are W1-D.
- **PR dan review.** `slot/w1-c-vio` belum dibuka sebagai PR ke `dev`; butuh satu
  reviewer (Lois atau Anin) sebelum W1-D mulai. W1-B juga belum di-merge ke `dev`
  dan belum punya tag `w1-b-ok`; W1-C karena itu dimulai dari
  `feat/silver-lois`, bukan dari tag.
- **Issue W1-C** belum dibuat di GitHub; tidak ada kredensial GitHub di mesin ini.

## Cara menjalankan

```powershell
# 1. infrastructure
docker compose --env-file .env -f deploy/compose.base.yml -f deploy/compose.dev.yml up -d --build
docker compose --env-file .env -f deploy/compose.base.yml -f deploy/compose.dev.yml --profile bootstrap run --rm minio-init
docker compose --env-file .env -f deploy/compose.base.yml -f deploy/compose.dev.yml --profile bootstrap run --rm lakekeeper-bootstrap

# 2. real market window + fixture posts
python scripts/make_replay_window.py --day 2026-11-10 --start 2026-11-10T14:00:00Z --end 2026-11-10T17:00:00Z --output data/replay/market_20261110T14-17.jsonl
python -m bmip.ingestion.cli market --replay data/replay/market_20261110T14-17.jsonl --max-records 400000
python -m bmip.ingestion.cli social --replay tests/fixtures/bluesky_posts.json

# 3. silver market from the stream
python -m bmip.transform.cli stream --once --group ohlcv-w1c --idle-timeout 20

# 4. silver social -> gates -> gold
python scripts/build_gold.py

# 5. verify the published tables and refresh the report
python scripts/quality.py

# 6. gates required by the workplan
python -m pytest
python scripts/e2e_smoke.py

# 7. a range backfill (recomputes marts, republishes only these hours)
python scripts/build_gold.py --start 2026-11-10T15:00:00Z --end 2026-11-10T16:00:00Z
```

Prefect path (same flow, scheduled at :50 every hour):

```powershell
python scripts/prefect_bootstrap.py
python -m prefect deployment run "transform-gold/transform-gold"
python -m prefect worker start -p local-process --run-once
```

## Kegagalan yang diketahui

| Gejala | Penyebab dugaan | Workaround |
| --- | --- | --- |
| Processor drains ~65 trades/s | `recompute_ohlcv` scans the full `event_date` partition per batch | Run it in the background; the backlog is a throughput item, not a correctness item |
| `dbt build` fails with `main_gold` schema | dbt's default `generate_schema_name` prefixes the target schema | `dbt/macros/generate_schema_name.sql` now returns the custom schema verbatim |
| `Can't open a connection ... different configuration` | dbt keeps the DuckDB file open read-write | Read the dbt target read-write, as `GoldWriter.publish_from_duckdb` does |
| `Access Denied` writing `warehouse/gold.db` | `svc-process` had no gold write | Gold publish uses `svc-dbt`; `svc-process` got read-only gold for the gate |
| `InvalidLocation ... tabular locations have to be empty` | A previous T-31 run left files | The probe table name and location include the run timestamp |
| GX pretty-print crashes on Windows | `rich` writes an emoji to cp1252 | Set `PYTHONIOENCODING=utf-8` |
| A range backfill deleted the rest of the day | Marts are partitioned by day; overwriting with only the requested hours drops the rest | `publish_arrow(start=..., end=...)` keeps rows outside the range before the overwrite |
| `e2e-smoke` failed on a clean stack | The first fixture replay inserts rows, so before/after counts differ | The gate now warms up both fixtures before measuring |

## Langkah berikutnya untuk Anin (W1-D)

1. Read gold from Iceberg with the `svc-api` credentials: `gold.mart_market`,
   `gold.mart_sentiment`, `gold.mart_ml`. The `api` policy already allows
   `GetObject` on `warehouse/gold.db/*`.
2. Use `dbt/models/marts/schema.yml` as the column contract. `mart_ml` columns
   are the model input; `feature_snapshot_id` (alias `snapshot_id`) defaults to
   `dev`, override it with `--vars '{feature_snapshot_id: <id>}'` when training.
   `window_start` and `event_hour` are the same column.
3. Empty sentiment hours are explicit: `post_count = 0` and null shares. Do not
   treat null as missing data.
4. Freshness: `gold.mart_market` must stay within 90 minutes of
   `silver.market_ohlcv_1m` (the `lag` rule). Wall-clock staleness is the
   `bmip_freshness_seconds` metric, owned by W2-B.
5. Keep `make quality` green after the serving loader is added; the gold suites
   read the published tables.
6. Do not change `silver.market_ohlcv_1m` without rerunning
   `scripts/w1b_evidence.py`; T05 and T24 depend on it.

## Evidence

| ID | File | Isi |
| --- | --- | --- |
| T-03 | `evidence/tests/T03.txt` | Rewriting the same post leaves the silver count unchanged |
| T-09 | `evidence/tests/T09.txt` | Two builds; a future price spike does not move earlier features |
| T-10 | `evidence/tests/T10.txt` | VADER scores stay in [-1, 1] |
| T-11 | `evidence/tests/T11.txt` | Null `trade_id` blocks the gate |
| T-12 | `evidence/tests/T12.txt` | 2.9% duplicate rate is a warning, pipeline continues |
| T-31 | `evidence/storage/T31.txt` | New nullable column readable; old snapshot still opens |
| T-32 | `evidence/storage/T32.json` | Corrected source changes the right hour |
| T-33 | `evidence/storage/T33.json` | Two reruns produce the same logical hashes |
| DQ | `evidence/dq/dq_report.json` | Full checkpoint result |
| DQ | `evidence/dq/mart-counts_20261113T2223.csv` | Rows per mart |
| PII | `evidence/security/pii-columns_20261113T2223.txt` | No raw URI, DID, or handle in silver |
| dbt | `evidence/dbt/docs.png` | dbt docs page for `mart_ml`, with columns and descriptions |
| dbt | `evidence/dbt/docs_20261113T2230.txt` | Catalog summary generated from `catalog.json` |
| E2E | `evidence/e2e/SMOKE-W1A_20261113T2226_3742fe9.txt` | W1-A smoke gate: health, replay, bronze counts, ledger, idempotence |
| Prefect | `evidence/deploy/prefect-gold_20261113T2229_3742fe9.json` | `transform-gold` flow run `Completed` through the worker |
| Sum | `evidence/w1c/SUMMARY_20261113T2223.json` | One-line result per test |

All files are generated by `python scripts/w1c_evidence.py` and
`python scripts/quality.py`; none are hand-written.
