# Runbook: Tailscale ACL (W2-C)

The ACL is deny-by-default: only the ports in `deploy/tailscale/acl.json` are
allowed, and nothing is exposed to the public internet.

## Apply

1. Tag each device in the Tailscale admin console:
   - N1/N2 platform nodes: `tag:bmip-core`
   - N3/N4 UI and observability nodes: `tag:bmip-ui`
   - analyst, lecturer, guest laptops: `tag:bmip-user`
2. Open **Access controls**, paste `deploy/tailscale/acl.json`, save.
3. Confirm the tailnet device list has a `100.64.x.x` address for every node.

## Verify

```powershell
tailscale status
tailscale ping n1
Test-NetConnection 100.64.0.11 -Port 443
Test-NetConnection 100.64.0.11 -Port 5433   # must fail for tag:bmip-user
```

Record the JSON output:

```powershell
tailscale status --json > evidence/security/tailscale-status_<ts>.json
```

## What is allowed

| Source | Destination | Ports |
| --- | --- | --- |
| `tag:bmip-user` | `tag:bmip-core` / `tag:bmip-ui` | 443 |
| `tag:bmip-core` | `tag:bmip-core` | 443, 5433, 5435, 8000, 8181, 9000, 9090, 3000, 5002 |
| `tag:bmip-core` | `tag:bmip-ui` | 3000, 3002, 8501, 8502 |
| `tag:bmip-ui` | `tag:bmip-core` | 8000, 9000, 8181, 5433 |

Everything else is dropped.

## Fallback

If Tailscale is not logged in on the demo machine (risk G1 in the workplan):

- run the single-node demo with `BMIP_BIND_ADDRESS=127.0.0.1` and Traefik on
  `80`/`443`;
- keep the ACL file as the reviewed configuration;
- record `tailscale status` failure in `evidence/security/tailscale-acl.md` and
  state the limitation in the handoff. Do not claim a cross-node test that was
  not run.
