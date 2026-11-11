# ADR-0001: W1-A foundation and dev storage choices

- Status: accepted
- Date: 2026-11-11
- Owner: Dhea (W1-A)

## Context

W1-A must deliver a reproducible dev stack with MinIO, PostgreSQL, Lakekeeper,
Redpanda, Traefik, and an API placeholder. Two upstream constraints appeared while
building the first stack:

1. `minio/minio` and `minio/mc` are no longer pullable from Docker Hub or
   `quay.io/minio` in this environment.
2. Docker Desktop for Windows does not publish host ports for containers that are
   attached only to an `internal: true` network.

## Decisions

### D1. MinIO image source

Use the `elestio/minio` image pinned by digest
`sha256:25348a257f1ece1b192f25f6cd9854618fa86422ac87b494b5d4e629c556d4bd`.
The image contains MinIO `RELEASE.2025-09-07T16-13-09Z` and also bundles `mc`,
`curl`, and `sh`, so the same image powers the server and the one-shot bootstrap
container.

Trade-off: it is a third-party mirror, not the upstream namespace. The binary is
the official MinIO build. Record the source here and replace it with the upstream
image as soon as it is pullable again.

### D2. MinIO runs as a non-root user

`minio` runs as uid/gid `1000:1000`. A one-shot `minio-perms` container runs as
root only to `chown` the named volume once per `up`, then exits. This keeps the
long-running object store non-root without a host-side permission step.

### D3. Lakekeeper bootstrap and namespace addressing

Lakekeeper starts with `LAKEKEEPER__AUTHZ_BACKEND=allowall` and
`LAKEKEEPER__ENABLE_DEFAULT_PROJECT=true` for the dev profile. The bootstrap
container accepts terms once, creates the `lakehouse` warehouse, and creates the
`bronze`, `silver`, and `gold` namespaces.

Lakekeeper addresses catalogs by warehouse UUID, not warehouse name. The
bootstrap and the doctor resolve the UUID from
`GET /management/v1/warehouse` before calling
`/catalog/v1/{warehouse-id}/namespaces`.

### D4. Dev overlay attaches published services to `edge`

The `data` network stays `internal: true` in the base file. Because Docker Desktop
will not publish ports from an internal-only network, the dev overlay attaches
`minio`, `postgres-core`, `lakekeeper`, and `redpanda` to `edge` as well. The
`edge` network is local-only; only the dev overlay publishes host ports. A later
multi-node profile can keep the same base file without host ports.

### D5. PostgreSQL host port

The local laptop already runs PostgreSQL on `5432`, so the dev overlay publishes
container `5432` as host `5433`. The container-internal DSN still uses `5432`.
`POSTGRES_CORE_DSN` in `.env.example` points at `localhost:5433`.

### D6. Bronze table locations and host-side IO

Bronze tables are created with explicit locations under
`s3://lakehouse/warehouse/bronze.db/<table>`. Lakekeeper would otherwise assign
a per-table UUID path, requiring every service policy to allow
`lakehouse/warehouse/*`; explicit locations keep policies scoped to the bronze
prefix.

Lakekeeper enables S3 remote signing and advertises the warehouse endpoint as
`http://host.docker.internal:9000`, which is not reachable from the Windows
host. The ingestion writer therefore replaces the loaded table's `FileIO` with
one built from the host endpoint (`http://localhost:9000`) and normal static
credentials. Iceberg metadata commits still go through Lakekeeper; only data
file IO is local. Containerized services do not need this workaround.

### D7. MinIO policies are refreshed on bootstrap

`deploy/minio/bootstrap.sh` detaches, removes, recreates, and reattaches each
managed policy on every `make bootstrap` run. The earlier create-if-missing
logic silently kept stale policies after resource changes.

### D8. Secrets

`make secrets` generates `.env` from `.env.example` with random
`token_urlsafe` values and never overwrites an existing file. `.env` is
gitignored. CI uses `deploy/env/ci.env.example` with dummy values only.

### D9. Compose evidence uses no interpolation

`make compose-config` runs `docker compose config --no-interpolate`. Plain
`config` renders real `.env` values, including passwords, into the evidence
file. `--no-interpolate` keeps `${VAR}` placeholders while still validating the
Compose model, so the evidence is safe to commit.

## Consequences

- `make dev-up` is idempotent: `minio-init` and `lakekeeper-bootstrap` can be
  re-run safely and treat existing users, buckets, warehouse, and namespaces as
  success.
- The upstream MinIO image source must be revisited when it becomes available.
- Multi-node profiles that need published ports must repeat the `edge`
  attachment or run on an OS where Docker publishes ports from internal networks.
