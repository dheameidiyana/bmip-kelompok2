# Runbook: API RBAC and audit (W2-C)

## Roles

| Role | Can do | Typical key |
| --- | --- | --- |
| `viewer` | every read route, `/v1/predict` | dashboard, catalog, analyst |
| `operator` | viewer + `POST /v1/admin/backfill` (202) | data engineer |
| `admin` | operator + `POST /v1/admin/catalog/reload`, key rotation | platform admin |

The W1-D `BMIP_API_KEY` is accepted as `viewer` for backward compatibility.
New keys use `bmip_<key_id>_<secret>`; only the Argon2 hash is stored in
`ops.api_keys`.

## Seed or rotate

```powershell
python scripts/w2c_seed_keys.py            # creates missing keys, prints once
python scripts/w2c_seed_keys.py --rotate   # new secrets for all three roles
```

Keys are written to `.env` (`BMIP_VIEWER_KEY`, `BMIP_OPERATOR_KEY`,
`BMIP_ADMIN_KEY`). Never commit `.env`.

## Verify

```powershell
python scripts/w2c_scan.py --steps rbac
```

Expected statuses: `401, 200, 403, 202, 200`. The script writes
`evidence/security/rbac-matrix.md` and shows the audit rows.

## Audit table

```sql
SELECT ts, actor, role, action, status, request_id
FROM ops.audit_log
ORDER BY id DESC
LIMIT 20;
```

One row is written per `/v1` attempt, including unauthenticated (401) and
insufficient-role (403) attempts. A failed audit insert is logged but never
fails the request.

## Revoke a key

```sql
UPDATE ops.api_keys SET revoked_at = now() WHERE key_id = '<id>';
```

The next request with that key returns 401 and writes an audit row.

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| every new key returns 401 | API container lacks `BMIP_API_KEY_HASH_SALT` | rebuild/recreate API with the same salt as the seed script |
| viewer can call admin routes | role mapping wrong or `API_AUTH_REQUIRED=false` | check `/v1/auth/whoami`; keep auth required outside local tests |
| audit table empty | migration not applied, or `/v1` not matched | `python scripts/w2c_migrate.py`; check `ops.audit_log` |
