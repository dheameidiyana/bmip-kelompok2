# W1-A Handoff

- Owner: Dhea
- Branch: `slot/w1-a-dhea`
- Status: CP1 and CP2 complete, Tahap 3 next
- Last update: 2026-11-11

## What works now

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
- Append-only PyIceberg tables `bronze.market_trade_raw` (partitioned by
  `event_date`) and `bronze.social_post_raw` (partitioned by `ingest_date`).
- `ops.batch_runs` records deterministic batch ids, checksums, row counts, and
  terminal status. Replaying identical data returns `skipped_identical` without
  appending duplicate bronze rows.

## Commands

Windows (recommended, handles Git's `sh` path for GNU Make):

```powershell
.\scripts\make.ps1 setup
.\scripts\make.ps1 secrets
.\scripts\make.ps1 dev-up
.\scripts\make.ps1 doctor
.\scripts\make.ps1 ingest-once
.\scripts\make.ps1 replay
.\scripts\make.ps1 evidence-cp2
.\scripts\make.ps1 dev-down
```

`make ingest-once` replays one market batch and one social batch and refreshes
the CP2 evidence. `make replay` skips evidence generation. `make ingest-live`
reads a small number of live records; it needs outbound access to Binance and
Bluesky.

Linux/macOS or a shell where `make` and `/bin/sh` are native:

```bash
make setup
make secrets
make dev-up
make doctor
make dev-down
```

`make reset` removes named volumes and rebuilds from scratch. It keeps `.env`, so
local passwords survive the reset.

## Evidence

CP1:

- `evidence/deploy/health_<ts>_<sha>.md`
- `evidence/deploy/compose-config_<ts>_<sha>.yml`

CP2:

- `evidence/tests/T01.json` — valid social post passes the contract
- `evidence/tests/T02.json` — negative price is rejected at `$.price`
- `evidence/ingestion/counts_<ts>.csv` — bronze row counts and timestamp range
- `evidence/batch/ledger_<ts>.csv` — `ops.batch_runs` rows with checksums

`make doctor` refreshes the health file. `make compose-config` refreshes the
compose file. `make evidence-cp2` refreshes the CP2 files. All are generated,
not hand-written.

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
- Host-side PyIceberg bypasses Lakekeeper remote signing. The warehouse endpoint
  (`host.docker.internal:9000`) is only reachable from containers, so the bronze
  writer replaces the table IO with the host endpoint (`localhost:9000`) while
  metadata commits still go through Lakekeeper.
- `make bootstrap` recreates MinIO policies on every run so policy changes are
  not silently skipped.

## Next for W1-A (Tahap 3)

1. Re-run the replay from empty-ish state, verify `T-26`, and confirm the ledger
   shows the expected terminal status.
2. Run `make ci` and an end-to-end smoke test from the documented commands.
3. Freeze evidence, update the index, and hand off to W1-B.

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
