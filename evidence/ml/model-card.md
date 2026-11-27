# Volatility Model Card

## Intended use
One-hour realized-volatility prediction for five Binance spot USDT pairs.

## Data
- Dataset: `mart_ml@2888713472648101633`
- Snapshot SHA-256: `54ebd4357f72b341af619cdd283a48ad1885030838f10f2d52f2400a796b52aa`
- Rows: 8150
- Symbols: BNBUSDT, BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT
- Range: 2026-09-18T02:00:00+00:00 to 2026-11-24T23:00:00+00:00
- Sentiment coverage: 0.06%
- Selection note: E2 did not add signal because sentiment coverage is 0.06%; the market-only E1 candidate is promoted per the H0 policy.

## Features
`ret_5m`, `ret_15m`, `ret_60m`, `rv_5m`, `rv_15m`, `rv_60m`, `volume_z_60m`, `trade_count_60m`, `hl_range_1m`, `vwap_dev`, `symbol_BTCUSDT`, `symbol_ETHUSDT`, `symbol_BNBUSDT`, `symbol_SOLUSDT`, `symbol_XRPUSDT`

## Split and label
Chronological 70/15/15 by event date, seed 42, no shuffle. Label is
`label_rv_next_1h`; features end before the label window.

## Metrics
- Validation MAE: 0.0001891627
- Validation RMSE: 0.0005040203
- Validation directional accuracy: 0.6342
- Test MAE: 0.0002409385
- Test RMSE: 0.0003908307
- Test directional accuracy: 0.6629
- Gate MAE improvement: -1.4780%
- Gate passed: False
- Gate comparison: champion

## Feature importance

| Feature | Importance | Share |
|---|---:|---:|
| `rv_60m` | 0.2425168753 | 24.2517% |
| `trade_count_60m` | 0.1550866961 | 15.5087% |
| `rv_15m` | 0.1245348230 | 12.4535% |
| `rv_5m` | 0.0867872462 | 8.6787% |
| `ret_5m` | 0.0751086250 | 7.5109% |
| `hl_range_1m` | 0.0745690018 | 7.4569% |
| `volume_z_60m` | 0.0626657903 | 6.2666% |
| `symbol_BTCUSDT` | 0.0440904386 | 4.4090% |
| `vwap_dev` | 0.0332145244 | 3.3215% |
| `ret_15m` | 0.0238677841 | 2.3868% |

<!-- BASELINES:START -->
## Baselines

EWMA uses `alpha=0.06` (`lambda=0.94`) and is shifted one hour so the prediction never sees the label window.

| Split | Baseline | Count | MAE | RMSE | R2 | Spearman |
|---|---|---:|---:|---:|---:|---:|
| validation | persistence | 1200 | 0.0002255579 | 0.0006588415 | -0.2417 | 0.7987 |
| validation | ewma | 1200 | 0.0002785915 | 0.0005786674 | 0.0421 | 0.5242 |
| test | persistence | 1320 | 0.0002623029 | 0.0004042621 | 0.3353 | 0.6986 |
| test | ewma | 1320 | 0.0003438923 | 0.0004790278 | 0.0666 | 0.3663 |

<!-- BASELINES:END -->

## Per-symbol test MAE
- BNBUSDT: 0.0001941253
- BTCUSDT: 0.0002273803
- ETHUSDT: 0.0002724993
- SOLUSDT: 0.0002572858
- XRPUSDT: 0.0002534019

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
