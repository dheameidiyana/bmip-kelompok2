# Handoff W2-C - Anin

- Owner: Anin
- Branch: `slot/w2-c-anin`
- Base: `w2-b-ok` (`e7823c5`, includes W2-A `af1734e` and `dev` `9972693`)
- Handoff to: Lois (W2-D)
- Last update: 2026-11-21

## Status

- CP1: PASS (dbt lineage event received by Marquez, `run_id` recorded)
- CP2: PASS (11 registry rows, T-30 trace, RBAC 401/403 draft)
- CP3: PASS (T-38 matrix + audit rows, T-13, PII, gitleaks, port scan, TLS)
- Tag: `w2-c-ok`

Gate: lineage from dbt/Prefect/stream is visible in Marquez, the catalogue has
11 datasets with owner/classification/retention, the RBAC matrix returns
`401/200/403/202/200` with an audit row for every attempt, and the security
scans are clean or explicitly marked partial with a reason.

## Yang sudah jalan

### Lineage

- `src/bmip/lineage/` emits OpenLineage RunEvents to
  `OPENLINEAGE_URL/api/v1/lineage` (Marquez) and always writes a JSONL spool to
  `evidence/lineage/spool/`.
- dbt is wrapped in `scripts/run_dbt.py` and the Prefect `dbt-build` task; the
  hook reads `dbt/target/manifest.json` and collapses each `gold.mart_*` model
  to its upstream `silver.*` sources.
- Prefect flows `harvest-social`, `transform-silver`, `transform-gold`,
  `infer-volatility`, and `train-volatility` emit START/COMPLETE/FAIL.
- The stream processor emits a `market-stream` event with bronze/silver
  datasets; `run_id` is the stream run id.

### Catalog

- `ops.dataset_registry` is the source of truth; `catalog/datasets.yml` seeds it
  and remains the offline fallback (`DATASET_REGISTRY_SOURCE=auto`).
- `serving.catalog_datasets` is still the API read model; the loader copies the
  registry and stores the live schema.
- `catalog.bmip.local:8502` has search (name/owner/tag), domain/layer/
  classification filters, detail, schema, lineage, quality, freshness, and
  admin actions.
- Auto-classification from column names fills `auto_classification` and is
  shown as a second opinion next to the declared classification.

### Gateway and RBAC

- Traefik terminates TLS on `:443`, redirects `:80`, and keeps the `:8000`
  path-based router for scripts.
- Host routers: `api`, `app`, `catalog`, `grafana`, `prometheus`, `marquez`,
  `minio`, `prefect`. API has retry, rate limit, and security headers.
- Basic auth only on Prometheus, Marquez, and MinIO console.
- `ops.api_keys` holds Argon2 hashes for `viewer`, `operator`, `admin`; the W1-D
  `BMIP_API_KEY` is accepted as `viewer`.
- `POST /v1/admin/backfill` -> 202 + queued row; `POST /v1/admin/catalog/reload`
  -> 200; `POST /v1/admin/keys/{id}/rotate` -> 200 with the new plaintext once.
- `ops.audit_log` gets one row per `/v1` attempt, including 401/403.

## Cara menjalankan

```powershell
make secrets          # merge missing keys; never rotates existing secrets
make certs users
make dev-up
make governance-up    # postgres-gov + Marquez + Marquez web
make governance       # migration + registry seed + API keys

python scripts/run_dbt.py --select marts   # emits the dbt event
python scripts/w2c_trace.py                # T-30
python scripts/w2c_evidence.py --steps cp1,cp2,summary
python scripts/w2c_scan.py                 # PII, ports, gitleaks, TLS, RBAC
```

URL:

| Layanan | URL |
| --- | --- |
| Traefik API | https://api.bmip.local/health/ready |
| Dashboard | https://app.bmip.local |
| Catalog | https://catalog.bmip.local |
| Marquez | https://marquez.bmip.local (basic auth) |
| Marquez API | http://localhost:5002/api/v1 |
| Prometheus | https://prometheus.bmip.local (basic auth) |
| Grafana | https://grafana.bmip.local |

## Keputusan dan deviasi

- OpenLineage emitter native (`httpx`), not `dbt-ol`; spool file is the fallback.
- Catalog is a separate Streamlit app (8502), not a tab in the business
  dashboard.
- TLS certificates come from `scripts/gen_certs.py` (`cryptography`), not
  mkcert.
- Internal dev ports bind to `127.0.0.1`; `BMIP_BIND_ADDRESS=0.0.0.0` overrides
  for a tailnet demo.
- Backfill is queued (202) in `ops.backfill_requests`; execution is W2-D/C3-A
  work, not an inline API thread.
- The API skips champion loading when `MLFLOW_TRACKING_URI` is empty, so the
  base dev stack starts in seconds instead of retrying an absent MLflow for
  minutes. `deploy/compose.ml.yml` still sets the URI and loads the champion.
- ADR number 0004 avoids the W2-B 0003 collision.

## Gap yang harus dibaca W2-D

- Marquez is in the `governance` profile; a plain `make dev-up` does not start
  it. `make governance-up` is required before CP1 evidence.
- `bmip_gold_rows` and `bmip_predictions_total` were already empty in W2-B;
  W2-C does not change the ML registry.
- The interactive lineage graph is still the Marquez UI; the catalog shows
  text lists. C3-C adds the five-view portal.
- Tailscale ACL is a reviewed file; cross-node verification needs Tailscale
  login and multiple devices. If unavailable, mark `partial` per risk G1.
- gitleaks must be installed on the evidence machine (`winget install
  Gitleaks.Gitleaks`) or dropped into `tools/gitleaks.exe` (gitignored). The
  W2-C run used 8.30.1 from `tools/`.

## Langkah berikutnya untuk Lois (W2-D)

1. Keep the W2-C tag ancestor when opening the final PR to `dev`.
2. Include `postgres-gov` in the backup set; it holds Marquez metadata.
3. Use `evidence/security/rbac-matrix.md` as the T-38 source; do not hand-edit.
4. Run `python scripts/w2c_trace.py` after any gold rebuild to refresh T-30.
5. Do not rebase `slot/w2-b-vio`; branch from `w2-b-ok` and keep the chain.

## Evidence

| ID | File | Isi |
| --- | --- | --- |
| CP1 | `evidence/lineage/CP1_20261121T101507.md` | Marquez health + dbt event + screenshot |
| CP1 | `evidence/lineage/events_20261121T101507.jsonl` | raw OpenLineage events |
| CP2 | `evidence/catalog/registry_20261121T101633.csv` | 11 registry rows |
| CP2 | `evidence/catalog/CP2_20261121T101633.md` | owner/classification/retention check |
| T-30 | `evidence/lineage/T30.md` | bronze -> silver -> gold -> serving -> API |
| T-13 | `evidence/security/api-401.txt` | unauthenticated 401 |
| T-22 | `evidence/security/pii-scan.txt` | silver PII scan |
| T-38 | `evidence/security/rbac-matrix.md` | 401/200/403/202/200 + audit rows |
| SECRETS | `evidence/security/gitleaks.txt` | gitleaks result |
| PORT | `evidence/security/port-scan.txt` | loopback/LAN ports |
| TLS | `evidence/security/tls.txt` | CA, SAN, redirect, HTTPS routes |
| ACL | `evidence/security/tailscale-acl.json` | ACL hash + tailscale status |
| SUM | `evidence/w2c/SUMMARY_20261121T101848_e7823c5.json` | run summary |
