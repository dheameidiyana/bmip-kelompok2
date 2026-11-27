# Runbook: documentation hosting (C3-C)

```powershell
.\scripts\make.ps1 docs
```

`make docs` = `scripts/c3c_docs.py --serve --upload`:

1. builds `docs/data-dictionary.md` from the registry and live schemas;
2. runs `dbt docs generate` and copies the static site to `docs/_site/dbt/`;
3. renders `evidence/dq/dq_report.json` into `docs/_site/gx/` (static GX Data
   Docs; GX 1.x Data Docs needs a configured context, so the checkpoint remains
   the deterministic source);
4. uploads the tree to `s3://docs/` with the `svc-docs` credentials;
5. starts the `docs` service and checks `/`, `/gx/`, `/dbt/`.

## URLs

- `https://docs.bmip.local/` - index and dataset table
- `https://docs.bmip.local/dbt/` - dbt docs
- `https://docs.bmip.local/gx/` - GX Data Docs
- `http://127.0.0.1:8089/` - direct dev fallback

Traefik router `docs-host` is in `deploy/traefik/dynamic/api.yml`; the service
listens on 8089 so the same URL works inside one compose project and across
N1 → N3.

## Evidence

`evidence/deploy/docs-hosting_<ts>.json` contains the dataset count, dbt return
code, S3 keys, HTTP statuses, and an optional screenshot. A missing screenshot
means Playwright is not installed; the HTTP and S3 checks are the gate.
