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

- Commit SHA: `937a0ef` (commit kode dan docs yang diuji)
- Profil compose: `dev` (`deploy/compose.base.yml` + `deploy/compose.dev.yml`)
- OS / Docker / Compose: Windows 11 Home 10.0.26200 / Docker 29.7.2 / Compose 5.5.0
- Python: 3.11.9
- Tanggal: 2026-11-11
- Tag `w1-a-ok` menunjuk commit final W1-A setelah evidence ini di-commit.

## Indeks

| ID | Area | File | Status | Catatan |
| --- | --- | --- | --- | --- |
| CP1 | deploy | `deploy/health_20261111T1404_937a0ef.md` | PASS | 6 service hijau, bucket + namespace + ops tables |
| CP1 | deploy | `deploy/compose-config_20261111T1406_937a0ef.yml` | PASS | `docker compose config --no-interpolate` profil dev |
| CP2 | tests | `tests/T01.json` | PASS | social post valid (termasuk `ingest_ts`) lolos kontrak |
| CP2 | tests | `tests/T02.json` | PASS | harga negatif ditolak di `$.price` |
| CP2 | ingestion | `ingestion/counts_20261111T1405.csv` | PASS | bronze market 3 row, social 2 row |
| CP2 | batch | `batch/ledger_20261111T1405.csv` | PASS | market `succeeded`, social `succeeded`, checksum tercatat |
| T-26 | batch | `batch/T26.json` | PASS | dua replay `skipped_identical`; counts bronze tidak berubah |
| CP3 | ingestion | `ingestion/replay_20261111T1405.txt` | PASS | log lengkap dua run replay market + social |
| E2E-W1A | e2e | `e2e/SMOKE-W1A_20261111T1406_937a0ef.txt` | PASS | health + replay + bronze counts + ledger + idempotensi |
