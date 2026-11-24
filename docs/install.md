# Instalasi dan Troubleshooting - BMIP

| Field | Value |
| --- | --- |
| Status | Draft W2-D (T-25 versi awal) |
| Target | Windows 11 + Docker Desktop/WSL2, Python 3.11 |
| Terakhir diuji | 2026-11-24 pada laptop pengembang |
| Catatan | Clean clone final tetap dijadwalkan di C3-D |

Dokumen ini adalah jalur instalasi minimum dari repository kosong sampai stack
dev sehat. Perintah PowerShell memakai `.\scripts\make.ps1`; di Linux/macOS
ganti dengan `make`.

## 1. Prasyarat

- Windows 11 dengan WSL2 aktif dan Docker Desktop berjalan.
- Python 3.11 tersedia sebagai `python`.
- Git for Windows (menyediakan `sh.exe` untuk `scripts/make.ps1`).
- GNU Make: `winget install ezwinports.make`.
- RAM minimal 16 GB; 32 GB disarankan untuk menjalankan seluruh profil.
- Port host yang harus kosong: 80, 443, 8000, 8501, 8502, 9000, 9001, 19092,
  5000, 5433, 5434, 5435, 8181, 8080, 8088, 9090, 9093.

## 2. Clone dan setup

```powershell
git clone <repository-url> bmip
Set-Location bmip
.\scripts\make.ps1 setup
.\scripts\make.ps1 secrets
.\scripts\make.ps1 certs
.\scripts\make.ps1 users
```

`setup` membuat `.venv` dan menginstal paket editable
`.[dev,ml,dashboard]`. `secrets` membuat `.env` dari `.env.example` dengan
secret acak; perintah ini tidak merotasi `.env` yang sudah ada.

## 3. Nyalakan stack dev

```powershell
.\scripts\make.ps1 dev-up
.\scripts\make.ps1 doctor
```

`dev-up` menjalankan compose dasar + dev, menunggu health, bootstrap MinIO dan
Lakekeeper, lalu menulis evidence health. Jika ingin memakai MLflow di host,
gunakan override `deploy/compose.host-ml.yml` agar API tetap bisa menghubungi
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

## 6. Dashboard, catalog, dan observability

```powershell
.\scripts\make.ps1 dashboard-dev   # http://localhost:8501
.\scripts\make.ps1 catalog-dev     # http://localhost:8502
.\scripts\make.ps1 obs-up
.\scripts\make.ps1 metrics-check
```

Dashboard membaca API pada `BMIP_API_URL` dan memakai `X-API-Key` dari `.env`.
Jika dashboard kosong, cek API health terlebih dahulu, bukan langsung mengubah
query.

## 7. Test dan benchmark

```powershell
.\scripts\make.ps1 lint
.\scripts\make.ps1 test
.\scripts\make.ps1 test-cov        # coverage >= 40%, tulis evidence/tests/coverage.json
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
| DQ `missing-dataset` | Stack/lake belum hidup saat checkpoint | Nyalakan stack, tunggu health, ulangi `quality` |
| DQ `gold-market-lag` critical | Data historis sparse; event terakhir jauh dari sekarang | Bukan bug ACL; muat window baru atau tandai partial dengan alasan |
| Training `needs at least three event dates` | `gold.mart_ml` hanya punya dua tanggal berlabel | Tambah window gold berlabel; jangan sintesis data |
| `PermissionError Forbidden` dari service `process` | ACL Lakekeeper untuk service tersebut belum membaca dataset | Pakai service `ml` untuk DQ read-only atau perbaiki ACL Lakekeeper |
| Dashboard kosong | Registry kosong / prediction `not_available` / API key salah | Cek `/v1/predict`, registry MLflow, dan header `X-API-Key` |
| `No matching distribution found for botocore==...` | Mirror pip lokal belum menyediakan pin | Ulangi `pip install -e ".[dev,ml,dashboard]" --index-url https://pypi.org/simple` |
| `ModuleNotFoundError: mlflow` saat pytest | Setup lama hanya memasang `.[dev]` | Jalankan `pip install -e ".[dev,ml,dashboard]"` |
| Container exit 137 | Docker Desktop kehabisan memori atau mati | Tutup workload lain, restart Docker Desktop, jalankan `doctor` |
| `docker compose up` menghapus health API | Override host-ml tidak disertakan | Selalu tambahkan `-f deploy/compose.host-ml.yml` saat menyentuh API |

## 9. Batas versi awal

Dokumen ini belum menggantikan clean clone final. Bukti T-25 final harus
menyertakan log clone baru, instalasi, `doctor`, dashboard tidak kosong, dan
tidak ada langkah manual yang tidak tercatat di sini.
