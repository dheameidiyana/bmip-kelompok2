# Runbook: API fallback ke PostgreSQL (C3-A)

## What this covers

Range endpoint API membaca Iceberg lewat DuckDB. Jika lake lambat atau gagal,
API jatuh ke tabel `serving.*` di PostgreSQL dan mengirim `X-Data-Stale: true`.

## Gejala

- Response 200 tetapi header `X-Data-Stale: true`.
- `meta.source` = `serving`, bukan `lake`.
- `bmip_api_fallback_total` naik.
- Data range lebih pendek dari yang diminta.

## Cek cepat

```powershell
$key = (Select-String -Path .env -Pattern '^BMIP_API_KEY=').Line.Split('=',2)[1]
curl.exe -s -D - -o NUL "http://localhost:8000/v1/market/ohlc?symbol=BTCUSDT&limit=5" -H "X-API-Key: $key"
curl.exe -s http://localhost:8000/metrics | Select-String "bmip_api_fallback_total"
```

## Tindakan

1. Cek lake:
   ```powershell
   docker compose --env-file .env -f deploy/compose.base.yml -f deploy/compose.dev.yml ps minio lakekeeper
   ```
2. Kalau Lakekeeper/MinIO sehat, cek log API:
   ```powershell
   docker logs bmip-api-1 --tail 100 | Select-String "fallback|iceberg|lake"
   ```
3. Kalau lake bermasalah, API tetap melayani dari serving. Jangan restart API
   hanya karena `X-Data-Stale: true`; itu perilaku yang diharapkan.
4. Setelah lake pulih, minta request baru (cache 30 detik) dan pastikan
   `meta.source` kembali `lake`.

## Eskalasi

Kalau `X-Data-Stale` muncul terus dan `serving` juga kosong, hentikan demo
range, gunakan `/v1/market/latest`, dan catat insiden di handoff.
