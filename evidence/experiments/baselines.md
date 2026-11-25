# W2-A Baselines

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
