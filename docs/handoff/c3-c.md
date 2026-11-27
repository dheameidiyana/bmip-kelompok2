# Handoff C3-C - Vio

- Owner: Vio
- Branch: `slot/c3-c-vio`
- Base: `slot/c3-b-dhea` (`eedb5ee`, one commit after the `c3-b-ok` tag)
- Status: CP2/CP3 PASS; CP1 PARTIAL (live Tailscale deferred to C3-D, Loki image pull blocked)
- Tag: none - `c3-c-ok` is withheld until the live ACL check is closed with C3-D
- Date: 2026-11-28

## Status

- CP1: PARTIAL - node profiles, 3/4-node config, ACL offline validation, the
  N1+N2 live check, and `e2e-smoke` PASS. Live Tailscale ACL is deferred to
  C3-D (joint work). Loki/Promtail runtime is still blocked by a Docker Hub
  image pull timeout; the configuration is committed.
- CP2: PASS - catalog migration, five views, tsvector/pg_trgm search,
  governance workflow, metadata consistency, data dictionary. PNG screenshots
  are the only evidence gap; JSON/text evidence is complete.
- CP3: PASS - docs hosting (local + S3 upload), lifecycle compaction/expiry,
  retention fixture, orphan removal, and the `compact_iceberg` Prefect flow.
  PNG screenshots are the only evidence gap.

## Yang sudah jalan

- `profiles` role `n1`..`n4` in `deploy/compose.base.yml`, overlays
  `deploy/compose.node1..4.yml`, non-secret `deploy/env/node1..4.env`.
- Valid `docker compose config` for node1..4, three-node, and four-node:
  `evidence/deploy/compose-3node.yml`, `compose-4node.yml`,
  `nodes_20261127T164629Z.json`.
- Final Tailscale ACL with `tag:bmip-n1..n4`; offline allow/deny matrix:
  `evidence/security/tailscale-acl_20261127T092149Z.json`.
- Live N1+N2 on one host: all required N1/N2 services running, API-2 and Prefect
  health 200 (`evidence/deploy/two-node-live_20261127T165614Z.json`).
- `e2e-smoke` PASS after the C3-C changes:
  `evidence/e2e/SMOKE-W1A_20261127T1833_8d1f7c3.txt`.
- Loki/Promtail configuration and Grafana datasource; `BMIP_LOG_FILE` file
  logging and `service=stream-processor` JSON logs.
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
- Orphan removal: 103 orphan files deleted in the first pass, then the remaining
  3; final state has zero candidates
  (`evidence/storage/orphans_20261127T195321Z.json`,
  `evidence/storage/orphans_20261127T195612Z.json`). `svc-process` now has
  `DeleteObject` on the table prefixes.
- Prefect `compact_iceberg` flow executed with compact + expiry + fixture
  retention (`evidence/storage/prefect-compact-iceberg_20261127T185626Z.json`);
  the deployment is declared in `prefect.yaml` (daily 01:00 UTC).
- Documentation hosting: dbt docs, static GX Data Docs, nginx on 8089, HTTP 200
  (`evidence/deploy/docs-hosting_20261127T132119Z.json`) and S3 upload of 9
  keys to `s3://docs/`
  (`evidence/deploy/docs-hosting_20261127T185821Z.json`).

## Yang belum jalan / gap

- **Live Tailscale ACL (deferred to C3-D, joint work with Vio).**
  `tailscale status` = `NeedsLogin`. ACL is final and validated offline
  (`offline_validation: PASS`), but there is no live deny-by-default test.
  This is not a code gap and not Lois's task alone: Vio holds the ACL context,
  Lois holds the close-out.
  Steps:
  1. Log in to a tailnet (team tailnet if available; otherwise a personal test
     tailnet, labelled as such).
  2. Tag at least two devices: `tag:bmip-n1` and `tag:bmip-n2` or
     `tag:bmip-user`.
  3. Paste `deploy/tailscale/acl.json` into Tailscale Access Controls.
  4. From the second device run `tailscale status`, `Test-NetConnection` to
     port 443 (allow) and port 5432 from `tag:bmip-user` (deny).
  5. Save `tailscale status --json` and the test output to
     `evidence/security/tailscale-status_<ts>.json`.
  CP1 stays PARTIAL and F-17 is not fully PASS until this runs.
- **Loki/Promtail runtime** - `grafana/loki:3.3.2` and
  `grafana/promtail:3.3.2` cannot be resolved from Docker Hub
  (`context deadline exceeded`). Configs are committed; C3-D must pull the
  images and run `make c3c-loki`.
- Four-node profile is `docker compose config` only; N1+N2 were started live on
  one laptop, not two physical hosts.
- Production retention stays `apply_retention: []` (dry-run) so demo history is
  not deleted before C3-D close-out. The delete path is proven on
  `silver.c3c_retention_probe`.
- PNG screenshots are missing. Playwright Chromium launches, but the Streamlit
  page never finishes loading in the sandboxed browser; JSON/text evidence is
  complete. C3-D may capture the images with a normal browser.
- PyIceberg 0.12 has no `rewrite_data_files`; compaction uses
  `table.overwrite`. The gold tables already had one file per partition, so the
  compaction pass was a no-op; orphan removal and retention are real.

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
- `evidence/e2e/SMOKE-W1A_20261127T1833_8d1f7c3.txt`
- `evidence/catalog/migration_20261127T121956Z.json`
- `evidence/catalog/governance_20261127T123615Z.json`
- `evidence/catalog/metadata-test_20261127T123931Z.txt`
- `evidence/catalog/views_20261127T124116Z.json`
- `evidence/catalog/search_20261127T124116Z.txt`
- `evidence/storage/compaction_20261127T155958Z.json`
- `evidence/storage/retention_20261127T155958Z.txt`
- `evidence/storage/orphans_20261127T195321Z.json`
- `evidence/storage/orphans_20261127T195612Z.json`
- `evidence/storage/prefect-compact-iceberg_20261127T185626Z.json`
- `evidence/deploy/docs-hosting_20261127T132119Z.json`
- `evidence/deploy/docs-hosting_20261127T185821Z.json`
- `docs/data-dictionary.md`

## Langkah berikutnya untuk C3-D

1. Do the joint Tailscale login/tag/live ACL test with Vio; attach
   `evidence/security/tailscale-status_<ts>.json`.
2. Pull the Loki/Promtail images, run `make c3c-loki`, and attach the JSON/TXT
   evidence.
3. Capture the missing catalog/docs screenshots with a normal browser.
4. Decide whether to enable production retention (`apply_retention`), starting
   with bronze only, after confirming the close-out window.
5. Do not rewrite C3-C evidence; add new files and update the compliance index.
