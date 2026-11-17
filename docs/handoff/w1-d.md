# Handoff W1-D - Anin

- Owner: Anin
- Branch: `slot/w1-d-anin`
- Handoff to: Dhea (W2-A)
- Last update: 2026-11-16
- Base: `dev` (`ef01ec5`, W1-C merged)

## Status

- CP1: PASS
- CP2: PASS
- CP3: PASS
- Tag: `w1-d-ok`

Gate M1: one trade and one post are visible from bronze -> silver -> gold ->
serving -> API -> dashboard. Evidence: `evidence/e2e/M1_20261114T0405.txt`.

## Detail

The full handoff (status, architecture, decisions, operations, evidence, gaps)
lives in [`docs/w1-d.md`](../w1-d.md). That file replaces the separate runbook
and ADR drafts written earlier in the slot; `docs/adr/0003-w1-d-serving-and-api.md`
is kept as a superseded pointer.

## Yang belum jalan / stub

| Item | State | Owner |
| --- | --- | --- |
| Champion, MLflow registry, promotion gate | `serving.model_metrics` empty; `/v1/predict` answers `status="not_available"` | W2-A |
| Scoring rows | only the T-36 validation rows (`status="error"`) | W2-A |
| Full metrics | `/metrics` is the minimal version | W2-B |
| `api-2`, load balancing, circuit breaker | `compose.two-node.yml` still a stub | C3-A |

## Langkah berikutnya untuk Dhea (W2-A)

1. Register the champion in `serving.model_metrics` (`alias='champion'`) and set
   `app.state.predictor`.
2. Write scoring rows to `serving.predictions` with PK
   `(symbol, window_start, model_version)`; `status` stays `ok|error`.
3. `/v1/model/latest` becomes `available` automatically; the dashboard stops
   showing "belum ada model".
4. Keep the T-36 contract: malformed body -> 422, out-of-range feature -> 200
   `status="error"`, valid body without champion -> 200 `not_available`.

## Evidence

All files are linked from [`docs/w1-d.md`](../w1-d.md) section 8 and
`evidence/README.md` (W1-D block). Start with:

- `evidence/e2e/M1_20261114T0405.txt` - M1 gate, end to end
- `evidence/api/routes_20261114T0239.txt` - 14 canonical routes + 5 aliases
- `evidence/tests/T15.txt` - MinIO down -> 200 with `X-Data-Stale: true`
- `evidence/serving/loader-idempotence_20261114T0239.json` - two loads, same hash
