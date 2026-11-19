# Runbook — service and resource

Covers: `BmipApiDown`, `BmipStreamDown`, `BmipTargetDown`, `BmipApiErrorRate`,
`BmipApiLatencyHigh`, `BmipContainerCpuHigh`, `BmipContainerMemoryHigh`.

## Gejala

- Telegram: `[FIRING] BmipApiDown` atau `BmipTargetDown`.
- Grafana → **BMIP · Pipeline**: tile *Scrape targets up* merah.
- `curl http://localhost:8080/api/health/ready` gagal atau mengembalikan 503.
- Panel *Latency* di atas 1 detik.

## Cek (2 menit)

```powershell
# container dan healthcheck
docker compose --env-file .env -f deploy/compose.base.yml -f deploy/compose.dev.yml ps

# log terakhir, difilter ke level error
docker compose --env-file .env -f deploy/compose.base.yml -f deploy/compose.dev.yml logs --tail 50 api |
  Select-String '"severity":"ERROR"'

# target mana yang turun
(Invoke-WebRequest http://localhost:9090/api/v1/targets).Content | Select-String '"health":"down"'
```

Log sekarang JSON, jadi `request_id` bisa dipakai untuk melacak satu request
dari error sampai response. Contoh satu baris yang sudah didiagnosis ada di
`evidence/logs/sample_<ts>.jsonl`.

## Tindakan

1. **API down** — `docker compose ... up -d api`. Kalau langsung mati lagi,
   baca log: `ModuleNotFoundError` berarti image perlu rebuild,
   `ServingNotReady` berarti serving kosong (bukan API-nya yang salah).
2. **Latency tinggi** — cek `bmip_api_fallback_total`. Kalau naik terus,
   jalur lake (DuckDB → Iceberg) gagal dan API jatuh ke PostgreSQL. Periksa
   MinIO dan Lakekeeper sebelum menaikkan timeout.
3. **Memory/CPU tinggi** — bandingkan dengan `mem_limit`/`cpus` di
   `deploy/compose.dev.yml`. Kalau container memang butuh lebih, ubah limit
   dan catat di handoff; jangan mematikan exporter.
4. **Target down** — `pushgateway`, `postgres-exporter`, atau `cadvisor`.
   `cadvisor` di Docker Desktop Windows bisa gagal mount; kalau begitu,
   catat sebagai keterbatasan dan andalkan metrik container dari sumber lain.

## Eskalasi

- Kalau API tidak pulih dalam 10 menit: aktifkan fallback dengan memastikan
  `serving.*` terisi (`make serving`), lalu beri tahu W2-C karena dashboard
  ikut membaca API.
- Jangan menghapus target dari `prometheus.yml` supaya alert hijau. Target
  yang mati adalah temuan, bukan gangguan.
