# Handoff W1-D - Anin

- Owner: Anin
- Branch: `slot/w1-d-anin`
- Handoff to: Dhea (W2-A)
- Last update: 2026-11-14
- Base: `dev` (`ef01ec5`, merge of PR W1-C)
- Code commits: `386760e` (serving + API + dashboard), `0df6000` (lake health +
  file cache), `cd9513a` (UTC chart labels), `a58f5d7` (Streamlit width API)
- Tag: `w1-d-ok`

## Status

- CP1: PASS — `/health/ready` green, three core endpoints return serving data,
  freshness computed.
- CP2: PASS — 14 canonical routes + 5 aliases in OpenAPI, T-13/T-34/T-36 pass,
  keyset pagination proven.
- CP3: PASS — MinIO stopped → 200 with `X-Data-Stale: true`, dashboard renders
  4 metrics + 2 filters + freshness badges, M1 gate green, gate W1-A..W1-C
  still green.

Gate M1: one trade and one post are visible from bronze → silver → gold →
serving → API → dashboard.

```
bronze.market_trade_raw   90,939     bronze.social_post_raw   2
silver.market_ohlcv_1m        61     silver.social_post       2
gold.mart_market               2     gold.mart_sentiment      1   gold.mart_ml 2
serving.market_hourly          2     serving.sentiment_hourly 1   serving.catalog_datasets 11
```

## Yang sudah jalan

### Serving tier

- `src/bmip/serving/schema.sql` creates `serving.*`: `market_hourly`,
  `market_latest`, `sentiment_hourly`, `predictions`, `freshness`, `dq_runs`,
  `dq_results`, `catalog_datasets`, `model_metrics`, `model_decisions`.
  `serving.volatility` is a view over `market_hourly` (one write path; ADR-0003).
- `bmip.serving.loader.load_serving()` reads `gold.mart_market` and
  `gold.mart_sentiment` with the **`svc-api`** credentials, upserts by natural
  key, imports `evidence/dq/dq_report.json`, publishes `catalog/datasets.yml`
  (11 datasets with owner, classification, retention, SLA, live schema), and
  refreshes `serving.freshness`.
- Idempotent: `scripts/serve_load.py` twice returns the same counts and the same
  `logical_hash` (`evidence/serving/loader-idempotence_*.json`).
- Wired into the pipeline: `scripts/build_gold.py` and the Prefect
  `transform-gold` flow now run `publish-serving` after `publish-gold`.

### Query API (`src/bmip/api`, `uvicorn bmip.api.main:create_app --factory`)

- 14 canonical routes (workplan) + 5 ARCHITECTURE aliases; `contracts/openapi.json`
  is committed and a unit test fails if a route is added without updating it.
- `X-API-Key` on `/v1/*` (constant-time compare); `/api` and `/health/*` stay
  public so `scripts/e2e_smoke.py` and the container healthcheck keep working.
- Range queries read Iceberg through DuckDB (`ATTACH` + `lake.gold.*`) and fall
  back to PostgreSQL when the lake fails, setting `X-Data-Stale: true` and
  `meta.source=serving`. `LAKE_READER=pyiceberg` selects the second reader.
- Keyset pagination (`limit` + opaque `cursor`), 31-day and 1,000-row caps,
  RFC 7807 errors with `request_id`, `X-Request-ID` on every response.
- Freshness is recomputed per request from `data_ts` + SLO; `BMIP_AS_OF` switches
  to a replay clock that is echoed as `clock: "replay"`.
- `/metrics` exposes request counts, latency sum, error count, and
  `bmip_api_fallback_total` (W2-B extends the panel).
- `POST /v1/predict` returns `200 status="not_available"` while no champion
  exists (decision 1), `422` for a malformed body, and records out-of-range
  features as `status="error"` in `serving.predictions`.

### Dashboard (`src/bmip/dashboard`)

- Streamlit v1 at `http://localhost:8501`, four business metrics (last price,
  last-hour realized volatility, sentiment score, prediction = "belum ada
  model"), two time filters (preset + explicit dates), a freshness badge per
  metric, and a quality/freshness expander. It reads **only** the API.
- Chart axes are labelled UTC; empty windows show an explicit explanation
  instead of a blank chart.

### Environment

- `deploy/api/Dockerfile` and `deploy/dashboard/Dockerfile` use `python:3.11-slim`
  (pyarrow has no musl wheel), bake the DuckDB `iceberg`/`httpfs` extensions, and
  use BuildKit pip cache mounts.
- Compose adds the `dashboard` service, api env for internal endpoints
  (`minio:9000`, `lakekeeper:8181`, `postgres-core:5432`), and Traefik routes
  `/v1`, `/api`, `/health`, `/metrics`, `/docs`, `/openapi.json` to the API and
  `/` to the dashboard.
- `.env.example`, `deploy/env/ci.env.example`, and `scripts/gen_env.py` carry the
  new keys; `BMIP_API_KEY` is generated as a random secret.

## Angka dan konteks data

- The replay window is real Binance Vision data for **2026-11-10 13:00-14:00
  UTC** (90,936 trades) plus the W1-A fixture (3 trades, 14:00) and two fixture
  posts at 14:05/14:06. `silver.market_ohlcv_1m` has all 60 bars of hour 13 plus
  one bar at 14:00.
- `gold.mart_market` has 2 hourly rows (13:00 and 14:00), `mart_sentiment` 1 row
  (14:00), `mart_ml` 2 rows. `realized_vol_1h` for 14:00 is null because that
  hour has a single minute bar; that is arithmetic, not a bug.
- Freshness is **stale** in the evidence because the replay data is four days
  old. In a live demo the badge turns green; nothing in the API fakes it.
- 143 tests pass; `ruff` clean; `docker compose config` valid for `dev` and
  `two-node`.

## Yang belum jalan / stub

| Item | Status | Owner |
|---|---|---|
| Champion model, MLflow registry, promotion gate | `serving.model_metrics` empty; predict returns `not_available` | W2-A |
| `serving.predictions` scoring rows | only the T-36 validation row exists (`status=error`) | W2-A |
| `api-2`, load balancing, circuit breaker | `compose.two-node.yml` still stubs `api-2` without env | C3-A |
| TLS, RBAC roles, Tailscale ACL | `/v1` uses one service key; no TLS yet | W2-C |
| Full Prometheus/Grafana metrics | `/metrics` is the minimal W1-D surface | W2-B |
| Hermetic screenshot | captured with Playwright + installed Edge (see evidence); no CI job for it | W2-D/C3-D |
| Prefect worker | not permanent (same as W1-B/W1-C); `publish-serving` ran inside `build_gold.py` | ops |

Known observations:

- `silver.market_trades` holds 86,371 of 90,936 trades while every minute of
  hour 13 still has a bar; the stream processor holds back the last two minutes
  by design (W1-B watermark) and the replay was stopped after the idle timeout.
  Not a W1-D issue.
- One record was quarantined during the replay (`late_beyond_window`), which is
  the expected late-event path, not data loss.
- `serving.predictions` now has one row from the T-36 out-of-range case
  (`status=error`, `model_version=none`). It is evidence, not a prediction.

## Cara menjalankan

```powershell
# 1. infrastructure + freshness of the serving tier
docker compose --env-file .env -f deploy/compose.base.yml -f deploy/compose.dev.yml up -d --build
python scripts/serve_load.py --counts

# 2. gates
python -m pytest
python -m ruff check src scripts tests deploy
python scripts/quality.py
python scripts/e2e_smoke.py      # gate W1-A
python scripts/m1_smoke.py       # gate M1 (W1-D)

# 3. evidence
python scripts/api_evidence.py --steps smoke,routes,auth,invalid,predict,pagination,idempotence,reconcile
python scripts/api_evidence.py --steps pagination,stale --with-faults
```

Pipeline path (same flow as Prefect): `python scripts/build_gold.py` builds
silver social, runs dbt, enforces both quality gates, publishes gold, and loads
serving.

API examples:

```powershell
$key = (Select-String -Path .env -Pattern '^BMIP_API_KEY=').Line.Split('=',2)[1]
curl.exe -s -H "X-API-Key: $key" "http://localhost:8000/v1/market/latest"
curl.exe -s -H "X-API-Key: $key" "http://localhost:8000/v1/freshness"
curl.exe -s -H "X-API-Key: $key" "http://localhost:8000/v1/market/ohlc?symbol=BTCUSDT&limit=2"
```

## Kegagalan yang diketahui

| Gejala | Penyebab | Perbaikan |
|---|---|---|
| API crash: `missing required environment variable: POSTGRES_PASSWORD` | `Settings.from_env` required the password even when a full DSN is injected | DSN is now used directly; the password is only required for host tools |
| `/v1/*` 500 `InFailedSqlTransaction` before the first load | one failed statement aborted the shared transaction | serving reads tolerate a missing schema and the API session uses autocommit |
| Range query answers from MinIO after it was stopped | DuckDB 1.5 external file cache | `SET enable_external_file_cache = false` in the reader |
| `/health/ready` says lake=true while MinIO is down | health only ran `SELECT 1` | health now reads one row from `gold.mart_market` |
| Dashboard crash: `No module named streamlit` | runtime installed `bmip` without the `dashboard` extra | runtime installs `bmip[dashboard]` |
| Docker build fails `pyarrow` | alpine base has no musl wheel | `python:3.11-slim` |
| Lake reads work in the container but not on the host | Iceberg metadata URLs use `minio:9000`, which only resolves inside the compose network | test the lake path through the container, not a host uvicorn |
| First lake query can exceed 5 s on a cold worker | DuckDB attach + metadata refresh | evidence warms the path; a longer `LAKE_QUERY_TIMEOUT_SECONDS` is the knob |

## Langkah berikutnya untuk Dhea (W2-A)

1. Register a champion: insert a row in `serving.model_metrics`
   (`model_name='volatility_model'`, `alias='champion'`) and set
   `app.state.predictor` in the API (a callable returning
   `{"predicted_rv_next_1h": float}`). No route change is needed.
2. Write scored rows to `serving.predictions` with the existing primary key
   `(symbol, window_start, model_version)`; keep `status` in `ok|error`.
3. `/v1/model/latest` already returns `status="available"` once a champion row
   exists; the dashboard flips from "belum ada model" automatically.
4. Keep the created T-36 semantics: malformed → 422, out-of-range → 200
   `status="error"` + row, valid without champion → 200 `not_available`.
5. Final T-36/T-21 evidence replaces the W1-D validation evidence; the alias
   route list is in `docs/adr/0003-w1-d-serving-and-api.md`.
6. `serving.dq_runs`/`dq_results` are loaded from `evidence/dq/dq_report.json`
   by the loader; W2-B can read them for the quality panel instead of parsing
   the file.

## Evidence

| ID | File | Isi |
| --- | --- | --- |
| CP1 | `evidence/api/smoke_20261114T0239.txt` | Health, 10 endpoints, market row + freshness + request id |
| ROUTES | `evidence/api/routes_20261114T0239.txt` | 14 canonical routes, 5 aliases, OpenAPI table |
| T-13 | `evidence/security/api-401.txt` | No key / wrong key → 401 problem+json; `/api` stays public |
| T-14 | `evidence/tests/T14.txt` | 2 live pages (limit=1) and 11 pages over 1,002 rows, no duplicates, stable cursor |
| T-15 | `evidence/tests/T15.txt` | MinIO stopped → 200 + `X-Data-Stale: true` from serving; recovery → `false` |
| T-34 | `evidence/api/T34.json` | Unknown symbol, inverted range, limit caps, broken cursor, bad datetime, missing range |
| T-36 | `evidence/ml/T36.json` | Malformed → 422, out-of-range → recorded error, valid → `not_available` (W1-D validation) |
| IDEM | `evidence/serving/loader-idempotence_20261114T0239.json` | Two loads, identical counts and logical hash |
| T-37 | `evidence/dashboard/reconciliation-draft.json` | API vs serving SQL vs Iceberg gold, 2/2 rows, 0 mismatches (draft) |
| M1 | `evidence/e2e/M1_20261114T0252.txt` | Bronze → silver → gold → serving → API → dashboard |
| DASH | `evidence/dashboards/streamlit_20261114T0253.png` | 4 metrics, 2 filters, freshness badges, "belum ada model" |

The dashboard screenshot is reproducible with Playwright against the installed
Edge browser (no browser download):

```python
page.goto("http://localhost:8501")
page.get_by_text("Semua data", exact=True).click()
page.screenshot(path="evidence/dashboards/streamlit_<ts>.png", full_page=True)
```

The default window is 24 hours; the replay data is from 2026-11-10, so the
screenshot selects "Semua data" to show the charts. The freshness badges stay
red in the screenshot because the data really is four days old.
