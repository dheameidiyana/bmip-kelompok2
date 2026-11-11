# BMIP - Bitcoin Market Intelligence Platform

Platform data end-to-end untuk menjawab satu pertanyaan:

> Apakah sentimen publik di Bluesky menambah nilai prediksi volatilitas Bitcoin
> jangka pendek, di luar data market Binance?

Proyek kelompok TBP Advanced Data Platform Engineering. Arsitektur lengkap ada di
[ARCHITECTURE.md](ARCHITECTURE.md), pembagian kerja ada di [workplan.md](workplan.md).

## Status

Tahap 0 (repo skeleton). Implementasi W1-A sedang berjalan; belum ada layanan yang
bisa dijalankan sampai compose dev tersedia.

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
src/bmip/         kode aplikasi
  common/         config, logging, validator kontrak
  ingest/         producer Binance, harvester Bluesky, adapter
  process/        stream processor dan penulis bronze/silver
tests/            unit, contract, integration
docs/             ADR, runbook, handoff
evidence/         bukti test, deploy, ingestion
scripts/          utilitas operasional
```

## Prasyarat

- Windows 11 + WSL2 + Docker Desktop (nyalakan sebelum menjalankan target)
- Python 3.11
- GNU Make, dijalankan dari Git Bash
- Git

## Quick start

Belum tersedia. Akan diisi pada Tahap 1 (CP1 W1-A) setelah compose dev dibuat.

## Model branch

| Branch | Fungsi |
|---|---|
| `main` | Stabil, hanya menerima merge dari `dev` saat gate |
| `dev` | Integrasi harian |
| `slot/w1-a-dhea` | Pekerjaan W1-A |
| `slot/w1-b-lois` | Pekerjaan W1-B |
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
