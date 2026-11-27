# Handoff C3-B - Dhea

- Owner: Dhea
- Branch: `slot/c3-b-dhea`
- Base: `c3-a-ok` (`c8e362b`)
- Status: PASS (CP1/CP2/CP3) - live accepted challenger deferred
- Date: 2026-11-25 (closed 2026-11-27)

## Status

- CP1: PASS - Feast repository applied, three feature views materialized, offline
  row count and feature hash match `mart_ml`, warm online read is below 50 ms.
- CP2: PASS - Feast online store feeds `/v1/predict` and batch inference; the
  running API exposes `bmip_feature_age_seconds`. Fresh run
  `evidence/ml/feature-age_20261126T230427Z.json` (`feature_source=feast`, 5
  symbols, age 3600 s < 7200 s) and batch request `batch-20261117T000000Z`
  persisted 5/5 `ok` rows in `serving.predictions`.
- CP3: PASS - `drift-report` detected real drift (PSI 1.45 on `rv_60m`,
  `drift_20261126T222406Z.json`, `trigger_required=true`) and automatically
  triggered `train-volatility`; `serving.drift_metrics` persists PSI/KS/rolling
  MAE; the retrain re-run completes and records the reject decision. The weekly
  retrain (`0 2 * * 0`) and daily drift (`30 3 * * *`) schedules are active.
  Live positive promotion is deferred - the current champion already wins, so
  the accept/archive path is proven by `promotion_20261125T143430Z.json` and
  T-21.
- E3: COMPLETE - pooled and per-symbol models trained on the same snapshot;
  pooled wins on test MAE and per-symbol inference differs by symbol.

## Penutupan 2026-11-27

- Drift trigger diuji live: `drift-report` (`lyrical-galago`) menghasilkan
  `trigger_required=true` (PSI `rv_60m` 1.45, `rv_15m` 1.32) dan otomatis
  memicu `train-volatility`.
- Bug `subprocess` `stdout=None` di `src/bmip/flows/ml.py` (task
  `train-volatility`) diperbaiki (null-safe + `stdout/stderr=PIPE`); retrain
  ulang `ancient-urchin` berakhir `Completed` dan `serving.model_decisions`
  mencatat challenger v8 `rejected` (champion v2 tetap).
- Batch inference jalur Feast lewat Prefect `infer-volatility` (`daffy-tanuki`)
  selesai; 5 simbol `ok`, feature age 3600 s.
- `bmip_feature_age_seconds` sudah tampil di `/metrics` API yang berjalan; tidak
  perlu rebuild image.
- Grafana `BMIP - Drift` ter-provision (`drift.json`); panel PSI, Rolling MAE,
  dan latest rows menampilkan data `serving.drift_metrics`.

## Yang sudah jalan

### Feast

- `feature_repo/` contains `symbol`, `market_features_1m` (TTL 1 jam),
  `sentiment_1h` (TTL 2 jam), and `market_hourly` (TTL 2 jam).
- `scripts/c3b_feast_build.py` writes offline Parquet from the frozen
  `mart_ml` snapshot and `serving.market_hourly`.
- `scripts/c3b_feast.py` creates the `feast` database when needed, applies the
  repo, materializes a full historical window, and probes the online store.
- `scripts/c3b_parity.py` compares the Feast point-in-time frame with the
  frozen snapshot.

### Inference

- `src/bmip/ml/features.py` provides `latest_features`: Feast online store when
  `FEATURE_SOURCE=feast`, otherwise the existing gold path.
- Predictor and batch use that reader.
- API exposes `bmip_feature_age_seconds` in `/metrics` after a scored request.

### Drift and promotion

- `serving.drift_metrics` added to `src/bmip/serving/schema.sql`.
- `scripts/c3b_drift.py` writes PSI, KS, rolling MAE 7d, and trigger status to
  PostgreSQL and evidence.
- `drift-report` deployment runs daily and can trigger `train-volatility`.
- `promotion_plan` archives the previous champion when a challenger is accepted.
- `scripts/c3b_promotion_check.py` proves the accept/archive and reject paths
  with a controlled gate fixture.

### Feast training

- `scripts/w2a_train.py --feature-source feast` rebuilds the training frame from
  `get_historical_features`; the normal `gold` path remains the default for
  compatibility.
- The Feast training run produced `train_20261125T123044Z.json` and refreshed
  the model card and E1/E2 table without changing the champion.

### E3 per-symbol

- `src/bmip/ml/per_symbol.py` and `scripts/c3b_per_symbol.py` train five
  market-only models without `symbol_*` features.
- Pooled test MAE: 0.0002262944; per-symbol test MAE: 0.0002402009.
- Per-symbol directional accuracy is slightly higher, but pooled wins on MAE
  and remains champion. This is a comparison-only result.

## Cara menjalankan

```powershell
make c3b-feast-build
make c3b-feast-apply
make c3b-parity
make c3b-feature-age
make c3b-drift
make c3b-per-symbol
make c3b-promotion
```

Feast scripts default to `127.0.0.1:5434`; the API container uses
`postgres-ml:5432`.

## Gap tersisa

- Live accepted challenger melalui MLflow: ditunda (defer). Champion saat ini
  sudah model E1 market-only; challenger live (v7, v8) ditolak gate 5% MAE.
  Jalur accept/archive tetap dibuktikan fixture
  `promotion_20261125T143430Z.json` dan T-21.
- Injeksi drift sintetis eksplisit (workplan no.5) belum dibuat sebagai skrip;
  trigger sudah dibuktikan dengan drift nyata pada snapshot lama
  (`snapshot 3627445140691597595`).
- Bukti penolakan prediksi saat feature age > 2 jam (`status=error`) belum
  berupa evidence runner terpisah; logika ada di `src/bmip/ml/batch.py`.

## Bukti

- `evidence/ml/feast-apply_20261125T143300Z.json`
- `evidence/ml/pit-parity_20261125T143348Z.json`
- `evidence/ml/feature-age_20261125T143446Z.json`
- `evidence/ml/drift_20261125T143419Z.json`
- `evidence/ml/promotion_20261125T143430Z.json`
- `evidence/ml/per-symbol_20261125T143428Z.json`
- `evidence/ml/inference-compare_20261125T143428Z.csv`
- `evidence/ml/inference-compare_20261125T143428Z.png`
- `evidence/experiments/E3_vs_pooled.md`
- `evidence/experiments/E1_vs_E2.md`
- `evidence/ml/feature-age_20261126T230427Z.json`
- `evidence/ml/drift_20261126T222406Z.json`
- `evidence/ml/train_20261126T223855Z.json`
- `evidence/ml/deployments-schedules_20261127T055745Z.png`
- `evidence/ml/retrain-schedule_20261127T060822Z.png`
- `evidence/ml/drift-trigger_20261127T061011Z.png`
- `evidence/ml/retrain-run_20261127T060926Z.png`
- `evidence/ml/drift-report-runs_20261127T060859Z.png`
- `evidence/dashboard/w3_drift.png`

