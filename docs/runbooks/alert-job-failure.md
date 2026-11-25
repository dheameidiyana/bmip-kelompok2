# Runbook — job failure

Covers: `BmipBatchJobStale`, `BmipDqCriticalFailures`, `BmipGoldRowsMissing`,
`BmipPredictionsFailed`.

## Gejala

- Telegram: `[FIRING] BmipDqCriticalFailures` atau `BmipBatchJobStale`.
- Grafana → **BMIP · Pipeline**: panel *Batch duration* kosong atau
  *DQ failures* bernilai lebih dari 0; panel *Gold rows* nol.
- `make gold` atau `make quality` keluar dengan kode 1.

## Cek (2 menit)

```powershell
# 1. status run terakhir
docker compose --env-file .env -f deploy/compose.base.yml -f deploy/compose.dev.yml ps
python -m prefect deployment run "transform-gold/transform-gold" --help

# 2. laporan gate terakhir
Get-Content evidence/dq/dq_report.json | Select-Object -First 30

# 3. metrik yang dipakai alert
(Invoke-WebRequest http://localhost:9090/api/v1/query?query=bmip_last_success_timestamp_seconds).Content
```

Yang dicari: nama suite dan id rule yang gagal di `dq_report.json`, misalnya
`silver_market_trades:market-trade-id-present`.

## Tindakan

1. **Critical di silver** — gold tidak dipublish. Perbaiki sumbernya dulu
   (kontrak, replay, atau data bronze), lalu jalankan ulang:
   `python scripts/build_gold.py`.
2. **Critical di gold** — jalankan `python scripts/quality.py --scope gold`
   untuk melihat rule yang gagal; kalau datanya memang salah, backfill jam
   yang rusak: `python scripts/build_gold.py --start ... --end ...`.
3. **Hanya warning** — pipeline boleh lanjut. Catat angkanya di handoff;
   jangan memakai `--warning-only` untuk menyembunyikan critical.
4. **PredictionsFailed** — cek `feature_ts` pada `evidence/ml/predictions_*.json`.
   Feature lebih tua dari 7200 detik akan ditolak; perbaiki jadwal
   `infer-volatility`, bukan ambangnya.

## Eskalasi

- Jika rule yang sama gagal dua kali berturut-turut: hentikan jadwal
  `transform-gold`, catat di `docs/handoff/w2-b.md`, dan beri tahu pemilik
  slot berikutnya (W2-C) karena serving akan memakai data lama.
- Jangan menaikkan threshold alert tanpa memperbarui
  `deploy/observability/rules.yml` dan mencatat alasannya di ADR.
