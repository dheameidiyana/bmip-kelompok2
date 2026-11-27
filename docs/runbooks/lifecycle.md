# Runbook: Iceberg lifecycle (C3-C)

Job: `compact_iceberg` in `prefect.yaml`, daily 01:00 UTC, entrypoint
`src/bmip/flows/maintenance.py`. Manual run:

```powershell
.\.venv\Scripts\python.exe scripts\c3c_lifecycle.py
```

It compacts small partitions, expires snapshots older than 7 days, removes
orphan data files older than 24 hours, and reports retention. The fixture table
`test.retention_probe` proves the delete path; the production tables are
dry-run unless `--retention-apply bronze,silver,gold` is passed.

## Policy

| Layer | Retention | Action |
| --- | --- | --- |
| bronze | 14 days | delete partitions older than the cutoff, then expire snapshots |
| silver | 30 days | same |
| gold | 90 days | same; this explicitly replaces the older 30-day cut |
| snapshots | 7 days | `expire_snapshots` |
| orphans | 24 hours | S3 objects under `data/` not referenced by any manifest |

## PyIceberg 0.12 deviation

PyIceberg 0.12 exposes `expire_snapshots` but **not** `rewrite_data_files` or
`remove_orphan_files`. Compaction therefore reads a partition with PyArrow and
commits `table.overwrite(...)`, the same primitive the gold writer already uses.
Orphan removal lists `s3://<bucket>/<table>/data/` and compares it with
`table.inspect.all_files()`. This is recorded in `docs/handoff/c3-c.md`.

## Evidence

- `evidence/storage/compaction_<ts>.json`: per table, files/bytes/snapshots
  before and after, rewritten partitions, retention plan, fixture result.
- `evidence/storage/retention_<ts>.txt`: operator-readable table and fixture.

## Safety

- The scheduled deployment keeps `apply_retention: []` (dry-run) by default so
  it cannot delete demo history before C3-D closes the evidence. To enforce a
  layer, set that deployment parameter to e.g. `["bronze"]` after confirming the
  cutoff. Do not run retention before the close-out needs the data.
- Orphan removal only deletes objects older than 24 hours; keep the 24-hour
  guard even when running it manually.
