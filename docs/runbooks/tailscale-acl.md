# Runbook: Tailscale ACL (C3-C final)

`deploy/tailscale/acl.json` is the final ACL. It is deny-by-default and
port-level least privilege: only the ports in the file are allowed.

## Tags

Tag each device in the Tailscale admin console:

| Tag | Device |
| --- | --- |
| `tag:bmip-n1` | edge, ingress, storage, API replica |
| `tag:bmip-n2` | processing, Prefect, MLflow, API replica |
| `tag:bmip-n3` | governance, UI, catalog, docs |
| `tag:bmip-n4` | Prometheus, Grafana, Loki, exporters |
| `tag:bmip-user` | analyst and lecturer laptops |

## Allowed matrix

| Source | Destination | Ports |
| --- | --- | --- |
| user | n1 | 443 |
| n1 | n2 | 8000, 4200, 5000, 5432 |
| n2 | n1 | 8000, 5432, 9000, 8181, 9092, 9101 |
| n1 | n3 | 5002, 8501, 8502, 3002, 8089 |
| n2 | n3 | 5002 |
| n3 | n1 | 8000 |
| n4 | n1 | 8000, 5432, 8080, 9000, 9101, 9644 |
| n4 | n2 | 8000, 5432, 8080 |
| n4 | n3 | 5432, 8080 |
| n1/n2/n3 | n4 | 3100, 9091 |

Everything else is denied.

## Validate offline

```powershell
.\scripts\make.ps1 c3c-acl
```

Writes `evidence/security/tailscale-acl_<ts>.json` with:

- `offline_validation: PASS` - JSON parser, known tags, required allows, and
  required denies (user cannot reach 5432/8000; N3 cannot reach storage ports);
- `live_test` - `not_run` with a reason when Tailscale is logged out, or
  `status_only` when the tailnet is up.

## Live test (C3-D)

The C3-C run had `tailscale status` = `NeedsLogin`, so the live cross-node
test is **not claimed**. Lois (C3-D) must run:

```powershell
tailscale status
tailscale ping n1
Test-NetConnection 100.64.0.11 -Port 443
Test-NetConnection 100.64.0.11 -Port 5432   # must fail from tag:bmip-user
tailscale status --json > evidence/security/tailscale-status_<ts>.json
```

Then update `docs/handoff/c3-c.md` or the compliance index with the result. Do
not mark F-17 fully PASS for the live ACL until this runs.
