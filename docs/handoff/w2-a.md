# Handoff W2-A - Dhea

- Owner: Dhea
- Branch: `slot/w2-a-dhea`
- Handoff to: W2-B (`slot/w2-b-*`)
- Last update: 2026-11-18
- Base: `dev` (`9972693`, W1-D merge)

## Status

- W2-A scope: IMPLEMENTED
- T-20 reproducibility: PASS
- T-21 bad challenger rejected: PASS
- T-35 E1 vs E2: PASS (E1 promoted under H0)
- T-36 final payload cases: PASS
- Drift report: generated; drift detected on volatility features
- Tag: pending until the final test pass

## Scope and decisions

- Five symbols: `BTCUSDT`, `ETHUSDT`, `BNBUSDT`, `SOLUSDT`, `XRPUSDT`.
- One pooled model with symbol one-hot features; no per-symbol models.
- Historical data is 1-minute Binance Vision klines for 60 days
  (2026-09-18 through 2026-11-16), not raw trade ticks. Backfill total is
  432,000 bars (86,400 per symbol).
- Label: `label_rv_next_1h`; chronological 70/15/15 split by event date,
  seed 42, no shuffle.
- E2 (sentiment) was tested but the sentiment coverage is only 0.07%. The H0
  policy promotes the market-only `e1_xgboost` model.

## Data and model

| Item | Value |
| --- | --- |
| Dataset | `mart_ml@3627445140691597595` |
| Snapshot SHA-256 | `1b1434dfffa55afe5ec163a4a26dc4bff6383e0e9050e7c8561e3404936f6ede` |
| Usable rows | 7,190 (1,438 per symbol) |
| Train / validation / test | 5,030 / 1,080 / 1,080 |
| Selected model | `e1_xgboost` |
| Test MAE | 0.0002262944 |
| Test directional accuracy | 0.6546 |
| Gate MAE improvement | 14.50% |
| Champion | `volatility_model` version 2 |

MLflow experiment is `volatility`; the registered model is
`volatility_model`, with `champion` and `challenger` aliases. Artifacts use the
MinIO `artifacts` bucket. The local MLflow UI is `http://localhost:5000`.

## Serving

- `/v1/predict` accepts `{"symbol": "..."}` or a feature payload.
- A valid symbol-only request returns `200 status="ok"` with model version 2.
- Malformed feature payload returns `422`; an out-of-range feature returns
  `200 status="error"`.
- The API uses the `champion` alias and reads a local latest-feature cache at
  `/app/data/ml/latest_features.json`. The cache is mounted read-only from the
  host `data/ml` directory, so the API does not have to reach Lakekeeper from
  the container.
- Regenerate the cache with `python scripts/w2a_batch.py`. The predictor loads
  the cache at startup, so restart the API after the cache changes.
- Batch inference writes five rows to `serving.predictions` with the champion
  model version and field mappings documented in `docs/handoff/w1-d.md`.

## Commands

```powershell
.\.venv\Scripts\python.exe scripts\w2a_backfill.py
.\.venv\Scripts\python.exe scripts\w2a_dataset.py
.\.venv\Scripts\python.exe scripts\w2a_train.py
.\.venv\Scripts\python.exe scripts\w2a_gate.py
.\.venv\Scripts\python.exe scripts\w2a_batch.py
.\.venv\Scripts\python.exe scripts\w2a_drift.py
.\.venv\Scripts\python.exe scripts\w2a_evidence.py
```

Use the Compose overlay for MLflow and the ML-enabled API:

```powershell
docker compose --env-file .env `
  -f deploy/compose.base.yml `
  -f deploy/compose.dev.yml `
  -f deploy/compose.ml.yml up -d --build api
```

`--env-file .env` is required; Compose otherwise does not read the local
multi-symbol settings and secrets.

## Evidence

- `evidence/ml/backfill_20261118T040656Z.json`
- `evidence/ml/dataset_20261118T044935Z.json`
- `evidence/ml/train_20261118T044935Z.json`
- `evidence/experiments/E1_vs_E2.md`
- `evidence/experiments/mlflow_volatility_20261118T0719Z.png`
- `evidence/ml/model-card.md`
- `evidence/tests/T09.txt`
- `evidence/ml/T20.txt`
- `evidence/ml/T21.json`
- `evidence/ml/T36.json`
- `evidence/ml/predictions_20261118T054850Z.json`
- `evidence/ml/drift_20261118T071754Z.json`

## Drift and limitations

The drift report compares the training split with the most recent seven labelled
days. `rv_60m`, `rv_15m`, `rv_5m`, and `hl_range_1m` exceed the PSI threshold
(0.25). This is a monitoring signal for W2-B, not an automatic promotion or
demotion in W2-A.

Known limitations:

- Sentiment is market-wide and almost absent in the available history.
- Source lineage for kline-only history falls back to `binance_ws`.
- The feature cache is batch-refreshed, not streamed continuously.
- The W1-D no-champion T-36 case was a placeholder; W2-A replaces it with valid
  five-symbol payloads, malformed input, and an out-of-range feature while
  champion v2 is registered.
- The model is a volatility estimate, not financial advice or a trading signal.

## Next for W2-B

1. Add scheduled retraining and a drift-triggered retrain path.
2. Revisit sentiment coverage with a longer or higher-volume social history.
3. Keep the T-36 contract and the champion alias when adding challengers.
4. Capture the MLflow experiment screenshot/run tags required by the final
   presentation.
