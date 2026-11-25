# Rekap Hasil W2-D - Recovery, Benchmark, dan Evidence Freeze

| Field | Nilai |
| --- | --- |
| Owner | Lois |
| Branch | `slot/w2-d-lois` |
| Commit dasar | `6187d41` |
| Base tag | `w2-c-ok` (`b3ffb46`) |
| Status keseluruhan | Selesai dengan partial yang dicatat; close-out 2026-11-25 menutup T-25 dan tag `w2-d-ok` |
| Tanggal rekap | 2026-11-24 (addendum close-out 2026-11-25) |

## Addendum close-out 2026-11-25

Close-out dikerjakan di branch `fix/w2-closeout`:

- Evidence yang sebelumnya tidak masuk git (`coverage.json`, `clean-clone.log`,
  19 log verifikasi) diperbaiki lewat `.gitignore` dan checker `--check`.
- `evidence/security/tailscale-acl.json` disanitasi; gitleaks kini 0 finding
  pada history dan working tree (allowlist sempit untuk commit lama).
- T-25 PASS dengan deviasi yang tercatat di `evidence/deploy/clean-clone.log`.
- `docs/handoff/w2-d.md` dan tag `w2-d-ok` dibuat setelah evidence final.
- Dokumentasi diselaraskan dengan lima symbol Binance.
- T-42 penuh dan registry ML tetap menjadi gap C3-D/C3-B.

## 1. Ringkasan

W2-D menyelesaikan backup/restore, restart persistence, dua fault injection,
benchmark matrix, coverage gate, evidence checker, serta draft dokumentasi
instalasi dan spec mapping. Hasil benchmark menunjukkan API dan throughput
memenuhi target. Blocker utama ada pada data ML yang terlalu sedikit dan DQ
freshness pada window historis; clean clone sudah diuji sampai stack, katalog,
dashboard, dan API hidup pada close-out 2026-11-25.

## 2. Hasil per deliverable

| Item | Status | Ringkasan |
| --- | --- | --- |
| Backup + manifest | PASS | 5 database, 7.338 baris, SHA-256, row count, checksum, upload MinIO |
| T-19 restore drill | PASS | Restore mengembalikan row count dan checksum yang identik |
| T-40 restart persistence | PASS | 19 service restart; tabel bisnis identik; offset identik |
| Fault stream kill | PASS | 0 duplikat setelah restart; RTO 88,52 detik |
| Fault MinIO stop | PASS | API fallback `X-Data-Stale`; RTO 42,0 detik |
| T-42 benchmark matrix | PARTIAL | 16 baris; API dan throughput pass; DQ/training/inference/B2 partial |
| T-41 coverage gate | PASS | 51,36% coverage; 188 test lulus |
| T-25 clean clone | PASS (deviasi) | Install, lint, compose config, stack, governance, katalog, dashboard, API; deviasi di `clean-clone.log` |
| Evidence index | PASS | File evidence tracked; manifest baru; 0 link mati |
| Commit/tag | PASS | Close-out `fix/w2-closeout`; tag `w2-d-ok` pada commit evidence |

## 3. Recovery dan fault injection

### Backup dan T-19

- Manifest: `evidence/recovery/manifest_20261121T163617Z.json`
- Bukti drill: `evidence/recovery/T19.txt`
- Total baris: **7.338**
- Cakupan:
  - `bmip`: 221 baris / 17 tabel
  - `lakekeeper`: 5.020 baris / 52 tabel
  - `prefect`: 2.002 baris / 37 tabel
  - `mlflow`: 0 baris / 0 tabel
  - `marquez`: 95 baris / 31 tabel
- Lokasi dump lokal: `backups/20261121T163617Z/` (gitignored)
- Salinan MinIO: `s3://backups/postgres/20261121T163617Z/`

### T-40 restart persistence

- Bukti: `evidence/recovery/T40.json`, `evidence/recovery/T40.txt`
- Hasil: **PASS**
- 19 service direstart.
- `restart_command_seconds`: **9,70**
- `ready_seconds`: **34,08**
- `business_tables_identical`: **true**
- `row_totals_not_decreased`: **true**
- Offset: 27 group before/after, **identik**
- Catatan: beberapa tabel metadata berubah jumlah baris karena statistik internal
  (`endpoint_statistics`, `namespaces`, `tags`), tetapi tabel bisnis tidak berubah.

### Fault injection

| Skenario | Evidence | Hasil |
| --- | --- | --- |
| Kill stream processor | `evidence/faults/stream-kill_20261123T182353.json` | PASS; 50 trade unik, 0 duplikat, RTO 88,52 s |
| Stop MinIO | `evidence/faults/minio-kill_20261123T182601.json` | PASS; 3 endpoint fallback 200 + `X-Data-Stale`, RTO 42,0 s |

## 4. Benchmark T-42

Evidence utama:

- `evidence/benchmark/matrix.csv`
- `evidence/benchmark/matrix.json`
- `evidence/benchmark/summary.md`
- `evidence/benchmark/resources.csv`

Matrix berisi **16 baris**: 13 skenario inti + 3 throughput run. Tidak ada error
pada seluruh request API dan throughput.

### API latency

| Skenario | Run 1 p95 | Run 2 p95 | Run 3 p95 | Target | Status |
| --- | ---: | ---: | ---: | ---: | --- |
| API latest | 52,592 ms | 100,452 ms | 86,607 ms | < 300 ms | PASS |
| API range 14 hari | 550,198 ms | 357,258 ms | 361,301 ms | < 2.000 ms | PASS |

### Throughput replay

| Run | Pesan measured | Error | Duplikat | Throughput | p95 | Status |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 1 | 600.000 | 0 | 0 | 999,999/s | 3,682 ms | PASS |
| 2 | 600.000 | 0 | 0 | 999,996/s | 3,265 ms | PASS |
| 3 | 600.000 | 0 | 0 | 999,998/s | 4,395 ms | PASS |

Run 3 diulang bersih setelah Docker Desktop sempat restart. Hasil baru sudah
menggantikan baris Run 3 lama, sedangkan Run 1 dan Run 2 tidak berubah.

### Hasil partial dan alasannya

| Skenario | Hasil | Alasan |
| --- | --- | --- |
| DQ runtime | PARTIAL; 60,061 s | Critical `gold_market:gold-market-lag`; data historis tidak fresh |
| Training | PARTIAL; 28,526 s | `dataset needs at least three event dates`; hanya 2 tanggal berlabel |
| Inference | PARTIAL; 100/100 `not_available` | Registry kosong; belum ada champion |
| B2 full vs pruned | PARTIAL; 724,375 ms vs 48,905 ms | Hanya 42 baris dan 5 baris hasil prune; belum representatif |
| cAdvisor host | PASS | CPU 0,000%; memory 2,682 GiB |

## 5. Coverage T-41

- Evidence: `evidence/tests/coverage.json`
- Bukti teks: `evidence/tests/T41_20261124T050900Z.txt`
- Command:

```text
python -m pytest --cov=bmip --cov-report=term \
  --cov-report=json:evidence/tests/coverage.json --cov-fail-under=40
```

Hasil:

- **188 passed**, 1 warning
- Coverage: **51,36%**
- Statements: **5.983**
- Missed: **2.914**
- Gate 40%: **PASS**

`make test-cov` sudah diarahkan ke command yang sama, tetapi GNU Make tidak
terpasang di host ini sehingga command dijalankan langsung.

## 6. Clean clone T-25

- Evidence: `evidence/deploy/clean-clone.log`
- Commit runtime: `b2eceb1` (clone awal `f4d7e9f`, fast-forward sebelum runtime)
- Hasil: **PASS dengan dua deviasi tercatat**

Yang lulus:

- `git clone`, venv Python 3.11, install `.[dev,ml,dashboard]`
- `make secrets certs users`
- `make dev-up` dengan `COMPOSE_PROJECT_NAME=bmip-t25` (volume terpisah)
- `make governance-up` + `make governance` (11 dataset, 3 key RBAC)
- `make e2e-smoke` PASS (market/social, bronze, ledger, idempotensi)
- `make stream-once` + `make gold` + `make serving`
- Dashboard tidak kosong, katalog 11 dataset, Marquez dan API hidup

Deviasi:

- `make dev-up` pertama memakai volume `bmip_*` lama dan gagal pada
  `lakekeeper-migrate`; solusi `COMPOSE_PROJECT_NAME` didokumentasikan.
- Seed data memakai window replay dua jam; window satu jam gagal
  `gold-market-hourly-gap`. Perintahnya ada di `docs/install.md` §5.1.

Catatan penting: install awal gagal karena mirror pip lokal tidak menyediakan
`botocore==1.43.117`; install ulang dengan PyPI eksplisit berhasil.

## 7. Perubahan kode dan konfigurasi

| File | Perubahan |
| --- | --- |
| `Makefile` | Setup memasang `.[dev,ml,dashboard]`; `test-cov`, `benchmark`, dan `evidence` diimplementasikan |
| `src/bmip/ingestion/kafka.py` | `broker.address.family=v4` untuk AdminClient dan Producer |
| `src/bmip/transform/stream.py` | `broker.address.family=v4` untuk consumer |
| `src/bmip/quality/checkpoint.py` | DQ membaca Iceberg lewat service `ml` agar tidak kena ACL `process` |
| `deploy/api/Dockerfile` | pip wheel memakai `--no-cache-dir --retries 10 --timeout 120` |
| `deploy/dashboard/Dockerfile` | Perubahan pip yang sama |
| `deploy/compose.host-ml.yml` | Override agar API memakai MLflow host `host.docker.internal:5000` |
| `scripts/w2d_benchmark.py` | Benchmark matrix T-42 |
| `scripts/w2d_evidence_check.py` | Pemeriksa manifest dan link evidence |
| `scripts/w2d_faults.py` | Fault injection stream dan MinIO |
| `scripts/w2d_restart.py` | Restart persistence T-40 |
| `docs/install.md` | Draft instalasi dan troubleshooting |
| `docs/spec-mapping.md` | Rekonstruksi F-01..F-20 + 11 aspek penilaian |
| `evidence/README.md` | Bagian evidence W2-D |
| `evidence/compliance/index.md` | Index F-01..F-20 dan test ID |
| `.gitignore` | Evidence `coverage.json`, `*.log`, dan `logs/` tidak lagi ter-ignore |
| `scripts/w2d_evidence_check.py` | Mode `--check`, tracked-file check, manifest baru |
| `src/bmip/common/config.py` | `connect_timeout=5` pada DSN PostgreSQL |
| `src/bmip/transform/dlq.py` | `broker.address.family=v4` untuk DLQ producer/consumer |
| `scripts/w2c_scan.py` | Sanitasi Tailscale evidence + gitleaks git/dir |
| `.gitleaks.toml` | Allowlist sempit untuk histori tailscale yang sudah diredaksi |
| `ARCHITECTURE.md`, `README.md`, `workplan.md` | Sinkronisasi lima symbol dan status W2 |

## 8. Evidence final

- Manifest close-out: `evidence/evidence-manifest_20261125T*.json`
- File yang diperiksa: **156**
- Required missing: **0**
- Required untracked: **0**
- Broken link: **0**
- Health clean clone: `evidence/deploy/health_20261125T0259_f4d7e9f.md`
- T-25: `evidence/deploy/clean-clone.log` (PASS dengan deviasi)
- Manifest lama `evidence-manifest_20261124T061230Z_6187d41.json` adalah
  **superseded**: ia menyertakan 21 file yang tidak pernah masuk git.

## 9. Keputusan yang sudah diambil

- Evidence `evidence/alerts/alerts.jsonl` dan `deliveries.jsonl` dipertahankan
  karena valid sebagai bukti drill W2-B (147 dan 149 baris JSON valid).
- Perubahan Dockerfile dipertahankan.
- DQ, training, dan inference diterima sebagai PARTIAL dengan alasan tertulis.
- `docs/spec-mapping.md` diterima sebagai rekonstruksi karena `Spek.md` tidak ada.
- Full T-25 dilakukan setelah commit kode/docs.

## 10. Yang belum selesai

1. T-42 penuh (DQ runtime, training, inference, B2) - C3-D.
2. Registry/champion ML dan data berlabel - C3-B.
3. Clean clone final setelah seluruh perubahan C3 - C3-D.
4. Keputusan retensi `evidence/lineage/spool/events_20261124.jsonl` - C3-D.

Item commit, T-25, evidence T-25, dan tag `w2-d-ok` sudah diselesaikan pada
close-out 2026-11-25.

## 11. Rekomendasi urutan close-out

```text
1. Review diff final.
2. Commit kode + docs W2-D.
3. Clone commit tersebut, jalankan stack bersih, health, dan dashboard berisi.
4. Simpan evidence T-25 PASS/PARTIAL.
5. Commit evidence final.
6. Tag w2-d-ok.
7. Serahkan ke C3-D untuk sapuan penuh dan tag v1.0-demo.
```

## 12. Kesimpulan

W2-D sudah membuktikan recovery, restart persistence, dua fault injection,
throughput 1.000 trade/s, latency API, coverage 51,36%, evidence index yang
resolvable, dan clean clone T-25 dengan dua deviasi tercatat. Yang belum
tertutup adalah T-42 penuh dan konsekuensi data ML yang terlalu sedikit; keduanya
dijadwalkan di C3-B/C3-D.
