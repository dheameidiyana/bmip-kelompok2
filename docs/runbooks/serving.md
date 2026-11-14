# Runbook: serving tier and Query API

Owner: Anin (W1-D). Scope: `serving.*`, `bmip-api`, `dashboard`.

## What can go wrong

| Symptom | Likely cause | First check | Action |
|---|---|---|---|
| `/v1/*` returns 401 | Missing or wrong `X-API-Key` | `curl -H "X-API-Key: $BMIP_API_KEY" ...` | Use the key from `.env` (`BMIP_API_KEY`); the dashboard uses it server-side |
| `/v1/*` returns 503 `api-key-not-configured` | `BMIP_API_KEY` empty in the container | `docker compose exec api printenv BMIP_API_KEY` | Set it in `.env`, recreate the container |
| `/health/ready` returns 503 | PostgreSQL **and** lake both unusable | body `checks` object | Restore Postgres or MinIO/Lakekeeper, see below |
| Range endpoints return `X-Data-Stale: true` | Lake path failed, response comes from PostgreSQL | `docker compose logs api | Select-String fallback` | Restore MinIO/Lakekeeper; the API recovers automatically |
| `bmip_api_fallback_total` keeps rising | MinIO/Lakekeeper down, or DuckDB attach failing | `docker compose logs api` | Fix storage; if DuckDB attach is the cause, set `LAKE_READER=pyiceberg` and restart |
| Freshness badge red | Data is older than 2× SLO (no ingestion running) | `/v1/freshness` `age_seconds` | Start ingestion or accept the honest stale state |
| Dashboard shows "belum ada model" | No champion registered (expected until W2-A) | `/v1/model/latest` | Nothing to fix; W2-A owns training |
| Dashboard empty charts | Selected window has no bars | `/v1/freshness` `data_ts` | Pick "Semua data" or the window around `data_ts` |
| `serving.*` empty | Loader never ran | `python scripts/serve_load.py --counts` | Run `python scripts/serve_load.py` |

## Checks

```powershell
# 1. containers
docker compose --env-file .env -f deploy/compose.base.yml -f deploy/compose.dev.yml ps

# 2. readiness (reports both paths)
curl -s http://localhost:8000/health/ready | ConvertFrom-Json

# 3. one authenticated read
curl -s -H "X-API-Key: $env:BMIP_API_KEY" http://localhost:8000/v1/market/latest

# 4. freshness
curl -s -H "X-API-Key: $env:BMIP_API_KEY" http://localhost:8000/v1/freshness

# 5. serving row counts
.\.venv\Scripts\python.exe scripts\serve_load.py --counts

# 6. logs (JSON lines)
docker compose --env-file .env -f deploy/compose.base.yml -f deploy/compose.dev.yml logs --tail 50 api
```

## Recovery

**Restart the API only**

```powershell
docker compose --env-file .env -f deploy/compose.base.yml -f deploy/compose.dev.yml restart api
```

**Reload serving from gold** (idempotent, safe to repeat)

```powershell
.\.venv\Scripts\python.exe scripts\serve_load.py
```

**MinIO down (fallback path)**

The API keeps serving ranges from `serving.market_hourly` /
`serving.sentiment_hourly` and marks `X-Data-Stale: true`. Restore MinIO, wait
for `/health/ready` to report `"lake": true`, then confirm
`X-Data-Stale: false` on one range query.

**DuckDB attach fails but MinIO is healthy**

The reader logs `duckdb could not attach the Iceberg catalog` and cools down
for 30 seconds. Set `LAKE_READER=pyiceberg` in `.env`, recreate the API, and
record the deviation (ARCHITECTURE R04). Both readers return the same shape.

## Contract notes

- Auth: `X-API-Key` on `/v1/*`. `/api` and `/health/*` stay public so the W1-A
  gate and the container healthcheck keep working.
- Errors: `application/problem+json` with `type`, `title`, `status`, `detail`,
  `instance`, `request_id`.
- Range caps: `serving_max_range_days` (31) and `serving_page_size_max` (1000).
- Pagination: `limit` + opaque `cursor`; the next page is strictly older than
  the cursor (keyset, never OFFSET).
- `X-Data-Stale` means "answered from PostgreSQL"; `freshness.status` means
  "data is older than its SLO". They are independent.
- `BMIP_AS_OF` switches freshness to a labelled replay clock (`clock: replay`).
