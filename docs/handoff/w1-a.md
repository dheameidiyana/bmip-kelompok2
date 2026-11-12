# Handoff W1-A - Dhea

- Owner: Dhea
- Branch: `slot/w1-a-dhea`
- Handoff to: Lois (W1-B)
- Last update: 2026-11-11

## Status

- CP1: PASS
- CP2: PASS
- CP3: PASS
- Tag: `w1-a-ok` (dipindah ke commit evidence final)

Gate: trade and post are in bronze in replay mode; `T-26` shows a second
identical replay is skipped and bronze counts stay unchanged.

## Yang sudah jalan

`make dev-up` starts six long-running services, bootstraps storage, and exits 0:

| Service | Image | Host port | Health |
| --- | --- | --- | --- |
| traefik | `traefik:v3.7.18` | 8080, 8082 | `/ping` |
| redpanda | `redpandadata/redpanda:v26.2.6` | 19092, 9644 | `rpk cluster health` |
| postgres-core | `postgres:16.15-alpine` | 5433 | `pg_isready` |
| minio | `elestio/minio` digest pinned | 9000, 9001 | `/minio/health/live` |
| lakekeeper | `quay.io/lakekeeper/catalog` digest pinned | 8181 | `/health` |
| api | `bmip/api:dev` (placeholder) | 8000 | `/health/ready` |

Bootstrap creates:

- buckets `lakehouse`, `artifacts`, `backups`, `docs`, `quarantine`
- MinIO users `svc-ingest`, `svc-process`, `svc-dbt`, `svc-ml`, `svc-api`,
  `svc-backup`, `svc-docs` with per-service policies
- Lakekeeper warehouse `lakehouse` and namespaces `bronze`, `silver`, `gold`
- PostgreSQL schema `ops` with `ops.batch_runs` and `ops.social_watermark`
- PostgreSQL database `lakekeeper` owned by role `lakekeeper`

Ingestion (CP2) now works end to end:

- Versioned contracts `contracts/market_trade.v1.json` and
  `contracts/social_post.v1.json`, enforced by pydantic validators. Invalid
  records go to the `quarantine` bucket as JSONL.
- Binance `aggTrade` producer over WebSocket plus a Binance Vision/download
  replay path. The replay fixture produces the same `market.trades` messages.
- Bluesky search harvester with a replay fixture and a persisted watermark.
  Live requests retry `429`/`5xx`/transport errors up to five times with
  exponential backoff (1-60s), honor `Retry-After`, and cache only successful
  pages. `social --live --interval 3600` repeats the harvest hourly.
- Social records carry both `created_at` and required `ingest_ts`; the contract
  rejects `ingest_ts` that is more than one second before `created_at`.
- Append-only PyIceberg tables `bronze.market_trade_raw` and
  `bronze.social_post_raw`, both partitioned by `event_date`. Social bronze also
  stores `ingest_ts`.
- `ops.batch_runs` records deterministic batch ids, checksums, row counts, and
  terminal status. Replaying identical data returns `skipped_identical` without
  appending duplicate bronze rows.
- `make e2e-smoke` runs the W1-A scope: health endpoints, market/social replay,
  bronze counts, ledger rows, and replay idempotence.

## Yang belum jalan / stub

- The full bronze to silver to gold to API to dashboard gate is M1/W1-D work.
  W1-A's `make e2e-smoke` stops at bronze and the ledger.
- Live Binance and Bluesky modes are implemented but not part of the CP evidence.
  Replay is the reproducible path; live needs outbound network access.
- The API is a placeholder for W1-D. Four-node profiles and the observability
  stack are deferred to Cycle 3.
- `make transform`, `make quality`, `make test-cov`, and `make benchmark` remain
  stubs owned by later slots.

## Cara menjalankan

Windows (recommended, handles Git's `sh` path for GNU Make):

```powershell
.\scripts\make.ps1 setup
.\scripts\make.ps1 secrets
.\scripts\make.ps1 dev-up
.\scripts\make.ps1 doctor
.\scripts\make.ps1 ingest-once
.\scripts\make.ps1 replay
.\scripts\make.ps1 evidence-cp2
.\scripts\make.ps1 evidence-cp3
.\scripts\make.ps1 e2e-smoke
.\scripts\make.ps1 dev-down
```

`make ingest-once` replays one market batch and one social batch and refreshes
the CP2 evidence. `make replay` skips evidence generation. `make ingest-live`
reads a small number of live records; it needs outbound access to Binance and
Bluesky.

Harvest sosial per jam (Ctrl+C berhenti bersih):

```powershell
.venv\Scripts\python.exe -m bmip.ingestion.cli social --live --interval 3600
```

Linux/macOS or a shell where `make` and `/bin/sh` are native:

```bash
make setup
make secrets
make dev-up
make doctor
make ingest-once
make evidence-cp3
make dev-down
```

`make reset` removes named volumes and rebuilds from scratch. It keeps `.env`, so
local passwords survive the reset.

## Evidence

Final evidence for commit `937a0ef`:

CP1:

- `evidence/deploy/health_20261111T1404_937a0ef.md`
- `evidence/deploy/compose-config_20261111T1406_937a0ef.yml`

CP2:

- `evidence/tests/T01.json` — valid social post passes the contract
- `evidence/tests/T02.json` — negative price is rejected at `$.price`
- `evidence/ingestion/counts_20261111T1405.csv` — bronze row counts and timestamp range
- `evidence/batch/ledger_20261111T1405.csv` — `ops.batch_runs` rows with checksums

CP3:

- `evidence/batch/T26.json` — both replays return `skipped_identical`; counts
  are equal before and after
- `evidence/ingestion/replay_20261111T1405.txt` — full output of two replay runs

E2E-W1A:

- `evidence/e2e/SMOKE-W1A_20261111T1406_937a0ef.txt` — health endpoints, replay,
  bronze counts, ledger rows, and idempotence

`make doctor` refreshes the health file. `make compose-config` refreshes the
compose file. `make evidence-cp2` and `make evidence-cp3` refresh the CP2/CP3
files. `make e2e-smoke` refreshes the E2E file. All are generated, not
hand-written.

Secret check: `.env` is not tracked, `.env.example` contains every key used by
`.env`, and no `.env` password value appears in tracked files.

## Decisions and deviations

See `docs/adr/0001-w1-a-foundation.md`.

Key points:

- MinIO comes from the `elestio/minio` mirror because the upstream images are not
  pullable here. The image is pinned by digest and bundles `mc`.
- Dev-only: `minio`, `postgres-core`, `lakekeeper`, and `redpanda` join the
  `edge` network so Docker Desktop publishes their ports. The `data` network
  remains internal.
- PostgreSQL is published on host `5433` because `5432` is already in use.
- Lakekeeper uses `allowall` authorization in dev and is bootstrapped explicitly.
- Bronze tables have explicit locations under
  `s3://lakehouse/warehouse/bronze.db/`. Without an explicit location Lakekeeper
  uses a per-table UUID path, which makes the MinIO policy needlessly broad.
- Social bronze moved from `ingest_date` to event-time `event_date` plus
  `ingest_ts`, matching the market table. The dev stack must be reset once when
  moving from an older schema because Iceberg partition specs are immutable.
- Host-side PyIceberg bypasses Lakekeeper remote signing. The warehouse endpoint
  (`host.docker.internal:9000`) is only reachable from containers, so the bronze
  writer replaces the table IO with the host endpoint (`localhost:9000`) while
  metadata commits still go through Lakekeeper.
- `make bootstrap` recreates MinIO policies on every run so policy changes are
  not silently skipped.

## Handoff to W1-B

1. Start from tag `w1-a-ok` or the merged `dev` branch.
2. Read `evidence/batch/T26.json` and the ledger to see the batch id and
   checksum conventions W1-B must preserve.
3. Consume `market.trades` from Redpanda; bronze rows already carry `batch_id`,
   `payload_hash`, `event_date`/`event_ts`, and `ingest_ts`.
4. Keep `make ci` green before opening the W1-B PR.

## Notes for other slots

- W1-B can use `REDPANDA_BROKERS=localhost:19092` from the host and
  `redpanda:9092` inside the compose network.
- W1-B/C/D can use the `lakehouse` warehouse. Resolve its UUID from
  `GET http://localhost:8181/management/v1/warehouse` before calling catalog
  paths.
- Bronze tables live under `s3://lakehouse/warehouse/bronze.db/`; read with the
  `svc-process` credentials. Iceberg metadata is committed through Lakekeeper.
- Use `host.docker.internal:9000` inside containers and `localhost:9000` from
  the host. Server-side remote signing is enabled by Lakekeeper, so a host
  client must override the table IO (see `BronzeWriter._table`).
- W1-D owns the real API. Replace `deploy/api/server.py` without changing the
  compose service name or health paths.
- Do not commit `.env`. Run `make secrets` on a fresh clone.
