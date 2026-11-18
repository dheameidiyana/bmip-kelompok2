# Volatility Model Card

## Intended use
One-hour realized-volatility prediction for five Binance spot USDT pairs.

## Data
- Dataset: `mart_ml@3627445140691597595`
- Snapshot SHA-256: `1b1434dfffa55afe5ec163a4a26dc4bff6383e0e9050e7c8561e3404936f6ede`
- Rows: 7190
- Symbols: BNBUSDT, BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT
- Range: 2026-09-18T02:00:00+00:00 to 2026-11-16T23:00:00+00:00
- Sentiment coverage: 0.07%
- Selection note: E2 did not add signal because sentiment coverage is 0.07%; the market-only E1 candidate is promoted per the H0 policy.

## Features
`ret_5m`, `ret_15m`, `ret_60m`, `rv_5m`, `rv_15m`, `rv_60m`, `volume_z_60m`, `trade_count_60m`, `hl_range_1m`, `vwap_dev`, `symbol_BTCUSDT`, `symbol_ETHUSDT`, `symbol_BNBUSDT`, `symbol_SOLUSDT`, `symbol_XRPUSDT`

## Split and label
Chronological 70/15/15 by event date, seed 42, no shuffle. Label is
`label_rv_next_1h`; features end before the label window.

## Metrics
- Validation MAE: 0.0001516332
- Validation RMSE: 0.0002468579
- Validation directional accuracy: 0.5972
- Test MAE: 0.0002262944
- Test RMSE: 0.0005561379
- Test directional accuracy: 0.6546
- Gate MAE improvement: 14.5002%
- Gate passed: True
- Gate comparison: persistence-baseline

## Feature importance

| Feature | Importance | Share |
|---|---:|---:|
| `rv_60m` | 0.3560193777 | 35.6019% |
| `rv_5m` | 0.1276581138 | 12.7658% |
| `rv_15m` | 0.1187099740 | 11.8710% |
| `hl_range_1m` | 0.0834576935 | 8.3458% |
| `ret_15m` | 0.0395111926 | 3.9511% |
| `trade_count_60m` | 0.0374080725 | 3.7408% |
| `vwap_dev` | 0.0355481990 | 3.5548% |
| `symbol_XRPUSDT` | 0.0330517218 | 3.3052% |
| `ret_5m` | 0.0324903466 | 3.2490% |
| `symbol_BTCUSDT` | 0.0311221220 | 3.1122% |

<!-- BASELINES:START -->
## Baselines

EWMA uses `alpha=0.06` (`lambda=0.94`) and is shifted one hour so the prediction never sees the label window.

| Split | Baseline | Count | MAE | RMSE | R2 | Spearman |
|---|---|---:|---:|---:|---:|---:|
| validation | persistence | 1080 | 0.0001679992 | 0.0002813277 | 0.4522 | 0.8248 |
| validation | ewma | 1080 | 0.0002444712 | 0.0003449117 | 0.1766 | 0.5479 |
| test | persistence | 1080 | 0.0002627024 | 0.0007039477 | -0.1632 | 0.7752 |
| test | ewma | 1080 | 0.0003176081 | 0.0006279400 | 0.0744 | 0.5396 |

<!-- BASELINES:END -->

## Per-symbol test MAE
- BNBUSDT: 0.0001703546
- BTCUSDT: 0.0002293510
- ETHUSDT: 0.0002532706
- SOLUSDT: 0.0002339986
- XRPUSDT: 0.0002444971

## Out-of-scope use
- Do not use this model as financial advice, a trading signal, or a risk-management system.
- Do not apply it to symbols outside the five trained Binance spot USDT pairs.

## Limitations
- The model is pooled across five symbols and is not a general market model.
- Sentiment features are market-wide, not symbol-specific.
- The historical backfill uses 1-minute klines, not raw trade ticks.
- Source lineage for kline-only hours falls back to `binance_ws`.

## Ethical note
This output is a volatility estimate, not financial advice. Do not use it
as an investment recommendation or as the sole basis for trading decisions.
