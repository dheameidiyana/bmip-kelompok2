# BMIP - Bitcoin Market Intelligence Platform

Platform data end-to-end untuk menjawab satu pertanyaan:

> Apakah sentimen publik di Bluesky menambah nilai prediksi volatilitas Bitcoin
> jangka pendek, di luar data market Binance?

Proyek kelompok TBP Advanced Data Platform Engineering. Arsitektur lengkap ada di
[ARCHITECTURE.md](ARCHITECTURE.md), pembagian kerja ada di [workplan.md](workplan.md).

## Status

W1-A selesai dan gate CP1-CP3 lulus: enam service dev berjalan, kontrak dan replay
ingestion menulis ke bronze, serta replay identik idempoten (`T-26`). Bronze social
menyimpan `event_date` dan `ingest_ts`; harvester Bluesky memakai retry/backoff dan
bisa berjalan per jam. `make e2e-smoke` memeriksa health, replay, bronze counts,
ledger, dan idempotensi dalam satu gate.

W1-B selesai di branch `feat/silver-lois`: stream processor OHLCV 1 menit dengan
watermark, dedup, DLQ, quarantine, dan freshness; `silver.market_trades` dan
`silver.market_ohlcv_1m` terisi; dbt silver dan Prefect schedule hijau. Branch itu
di-tag `w1-b-ok` pada `fdaf360` dan masuk ke `dev` lewat PR W1-C.

W1-C selesai di branch `slot/w1-c-vio` (base `feat/silver-lois`): silver social
dengan pseudonimisasi HMAC dan VADER, tiga gold mart (`mart_market`,
`mart_sentiment`, `mart_ml`) dengan partition overwrite per `event_date`, dan
checkpoint Great Expectations yang memblokir gold saat critical gagal serta
mencatat warning. `make lint`, `make test`, dan `make e2e-smoke` hijau, dan flow
Prefect `transform-gold` sudah dijalankan lewat worker. Detail serah terima ada
di [docs/handoff/w1-c.md](docs/handoff/w1-c.md).

W1-D selesai di branch `slot/w1-d-anin`: skema `serving.*` diisi idempoten dari
gold, Query API 13 endpoint read-only + 1 endpoint scoring, fallback
`X-Data-Stale` saat lake mati, dan dashboard Streamlit v1 (4 metrik, 2 filter
waktu, freshness badge). `POST /v1/predict` menjawab `status: not_available`
selama belum ada champion; training adalah W2-A. Detail di
[docs/handoff/w1-d.md](docs/handoff/w1-d.md) dan runbook
[docs/runbooks/serving.md](docs/runbooks/serving.md).

## Stack

- Sumber: Binance WebSocket (stream) + Bluesky AT Protocol (batch per jam)
- Broker: Redpanda
- Lakehouse: MinIO + Apache Iceberg + Lakekeeper
- Transformasi: Polars, DuckDB, dbt-duckdb
- Orkestrasi: Prefect 3
- Quality: Great Expectations
- Serving: FastAPI + PostgreSQL
- ML: scikit-learn/XGBoost, MLflow, Feast
- Observability: Prometheus, Grafana, Loki
- Deployment: Docker Compose (`dev`, `two-node`, `three-node`, `four-node`)

## Struktur repo

```text
contracts/        JSON Schema kontrak data
deploy/           compose, env, policy MinIO, init PostgreSQL, Traefik
dbt/              dbt project (silver + gold)
src/bmip/         kode aplikasi
  common/         config, logging, kontrak, ledger
  ingestion/      producer Binance, harvester Bluesky, adapter, bronze writer
  transform/      transformasi silver dan gold
  quality/        Great Expectations
  serving/        loader serving dan API
  ml/             fitur, training, inference, drift
tests/            unit, contract, integration
docs/             ADR, runbook, handoff
evidence/         bukti test, deploy, ingestion
scripts/          utilitas operasional
```

## Prasyarat

- Windows 11 + WSL2 + Docker Desktop (nyalakan sebelum menjalankan target)
- Python 3.11
- GNU Make (`winget install ezwinports.make`) dan Git untuk Windows
- Linux/macOS: `make`, `sh`, Docker Compose v2

Di Windows, jalankan target lewat `.\scripts\make.ps1` agar GNU Make memakai
`sh` dari Git for Windows. Di Linux/macOS, `make` bisa dipakai langsung.

## Quick start

```powershell
.\scripts\make.ps1 setup       # buat .venv dan install dependensi
.\scripts\make.ps1 secrets     # buat .env dengan secret acak (sekali)
.\scripts\make.ps1 dev-up      # nyalakan 6 service + bootstrap storage
.\scripts\make.ps1 doctor      # cek health dan tulis evidence CP1
```

Setara di Linux/macOS:

```bash
make setup && make secrets && make dev-up && make doctor
```

Port host dev:

| Service | Port |
| --- | --- |
| Traefik | 8080 (HTTP), 8082 (ping) |
| Query API | 8000 |
| Dashboard | 8501 |
| MinIO | 9000 (S3), 9001 (console) |
| Lakekeeper | 8181 |
| PostgreSQL core | 5433 |
| Redpanda | 19092 (Kafka), 9644 (admin) |

Perintah operasional:

```powershell
.\scripts\make.ps1 dev-down     # stop stack, data tetap
.\scripts\make.ps1 reset        # hapus volume lalu dev-up bersih
.\scripts\make.ps1 ingest-once  # replay market + social, refresh evidence CP2
.\scripts\make.ps1 evidence-cp3 # replay dua kali, cek idempotensi T-26
.\scripts\make.ps1 e2e-smoke    # health + replay + bronze + ledger W1-A
.\scripts\make.ps1 gold         # silver social + dbt + quality gate + publish gold
.\scripts\make.ps1 quality      # GX checkpoint, tulis evidence/dq/dq_report.json
.\scripts\make.ps1 evidence-w1c # T-03/T-09/T-10/T-11/T-12/T-31/T-32/T-33
.\scripts\make.ps1 serving      # load gold -> serving (idempoten)
.\scripts\make.ps1 evidence-api # CP1/CP2: smoke, routes, T-13, T-34, T-36
.\scripts\make.ps1 evidence-api-faults # T-14/T-15/T-37 + idempotensi (stop MinIO sebentar)
.\scripts\make.ps1 e2e-m1       # gate M1: bronze -> silver -> gold -> serving -> API -> dashboard
.\scripts\make.ps1 ci           # compose config + lint + test
```

Harvester sosial per jam (Ctrl+C berhenti bersih):

```powershell
.venv\Scripts\python.exe -m bmip.ingestion.cli social --live --interval 3600
```

`make secrets` tidak menimpa `.env` yang sudah ada. Hapus `.env` manual jika
ingin merotasi seluruh secret lokal. Detail keputusan dan deviasi ada di
`docs/adr/0001-w1-a-foundation.md`, status serah terima ada di
`docs/handoff/w1-a.md`.

## Query API dan dashboard

API hanya membaca: `/v1/*` memerlukan `X-API-Key` (nilai `BMIP_API_KEY` di
`.env`), sedangkan `/api` dan `/health/*` publik untuk healthcheck dan gate lama.
Dashboard berjalan di `http://localhost:8501` dan hanya memanggil API.

```powershell
$key = (Select-String -Path .env -Pattern '^BMIP_API_KEY=').Line.Split('=',2)[1]

curl.exe -s -H "X-API-Key: $key" "http://localhost:8000/v1/market/latest"
curl.exe -s -H "X-API-Key: $key" "http://localhost:8000/v1/freshness"
curl.exe -s -H "X-API-Key: $key" "http://localhost:8000/v1/market/ohlc?symbol=BTCUSDT&limit=5"
curl.exe -s -H "X-API-Key: $key" "http://localhost:8000/v1/quality/status"
curl.exe -s -H "X-API-Key: $key" "http://localhost:8000/v1/model/latest"
```

Respons memuat `meta.freshness` (`ok`/`warn`/`stale`/`unknown`) dan header
`X-Data-Source` (`lake`/`serving`) serta `X-Data-Stale` saat jalur lake gagal.
`BMIP_AS_OF` mengaktifkan jam replay yang selalu dilaporkan sebagai
`clock: replay`, bukan waktu dinding.

## Model branch

| Branch | Fungsi |
|---|---|
| `main` | Stabil, hanya menerima merge dari `dev` saat gate |
| `dev` | Integrasi harian |
| `slot/w1-a-dhea` | Pekerjaan W1-A |
| `slot/w1-b-lois` | Pekerjaan W1-B (aktual: `feat/silver-lois`) |
| `slot/w1-c-vio` | Pekerjaan W1-C |
| `slot/w1-d-anin` | Pekerjaan W1-D |

Alur: branch slot -> PR ke `dev` (review minimal 1 orang) -> PR `dev` ke `main` saat
gate -> tag slot (contoh `w1-a-ok`).

## Aturan secret

- Jangan pernah commit `.env`, kredensial, token, atau sertifikat.
- Hanya `.env.example` yang boleh masuk repo, tanpa nilai rahasia.
- Jika sebuah secret telanjur ter-push, rotasi secret tersebut dan catat di handoff.

## Tim

Anin, Lois, Dhea, Vio.
