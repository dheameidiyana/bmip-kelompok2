# Handoff C3-C - Vio

- Owner: Vio
- Branch: `slot/c3-c-vio`
- Base: `slot/c3-b-dhea` (`eedb5ee`, one commit after the `c3-b-ok` tag)
- Status: PASS with two recorded environment gaps (Loki image pull, live Tailscale)
- Tag: `c3-c-ok` (local; not pushed)
- Date: 2026-11-28

## Status

- CP1: PASS with gaps - node profiles, final ACL, and the N1+N2 live check
  passed. Loki/Promtail configuration is complete but the images could not be
  pulled (Docker Hub timeout), so there is no Loki screenshot.
- CP2: PASS - catalog migration, five views, tsvector search, governance
  workflow, metadata consistency, and data dictionary.
- CP3: PASS - lifecycle compaction/expiry/retention evidence, docs hosting,
  handoff. Compaction was a no-op because the gold tables already have one file
  per partition; the retention delete path passed on the fixture table.

## Yang sudah jalan

- `profiles` role `n1`..`n4` in `deploy/compose.base.yml`, overlays
  `deploy/compose.node1..4.yml`, non-secret `deploy/env/node1..4.env`.
- Valid `docker compose config` for node1..4, three-node, and four-node:
  `evidence/deploy/compose-3node.yml`, `compose-4node.yml`.
- Final Tailscale ACL with `tag:bmip-n1..n4`; offline allow/deny matrix:
  `evidence/security/tailscale-acl_20261127T092149Z.json`.
- Live N1+N2 on one host: all required N1/N2 services running, API-2 and Prefect
  health 200 (`evidence/deploy/two-node-live_20261127T165614Z.json`). The N1
  host-port HTTP checks (9000/8181) were refused by the Docker port proxy even
  though the containers were running; this is recorded as a local limitation,
  not a node-profile failure.
- Loki/Promtail configuration and Grafana datasource; `BMIP_LOG_FILE` file
  logging and `service=stream-processor` JSON logs. The `loki`/`promtail` images
  could not be pulled; no runtime Loki evidence.
- Catalog migration: `pg_trgm`, generated `search_vector`, trigram indexes, and
  governance columns (`evidence/catalog/migration_20261127T121956Z.json`).
- Catalog five views: Search, Dataset detail, Lineage, Quality, Governance
  (`evidence/catalog/views_20261127T124116Z.json`); search evidence in
  `evidence/catalog/search_20261127T124116Z.txt`.
- Governance workflow register/change/deprecate/delete + audit + metadata test
  (`evidence/catalog/governance_20261127T123615Z.json`,
  `metadata-test_20261127T123931Z.txt`).
- `docs/data-dictionary.md` generated from the registry and live schemas.
- Lifecycle: compaction/expiry report + production retention dry-run + fixture
  retention apply PASS (`evidence/storage/compaction_20261127T155958Z.json`,
  `retention_20261127T155958Z.txt`).
- Documentation hosting: dbt docs, static GX Data Docs, nginx on 8089, HTTP 200
  (`evidence/deploy/docs-hosting_20261127T132119Z.json`).

## Yang belum jalan / gap

- **Live Tailscale ACL test not run** - `tailscale status` is `NeedsLogin`.
  ACL was validated offline only (`offline_validation: PASS`,
  `live_test: not_run`). C3-D must log in, tag N1..N4, run
  `tailscale status --json` and the `Test-NetConnection` checks from
  `docs/runbooks/tailscale-acl.md`, then attach
  `evidence/security/tailscale-status_<ts>.json`.
- **Loki/Promtail not started** - `grafana/loki:3.3.2` and
  `grafana/promtail:3.3.2` could not be resolved from Docker Hub
  (`context deadline exceeded`). Configuration is in place; C3-D must pull the
  images, run `make c3c-loki`, and attach the JSON/TXT evidence. Do not claim a
  Loki screenshot before that.
- Four-node profile is `docker compose config` only; N1+N2 were started live on
  one laptop, not two physical hosts. This is not a real two-laptop tailnet test.
- Scheduled retention keeps `apply_retention: []` (dry-run) so demo history is
  not deleted before C3-D close-out. The delete path is proven on
  `silver.c3c_retention_probe`; C3-D can enable a layer after checking the cutoff.
- PyIceberg 0.12 has no `rewrite_data_files`/`remove_orphan_files`; compaction
  uses `table.overwrite` and orphan removal would reconcile the S3 listing with
  all manifests. The run showed one file per partition, so nothing was rewritten.
- Screenshot evidence is absent: Playwright's Chrome channel hung and the
  headless Chrome screenshot only rendered the Streamlit skeleton. JSON/text
  evidence is complete; C3-D may add screenshots with a stable browser.

## Cara menjalankan

```powershell
.\scripts\make.ps1 node1-config node2-config node3-config node4-config
.\scripts\make.ps1 three-node-config four-node-config
.\scripts\make.ps1 c3c-nodes
.\scripts\make.ps1 c3c-acl
.\scripts\make.ps1 c3c-loki        # needs the Loki/Promtail images
.\scripts\make.ps1 c3c-migrate
.\scripts\make.ps1 c3c-governance
.\scripts\make.ps1 c3c-catalog
.\scripts\make.ps1 c3c-lifecycle
.\scripts\make.ps1 docs
.\scripts\make.ps1 test
.\scripts\make.ps1 evidence-check
```

## Bukti

- `evidence/deploy/compose-3node.yml`
- `evidence/deploy/compose-4node.yml`
- `evidence/deploy/nodes_20261127T164629Z.json`
- `evidence/deploy/two-node-live_20261127T165614Z.json`
- `evidence/security/tailscale-acl_20261127T092149Z.json`
- `evidence/catalog/migration_20261127T121956Z.json`
- `evidence/catalog/governance_20261127T123615Z.json`
- `evidence/catalog/metadata-test_20261127T123931Z.txt`
- `evidence/catalog/views_20261127T124116Z.json`
- `evidence/catalog/search_20261127T124116Z.txt`
- `evidence/storage/compaction_20261127T155958Z.json`
- `evidence/storage/retention_20261127T155958Z.txt`
- `evidence/deploy/docs-hosting_20261127T132119Z.json`
- `docs/data-dictionary.md`

## Langkah berikutnya untuk C3-D

1. Log in to Tailscale, tag N1..N4, run the live ACL checks, and attach the
   JSON status. Do not mark F-17 fully PASS before this.
2. Pull `grafana/loki:3.3.2` and `grafana/promtail:3.3.2`, run `make c3c-loki`,
   and attach `evidence/logs/loki_<ts>.json|txt` (and PNG if a browser works).
3. Decide whether to enable production retention (`apply_retention`), starting
   with bronze only, after confirming the close-out window.
4. Verify a clean clone includes `deploy/env/node*.env` and that `make docs`
   produces both the dbt and GX trees.
5. Do not rewrite C3-C evidence; add new files and update the compliance index.
