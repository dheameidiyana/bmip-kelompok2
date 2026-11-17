# ADR-003: Serving tier, Query API, and dashboard v1

- Status: Superseded (content consolidated)
- Date: 2026-11-14
- Owner: Anin (W1-D)
- Supersedes: none
- Related: ARCHITECTURE S10, S15, S19; ADR-002

## Context

W1-D had to expose the three gold marts to the API and the dashboard without
letting either of them read PostgreSQL or Iceberg directly, and without
promising a prediction before a champion exists.

## Decision

The decisions and their rationale now live in one slot document,
[`docs/w1-d.md`](../../docs/w1-d.md) section 3: canonical routes follow the
workplan with the ARCHITECTURE names kept as aliases, `serving.volatility` is a
view over `serving.market_hourly`, DuckDB is the primary range reader with
PyIceberg as fallback, `/api` and `/health/*` stay unauthenticated, and
`POST /v1/predict` returns `not_available` until W2-A registers a champion.

This file stays in the repository as the numbered ADR record so the ADR series
remains contiguous; the authoritative text is the slot document above. W2-A
must keep the same route contract and the `serving.predictions` table.
