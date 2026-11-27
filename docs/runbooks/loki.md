# Runbook: Loki and Promtail (C3-C)

Loki stores logs for 14 days (ARCHITECTURE 8.5). Promtail ships Docker
container logs and the host job logs written to `logs/*.jsonl`.

## Start

```powershell
docker compose --env-file .env -f deploy/compose.base.yml -f deploy/compose.dev.yml `
  --profile n1 --profile n2 --profile n3 --profile n4 --profile loki --profile promtail `
  up -d loki promtail
```

`make c3c-loki` does the same, runs the stream processor once with
`BMIP_LOG_FILE=logs/stream-processor.jsonl`, and writes
`evidence/logs/loki_<ts>.json` and `.txt`.

## Labels

- `service`: container name (for Docker logs) or the JSON `service` field (for
  host job files).
- `node`: `BMIP_NODE` from the node env file.
- `level`: JSON `severity`.
- `run_id` and `request_id` are **not** labels. Query them with a line filter.

```logql
{service="stream-processor"} |= "run_id"
{service="api"} |= "request_id"
{node="n1"} | json | level="ERROR"
```

## Check

```powershell
Invoke-WebRequest http://127.0.0.1:3100/ready
Invoke-RestMethod "http://127.0.0.1:3100/loki/api/v1/labels"
```

Grafana datasource `Loki` (uid `loki`) is provisioned in
`deploy/observability/grafana/provisioning/datasources/datasources.yml`.

## Known limits

- In the `dev` profile Loki is off unless the `loki` profile is requested.
- The stream processor normally runs on the host; Promtail tails
  `logs/stream-processor.jsonl` through the `/var/log/bmip` mount. A container
  that does not write JSON still gets its stdout via the Docker socket.
- Loki retention is enforced by the compactor; the first compaction can take
  one `compaction_interval` (10 minutes).
