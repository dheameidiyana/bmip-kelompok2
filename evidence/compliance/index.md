# Compliance and Evidence Index

| Field | Value |
| --- | --- |
| Status | Draft W2-D; final sweep C3-D |
| Commit | `6187d41` plus working-tree W2-D evidence |
| Owner | Lois |
| Last updated | 2026-11-24 |
| Mapping detail | [`../../docs/spec-mapping.md`](../../docs/spec-mapping.md) |

> `Spek.md` tidak ada di repository. ID F-01..F-20 di sini mengikuti
> rekonstruksi di `docs/spec-mapping.md`; baris yang tidak pasti ditandai
> `partial`. Setiap link di bawah menunjuk file yang ada saat index ditulis.

## 1. Functional requirements

| ID | Requirement | Evidence | Status |
| --- | --- | --- | --- |
| F-01 | Dua sumber batch dan stream | [`../ingestion/counts_20261111T1405.csv`](../ingestion/counts_20261111T1405.csv), [`../e2e/M1_20261120T0323.txt`](../e2e/M1_20261120T0323.txt) | PASS |
| F-02 | Kontrak data, event time, ID unik | [`../tests/T01.json`](../tests/T01.json), [`../tests/T02.json`](../tests/T02.json) | PASS |
| F-03 | Ingestion batch, replay, backfill | [`../ingestion/replay_20261111T1405.txt`](../ingestion/replay_20261111T1405.txt), [`../batch/T26.json`](../batch/T26.json) | PASS |
| F-04 | Stream market, offset, restart, DLQ | [`../stream/CP1_20261113T0003.json`](../stream/CP1_20261113T0003.json), [`../stream/T28.txt`](../stream/T28.txt), [`../stream/T29.json`](../stream/T29.json) | PASS |
| F-05 | Bronze dan replay idempoten | [`../ingestion/counts_20261111T1405.csv`](../ingestion/counts_20261111T1405.csv), [`../e2e/SMOKE-W1A_20261120T0150_ee4c8bf.txt`](../e2e/SMOKE-W1A_20261120T0150_ee4c8bf.txt) | PASS |
| F-06 | Silver, deduplikasi, freshness | [`../tests/T03.txt`](../tests/T03.txt), [`../tests/T24.txt`](../tests/T24.txt) | PASS |
| F-07 | Tiga gold mart | [`../dq/mart-counts_20261113T2223.csv`](../dq/mart-counts_20261113T2223.csv), [`../dbt/docs_20261113T2230.txt`](../dbt/docs_20261113T2230.txt) | PASS |
| F-08 | DQ GX, severity, quarantine | [`../dq/dq_report.json`](../dq/dq_report.json), [`../tests/T11.txt`](../tests/T11.txt), [`../tests/T12.txt`](../tests/T12.txt) | PARTIAL: snapshot freeze punya critical `gold-market-lag` |
| F-09 | Orkestrasi Prefect | [`../deploy/prefect-gold_20261113T2229_3742fe9.json`](../deploy/prefect-gold_20261113T2229_3742fe9.json), [`../deploy/prefect_w2a_20261118T155105_afa8617.json`](../deploy/prefect_w2a_20261118T155105_afa8617.json) | PASS |
| F-10 | MinIO, Iceberg, Lakekeeper | [`../storage/T31.txt`](../storage/T31.txt), [`../storage/T32.json`](../storage/T32.json), [`../storage/T33.json`](../storage/T33.json) | PASS |
| F-11 | Query API minimal sepuluh endpoint | [`../api/smoke_20261114T0239.txt`](../api/smoke_20261114T0239.txt), [`../api/routes_20261114T0239.txt`](../api/routes_20261114T0239.txt) | PASS |
| F-12 | Serving dan query rentang | [`../serving/loader-idempotence_20261114T0239.json`](../serving/loader-idempotence_20261114T0239.json), [`../api/T34.json`](../api/T34.json) | PASS |
| F-13 | Dashboard Streamlit dan Grafana | [`../dashboards/streamlit_20261114T0405.png`](../dashboards/streamlit_20261114T0405.png), [`../dashboards/grafana-pipeline_20261120T0324_c9ef99a.png`](../dashboards/grafana-pipeline_20261120T0324_c9ef99a.png) | PASS untuk visualisasi; prediksi kosong saat registry kosong |
| F-14 | Analisis sentimen | [`../tests/T10.txt`](../tests/T10.txt), [`../dq/mart-counts_20261113T2223.csv`](../dq/mart-counts_20261113T2223.csv) | PASS |
| F-15 | Training, registry, inference, drift | [`../ml/train_20261118T143530Z.json`](../ml/train_20261118T143530Z.json), [`../ml/registry-metadata_20261118T154807Z.json`](../ml/registry-metadata_20261118T154807Z.json), [`../ml/T20.txt`](../ml/T20.txt), [`../ml/T21.json`](../ml/T21.json), [`../ml/drift_20261118T092731Z.json`](../ml/drift_20261118T092731Z.json) | PARTIAL: registry kosong saat freeze dan retrain sekarang gagal karena dua event date berlabel |
| F-16 | Metrics, logs, alerting | [`../observability/CP1_20261120T0323_c9ef99a.json`](../observability/CP1_20261120T0323_c9ef99a.json), [`../alerts/CP2_20261120T0323_c9ef99a.json`](../alerts/CP2_20261120T0323_c9ef99a.json), [`../alerts/T39_20261120T0304_e5369f6.md`](../alerts/T39_20261120T0304_e5369f6.md) | PASS |
| F-17 | Security, RBAC, TLS, scan | [`../security/api-401.txt`](../security/api-401.txt), [`../security/rbac-matrix.md`](../security/rbac-matrix.md), [`../security/tls.txt`](../security/tls.txt), [`../security/gitleaks.txt`](../security/gitleaks.txt), [`../security/pii-scan.txt`](../security/pii-scan.txt) | PASS |
| F-18 | Catalog, lineage, governance | [`../catalog/CP2_20261121T101633.md`](../catalog/CP2_20261121T101633.md), [`../lineage/CP1_20261121T101507.md`](../lineage/CP1_20261121T101507.md), [`../lineage/T30.md`](../lineage/T30.md) | PASS |
| F-19 | Recovery, fault, benchmark | [`../recovery/T19.txt`](../recovery/T19.txt), [`../recovery/T40.json`](../recovery/T40.json), [`../faults/stream-kill_20261123T182353.json`](../faults/stream-kill_20261123T182353.json), [`../faults/minio-kill_20261123T182601.json`](../faults/minio-kill_20261123T182601.json), [`../benchmark/matrix.csv`](../benchmark/matrix.csv) | PARTIAL: backup/restore/T-40/fault PASS; benchmark sebagian partial |
| F-20 | Dokumentasi, evidence, demo | [`../README.md`](../README.md), [`index.md`](index.md), [`../../docs/spec-mapping.md`](../../docs/spec-mapping.md) | PARTIAL: clean clone dan final C3-D belum |

## 2. Test and checkpoint evidence

| ID | Evidence | Status |
| --- | --- | --- |
| CP1 W1-A | [`../deploy/health_20261111T1404_937a0ef.md`](../deploy/health_20261111T1404_937a0ef.md) | PASS |
| CP2 W1-A | [`../tests/CP2_20261113000220.json`](../tests/CP2_20261113000220.json) | PASS |
| T-03 | [`../tests/T03.txt`](../tests/T03.txt) | PASS |
| T-04 | [`../tests/T04.txt`](../tests/T04.txt) | PASS |
| T-06 | [`../tests/T06.txt`](../tests/T06.txt) | PASS |
| T-07 | [`../tests/T07.txt`](../tests/T07.txt) | PASS |
| T-08 | [`../tests/T08.txt`](../tests/T08.txt) | PASS |
| T-09 | [`../tests/T09.txt`](../tests/T09.txt) | PASS |
| T-10 | [`../tests/T10.txt`](../tests/T10.txt) | PASS |
| T-11 | [`../tests/T11.txt`](../tests/T11.txt) | PASS |
| T-12 | [`../tests/T12.txt`](../tests/T12.txt) | PASS |
| T-13 | [`../security/api-401.txt`](../security/api-401.txt) | PASS |
| T-14 | [`../tests/T14.txt`](../tests/T14.txt) | PASS |
| T-15 | [`../tests/T15.txt`](../tests/T15.txt) | PASS |
| T-19 | [`../recovery/T19.txt`](../recovery/T19.txt) | PASS |
| T-20 | [`../ml/T20.txt`](../ml/T20.txt) | PASS |
| T-21 | [`../ml/T21.json`](../ml/T21.json) | PASS |
| T-22 | [`../security/pii-scan.txt`](../security/pii-scan.txt) | PASS |
| T-24 | [`../tests/T24.txt`](../tests/T24.txt) | PASS |
| T-26 | [`../batch/T26.json`](../batch/T26.json) | PASS |
| T-27 | [`../batch/T27.json`](../batch/T27.json) | PASS |
| T-28 | [`../stream/T28.txt`](../stream/T28.txt) | PASS |
| T-29 | [`../stream/T29.json`](../stream/T29.json) | PASS |
| T-30 | [`../lineage/T30.md`](../lineage/T30.md) | PASS |
| T-31 | [`../storage/T31.txt`](../storage/T31.txt) | PASS |
| T-32 | [`../storage/T32.json`](../storage/T32.json) | PASS |
| T-33 | [`../storage/T33.json`](../storage/T33.json) | PASS |
| T-34 | [`../api/T34.json`](../api/T34.json) | PASS |
| T-36 | [`../ml/T36.json`](../ml/T36.json) | PASS for W2-A contract |
| T-37 | [`../dashboard/reconciliation_20261120T0324_c9ef99a.json`](../dashboard/reconciliation_20261120T0324_c9ef99a.json) | PASS |
| T-38 | [`../security/rbac-matrix.md`](../security/rbac-matrix.md) | PASS |
| T-39 | [`../alerts/T39_20261120T0304_e5369f6.md`](../alerts/T39_20261120T0304_e5369f6.md) | PASS |
| T-40 | [`../recovery/T40.json`](../recovery/T40.json) | PASS |
| T-41 | [`../tests/coverage.json`](../tests/coverage.json), [`../tests/T41_20261125T040800Z.txt`](../tests/T41_20261125T040800Z.txt) | PASS (51.36%, 188 tests) |
| T-42 | [`../benchmark/matrix.csv`](../benchmark/matrix.csv) | PARTIAL until full sweep C3-D |
| T-25 | [`../deploy/clean-clone.log`](../deploy/clean-clone.log) | PASS with documented deviations (stack, catalog, dashboard, API) |
| T-16 | [`../tests/T16.txt`](../tests/T16.txt) | PASS (15 + 15 requests to two replicas) |
| T-17 | [`../tests/T17.txt`](../tests/T17.txt) | PASS (0 5xx with `api-2` stopped) |
| T-18 | [`../tests/T18.txt`](../tests/T18.txt) | PASS (latency -> circuit 503 -> recovery) |
| TRIVY | [`../security/trivy.txt`](../security/trivy.txt) | PASS (0 HIGH/CRITICAL) |
| RATE | [`../security/rate-limit.txt`](../security/rate-limit.txt) | PASS (200 + 429) |
| TLS | [`../security/tls-c3a.txt`](../security/tls-c3a.txt) | PASS (TLS + HSTS) |
| AUDIT | [`../security/audit.csv`](../security/audit.csv) | PASS (100 rows) |

## 3. Known dead-link policy

`make evidence-check` and CI now fail when a linked file is missing or when an
evidence file is untracked. This index was last verified on 2026-11-25. Rows
marked `pending` intentionally point to files that do not exist yet and must be
updated before the final C3-D freeze.

## 4. C3-C

| ID | Evidence | Status |
| --- | --- | --- |
| CP1 nodes | [`../deploy/compose-3node.yml`](../deploy/compose-3node.yml), [`../deploy/compose-4node.yml`](../deploy/compose-4node.yml) | PASS |
| CP1 live | [`../deploy/two-node-live_20261127T165614Z.json`](../deploy/two-node-live_20261127T165614Z.json) | PASS for N1+N2 services on one host |
| CP1 ACL | [`../security/tailscale-acl_20261127T092149Z.json`](../security/tailscale-acl_20261127T092149Z.json) | PASS offline; live test NOT RUN (`NeedsLogin`) |
| CP1 logs | `deploy/observability/loki.yml`, `deploy/observability/promtail.yml` | PARTIAL: Docker Hub image pull timed out |
| CP2 catalog | [`../catalog/migration_20261127T121956Z.json`](../catalog/migration_20261127T121956Z.json) | PASS |
| CP2 governance | [`../catalog/governance_20261127T123615Z.json`](../catalog/governance_20261127T123615Z.json), [`../catalog/metadata-test_20261127T123931Z.txt`](../catalog/metadata-test_20261127T123931Z.txt) | PASS |
| CP2 views | [`../catalog/search_20261127T124116Z.txt`](../catalog/search_20261127T124116Z.txt), [`../catalog/views_20261127T124116Z.json`](../catalog/views_20261127T124116Z.json) | PASS |
| CP3 docs | [`../deploy/docs-hosting_20261127T132119Z.json`](../deploy/docs-hosting_20261127T132119Z.json) | PASS |
| CP3 lifecycle | [`../storage/compaction_20261127T155958Z.json`](../storage/compaction_20261127T155958Z.json), [`../storage/retention_20261127T155958Z.txt`](../storage/retention_20261127T155958Z.txt) | PASS; compaction no-op (one file per partition) |
| F-17 note | ACL live check | PARTIAL until C3-D logs in to Tailscale |
| F-18 note | catalog governance | PASS for register/change/deprecate/delete + metadata test |

C3-D must add the Loki runtime evidence after pulling the images; until then this
section does not claim it. The live ACL test also remains C3-D work.
