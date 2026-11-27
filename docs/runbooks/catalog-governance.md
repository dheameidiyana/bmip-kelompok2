# Runbook: catalog governance (C3-C)

Registry: `ops.dataset_registry`. Serving copy: `serving.catalog_datasets`.
Every governance action writes one row to `ops.audit_log` with
`method='CLI'` and `path='governance:<action>'`.

## Roles

Governance actions require `admin`. The demo keys from
`scripts/w2c_seed_keys.py` are viewer/operator/admin; do not hardcode them in
the repository.

## Workflow

```powershell
# Register
.\.venv\Scripts\python.exe scripts\c3c_governance.py register --actor vio --role admin

# Change a metadata field
.\.venv\Scripts\python.exe scripts\c3c_governance.py change `
  --dataset serving.c3c_governance_probe --description "new description"

# Deprecate: status, removal_date, and a change note
.\.venv\Scripts\python.exe scripts\c3c_governance.py deprecate `
  --dataset serving.c3c_governance_probe --removal-date 2026-11-28

# Delete only after deprecation, with confirmation
.\.venv\Scripts\python.exe scripts\c3c_governance.py delete `
  --dataset serving.c3c_governance_probe --confirm
```

`make c3c-governance` runs the full probe register → change → deprecate →
delete, then the metadata consistency test. The probe is removed at the end, so
the production registry stays at 11 datasets.

## Metadata consistency test

```powershell
.\scripts\make.ps1 c3c-governance
```

It checks:

1. required fields: owner, description, classification, refresh_schedule;
2. retention matches the layer contract (bronze 14, silver 30, gold 90);
3. `serving.catalog_datasets` ids and fields match the registry;
4. the serving copy was refreshed after the registry row (two-minute tolerance);
5. no orphan ids in the serving copy.

Evidence: `evidence/catalog/metadata-test_<ts>.txt` and
`governance_<ts>.json`.

## Data dictionary

`make docs` writes `docs/data-dictionary.md` and the docs site. It reads the
registry plus live schemas; an offline run still produces the dataset list.

## Catalog views

`catalog-dev` (port 8502) exposes Search, Dataset detail, Lineage, Quality, and
Governance. Search uses `tsvector` + `pg_trgm`; lineage is read from the API
cache populated by the OpenLineage emitter.
