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

## Per-symbol test MAE
- BNBUSDT: 0.0001703546
- BTCUSDT: 0.0002293510
- ETHUSDT: 0.0002532706
- SOLUSDT: 0.0002339986
- XRPUSDT: 0.0002444971

## Limitations
- The model is pooled across five symbols and is not a general market model.
- Sentiment features are market-wide, not symbol-specific.
- The historical backfill uses 1-minute klines, not raw trade ticks.
- Source lineage for kline-only hours falls back to `binance_ws`.

## Ethical note
This output is a volatility estimate, not financial advice. Do not use it
as an investment recommendation or as the sole basis for trading decisions.
