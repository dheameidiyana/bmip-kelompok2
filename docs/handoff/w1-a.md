# W1-A Handoff

- Owner: Dhea
- Branch: `slot/w1-a-dhea`
- Status: CP1 complete, Tahap 2 next
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

## Commands

Windows (recommended, handles Git's `sh` path for GNU Make):

```powershell
.\scripts\make.ps1 setup
.\scripts\make.ps1 secrets
.\scripts\make.ps1 dev-up
.\scripts\make.ps1 doctor
.\scripts\make.ps1 dev-down
```

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

## CP1 evidence

- `evidence/deploy/health_<ts>_<sha>.md`
- `evidence/deploy/compose-config_<ts>_<sha>.yml`

`make doctor` refreshes the health file. `make compose-config` refreshes the
compose file. Both are generated, not hand-written.

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

## Next for W1-A (Tahap 2)

1. Write `contracts/market_trade.v1.json`, `contracts/social_post.v1.json`, and
   the pydantic validators.
2. Implement the Binance producer, replay feed, Bluesky harvester, and PyIceberg
   bronze writer.
3. Write one ledger row to `ops.batch_runs` with a deterministic checksum.
4. Produce `evidence/tests/T01.json`, `T02.json`,
   `evidence/ingestion/counts_<ts>.csv`, and `evidence/batch/ledger_<ts>.csv`.

## Notes for other slots

- W1-B can use `REDPANDA_BROKERS=localhost:19092` from the host and
  `redpanda:9092` inside the compose network.
- W1-B/C/D can use the `lakehouse` warehouse. Resolve its UUID from
  `GET http://localhost:8181/management/v1/warehouse` before calling catalog
  paths.
- W1-D owns the real API. Replace `deploy/api/server.py` without changing the
  compose service name or health paths.
- Do not commit `.env`. Run `make secrets` on a fresh clone.
