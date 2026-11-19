# Handoff W2-B - Vio

- Owner: Vio
- Branch: `slot/w2-b-vio`
- Base: `slot/w2-a-dhea` (`6fbcf98`), which already contains `dev` (`9972693`)
- Handoff to: Anin (W2-C)
- Last update: 2026-11-19

## Status

- CP1: PASS
- CP2: PASS
- CP3: PASS
- Tag: `w2-b-ok` (dibuat setelah commit evidence)

Gate: enam target ter-scrape, dua dashboard Grafana hidup dengan data nyata,
16 rule dalam tiga kelas ter-load, tiga kelas alert terbukti fire → deliver →
resolve, dan T-37 cocok untuk 24 jam dan 7 hari.

## Angka pada handoff ini

| Item | Nilai |
| :-- | :-- |
| Scrape target | 6/6 up (`api`, `stream`, `prometheus`, `pushgateway`, `postgres`, `cadvisor`) |
| Metrik pipeline | 7/9 hadir; `bmip_gold_rows` dan `bmip_predictions_total` belum ada baris |
| Alert rule | 16 (job 4, stream 5, service 7) |
| Dashboard | 2 (`pipeline`, `business`) |
| Drill | 3 alert firing, 3 resolved, 6 delivery |
| T-37 | 3 kunci, 0 selisih, 24 jam dan 7 hari |
| Log sample | 40 baris JSON, 6 field kontrak |

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

Semua push bersifat best-effort: tanpa `PUSHGATEWAY_URL`, job tetap jalan dan
tidak menulis metrik.

### Log JSON enam field

`bmip.common.logging` sekarang menulis `timestamp`, `severity`, `service`,
`logger`, `message`, plus `run_id` (kalau di-set) dan setiap atribut `ctx_*`
sebagai nama tanpa prefix — jadi `ctx_request_id` menjadi `request_id`.
`configure_logging(level, service=...)` dipanggil API dengan `service="api"`.

### Grafana sebagai kode

- `deploy/observability/grafana/provisioning/` berisi datasource Prometheus
  (uid `prometheus`) dan PostgreSQL (uid `serving`).
- Dashboard `pipeline` (uid `bmip-pipeline`): freshness, consumer lag, batch
  duration, DQ failures, gold rows, scrape targets.
- Dashboard `business` (uid `bmip-business`): harga close, volatilitas
  terealisasi, sentimen per jam, tabel prediksi — semuanya dari `serving.*`.

### Alerting

- 16 rule di `deploy/observability/rules.yml`, tiga kelas: `job-failure` (4),
  `stream-lag` (5), `service` (7).
- Setiap rule punya `severity`, `owner`, `channel`, `alert_class`, dan
  `runbook_url`.
- Alertmanager merutekan semuanya ke `notify:8080/alert`; notifier menulis
  `evidence/alerts/alerts.jsonl` + `deliveries.jsonl` dan mengirim ke Telegram
  bila `TELEGRAM_BOT_TOKEN` dan `TELEGRAM_CHAT_ID` diisi.
- Tiga runbook: `docs/runbooks/alert-job-failure.md`,
  `alert-stream-freshness.md`, `alert-service-resource.md`.

## Cara menjalankan

```powershell
# 1. stack utama + observability
docker compose --env-file .env -f deploy/compose.base.yml -f deploy/compose.dev.yml up -d --build

# 2. cek target dan metrik
python scripts/w2b_metrics_check.py

# 3. CP1/CP2 evidence
python scripts/w2b_evidence.py --steps cp1,cp2

# 4. T-39: tiga kelas alert fire -> deliver -> resolve (butuh api hidup)
python scripts/w2b_evidence.py --steps drill

# 5. T-37: dashboard vs API vs SQL, 24 jam dan 7 hari
python scripts/w2b_evidence.py --steps reconcile
```

URL:

| Layanan | URL |
| :-- | :-- |
| Grafana | http://localhost:3000 (dashboard `bmip-pipeline`, `bmip-business`) |
| Prometheus | http://localhost:9090 |
| Alertmanager | http://localhost:9093 |
| Pushgateway | http://localhost:9091 |
| Notifier | http://localhost:8081/healthz, `/deliveries` |

Untuk Telegram, isi dua variabel di `.env` lalu jalankan ulang container
`notify`; tidak ada perubahan konfigurasi lain:

```text
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_CHAT_ID=123456789
```

## Kegagalan yang diketahui

| Gejala | Penyebab | Workaround |
| :-- | :-- | :-- |
| Target `stream` DOWN | processor hanya hidup saat `make stream` | jalankan replay; alert `BmipStreamDown` memang warning |
| cAdvisor gagal start di Windows | mount host tidak lengkap di Docker Desktop | catat sebagai keterbatasan; metrik container tidak lengkap |
| Grafana tidak bisa menulis | bind mount provisioning read-only | provisioning memang read-only; ubah file lalu restart |
| Alert tidak sampai ke Telegram | token kosong | notifier tetap menulis `deliveries.jsonl` (`skipped: true`) |
| `BmipTargetDown` untuk stream | sengaja dikecualikan (`job!="stream"`) | gunakan `BmipStreamDown` |

## Langkah berikutnya untuk Anin (W2-C)

1. Baca `docs/adr/0003-w2-b-observability.md` sebelum mengubah rule atau
   datasource.
2. Jangan mengubah nama metrik: dashboard dan 16 rule memakai nama itu.
3. Kalau menambah target scrape, tambahkan juga alert untuk target itu dan
   perbarui `tests/unit/test_alert_rules.py`.
4. `T-37` memakai `serving.market_hourly` sebagai kaki "dashboard"; kalau
   skema serving berubah, perbarui `scripts/w2b_evidence.py` sekaligus.
5. Setelah W2-C selesai, Lois (W2-D) yang membuat PR ke `dev`. Jangan rebase
   `slot/w2-b-vio` setelah Anin menariknya.

## Evidence

| ID | File | Isi |
| :-- | :-- | :-- |
| CP1 | `evidence/observability/CP1_20261119T1815_6fbcf98.json` | 6/6 target, 6 panel, log sample |
| CP2 | `evidence/alerts/CP2_20261119T1814_6fbcf98.json` | 16 rule, 3 kelas, 3 runbook |
| CP2 | `evidence/alerts/rules_20261119T1814_6fbcf98.yml` | salinan rule yang ter-load |
| T-39 | `evidence/alerts/T39_20261119T1820_6fbcf98.md` | timeline fire ? deliver ? resolve |
| T-39 | `evidence/alerts/deliveries.jsonl` | 6 delivery mentah dari notifier |
| T-37 | `evidence/dashboard/reconciliation_20261119T1815_6fbcf98.json` | API vs SQL vs Iceberg, 24 jam + 7 hari |
| LOG | `evidence/logs/sample_20261119T1815_6fbcf98.jsonl` | log JSON API |
| LOG | `evidence/logs/diagnosis_20261119T1815_6fbcf98.json` | diagnosis satu error 400 |
| DASH | `evidence/dashboards/grafana-pipeline_20261119T1836_6fbcf98.png` | dashboard pipeline |
| DASH | `evidence/dashboards/grafana-business_20261119T1838_6fbcf98.png` | dashboard business |
| DQ | `evidence/dq/dq_report.json` | checkpoint 7 suite |
| SUM | `evidence/w2b/SUMMARY_20261119T1820_6fbcf98.json` | ringkasan run |

Semua file dihasilkan oleh `scripts/w2b_evidence.py`, `scripts/quality.py`,
dan `scripts/w2b_metrics_check.py`; tidak ada yang ditulis tangan.

## Gap yang harus dibaca W2-C

- **`bmip_gold_rows` belum punya baris.** `build_gold.py` gagal di langkah dbt
  pada mesin ini (DuckDB crash `0xC0000409` saat membaca Iceberg), jadi publish
  tidak selesai. Metrik dan panelnya sudah terpasang dan akan terisi pada run
  dbt yang sukses. `bmip_batch_duration_seconds{job="gold",status="failed"}`
  mencatat kegagalan itu, bukan menyembunyikannya.
- **`bmip_predictions_total` belum ada baris.** Butuh satu run
  `scripts/w2a_batch.py` dengan MLflow hidup; panel "Prediksi terbaru" kosong
  sampai itu dijalankan.
- **Telegram dalam mode berkas.** `TELEGRAM_BOT_TOKEN` kosong, jadi notifier
  menulis `deliveries.jsonl` dengan `skipped: true`. Isi token di `.env` lalu
  restart `notify`; tidak ada perubahan kode.
- **Stream target on-demand.** Processor hanya hidup saat `make stream`
  dijalankan; `BmipStreamDown` memang warning.

Catatan tambahan: `BmipStreamIdle` juga menyala sendiri pada 18:51 ketika replay
selesai dan topic kosong (tercatat di `deliveries.jsonl`). Itu bukan bagian
drill, jadi aturan keempat terbukti tanpa disuntik.
