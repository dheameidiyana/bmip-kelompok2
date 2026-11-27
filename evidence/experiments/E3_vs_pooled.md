# E3: Pooled vs Per-Symbol

| Scope | MAE | RMSE | Direction |
|---|---:|---:|---:|
| pooled | 0.0002262944 | 0.0005561379 | 0.6546 |
| per-symbol | 0.0002402009 | 0.0005777073 | 0.6593 |

## Per-symbol test MAE

| Symbol | Pooled | Per-symbol | Delta |
|---|---:|---:|---:|
| BNBUSDT | 0.0001703546 | 0.0001855750 | +0.0000152204 |
| BTCUSDT | 0.0002293510 | 0.0002514942 | +0.0000221432 |
| ETHUSDT | 0.0002532706 | 0.0002667448 | +0.0000134742 |
| SOLUSDT | 0.0002339986 | 0.0002467827 | +0.0000127840 |
| XRPUSDT | 0.0002444971 | 0.0002504075 | +0.0000059105 |

## Latest inference comparison

| Symbol | Pooled | Per-symbol | Difference |
|---|---:|---:|---:|
| BNBUSDT | 0.00039929800550453365 | 0.0003658804 | -3.341762931086123e-05 |
| BTCUSDT | 0.000491953978780657 | 0.0003494283 | -0.00014252564869821072 |
| ETHUSDT | 0.0005220577004365623 | 0.0005372958 | 1.5238067135214806e-05 |
| SOLUSDT | 0.000734648434445262 | 0.0006487353 | -8.591316873207688e-05 |
| XRPUSDT | 0.000670968962367624 | 0.0006586869 | -1.2282049283385277e-05 |

The per-symbol models use the same snapshot, chronological split, seed, and hyperparameters as the pooled model, but do not receive `symbol_*` one-hot features. The pooled model remains the champion; this is a comparison-only experiment.
