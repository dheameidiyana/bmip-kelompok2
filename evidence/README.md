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

W1-C menambahkan:

- Commit SHA: lihat header `commit` di tiap file W1-C (kode diuji: `3742fe9`).
- Base branch: `feat/silver-lois` (`fdaf360`), karena W1-B belum di-merge ke `dev`.
- Python: 3.11.9, Great Expectations 1.25.0, VADER 3.3.2.
- Lint: `ruff` + `sqlfluff` (config `.sqlfluff`) bersih; `e2e-smoke` PASS.
- Data: replay nyata Binance Vision `BTCUSDT-aggTrades-2026-11-10` pukul
  14:00-17:00 UTC, plus dua post fixture W1-A.
- Tag `w1-c-ok` menunjuk commit final W1-C setelah evidence di-commit.

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

### W1-C

| ID | Area | File | Status | Catatan |
| --- | --- | --- | --- | --- |
| T-03 | tests | `tests/T03.txt` | PASS | tulis ulang `post_key` yang sama; count silver tidak berubah |
| T-09 | tests | `tests/T09.txt` | PASS | dua build; lonjakan harga di masa depan tidak menggeser fitur sebelumnya |
| T-10 | tests | `tests/T10.txt` | PASS | skor VADER selalu di [-1, 1] |
| T-11 | tests | `tests/T11.txt` | PASS | `trade_id` null memblokir gate gold |
| T-12 | tests | `tests/T12.txt` | PASS | duplicate rate 2,9% hanya warning, pipeline lanjut |
| T-31 | storage | `storage/T31.txt` | PASS | kolom nullable baru terbaca; snapshot lama tetap bisa dibuka |
| T-32 | storage | `storage/T32.json` | PASS | koreksi sumber mengubah jam yang benar |
| T-33 | storage | `storage/T33.json` | PASS | dua rerun menghasilkan hash logis identik |
| DQ | dq | `dq/dq_report.json` | PASS | checkpoint GX lengkap, 7 suite |
| DQ | dq | `dq/mart-counts_20261113T2223.csv` | PASS | jumlah baris per mart |
| PII | security | `security/pii-columns_20261113T2223.txt` | PASS | tidak ada URI, DID, atau handle mentah di silver |
| DBT | dbt | `dbt/docs.png` | PASS | halaman dbt docs `mart_ml` dengan kolom dan deskripsi |
| DBT | dbt | `dbt/docs_20261113T2230.txt` | PASS | katalog model dan kolom hasil `dbt docs generate` |
| E2E | e2e | `e2e/SMOKE-W1A_20261113T2226_3742fe9.txt` | PASS | health + replay + bronze counts + ledger + idempotensi, dengan warm-up |
| Prefect | deploy | `deploy/prefect-gold_20261113T2229_3742fe9.json` | PASS | flow `transform-gold` berstatus Completed lewat worker |
| W1-C | w1c | `w1c/SUMMARY_20261113T2223.json` | PASS | ringkasan satu baris per test |
