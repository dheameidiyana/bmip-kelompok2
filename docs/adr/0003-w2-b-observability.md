# ADR-003: Observability stack for W2-B

- Status: Accepted
- Date: 2026-11-19
- Owner: Vio (W2-B)
- Supersedes: none
- Related: ARCHITECTURE §13.3, §13.4; workplan W2-B; ADR-002

## Context

W1-C left a working pipeline with a quality gate, but nothing watched it. W2-B
has to answer three questions from one place: did the job run, is the stream
keeping up, and is a service or container unhealthy. The workplan fixes the
shape: Prometheus, Grafana, 16 rules in three classes, Telegram routing, three
runbooks, one drill, and a reconciliation against the API and SQL.

## Decisions

### 1. Pushgateway for batch jobs, scrape targets for long-running services

The API and the stream processor expose `/metrics` over HTTP. Gold, quality and
inference are short-lived processes: they exit before Prometheus could scrape
them, so they push their samples to the Pushgateway on the way out
(`bmip.observability.batch_run`).

Why: scraping an exited process is impossible, and inventing values in a
dashboard would break the "no made-up numbers" rule in the W2-B risk table.

### 2. Alertmanager routes to a small notifier, not directly to Telegram

`alertmanager.yml` has one receiver, a webhook at `notify:8080/alert`. That
service appends the payload to `evidence/alerts/alerts.jsonl`, sends one message
per alert to Telegram when a token exists, and records the delivery result in
`deliveries.jsonl`.

Why: the workplan lists "Telegram bot token is not available" as a risk. With
the notifier, the drill still produces a verifiable timeline on a machine
without a token, and the message format (severity, class, owner, `run_id`,
runbook link) lives in one place instead of being duplicated in YAML templates.

### 3. Two dashboards, two datasources

`pipeline` reads Prometheus; `business` reads PostgreSQL `serving.*`, which is
the same table the API falls back to and the same one the Grafana panel shows.

Why: business panels need hourly OHLC, sentiment, and predictions with correct
types. Querying Iceberg directly from Grafana would add a DuckDB plugin and a
second definition of "close price"; reading `serving.market_hourly` keeps one
source of truth and makes T-37 a real comparison instead of a tautology.

### 4. Anonymous viewer in dev, admin password from the environment

`GF_AUTH_ANONYMOUS_ENABLED=true` with the Viewer role, so a headless browser can
capture the dashboard for evidence and a teammate can open it without a login.
The admin password still comes from `GRAFANA_ADMIN_PASSWORD`.

Why: the screenshot has to be produced by a script, and a login form would need
a browser automation dependency. Viewer access is read-only; provisioning stays
admin-only.

### 5. The stream processor is scraped through the Docker host gateway

`host.docker.internal:9101` is a scrape target, not a compose service. The
processor is started on demand (`make stream`) because a replay is a deliberate
act, not a daemon.

Why: the W1-B evidence depends on running the processor with explicit flags
(group, idle timeout). Turning it into an always-on service would change that
contract. The cost is a target that is DOWN when nobody is replaying, which
`BmipStreamDown` reports as a warning instead of hiding.

### 6. Sixteen rules, three classes, `for:` between 1 and 10 minutes

- job failure (4): stale success, critical DQ failure, empty mart, failed
  predictions.
- stream lag/freshness (5): consumer lag, idle stream, silver freshness, gold
  freshness, silver bar age.
- service/resource (7): API down, stream down, any target down, API error rate,
  API latency, container CPU, container memory.

`for:` is 1 minute for the DQ rule (it blocks a publish), 2 minutes for lag and
API down (long enough to ignore a scrape blip, short enough for a drill), and
5–10 minutes for trend rules.

### 7. Log fields are a contract

`JsonFormatter` emits `timestamp`, `severity`, `service`, `logger`, `message`,
plus `run_id` when set and any `ctx_*` attribute as its bare name (so
`ctx_request_id` becomes `request_id`). The API sets `service="api"` and the
batch scripts use the job name.

Why: the workplan asks for those six fields, and the old format used `ts` and
`level`, which made a grep across services inconsistent.

### 8. T-37 tolerance is relative 1e-9 on `realized_vol_1h`

Three legs are compared for 24 hours and 7 days: the API response, the
`serving.market_hourly` row (the Grafana source), and `gold.mart_market` in
Iceberg. Every key present in the API must exist in serving; float differences
must be within `1e-9 * max(1, |a|, |b|)`.

Why: the three legs are copies of the same value, so any drift is a real bug,
not rounding. The relative form keeps the tolerance meaningful for values around
1e-3.

### 9. cAdvisor is best-effort on Docker Desktop

cAdvisor needs host mounts that are partial on Windows. The container is part of
the stack and its metrics feed the resource rules, but a failed mount is
documented as a limitation instead of being hidden by removing the target.

### 10. Observability services join the edge network in the dev profile

The `data` network is `internal: true`, and Docker does not publish ports for a
container that is only attached to an internal network. Prometheus, Grafana,
Alertmanager, Pushgateway, the exporters and the notifier therefore get `edge`
from `deploy/compose.dev.yml`, next to their `data` membership from the base
file. Without it the containers start and pass their healthchecks while
`localhost:9090` refuses every connection — a failure that looks like a broken
scrape config but is only a network attachment.

### 11. The host file IO is built explicitly

`table_with_host_io` constructs `FsspecFileIO` from our own properties instead
of `load_file_io`. Lakekeeper vends `s3.endpoint=http://minio:9000` and a REST
signer; from the host neither is reachable, and `load_file_io` can return that
cached instance, so every read fails with a connection reset. A fresh IO with
`localhost:9000` and remote signing disabled is the only reliable path outside
the compose network. Catalog calls are retried twice because Docker Desktop's
port proxy occasionally resets an idle keep-alive socket.

### 12. Batch metrics carry `run_id`, and the alert template forwards it

`batch_run` generates `run_id` (or takes `BMIP_RUN_ID`), attaches it to every
sample, and sets the same value for the JSON log. The four batch rules add
`run_id: "{{ $labels.run_id }}"` to their labels, so the notifier prints the run
that produced the failure instead of a dash.

Why: the workplan asks the Telegram message to carry `run_id`. A run id that
lives only in a log file cannot be quoted from a phone.

### 13. Dashboards print their URL and range inside the panel

Each dashboard starts with a text panel containing the dashboard URL, the range
start, and the scrape interval. Headless screenshots have no address bar and no
system clock, so the panel is the only way the image itself can prove which
dashboard and which window it shows.

Why: §3.2 asks a screenshot to show the URL and the time. A caption added
outside the image would be a hand-written claim; a panel is rendered by Grafana
from the same provisioning file the stack loads.

## Consequences

- A batch job that fails leaves a `status="failed"` sample and an old
  `bmip_last_success_timestamp_seconds`, which is exactly what the stale-job
  rule reads.
- The drill can run without Telegram, and with Telegram when a token is added to
  `.env`; no config change is needed.
- `make metrics-check` fails when fewer than four targets are up, so CP1 is a
  command, not an opinion.
- The business dashboard and the API share `serving.*`; a reconciliation
  failure means one of the loaders is wrong, not that the chart is stale.
