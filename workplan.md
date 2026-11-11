# BMIP — Rencana Pembagian Tugas Implementasi

| Field | Value |
| :---- | :---- |
| Document | Work plan, TBP Advanced Data Platform Engineering |
| Version | 1.0 |
| Date | 2026-11-10 |
| Reference | `ARCHITECTURE.md` v2.0 (2026-11-09), `Spek.md` F-01–F-20 |
| Team | Anin, Lois, Dhea, Vio |
| Implementation window | Rabu 11 November 2026 00.00 — Senin 30 November 2026 23.59 |
| Working model | Relay sekuensial, 3 siklus × 4 slot × 36 jam |
| Status | Approved for execution |

Dokumen ini adalah satu-satunya acuan pembagian kerja. Setiap orang tahu kapan window-nya mulai, apa yang harus selesai pada CP1/CP2/CP3, bukti apa yang harus ada, dan ke siapa pekerjaannya diserahkan. Jika dokumen ini dan pesan chat berbeda, dokumen ini yang berlaku sampai diubah secara eksplisit.

---

## 1\. Parameter kerja

### 1.1 Model relay

1. **Satu orang aktif pada satu waktu.** Slot berurutan, tidak ada dua orang menulis file, container, atau tabel yang sama secara bersamaan (ARCHITECTURE §4.1 prinsip 6: single writer per table).  
2. **36 jam adalah batas waktu, bukan durasi kerja.** Estimasi kerja efektif 24 jam, 12 jam sisanya buffer untuk blockage, review, dan evidence.  
3. **Deadline bersifat keras.** CP3 tidak boleh digeser. Kalau pekerjaan belum selesai di CP3, yang diserahkan adalah versi yang jalan \+ daftar gap di handoff. Menggeser deadline berarti memakan window orang berikutnya.  
4. **Handoff terverifikasi.** Dua jam pertama setiap slot dipakai untuk membaca handoff, menjalankan gate, dan mereview PR slot sebelumnya. Sisanya untuk pekerjaan sendiri.  
5. **Satu tag per slot.** Setelah gate hijau, penulis membuat tag slot: `w{minggu}-{slot}-ok` untuk Siklus 1–2 (contoh `w1-a-ok`) dan `c3-{slot}-ok` untuk Siklus 3 (contoh `c3-a-ok`). Slot berikutnya selalu mulai dari tag terakhir yang hijau.

### 1.2 Kapasitas

| Item | Nilai |
| :---- | :---- |
| Slot per siklus | 4 |
| Panjang slot | 36 jam |
| Panjang siklus | 144 jam (Rabu 00.00 — Senin 23.59) |
| Jumlah siklus | 3 |
| Total window | 432 jam |
| Kerja efektif | 288 jam (12 slot × 24 jam) |
| Paket kerja | 12 (satu per slot) |
| Selesai | Senin 30 November 2026 23.59 |

### 1.3 Ritme harian

| Waktu | Aktivitas | Durasi |
| :---- | :---- | :---- |
| Awal slot | Baca `docs/handoff/` slot sebelumnya, jalankan `make e2e-smoke`, review PR | 2 jam |
| CP1 (+12 jam) | Update status di issue \+ push branch | 15 menit |
| CP2 (+24 jam) | Update status \+ demo 3 menit di chat (rekaman singkat) | 15 menit |
| CP3 (+36 jam) | Tag `wX-Y-ok`, tulis handoff, serahkan | 30 menit |

Tidak ada kerja paralel, sehingga jalur komunikasi utama adalah issue per slot dan handoff tertulis, bukan sinkronisasi tatap muka.

---

## 2\. Kalender

### Siklus 1 — Walking skeleton: source → bronze → silver → gold → API → dashboard

| Slot | Window | Durasi | Pemilik | Fokus |
| :---- | :---- | :---- | :---- | :---- |
| W1-A | Rab 11 Nov 00.00 – Kam 12 Nov 11.59 | 36 jam | **Dhea** | Foundation, storage, broker, kedua sumber, bronze |
| W1-B | Kam 12 Nov 12.00 – Jum 13 Nov 23.59 | 36 jam | **Lois** | Stream processor, silver market, Prefect |
| W1-C | Sab 14 Nov 00.00 – Min 15 Nov 11.59 | 36 jam | **Vio** | Silver social, sentiment, 3 gold marts, quality gate |
| W1-D | Min 15 Nov 12.00 – Sen 16 Nov 23.59 | 36 jam | **Anin** | Serving tables, API 13+1, dashboard v1 |
| — | Sel 17 Nov | buffer | tidak ada | Integrasi dan demo di luar window |

**Gate M1 (Senin 16 Nov 23.59):** satu trade dan satu post terlihat dari bronze → silver → gold → API → dashboard, freshness badge benar, `make e2e-smoke` hijau.

### Siklus 2 — ML, operations, trust, hardening

| Slot | Window | Durasi | Pemilik | Fokus |
| :---- | :---- | :---- | :---- | :---- |
| W2-A | Rab 18 Nov 00.00 – Kam 19 Nov 11.59 | 36 jam | **Dhea** | ML dataset, E1/E2, MLflow, gate, batch inference |
| W2-B | Kam 19 Nov 12.00 – Jum 20 Nov 23.59 | 36 jam | **Vio** | Metrics, logs, Grafana, 16 alert rule, drill 3 kelas |
| W2-C | Sab 21 Nov 00.00 – Min 22 Nov 11.59 | 36 jam | **Anin** | Lineage, catalog, gateway, RBAC, security scan |
| W2-D | Min 22 Nov 12.00 – Sen 23 Nov 23.59 | 36 jam | **Lois** | Backup/restore, fault injection, benchmark, evidence freeze |
| — | Sel 24 Nov | buffer | tidak ada | Integrasi dan demo di luar window |

**Gate M2 (Senin 23 Nov 23.59):** prediksi tampil di dashboard, minimal satu alert per kelas terbukti fire dan resolve, lineage dan RBAC terbukti, restore terbukti, benchmark versi awal terdokumentasi.

### Siklus 3 — Completeness dan penutupan

| Slot | Window | Durasi | Pemilik | Fokus |
| :---- | :---- | :---- | :---- | :---- |
| C3-A | Rab 25 Nov 00.00 – Kam 26 Nov 11.59 | 36 jam | **Anin** | Replica kedua, load balancing, health removal, circuit breaker, security sweep |
| C3-B | Kam 26 Nov 12.00 – Jum 27 Nov 23.59 | 36 jam | **Dhea** | Feast online, paritas point-in-time join, retraining otomatis, promotion otomatis, drift |
| C3-C | Sab 28 Nov 00.00 – Min 29 Nov 11.59 | 36 jam | **Vio** | Profil 3/4 node, ACL final, Loki, catalog 5 view, governance, lifecycle, hosting docs |
| C3-D | Min 29 Nov 12.00 – Sen 30 Nov 23.59 | 36 jam | **Lois** | DQ-01…08, sapuan T-01…T-42, benchmark B1–B4, 10 fault \+ RTO, clean clone, tag, rehearsal |
| — | Sel 1 Des | tidak dijadwalkan | tidak ada | Pekerjaan berhenti Senin 30 Nov 23.59 |

**Gate M3 (Senin 30 Nov 23.59):** seluruh komponen `ARCHITECTURE.md` berdiri, T-01…T-42 punya evidence (pass atau partial dengan alasan tertulis), tag `v1.0-demo` dibuat, tidak ada pekerjaan tersisa.

### 2.1 Matriks pembagian

| Orang | Siklus 1 | Siklus 2 | Siklus 3 | Total jam |
| :---- | :---- | :---- | :---- | :---- |
| Anin | W1-D API \+ dashboard | W2-C lineage \+ catalog \+ security | C3-A gateway \+ resilience \+ security sweep | 108 jam |
| Lois | W1-B stream \+ silver market | W2-D recovery \+ benchmark | C3-D evidence completion \+ close-out | 108 jam |
| Dhea | W1-A foundation \+ bronze | W2-A ML loop | C3-B ML completeness | 108 jam |
| Vio | W1-C gold \+ quality | W2-B observability \+ alerting | C3-C platform completeness | 108 jam |

Siklus 1 dan 2 diundi acak dan dapat direproduksi: `Get-Random -SetSeed 1111` (`dhea → lois → vio → anin`) dan `-SetSeed 1811` (`dhea → vio → anin → lois`). Siklus 3 memakai kesinambungan area, bukan undian: setiap orang melanjutkan komponen yang ia pegang di siklus 2, sehingga tidak ada waktu terbuang untuk membangun konteks baru di slot terakhir. Setiap komponen inti tetap punya minimal dua orang yang pernah menyentuhnya.

---

## 3\. Aturan umum yang berlaku untuk semua slot

### 3.1 Definisi selesai (ARCHITECTURE §22.4, disesuaikan)

Sebuah item dianggap selesai hanya jika seluruh baris terpenuhi:

1. Kode/laporan ter-commit di branch `slot/w{minggu}-{slot}-{nama}`, PR direview minimal satu orang lain.  
2. Unit/contract test untuk kode baru lulus (`make test`).  
3. Gate integrasi lulus (`make e2e-smoke` hijau di profil `dev`).  
4. Perubahan tercatat di catalog atau README/runbook komponen.  
5. File evidence ada di `evidence/` dan tertaut dari handoff.  
6. Jalur demo tidak rusak: langkah demo yang sudah ada tetap jalan.

### 3.2 Format evidence

- Nama file: `evidence/<area>/<ID>_<YYYYMMDDTHHMM>_<git-sha-pendek>.<ext>` Contoh: `evidence/tests/T04_20261113T1800_a1b2c3d.txt`  
- Setiap file teks diawali header: `id`, `timestamp UTC`, `commit SHA`, `command`, `result`, `owner`.  
- Screenshot menampilkan jam sistem dan URL.  
- Output mentah disimpan, bukan hanya ringkasan.  
- `git status --porcelain` harus kosong sebelum menjalankan evidence run.

### 3.3 Kontrak handoff

Setiap slot diakhiri dengan `docs/handoff/w{minggu}-{slot}.md` mengikuti template:

````markdown
# Handoff W1-A — Dhea

## Status
- CP1: PASS / PARTIAL / FAIL
- CP2: PASS / PARTIAL / FAIL
- CP3: PASS / PARTIAL / FAIL

## Yang sudah jalan
- <komponen> — `<perintah untuk membuktikan>`

## Yang belum jalan / stub
- <komponen> — <apa yang hilang> — <dampak ke slot berikut>

## Cara menjalankan
```bash
make dev-up
make ingest-once
make e2e-smoke
```

## Kegagalan yang diketahui
- <gejala> — <penyebab dugaan> — <workaround>

## Langkah berikutnya untuk slot berikutnya
1. ...
2. ...

## Evidence
- `evidence/...` — <satu baris isi>
````

&nbsp;

### 3.4 Aturan eskalasi

| Kondisi | Tindakan |
| :---- | :---- |
| CP1 belum hijau pada \+12 jam | Potong scope ke Must-only, tulis di issue, lanjut. Jangan menambah jam. |
| CP2 belum demo-able pada \+24 jam | Freeze fitur, selesaikan happy path \+ evidence, sisanya masuk daftar gap di handoff |
| CP3 sesuatu gagal | Serahkan dengan tag `wX-Y-ok` hanya jika gate hijau; kalau tidak, tag tidak dibuat dan gap dicatat |
| Gate `e2e-smoke` merah di akhir slot | Kembalikan ke tag hijau terakhir, tulis sebabnya, serahkan pipeline dalam keadaan jalan |
| Dependency eksternal mati (DNS Binance, API Bluesky) | Pakai mode replay/fixture, catat di handoff, jangan menunggu |

### 3.5 Target Makefile

Dibuat oleh W1-A, dipakai oleh semua slot setelahnya:

| Target | Fungsi |
| :---- | :---- |
| `make dev-up` / `make dev-down` | Nyalakan/matikan profil dev |
| `make reset` | Hapus volume dev, deploy ulang bersih |
| `make doctor` | Tabel health semua service |
| `make ingest-once` | Jalankan harvest Bluesky \+ producer replay sekali |
| `make transform` | dbt silver \+ gold |
| `make quality` | GX checkpoint \+ `dq_report.json` |
| `make e2e-smoke` | Cek bronze → silver → gold → API → dashboard |
| `make test` / `make test-cov` | Unit \+ contract test, coverage gate 40% |
| `make benchmark` | Matrix benchmark, tulis CSV \+ SHA |
| `make backup` / `make restore` | Backup dan restore PostgreSQL |
| `make evidence` | Kumpulkan manifest evidence \+ daftar file yang hilang |

---

## 4\. Siklus 1

### W1-A — Dhea — Foundation dan bronze

| Item | Isi |
| :---- | :---- |
| Window | Rab 11 Nov 00.00 – Kam 12 Nov 11.59 |
| Bergantung pada | — (slot pertama) |
| Menyerahkan ke | Lois (W1-B) |
| Gate keluar | Tag `w1-a-ok`; trade dan post ada di bronze dalam mode live atau replay |

**Lingkup Must**

1. Repo skeleton: `src/{ingestion,transform,quality,serving,ml}`, `deploy/`, `dbt/`, `tests/`, `Makefile`, `pyproject.toml`, `.env.example`, `.gitignore`, `.gitattributes` (LF).  
2. Compose profil `dev`: traefik, redpanda, minio, postgres-core, lakekeeper, api (placeholder). Named volume, health check, restart policy, resource limit, non-root user.  
3. MinIO: bucket warehouse \+ artifact \+ backup, user per service. Lakekeeper: warehouse \+ namespace `bronze`, `silver`, `gold` \+ schema `ops` di PostgreSQL.  
4. Kontrak data v1: `trade.v1` (`symbol`, `trade_id`, `price`, `qty`, `event_ts`, `ingest_ts`, `payload_hash`), `social_post.v1` (`post_uri`, `created_at`, `text`, `author_did`, `ingest_ts`, `payload_hash`). Validator pydantic \+ JSON Schema.  
5. Producer Binance: WebSocket `aggTrade`, reconnect \+ backoff, `acks=all` ke topic `market.trades`, fallback `BinanceVisionReplayFeed` untuk mode replay tanpa mengubah pipeline.  
6. Harvester Bluesky: `app.bsky.feed.searchPosts` per jam, cursor, backoff, cache lokal, mode replay dari file.  
7. Penulis bronze PyIceberg: append-only, partisi `event_date`, kolom `event_ts`, `ingest_ts`, `payload_hash`, `batch_id`.  
8. Ledger `ops.batch_runs`: `batch_id`, `source`, `window_start`, `window_end`, `row_count`, `checksum`, `status`.

**Should (hanya kalau Must selesai)**

- `make doctor` dengan tabel health yang rapi.  
- CI lint (ruff \+ sqlfluff) dan `docker compose config` untuk profil `dev` \+ `two-node`.  
- Pre-download satu window replay untuk demo.

**Defer**

- Profil empat node dan observability stack dikerjakan di Siklus 3; API konten di W1-D.

**Estimasi jam (24 jam efektif)**

| Workstream | Jam |
| :---- | :---- |
| Repo skeleton \+ Makefile \+ CI lint | 2 |
| Compose dev \+ health \+ volume \+ limit | 4 |
| MinIO \+ Lakekeeper \+ namespace \+ schema `ops` | 2 |
| Kontrak \+ validator | 2 |
| Producer Binance (live \+ replay) | 5 |
| Harvester Bluesky | 4 |
| Bronze writer \+ ledger | 3 |
| Evidence \+ handoff | 2 |

**Checkpoint**

| CP | Waktu | Definition of done | Evidence wajib |
| :---- | :---- | :---- | :---- |
| CP1 | Rab 11 Nov 12.00 | `make dev-up` menyalakan 6 service; `make doctor` semua hijau; bucket dan namespace `bronze/silver/gold` ada; `docker compose config` valid | `evidence/deploy/health_<ts>_<sha>.md`, `evidence/deploy/compose-config_<ts>.yml` |
| CP2 | Kam 12 Nov 00.00 | Satu trade masuk bronze lewat live atau replay; satu post masuk bronze; T-01 dan T-02 lulus; satu baris `ops.batch_runs` dengan checksum | `evidence/tests/T01.json`, `evidence/tests/T02.json`, `evidence/ingestion/counts_<ts>.csv`, `evidence/batch/ledger_<ts>.csv` |
| CP3 | Kam 12 Nov 11.59 | Mode replay menjalankan pipeline yang sama tanpa perubahan kode; T-26 lulus (`skipped_identical` pada run kedua); `.env.example` lengkap dan tidak ada secret di git; handoff ditulis | `evidence/batch/T26.json`, `evidence/ingestion/replay_<ts>.txt`, `docs/handoff/w1-a.md` |

**Risiko khusus**

| Risiko | Mitigasi |
| :---- | :---- |
| Domain Binance diblokir DNS | Jalankan replay dari `data.binance.vision` yang sudah diunduh; jangan menunggu |
| Lakekeeper/PyIceberg gagal commit partisi | Fallback: bronze Parquet \+ manifest, Iceberg tetap untuk append-only; catat sebagai ADR deviasi |
| Bluesky rate limit 429 | Backoff \+ cache; demo memakai window yang sudah tersimpan |

---

### W1-B — Lois — Stream processor, silver market, orchestration

| Item | Isi |
| :---- | :---- |
| Window | Kam 12 Nov 12.00 – Jum 13 Nov 23.59 |
| Bergantung pada | W1-A (bronze, topic, kontrak) |
| Menyerahkan ke | Vio (W1-C) |
| Gate keluar | Tag `w1-b-ok`; silver market 1 menit benar dan bisa di-replay |

**Lingkup Must**

1. Topic `market.trades` dikonfigurasi 3 partisi, `acks=all`, retensi 7 hari; consumer group dengan offset committed.  
2. Stream processor micro-batch: baca Redpanda → window 1 menit → OHLCV (`open`, `high`, `low`, `close`, `volume`, `trade_count`).  
3. `event_time` dipisah dari `ingest_time`; watermark; penanganan late event (trade terlambat 2 menit memperbaiki menit yang benar).  
4. Dedup `(symbol, trade_id)` di silver; idempoten terhadap replay.  
5. DLQ \+ tabel quarantine dengan alasan penolakan; metrik `quarantine_total`.  
6. Silver market PyIceberg, partisi `event_date`, plus kolom `ingest_ts` untuk merge policy.  
7. dbt model silver market \+ test (`unique`, `not_null`, `accepted_values` untuk OHLC konsisten).  
8. Prefect: flow harvester (deploy, schedule per jam), flow transform, retry policy, concurrency limit 1 untuk job berat; job yang dibunuh setelah bronze dan sebelum commit harus bisa di-retry tanpa duplikat (T-27).

**Should**

- Endpoint `/metrics` pada processor (lag, batch size, commit count).  
- `make ingest-once` dan `make transform` benar-benar berfungsi.  
- CLI replay per rentang menit.

**Defer**

- Silver social (dikerjakan W1-C), alert rule (W2-B), backfill UI.

**Estimasi jam (24 jam efektif)**

| Workstream | Jam |
| :---- | :---- |
| Verifikasi handoff \+ perbaikan gate | 2 |
| Konfigurasi topic \+ consumer offset \+ lag | 3 |
| Micro-batch OHLCV \+ watermark \+ late event | 5 |
| Dedup \+ DLQ \+ quarantine \+ metrik | 4 |
| Silver market \+ dbt model \+ test | 4 |
| Prefect flow \+ schedule \+ retry | 4 |
| Evidence \+ handoff | 2 |

**Checkpoint**

| CP | Waktu | Definition of done | Evidence wajib |
| :---- | :---- | :---- | :---- |
| CP1 | Jum 13 Nov 00.00 | Consumer jalan dari offset tersimpan; lag terlihat di `/metrics`; stop/start consumer tanpa trigger manual dan tidak ada data hilang | `evidence/stream/lag_<ts>.png`, `evidence/stream/restart_<ts>.txt` |
| CP2 | Jum 13 Nov 12.00 | OHLC 1 menit cocok dengan hitungan tangan (T-08); dedup T-04; late event T-06; malformed T-07 masuk quarantine dengan alasan | `evidence/tests/T04.txt`, `T06.txt`, `T07.txt`, `T08.txt` |
| CP3 | Jum 13 Nov 23.59 | Replay satu jam dua kali menghasilkan hasil identik (T-05); restart consumer memproses semua event (T-28); poison record masuk DLQ dan bisa di-replay (T-29); job yang gagal setelah bronze di-retry tanpa duplikat dan ledger mencatat `failed` → `succeeded` (T-27); silver freshness ≤2 menit (T-24); dbt test hijau | `evidence/replay/T05.txt`, `evidence/stream/T28.txt`, `evidence/stream/T29.json`, `evidence/batch/T27.json`, `evidence/tests/T24.txt`, `docs/handoff/w1-b.md` |

**Risiko khusus**

| Risiko | Mitigasi |
| :---- | :---- |
| PyIceberg tidak bisa upsert partisi | Tulis partisi dengan overwrite penuh per `event_date` \+ `symbol`; jangan merge baris |
| Late event tidak terkoreksi karena window sudah ditutup | Simpan watermark \+ toleransi 5 menit; dokumentasikan batasnya di handoff |
| Redpanda memory | Turunkan retensi ke 3 hari di profil dev |

---

### W1-C — Vio — Silver social, sentiment, tiga gold mart, quality gate

| Item | Isi |
| :---- | :---- |
| Window | Sab 14 Nov 00.00 – Min 15 Nov 11.59 |
| Bergantung pada | W1-A (bronze social, kontrak), W1-B (silver market, dbt project) |
| Menyerahkan ke | Anin (W1-D) |
| Gate keluar | Tag `w1-c-ok`; tiga mart terisi, GX memblokir gold saat data buruk |

**Lingkup Must**

1. Silver social: dedup `post_uri`, parse `created_at` sebagai `event_ts`, filter teks kosong.  
2. Pseudonimisasi: hash handle dan DID (`sha256` \+ salt dari secret); tidak ada handle, display name, atau DID mentah di silver (ADR-011).  
3. Sentimen VADER: skor `compound` ∈ \[-1, 1\], `pos/neu/neg`; model version dicatat.  
4. `mart_market`: OHLC 1 jam \+ realized volatility dari silver market.  
5. `mart_sentiment`: agregat per jam (jumlah post, rata-rata skor, rasio positif/negatif), plus jam tanpa data tetap muncul dengan nilai null/kosong yang eksplisit.  
6. `mart_ml`: fitur point-in-time (semua fitur ≤ `window_start`) \+ label realized volatility jam berikutnya; kolom `event_hour`, `snapshot_id`.  
7. Merge policy per tabel: `mart_*` pakai partition overwrite; `ingest_ts` terbaru menang; backfill rentang jam lewat flow Prefect.  
8. Great Expectations: suite critical (unique `event_hour`, null `trade_id` \= 0, skor dalam rentang, volume ≥ 0\) \+ suite warning (rasio duplikat \< 2%); checkpoint menulis `dq_report.json`; kegagalan critical memblokir build gold.

**Should**

- Tabel quarantine terpadu yang dipakai juga oleh stream processor.  
- dbt docs ter-generate.  
- GX Data Docs statis.

**Defer**

- Klasifikasi sentimen terlatih (TF-IDF \+ Logistic Regression) — cukup VADER.  
- Catalog portal versi dasar (W2-C), dilengkapi menjadi 5 view di C3-C.

**Estimasi jam (24 jam efektif)**

| Workstream | Jam |
| :---- | :---- |
| Verifikasi handoff \+ perbaikan gate | 2 |
| Silver social \+ pseudonimisasi \+ VADER | 5 |
| `mart_market` \+ `mart_sentiment` | 5 |
| `mart_ml` fitur \+ label \+ uji no-leakage | 4 |
| GX suite \+ checkpoint \+ `dq_report.json` \+ gate | 4 |
| Merge policy \+ backfill | 2 |
| Evidence \+ handoff | 2 |

**Checkpoint**

| CP | Waktu | Definition of done | Evidence wajib |
| :---- | :---- | :---- | :---- |
| CP1 | Sab 14 Nov 12.00 | Silver social terisi; pseudonimisasi terbukti (kolom sensitif tidak ada); T-03 dan T-10 lulus | `evidence/tests/T03.txt`, `T10.txt`, `evidence/security/pii-columns_<ts>.txt` |
| CP2 | Min 15 Nov 00.00 | Tiga mart ada dan `dbt build` hijau; fitur `mart_ml` semuanya ≤ `window_start` (T-09); row count per mart tercatat | `evidence/dbt/docs.png`, `evidence/tests/T09.txt`, `evidence/dq/mart-counts_<ts>.csv` |
| CP3 | Min 15 Nov 11.59 | Injeksi null `trade_id` memblokir gold dan memicu jalur alert (T-11); duplikat 2% hanya warning (T-12); rerun tanpa perubahan identik (T-33); rerun dengan koreksi sumber mengubah nilai yang benar (T-32); schema evolution nullable column terbaca di snapshot lama (T-31) | `evidence/dq/dq_report.json`, `evidence/tests/T11.txt`, `T12.txt`, `evidence/storage/T31.txt`, `T32.json`, `T33.json`, `docs/handoff/w1-c.md` |

**Risiko khusus**

| Risiko | Mitigasi |
| :---- | :---- |
| Data sentimen terlalu sedikit | Tetap bangun mart \+ dokumentasikan limitasi; jangan sintesis data |
| GX memblokir demo karena satu baris buruk | Sediakan mode `--warning-only` yang tercatat, jangan dimatikan diam-diam |
| Jam tanpa post membuat join hilang | Outer join per `event_hour` dan isi eksplisit |

---

### W1-D — Anin — Serving layer, API 13+1, dashboard v1

| Item | Isi |
| :---- | :---- |
| Window | Min 15 Nov 12.00 – Sen 16 Nov 23.59 |
| Bergantung pada | W1-C (tiga mart), W1-A (PostgreSQL, gateway) |
| Menyerahkan ke | Dhea (W2-A) |
| Gate keluar | Tag `w1-d-ok`; demo end-to-end M1 jalan |

**Lingkup Must**

1. Skema serving PostgreSQL: `serving.market_latest`, `serving.sentiment_hourly`, `serving.volatility`, `serving.predictions` (tabel disiapkan walau belum terisi), `serving.freshness`.  
2. Loader: gold → serving (dipanggil dari flow Prefect `transform`), idempoten.  
3. DuckDB read path ke Iceberg untuk query rentang historis.  
4. 13 endpoint read-only \+ 1 scoring:  
   - `GET /v1/meta/instance`, `GET /v1/market/latest`, `GET /v1/market/ohlc`, `GET /v1/market/volatility/latest`, `GET /v1/market/volatility/range`, `GET /v1/sentiment/latest`, `GET /v1/sentiment/hourly`, `GET /v1/sentiment/range`, `GET /v1/freshness`, `GET /v1/dataset`, `GET /v1/dataset/{id}/schema`, `GET /v1/quality/status`, `GET /v1/model/latest`  
   - `POST /v1/predict`  
5. Kontrak error: `application/problem+json` dengan `request_id`; validasi `from`/`to` (400/422).  
6. Pagination cursor stabil untuk endpoint rentang (limit 100, tanpa duplikat/kehilangan baris).  
7. `X-Data-Stale: true` \+ fallback ke PostgreSQL saat MinIO tidak tersedia.  
8. Freshness field di setiap respons yang relevan (umur data dalam detik \+ status `ok/warn/stale`).  
9. `openapi.json` di-commit; `evidence/api/` berisi curl per endpoint.  
10. Streamlit v1: 4 metrik bisnis (harga terakhir, volatilitas jam terakhir, skor sentimen, prediksi jam berikutnya), 2 filter waktu, freshness badge per metrik. Membaca API saja, tidak query langsung ke lake.

**Should**

- API key sederhana (header `X-API-Key`) untuk endpoint scoring; RBAC penuh di W2-C.  
- Cache 30 detik untuk endpoint latest.  
- Panel kualitas data yang membaca `/v1/quality/status`.

**Defer**

- API replica kedua, load balancing, circuit breaker dikerjakan di C3-A.

**Estimasi jam (24 jam efektif)**

| Workstream | Jam |
| :---- | :---- |
| Verifikasi handoff \+ perbaikan gate | 2 |
| Skema serving \+ loader idempoten | 4 |
| DuckDB read path \+ query builder | 3 |
| 13 endpoint read-only | 6 |
| Endpoint scoring \+ kontrak error \+ pagination | 3 |
| Streamlit v1 | 4 |
| OpenAPI \+ evidence \+ handoff | 2 |

**Checkpoint**

| CP | Waktu | Definition of done | Evidence wajib |
| :---- | :---- | :---- | :---- |
| CP1 | Sen 16 Nov 00.00 | `/health/ready` hijau; tiga endpoint inti mengembalikan data serving; freshness terhitung | `evidence/api/smoke_<ts>.txt` |
| CP2 | Sen 16 Nov 12.00 | 14 route terdaftar di OpenAPI; pagination T-14; parameter tidak valid T-34 mengembalikan 400/422 \+ `request_id`; tanpa API key T-13 \= 401 | `openapi.json`, `evidence/tests/T14.txt`, `evidence/api/T34.json`, `evidence/security/api-401.txt` |
| CP3 | Sen 16 Nov 23.59 | MinIO dimatikan → response 200 dengan `X-Data-Stale: true` (T-15); Streamlit menampilkan 4 metrik \+ 2 filter \+ freshness badge; reconciliasi dashboard vs SQL untuk 24 jam (draft T-37); gate M1 demo direkam | `evidence/tests/T15.txt`, `evidence/dashboards/streamlit_<ts>.png`, `evidence/dashboard/reconciliation-draft.json`, `docs/handoff/w1-d.md` |

**Risiko khusus**

| Risiko | Mitigasi |
| :---- | :---- |
| 14 endpoint tidak selesai | Prioritaskan: market/latest, market/ohlc, sentiment/latest, freshness, predict; sisanya endpoint meta yang murah |
| DuckDB lambat pada file kecil banyak | Batasi rentang 14 hari, tambah filter partisi, ukur p95 |
| Streamlit butuh data yang belum ada | Tampilkan state kosong yang jelas, jangan data palsu |

---

## 5\. Siklus 2

### W2-A — Dhea — ML loop

| Item | Isi |
| :---- | :---- |
| Window | Rab 18 Nov 00.00 – Kam 19 Nov 11.59 |
| Bergantung pada | W1-C (`mart_ml`), W1-D (endpoint model/predict) |
| Menyerahkan ke | Vio (W2-B) |
| Gate keluar | Tag `w2-a-ok`; champion terdaftar, prediksi masuk tabel, gate promosi terbukti |

**Lingkup Must**

1. Dataset snapshot: baca `mart_ml` pada snapshot ID tetap; simpan `dataset_id`, rentang waktu, jumlah baris, SHA fitur.  
2. Split kronologis (train/validation/holdout) tanpa shuffle; seed `42`; T-09 ulang pada level fitur.  
3. Baseline: persistence (volatilitas jam sebelumnya) dan EWMA.  
4. E1 (fitur market) dan E2 (market \+ sentimen), model Ridge dan XGBoost kecil, hyperparameter identik antar eksperimen.  
5. MLflow: dua run di experiment yang sama, log params/metrics/artifacts, dataset snapshot ID \+ commit SHA di tag run.  
6. Registry \+ alias `champion`/`challenger`; gate: challenger dipromosikan hanya jika MAE ≥5% lebih baik pada holdout yang sama; keputusan dicatat.  
7. Batch inference per jam: tulis ke `serving.predictions` dengan `input_record_id`, `model_version`, `predicted_at`, `value`, `status`.  
8. Endpoint `POST /v1/predict` memakai model champion; payload valid → 200, malformed → 422, out-of-range → baris `status=error`.  
9. Model card: tujuan, fitur, label, split, metrik, batasan, larangan interpretasi sebagai saran investasi.  
10. Drift report sederhana: distribusi fitur holdout vs produksi \+ metrik error harian.

**Should**

- SHAP/feature importance ringkas untuk laporan.  
- Retrain manual flow di Prefect \+ schedule mingguan (nonaktif saat demo).

**Defer**

- Feast online store dikerjakan di C3-B; deep learning dan tuning hyperparameter besar tidak dikerjakan.

**Estimasi jam (24 jam efektif)**

| Workstream | Jam |
| :---- | :---- |
| Verifikasi handoff \+ perbaikan gate | 2 |
| Snapshot \+ split \+ baseline | 4 |
| E1/E2 training \+ evaluasi | 6 |
| MLflow tracking \+ registry \+ gate | 4 |
| Batch inference \+ prediction contract | 4 |
| Drift \+ model card \+ evidence | 2 |
| Handoff | 2 |

**Checkpoint**

| CP | Waktu | Definition of done | Evidence wajib |
| :---- | :---- | :---- | :---- |
| CP1 | Rab 18 Nov 12.00 | Snapshot dataset tercatat; split kronologis; baseline persistence \+ EWMA punya MAE/RMSE; T-09 lulus | `evidence/ml/dataset_<ts>.json`, `evidence/tests/T09.txt` |
| CP2 | Kam 19 Nov 00.00 | E1 dan E2 terdaftar di MLflow dengan snapshot \+ split identik; tabel perbandingan MAE/RMSE/directional accuracy | `evidence/experiments/E1_vs_E2.md`, tautan run MLflow \+ screenshot |
| CP3 | Kam 19 Nov 11.59 | T-20 reproduktif (retrain snapshot sama, selisih ≤1%); T-21 gate menolak challenger buruk; T-35 dua eksperimen; T-36 payload valid/malformed/out-of-range; predictions terisi; model card ada | `evidence/ml/T20.txt`, `evidence/ml/T21.json`, `evidence/experiments/E1_vs_E2.md`, `evidence/ml/T36.json`, `evidence/ml/model-card.md`, `docs/handoff/w2-a.md` |

**Risiko khusus**

| Risiko | Mitigasi |
| :---- | :---- |
| Sentimen tidak menambah nilai (H0) | Itu hasil yang sah: laporkan, promosikan model market-only, tulis di model card |
| Data \< 300 baris | Perpanjang window gold yang tersedia; laporkan batas sample; jangan sintesis |
| Waktu training \> 5 menit | Kecilkan XGBoost (n\_estimators ≤ 300), catat waktu di benchmark |

---

### W2-B — Vio — Observability dan alerting

| Item | Isi |
| :---- | :---- |
| Window | Kam 19 Nov 12.00 – Jum 20 Nov 23.59 |
| Bergantung pada | W1-B (processor, metrik), W1-D (API), W2-A (metrik model) |
| Menyerahkan ke | Anin (W2-C) |
| Gate keluar | Tag `w2-b-ok`; tiga kelas alert terbukti fire → deliver → resolve |

**Lingkup Must**

1. Prometheus \+ scrape config untuk: API, stream processor, pushgateway (job batch), postgres-exporter, cAdvisor.  
2. Metrik pipeline: `bmip_ingest_events_total`, `bmip_duplicate_total`, `bmip_quarantine_total`, `bmip_consumer_lag`, `bmip_freshness_seconds`, `bmip_batch_duration_seconds`, `bmip_gold_rows`, `bmip_dq_failures_total`, `bmip_predictions_total`.  
3. Structured JSON log di semua service: `timestamp`, `severity`, `service`, `run_id`, `request_id`, `message`; satu contoh log error dengan diagnosis.  
4. Grafana provisioned as code: dashboard `pipeline` (freshness, lag, batch status, DQ) dan `business` (harga, volatilitas, sentimen, prediksi).  
5. 16 alert rule dengan severity, window, threshold, owner, channel, tautan runbook. Tiga kelas wajib: job failure, stream lag/freshness, service/resource.  
6. Routing ke Telegram; pesan memuat runbook link \+ `run_id`.  
7. Runbook minimal untuk tiga kelas alert (gejala, cek, tindakan, eskalasi).  
8. Drill T-39: satu fault per kelas, catat timeline fire → deliver → resolve dengan screenshot.  
9. Rekonsiliasi dashboard vs API vs SQL untuk 24 jam dan 7 hari (T-37) dengan toleransi terdokumentasi.

**Should**

- Panel Grafana tambahan untuk DQ dan model drift.  
- Alert untuk DQ failure dan model drift.

**Defer**

- Dex/oauth2-proxy, alertmanager HA, on-call rotation.

**Estimasi jam (24 jam efektif)**

| Workstream | Jam |
| :---- | :---- |
| Verifikasi handoff \+ perbaikan gate | 2 |
| Prometheus \+ exporter \+ cAdvisor | 3 |
| Metrik pipeline di kode | 3 |
| Structured logging \+ contoh diagnosis | 2 |
| Grafana dua dashboard | 4 |
| 16 rule \+ routing Telegram \+ 3 runbook | 5 |
| Drill T-39 \+ rekonsiliasi T-37 | 3 |
| Handoff | 2 |

**Checkpoint**

| CP | Waktu | Definition of done | Evidence wajib |
| :---- | :---- | :---- | :---- |
| CP1 | Jum 20 Nov 00.00 | `/metrics` ter-scrape untuk minimal 4 target; satu panel Grafana hidup dengan data nyata; log sample punya `run_id` | `evidence/logs/sample_<ts>.jsonl`, `evidence/dashboards/grafana-pipeline_<ts>.png` |
| CP2 | Jum 20 Nov 12.00 | 16 rule ter-load; 3 runbook tertulis; dashboard business menampilkan 4 metrik | `evidence/alerts/rules_<ts>.yml`, `docs/runbooks/alert-*.md` |
| CP3 | Jum 20 Nov 23.59 | Tiga kelas alert fire, terkirim ke Telegram, dan resolve dengan timeline; T-37 dua rentang cocok dalam toleransi | `evidence/alerts/T39.md`, screenshot Telegram, `evidence/dashboard/reconciliation.json`, `docs/handoff/w2-b.md` |

**Risiko khusus**

| Risiko | Mitigasi |
| :---- | :---- |
| Telegram bot token tidak tersedia | Simpan payload notifikasi ke file \+ screenshot webhook receiver lokal; token di `.env` |
| Alert terlalu bising saat demo | Tetapkan `for:` duration 2–5 menit dan threshold yang diuji |
| Metrik tidak ada di kode | Tambahkan pushgateway untuk job batch; jangan mengarang angka |

---

### W2-C — Anin — Lineage, catalog, security

| Item | Isi |
| :---- | :---- |
| Window | Sab 21 Nov 00.00 – Min 22 Nov 11.59 |
| Bergantung pada | W1-B/W1-C (dbt, job), W2-B (observability), W1-D (API) |
| Menyerahkan ke | Lois (W2-D) |
| Gate keluar | Tag `w2-c-ok`; lineage dan matriks RBAC terbukti, scan bersih |

**Lingkup Must**

1. Marquez API \+ Web (profil governance), PostgreSQL governance.  
2. OpenLineage emitter di dbt, Prefect flow, dan stream processor: event `START/COMPLETE/FAIL` dengan `run_id`, dataset input/output, schema facet.  
3. Lineage edge yang bisa ditunjukkan: `bronze.* → silver.* → gold.mart_* → serving.*`.  
4. Raw-to-gold trace T-30: satu `payload_hash` ditelusuri bronze → silver → gold → API, nilainya cocok.  
5. Catalog registry (tabel `ops.dataset_registry` \+ halaman Streamlit): 11 dataset dengan owner, deskripsi, schema, klasifikasi (public/internal/restricted), retensi, jadwal refresh, lokasi, status kualitas.  
6. Pencarian katalog sederhana (nama/owner/tag) \+ halaman detail menampilkan lineage dan status DQ.  
7. Traefik: TLS (sertifikat lokal), route per service, health check, retry, rate limit, header keamanan dasar.  
8. Tailscale ACL deny-by-default: hanya N1–N4 \+ user yang boleh akses port tertentu; tidak ada service terekspos ke luar tailnet.  
9. RBAC aplikasi: `viewer` (read), `operator` (trigger backfill), `admin` (reload katalog/rotate secret); enforcement di API \+ Streamlit; audit log satu baris per percobaan.  
10. Scan: `gitleaks` bersih, PII scan silver (T-22), port scan membuktikan tidak ada service publik, T-13 401 dan T-38 matriks RBAC (200/403/202/200 \+ audit row).

**Should**

- Klasifikasi otomatis berdasarkan nama kolom.  
- Halaman katalog menampilkan freshness.

**Defer**

- Keycloak/Dex/OIDC; approval workflow governance dan retensi otomatis dikerjakan di C3-C.

**Estimasi jam (24 jam efektif)**

| Workstream | Jam |
| :---- | :---- |
| Verifikasi handoff \+ perbaikan gate | 2 |
| Marquez \+ OpenLineage emitter | 5 |
| Catalog registry \+ halaman \+ pencarian | 5 |
| Traefik TLS \+ route \+ retry \+ rate limit | 3 |
| Tailscale ACL \+ verifikasi | 2 |
| RBAC \+ audit log | 4 |
| Scan \+ evidence | 3 |

**Checkpoint**

| CP | Waktu | Definition of done | Evidence wajib |
| :---- | :---- | :---- | :---- |
| CP1 | Sab 21 Nov 12.00 | Marquez menerima minimal satu event lineage dari dbt dengan `run_id` | `evidence/lineage/first-event_<ts>.png`, event JSON mentah |
| CP2 | Min 22 Nov 00.00 | 11 record katalog dengan owner \+ klasifikasi \+ retensi; trace T-30 selesai; RBAC draft (401/403) | `evidence/catalog/registry_<ts>.csv`, `evidence/lineage/T30.md` |
| CP3 | Min 22 Nov 11.59 | T-38 matriks lengkap \+ audit row per percobaan; T-13; T-22; gitleaks bersih; port scan bersih; TLS aktif di semua route | `evidence/security/rbac-matrix.md`, `evidence/security/pii-scan.txt`, `evidence/security/gitleaks.txt`, `evidence/security/port-scan.txt`, `docs/handoff/w2-c.md` |

**Risiko khusus**

| Risiko | Mitigasi |
| :---- | :---- |
| Marquez berat / gagal start | Turunkan retensi, jalankan di profil governance; fallback: exporter OpenLineage ke file \+ screenshot graph dari run dbt |
| Sertifikat TLS lokal tidak dipercaya browser | Dokumentasikan langkah trust \+ sediakan mode HTTP untuk dev |
| RBAC mengunci demo | Seed user demo (viewer/operator/admin) di `.env.example`, jangan hardcode password |

---

### W2-D — Lois — Recovery, benchmark, evidence freeze

| Item | Isi |
| :---- | :---- |
| Window | Min 22 Nov 12.00 – Sen 23 Nov 23.59 |
| Bergantung pada | Seluruh slot sebelumnya |
| Menyerahkan ke | Anin (C3-A) |
| Gate keluar | Tag `w2-d-ok`; evidence index dan `spec-mapping.md` versi draft ada |

**Lingkup Must**

1. Backup: `pg_dump` untuk postgres-core (serving, ops, audit), postgres-ml (MLflow, Prefect, Feast), postgres-gov; manifest berisi ukuran \+ checksum.  
2. Restore drill T-19: dump → drop schema → restore → row count dan checksum cocok.  
3. Restart persistence T-40: `docker compose restart` seluruh stack, data dan offset selamat, cek checksum.  
4. Fault injection: kill stream processor (tidak ada duplikat setelah restart), kill MinIO (API fallback `X-Data-Stale`), minimal dua skenario; ukur RTO per skenario.  
5. Benchmark: throughput replay (target 1.000 trade/s, 10 menit), latency end-to-end, freshness, API latest p95 (\<300 ms), API range 14 hari p95 (\<2 s), DQ runtime, training, inference, resource cAdvisor; minimal satu pasangan before/after (B1 compaction atau B2 partisi).  
6. Coverage gate T-41: `make test-cov` ≥40%, `coverage.json` tersimpan, build gagal di bawah 40%.  
7. Clean-clone T-25: clone bersih → ikuti `docs/install.md` → health hijau \+ dashboard tidak kosong tanpa langkah tak terdokumentasi.  
8. Evidence freeze: `evidence/README.md` dengan commit SHA \+ tabel environment; `evidence/compliance/index.md` memetakan F-01…F-20 → file; `docs/spec-mapping.md` versi draft lengkap; tidak ada link mati.  
9. Tag `w2-d-ok` pada commit yang sama dengan isi evidence. Rehearsal demo dan tag final `v1.0-demo` dilakukan di C3-D, bukan di sini.

**Should**

- Benchmark versi awal: throughput, API latest/range, DQ runtime, training, inference, `resources.csv`.  
- `docs/install.md` versi draft \+ troubleshooting.

**Defer**

- Profil empat node, B3/B4, sapuan penuh 42 test, dan DQ-01…08 dipindah ke Siklus 3\.

**Estimasi jam (24 jam efektif)**

| Workstream | Jam |
| :---- | :---- |
| Verifikasi handoff \+ perbaikan gate | 2 |
| Backup \+ restore \+ checksum | 4 |
| Restart persistence \+ 2 fault injection \+ RTO | 4 |
| Benchmark matrix \+ plot | 5 |
| Coverage gate \+ clean clone | 3 |
| Evidence index \+ spec mapping \+ install doc | 4 |
| Tag \+ rehearsal | 2 |

**Checkpoint**

| CP | Waktu | Definition of done | Evidence wajib |
| :---- | :---- | :---- | :---- |
| CP1 | Sen 23 Nov 00.00 | Backup tiga database \+ manifest; restore mengembalikan row count identik (T-19) | `evidence/recovery/T19.txt`, `evidence/recovery/manifest_<ts>.json` |
| CP2 | Sen 23 Nov 12.00 | Restart persistence lulus (T-40); dua fault injection punya timeline dan RTO; matrix benchmark terisi minimal 5 baris | `evidence/recovery/T40.json`, `evidence/faults/*.txt`, `evidence/benchmark/matrix.csv` |
| CP3 | Sen 23 Nov 23.59 | T-41 ≥40% \+ `coverage.json`; T-25 clean clone versi awal; T-42 matrix awal \+ kesimpulan bottleneck; evidence index resolve semua link; tag `w2-d-ok` | `evidence/tests/coverage.json`, `evidence/deploy/clean-clone.log`, `evidence/benchmark/matrix.csv`, `evidence/compliance/index.md`, `evidence/README.md` |

**Risiko khusus**

| Risiko | Mitigasi |
| :---- | :---- |
| Restore gagal karena versi image berbeda | Pin image tag; simpan dump di volume terpisah; uji restore di database sementara |
| Benchmark tidak stabil di laptop | Warm-up 2 menit dibuang, median 3 run, catat beban CPU lain, tulis variance |
| Evidence link mati | `make evidence` memeriksa manifest; CI gagal jika ada file hilang |

---

## 6\. Siklus 3

Siklus ini menutup semua komponen `ARCHITECTURE.md` yang belum tercakup di Siklus 1–2. Fokusnya bukan fitur baru untuk demo, melainkan kelengkapan, otomatisasi, dan bukti.

### C3-A — Anin — Gateway, resilience, security sweep

| Item | Isi |
| :---- | :---- |
| Window | Rab 25 Nov 00.00 – Kam 26 Nov 11.59 |
| Bergantung pada | W1-D (API), W2-C (Traefik, RBAC, scan) |
| Menyerahkan ke | Dhea (C3-B) |
| Gate keluar | Tag `c3-a-ok`; T-16/T-17/T-18 lulus |

**Lingkup Must**

1. `api-2` di compose `dev` dan `two-node`: image sama, `mem_limit` 700m, health check `/health/ready`, role PostgreSQL read-only.  
2. Traefik `loadBalancer` dua server dari `services.yaml`, strategi `wrr`, health check aktif (interval 10s, timeout 3s), plus generator daftar server.  
3. Middleware API: retry 3× `initialInterval 200ms`, rate limit 100 avg / 200 burst, header keamanan (`contentTypeNosniff`, `frameDeny`, `referrerPolicy`).  
4. Circuit breaker sesuai ARCHITECTURE §19.2 (`ResponseCodeRatio(500,600,0,600) > 0.25 || LatencyAtQuantileMS(50.0) > 1500`), fallback aplikasi ke PostgreSQL \+ `X-Data-Stale`, metrik `bmip_api_fallback_total`.  
5. Toxiproxy di profil `chaos`: latency toxic 2 detik pada jalur API.  
6. Security sweep: Trivy scan image, port scan dari luar tailnet, uji 429 rate limit, uji TLS \+ HSTS, export audit log.  
7. Runbook: `circuit-breaker.md`, `api-fallback.md`, `restart-loop.md`.

**Should**

- Panel Grafana replica distribution \+ circuit state.  
- Batas konkurensi query per replica (bulkhead).

**Defer**

- Dex/oauth2-proxy (opsional menurut ARCHITECTURE §5.3).

**Estimasi jam (24 jam efektif)**

| Workstream | Jam |
| :---- | :---- |
| Verifikasi handoff \+ gate | 2 |
| `api-2` \+ compose \+ `services.yaml` | 3 |
| Traefik LB \+ health check \+ retry \+ rate limit | 3 |
| Circuit breaker \+ Toxiproxy \+ fallback | 4 |
| T-16/T-17/T-18 evidence | 3 |
| Trivy \+ port scan \+ TLS \+ rate limit 429 | 4 |
| 3 runbook \+ audit export | 3 |
| Evidence \+ handoff | 2 |

**Checkpoint**

| CP | Waktu | Definition of done | Evidence wajib |
| :---- | :---- | :---- | :---- |
| CP1 | Rab 25 Nov 12.00 | `api-2` healthy; Traefik mendistribusikan traffic ke dua replica; `services.yaml` ter-render | `evidence/deploy/api2-health_<ts>.md`, `evidence/tests/T16.txt` |
| CP2 | Kam 26 Nov 00.00 | `api-2` dihentikan → tidak ada 5xx (T-17); retry dan rate limit terbukti; Trivy dan port scan awal bersih | `evidence/tests/T17.txt`, `evidence/security/trivy.txt`, `evidence/security/port-scan.txt` |
| CP3 | Kam 26 Nov 11.59 | Latency 2 detik → circuit open → 503 → pulih (T-18); TLS \+ HSTS valid; 429 terdokumentasi; audit log ter-export; 3 runbook ada | `evidence/tests/T18.txt`, `evidence/security/tls.txt`, `evidence/security/rate-limit.txt`, `evidence/security/audit.txt`, `docs/handoff/c3-a.md` |

**Risiko khusus**

| Risiko | Mitigasi |
| :---- | :---- |
| Toxiproxy tidak kompatibel dengan Docker Desktop di Windows | Simulasi latency lewat endpoint `/v1/meta/slow` \+ `sleep`; catat deviasi di handoff |
| Circuit breaker memutus dashboard | Middleware hanya dipasang di router API, bukan router Streamlit |
| Dua replica berebut memori | `api-2` hanya di profil `dev` dan `two-node`; limit 700m |

---

### C3-B — Dhea — ML completeness

| Item | Isi |
| :---- | :---- |
| Window | Kam 26 Nov 12.00 – Jum 27 Nov 23.59 |
| Bergantung pada | W2-A (ML loop), W1-C (`mart_ml`) |
| Menyerahkan ke | Vio (C3-C) |
| Gate keluar | Tag `c3-b-ok`; inference membaca Feast online, retraining dan promotion otomatis terbukti |

**Lingkup Must**

1. Feast repo: entity `symbol`, feature view `market_features_1m` (TTL 1 jam), `sentiment_1h` (TTL 2 jam), `market_hourly` (TTL 2 jam), offline source Parquet/Iceberg, online store PostgreSQL schema `feast`, registry di volume.  
2. `feast apply` \+ `feast materialize` per jam melalui flow Prefect `refresh_feast`.  
3. Training memakai `get_historical_features` (point-in-time join); hasilnya setara `mart_ml`: row count dan hash kolom fitur identik.  
4. Inference membaca online store; metrik `bmip_feature_age_seconds`; tolak prediksi bila feature age \> 2 jam dan tulis `status=error`.  
5. Retraining: deployment `train_volatility` jadwal Minggu 02.00 UTC \+ trigger drift (PSI \> 0.2 pada top-5 fitur → challenger dalam 24 jam); trigger diuji dengan injeksi drift sintetis.  
6. Promotion otomatis sesuai gate ARCHITECTURE §11.7: MAE ≥5% lebih baik, RMSE tidak lebih buruk 5%, leakage test lulus, model card lengkap → alias `champion`, model lama `archived`, keputusan tercatat di `serving.model_decisions`.  
7. Drift report harian: PSI per fitur, KS test, rolling MAE 7 hari → `serving.drift_metrics` \+ panel Grafana.  
8. E1/E2 dijalankan ulang setelah Feast aktif dari snapshot yang sama; tabel perbandingan diperbarui.

**Should**

- Feature importance ringkas di model card.  
- Peringatan otomatis bila baris training \< 300\.

**Defer**

- Classifier sentimen TF-IDF \+ Logistic Regression (ditandai `MAY` di ARCHITECTURE §11.10; VADER tetap dipakai).

**Estimasi jam (24 jam efektif)**

| Workstream | Jam |
| :---- | :---- |
| Verifikasi handoff \+ gate | 2 |
| Feast repo \+ feature views \+ apply | 5 |
| Online store \+ materialize \+ integrasi inference | 5 |
| Bukti paritas point-in-time join | 3 |
| Retraining terjadwal \+ drift trigger \+ promotion otomatis | 5 |
| Drift report \+ model card \+ E1/E2 ulang | 2 |
| Handoff | 2 |

**Checkpoint**

| CP | Waktu | Definition of done | Evidence wajib |
| :---- | :---- | :---- | :---- |
| CP1 | Jum 27 Nov 00.00 | `feast apply` sukses; materialize jalan; online read \< 50 ms | `evidence/ml/feast-apply_<ts>.txt`, `evidence/ml/online-latency_<ts>.txt` |
| CP2 | Jum 27 Nov 12.00 | PIT join setara `mart_ml` (row count \+ hash); inference memakai online store; `bmip_feature_age_seconds` terlihat | `evidence/ml/pit-parity_<ts>.json`, `evidence/ml/feature-age_<ts>.png` |
| CP3 | Jum 27 Nov 23.59 | Retrain terjadwal \+ drift trigger terbukti; promotion otomatis menolak challenger buruk dan menerima yang lebih baik; T-20/T-21/T-35 lulus ulang; model card final; drift report tersimpan | `evidence/ml/retrain-schedule_<ts>.png`, `evidence/ml/T21.json`, `evidence/experiments/E1_vs_E2.md`, `evidence/ml/model-card.md`, `evidence/ml/drift_<ts>.json`, `docs/handoff/c3-b.md` |

**Risiko khusus**

| Risiko | Mitigasi |
| :---- | :---- |
| Materialization lambat atau boros memori | Batasi jumlah feature view, materialize per jam bukan per menit |
| Online dan offline tidak konsisten | Uji paritas sebagai gate CP2; CP3 diblokir bila gagal |
| Drift trigger palsu saat data tipis | Minimum 24 baris sebelum PSI dihitung; ambang dicatat |

---

### C3-C — Vio — Platform completeness

| Item | Isi |
| :---- | :---- |
| Window | Sab 28 Nov 00.00 – Min 29 Nov 11.59 |
| Bergantung pada | W1-A (compose), W2-B (metrics), W2-C (gateway) |
| Menyerahkan ke | Lois (C3-D) |
| Gate keluar | Tag `c3-c-ok`; profil empat node valid, catalog lengkap, lifecycle berjalan |

**Lingkup Must**

1. Profil `three-node` dan `four-node`: `compose.node1..4.yml` \+ `deploy/env/node1..4.env` \+ `services.yaml` final; verifikasi nyata minimal dua node, sisanya divalidasi dengan `docker compose config`.  
2. Tailscale ACL final (ARCHITECTURE §5.5.2) \+ uji deny-by-default antar node.  
3. Loki \+ Promtail: log shipping, label `service`/`node`/`level`, query `{service="stream-processor"} |= "run_id"`, datasource Grafana.  
4. Catalog portal 5 view: search, detail, lineage, quality, governance; pencarian `tsvector` \+ `pg_trgm`; filter domain, classification, layer.  
5. Governance workflow: register/change/deprecate/delete dataset; test `metadata_consistency` (registry `refresh_schedule` vs `updated_at` aktual); `make docs` menghasilkan `docs/data-dictionary.md`.  
6. Lifecycle: job `compact_iceberg` (`rewrite_data_files` target 128 MB), snapshot expiry 7 hari, orphan file removal, retensi bronze 14 / silver 30 / gold 90; jalankan sekali dengan catatan files before/after.  
7. Hosting docs: `docs.bmip.local` untuk dbt docs dan GX Data Docs melalui Traefik.  
8. Retensi gold menjadi 90 hari, membatalkan pemotongan 30 hari di Siklus 2\.

**Should**

- Panel Grafana governance: dataset tanpa owner, dataset tanpa deskripsi.  
- Export katalog ke CSV sebagai evidence.

**Defer**

- Pencarian semantik berbasis embedding.

**Estimasi jam (24 jam efektif)**

| Workstream | Jam |
| :---- | :---- |
| Verifikasi handoff \+ gate | 2 |
| Profil 3/4 node \+ services.yaml \+ validasi | 4 |
| ACL final \+ port scan | 2 |
| Loki \+ Promtail \+ datasource | 3 |
| Catalog 5 view \+ search | 5 |
| Governance workflow \+ metadata test \+ data dictionary | 3 |
| Compaction \+ expiry \+ retention | 3 |
| Hosting docs \+ handoff | 2 |

**Checkpoint**

| CP | Waktu | Definition of done | Evidence wajib |
| :---- | :---- | :---- | :---- |
| CP1 | Sab 28 Nov 12.00 | `docker compose config` valid untuk `three-node` dan `four-node`; ACL final teruji; Loki menerima log berlabel `run_id` | `evidence/deploy/compose-3node.yml`, `evidence/deploy/compose-4node.yml`, `evidence/security/tailscale-acl_<ts>.json`, `evidence/logs/loki_<ts>.png` |
| CP2 | Min 29 Nov 00.00 | Catalog 5 view hidup; search mengembalikan hasil untuk nama/owner/tag; data dictionary ter-generate | `evidence/catalog/views_<ts>.png`, `evidence/catalog/search_<ts>.txt`, `docs/data-dictionary.md` |
| CP3 | Min 29 Nov 11.59 | Compaction \+ snapshot expiry \+ retensi berjalan dengan files before/after; `docs.bmip.local` menyajikan dbt dan GX docs; `metadata_consistency` lulus | `evidence/storage/compaction_<ts>.json`, `evidence/storage/retention_<ts>.txt`, `evidence/deploy/docs-hosting_<ts>.png`, `evidence/catalog/metadata-test_<ts>.txt`, `docs/handoff/c3-c.md` |

**Risiko khusus**

| Risiko | Mitigasi |
| :---- | :---- |
| Hanya satu laptop tersedia saat uji | Validasi 4-node lewat `compose config` \+ uji dua node nyata; batasnya dicatat |
| Compaction/expiry menghapus snapshot yang dipakai training | Expiry hanya untuk snapshot \> 7 hari; snapshot ID training diverifikasi masih terbaca |
| Loki menambah memori di profil dev | Loki mati di `dev`, hidup di `two-node` dan `four-node` |

---

### C3-D — Lois — Evidence completion dan penutupan

| Item | Isi |
| :---- | :---- |
| Window | Min 29 Nov 12.00 – Sen 30 Nov 23.59 |
| Bergantung pada | Seluruh slot sebelumnya |
| Menyerahkan ke | — (gate penutup) |
| Gate keluar | Tag `c3-d-ok` dan `v1.0-demo`; semua evidence resolve; selesai Senin 30 Nov 23.59 |

**Lingkup Must**

1. Matriks injeksi DQ-01…DQ-08 lengkap dengan `dq_report.json` dan quarantine record.  
2. Sapuan T-01…T-42: jalankan semua, simpan output, catat `pass` / `partial` / `fail` \+ alasan di `evidence/compliance/index.md`.  
3. Benchmark penuh: B1 compaction, B2 partisi, B3 thread DuckDB, B4 batch size; warm-up dibuang, median minimal 3 run; plus throughput replay 1.000 trade/s, latency end-to-end, freshness, cold cache, DQ runtime, training, inference, `resources.csv`.  
4. Matriks fault ARCHITECTURE §20.3: 10 skenario, timeline dan RTO per skenario ke `evidence/recovery/rto.csv`.  
5. Clean-clone T-25 final di laptop bersih \+ `docs/install.md` final.  
6. `evidence/README.md` (index, environment, commit SHA), `evidence/compliance/index.md` tanpa link mati, `docs/spec-mapping.md` draft lengkap F-01…F-20 \+ 11 aspek penilaian.  
7. Tag `v1.0-demo` pada commit yang sama dengan isi evidence; setelah tag hanya boleh perbaikan evidence.  
8. Rehearsal demo 15 menit (ARCHITECTURE §20.7) satu kali; celah dicatat.

**Should**

- Grafik benchmark (PNG) selain CSV.  
- Export `ops.batch_runs`, `ops.alert_events`, `governance.audit_log` sebagai CSV bukti.

**Defer**

- Paket F-20 (laporan, PPT, video) tidak dijadwalkan di dokumen ini.

**Estimasi jam (24 jam efektif)**

| Workstream | Jam |
| :---- | :---- |
| Verifikasi handoff \+ gate | 2 |
| DQ-01…DQ-08 | 4 |
| Sapuan 42 test \+ perbaikan | 6 |
| Benchmark B1–B4 \+ matrix \+ resources | 4 |
| 10 fault \+ RTO | 4 |
| Clean clone \+ install doc | 2 |
| Evidence index \+ spec-mapping \+ tag \+ rehearsal | 2 |

**Checkpoint**

| CP | Waktu | Definition of done | Evidence wajib |
| :---- | :---- | :---- | :---- |
| CP1 | Sen 30 Nov 00.00 | DQ-01…DQ-08 selesai; minimal 50% test T-01…T-42 sudah dijalankan dan dicatat; dua eksperimen benchmark selesai | `evidence/dq/DQ-0*.json`, `evidence/compliance/index.md` (draft), `evidence/benchmark/matrix.csv` (partial) |
| CP2 | Sen 30 Nov 12.00 | 42 test dijalankan semua (tidak ada yang belum dicoba); 10 skenario fault punya timeline \+ RTO | `evidence/tests/T*.{json,txt}`, `evidence/faults/*.txt`, `evidence/recovery/rto.csv` |
| CP3 | Sen 30 Nov 23.59 | Clean clone lulus; evidence index resolve; `spec-mapping.md` lengkap; tag `v1.0-demo`; rehearsal tercatat; tidak ada pekerjaan tersisa | `evidence/deploy/clean-clone.log`, `evidence/README.md`, `docs/spec-mapping.md`, `git tag v1.0-demo`, `evidence/deploy/rehearsal_<ts>.md` |

**Risiko khusus**

| Risiko | Mitigasi |
| :---- | :---- |
| Ada test yang gagal di menit terakhir | Tandai `partial` \+ alasan tertulis di compliance index; jangan klaim pass tanpa evidence |
| Benchmark tidak stabil | Median 3 run, catat variance dan beban CPU lain |
| Link evidence mati | `make evidence` memeriksa manifest; CI gagal bila file hilang |

---

## 7\. Peta evidence dan test ID

| Test | Arti singkat | Slot pemilik | File utama |
| :---- | :---- | :---- | :---- |
| T-01 | Kontrak social menerima post valid | W1-A | `evidence/tests/T01.json` |
| T-02 | Kontrak market menolak harga negatif | W1-A | `evidence/tests/T02.json` |
| T-03 | Dedup social | W1-C | `evidence/tests/T03.txt` |
| T-04 | Dedup market | W1-B | `evidence/tests/T04.txt` |
| T-05 | Replay idempoten | W1-B | `evidence/replay/T05.txt` |
| T-06 | Koreksi late event | W1-B | `evidence/tests/T06.txt` |
| T-07 | Karantina malformed | W1-B | `evidence/tests/T07.txt` |
| T-08 | Kebenaran OHLC | W1-B | `evidence/tests/T08.txt` |
| T-09 | Tanpa leakage fitur | W1-C, W2-A | `evidence/tests/T09.txt` |
| T-10 | Rentang sentimen | W1-C | `evidence/tests/T10.txt` |
| T-11 | Gate DQ critical | W1-C | `evidence/tests/T11.txt` |
| T-12 | Jalur warning DQ | W1-C | `evidence/tests/T12.txt` |
| T-13 | Autentikasi API | W1-D, W2-C | `evidence/security/api-401.txt` |
| T-14 | Pagination | W1-D | `evidence/tests/T14.txt` |
| T-15 | Fallback stale | W1-D | `evidence/tests/T15.txt` |
| T-19 | Backup dan restore | W2-D | `evidence/recovery/T19.txt` |
| T-20 | Reproduktifitas model | W2-A | `evidence/ml/T20.txt` |
| T-21 | Gate promosi | W2-A | `evidence/ml/T21.json` |
| T-22 | PII scan | W2-C | `evidence/security/pii-scan.txt` |
| T-23 | Event lineage | W2-C | `evidence/lineage/T23.png` |
| T-24 | Freshness end-to-end | W1-B | `evidence/tests/T24.txt` |
| T-25 | Clean-clone redeploy | W2-D (versi awal), C3-D (final) | `evidence/deploy/clean-clone.log` |
| T-26 | Idempotensi batch | W1-A | `evidence/batch/T26.json` |
| T-27 | Retry job gagal tanpa duplikat | W1-B | `evidence/batch/T27.json` |
| T-28 | Restart consumer | W1-B | `evidence/stream/T28.txt` |
| T-29 | DLQ capture dan replay | W1-B | `evidence/stream/T29.json` |
| T-30 | Trace raw-to-gold | W2-C | `evidence/lineage/T30.md` |
| T-31 | Schema evolution | W1-C | `evidence/storage/T31.txt` |
| T-32 | Merge policy, sumber berubah | W1-C | `evidence/storage/T32.json` |
| T-33 | Merge policy, sumber sama | W1-C | `evidence/storage/T33.json` |
| T-34 | Parameter tidak valid | W1-D | `evidence/api/T34.json` |
| T-35 | Dua eksperimen E1/E2 | W2-A | `evidence/experiments/E1_vs_E2.md` |
| T-36 | Payload inference salah | W1-D (validasi), W2-A (final) | `evidence/ml/T36.json` |
| T-37 | Rekonsiliasi dashboard | W1-D (draft), W2-B (final) | `evidence/dashboard/reconciliation.json` |
| T-38 | Matriks RBAC | W2-C | `evidence/security/rbac-matrix.md` |
| T-39 | Drill alert | W2-B | `evidence/alerts/T39.md` |
| T-40 | Restart dan restore | W2-D | `evidence/recovery/T40.json` |
| T-41 | Coverage gate | W2-D | `evidence/tests/coverage.json` |
| T-42 | Benchmark before/after | W2-D (awal), C3-D (matriks penuh) | `evidence/benchmark/matrix.csv` |
| T-16 | Load balancing dua replica | C3-A | `evidence/tests/T16.txt` |
| T-17 | Health removal tanpa 5xx | C3-A | `evidence/tests/T17.txt` |
| T-18 | Circuit breaker \+ recovery | C3-A | `evidence/tests/T18.txt` |
| DQ-01…DQ-08 | Matriks injeksi kualitas | C3-D | `evidence/dq/DQ-0*.json` |

---

## 8\. Ruang lingkup yang dipotong

Dipotong secara eksplisit agar tidak dianggap lupa. Sejak Siklus 3 ditambahkan, daftar ini menyusut drastis: semua komponen wajib `ARCHITECTURE.md` kini punya slot.

| Item | Alasan | Dampak yang diterima |
| :---- | :---- | :---- |
| Classifier sentimen terlatih (TF-IDF \+ Logistic Regression) | Ditandai `MAY` di ARCHITECTURE §11.10; VADER memenuhi F-11 | Sentimen kurang domain-specific; limitasi ditulis di model card dan laporan |
| Dex, oauth2-proxy | Ditandai opsional di ARCHITECTURE §5.3; Tailscale ACL \+ RBAC aplikasi sudah memenuhi F-16 | Tidak ada SSO; UI memakai basic auth |
| Distributed tracing | ARCHITECTURE §16.1 menyatakan out of scope fase 1 | Korelasi lewat `run_id` \+ `request_id` di log |
| HA, failover otomatis, multi-tenant, Spark/Trino/DataHub/Superset/Keycloak/Vault | Non-goal ARCHITECTURE §1.4 | Tidak diklaim, sesuai §19.8 |
| Paket F-20: laporan, PPT, video, contribution table | Tidak dijadwalkan di dokumen ini | Harus dikerjakan pada fase terpisah setelah 30 Nov |

Semua item lain — termasuk replica kedua, load balancing, circuit breaker, Feast online store, retraining otomatis, promotion otomatis, Loki, profil tiga/empat node, catalog lima view, governance workflow, compaction, snapshot expiry, retensi gold 90 hari, benchmark B1–B4, dan DQ-01…DQ-08 — **tidak lagi dipotong** dan wajib selesai pada Siklus 3\.

---

## 9\. Risiko lintas slot

| ID | Risiko | Slot terdampak | Trigger | Respons |
| :---- | :---- | :---- | :---- | :---- |
| G1 | Tailscale/Docker networking tidak jalan | W1-A, W2-C | Cross-node ping/port gagal | Fallback LAN statis, dokumentasikan; demo satu node |
| G2 | Binance DNS diblokir | W1-A, W1-B | Producer tidak connect | Mode replay \+ window terunduh |
| G3 | PyIceberg gagal commit partisi | W1-A, W1-B, W1-C | Commit error/tidak idempoten | Overwrite partisi penuh atau Parquet \+ manifest |
| G4 | Satu slot melewati CP2 | Semua | CP2 merah | Potong ke Must-only, gap ditulis, jangan geser deadline |
| G5 | Data sentimen sedikit | W1-C, W2-A | \< 300 baris | Laporkan H0, promosikan model market-only |
| G6 | Memori 16 GB habis di profil dev | W2-B, W2-D | OOM kill | Satu job berat pada satu waktu, turunkan limit |
| G7 | Secret bocor | W2-C, W2-D | gitleaks finding | Rotasi, hapus dari history, catat di laporan |
| G8 | Evidence tidak lengkap saat freeze | W2-D, C3-D | Link mati | `make evidence` \+ CI check, freeze hanya jika manifest lengkap |
| G9 | Siklus 3 dimulai dalam kondisi lelah setelah dua siklus | C3-A | CP1 meleset \> 4 jam | Turunkan item Should, jaga Must, jangan geser deadline |
| G10 | Benchmark dan evidence bertabrakan di slot terakhir | C3-D | CP2 selesai dengan \< 24 jam tersisa | Prioritaskan 42 test \+ evidence index; benchmark ditandai `partial` dengan alasan |
| G11 | Commit masuk setelah tag `v1.0-demo` | C3-D | Ada commit setelah tag | Tag ulang hanya bila evidence diperbarui; catat di compliance index |

---

## 10\. Ringkasan beban per orang

| Orang | Siklus 1 (36 jam window) | Siklus 2 (36 jam window) | Siklus 3 (36 jam window) |
| :---- | :---- | :---- | :---- |
| Anin | W1-D: serving, API 13+1, Streamlit v1, T-13/14/15/34 | W2-C: lineage, catalog, Traefik, ACL, RBAC, T-22/23/30/38 | C3-A: `api-2`, LB, circuit breaker, Trivy, port/TLS/rate-limit scan, T-16/17/18 |
| Lois | W1-B: topic, OHLC, watermark, dedup, DLQ, Prefect, T-04/05/06/07/08/24/28/29 | W2-D: backup/restore, fault injection, benchmark awal, coverage, clean clone, tag `w2-d-ok` | C3-D: DQ-01…08, sapuan T-01…T-42, benchmark B1–B4, 10 fault \+ RTO, tag `v1.0-demo`, rehearsal |
| Dhea | W1-A: repo, compose, storage, kontrak, dua sumber, bronze, ledger, T-01/02/26 | W2-A: snapshot, E1/E2, MLflow, gate, inference, drift, T-09/20/21/35/36 | C3-B: Feast online, paritas PIT join, retraining otomatis, promotion otomatis, drift report |
| Vio | W1-C: silver social, VADER, tiga mart, merge, GX, T-03/09/10/11/12/31/32/33 | W2-B: metrics, logs, Grafana, 16 rule, runbook, drill, T-37/39 | C3-C: profil 3/4 node, ACL final, Loki, catalog 5 view, governance, lifecycle, hosting docs |

Setiap orang memegang minimal satu komponen data (bronze, stream, gold, ML) dan satu komponen kepercayaan/operasi (API, observability, security, recovery) sehingga seluruh tim bisa menjelaskan jalur end-to-end saat demo (syarat F-20). Siklus 3 memakai kesinambungan area, jadi setiap orang menutup komponen yang ia mulai di siklus sebelumnya.