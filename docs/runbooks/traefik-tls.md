# Runbook: Traefik TLS and host routing (W2-C)

## What this covers

Traefik terminates TLS for `*.bmip.local`, redirects HTTP to HTTPS, and routes
each service by hostname. The path-based router on `:8000` stays available for
scripts and tests.

## One-time setup

```powershell
make certs      # deploy/traefik/certs/bmip-ca.pem + bmip.pem
make users      # deploy/traefik/users.htpasswd from BMIP_UI_USERS
```

Add the hosts entries (Administrator PowerShell):

```powershell
$hosts = "C:\Windows\System32\drivers\etc\hosts"
@(
  "127.0.0.1 api.bmip.local app.bmip.local catalog.bmip.local",
  "127.0.0.1 grafana.bmip.local prometheus.bmip.local marquez.bmip.local",
  "127.0.0.1 minio.bmip.local prefect.bmip.local"
) | Add-Content $hosts
```

Trust the CA once per laptop:

```powershell
certutil -addstore -f Root deploy\traefik\certs\bmip-ca.pem
```

The certificates are gitignored. Re-run `make certs` with `--force` only when
the CA or hostnames change.

## Check

```powershell
curl.exe -I http://127.0.0.1/                         # 308 to https
curl.exe -I --cacert deploy/traefik/certs/bmip-ca.pem --resolve api.bmip.local:443:127.0.0.1 https://api.bmip.local/health/ready
```

- `api.bmip.local` has retry, rate limit, and security headers.
- `app.bmip.local` and `catalog.bmip.local` are open on the tailnet; the API key
  and RBAC protect the data.
- `prometheus.bmip.local`, `marquez.bmip.local`, and `minio.bmip.local` ask for
  the `BMIP_UI_USERS` credentials.

## Failure modes

| Symptom | Cause | Fix |
| --- | --- | --- |
| Traefik restarts with `no such file` | certs not generated | `make certs` |
| Browser warns about the certificate | CA not trusted | import `bmip-ca.pem` into Trusted Root |
| `404` from a hostname | hosts entry missing or router not loaded | check `docker logs bmip-traefik-1` |
| Basic auth loops | `users.htpasswd` missing or bad line | `make users`, restart Traefik |
| API returns 502 | API container unhealthy (MLflow retry) | wait for `/health/ready`; check API logs |

## HTTP-only fallback

Use `http://localhost:8000` for API calls and `http://localhost:8501` /
`http://localhost:8502` for the UIs. This keeps the W1-D/W2-B scripts working
without hosts entries or a trusted CA.
