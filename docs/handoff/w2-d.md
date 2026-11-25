# Handoff W2-D - Lois

## Status

- CP1: PASS - backup, manifest, dan restore T-19.
- CP2: PASS - T-40 restart persistence dan dua fault injection.
- CP3: PASS dengan partial yang dicatat - T-25 close-out PASS (dua deviasi),
  T-41 PASS, T-42 matrix awal 16 baris dengan beberapa skenario PARTIAL.
- Tag: `w2-d-ok` pada commit evidence close-out.
- Close-out W2: `fix/w2-closeout`, 2026-11-25.

## Yang sudah jalan

- Backup lima database (core, ml, prefect, mlflow, marquez) + manifest SHA-256:
  `make backup`, `evidence/recovery/manifest_20261121T163617Z.json`.
- Restore drill T-19: row count dan checksum identik:
  `evidence/recovery/T19.txt`.
- Restart persistence T-40: 19 service, tabel bisnis dan offset identik:
  `evidence/recovery/T40.json`, `evidence/recovery/T40.txt`.
- Fault injection stream dan MinIO dengan RTO:
  `evidence/faults/stream-kill_20261123T182353.json`,
  `evidence/faults/minio-kill_20261123T182601.json`.
- Benchmark matrix T-42:
  `evidence/benchmark/matrix.csv`, `evidence/benchmark/matrix.json`,
  `evidence/benchmark/summary.md`.
- Coverage T-41: 188 test, 51,36%, gate 40%:
  `evidence/tests/coverage.json`, `evidence/tests/T41_20261124T050900Z.txt`.
- Clean clone T-25: PASS dengan deviasi, termasuk dashboard dan katalog hidup:
  `evidence/deploy/clean-clone.log`.
- Evidence checker yang menolak file tidak tracked:
  `python scripts/w2d_evidence_check.py --check`.
- Dokumentasi 5 symbol: `README.md`, `ARCHITECTURE.md`, `workplan.md`,
  `docs/install.md`, `docs/spec-mapping.md`, dan Grafana business variable.

## Yang belum jalan / stub

- T-42 penuh: DQ runtime, training, inference, dan B2 masih PARTIAL karena data
  historis sparse dan registry ML kosong. Dampak: C3-D perlu menjalankan ulang
  matrix dengan data yang lebih baru.
- DQ `gold-market-lag` / `gold-market-hourly-gap` pada window satu jam. Dampak:
  seed demo harus memakai window minimal dua jam (lihat `docs/install.md` §5.1).
- Registry ML kosong dan hanya dua event date berlabel. Dampak: inference
  `not_available`; C3-B harus memperluas data atau memilih model market-only.
- T-25 memakai fast-forward `f4d7e9f -> b2eceb1` sebelum runtime dan seed replay
  dua jam; bukan clone statis dari commit final. Dampak: C3-D mengulang clean
  clone final setelah semua perubahan C3.
- 19 log `evidence/verification/**/logs/*` dari manifest lama tidak tersedia di
  mesin close-out; file itu tidak masuk manifest baru. Dampak: bukti verifikasi
  W1-B mengandalkan file lain yang sudah tracked; tidak ada klaim pass baru.
- Hanya BTCUSDT yang punya bar pada window replay T-25; ETH/BNB/SOL/XRP
  mengembalikan 200 `data=null`. API tetap menerima kelima symbol.

## Cara menjalankan

```bash
make dev-up
make governance-up
make governance
make e2e-smoke
make stream-once
make gold
make serving
make evidence-check
make test-cov
```

Untuk dashboard tidak kosong di clone baru, ikuti seed window dua jam di
`docs/install.md` §5.1.

## Kegagalan yang diketahui

- `psycopg` tanpa `connect_timeout` menggantung di `localhost` Windows.
  Workaround sudah permanen: `Settings.postgres_dsn` menambahkan
  `connect_timeout=5`.
- `e2e-smoke` menggantung sebelum fix di atas; setelah fix, gate PASS di clean
  clone (`evidence/e2e/SMOKE-W1A_20261125T0323_ab6010e.txt`).
- Producer/consumer DLQ tidak memakai `broker.address.family=v4`; sudah
  diperbaiki di `src/bmip/transform/dlq.py`. Tanpa itu, stream gagal
  `_MSG_TIMED_OUT` ke `ipv6#[::1]:19092`.
- Compose top-level `name: bmip` membuat clone memakai volume lama dan gagal
  `password authentication failed`. Workaround: `COMPOSE_PROJECT_NAME=bmip-t25`
  untuk volume terpisah.
- `evidence/security/tailscale-acl.json` versi lama memuat node key dan IP
  perangkat. Sudah disanitasi; histori commit `7495700` di-allowlist sempit di
  `.gitleaks.toml` karena bukan kredensial.

## Langkah berikutnya untuk C3-A

1. Mulai dari `w2-d-ok`/`dev` HEAD; baca handoff ini dan `docs/handoff/w2-c.md`.
2. Implementasikan `api-2`, Traefik load balancer, circuit breaker, Toxiproxy,
   Trivy, rate-limit/TLS/HSTS, dan tiga runbook.
3. Jalankan ulang `make evidence-check` dan gitleaks setiap commit.
4. Jangan mengubah evidence W2 yang sudah ditandatangani; tambahkan evidence
   C3 di file baru.

## Evidence

- `evidence/recovery/T19.txt` - restore row count/checksum.
- `evidence/recovery/T40.json` - restart persistence.
- `evidence/faults/stream-kill_20261123T182353.json` - stream kill RTO.
- `evidence/faults/minio-kill_20261123T182601.json` - MinIO stop fallback.
- `evidence/benchmark/matrix.csv` - 16 baris benchmark.
- `evidence/benchmark/summary.md` - kesimpulan bottleneck.
- `evidence/tests/coverage.json` - coverage 51,36%.
- `evidence/deploy/clean-clone.log` - T-25 PASS dengan deviasi.
- `evidence/deploy/health_20261125T0259_f4d7e9f.md` - health clean clone.
- `evidence/e2e/SMOKE-W1A_20261125T0323_ab6010e.txt` - W1-A gate di clean clone.
- `evidence/deploy/clean-clone-dashboard.png` - dashboard tidak kosong.
- `evidence/deploy/clean-clone-catalog.png` - katalog 11 dataset.
