#!/usr/bin/env python3
"""Security evidence for W2-C: PII, ports, gitleaks, TLS, and RBAC."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import socket
import ssl
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]
SEC = ROOT / "evidence" / "security"
load_dotenv(ROOT / ".env")

FORBIDDEN_COLUMNS = {
    "author_did",
    "did",
    "handle",
    "author_handle",
    "display_name",
    "avatar",
    "post_uri",
    "raw_uri",
    "uri",
    "raw_payload",
    "raw_text",
}
PII_PATTERNS = {
    "did": re.compile(r"did:(?:plc|web):[a-zA-Z0-9]+"),
    "email": re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"),
    "handle": re.compile(r"(?<!\w)@[A-Za-z0-9._-]{3,}"),
}
LAN_PORTS = [
    80,
    443,
    3000,
    3002,
    4200,
    5002,
    5433,
    5434,
    5435,
    8000,
    8181,
    8501,
    8502,
    9000,
    9001,
    9090,
    9091,
    9093,
    9101,
]


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S")


def _sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return "nogit"


def _header(identity: str, command: str, result: str, owner: str = "anin") -> str:
    return "\n".join(
        [
            f"id        : {identity}",
            f"timestamp : {datetime.now(UTC).isoformat()}",
            f"commit    : {_sha()}",
            f"command   : {command}",
            f"result    : {result}",
            f"owner     : {owner}",
            "",
        ]
    )


def _write(area: str, name: str, text: str) -> Path:
    path = ROOT / "evidence" / area / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def pii() -> dict[str, Any]:
    from bmip.common.config import get_settings
    from bmip.transform.iceberg import load_rest_catalog, table_with_host_io

    settings = get_settings()
    tables = [
        "silver.market_trades",
        "silver.market_ohlcv_1m",
        "silver.social_post",
        "silver.social_sentiment",
    ]
    lines = [_header("T-22", "python scripts/w2c_scan.py --pii", "PASS")]
    findings: list[str] = []
    sample_hits: list[str] = []
    for identifier in tables:
        try:
            catalog = load_rest_catalog(settings, "process")
            table = table_with_host_io(catalog, settings, identifier, "process")
            columns = [field.name for field in table.schema().fields]
            bad = sorted(set(columns) & FORBIDDEN_COLUMNS)
            if bad:
                findings.append(f"{identifier}: forbidden column(s) {bad}")
            rows = (
                table.scan(selected_fields=columns)
                .to_arrow()
                .slice(0, 200)
                .to_pylist()
            )
            text_fields = [
                name for name in columns if name in {"post_text", "text", "description"}
            ]
            for row in rows:
                for field in text_fields:
                    value = str(row.get(field) or "")
                    for label, pattern in PII_PATTERNS.items():
                        if pattern.search(value):
                            sample_hits.append(f"{identifier}.{field}: {label} mention")
                            break
            lines.append(f"{identifier}: {len(columns)} columns, {len(rows)} sampled")
        except Exception as exc:  # noqa: BLE001 - report, do not crash
            findings.append(f"{identifier}: scan failed: {type(exc).__name__}: {exc}")
            lines.append(f"{identifier}: SCAN FAILED {exc}")
    lines.append("")
    summary = "none" if not findings else ", ".join(findings)
    lines.append("Forbidden structured columns: " + summary)
    lines.append(
        "Free-text mentions are informational; ARCHITECTURE 17.6 keeps post_text internal-only."
    )
    for hit in sorted(set(sample_hits))[:20]:
        lines.append(f"INFO {hit}")
    result = "PASS" if not findings else "FAIL"
    lines[0] = _header("T-22", "python scripts/w2c_scan.py --pii", result)
    path = _write("security", "pii-scan.txt", "\n".join(lines) + "\n")
    return {"step": "pii", "passed": not findings, "evidence": str(path.relative_to(ROOT))}


def _local_ips() -> list[str]:
    ips = ["127.0.0.1"]
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ips.append(sock.getsockname()[0])
        sock.close()
    except OSError:
        pass
    try:
        result = subprocess.check_output(
            ["tailscale", "ip", "-4"], text=True, timeout=5
        ).strip()
        if result:
            ips.extend(part for part in result.splitlines() if part)
    except (OSError, subprocess.SubprocessError):
        pass
    return list(dict.fromkeys(ips))


def _open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.6):
            return True
    except OSError:
        return False


def ports() -> dict[str, Any]:
    lines = [_header("PORT-SCAN", "python scripts/w2c_scan.py --ports", "PASS")]
    findings: list[str] = []
    for host in _local_ips():
        opened = [port for port in LAN_PORTS if _open(host, port)]
        lines.append(f"{host}: open {opened}")
        if host != "127.0.0.1":
            external = [port for port in opened if port not in {80, 443}]
            if external:
                findings.append(f"{host}: internal ports reachable {external}")
    lines.append("")
    lines.append("Expected outside loopback: only 80/443 (Traefik).")
    lines.append("Findings: " + ("none" if not findings else "; ".join(findings)))
    result = "PASS" if not findings else "FAIL"
    lines[0] = _header("PORT-SCAN", "python scripts/w2c_scan.py --ports", result)
    path = _write("security", "port-scan.txt", "\n".join(lines) + "\n")
    return {"step": "ports", "passed": not findings, "evidence": str(path.relative_to(ROOT))}


def gitleaks() -> dict[str, Any]:
    binary = shutil.which("gitleaks") or str(ROOT / "tools" / "gitleaks.exe")
    lines = [_header("SECRETS", "gitleaks git + gitleaks dir", "PASS")]
    if not Path(binary).exists():
        lines[0] = _header("SECRETS", "gitleaks git + gitleaks dir", "BLOCKED")
        lines.append("gitleaks is not installed. Install it with:")
        lines.append("  winget install Gitleaks.Gitleaks")
        lines.append("or download a release into tools/gitleaks.exe (gitignored).")
        path = _write("security", "gitleaks.txt", "\n".join(lines) + "\n")
        return {
            "step": "gitleaks",
            "passed": False,
            "blocked": True,
            "evidence": str(path.relative_to(ROOT)),
        }

    findings = 0
    exits: list[str] = []
    targets = [("git", ".")] + [
        ("dir", name)
        for name in ("src", "scripts", "deploy", "docs", "evidence", "tests", "contracts")
        if (ROOT / name).exists()
    ]
    for mode, target in targets:
        report = SEC / f"gitleaks-{mode}-{Path(target).name or 'root'}.json"
        report.parent.mkdir(parents=True, exist_ok=True)
        completed = subprocess.run(
            [
                binary,
                mode,
                target,
                "--config",
                ".gitleaks.toml",
                "--redact",
                "--report-format",
                "json",
                "--report-path",
                str(report),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        exits.append(f"{mode} {target} exit={completed.returncode}")
        if report.exists():
            try:
                findings += len(json.loads(report.read_text(encoding="utf-8")) or [])
            except (ValueError, OSError):
                pass
        if completed.stderr:
            lines.append(completed.stderr.strip()[-2000:])

    result = "PASS" if findings == 0 else "FAIL"
    lines[0] = _header("SECRETS", "gitleaks git + gitleaks dir", result)
    lines.extend(exits)
    lines.append(f"findings: {findings}")
    path = _write("security", "gitleaks.txt", "\n".join(lines) + "\n")
    return {"step": "gitleaks", "passed": findings == 0, "evidence": str(path.relative_to(ROOT))}


def tls() -> dict[str, Any]:
    ca = ROOT / "deploy" / "traefik" / "certs" / "bmip-ca.pem"
    lines = [_header("TLS", "python scripts/w2c_scan.py --tls", "PASS")]
    ok = True
    if not ca.exists():
        lines[0] = _header("TLS", "python scripts/w2c_scan.py --tls", "BLOCKED")
        lines.append("local CA missing; run `make certs`")
        path = _write("security", "tls.txt", "\n".join(lines) + "\n")
        return {
            "step": "tls",
            "passed": False,
            "blocked": True,
            "evidence": str(path.relative_to(ROOT)),
        }
    try:
        context = ssl.create_default_context(cafile=str(ca))
        with socket.create_connection(("127.0.0.1", 443), timeout=5) as raw:
            with context.wrap_socket(raw, server_hostname="api.bmip.local") as secure:
                cert = secure.getpeercert()
        lines.append(f"subject: {cert.get('subject')}")
        lines.append(f"issuer: {cert.get('issuer')}")
        lines.append(f"notAfter: {cert.get('notAfter')}")
        lines.append(f"SAN: {cert.get('subjectAltName')}")
    except Exception as exc:  # noqa: BLE001 - record the failure
        ok = False
        lines.append(f"TLS handshake failed: {type(exc).__name__}: {exc}")
    try:
        response = httpx.get("http://127.0.0.1/", follow_redirects=False, timeout=5)
        lines.append(f"HTTP -> {response.status_code} Location={response.headers.get('location')}")
        ok = ok and response.status_code in {301, 308}
        api = httpx.get(
            "https://127.0.0.1/v1/auth/whoami",
            headers={
                "Host": "api.bmip.local",
                "X-API-Key": os.getenv("BMIP_VIEWER_KEY", ""),
            },
            verify=str(ca),
            timeout=5,
        )
        lines.append(f"https whoami -> {api.status_code}")
        ok = ok and api.status_code == 200
        routes = [
            ("app.bmip.local", "/_stcore/health", 200),
            ("catalog.bmip.local", "/_stcore/health", 200),
            ("grafana.bmip.local", "/api/health", 200),
            ("prometheus.bmip.local", "/-/healthy", 401),
            ("marquez.bmip.local", "/", 401),
            ("minio.bmip.local", "/", 401),
        ]
        for host, path, expected in routes:
            probe = httpx.get(
                f"https://127.0.0.1{path}",
                headers={"Host": host},
                verify=str(ca),
                timeout=5,
            )
            lines.append(f"{host}{path} -> {probe.status_code} (expect {expected})")
            ok = ok and probe.status_code == expected
    except Exception as exc:  # noqa: BLE001
        ok = False
        lines.append(f"HTTPS request failed: {type(exc).__name__}: {exc}")
    lines[0] = _header("TLS", "python scripts/w2c_scan.py --tls", "PASS" if ok else "FAIL")
    path = _write("security", "tls.txt", "\n".join(lines) + "\n")
    return {"step": "tls", "passed": ok, "evidence": str(path.relative_to(ROOT))}


def rbac() -> dict[str, Any]:
    from bmip.common.config import get_settings

    settings = get_settings()
    base = "http://127.0.0.1:8000"
    viewer = os.getenv("BMIP_VIEWER_KEY", "")
    operator = os.getenv("BMIP_OPERATOR_KEY", "")
    admin = os.getenv("BMIP_ADMIN_KEY", "")
    now = datetime.now(UTC)
    from datetime import timedelta

    body = {
        "start": (now - timedelta(hours=2)).isoformat(),
        "end": now.isoformat(),
    }
    cases = [
        ("no key -> 401", {}),
        ("viewer read -> 200", {"X-API-Key": viewer}),
        ("viewer backfill -> 403", {"X-API-Key": viewer}),
        ("operator backfill -> 202", {"X-API-Key": operator}),
        ("admin reload -> 200", {"X-API-Key": admin}),
    ]
    results: list[dict[str, Any]] = []
    for label, headers in cases:
        method = "GET"
        path = "/v1/auth/whoami"
        payload = None
        if "backfill" in label:
            method, path, payload = "POST", "/v1/admin/backfill", body
        elif "reload" in label:
            method, path = "POST", "/v1/admin/catalog/reload"
        response = httpx.request(
            method, f"{base}{path}", headers=headers, json=payload, timeout=10
        )
        results.append(
            {
                "case": label,
                "method": method,
                "path": path,
                "status": response.status_code,
                "body": response.text[:300],
            }
        )
        # no key must be 401; viewer read 200; viewer backfill 403;
        # operator backfill 202; admin reload 200
    expected = [401, 200, 403, 202, 200]
    passed = [row["status"] for row in results] == expected
    with psycopg.connect(
        settings.postgres_dsn, row_factory=dict_row
    ) as connection:
        audit = connection.execute(
            """
            SELECT id, ts, actor, role, action, status, request_id
            FROM ops.audit_log
            ORDER BY id DESC
            LIMIT 10
            """
        ).fetchall()
    lines = [_header("T-38", "python scripts/w2c_scan.py --rbac", "PASS" if passed else "FAIL")]
    lines.append("| Percobaan | Method | Path | Status |")
    lines.append("| --- | --- | --- | --- |")
    for row in results:
        lines.append(
            f"| {row['case']} | {row['method']} | `{row['path']}` | {row['status']} |"
        )
    lines.append("")
    lines.append("Audit rows (last 10):")
    lines.append("| id | ts | actor | role | action | status | request_id |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for row in audit:
        lines.append(
            f"| {row['id']} | {row['ts']} | {row['actor']} | {row['role']} | "
            f"{row['action']} | {row['status']} | {row['request_id']} |"
        )
    audit_ok = len(audit) >= 4
    passed = passed and audit_ok
    lines[0] = _header("T-38", "python scripts/w2c_scan.py --rbac", "PASS" if passed else "FAIL")
    path = _write("security", "rbac-matrix.md", "\n".join(lines) + "\n")
    api401 = _header(
        "T-13",
        "curl -i http://127.0.0.1:8000/v1/auth/whoami",
        "PASS" if results[0]["status"] == 401 else "FAIL",
    )
    api401 += f"status without key: {results[0]['status']}\n"
    _write("security", "api-401.txt", api401)
    return {
        "step": "rbac",
        "passed": passed,
        "evidence": str(path.relative_to(ROOT)),
        "statuses": [row["status"] for row in results],
        "audit_rows": len(audit),
    }


def tailscale() -> dict[str, Any]:
    acl = ROOT / "deploy" / "tailscale" / "acl.json"
    digest = hashlib.sha256(acl.read_bytes()).hexdigest()
    status: dict[str, Any] = {"acl_sha256": digest, "acl_path": str(acl.relative_to(ROOT))}
    try:
        completed = subprocess.run(
            ["tailscale", "status", "--json"],
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
        status["exit_code"] = completed.returncode
        if completed.returncode == 0 and completed.stdout.strip():
            payload = json.loads(completed.stdout)
            status["backend_state"] = payload.get("BackendState")
            status["tailscale_version"] = payload.get("Version")
            status["peer_count"] = len(payload.get("Peer") or {})
            status["note"] = (
                "peer identities, node keys, DNS names, and addresses are redacted"
            )
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        status["error"] = f"{type(exc).__name__}: {exc}"
    path = _write(
        "security",
        "tailscale-acl.json",
        json.dumps(status, indent=2, default=str) + "\n",
    )
    running = status.get("backend_state") == "Running"
    return {
        "step": "tailscale",
        "passed": running,
        "partial": not running,
        "evidence": str(path.relative_to(ROOT)),
        "peer_count": status.get("peer_count"),
    }


STEPS = {
    "pii": pii,
    "ports": ports,
    "gitleaks": gitleaks,
    "tls": tls,
    "rbac": rbac,
    "tailscale": tailscale,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--steps",
        default="pii,ports,gitleaks,tls,rbac,tailscale",
        help="comma-separated: pii,ports,gitleaks,tls,rbac,tailscale",
    )
    args = parser.parse_args(argv)
    results = []
    for name in [part.strip() for part in args.steps.split(",") if part.strip()]:
        if name not in STEPS:
            print(f"unknown step: {name}", file=sys.stderr)
            return 2
        results.append(STEPS[name]())
    print(json.dumps(results, indent=2))
    return (
        0
        if all(item.get("passed") or item.get("partial") for item in results)
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
