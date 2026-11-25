# Spec Mapping - BMIP

| Field | Value |
| --- | --- |
| Status | Draft W2-D; final sweep in C3-D |
| Source of truth | `ARCHITECTURE.md` v2.0, `workplan.md`, `README.md` |
| Missing source | `Spek.md` tidak ada di repository ini |
| Owner | Lois |
| Last updated | 2026-11-24 |

> Catatan: file `Spek.md` yang dirujuk workplan tidak tersedia di repository.
> Karena itu ID F-01 sampai F-20 di bawah ini direkonstruksi dari
> `ARCHITECTURE.md` section 2.1, 2.2, 2.5, dan daftar komponen pada
> `workplan.md`. Setiap baris yang tidak dapat dipetakan secara pasti ditandai
> `partial` atau `unknown`; tidak ada klaim pass tanpa file bukti.

## 1. Functional requirements F-01..F-20

| ID | Requirement yang dipetakan | Implementasi utama | Evidence | Status |
| --- | --- | --- | --- | --- |
| F-01 | Dua jenis sumber: batch Bluesky dan stream Binance | `src/bmip/ingestion/`, `src/bmip/ingestion/kafka.py` | `evidence/ingestion/counts_20261111T1405.csv`, `evidence/e2e/M1_20261120T0323.txt` | PASS |
| F-02 | Event timestamp dan ID unik pada kontrak data | `contracts/`, `src/bmip/ingestion/contracts.py` | `evidence/tests/T01.json`, `evidence/tests/T02.json` | PASS |
| F-03 | Ingestion batch dan replay/backfill | `src/bmip/ingestion/social.py`, `scripts/w2a_backfill.py` | `evidence/ingestion/replay_20261111T1405.txt`, `evidence/batch/T26.json`, `evidence/ml/backfill_20261118T040656Z.json` | PASS |
| F-04 | Ingestion stream market, offset, restart, DLQ | `src/bmip/ingestion/kafka.py`, `src/bmip/transform/stream.py` | `evidence/stream/CP1_20261113T0003.json`, `evidence/stream/T28.txt`, `evidence/stream/T29.json` | PASS |
| F-05 | Layer bronze mentah dan replay idempoten | `src/bmip/ingestion/`, `dbt/models/bronze/` | `evidence/ingestion/counts_20261111T1405.csv`, `evidence/e2e/SMOKE-W1A_20261120T0150_ee4c8bf.txt` | PASS |
| F-06 | Layer silver tervalidasi dan deduplikasi | `src/bmip/transform/`, `dbt/models/silver/` | `evidence/tests/T03.txt`, `evidence/tests/T24.txt`, `evidence/stream/T28.txt` | PASS |
| F-07 | Tiga gold mart: market, sentiment, ML | `dbt/models/gold/`, `scripts/build_gold.py` | `evidence/dq/mart-counts_20261113T2223.csv`, `evidence/dbt/docs_20261113T2230.txt` | PASS |
| F-08 | Data quality GX, severity, quarantine | `src/bmip/quality/`, `gx/suites/` | `evidence/dq/dq_report.json`, `evidence/tests/T11.txt`, `evidence/tests/T12.txt` | PARTIAL: DQ terbaca dan berjalan, tetapi snapshot saat freeze menghasilkan critical `gold-market-lag` karena data historis sparse |
| F-09 | Orkestrasi Prefect, flow, retry, backfill | `src/bmip/orchestration/`, `prefect.yaml` | `evidence/deploy/prefect-gold_20261113T2229_3742fe9.json`, `evidence/deploy/prefect_w2a_20261118T155105_afa8617.json` | PASS |
| F-10 | Storage lakehouse MinIO + Iceberg + Lakekeeper | `deploy/compose.base.yml`, `src/bmip/transform/iceberg.py` | `evidence/storage/T31.txt`, `evidence/storage/T32.json`, `evidence/storage/T33.json` | PASS |
| F-11 | Query API minimal sepuluh endpoint | `src/bmip/api/` | `evidence/api/smoke_20261114T0239.txt`, `evidence/api/routes_20261114T0239.txt`, `contracts/openapi.json` | PASS |
| F-12 | Serving PostgreSQL dan query rentang DuckDB/Iceberg | `src/bmip/serving/`, `src/bmip/api/routers/market.py` | `evidence/serving/loader-idempotence_20261114T0239.json`, `evidence/api/T34.json` | PASS |
| F-13 | Dashboard Streamlit dan Grafana | `src/bmip/dashboard/`, `deploy/grafana/` | `evidence/dashboards/streamlit_20261114T0405.png`, `evidence/dashboards/grafana-pipeline_20261120T0324_c9ef99a.png`, `evidence/dashboards/grafana-business_20261120T0324_c9ef99a.png` | PASS untuk visualisasi; prediksi tampil kosong saat registry kosong |
| F-14 | Analisis sentimen | `src/bmip/transform/sentiment.py`, `dbt/models/silver/silver_social_sentiment.sql` | `evidence/tests/T10.txt`, `evidence/dq/mart-counts_20261113T2223.csv` | PASS |
| F-15 | Training, registry, inference, drift, retraining | `src/bmip/ml/`, `scripts/w2a_train.py`, `scripts/w2a_drift.py` | `evidence/ml/train_20261118T143530Z.json`, `evidence/ml/registry-metadata_20261118T154807Z.json`, `evidence/ml/T20.txt`, `evidence/ml/T21.json`, `evidence/ml/drift_20261118T092731Z.json` | PARTIAL: evidence W2-A pass; registry saat freeze kosong dan retrain sekarang gagal karena kurang dari tiga event date berlabel |
| F-16 | Observability, metrics, structured logs, alerting | `src/bmip/observability/`, `deploy/prometheus/`, `deploy/alertmanager/` | `evidence/observability/CP1_20261120T0323_c9ef99a.json`, `evidence/alerts/CP2_20261120T0323_c9ef99a.json`, `evidence/alerts/T39_20261120T0304_e5369f6.md` | PASS |
| F-17 | Security: auth API, RBAC, TLS, secret/PII scan, ACL | `src/bmip/api/security.py`, `deploy/traefik/`, `scripts/w2c_scan.py` | `evidence/security/api-401.txt`, `evidence/security/rbac-matrix.md`, `evidence/security/tls.txt`, `evidence/security/gitleaks.txt`, `evidence/security/pii-scan.txt`, `evidence/security/tailscale-acl.json` | PASS |
| F-18 | Governance, catalog, lineage | `src/bmip/catalog/`, `scripts/w2c_*`, `dbt` OpenLineage | `evidence/catalog/CP2_20261121T101633.md`, `evidence/catalog/registry_20261121T101633.csv`, `evidence/lineage/CP1_20261121T101507.md`, `evidence/lineage/T30.md` | PASS |
| F-19 | Recovery, restart persistence, fault injection, benchmark | `scripts/w2d_backup.py`, `scripts/w2d_restore.py`, `scripts/w2d_restart.py`, `scripts/w2d_faults.py`, `scripts/w2d_benchmark.py` | `evidence/recovery/T19.txt`, `evidence/recovery/T40.json`, `evidence/faults/stream-kill_20261123T182353.json`, `evidence/faults/minio-kill_20261123T182601.json`, `evidence/benchmark/matrix.csv` | PARTIAL: backup/restore/T-40/dua fault PASS; benchmark matrix ada tetapi beberapa skenario partial |
| F-20 | Dokumentasi, evidence index, laporan/demo | `README.md`, `ARCHITECTURE.md`, `evidence/README.md`, `evidence/compliance/index.md` | `evidence/README.md`, `evidence/compliance/index.md`, `docs/spec-mapping.md` | PARTIAL: dokumen draft lengkap; clean clone T-25 dan final C3-D belum selesai |

## 2. Sebelas aspek penilaian

| Aspek | Bagian arsitektur | Implementasi | Evidence | Status |
| --- | --- | --- | --- | --- |
| Environment | Section 5 | `deploy/compose.base.yml`, `deploy/compose.dev.yml`, `deploy/compose.host-ml.yml` | `evidence/deploy/compose-config_20261111T1406_937a0ef.yml`, `evidence/recovery/T40.json` | PASS |
| Ingestion | Section 7 | `src/bmip/ingestion/` | `evidence/ingestion/`, `evidence/stream/` | PASS |
| Processing | Section 9 | `src/bmip/transform/`, `dbt/models/` | `evidence/tests/T03.txt`, `evidence/tests/T24.txt`, `evidence/e2e/M1_20261120T0323.txt` | PASS |
| Storage | Section 8 | MinIO, Iceberg, Lakekeeper | `evidence/storage/` | PASS |
| Query Layer | Section 10 | FastAPI, DuckDB, PostgreSQL serving | `evidence/api/`, `evidence/serving/` | PASS |
| Machine Learning | Section 11 | `src/bmip/ml/`, MLflow | `evidence/ml/`, `evidence/experiments/` | PARTIAL: registry kosong saat freeze, retrain terblokir jumlah event date |
| Dashboard and Visualization | Section 15 | Streamlit, Grafana | `evidence/dashboards/`, `evidence/dashboard/` | PASS |
| Alerting | Section 16 | Prometheus, Alertmanager, Telegram | `evidence/alerts/`, `evidence/observability/` | PASS |
| Security | Section 17 | API key, RBAC, TLS, Tailscale ACL | `evidence/security/` | PASS |
| Governance | Section 18 | Catalog, registry, lineage, audit | `evidence/catalog/`, `evidence/lineage/` | PASS |
| Orchestration | Section 12 | Prefect flows dan deployment | `evidence/deploy/prefect-*.json` | PASS |

## 3. Known gaps and next owners

| Gap | Dampak | Status | Next |
| --- | --- | --- | --- |
| `Spek.md` tidak ada | ID F-01..F-20 tidak dapat diverifikasi terhadap teks asli | partial | C3-D menyalin `Spek.md` atau menandai rekonstruksi ini sebagai final |
| Registry ML kosong dan data berlabel hanya dua event date | Inference mengembalikan `not_available`; training gagal | partial | C3-B / Dhea memperluas snapshot atau memilih model market-only |
| DQ `gold-market-lag` critical | Gate gold penuh tidak hijau pada snapshot sekarang | partial | C3-D menjalankan DQ-01..DQ-08 dengan data yang lebih baru |
| Clean clone T-25 | Instalasi, lint, dan compose config lulus; stack/dashboard belum | partial | C3-D menyelesaikan clone bersih dengan Docker stabil dan dashboard berisi |
| Coverage T-41 | Gate 40% lulus | pass | 51.30%, 186 test, `evidence/tests/coverage.json` |
| Benchmark throughput hanya satu laptop | Angka tidak mewakili profil empat node | partial | C3-D menjalankan B1-B4 dan mencatat variance |
