# BMIP - Bitcoin Market Intelligence Platform

Platform data end-to-end untuk menjawab satu pertanyaan:

> Apakah sentimen publik di Bluesky menambah nilai prediksi volatilitas
> jangka pendek pada lima Binance spot pair (BTC, ETH, BNB, SOL, XRP), di luar
> data market Binance?

Proyek kelompok TBP Advanced Data Platform Engineering. Arsitektur lengkap ada di
[ARCHITECTURE.md](ARCHITECTURE.md), pembagian kerja ada di [workplan.md](workplan.md).

Pipeline market memakai `MARKET_SYMBOLS` dengan default lima pair:
`BTCUSDT`, `ETHUSDT`, `BNBUSDT`, `SOLUSDT`, `XRPUSDT`. Nama produk tetap BMIP
karena Bitcoin adalah pair utama, tetapi ingestion, API, dan model dilatih untuk
lima pair tersebut.

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
waktu, panel kualitas). `POST /v1/predict` menjawab `status: not_available`
selama belum ada champion; training adalah W2-A. Status, keputusan, operasi,
dan bukti ada di [docs/w1-d.md](docs/w1-d.md).

W2-A selesai di branch `slot/w2-a-dhea` (base `slot/w1-d-anin`): ML loop dengan
snapshot `mart_ml`, split kronologis, baseline persistence/EWMA, E1/E2, MLflow
registry, batch inference, drift report, dan model card. Model dilatih pooled
untuk lima symbol dengan fitur one-hot symbol; detail ada di
[docs/handoff/w2-a.md](docs/handoff/w2-a.md).

W2-B selesai di branch `slot/w2-b-vio` (base `slot/w2-a-dhea`): Prometheus
dengan enam target, Pushgateway untuk job batch, sembilan metrik pipeline,
log JSON enam field, dua dashboard Grafana sebagai kode, 16 alert rule dalam
tiga kelas, routing Alertmanager → notifier → Telegram/berkas, tiga runbook,
drill T-39, dan rekonsiliasi T-37 untuk 24 jam dan 7 hari. Detail serah terima
ada di [docs/handoff/w2-b.md](docs/handoff/w2-b.md) dan keputusan teknisnya di
[docs/adr/0003-w2-b-observability.md](docs/adr/0003-w2-b-observability.md).

W2-C selesai di branch `slot/w2-c-anin` (base `w2-b-ok`): lineage OpenLineage
ke Marquez dari dbt, Prefect, dan stream processor; katalog 11 dataset di
`ops.dataset_registry` dengan portal Streamlit; Traefik TLS dan route per
hostname; ACL Tailscale deny-by-default; RBAC `viewer/operator/admin` dengan
audit log; serta scan gitleaks, PII, port, dan TLS. Detail ada di
[docs/handoff/w2-c.md](docs/handoff/w2-c.md) dan keputusan di
[docs/adr/0004-w2-c-lineage-catalog-security.md](docs/adr/0004-w2-c-lineage-catalog-security.md).

W2-D selesai di branch `slot/w2-d-lois` (base `w2-c-ok`): backup/restore T-19,
restart persistence T-40, fault injection stream dan MinIO, benchmark T-42,
coverage gate T-41 51,36%, evidence checker, `docs/install.md`, dan
`docs/spec-mapping.md`. T-25 clean clone sudah PASS dengan dua deviasi tercatat;
T-42 penuh tetap PARTIAL sampai C3-D. Detail ada di
[docs/w2-d-recap.md](docs/w2-d-recap.md) dan
[docs/handoff/w2-d.md](docs/handoff/w2-d.md).

C3-A berjalan di branch `slot/c3-a-anin`: `api-2` read-only, Traefik load
balancer `wrr`, circuit breaker, HSTS, retry/rate limit, Toxiproxy, Trivy,
port/TLS/429/audit evidence, tiga runbook, dan T-16/T-17/T-18. Detail ada di
[docs/handoff/c3-a.md](docs/handoff/c3-a.md).

Dashboard v2 memakai delapan tab: Ringkasan, Market, Volatilitas, Korelasi,
Sentimen, Kualitas, Katalog, dan Lineage. Tab Korelasi memakai return/volatilitas
lima symbol dan menampilkan jumlah jam sampel; tidak ada klaim kausalitas.

## Stack

- Sumber: Binance WebSocket lima pair (stream) + Bluesky AT Protocol (batch per jam)
- Broker: Redpanda
- Lakehouse: MinIO + Apache Iceberg + Lakekeeper
- Transformasi: Polars, DuckDB, dbt-duckdb
- Orkestrasi: Prefect 3
- Quality: Great Expectations
- Serving: FastAPI + PostgreSQL
- ML: scikit-learn/XGBoost, MLflow (Feast di C3-B)
- Observability: Prometheus, Grafana (Loki di C3-C)
- Deployment: Docker Compose (`dev`, `two-node`; `three-node`/`four-node` di C3-C)

## Struktur repo

```text
contracts/        JSON Schema kontrak data
deploy/           compose, env, policy MinIO, init PostgreSQL, Traefik
  observability/  Prometheus, Alertmanager, rule, provisioning Grafana
  notify/         penerima webhook Alertmanager -> Telegram/berkas
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
make governance-up && make governance   # Marquez, registry, dan API key RBAC
```

Port host dev:

| Service | Port |
| --- | --- |
| Traefik | 80/443 (TLS), 8080 (HTTP dev), 8082 (ping) |
| Query API | 8000 |
| Dashboard | 8501 |
| Catalog | 8502 |
| Marquez API / web | 5002 / 3002 |
| MinIO | 9000 (S3), 9001 (console) |
| Lakekeeper | 8181 |
| PostgreSQL core / governance | 5433 / 5435 |
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
.\scripts\make.ps1 governance-up # Marquez + postgres-gov (profil governance)
.\scripts\make.ps1 governance   # migrasi ops, seed registry, seed key RBAC
.\scripts\make.ps1 certs users  # CA lokal + users.htpasswd untuk Traefik
.\scripts\make.ps1 catalog-dev  # portal katalog di 8502
.\scripts\make.ps1 evidence-w2c # CP1/CP2 W2-C
.\scripts\make.ps1 scan-w2c     # PII, port, gitleaks, TLS, RBAC
.\scripts\make.ps1 evidence-check # verifikasi manifest dan link tanpa menulis manifest
.\scripts\make.ps1 c3a-roles   # role read-only bmip_api_ro
.\scripts\make.ps1 c3a-services # render daftar replica Traefik
.\scripts\make.ps1 c3a-up      # recreate api + api-2 + traefik
.\scripts\make.ps1 c3a-scan    # Trivy, port, 429, TLS/HSTS, audit
.\scripts\make.ps1 c3a-evidence # T-16/T-17 + health replica
.\scripts\make.ps1 c3a-circuit # T-18 circuit breaker
.\scripts\make.ps1 evidence     # health + manifest baru (butuh stack hidup)
.\scripts\make.ps1 ci           # compose config + lint + test
```

Harvester sosial per jam (Ctrl+C berhenti bersih):

```powershell
.venv\Scripts\python.exe -m bmip.ingestion.cli social --live --interval 3600
```

`make secrets` tidak menimpa `.env` yang sudah ada; ia hanya menambahkan key
baru dari `.env.example` (`--merge`) tanpa merotasi secret lama. Hapus `.env`
manual jika ingin merotasi seluruh secret lokal. Detail keputusan dan deviasi
ada di `docs/adr/0001-w1-a-foundation.md`, status serah terima ada di
`docs/handoff/w1-a.md`.

## Query API dan dashboard

API hanya membaca: `/v1/*` memerlukan `X-API-Key`, sedangkan `/api` dan
`/health/*` publik untuk healthcheck dan gate lama. Tiga role tersedia:
`viewer` (baca), `operator` (queue backfill), `admin` (reload katalog dan
rotasi key). Key lama `BMIP_API_KEY` tetap berlaku sebagai `viewer`; key baru
`BMIP_VIEWER_KEY`, `BMIP_OPERATOR_KEY`, dan `BMIP_ADMIN_KEY` dibuat oleh
`python scripts/w2c_seed_keys.py`.

Dashboard berjalan di `http://localhost:8501`, katalog di
`http://localhost:8502`, dan Marquez di `http://localhost:3002`. Dengan
`make certs users`, ketiganya juga tersedia sebagai
`https://app.bmip.local`, `https://catalog.bmip.local`, dan
`https://marquez.bmip.local` (lihat `docs/runbooks/traefik-tls.md`).

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
| `slot/w2-a-dhea` | Pekerjaan W2-A |
| `slot/w2-b-vio` | Pekerjaan W2-B |
| `slot/w2-c-anin` | Pekerjaan W2-C |
| `slot/w2-d-lois` | Pekerjaan W2-D |
| `slot/c3-a-anin` | Pekerjaan C3-A |
| `fix/w2-closeout` | Perbaikan evidence, gitleaks, dan dokumentasi 5 symbol |

Alur: branch slot -> PR ke `dev` (review minimal 1 orang) -> PR `dev` ke `main` saat
gate -> tag slot (contoh `w1-a-ok`).

## Aturan secret

- Jangan pernah commit `.env`, kredensial, token, atau sertifikat.
- Hanya `.env.example` yang boleh masuk repo, tanpa nilai rahasia.
- Jika sebuah secret telanjur ter-push, rotasi secret tersebut dan catat di handoff.

## Tim

Anin, Lois, Dhea, Vio.
