# Runbook: node profiles (C3-C)

The cluster is one compose base plus one overlay per node. Profiles select the
role; the overlay adds ports, limits, and cross-node host mappings.

## Files

| File | Role |
| --- | --- |
| `deploy/compose.base.yml` | every service, with `profiles: [n1]` … `[n4]` |
| `deploy/compose.node1.yml` | edge, ingestion, storage, query |
| `deploy/compose.node2.yml` | processing, orchestration, ML |
| `deploy/compose.node3.yml` | governance, UI, docs |
| `deploy/compose.node4.yml` | observability, security |
| `deploy/env/node1.env` … `node4.env` | non-secret addresses and ports |
| `deploy/traefik/services.yaml` | placement table and API replica list |

## Validate

```powershell
.\scripts\make.ps1 node1-config node2-config node3-config node4-config
.\scripts\make.ps1 three-node-config four-node-config
```

`c3c_nodes.py` also writes `evidence/deploy/compose-3node.yml` and
`compose-4node.yml` with `--no-interpolate`, so the evidence contains no secret
values.

## Start one node

```powershell
.\scripts\make.ps1 node1-up
.\scripts\make.ps1 node2-up
.\scripts\make.ps1 node3-up
.\scripts\make.ps1 node4-up
```

N1 includes a one-shot MinIO/Lakekeeper bootstrap. N3 needs the `governance`
and `docs` profiles; the Make target passes them. N4 starts Loki and Promtail
through the `loki` profile.

Tailscale tags: `tag:bmip-n1` … `tag:bmip-n4`; users are `tag:bmip-user`.

## Limits that must be said out loud

- The C3-C live check starts N1+N2 on **one laptop** with the same compose
  project. It proves the role split and the cross-node env wiring, not a real
  two-laptop network. The handoff records this.
- A four-node run also needs four Tailscale devices and four hostnames. Until
  that exists, four-node evidence is `docker compose config`.
- `deploy/env/node*.env` are committed because they contain no secrets. Real
  secrets stay in the root `.env`.
