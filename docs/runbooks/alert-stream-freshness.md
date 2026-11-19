# Runbook — stream lag and freshness

Covers: `BmipConsumerLagHigh`, `BmipStreamIdle`, `BmipSilverFreshnessBreach`,
`BmipGoldFreshnessBreach`, `BmipSilverBarAgeHigh`.

## Gejala

- Telegram: `[FIRING] BmipConsumerLagHigh` atau `BmipGoldFreshnessBreach`.
- Grafana → **BMIP · Pipeline**: panel *Consumer lag* naik terus, atau
  *Freshness* melewati 5400 detik (90 menit).
- Dashboard menampilkan badge **stale**.

## Cek (2 menit)

```powershell
# lag dan offset per partisi
python -m bmip.transform.cli lag --group ohlcv-builder

# metrik yang sedang dilihat Prometheus
(Invoke-WebRequest "http://localhost:9090/api/v1/query?query=bmip_freshness_seconds").Content

# apakah processor hidup
(Invoke-WebRequest http://localhost:9101/metrics).Content | Select-String "bmip_ingest_events_total"
```

Baca tiga angka: `bmip_consumer_lag`, `bmip_freshness_seconds{job="stream"}`,
dan `bmip_freshness_seconds{layer="gold"}`. Kalau lag tinggi **dan** freshness
tinggi, masalahnya di processor. Kalau lag rendah tapi freshness tinggi,
masalahnya di jadwal gold.

## Tindakan

1. **Processor mati** — jalankan `make stream` (atau
   `python -m bmip.transform.cli stream --follow`), lalu lihat lag turun.
2. **Lag tinggi tapi processor hidup** — throughput. Kurangi
   `STREAM_POLL_MAX_RECORDS`, atau jalankan replay di luar jam demo. Jangan
   menghapus consumer group: offset hilang berarti data diproses ulang.
3. **Freshness gold tinggi, silver normal** — `transform-gold` tidak jalan.
   Jalankan `python scripts/build_gold.py`; kalau perlu backfill jam yang
   tertinggal dengan `--start/--end`.
4. **Replay historis** — freshness terhadap jam dinding memang akan merah.
   Untuk demo, set `BMIP_AS_OF` ke ujung window replay supaya badge dan alert
   memakai clock yang sama.

## Eskalasi

- Kalau lag tidak turun setelah 30 menit: catat `bmip_consumer_lag` dan
  `bmip_ingest_events_total` di handoff, lalu minta W2-D (Lois) melihat
  throughput `recompute_ohlcv` — backlog ini sudah tercatat sejak W1-C.
- Jangan menurunkan threshold freshness agar alert hilang; ubah hanya kalau
  SLO-nya memang berubah, dan tulis di ADR.
