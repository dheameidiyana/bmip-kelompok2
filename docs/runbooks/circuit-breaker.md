# Runbook: Circuit breaker API (C3-A)

## What this covers

Traefik `api-circuit` membuka circuit kalau lebih dari 25% response 5xx atau
latency p50 di atas 1.5 detik dalam `checkPeriod` 10 detik. Saat terbuka,
Traefik mengembalikan **503** sebelum request mencapai API.

## Gejala

- Dashboard/API mengembalikan 503 padahal container `api` healthy.
- Log Traefik memuat `circuit breaker` atau `service unavailable`.
- `api-chaos` / Toxiproxy menunjukkan latency 2 detik.

## Cek cepat

```powershell
docker compose --env-file .env -f deploy/compose.base.yml -f deploy/compose.dev.yml ps api api-2
docker logs bmip-traefik-1 --tail 100 | Select-String "circuit|503"
curl.exe -s -o NUL -w "%{http_code}`n" https://127.0.0.1/health/live -H "Host: api.bmip.local" -k
```

## Tindakan

1. Pastikan bukan latency buatan:
   ```powershell
   Invoke-RestMethod http://127.0.0.1:8474/proxies/api-chaos
   ```
   Hapus toxic:
   ```powershell
   Invoke-RestMethod -Method Delete http://127.0.0.1:8474/proxies/api-chaos/toxics/latency
   ```
2. Tunggu `fallbackDuration` + `recoveryDuration` (10s + 10s).
3. Kalau 503 tetap muncul, cek health replica:
   ```powershell
   docker inspect --format "{{.Name}} {{.State.Health.Status}}" bmip-api-1 bmip-api-2-1
   ```
4. Kalau satu replica sehat, Traefik harus mengeluarkannya dari LB. Kalau tidak,
   restart Traefik:
   ```powershell
   docker compose --env-file .env -f deploy/compose.base.yml -f deploy/compose.dev.yml restart traefik
   ```

## Eskalasi

Kalau circuit terbuka tanpa latency buatan dan tidak pulih dalam 5 menit,
matikan `api-2` untuk memaksa satu replica, lalu buka incident dan periksa log
API/DB.
