# Instalasi dan Troubleshooting - BMIP

| Field | Value |
| --- | --- |
| Status | W2-D close-out; T-25 PASS dengan deviasi yang tercatat di `evidence/deploy/clean-clone.log` |
| Target | Windows 11 + Docker Desktop/WSL2, Python 3.11 |
| Terakhir diuji | 2026-11-25 pada laptop pengembang |
| Catatan | Clean clone final tetap diulang di C3-D setelah semua perubahan C3 |

Dokumen ini adalah jalur instalasi minimum dari repository kosong sampai stack
dev sehat. Perintah PowerShell memakai `.\scripts\make.ps1`; di Linux/macOS
ganti dengan `make`.

## 1. Prasyarat

- Windows 11 dengan WSL2 aktif dan Docker Desktop berjalan.
- Python 3.11 tersedia sebagai `py -3.11` (di mesin ini `python` menunjuk 3.14;
  venv proyek harus dibuat dengan 3.11).
- Git for Windows (menyediakan `sh.exe` untuk `scripts/make.ps1`).
- GNU Make: `winget install ezwinports.make`.
- RAM minimal 16 GB; 32 GB disarankan untuk menjalankan seluruh profil.
- Port host yang harus kosong: 80, 443, 8000, 8501, 8502, 9000, 9001, 19092,
  5000, 5433, 5434, 5435, 8181, 8080, 8088, 9090, 9093.

## 2. Clone dan setup

```powershell
git clone <repository-url> bmip
Set-Location bmip
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,ml,dashboard]" --index-url https://pypi.org/simple
.\scripts\make.ps1 secrets
.\scripts\make.ps1 certs
.\scripts\make.ps1 users
```

Jika `python` di mesin sudah 3.11, `.\scripts\make.ps1 setup` boleh dipakai.
`secrets` membuat `.env` dari `.env.example` dengan secret acak; perintah ini
tidak merotasi `.env` yang sudah ada.

## 3. Nyalakan stack dev

```powershell
.\scripts\make.ps1 dev-up
.\scripts\make.ps1 governance-up
.\scripts\make.ps1 governance
.\scripts\make.ps1 doctor
```

`dev-up` menjalankan compose dasar + dev, menunggu health, bootstrap MinIO dan
Lakekeeper, lalu menulis evidence health. `governance-up` menyalakan
`postgres-gov` + Marquez + Marquez web (profil `governance`), sedangkan
`governance` menjalankan migrasi `ops`, seed registry 11 dataset, dan seed API
key RBAC. Tanpa dua langkah itu, lineage UI, katalog database, dan key
viewer/operator/admin tidak tersedia.

Market memakai lima pair default:
`BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT`. Ubah `MARKET_SYMBOLS` di `.env`
sebelum `dev-up` jika ingin cakupan lain; `MARKET_SYMBOL` hanya default legacy.

Jika ingin memakai MLflow di host, gunakan override
`deploy/compose.host-ml.yml` agar API tetap bisa menghubungi
`host.docker.internal:5000`.

## 4. MLflow host (opsional tetapi diperlukan untuk inference)

MLflow 3.18 dijalankan di host, bukan container:

```powershell
$env:MLFLOW_S3_ENDPOINT_URL = "http://127.0.0.1:9000"
$env:AWS_ACCESS_KEY_ID = (Select-String .env '^BMIP_MINIO_ROOT_USER=').Line.Split('=',2)[1]
$env:AWS_SECRET_ACCESS_KEY = (Select-String .env '^BMIP_MINIO_ROOT_PASSWORD=').Line.Split('=',2)[1]
.venv\Scripts\mlflow.exe server --host 127.0.0.1 --port 5000 --workers 1 `
  --backend-store-uri "postgresql://prefect:<password>@127.0.0.1:5434/mlflow" `
  --serve-artifacts --artifacts-destination s3://artifacts/mlflow `
  --allowed-hosts localhost:5000,127.0.0.1:5000,host.docker.internal:5000
```

Ganti `<password>` dengan nilai `BMIP_PREFECT_DB_PASSWORD` dari `.env`. Cek
`http://127.0.0.1:5000/health` harus `200`.

## 5. Verifikasi minimum

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/health/ready
.\scripts\make.ps1 e2e-smoke
.\scripts\make.ps1 quality
.\scripts\make.ps1 serving
.\scripts\make.ps1 evidence-api
```

Hasil yang diharapkan:

- `/health/ready` mengembalikan `{"status":"ready","checks":{"lake":true,"serving":true}}`.
- `e2e-smoke` menulis bukti replay dan bronze counts.
- `quality` menulis `evidence/dq/dq_report.json`.
- `serving` mengisi `serving.market_hourly` dan `serving.sentiment_hourly`.
- `evidence-api` menulis smoke/routes dan T-34.
- API menerima kelima symbol default (`BTCUSDT`, `ETHUSDT`, `BNBUSDT`,
  `SOLUSDT`, `XRPUSDT`); symbol di luar allowlist mengembalikan `400`.

### 5.1 Seed data demo (agar dashboard tidak kosong)

Dashboard membaca `serving.*`, jadi data harus melewati bronze -> silver ->
gold. Untuk demo, gunakan window replay dua jam (window satu jam tidak lolos
aturan `gold-market-hourly-gap`):

```powershell
.\scripts\make.ps1 ingest-once
.\.venv\Scripts\python.exe scripts\make_replay_window.py `
  --day 2026-11-10 `
  --start 2026-11-10T13:00:00Z `
  --end 2026-11-10T15:00:00Z `
  --output data/replay/market_20261110T13-15.jsonl
.\.venv\Scripts\python.exe -m bmip.ingestion.cli market `
  --replay data/replay/market_20261110T13-15.jsonl --max-records 200000
.\scripts\make.ps1 stream-once
.\scripts\make.ps1 gold
.\scripts\make.ps1 serving
```

`make_replay_window.py` mengunduh hari Binance Vision dan memotong window;
file replay tetap gitignored. Tanpa langkah ini, stack sehat tetapi dashboard
akan kosong karena `serving.*` belum terisi.

## 6. Dashboard, catalog, dan observability

```powershell
.\scripts\make.ps1 dashboard-dev   # http://localhost:8501
.\scripts\make.ps1 catalog-dev     # http://localhost:8502
.\scripts\make.ps1 obs-up
.\scripts\make.ps1 metrics-check
```

Dashboard membaca API pada `BMIP_API_URL` dan memakai `X-API-Key` dari `.env`.
Jika dashboard kosong, cek API health terlebih dahulu, bukan langsung mengubah
query. Katalog harus menampilkan 11 dataset; Marquez harus hidup di
`http://localhost:3002` setelah `governance-up` dan `governance`.

Dashboard v2 punya delapan tab: Ringkasan, Market, Volatilitas, Korelasi,
Sentimen, Kualitas, Katalog, dan Lineage. Tab Korelasi membutuhkan minimal 24
jam berpasangan untuk menampilkan angka; jika kurang, UI menampilkan status
"data belum cukup" (bukan korelasi palsu).

## 6.1 Dua replica API dan security sweep (C3-A)

```powershell
.\scripts\make.ps1 c3a-roles
.\scripts\make.ps1 c3a-services
.\scripts\make.ps1 c3a-up
.\scripts\make.ps1 c3a-evidence
.\scripts\make.ps1 c3a-circuit
.\scripts\make.ps1 c3a-scan
```

`c3a-roles` membuat role `bmip_api_ro`; `c3a-services` merender daftar replica
Traefik; `c3a-up` menyalakan `api` + `api-2`. `c3a-evidence` menulis T-16/T-17,
`c3a-circuit` menulis T-18, dan `c3a-scan` menulis Trivy/port/429/TLS/audit.

Endpoint baca lewat load balancer, sedangkan `/v1/predict` dan `/v1/admin`
selalu diarahkan ke replica utama karena menulis ke database.

## 7. Test dan benchmark

```powershell
.\scripts\make.ps1 lint
.\scripts\make.ps1 test
.\scripts\make.ps1 test-cov        # coverage >= 40%, tulis evidence/tests/coverage.json
.\scripts\make.ps1 evidence-check  # manifest + link + tracked evidence
.\scripts\make.ps1 benchmark
.\scripts\make.ps1 backup
.\scripts\make.ps1 restore
```

Benchmark penuh memakai warm-up 120 detik dan tiga run 10 menit. Untuk sesi
terbatas, gunakan `--smoke`; jangan mencampur hasil smoke dengan matriks final.

## 8. Troubleshooting

| Gejala | Penyebab umum | Tindakan |
| --- | --- | --- |
| `host.docker.internal:5000` connection refused | MLflow host mati | Jalankan ulang MLflow host; cek `/health`; recreate API dengan override host-ml |
| API `/health/ready` 503 | Lake atau MLflow tidak siap | Cek `docker ps`, `curl http://127.0.0.1:5000/health`, lalu `doctor` |
| `Connect to ipv6#[::1]:19092 failed` | Redpanda advertise `localhost`, Windows resolve ke `::1` | Pastikan `broker.address.family=v4` pada producer/consumer; set `REDPANDA_BROKERS=127.0.0.1:19092` |
| `lakekeeper-migrate` gagal `password authentication failed` | Compose top-level `name: bmip` memakai volume lama dengan secret baru | Untuk clean clone di mesin yang sudah punya stack, set `COMPOSE_PROJECT_NAME=bmip-clean` (volume terpisah) atau hentikan stack lama; jangan pakai volume lama dengan `.env` baru |
| `psycopg` menggantung di `localhost` | resolve IPv6/Windows; connect tanpa timeout | Kode sekarang menambahkan `connect_timeout=5` ke `POSTGRES_CORE_DSN`; jika memanggil psycopg manual, tambahkan parameter yang sama |
| DQ `missing-dataset` | Stack/lake belum hidup saat checkpoint | Nyalakan stack, tunggu health, ulangi `quality` |
| DQ `gold-market-lag` critical | Data historis sparse; event terakhir jauh dari sekarang | Bukan bug ACL; muat window baru atau tandai partial dengan alasan |
| DQ `gold-market-hourly-gap` critical | Window replay kurang dari dua jam | Pakai window minimal dua jam seperti §5.1 |
| Training `needs at least three event dates` | `gold.mart_ml` hanya punya dua tanggal berlabel | Tambah window gold berlabel; jangan sintesis data |
| `PermissionError Forbidden` dari service `process` | ACL Lakekeeper untuk service tersebut belum membaca dataset | Pakai service `ml` untuk DQ read-only atau perbaiki ACL Lakekeeper |
| Dashboard kosong | Registry kosong / prediction `not_available` / API key salah | Cek `/v1/predict`, registry MLflow, dan header `X-API-Key` |
| `No matching distribution found for botocore==...` | Mirror pip lokal belum menyediakan pin | Ulangi `pip install -e ".[dev,ml,dashboard]" --index-url https://pypi.org/simple` |
| `ModuleNotFoundError: mlflow` saat pytest | Setup lama hanya memasang `.[dev]` | Jalankan `pip install -e ".[dev,ml,dashboard]"` |
| Container exit 137 | Docker Desktop kehabisan memori atau mati | Tutup workload lain, restart Docker Desktop, jalankan `doctor` |
| `docker compose up` menghapus health API | Override host-ml tidak disertakan | Selalu tambahkan `-f deploy/compose.host-ml.yml` saat menyentuh API |

## 9. Status T-25

T-25 close-out W2 dijalankan pada 2026-11-25 dari commit `b2eceb1`
(`evidence/deploy/clean-clone.log`). Hasil: PASS dengan dua deviasi yang
tercatat — isolasi `COMPOSE_PROJECT_NAME` dan seed window replay dua jam untuk
dashboard. C3-D tetap mengulang clean clone final setelah semua perubahan C3.

Batas yang masih berlaku:

- Registry/champion ML kosong sampai C3-B; panel prediksi menampilkan
  "belum ada model".
- Replay historis membuat status freshness `stale`; ini bukan kegagalan health.
- Hanya pair yang ada di window replay yang memiliki bar; API tetap menerima
  kelima symbol allowlist.
