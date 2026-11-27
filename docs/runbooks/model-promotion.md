# Model promotion

The promotion gate compares a challenger with the current champion on the last
seven labelled test days.

- MAE must improve by at least 5%.
- RMSE must not worsen by more than 5%.
- Leakage and model-card checks must pass.

If the gate passes, the candidate receives the `champion` alias, the previous
champion receives `archived`, and `serving.model_decisions` records the
promotion. If the gate fails, the challenger remains registered but the champion
does not change.

Use `python scripts/c3b_promotion_check.py` to verify the decision logic without
changing MLflow. A real promotion must still be checked through MLflow aliases
and `serving.model_metrics`.
