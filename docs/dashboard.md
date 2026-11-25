# Dashboard v2 - Multi-Asset Market Intelligence Platform

Dashboard hanya membaca Query API. Tidak ada akses langsung ke PostgreSQL atau
Iceberg dari Streamlit.

## Tabs

| Tab | Isi |
| --- | --- |
| Ringkasan | 4 metric, status freshness/quality/katalog/instance, performa 5 symbol |
| Market | harga ternormalisasi 5 symbol + detail symbol terpilih |
| Volatilitas | realized volatility 5 symbol + ringkasan per symbol |
| Korelasi | heatmap return/volatility, rolling 24 jam, lead-lag |
| Sentimen | bar sentimen per jam + scatter sentimen vs return BTC |
| Kualitas | status GX, failure, tabel freshness |
| Katalog | cari dataset, tabel metadata, detail satu dataset |
| Lineage | upstream/downstream dari `ops.lineage_edges` |

Judul utama tidak lagi memakai `(BMIP)`; nama produk tetap disebut di footer
API.

## Cara membaca korelasi

- Korelasi mengukur **pergerakan bersama**, bukan sebab-akibat.
- Basis `Return` memakai log return per jam; basis `Volatilitas` memakai
  `realized_vol_1h`.
- Heatmap hanya dihitung jika ada minimal 24 jam berpasangan.
- `n < 24` -> "data belum cukup"; `24 <= n < 48` -> label sample kecil.
- Rolling correlation memakai window 24 jam.
- Lead-lag positif berarti symbol pertama mendahului symbol kedua pada data
  historis, bukan bukti kausalitas.

## Data readiness

Korelasi 5 symbol membutuhkan bar yang beririsan. Jika `serving`/lake hanya
berisi satu symbol, jalankan backfill:

```powershell
.\.venv\Scripts\python.exe scripts\w2a_backfill.py `
  --start 2026-11-10 --end 2026-11-24 `
  --symbols BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT
make gold
make serving
```

Backfill menulis silver klines, lalu `make gold` membangun mart dan
`make serving` memuatnya ke PostgreSQL.

## Batasan

- Registry/champion ML masih kosong; panel prediksi menampilkan
  "belum ada model".
- Data historis membuat status freshness `stale`; ini bukan kegagalan health.
- Correlation window dibatasi `market_ohlc`/`volatility_range` (limit 500).
