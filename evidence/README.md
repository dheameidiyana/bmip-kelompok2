# Evidence Index

Setiap klaim pada demo harus punya file bukti di direktori ini.

## Format nama file

```text
evidence/<area>/<ID>_<YYYYMMDDTHHMM>_<git-sha-pendek>.<ext>
```

Contoh: `evidence/tests/T04_20261113T1800_a1b2c3d.txt`

## Header wajib untuk file teks

```text
id        : T-04
timestamp : 2026-11-13T18:00:00Z
commit    : a1b2c3d
command   : make test
result    : PASS
owner     : dhea
```

## Environment

Isi saat evidence freeze:

- Commit SHA: `03338fa` (commit CP3)
- Profil compose: `dev` (`deploy/compose.base.yml` + `deploy/compose.dev.yml`)
- OS / Docker / Compose: Windows 11 Home 10.0.26200 / Docker 29.7.2 / Compose 5.5.0
- Python: 3.11.9
- Tanggal: 2026-11-11

## Indeks

| ID | Area | File | Status | Catatan |
| --- | --- | --- | --- | --- |
| CP1 | deploy | `deploy/health_20261111T0353_a08b0fb.md` | PASS | 6 service hijau, bucket + namespace + ops tables |
| CP1 | deploy | `deploy/compose-config_20261111T0353_a08b0fb.yml` | PASS | `docker compose config --no-interpolate` profil dev |
| CP2 | tests | `tests/T01.json` | PASS | social post valid lolos kontrak |
| CP2 | tests | `tests/T02.json` | PASS | harga negatif ditolak di `$.price` |
| CP2 | ingestion | `ingestion/counts_20261111T0450.csv` | PASS | bronze market 3 row, social 2 row |
| CP2 | batch | `batch/ledger_20261111T0450.csv` | PASS | market idempoten (`skipped_identical`), social `succeeded`, checksum tercatat |
| T-26 | batch | `batch/T26.json` | PASS | dua replay `skipped_identical`; counts bronze tidak berubah |
| CP3 | ingestion | `ingestion/replay_20261111T0456.txt` | PASS | log lengkap dua run replay market + social |
| CP3 | deploy | `deploy/health_20261111T0456_03338fa.md` | PASS | 6 service + bucket/namespace/ops tables |
| CP3 | deploy | `deploy/compose-config_20261111T0457_03338fa.yml` | PASS | config terbaru, placeholder tanpa secret |
