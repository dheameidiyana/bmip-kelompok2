#!/usr/bin/env python3
"""C3-A security evidence: Trivy, ports, rate limit, TLS/HSTS, audit export."""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import socket
import ssl
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
SEC = ROOT / "evidence" / "security"
CA = ROOT / "deploy" / "traefik" / "certs" / "bmip-ca.pem"
HOST_HEADER = {"Host": "api.bmip.local"}
load_dotenv(ROOT / ".env")

PORTS = [
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


def _write(name: str, text: str) -> Path:
    path = SEC / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _api_key() -> str:
    return os.getenv("BMIP_VIEWER_KEY") or os.getenv("BMIP_API_KEY", "")


def trivy() -> dict[str, Any]:
    binary = shutil.which("trivy") or str(ROOT / "tools" / "trivy.exe")
    lines = [_header("TRIVY", "trivy image --severity HIGH,CRITICAL --ignore-unfixed", "PASS")]
    if not Path(binary).exists():
        lines[0] = _header("TRIVY", "trivy image", "BLOCKED")
        lines.append("trivy is not installed; install it under tools/trivy.exe")
        _write("trivy.txt", "\n".join(lines) + "\n")
        return {"step": "trivy", "passed": False, "blocked": True}
    images = ["bmip/api:dev", "bmip/dashboard:dev"]
    findings: list[dict[str, Any]] = []
    for image in images:
        report = SEC / "trivy.json"
        completed = subprocess.run(
            [
                binary,
                "image",
                "--severity",
                "HIGH,CRITICAL",
                "--ignore-unfixed",
                "--no-progress",
                "--format",
                "json",
                "--output",
                str(report),
                image,
            ],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )
        lines.append(f"--- {image} (exit {completed.returncode}) ---")
        if not report.exists():
            lines.append(completed.stderr.strip()[-2000:])
            continue
        try:
            payload = json.loads(report.read_text(encoding="utf-8"))
        except ValueError:
            lines.append("trivy report was not valid JSON")
            continue
        for result in payload.get("Results") or []:
            for vuln in result.get("Vulnerabilities") or []:
                findings.append(
                    {
                        "image": image,
                        "id": vuln.get("VulnerabilityID"),
                        "package": vuln.get("PkgName"),
                        "severity": vuln.get("Severity"),
                        "installed": vuln.get("InstalledVersion"),
                        "fixed": vuln.get("FixedVersion"),
                        "title": vuln.get("Title"),
                    }
                )
        lines.append(f"findings so far: {len(findings)}")
    result_text = "PASS" if not findings else "FAIL"
    lines[0] = _header(
        "TRIVY", "trivy image --severity HIGH,CRITICAL --ignore-unfixed", result_text
    )
    for item in findings:
        lines.append(
            f"{item['severity']} {item['id']} {item['package']} "
            f"{item['installed']} -> {item['fixed']} ({item['image']})"
        )
    lines.append(f"HIGH/CRITICAL findings: {len(findings)}")
    _write("trivy.txt", "\n".join(lines) + "\n")
    _write("trivy-findings.json", json.dumps(findings, indent=2, sort_keys=True) + "\n")
    # Keep the last raw report for inspection; it is replaced on each run.
    return {"step": "trivy", "passed": not findings, "findings": len(findings)}


def _local_ips() -> list[str]:
    ips = {"127.0.0.1"}
    try:
        for item in socket.gethostbyname_ex(socket.gethostname())[2]:
            if item and not item.startswith("127."):
                ips.add(item)
    except OSError:
        pass
    try:
        completed = subprocess.run(
            ["tailscale", "ip", "-4"], text=True, capture_output=True, check=False, timeout=5
        )
        if completed.returncode == 0:
            for line in completed.stdout.splitlines():
                value = line.strip()
                if value and value not in ips:
                    ips.add(value)
    except (OSError, subprocess.SubprocessError):
        pass
    return sorted(ips)


def ports() -> dict[str, Any]:
    lines = [_header("PORT-SCAN", "python scripts/c3a_scan.py --ports", "PASS")]
    findings: list[str] = []
    for host in _local_ips():
        open_ports = []
        for port in PORTS:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.25)
                if sock.connect_ex((host, port)) == 0:
                    open_ports.append(port)
        lines.append(f"{host}: open {open_ports}")
        if host != "127.0.0.1":
            unexpected = [port for port in open_ports if port not in (80, 443)]
            if unexpected:
                findings.append(f"{host}: unexpected {unexpected}")
    lines.append("Expected outside loopback: only 80/443 (Traefik).")
    lines.append("Findings: none" if not findings else "Findings: " + "; ".join(findings))
    if findings:
        lines[0] = _header("PORT-SCAN", "python scripts/c3a_scan.py --ports", "FAIL")
    _write("c3a-port-scan.txt", "\n".join(lines) + "\n")
    return {"step": "ports", "passed": not findings, "findings": findings}


def rate_limit() -> dict[str, Any]:
    lines = [_header("RATE-LIMIT", "python scripts/c3a_scan.py --rate-limit", "PASS")]
    statuses: dict[int, int] = {}
    try:
        with httpx.Client(timeout=10) as client:

            def one(_: int) -> int:
                return client.get("http://127.0.0.1:8085/health/live").status_code

            with ThreadPoolExecutor(max_workers=40) as pool:
                for code in pool.map(one, range(600)):
                    statuses[code] = statuses.get(code, 0) + 1
    except Exception as exc:  # noqa: BLE001 - evidence must record the failure
        lines[0] = _header("RATE-LIMIT", "python scripts/c3a_scan.py --rate-limit", "BLOCKED")
        lines.append(f"{type(exc).__name__}: {exc}")
        _write("rate-limit.txt", "\n".join(lines) + "\n")
        return {"step": "rate-limit", "passed": False, "blocked": True}
    lines.append("status counts: " + json.dumps(statuses, sort_keys=True))
    passed = statuses.get(429, 0) > 0 and statuses.get(200, 0) > 0
    if not passed:
        lines[0] = _header("RATE-LIMIT", "python scripts/c3a_scan.py --rate-limit", "FAIL")
    _write("rate-limit.txt", "\n".join(lines) + "\n")
    return {"step": "rate-limit", "passed": passed, "statuses": statuses}


def tls() -> dict[str, Any]:
    lines = [_header("TLS-HSTS", "python scripts/c3a_scan.py --tls", "PASS")]
    passed = True
    try:
        context = ssl.create_default_context(cafile=str(CA))
        with socket.create_connection(("127.0.0.1", 443), timeout=5) as raw:
            with context.wrap_socket(raw, server_hostname="127.0.0.1") as tls_sock:
                cert = tls_sock.getpeercert()
                expires = datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z")
                lines.append(f"subject: {cert.get('subject')}")
                lines.append(f"issuer: {cert.get('issuer')}")
                lines.append(f"notAfter: {expires.isoformat()}")
                lines.append(f"SAN: {cert.get('subjectAltName')}")
        redirect = httpx.get(
            "http://127.0.0.1", headers=HOST_HEADER, follow_redirects=False, timeout=10
        )
        lines.append(f"HTTP -> {redirect.status_code} Location={redirect.headers.get('location')}")
        response = httpx.get(
            "https://127.0.0.1/health/live", headers=HOST_HEADER, verify=str(CA), timeout=10
        )
        hsts = response.headers.get("strict-transport-security", "")
        lines.append(f"HTTPS health: {response.status_code}")
        lines.append(f"Strict-Transport-Security: {hsts}")
        passed = redirect.status_code == 301 and response.status_code == 200 and "max-age=" in hsts
    except Exception as exc:  # noqa: BLE001
        passed = False
        lines.append(f"{type(exc).__name__}: {exc}")
    if not passed:
        lines[0] = _header("TLS-HSTS", "python scripts/c3a_scan.py --tls", "FAIL")
    _write("tls-c3a.txt", "\n".join(lines) + "\n")
    return {"step": "tls", "passed": passed}


def audit() -> dict[str, Any]:
    from bmip.common.config import get_settings

    lines = [_header("AUDIT-EXPORT", "python scripts/c3a_scan.py --audit", "PASS")]
    rows: list[dict[str, Any]] = []
    try:
        with psycopg.connect(get_settings().postgres_dsn, connect_timeout=5) as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, ts, actor, role, action, status, request_id
                    FROM ops.audit_log
                    ORDER BY id DESC
                    LIMIT 100
                    """
                )
                columns = [item.name for item in cursor.description]
                rows = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
    except Exception as exc:  # noqa: BLE001
        lines[0] = _header("AUDIT-EXPORT", "python scripts/c3a_scan.py --audit", "FAIL")
        lines.append(f"{type(exc).__name__}: {exc}")
        _write("audit.txt", "\n".join(lines) + "\n")
        return {"step": "audit", "passed": False}
    path = SEC / "audit.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["id", "ts", "actor", "role", "action", "status", "request_id"]
        )
        writer.writeheader()
        writer.writerows(rows)
    lines.append(f"rows: {len(rows)}")
    lines.append(f"file: {path.relative_to(ROOT)}")
    _write("audit.txt", "\n".join(lines) + "\n")
    return {"step": "audit", "passed": bool(rows), "rows": len(rows)}


STEPS = {
    "trivy": trivy,
    "ports": ports,
    "rate-limit": rate_limit,
    "tls": tls,
    "audit": audit,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--steps", default="trivy,ports,rate-limit,tls,audit")
    args = parser.parse_args(argv)
    results = []
    for name in [part.strip() for part in args.steps.split(",") if part.strip()]:
        if name not in STEPS:
            raise SystemExit(f"unknown step: {name}")
        results.append(STEPS[name]())
    print(json.dumps(results, indent=2))
    return 0 if all(item.get("passed") for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
