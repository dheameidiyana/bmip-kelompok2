# Handoff W1-B - Lois

- Owner: Lois
- Branch: `feat/silver-lois`
- Handoff to: Vio (W1-C)
- Last update: 2026-11-13
- Commit at evidence time: `328e0b2`

## Status

- CP1: PASS
- CP2: PASS
- CP3: PASS
- Tag: `w1-b-ok` pending approval

Gate: stream processor, silver market, replay idempotence, retry after bronze,
DLQ replay, freshness, dbt tests, and Prefect schedule/retry/concurrency are
implemented and evidenced.

## Yang sudah jalan

### Stream processor dan replay

- Redpanda topic `market.trades`; DLQ default `market.trades.dlq`.
- Consumer group offset commit hanya pada mode stream, bukan replay.
- `bmip.transform.cli` menyediakan `stream`, `lag`, dan `replay`.
- Replay memakai event `event_ts` untuk filter `--from/--to`, urut
  `(event_ts, partition, offset)`, dan flush per menit.
- Watermark `120s`, correction window `30m`, dedup `(symbol, trade_id)`,
  quarantine, dan metrik Prometheus pada port `9101`.
- `T05` membuktikan replay satu jam dua kali menghasilkan 60 bar identik;
  run kedua mencatat 120 duplicate dan tidak menulis bar baru.
- `T28` membuktikan consumer restart melanjutkan dari offset tersimpan:
  4 event pertama, lalu 6 event sisanya, total 10.

### Silver market

- Tabel Iceberg:
  - `silver.market_trades`
  - `silver.market_ohlcv_1m`
  - `quarantine.market_trade_rejected`
- OHLCV ditulis dengan overwrite per `event_date`, sehingga koreksi late event
  memperbarui bar yang sama, bukan menambah bar duplikat.
- `compute_silver_freshness()` menghitung ingest lag dari trade dengan
  `event_ts` terbaru.
- `T24` PASS: `ingest_lag_seconds=15.0`, `bar_age_seconds=0.0`,
  threshold `120s`.

### Retry setelah bronze

- `BronzeWriter.append_market()` dan `append_social()` idempoten per
  `batch_id`; append duplikat mengembalikan `0`.
- `T27` PASS:
  - run pertama gagal setelah bronze dan ledger mencatat `failed`;
  - retry mencatat `succeeded`;
  - baris bronze tetap `1` sebelum dan sesudah retry;
  - `duplicate_count=0`.

### DLQ

- Poison record `schema_violation` masuk DLQ.
- `read_dlq()` membaca record DLQ dengan group unik.
- `T29` PASS: payload tanpa `trade_id` ditangkap, dikoreksi, di-replay, lalu
  diterima silver.

### dbt

- Model `stg_market_ohlcv_1m` di atas source `silver.market_ohlcv_1m`.
- `dbt build` hijau: 19 data tests + 1 model, total 20 PASS.
- Evidence: `evidence/dbt/build_20261113T0857_328e0b2.txt`.

### Prefect

- `postgres-ml` dan `prefect-server` sudah masuk compose; UI di
  `http://localhost:4200`.
- Work pool `local-process`, concurrency limit `1`.
- Deployment:
  - `harvest-social/harvest-social`, cron `10 * * * *` UTC;
  - `transform-silver/transform-silver`, cron `40 * * * *` UTC.
- Retry:
  - harvest task: 3 retries, delay 60/300/900 detik;
  - dbt task: 2 retries, delay 30/120 detik.
- Kedua flow sudah pernah berstatus `Completed` lewat worker.
- Evidence: `evidence/deploy/prefect_20261113T085943_328e0b2.json`.

## Yang belum jalan / stub

- Worker Prefect tidak berjalan permanen. Work pool akan berstatus
  `NOT_READY` saat worker berhenti; ini normal. Jalankan worker sebelum
  mengandalkan schedule.
- Silver social, sentiment, gold marts, GX, serving loader, API, dan dashboard
  adalah scope W1-C/W1-D, bukan W1-B.
- `harvest-social` memakai `SOCIAL_FEED` dari `.env`. Untuk demo offline,
  set `SOCIAL_FEED=replay`.
- Screenshot CP1 belum ada. File yang diminta:
  `evidence/stream/lag_<ts>.png`.
- Commit dan tag belum dibuat karena menunggu approval.

## Cara menjalankan

Canonical Windows commands:

```powershell
.\.venv\Scripts\python.exe scripts\doctor.py --evidence
.\.venv\Scripts\python.exe scripts\stream_evidence_cp1.py
.\.venv\Scripts\python.exe scripts\cp2_market_evidence.py
.\.venv\Scripts\python.exe scripts\w1b_evidence.py
.\.venv\Scripts\python.exe scripts\t27_evidence.py
.\.venv\Scripts\python.exe scripts\prefect_evidence.py
.\.venv\Scripts\python.exe scripts\run_dbt.py
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check src scripts tests deploy
```

Start Prefect:

```powershell
docker compose --env-file .env -f deploy/compose.base.yml -f deploy/compose.dev.yml up -d postgres-ml prefect-server
.\.venv\Scripts\python.exe scripts\prefect_bootstrap.py
.\.venv\Scripts\python.exe -m prefect worker start -p local-process
```

One polling cycle without a permanent worker:

```powershell
.\.venv\Scripts\python.exe -m prefect worker start -p local-process --run-once
```

`make` tidak tersedia di shell Windows ini. Makefile sudah diperbarui dengan
target `prefect-deploy` dan `prefect-worker`, tetapi commands di atas adalah
acuan yang sudah diverifikasi.

## Evidence

- CP1:
  - `evidence/stream/lag_20261113T0003.txt`
  - `evidence/stream/restart_20261113T0003.txt`
  - `evidence/stream/CP1_20261113T0003.json`
- CP2:
  - `evidence/tests/T04.txt`
  - `evidence/tests/T06.txt`
  - `evidence/tests/T07.txt`
  - `evidence/tests/T08.txt`
  - `evidence/tests/CP2_20261113000220.json`
- CP3:
  - `evidence/replay/T05.txt`
  - `evidence/tests/T24.txt`
  - `evidence/stream/T28.txt`
  - `evidence/stream/T29.json`
  - `evidence/batch/T27.json`
  - `evidence/CP3_W1B_20261113084732.json`
  - `evidence/deploy/prefect_20261113T085943_328e0b2.json`
  - `evidence/dbt/build_20261113T0857_328e0b2.txt`
- Deploy health:
  - `evidence/deploy/health_20261113T0004_328e0b2.md`

## Catatan untuk Vio

- Silver market siap dipakai sebagai source dbt W1-C.
- Jangan mengubah `silver.market_ohlcv_1m` tanpa menjalankan ulang
  `scripts/w1b_evidence.py`; T05 dan T24 bergantung pada tabel ini.
- Untuk evidence final setelah commit, jalankan ulang:
  1. `scripts/w1b_evidence.py`
  2. `scripts/t27_evidence.py`
  3. `scripts/prefect_evidence.py`
  4. `scripts/run_dbt.py` dengan output ke `evidence/dbt/`
- Setelah semua PASS, commit evidence dan buat tag `w1-b-ok` pada commit yang
  sama dengan evidence final.
