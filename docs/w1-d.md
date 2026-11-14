# W1-D - Serving layer, Query API, dan Dashboard v1

| Field | Value |
| --- | --- |
| Owner | Anin |
| Slot | W1-D, 15-16 November 2026 |
| Base | `dev` (`ef01ec5`) |
| Tag | `w1-d-ok` |
| Status | CP1 PASS, CP2 PASS, CP3 PASS |
| Menggantikan | `docs/handoff/w1-d.md`, `docs/adr/0003-w1-d-serving-and-api.md`, `docs/runbooks/serving.md` |

Dokumen ini adalah satu-satunya acuan W1-D: status, keputusan teknis, cara
operasi, bukti, dan serah terima ke W2-A.

## 1. Status dan gate

Gate M1: satu trade dan satu post terlihat dari bronze -> silver -> gold ->
serving -> API -> dashboard.

| Layer | Baris |
| --- | --- |
| `bronze.market_trade_raw` | 90.939 |
| `bronze.social_post_raw` | 2 |
| `silver.market_ohlcv_1m` | 61 |
| `silver.social_post` | 2 |
| `gold.mart_market` / `mart_sentiment` / `mart_ml` | 2 / 1 / 2 |
| `serving.market_hourly` / `sentiment_hourly` | 2 / 1 |
| `serving.catalog_datasets` | 11 |

Bukti gate: `evidence/e2e/M1_20261114T0405.txt`. Gate lama tetap hijau:
`pytest` (143), `ruff`, `make quality`, `e2e-smoke`, `compose config` dev dan
two-node.

## 2. Arsitektur

```
gold.mart_* --(PyIceberg, svc-api)--> serving.* --(psycopg)--> FastAPI --(HTTP)--> Streamlit
                                        ^                            |
                                        +-- lake read (DuckDB Iceberg) untuk query rentang
```

- API adalah satu-satunya jalur baca dashboard; Streamlit tidak menyentuh
  PostgreSQL atau Iceberg.
- Query rentang membaca Iceberg lewat DuckDB. Jika jalur lake gagal, API
  menjawab dari tabel serving dan menandai `X-Data-Stale: true`.
- Dua makna "stale" dipisah: `X-Data-Stale` = jalur degradasi;
  `freshness.status` = umur data terhadap SLO.

## 3. Keputusan teknis

1. **Route kanonik mengikuti workplan** (13 read-only + 1 scoring). Nama
   ARCHITECTURE dipertahankan sebagai alias: `/v1/market/ohlcv`,
   `/v1/market/volatility`, `/v1/sentiment/timeseries`, `/v1/dq/results`,
   `/v1/catalog/search`.
2. **Serving adalah jalur latensi rendah; Iceberg tetap histori.**
   `serving.market_hourly`, `market_latest`, `sentiment_hourly`,
   `predictions`, `freshness`, plus tabel kualitas, katalog, dan model.
3. **`serving.volatility` adalah view** di atas `market_hourly`; satu jalur
   tulis, kolom tetap sesuai workplan.
4. **DuckDB primary, PyIceberg fallback** untuk query rentang (`LAKE_READER`).
   Attach yang gagal di-cooldown 30 detik agar healthcheck tidak menunggu 5
   detik tiap panggilan.
5. **Auth `X-API-Key` hanya untuk `/v1/*`.** `/api` dan `/health/*` publik
   karena `scripts/e2e_smoke.py` dan healthcheck container memanggilnya.
6. **Tanpa champion berarti `status="not_available"`**, bukan prediksi
   rekaan. Body malformed -> 422; fitur out-of-range -> 200 `status="error"`
   dan baris tercatat di `serving.predictions`.
7. **Freshness dihitung ulang per request** dari `data_ts` + SLO.
   `BMIP_AS_OF` mengaktifkan jam replay yang selalu dilaporkan
   `clock="replay"`.
8. **Image API memakai `python:3.11-slim`** karena pyarrow tidak punya wheel
   musl; ekstensi DuckDB `iceberg`/`httpfs` di-bake saat build.
9. **Cache file eksternal DuckDB dimatikan** (`enable_external_file_cache`),
   jika tidak MinIO yang mati tetap terlihat sehat.

Revisi dashboard 14 November 2026 (keputusan owner):

- Poppins dari Google Fonts CDN, fallback `Segoe UI`.
- Light mode, palet hitam-abu-putih-navy-pink, tanpa emoji.
- Judul "Bitcoin Market Intelligence Platform (BMIP)".
- Layout: metrik, lalu harga satu baris penuh, lalu sentimen | volatilitas.
- Filter rentang berupa dropdown; input simbol dihapus (simbol = env).
- Badge freshness per metrik dan caption chart dihapus; freshness tampil di
  panel kualitas dan tetap ada di payload API.

## 4. Implementasi

**Serving** (`src/bmip/serving/`)

- `schema.sql`: DDL idempoten untuk seluruh tabel `serving.*`.
- `loader.py`: baca gold dengan kredensial `svc-api`, upsert per primary key,
  impor `evidence/dq/dq_report.json`, publikasikan `catalog/datasets.yml`
  (11 dataset dengan owner, klasifikasi, retensi, SLA, skema live), hitung
  freshness. Dua kali load menghasilkan hash logis identik.
- Terpasang di `scripts/build_gold.py` dan flow Prefect `transform-gold`
  (`publish-serving` setelah `publish-gold`).

**API** (`src/bmip/api/`)

- 14 route kanonik + 5 alias; `contracts/openapi.json` di-commit dan dijaga
  test anti-drift.
- Keyset pagination (`limit` + `cursor`), cap 31 hari / 1.000 baris, error
  RFC 7807 dengan `request_id`, `X-Request-ID` di setiap respons.
- `/metrics` minimal (request, latency, error, fallback); W2-B melanjutkan.

**Dashboard** (`src/bmip/dashboard/`)

- Streamlit v1: 4 metrik bisnis, 2 filter waktu, panel kualitas, hanya baca API.
- `theme.py` mengunci palet dan membuat spec Altair eksplisit sehingga warna
  default chart tidak muncul.
- Sidebar selalu terbuka saat load; tombol buka/tutup dipaksa terlihat.

**Environment**

- `deploy/api/Dockerfile`, `deploy/dashboard/Dockerfile` (slim, BuildKit cache
  mount), service `dashboard`, route Traefik `/v1` + `/`.
- `.env.example`, `deploy/env/ci.env.example`, `scripts/gen_env.py` memuat key
  baru; `BMIP_API_KEY` dibuat acak.

## 5. Data dan konteks

- Replay Binance Vision asli 2026-11-10 13:00-14:00 UTC (90.936 trade) plus
  fixture W1-A (3 trade, 14:00) dan dua post fixture 14:05/14:06.
- `silver.market_ohlcv_1m` berisi 60 bar jam 13 plus satu bar 14:00.
- `gold.mart_market` 2 baris jam 13:00 dan 14:00; `mart_sentiment` 1 baris;
  `mart_ml` 2 baris. `realized_vol_1h` jam 14:00 null karena hanya satu bar
  menit - aritmetika, bukan bug.
- Freshness di bukti berstatus `stale` karena data replay berumur empat hari.
  Pada demo live badge menjadi hijau; API tidak memalsukan umur data.
- `silver.market_trades` 86.371 dari 90.936 trade sementara semua menit jam 13
  punya bar; stream processor menahan dua menit terakhir sesuai watermark
  W1-B. Bukan isu W1-D.
- Satu record masuk quarantine (`late_beyond_window`) saat replay - jalur late
  event yang memang dirancang.

## 6. Operasi

| Gejala | Sebab | Tindakan |
| --- | --- | --- |
| `/v1/*` 401 | key hilang/salah | pakai `BMIP_API_KEY` dari `.env`; dashboard memakai key server-side |
| 503 `api-key-not-configured` | env kosong di container | isi `.env`, recreate container |
| `/health/ready` 503 | PostgreSQL dan lake sama-sama mati | cek `checks` di body, pulihkan Postgres atau MinIO/Lakekeeper |
| `X-Data-Stale: true` | jalur lake gagal | pulihkan MinIO; API kembali normal otomatis |
| `bmip_api_fallback_total` naik | MinIO/Lakekeeper mati atau attach DuckDB gagal | perbaiki storage; jika attach, set `LAKE_READER=pyiceberg` |
| Badge freshness merah | data lebih tua dari 2x SLO | jalankan ingestion atau terima status stale |
| "belum ada model" | champion belum terdaftar | W2-A; bukan kerusakan |
| Chart kosong | jendela waktu tidak berisi bar | pilih "Semua data" atau rentang di sekitar `data_ts` |
| Sidebar tertutup | state collapse tersimpan di browser | klik chevron kiri atas; hapus `stSidebarCollapsed-` di localStorage |
| Tabel serving kosong | loader belum jalan | `python scripts/serve_load.py` |

Perintah operasional:

```powershell
docker compose --env-file .env -f deploy/compose.base.yml -f deploy/compose.dev.yml ps
curl.exe -s http://localhost:8000/health/ready
curl.exe -s -H "X-API-Key: $env:BMIP_API_KEY" http://localhost:8000/v1/freshness
.\.venv\Scripts\python.exe scripts\serve_load.py --counts
docker compose --env-file .env -f deploy/compose.base.yml -f deploy/compose.dev.yml restart api
```

## 7. Cara menjalankan

```powershell
docker compose --env-file .env -f deploy/compose.base.yml -f deploy/compose.dev.yml up -d --build
.\.venv\Scripts\python.exe scripts\serve_load.py --counts

.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check src scripts tests deploy
.\.venv\Scripts\python.exe scripts\quality.py
.\.venv\Scripts\python.exe scripts\e2e_smoke.py
.\.venv\Scripts\python.exe scripts\m1_smoke.py

.\.venv\Scripts\python.exe scripts\api_evidence.py --steps smoke,routes,auth,invalid,predict,pagination,idempotence,reconcile
.\.venv\Scripts\python.exe scripts\api_evidence.py --steps pagination,stale --with-faults
```

Pipeline penuh (jalur yang sama dengan Prefect): `python scripts/build_gold.py`.

## 8. Bukti

| ID | File | Isi |
| --- | --- | --- |
| CP1 | `evidence/api/smoke_20261114T0239.txt` | health, 10 endpoint, baris market, freshness, request id |
| ROUTES | `evidence/api/routes_20261114T0239.txt` | 14 route kanonik, 5 alias, OpenAPI |
| T-13 | `evidence/security/api-401.txt` | tanpa key / key salah -> 401 problem+json |
| T-14 | `evidence/tests/T14.txt` | 2 halaman live dan 11 halaman atas 1.002 baris, 0 duplikat |
| T-15 | `evidence/tests/T15.txt` | MinIO stop -> 200 `X-Data-Stale: true`; pulih -> `false` |
| T-34 | `evidence/api/T34.json` | symbol, range, limit, cursor, datetime, missing range |
| T-36 | `evidence/ml/T36.json` | 422 malformed, error out-of-range, `not_available` |
| IDEM | `evidence/serving/loader-idempotence_20261114T0239.json` | dua load, counts + hash identik |
| T-37 | `evidence/dashboard/reconciliation-draft.json` | API vs serving vs gold, 0 selisih (draft) |
| M1 | `evidence/e2e/M1_20261114T0405.txt` | bronze -> silver -> gold -> serving -> API -> dashboard |
| DASH | `evidence/dashboards/streamlit_20261114T0405.png` | 4 metrik, 2 filter, Poppins, palet, sidebar |
| E2E | `evidence/e2e/SMOKE-W1A_20261114T0253_a58f5d7.txt` | gate W1-A tetap hijau |

## 9. Gap dan serah terima ke W2-A

| Item | Status | Owner |
| --- | --- | --- |
| Champion, MLflow registry, promotion gate | `serving.model_metrics` kosong; predict `not_available` | W2-A |
| Scoring rows | hanya baris validasi T-36 (`status=error`) | W2-A |
| `api-2`, load balancing, circuit breaker | `compose.two-node.yml` masih stub | C3-A |
| TLS, RBAC, Tailscale ACL | satu service key, belum ada TLS | W2-C |
| Metrik penuh | `/metrics` versi minimal | W2-B |

Langkah W2-A:

1. Daftarkan champion di `serving.model_metrics` (`alias='champion'`) dan set
   `app.state.predictor`.
2. Tulis hasil skor ke `serving.predictions` dengan PK
   `(symbol, window_start, model_version)`; `status` tetap `ok|error`.
3. `/v1/model/latest` otomatis `available`; dashboard berhenti menampilkan
   "belum ada model".
4. Pertahankan semantik T-36: malformed 422, out-of-range 200 `status=error`,
   valid tanpa champion 200 `not_available`.

## 10. Catatan kegagalan yang sudah diperbaiki

| Gejala | Sebab | Perbaikan |
| --- | --- | --- |
| API crash `missing POSTGRES_PASSWORD` | config mewajibkan password walau DSN sudah diberikan | DSN dipakai langsung |
| 500 `InFailedSqlTransaction` sebelum load pertama | satu statement gagal membatalkan transaksi | baca serving toleran skema kosong + autocommit |
| Range tetap terbaca saat MinIO mati | cache file eksternal DuckDB | cache dimatikan |
| `/health/ready` bilang lake sehat saat MinIO mati | health hanya `SELECT 1` | health membaca satu baris gold |
| Dashboard `No module named streamlit` | runtime install tanpa extra | `bmip[dashboard]` |
| Build gagal di pyarrow | base alpine tanpa wheel musl | `python:3.11-slim` |
| Lake gagal di host | metadata Iceberg memakai `minio:9000` | uji jalur lake dari container |
| Sidebar/filter tampak hilang | CSS menyembunyikan `stToolbar` yang memuat tombol expand | CSS hanya menyembunyikan tombol deploy + `initial_sidebar_state="expanded"` |
| Font ikon jadi teks | override `font-family` global | font Material ikon dipulihkan |

## 11. Referensi

- Arsitektur: `ARCHITECTURE.md` S10, S15, S19.
- Pembagian kerja: `workplan.md` W1-D.
- Kontrak API: `contracts/openapi.json`.
- Katalog dataset: `catalog/datasets.yml`.
