# Handoff W2-B - Vio

- Owner: Vio
- Branch: `slot/w2-b-vio`
- Base: `slot/w2-a-dhea` (`6fbcf98`, plus `af1734e` merged: MLflow `--workers 1`), which already contains `dev` (`9972693`)
- Handoff to: Anin (W2-C)
- Last update: 2026-11-20

## Status

- CP1: PASS
- CP2: PASS
- CP3: PASS
- Tag: `w2-b-ok`

Gate: enam target ter-scrape, dua dashboard Grafana hidup dengan data nyata,
16 rule dalam tiga kelas ter-load, tiga kelas alert terbukti fire → deliver →
resolve dengan `run_id`, T-37 cocok untuk 24 jam dan 7 hari, `e2e-smoke`
hijau, dan pesan Telegram terkirim (HTTP 200 untuk firing dan resolved).

## Angka pada handoff ini

| Item | Nilai |
| :-- | :-- |
| Scrape target | 6/6 up (`api`, `stream`, `prometheus`, `pushgateway`, `postgres`, `cadvisor`) |
| Metrik pipeline | 7/9 hadir; `bmip_gold_rows` dan `bmip_predictions_total` belum ada baris |
| Alert rule | 16 (job 4, stream 5, service 7) |
| Dashboard | 2 (`pipeline`, `business`) |
| Drill | 3 alert firing, 3 resolved, 6 delivery, `run_id=drill-...` |
| T-37 | 3 kunci, 0 selisih, 24 jam dan 7 hari |
| Log | 40 baris INFO + 1 baris ERROR, 6 field kontrak |
| E2E | PASS (`SMOKE-W1A_20261120T0150_ee4c8bf.txt`) |
| Telegram | 2 pesan terkirim (firing + resolved), `ok: true`, HTTP 200 |

## Yang sudah jalan

### Prometheus dan exporter

- Enam scrape target: `prometheus`, `api`, `stream`, `pushgateway`,
  `postgres`, `cadvisor` (`deploy/observability/prometheus.yml`).
- API dan stream processor diekspos lewat `/metrics`; job batch memakai
  Pushgateway karena prosesnya keluar sebelum bisa di-scrape.
- Retensi 7 hari, evaluasi 15 detik, `--web.enable-lifecycle` untuk reload.

### Sembilan metrik pipeline

| Metrik | Sumber |
| :-- | :-- |
| `bmip_ingest_events_total` | stream processor |
| `bmip_duplicate_total` | stream processor |
| `bmip_quarantine_total` | stream processor |
| `bmip_consumer_lag` | stream processor |
| `bmip_freshness_seconds` | stream (`job="stream"`) dan gold (`layer="gold"`) |
| `bmip_batch_duration_seconds` | `scripts/build_gold.py`, `scripts/quality.py`, `scripts/w2a_batch.py` |
| `bmip_gold_rows` | `scripts/build_gold.py` |
| `bmip_dq_failures_total` | `scripts/quality.py` |
| `bmip_predictions_total` | `scripts/w2a_batch.py` |

Setiap sampel batch membawa label `run_id` (dari `BMIP_RUN_ID` atau
`<job>-<UTC>`), sehingga pesan alert menyebut run yang menyebabkannya.

### Log JSON enam field

`bmip.common.logging` menulis `timestamp`, `severity`, `service`, `logger`,
`message`, plus `run_id` dan setiap atribut `ctx_*` sebagai nama tanpa prefix —
`ctx_request_id` menjadi `request_id`. API memakai `run_id="api-<started>"`,
stream memakai `stream-<started>` atau `BMIP_RUN_ID`. Dashboard dan notifier
juga memanggil `configure_logging` dengan service masing-masing. Bukti untuk
dashboard diambil dengan menjalankan skripnya lewat `streamlit.testing` dan
menyimpan 8 baris JSON (`service=dashboard`, termasuk `dashboard started`).

### Grafana sebagai kode

- `deploy/observability/grafana/provisioning/` berisi datasource Prometheus
  (uid `prometheus`) dan PostgreSQL (uid `serving`).
- Dashboard `pipeline` (uid `bmip-pipeline`): URL + rentang waktu, freshness,
  consumer lag, batch duration, DQ failures, gold rows, scrape targets.
- Dashboard `business` (uid `bmip-business`): URL + rentang waktu, harga close,
  volatilitas terealisasi, sentimen per jam, tabel prediksi.

### Alerting

- 16 rule di `deploy/observability/rules.yml`, tiga kelas: `job-failure` (4),
  `stream-lag` (5), `service` (7).
- Empat rule batch membawa label `run_id: "{{ $labels.run_id }}"`.
- Alertmanager merutekan semuanya ke `notify:8080/alert`; notifier menulis
  `evidence/alerts/alerts.jsonl` + `deliveries.jsonl` dan mengirim ke Telegram
  bila `TELEGRAM_BOT_TOKEN` dan `TELEGRAM_CHAT_ID` diisi.
- Tiga runbook: `docs/runbooks/alert-job-failure.md`,
  `alert-stream-freshness.md`, `alert-service-resource.md`.
- Pesan Telegram berbahasa Indonesia dan memuat: ringkasan, kelas/pemilik/
  `run_id`, detail, dampak, langkah pertama, kode rule, dan link runbook.
- `BmipTargetDown` mengecualikan `api` dan `stream`, jadi satu gangguan
  hanya menghasilkan satu pesan.
- `runbook_url` menunjuk ke tag `w2-b-ok`, bukan `dev`, supaya tautannya hidup
  sekarang dan tetap hidup setelah PR merge.

## Cara menjalankan

```powershell
# 1. stack utama + observability
docker compose --env-file .env -f deploy/compose.base.yml -f deploy/compose.dev.yml up -d --build

# 2. cek target dan metrik
python scripts/w2b_metrics_check.py

# 3. CP1/CP2 + contoh log ERROR
python scripts/w2b_evidence.py --steps cp1,cp2,logerror

# 4. T-39: tiga kelas alert fire -> deliver -> resolve (butuh cadvisor hidup)
python scripts/w2b_evidence.py --steps drill

# 5. T-37: dashboard vs API vs SQL, 24 jam dan 7 hari
python scripts/w2b_evidence.py --steps reconcile

# 6. gate integrasi
python scripts/e2e_smoke.py
```

URL:

| Layanan | URL |
| :-- | :-- |
| Grafana | http://localhost:3000 (dashboard `bmip-pipeline`, `bmip-business`) |
| Prometheus | http://localhost:9090 |
| Alertmanager | http://localhost:9093 |
| Pushgateway | http://localhost:9091 |
| Notifier | http://localhost:8081/healthz, `/deliveries` |

Setelah mengubah rule atau notifier:

```powershell
docker compose --env-file .env -f deploy/compose.base.yml -f deploy/compose.dev.yml build notify
docker compose --env-file .env -f deploy/compose.base.yml -f deploy/compose.dev.yml up -d --force-recreate notify
curl -X POST http://localhost:9090/-/reload
```

Rule dibaca dari file yang di-mount, jadi cukup reload Prometheus; notifier
perlu image baru karena kodenya ikut di dalam image.

Untuk Telegram, isi dua variabel di `.env` lalu jalankan ulang container
`notify`; tidak ada perubahan kode:

```text
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_CHAT_ID=123456789
```

## Kegagalan yang diketahui

| Gejala | Penyebab | Workaround |
| :-- | :-- | :-- |
| Target `stream` DOWN | processor hanya hidup saat `make stream` | jalankan replay; `BmipStreamDown` memang warning |
| API butuh ~7 menit saat start | entrypoint `bmip.ml.api` mencoba champion MLflow yang tidak hidup | tunggu, atau jalankan overlay `compose.ml.yml` |
| `build_gold` gagal di dbt | DuckDB crash `0xC0000409` saat membaca Iceberg di mesin ini | metrik gold tidak terisi; lihat gap |
| Dashboard business kosong | rentang waktu default di luar window replay | pakai `now-30d` (sudah jadi default) |
| Alert tidak sampai ke Telegram | `TELEGRAM_CHAT_ID` kosong | notifier menulis `deliveries.jsonl` (`skipped: true`) |
| `BmipTargetDown` untuk stream | sengaja dikecualikan (`job!="stream"`) | gunakan `BmipStreamDown` |

## Gap yang harus dibaca W2-C

- **`bmip_gold_rows` belum punya baris.** `build_gold.py` gagal di langkah dbt
  pada mesin ini (DuckDB crash `0xC0000409` saat membaca Iceberg), jadi publish
  tidak selesai. Metrik dan panelnya sudah terpasang.
- **`bmip_predictions_total` belum ada baris.** Fix W2-A `--workers 1`
  (`af1734e`) sudah di-merge dan server MLflow sekarang sehat (`/health` 200).
  Tetapi registry di mesin ini kosong (hanya experiment `Default`), jadi
  `scripts/w2a_batch.py` tidak punya champion. Perlu restore registry/artefak
  atau retrain sebelum prediksi bisa dihasilkan.
- **Panel dan alert model drift (Should) belum ada.** W2-A menaruh drift di
  berkas JSON dan menunda `serving.drift_metrics`; tidak ada metrik Prometheus
  yang bisa dipakai tanpa mengubah skrip W2-A.
- **PR + review** dilakukan Lois di akhir rantai (kesepakatan tim).

## Langkah berikutnya untuk Anin (W2-C)

1. Baca `docs/adr/0003-w2-b-observability.md` sebelum mengubah rule atau
   datasource.
2. Jangan mengubah nama metrik: dashboard dan 16 rule memakai nama itu.
3. Kalau menambah target scrape, tambahkan alert-nya dan perbarui
   `tests/unit/test_alert_rules.py`.
4. `T-37` memakai `serving.market_hourly` sebagai kaki "dashboard"; kalau
   skema serving berubah, perbarui `scripts/w2b_evidence.py`.
5. Setelah W2-C selesai, Lois (W2-D) yang membuat PR ke `dev`. Jangan rebase
   `slot/w2-b-vio` setelah Anin menariknya.

## Evidence

| ID | File | Isi |
| :-- | :-- | :-- |
| CP1 | `evidence/observability/CP1_20261120T0323_c9ef99a.json` | 6/6 target, 6 field log, 40 baris |
| CP2 | `evidence/alerts/CP2_20261120T0323_c9ef99a.json` | 16 rule, 3 kelas, 3 runbook |
| CP2 | `evidence/alerts/rules_20261120T0323_c9ef99a.yml` | salinan rule yang ter-load |
| T-39 | `evidence/alerts/T39_20261120T0304_e5369f6.md` | timeline fire → deliver → resolve |
| T-39 | `evidence/alerts/deliveries.jsonl` | delivery mentah, `run_id` terisi |
| T-39 | `evidence/alerts/TELEGRAM_20261120T0249_3a87740.json` | bukti Telegram HTTP 200 (firing + resolved) |
| T-39 | `evidence/alerts/telegram_20261121.png` | screenshot pesan Indonesia (AKTIF + SELESAI) |
| T-39 | `evidence/alerts/telegram_20261120.png` | format lama sebelum perbaikan (arsip) |
| T-37 | `evidence/dashboard/reconciliation_20261120T0324_c9ef99a.json` | API vs SQL vs Iceberg |
| LOG | `evidence/logs/sample_20261120T0323_c9ef99a.jsonl` | log JSON API |
| LOG | `evidence/logs/error_20261120T0324_c9ef99a.jsonl` | satu baris ERROR |
| LOG | `evidence/logs/diagnosis_error_20261120T0324_c9ef99a.json` | diagnosis error |
| LOG | `evidence/logs/dashboard_20261120T0334_b52ce90.jsonl` | dashboard menulis JSON (`service=dashboard`) |
| DASH | `evidence/dashboards/grafana-pipeline_20261120T0324_c9ef99a.png` | dashboard pipeline |
| DASH | `evidence/dashboards/grafana-business_20261120T0324_c9ef99a.png` | dashboard business |
| E2E | `evidence/e2e/SMOKE-W1A_20261120T0150_ee4c8bf.txt` | gate integrasi W1-A |
| M1 | `evidence/e2e/M1_20261120T0323.txt` | bronze -> silver -> gold -> serving -> API -> dashboard |
| DQ | `evidence/dq/dq_report.json` | checkpoint 7 suite |
| SUM | `evidence/w2b/SUMMARY_20261120T0324_c9ef99a.json` | ringkasan run |
| ML | `evidence/deploy/mlflow-health_20261121T0532_a6b33fc.json` | MLflow sehat dengan 1 worker; registry kosong |

Semua file dihasilkan oleh `scripts/w2b_evidence.py`, `scripts/quality.py`,
`scripts/e2e_smoke.py`, dan `scripts/w2b_metrics_check.py`; tidak ada yang
ditulis tangan.
