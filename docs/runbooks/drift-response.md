# Drift response

1. Run `python scripts/c3b_drift.py` or wait for the `drift-report` deployment.
2. Inspect `evidence/ml/drift_<timestamp>.json` and
   `serving.drift_metrics`.
3. Treat PSI above 0.2 on any top-5 model feature as a trigger.
4. The flow launches `train-volatility`; the new model remains a challenger
   until it passes the promotion gate.
5. If the trigger fires repeatedly, check whether the offline materialization
   window is current and whether the feature source is still Feast.
6. Do not promote a model solely because drift fired; use the gate.
