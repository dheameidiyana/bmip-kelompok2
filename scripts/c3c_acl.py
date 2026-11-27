#!/usr/bin/env python3
"""Validate the final BMIP Tailscale ACL (C3-C).

The ACL is one of the few C3-C deliverables that cannot be exercised on a
single laptop without a logged-in tailnet. This script therefore separates two
facts and records both in the evidence file:

1. the ACL file is syntactically valid and contains the intended allow/deny
   matrix (``offline_validation: PASS``);
2. whether a live ``tailscale status`` was possible (``live_test``).

It never claims a live cross-node test when Tailscale is logged out.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ACL_PATH = ROOT / "deploy" / "tailscale" / "acl.json"
EVIDENCE = ROOT / "evidence" / "security"

TAGS = {"tag:bmip-n1", "tag:bmip-n2", "tag:bmip-n3", "tag:bmip-n4", "tag:bmip-user"}
DST_RE = re.compile(r"^(tag:bmip-n[1-4]|tag:bmip-user):([0-9,\-]+)$")

REQUIRED_ALLOW = [
    ("tag:bmip-user", "tag:bmip-n1", 443),
    ("tag:bmip-n1", "tag:bmip-n2", 8000),
    ("tag:bmip-n1", "tag:bmip-n2", 4200),
    ("tag:bmip-n1", "tag:bmip-n2", 5432),
    ("tag:bmip-n2", "tag:bmip-n1", 5432),
    ("tag:bmip-n2", "tag:bmip-n1", 9000),
    ("tag:bmip-n2", "tag:bmip-n1", 8181),
    ("tag:bmip-n1", "tag:bmip-n3", 5002),
    ("tag:bmip-n1", "tag:bmip-n3", 8501),
    ("tag:bmip-n3", "tag:bmip-n1", 8000),
    ("tag:bmip-n4", "tag:bmip-n1", 8000),
    ("tag:bmip-n4", "tag:bmip-n1", 5432),
    ("tag:bmip-n1", "tag:bmip-n4", 3100),
    ("tag:bmip-n2", "tag:bmip-n4", 3100),
    ("tag:bmip-n3", "tag:bmip-n4", 3100),
]

# Deny-by-default checks that matter for the assessment: a user must never
# reach a database or an internal service port, and UI nodes must not reach
# storage directly.
REQUIRED_DENY = [
    ("tag:bmip-user", "tag:bmip-n1", 5432),
    ("tag:bmip-user", "tag:bmip-n1", 8000),
    ("tag:bmip-user", "tag:bmip-n2", 5432),
    ("tag:bmip-user", "tag:bmip-n4", 9090),
    ("tag:bmip-n3", "tag:bmip-n1", 5432),
    ("tag:bmip-n3", "tag:bmip-n1", 9000),
    ("tag:bmip-n2", "tag:bmip-n2", 5432),
]


def _commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return os.getenv("BMIP_COMMIT", "nogit")


def _ports(value: str) -> set[int]:
    ports: set[int] = set()
    for part in value.split(","):
        if "-" in part:
            start, end = part.split("-", 1)
            ports.update(range(int(start), int(end) + 1))
        else:
            ports.add(int(part))
    return ports


def load_matrix(payload: dict[str, Any]) -> tuple[dict[tuple[str, str], set[int]], list[str]]:
    problems: list[str] = []
    matrix: dict[tuple[str, str], set[int]] = {}
    for index, rule in enumerate(payload.get("acls", [])):
        srcs = rule.get("src", [])
        dsts = rule.get("dst", [])
        if not srcs or not dsts:
            problems.append(f"rule {index}: empty src or dst")
            continue
        if rule.get("action") != "accept":
            problems.append(f"rule {index}: only accept rules are expected")
            continue
        for src in srcs:
            if src not in TAGS:
                problems.append(f"rule {index}: unknown source tag {src!r}")
                continue
            for dst in dsts:
                match = DST_RE.match(dst)
                if not match:
                    problems.append(f"rule {index}: invalid dst {dst!r}")
                    continue
                target, raw_ports = match.groups()
                if target not in TAGS:
                    problems.append(f"rule {index}: unknown destination tag {target!r}")
                    continue
                matrix.setdefault((src, target), set()).update(_ports(raw_ports))
    return matrix, problems


def _allowed(matrix: dict[tuple[str, str], set[int]], src: str, dst: str, port: int) -> bool:
    return port in matrix.get((src, dst), set())


def live_status() -> dict[str, Any]:
    binary = shutil.which("tailscale")
    if not binary:
        return {"live_test": "not_run", "reason": "tailscale CLI not found"}
    try:
        raw = subprocess.run(
            [binary, "status", "--json"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"live_test": "not_run", "reason": f"{type(exc).__name__}: {exc}"}
    if raw.returncode != 0:
        return {
            "live_test": "not_run",
            "reason": (raw.stderr or raw.stdout or "tailscale status failed").strip()[:300],
        }
    try:
        status = json.loads(raw.stdout or "{}")
    except ValueError:
        return {"live_test": "not_run", "reason": "tailscale status was not JSON"}
    state = status.get("BackendState") or status.get("backendState") or "unknown"
    peers = status.get("Peer") or {}
    if state != "Running":
        return {
            "live_test": "not_run",
            "reason": f"tailscale backend state is {state}; login required",
            "backend_state": state,
        }
    return {
        "live_test": "status_only",
        "reason": "tailnet is logged in; port-level deny test is still a manual C3-D step",
        "backend_state": state,
        "peers": len(peers),
        "self": (status.get("Self") or {}).get("HostName"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acl", default=str(ACL_PATH))
    parser.add_argument(
        "--output",
        default=None,
        help="default: evidence/security/tailscale-acl_<UTC>.json",
    )
    args = parser.parse_args(argv)

    payload = json.loads(Path(args.acl).read_text(encoding="utf-8"))
    matrix, problems = load_matrix(payload)

    missing_allow = [
        {"src": src, "dst": dst, "port": port}
        for src, dst, port in REQUIRED_ALLOW
        if not _allowed(matrix, src, dst, port)
    ]
    unexpected_allow = [
        {"src": src, "dst": dst, "port": port}
        for src, dst, port in REQUIRED_DENY
        if _allowed(matrix, src, dst, port)
    ]

    tag_owners = set((payload.get("tagOwners") or {}).keys())
    unknown_owners = sorted(tag_owners - TAGS)
    if unknown_owners:
        problems.append(f"unknown tagOwners entries: {unknown_owners}")

    status = live_status()
    passed = not problems and not missing_allow and not unexpected_allow
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output = (
        Path(args.output)
        if args.output
        else EVIDENCE / f"tailscale-acl_{stamp}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)

    document = {
        "id": "CP1-tailscale-acl",
        "timestamp": datetime.now(UTC).isoformat(),
        "commit": _commit(),
        "command": "python scripts/c3c_acl.py",
        "result": "PASS" if passed else "FAIL",
        "owner": "vio",
        "acl_file": str(Path(args.acl).relative_to(ROOT)),
        "offline_validation": "PASS" if passed else "FAIL",
        "live_test": status.get("live_test"),
        "live_reason": status.get("reason"),
        "live_status": status,
        "required_allow": len(REQUIRED_ALLOW),
        "required_deny": len(REQUIRED_DENY),
        "missing_allow": missing_allow,
        "unexpected_allow": unexpected_allow,
        "problems": problems,
        "matrix": {
            f"{src} -> {dst}": sorted(ports)
            for (src, dst), ports in sorted(matrix.items())
        },
    }
    output.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "result": document["result"],
                "offline_validation": document["offline_validation"],
                "live_test": document["live_test"],
                "live_reason": document["live_reason"],
                "missing_allow": missing_allow,
                "unexpected_allow": unexpected_allow,
                "evidence": str(output.relative_to(ROOT)),
            },
            indent=2,
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
