# ADR-0003 — Serving tier and Query API for W1-D

- Status: Accepted
- Date: 2026-11-14
- Owner: Anin
- Supersedes: none
- Related: ARCHITECTURE §10, §15; workplan W1-D; ADR-0002

## Context

W1-D must turn three published gold marts into something a dashboard can read
in under a second, without letting the dashboard talk to the lakehouse, and
without inventing a model that W2-A has not trained yet. The query layer also
has to survive MinIO being unavailable during a demo, and it must not break the
gates earlier slots already proved (`e2e_smoke`, `quality`, `pytest`).

The two planning documents disagree on the endpoint list: the workplan defines
13 read-only routes plus a scoring route, while ARCHITECTURE §10.3 names a
different set of 13. They also disagree on two path spellings.

## Decision

1. **Canonical routes follow the workplan.** ARCHITECTURE names are kept as
   aliases (`/v1/market/ohlcv`, `/v1/market/volatility`,
   `/v1/sentiment/timeseries`, `/v1/dq/results`, `/v1/catalog/search`), so both
   documents resolve without a second implementation.
2. **Serving tables are the low-latency path; Iceberg stays the history.**
   `serving.market_hourly`, `serving.market_latest`, `serving.sentiment_hourly`,
   `serving.predictions`, `serving.freshness`, plus quality, catalogue, and
   model metadata. Writes are `INSERT ... ON CONFLICT ... DO UPDATE` from one
   loader, so a rerun cannot duplicate a row.
3. **`serving.volatility` is a view** over `serving.market_hourly`. The workplan
   calls it a table; a view keeps one write path and makes disagreement between
   two tables impossible. Column names are unchanged.
4. **Range queries read Iceberg through DuckDB, with PyIceberg as a second
   reader.** DuckDB is the primary engine (embedded, stateless). Because
   "DuckDB can attach the Lakekeeper catalog" is an assumption (ARCHITECTURE
   R04), a PyIceberg implementation of the same interface exists and is selected
   by `LAKE_READER=pyiceberg` or automatically when DuckDB cannot attach. An
   attach failure cools down for 30 seconds so a broken lake does not add five
   seconds to every request and healthcheck.
5. **Two different "stale" signals are kept separate.** `X-Data-Stale: true`
   means "this answer came from PostgreSQL because the lake path failed".
   `freshness.status` means "the data is older than its SLO". Mixing them would
   hide a storage outage behind a red badge or vice versa.
6. **Freshness is recomputed at request time** from `data_ts` and the stored
   SLO, so a badge does not freeze between hourly loads. `BMIP_AS_OF` switches
   to a replay clock that is echoed as `clock: "replay"`; nothing pretends the
   replay clock is wall time.
7. **Authentication is scoped to `/v1/*`.** `/api` and `/health/*` stay public
   because `scripts/e2e_smoke.py` (W1-A gate) and the container healthcheck call
   them. A single service key is compared in constant time; W2-C replaces it
   with a hashed key table and roles without touching the routers.
8. **No champion means `status: "not_available"`, not a fake prediction.**
   `POST /v1/predict` returns 200 with an explicit state while no model is
   registered, 422 for a malformed body, and records business out-of-range
   input as `status: "error"` in `serving.predictions`. W2-A only has to set
   `app.state.predictor` and insert a champion row.
9. **The API image is Debian slim.** PyIceberg pulls pyarrow, which publishes
   manylinux wheels but not musl ones; an alpine base fails at install time.
   DuckDB's `iceberg` and `httpfs` extensions are installed at build time so the
   container never needs egress to `extensions.duckdb.org`.

## Consequences

- The API is the only reader the dashboard uses, so authorisation, caching,
  fallback, and caps live in one place.
- A missing serving schema is an empty state (200, `data: null`, freshness
  `unknown`), not a 500: the first boot before the loader runs stays diagnosable.
- Two readers mean two code paths to test; the unit tests fake the reader
  interface, and the live evidence covers the DuckDB path.
- Aliases add five routes to OpenAPI. `tests/unit/test_api_app.py` asserts the
  committed `contracts/openapi.json` matches the app, so a route cannot be added
  without updating the contract.
- The two-node overlay still only stubs `api-2`; the real replica, load
  balancing, and circuit breaker remain C3-A scope.

## Revision 2026-11-14 - dashboard visual system

The dashboard owner revised the W1-D visual contract after the first
screenshot. This section overrides ARCHITECTURE S15.1 and workplan W1-D item
10; both were updated in the same commit.

- **Typography:** Poppins (400/500/600) from the Google Fonts CDN, with
  `Segoe UI` and the system sans stack as fallback. A fully offline demo loses
  the web font but keeps the layout; self-hosting the woff2 files was rejected
  for this slot to avoid shipping binary assets.
- **Palette:** light mode only, limited to black `#0A0A0A`, grey `#6B7280` /
  `#F5F6F8` / `#E5E7EB`, white `#FFFFFF`, navy `#0B1F3A` / `#163A66`, and pink
  `#E85D9E`. `.streamlit/config.toml` pins the Streamlit theme; charts are
  explicit Altair specs so the default blue/green never appears.
- **No emoji, no decorative chrome:** the page icon, status dots, the Deploy
  toolbar, and the Streamlit menu are removed.
- **Title:** "Bitcoin Market Intelligence Platform (BMIP)".
- **Layout:** metrics row, then price full width, then sentiment and volatility
  side by side. The range control is a dropdown; the custom range stays; the
  symbol input is removed because the symbol is a deployment setting.
- **Freshness:** per-metric badges and the per-chart source captions are gone.
  Freshness stays in `serving.freshness`, in every API response, and in the
  data-quality panel. `X-Data-Stale` is no longer surfaced in the UI, so the
  operator relies on Grafana (W2-B) and the API headers.

Consequences: the page reads as a business dashboard rather than an
operations console. The trade-off was accepted explicitly; it does not change
the API contract or any evidence other than the dashboard screenshot.
