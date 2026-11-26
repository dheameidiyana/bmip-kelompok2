# Slide C3-A

Dua board 1920x1080, gaya sama dengan `docs/presentation/w2c`. Isi hanya bukti;
teks dibatasi ke label, angka, dan satu baris keterangan.

| File | Isi | Sumber |
| --- | --- | --- |
| `01-replika-gateway.png` | Dua replica healthy, LB `wrr` dua server, T-16 bagi rata 15/15, T-17 failover 0 5xx, router baca/tulis + role read-only | `evidence/tests/T16.txt`, `T17.txt`, `deploy/traefik/dynamic/services.yaml`, `scripts/c3a_roles.py` |
| `02-resiliensi-keamanan.png` | Circuit breaker tripped lalu pulih, Trivy 0, rate limit 336/264, TLS/HSTS/port, audit export | `evidence/tests/T18.txt`, `evidence/security/trivy.txt`, `rate-limit.txt`, `tls-c3a.txt`, `c3a-port-scan.txt`, `audit.csv` |

Dashboard sengaja tidak dimasukkan; itu cerita terpisah.

Angka di panel diambil dari run 2026-11-26 (commit `c8e362b`) setelah image
di-rebuild dengan perbaikan `libzstd1`.
