# Handoff C3-A - Anin

## Status

- CP1: PASS - `api-2` healthy, dua instance terlihat lewat Traefik.
- CP2: PASS - `api-2` dimatikan, 0 5xx; retry/rate limit terbukti.
- CP3: PASS - circuit breaker latency 2s -> 503 -> recovery; HSTS, 429,
  Trivy, port scan, audit export, dan tiga runbook ada.
- Tag: `c3-a-ok`.
- Tanggal: 2026-11-25.

## Yang sudah jalan

- `api-2` read-only di `compose.base.yml`; `api` dan `api-2` memakai
  `BMIP_INSTANCE` berbeda.
- Role `bmip_api_ro`: SELECT serving/ops, INSERT audit, UPDATE `last_used_at`;
  insert `serving.predictions` ditolak.
- Traefik `services.yaml` + renderer; `api` LB `wrr` dua server, health check
  10s/3s; `/v1/predict` dan `/v1/admin` dipin ke `api-primary`.
- Circuit breaker, retry, rate limit, HSTS, security headers.
- Toxiproxy profile `chaos`; T-18 PASS.
- Trivy 0 HIGH/CRITICAL pada `bmip/api:dev` dan `bmip/dashboard:dev`.
- Port scan luar loopback hanya 80/443; 429 terbukti; TLS/HSTS PASS.
- Audit export 100 baris.
- Tiga runbook: circuit breaker, API fallback, restart loop.
- Dashboard v2 8 tab + korelasi 5 symbol + backfill 15 hari (108.000 bar).

## Yang belum jalan / stub

- `/v1/predict` tetap `not_available` sampai champion ML ada (C3-B).
- Grafana panel replica/circuit state belum ditambahkan (Should).
- Bulkhead konkurensi per replica belum (Should).
- Dashboard memakai 8 tab; jika data sentiment hanya satu jam, scatter
  sentimen vs return menampilkan status sample kecil.

## Cara menjalankan

```bash
make c3a-roles
make c3a-services
make c3a-up
make c3a-evidence
make c3a-circuit
make c3a-scan
make test-cov
make evidence-check
```

## Kegagalan yang diketahui

- Traefik `api-dev` dengan circuit breaker bisa membuka circuit saat uji burst
  berat. Rate-limit evidence memakai entrypoint uji `:8085` tanpa circuit agar
  429 terukur; ini deviasi tertulis.
- `serving` awal hanya BTC; backfill 15 hari 5 symbol dilakukan lewat
  `scripts/w2a_backfill.py` + `make gold` + `make serving`.
- Freshness historis tetap `stale`; bukan kegagalan health.
- MLflow registry kosong.

## Langkah berikutnya untuk C3-B

1. Feast online store + point-in-time join.
2. Champion/challenger dan promotion otomatis.
3. Drift report + retraining.
4. Jangan mengubah evidence C3-A yang sudah ditandatangani.

## Evidence

- `evidence/tests/T16.txt` - load balancing dua replica.
- `evidence/tests/T17.txt` - failover tanpa 5xx.
- `evidence/tests/T18.txt` - circuit breaker + recovery.
- `evidence/deploy/api2-health_*.md` - health dua replica.
- `evidence/security/trivy.txt` - 0 HIGH/CRITICAL.
- `evidence/security/c3a-port-scan.txt` - hanya 80/443 di luar loopback.
- `evidence/security/rate-limit.txt` - 200/429.
- `evidence/security/tls-c3a.txt` - TLS + HSTS.
- `evidence/security/audit.csv` - audit export.
- `evidence/dashboard/w3_*.png` - dashboard 8 tab.
- `docs/dashboard.md` - cara baca dashboard dan korelasi.
