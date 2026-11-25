# Runbook: Restart loop API (C3-A)

## What this covers

Container `api` atau `api-2` restart berulang, health tidak pernah stabil, atau
Traefik mengeluarkan replica dari load balancer.

## Gejala

- `docker ps` menunjukkan `Restarting` atau `Up ... (unhealthy)`.
- Traefik log: `Health check failed` untuk `api@file`.
- Request 502/503 dari Traefik.

## Cek cepat

```powershell
docker compose --env-file .env -f deploy/compose.base.yml -f deploy/compose.dev.yml ps api api-2
docker inspect --format "{{.Name}} {{.RestartCount}} {{.State.Health.Status}}" bmip-api-1 bmip-api-2-1
docker logs bmip-api-1 --tail 120
docker stats --no-stream bmip-api-1 bmip-api-2-1
```

## Penyebab umum

| Gejala log | Penyebab | Tindakan |
| --- | --- | --- |
| `password authentication failed` | Password role/DSN berubah | Cek `.env`, jalankan `make c3a-roles`, recreate API |
| `connection refused` ke Postgres | DB belum healthy | Tunggu `postgres-core`, restart API |
| `Killed` / exit 137 | Memory limit 700–768m | Turunkan beban, cek `docker stats` |
| `duckdb` extension error | Cache extension rusak | Hapus volume cache extension atau recreate API |
| `Unhealthy` tanpa error | Health check terlalu ketat | Cek `/health/ready` manual, lihat detail `checks` |

## Tindakan aman

1. Jangan `make reset`; itu menghapus volume data.
2. Recreate satu replica:
   ```powershell
   docker compose --env-file .env -f deploy/compose.base.yml -f deploy/compose.dev.yml up -d --force-recreate api-2
   ```
3. Kalau hanya `api-2` bermasalah, hentikan sementara:
   ```powershell
   docker compose --env-file .env -f deploy/compose.base.yml -f deploy/compose.dev.yml stop api-2
   ```
   Traefik akan mengarahkan traffic ke `api`.
4. Kalau `api` utama bermasalah, jangan hentikan keduanya; mulai `api` lebih
   dulu, lalu `api-2`.

## Eskalasi

Kalau restart loop terjadi setelah perubahan config, rollback commit terakhir
dan catat di `docs/handoff/c3-a.md`.
