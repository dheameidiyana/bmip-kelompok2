# Evidence Index

Setiap klaim pada demo harus punya file bukti di direktori ini.

## Format nama file

```text
evidence/<area>/<ID>_<YYYYMMDDTHHMM>_<git-sha-pendek>.<ext>
```

Contoh: `evidence/tests/T04_20261113T1800_a1b2c3d.txt`

## Header wajib untuk file teks

```text
id        : T-04
timestamp : 2026-11-13T18:00:00Z
commit    : a1b2c3d
command   : make test
result    : PASS
owner     : dhea
```

## Environment

Isi saat evidence freeze:

- Commit SHA: `937a0ef` (commit kode dan docs yang diuji)
- Profil compose: `dev` (`deploy/compose.base.yml` + `deploy/compose.dev.yml`)
- OS / Docker / Compose: Windows 11 Home 10.0.26200 / Docker 29.7.2 / Compose 5.5.0
- Python: 3.11.9
- Tanggal: 2026-11-11
- Tag `w1-a-ok` menunjuk commit final W1-A setelah evidence ini di-commit.

W1-C menambahkan:

- Commit SHA: lihat header `commit` di tiap file W1-C (kode diuji: `3742fe9`).
- Base branch: `feat/silver-lois` (`fdaf360`), yaitu tag `w1-b-ok`; W1-B masuk ke
  `dev` lewat PR W1-C.
- Python: 3.11.9, Great Expectations 1.25.0, VADER 3.3.2.
- Lint: `ruff` + `sqlfluff` (config `.sqlfluff`) bersih; `e2e-smoke` PASS.
- Data: replay nyata Binance Vision `BTCUSDT-aggTrades-2026-11-10` pukul
  14:00-17:00 UTC, plus dua post fixture W1-A.
- Tag `w1-c-ok` menunjuk commit final W1-C setelah evidence di-commit.

## Indeks

| ID | Area | File | Status | Catatan |
| --- | --- | --- | --- | --- |
| CP1 | deploy | `deploy/health_20261111T1404_937a0ef.md` | PASS | 6 service hijau, bucket + namespace + ops tables |
| CP1 | deploy | `deploy/compose-config_20261111T1406_937a0ef.yml` | PASS | `docker compose config --no-interpolate` profil dev |
| CP2 | tests | `tests/T01.json` | PASS | social post valid (termasuk `ingest_ts`) lolos kontrak |
| CP2 | tests | `tests/T02.json` | PASS | harga negatif ditolak di `$.price` |
| CP2 | ingestion | `ingestion/counts_20261111T1405.csv` | PASS | bronze market 3 row, social 2 row |
| CP2 | batch | `batch/ledger_20261111T1405.csv` | PASS | market `succeeded`, social `succeeded`, checksum tercatat |
| T-26 | batch | `batch/T26.json` | PASS | dua replay `skipped_identical`; counts bronze tidak berubah |
| CP3 | ingestion | `ingestion/replay_20261111T1405.txt` | PASS | log lengkap dua run replay market + social |
| E2E-W1A | e2e | `e2e/SMOKE-W1A_20261111T1406_937a0ef.txt` | PASS | health + replay + bronze counts + ledger + idempotensi |

### W1-C

| ID | Area | File | Status | Catatan |
| --- | --- | --- | --- | --- |
| T-03 | tests | `tests/T03.txt` | PASS | tulis ulang `post_key` yang sama; count silver tidak berubah |
| T-09 | tests | `tests/T09.txt` | PASS | dua build; lonjakan harga di masa depan tidak menggeser fitur sebelumnya |
| T-10 | tests | `tests/T10.txt` | PASS | skor VADER selalu di [-1, 1] |
| T-11 | tests | `tests/T11.txt` | PASS | `trade_id` null memblokir gate gold |
| T-12 | tests | `tests/T12.txt` | PASS | duplicate rate 2,9% hanya warning, pipeline lanjut |
| T-31 | storage | `storage/T31.txt` | PASS | kolom nullable baru terbaca; snapshot lama tetap bisa dibuka |
| T-32 | storage | `storage/T32.json` | PASS | koreksi sumber mengubah jam yang benar |
| T-33 | storage | `storage/T33.json` | PASS | dua rerun menghasilkan hash logis identik |
| DQ | dq | `dq/dq_report.json` | PASS | checkpoint GX lengkap, 7 suite |
| DQ | dq | `dq/mart-counts_20261113T2223.csv` | PASS | jumlah baris per mart |
| PII | security | `security/pii-columns_20261113T2223.txt` | PASS | tidak ada URI, DID, atau handle mentah di silver |
| DBT | dbt | `dbt/docs.png` | PASS | halaman dbt docs `mart_ml` dengan kolom dan deskripsi |
| DBT | dbt | `dbt/docs_20261113T2230.txt` | PASS | katalog model dan kolom hasil `dbt docs generate` |
| E2E | e2e | `e2e/SMOKE-W1A_20261113T2226_3742fe9.txt` | PASS | health + replay + bronze counts + ledger + idempotensi, dengan warm-up |
| Prefect | deploy | `deploy/prefect-gold_20261113T2229_3742fe9.json` | PASS | flow `transform-gold` berstatus Completed lewat worker |
| W1-C | w1c | `w1c/SUMMARY_20261113T2223.json` | PASS | ringkasan satu baris per test |

### W1-D

Environment: profil `dev`, Windows 11 / Docker 29.2.1 / Compose v5, Python 3.11.9,
replay Binance Vision 2026-11-10 13:00-14:00 UTC (90.936 trade) plus dua post
fixture. Kode diuji: `0df6000` (API) dan `a58f5d7` (dashboard). Tag `w1-d-ok`
menunjuk commit final W1-D setelah evidence ini di-commit.

| ID | Area | File | Status | Catatan |
| --- | --- | --- | --- | --- |
| CP1 | api | `api/smoke_20261114T0239.txt` | PASS | health, 10 endpoint, baris market, freshness, request id |
| ROUTES | api | `api/routes_20261114T0239.txt` | PASS | 14 route kanonik + 5 alias; `contracts/openapi.json` ditulis |
| T-13 | security | `security/api-401.txt` | PASS | tanpa key / key salah → 401 problem+json; `/api` tetap publik |
| T-14 | tests | `tests/T14.txt` | PASS | 2 halaman live (limit=1) dan 11 halaman atas 1.002 baris, 0 duplikat |
| T-15 | tests | `tests/T15.txt` | PASS | MinIO stop → 200 `X-Data-Stale: true`; pulih → `false` |
| T-34 | api | `api/T34.json` | PASS | symbol, range, limit, cursor, datetime, missing range |
| T-36 | ml | `ml/T36.json` | PASS | W1-D contract; final W2-A run supersedes this row (see W2-A block) |
| IDEM | serving | `serving/loader-idempotence_20261114T0239.json` | PASS | dua load, counts + logical hash identik |
| T-37 | dashboard | `dashboard/reconciliation-draft.json` | PASS | API vs serving vs gold, 2/2 baris, 0 selisih (draft) |
| DQ | dq | `dq/dq_report_w1d_20261114T0255.json` | PASS | checkpoint GX run W1-D (`a58f5d7`); `dq_report.json` kanonik tetap milik W1-C |
| M1 | e2e | `e2e/M1_20261114T0405.txt` | PASS | bronze → silver → gold → serving → API → dashboard |
| DASH | dashboards | `dashboards/streamlit_20261114T0405.png` | PASS | 4 metrik, 2 filter, "belum ada model", Poppins, palet hitam-abu-putih-navy-pink, sidebar bisa ditutup/dibuka |

### W2-A

Environment: branch `slot/w2-a-dhea`, Windows / Docker Compose dev + ML overlay,
Python 3.11.9, MLflow 3.18.0. Five symbols, 60 days of 1-minute klines, pooled
model, champion `volatility_model` version 2. Evidence closeout: 2026-11-18;
code under test: `afa8617` plus the final evidence diff. Tag `w2-a-ok-complete`
menunjuk commit close-out lengkap; `w2-a-ok-final` tetap di `38f0441` dan tag
lama `w2-a-ok` tetap di `eec3186`.

| ID | Area | File | Status | Catatan |
| --- | --- | --- | --- | --- |
| CP1 | ml | `ml/dataset_20261118T044935Z.json` | PASS | snapshot `mart_ml@3627445140691597595`; 7.190 baris; 5 symbol |
| CP1 | tests | `tests/T09.txt` | PASS | T-09 feature-level, 7.200 baris `mart_ml` |
| CP2 | experiments | `experiments/E1_vs_E2.md` | PASS | E1/E2 Ridge/XGBoost; E1 promoted under H0; top features |
| CP2 | experiments | `experiments/mlflow_volatility_20261118T0719Z.png` | PASS | MLflow experiment `volatility`; tags, bad challenger |
| CP2 | ml | `ml/feature_importance_20261118T143530Z.json` | PASS | model-native top features; `rv_60m` 35.60% |
| BASELINE | experiments | `experiments/baselines.md` | PASS | persistence + EWMA `alpha=0.06`, shifted one hour |
| BASELINE | experiments | `experiments/baselines_20261118T092655Z.json` | PASS | validation/test MAE, RMSE, R2, Spearman |
| T-20 | ml | `ml/T20.txt` | PASS | retrain snapshot sama; delta 0.00000000%; tolerance 1% |
| T-21 | ml | `ml/T21.json` | PASS | bad challenger v4 rejected vs champion v2; champion unchanged |
| T-36 | ml | `ml/T36.json` | PASS | 422 malformed; 200 error out-of-range; 5 symbol `ok` with `feature_ts`; stale response persisted as `status=error` |
| MODEL | ml | `ml/model-card.md` | PASS | intended use, feature importance, baselines, out-of-scope, limitations, ethical note |
| REGISTRY | ml | `ml/registry-metadata_20261118T154807Z.json` | PASS | snapshot/feature/trigger/git tags + model-card and feature-importance artifacts |
| BATCH | ml | `ml/predictions_20261118T054850Z.json` | PASS | historical 5 predictions written to `serving.predictions` |
| BATCH | ml | `ml/predictions_20261118T093616Z.json` | PASS | stale snapshot rejected; non-zero exit; cache not overwritten |
| HEALTH | ml | `ml/predictions_health_20261118T154754Z.json` | PASS | stale `ok` rows cleaned; final `stale_ok=0` |
| SCHEDULE | deploy | `deploy/prefect_w2a_20261118T155105_afa8617.json` | PASS | hourly `infer-volatility` active + 1 completed run; weekly `train-volatility` inactive |
| DRIFT | ml | `ml/drift_20261118T092731Z.json` | PASS | holdout reference vs 7 production days; PSI 0.2; 7 flags |
| CLOSEOUT | tests | `tests/w2a_complete_20261118T155136Z.txt` | PASS | pytest 153 + ruff clean on complete worktree |


### W2-B

Environment: branch `slot/w2-b-vio`, base `slot/w2-a-dhea` (`6fbcf98`),
Windows 11 / Docker Compose dev, Python 3.11.9, Prometheus v2.55.1,
Alertmanager v0.27.0, Grafana 11.3.0, cAdvisor v0.49.1. Evidence 2026-11-20;
kode yang diuji: `c9ef99a` (tag `w2-b-ok`).

| ID | Area | File | Status | Catatan |
| --- | --- | --- | --- | --- |
| CP1 | observability | `observability/CP1_20261120T0323_c9ef99a.json` | PASS | 6/6 target; 40 baris log; 6 field kontrak |
| CP2 | alerts | `alerts/CP2_20261120T0323_c9ef99a.json` | PASS | 16 rule, 3 kelas, 3 runbook, 5 panel business |
| CP2 | alerts | `alerts/rules_20261120T0323_c9ef99a.yml` | PASS | salinan rule yang ter-load Prometheus |
| T-39 | alerts | `alerts/T39_20261120T0304_e5369f6.md` | PASS | 3 kelas fire -> deliver -> resolve |
| T-39 | alerts | `alerts/deliveries.jsonl` | PASS | `run_id=drill-...` ikut di pesan firing dan resolved |
| T-39 | alerts | `alerts/TELEGRAM_20261120T0249_3a87740.json` | PASS | Telegram `ok: true`, HTTP 200 untuk firing dan resolved |
| T-39 | alerts | `alerts/telegram_20261121.png` | PASS | screenshot pesan Indonesia (AKTIF + SELESAI) |
| T-39 | alerts | `alerts/telegram_20261120.png` | arsip | format lama sebelum perbaikan |
| T-37 | dashboard | `dashboard/reconciliation_20261120T0324_c9ef99a.json` | PASS | API vs SQL vs Iceberg, 24 jam dan 7 hari, 0 selisih |
| LOG | logs | `logs/sample_20261120T0323_c9ef99a.jsonl` | PASS | `run_id`, `request_id`, `service`, `severity` |
| LOG | logs | `logs/error_20261120T0324_c9ef99a.jsonl` | PASS | satu baris `severity=ERROR` dengan traceback |
| LOG | logs | `logs/diagnosis_error_20261120T0324_c9ef99a.json` | PASS | frame gagal dan baris exception terakhir |
| LOG | logs | `logs/dashboard_20261120T0334_b52ce90.jsonl` | PASS | dashboard JSON log, `service=dashboard` |
| DASH | dashboards | `dashboards/grafana-pipeline_20261120T0324_c9ef99a.png` | PASS | URL dan range tertulis di panel; 6 target hijau |
| DASH | dashboards | `dashboards/grafana-business_20261120T0324_c9ef99a.png` | PASS | harga, volatilitas, sentimen berisi; prediksi kosong |
| E2E | e2e | `e2e/SMOKE-W1A_20261120T0150_ee4c8bf.txt` | PASS | health, replay, bronze, ledger, idempotensi |
| M1 | e2e | `e2e/M1_20261120T0323.txt` | PASS | bronze -> silver -> gold -> serving -> API -> dashboard |
| DQ | dq | `dq/dq_report.json` | PASS | 7 suite, 0 critical, 0 warning |
| SUM | w2b | `w2b/SUMMARY_20261120T0324_c9ef99a.json` | PASS | ringkasan run terakhir |
| ML | deploy | `deploy/mlflow-health_20261121T0532_a6b33fc.json` | PASS | MLflow sehat (1 worker); registry kosong, prediksi belum bisa |
