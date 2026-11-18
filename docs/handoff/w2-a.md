# Handoff W2-A - Dhea

- Owner: Dhea
- Branch: `slot/w2-a-dhea`
- Handoff to: W2-B (`slot/w2-b-*`)
- Last update: 2026-11-18
- Base: `dev` (`9972693`, W1-D merge)

## Status

- W2-A scope: IMPLEMENTED and verified; final commit/tag pending
- T-20 reproducibility: PASS
- T-21 bad challenger rejected: PASS (challenger v4 vs champion v2)
- T-35 E1 vs E2: PASS (E1 promoted under H0)
- T-36 final payload cases: PASS (`feature_ts` and freshness included)
- Persistence/EWMA baselines: PASS
- Drift report: generated; drift detected on seven features
- Registry tags and model-card artifact: PASS
- Tag `w2-a-ok`: still points at `eec3186`; do not move without approval

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
- Drift reference: validation holdout before the most recent seven days.
  PSI threshold is `0.2`; production points are never used as reference.
- Batch refuses features older than two hours. A stale batch exits non-zero
  and does not refresh the API cache.
- API exposes `feature_ts`, computes `meta.stale` from feature age, and writes
  the timestamp to `serving.predictions`.

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
| Training gate MAE improvement vs persistence | 14.50% |
| T-21 gate MAE improvement vs champion | -64.97% (rejected) |
| Champion | `volatility_model` version 2 |

MLflow experiment is `volatility`; the registered model is
`volatility_model`, with `champion` and `challenger` aliases. Artifacts use the
MinIO `artifacts` bucket. The local MLflow UI is `http://localhost:5000`.
The champion run carries `data_snapshot_id`, `feature_version`, `trigger`, and
`git_sha`, plus the model-card artifact under `model_card/`.

## Serving

- `/v1/predict` accepts `{"symbol": "..."}` or a feature payload.
- A valid symbol-only request returns `200 status="ok"` with model version 2,
  a `feature_ts`, and `X-Data-Stale` reflecting feature age.
- Malformed feature payload returns `422`; an out-of-range feature returns
  `200 status="error"`.
- The API uses the `champion` alias and reads a local latest-feature cache at
  `/app/data/ml/latest_features.json`. A missing or malformed cache disables
  the cache path instead of falling back to Lakekeeper from the container.
- Refresh the cache without scoring with
  `python scripts/w2a_cache.py`. Refresh it with scoring via
  `python scripts/w2a_batch.py`; stale inputs make that command exit `1`.
- Batch inference writes `feature_ts`, status, and champion metadata to
  `serving.predictions` using the field mappings in `docs/handoff/w1-d.md`.
- The current local snapshot ends at `2026-11-17T00:00Z`; T-36 therefore
  reports `stale=true` until a newer feature refresh is available. This is the
  intended fail-visible behaviour, not a fresh-data claim.

## Commands

```powershell
.\.venv\Scripts\python.exe scripts\w2a_backfill.py
.\.venv\Scripts\python.exe scripts\w2a_dataset.py
.\.venv\Scripts\python.exe scripts\w2a_train.py
.\.venv\Scripts\python.exe scripts\w2a_gate.py
.\.venv\Scripts\python.exe scripts\w2a_baselines.py
.\.venv\Scripts\python.exe scripts\w2a_drift.py
.\.venv\Scripts\python.exe scripts\w2a_batch.py
.\.venv\Scripts\python.exe scripts\w2a_cache.py
.\.venv\Scripts\python.exe scripts\w2a_registry_evidence.py
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
- `evidence/experiments/baselines.md`
- `evidence/experiments/baselines_20261118T092655Z.json`
- `evidence/experiments/mlflow_volatility_20261118T0719Z.png`
- `evidence/ml/model-card.md`
- `evidence/tests/T09.txt`
- `evidence/ml/T20.txt`
- `evidence/ml/T21.json`
- `evidence/ml/T36.json`
- `evidence/ml/predictions_20261118T093616Z.json`
- `evidence/ml/drift_20261118T092731Z.json`
- `evidence/ml/registry-metadata_20261118T110808Z.json`
- `evidence/tests/w2a_closeout_20261118Z.txt`
- `evidence/ml/archive/20261118T0930Z/`: pre-closeout T-21/T-36 copies

## Drift and limitations

The new drift report uses 235 reference rows
(`2026-11-08T00:00Z`-`2026-11-09T22:00Z`) and 845 production rows
(`2026-11-09T23:00Z`-`2026-11-16T23:00Z`). PSI flags `rv_60m`, `rv_15m`,
`rv_5m`, `hl_range_1m`, `trade_count_60m`, `ret_5m`, and `vwap_dev`. This is a
monitoring signal for W2-B, not an automatic promotion or demotion in W2-A.

Known limitations:

- Sentiment is market-wide and almost absent in the available history.
- Source lineage for kline-only history falls back to `binance_ws`.
- The feature cache is batch-refreshed, not streamed continuously.
- The demo dataset ends before the current wall clock; stale responses are
  expected and visible through `meta.stale` / `X-Data-Stale`.
- The W1-D no-champion T-36 case was a placeholder; W2-A replaces it with valid
  five-symbol payloads, malformed input, and an out-of-range feature while
  champion v2 is registered.
- The model is a volatility estimate, not financial advice or a trading signal.

## Deferred to W2-B or later

- Walk-forward validation and a scheduled retraining flow.
- Feast feature store and `gold.predictions`.
- KS test and prediction-distribution PSI; `serving.drift_metrics`.
- Automatic drift-triggered promotion/demotion.
- Hourly Prefect scheduling for batch inference and cache refresh.

## Next for W2-B

1. Add scheduled retraining and a drift-triggered retrain path.
2. Revisit sentiment coverage with a longer or higher-volume social history.
3. Keep the T-36 contract and the champion alias when adding challengers.
4. Capture the MLflow experiment screenshot/run tags required by the final
   presentation.
