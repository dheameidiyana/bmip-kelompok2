#!/usr/bin/env python3
"""Run the C3-C governance workflow and metadata consistency test."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence" / "catalog"
load_dotenv(ROOT / ".env")

PROBE_ID = "serving.c3c_governance_probe"


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return os.getenv("BMIP_COMMIT", "nogit")


def _probe() -> dict[str, Any]:
    return {
        "id": PROBE_ID,
        "name": "C3-C governance probe",
        "layer": "serving",
        "domain": "ops",
        "kind": "postgres",
        "location": "serving.c3c_governance_probe",
        "description": "Temporary dataset used to prove the governance workflow.",
        "owner": "vio",
        "classification": "internal",
        "retention_days": 1,
        "refresh_schedule": "on demand",
        "sla": "not applicable",
        "license": "internal",
        "contains_pii": False,
        "tags": ["governance", "probe"],
        "contract_version": "v1",
        "change_note": "created by the C3-C workflow test",
    }


def _cleanup(settings) -> None:
    """Remove a probe left behind by an interrupted earlier run."""
    with psycopg.connect(settings.postgres_dsn, autocommit=True) as connection:
        connection.execute("DELETE FROM ops.dataset_registry WHERE id = %s", (PROBE_ID,))
        connection.execute("DELETE FROM serving.catalog_datasets WHERE id = %s", (PROBE_ID,))


def _audit_rows(settings, audit_ids: list[int]) -> list[dict[str, Any]]:
    if not audit_ids:
        return []
    with psycopg.connect(settings.postgres_dsn, autocommit=True) as connection:
        rows = connection.execute(
            """
            SELECT id, ts, actor, role, action, target, method, path, status
            FROM ops.audit_log WHERE id = ANY(%s) ORDER BY id
            """,
            (audit_ids,),
        ).fetchall()
    return [
        {
            "id": row[0],
            "ts": row[1].isoformat(),
            "actor": row[2],
            "role": row[3],
            "action": row[4],
            "target": row[5],
            "method": row[6],
            "path": row[7],
            "status": row[8],
        }
        for row in rows
    ]


def workflow(actor: str, role: str) -> dict[str, Any]:
    from bmip.catalog import governance
    from bmip.common.config import get_settings

    settings = get_settings()
    _cleanup(settings)
    steps: list[dict[str, Any]] = []
    audit_ids: list[int] = []
    try:
        registered = governance.register(_probe(), actor=actor, role=role, settings=settings)
        steps.append(registered)
        audit_ids.append(int(registered["audit_id"]))

        changed = governance.change(
            PROBE_ID,
            {
                "description": "Changed by the C3-C governance workflow test.",
                "contract_version": "v1.1",
                "change_note": "description and contract version updated",
            },
            actor=actor,
            role=role,
            settings=settings,
        )
        steps.append(changed)
        audit_ids.append(int(changed["audit_id"]))

        deprecated = governance.deprecate(
            PROBE_ID,
            removal_date=date.today(),
            note="workflow probe is removed at the end of the test",
            actor=actor,
            role=role,
            settings=settings,
        )
        steps.append(deprecated)
        audit_ids.append(int(deprecated["audit_id"]))

        deleted = governance.delete(
            PROBE_ID,
            actor=actor,
            role=role,
            confirm=True,
            settings=settings,
        )
        steps.append(deleted)
        audit_ids.append(int(deleted["audit_id"]))
    finally:
        _cleanup(settings)

    metadata = governance.metadata_consistency(settings)
    gaps = governance.gaps(settings)
    with psycopg.connect(settings.postgres_dsn, autocommit=True) as connection:
        remaining = connection.execute(
            "SELECT count(*) FROM ops.dataset_registry WHERE id = %s", (PROBE_ID,)
        ).fetchone()[0]
        total = connection.execute("SELECT count(*) FROM ops.dataset_registry").fetchone()[0]
    passed = (
        metadata["result"] == "PASS"
        and remaining == 0
        and total >= 11
        and [step["action"] for step in steps] == ["register", "change", "deprecate", "delete"]
    )
    document = {
        "id": "C3C-governance-workflow",
        "timestamp": datetime.now(UTC).isoformat(),
        "commit": _sha(),
        "command": "python scripts/c3c_governance.py workflow",
        "result": "PASS" if passed else "FAIL",
        "owner": "vio",
        "actor": actor,
        "role": role,
        "probe": PROBE_ID,
        "steps": steps,
        "audit": _audit_rows(settings, audit_ids),
        "metadata": metadata,
        "gaps": gaps,
        "probe_rows_left": remaining,
        "registry_rows": total,
    }
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    stamp = _stamp()
    path = EVIDENCE / f"governance_{stamp}.json"
    path.write_text(json.dumps(document, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({**document, "evidence": str(path.relative_to(ROOT))}, indent=2, default=str))
    return document


def metadata_test() -> dict[str, Any]:
    from bmip.catalog import governance
    from bmip.common.config import get_settings

    document = governance.metadata_consistency(get_settings())
    document.update(
        {
            "commit": _sha(),
            "command": "python scripts/c3c_governance.py metadata-test",
            "owner": "vio",
        }
    )
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    stamp = _stamp()
    json_path = EVIDENCE / f"metadata-test_{stamp}.json"
    json_path.write_text(json.dumps(document, indent=2, default=str) + "\n", encoding="utf-8")
    text_path = EVIDENCE / f"metadata-test_{stamp}.txt"
    text_path.write_text(
        "\n".join(
            [
                "id        : metadata_consistency",
                f"timestamp : {document['timestamp']}",
                f"commit    : {document['commit']}",
                "command   : python scripts/c3c_governance.py metadata-test",
                f"result    : {document['result']}",
                "owner     : vio",
                "",
                f"datasets          : {document['datasets']}",
                f"serving_datasets  : {document['serving_datasets']}",
                f"failures          : {len(document['failures'])}",
                *[f"- {failure}" for failure in document["failures"]],
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({**document, "evidence": str(json_path.relative_to(ROOT))}, indent=2))
    return document


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        nargs="?",
        default="workflow",
        choices=("workflow", "metadata-test", "gaps", "register", "change", "deprecate", "delete"),
    )
    parser.add_argument("--actor", default="vio")
    parser.add_argument("--role", default="admin")
    parser.add_argument("--dataset", default=PROBE_ID)
    parser.add_argument("--description", default="")
    parser.add_argument("--removal-date", default=str(date.today()))
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args(argv)

    if args.command == "workflow":
        document = workflow(args.actor, args.role)
        return 0 if document["result"] == "PASS" else 1
    if args.command == "metadata-test":
        document = metadata_test()
        return 0 if document["result"] == "PASS" else 1
    if args.command == "gaps":
        from bmip.catalog import governance
        from bmip.common.config import get_settings

        print(json.dumps(governance.gaps(get_settings()), indent=2))
        return 0

    from bmip.catalog import governance
    from bmip.common.config import get_settings

    settings = get_settings()
    if args.command == "register":
        print(
            json.dumps(
                governance.register(
                    _probe(), actor=args.actor, role=args.role, settings=settings
                ),
                indent=2,
            )
        )
    elif args.command == "change":
        print(
            json.dumps(
                governance.change(
                    args.dataset,
                    {"description": args.description or "changed from the CLI"},
                    actor=args.actor,
                    role=args.role,
                    settings=settings,
                ),
                indent=2,
            )
        )
    elif args.command == "deprecate":
        print(
            json.dumps(
                governance.deprecate(
                    args.dataset,
                    removal_date=date.fromisoformat(args.removal_date),
                    note="deprecated from the CLI",
                    actor=args.actor,
                    role=args.role,
                    settings=settings,
                ),
                indent=2,
            )
        )
    elif args.command == "delete":
        print(
            json.dumps(
                governance.delete(
                    args.dataset,
                    actor=args.actor,
                    role=args.role,
                    confirm=args.confirm,
                    settings=settings,
                ),
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
