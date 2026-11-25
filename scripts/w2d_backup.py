#!/usr/bin/env python3
"""Back up the BMIP PostgreSQL databases and write a recovery manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILES = ("deploy/compose.base.yml", "deploy/compose.dev.yml")
BACKUP_BUCKET = "backups"
BACKUP_PREFIX = "postgres"


@dataclass(frozen=True)
class DatabaseTarget:
    service: str
    user: str
    database: str
    profile: str | None = None


def compose_prefix(profile: str | None = None) -> list[str]:
    command = ["docker", "compose", "--env-file", ".env"]
    for path in COMPOSE_FILES:
        command.extend(["-f", path])
    if profile:
        command.extend(["--profile", profile])
    return command


def run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    process = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )
    if check and process.returncode != 0:
        detail = (process.stderr or process.stdout).strip()
        raise RuntimeError(f"command failed ({process.returncode}): {' '.join(command)}\n{detail}")
    return process


def quote_ident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def container_for(target: DatabaseTarget) -> str:
    process = run([*compose_prefix(target.profile), "ps", "-q", target.service])
    containers = [line.strip() for line in process.stdout.splitlines() if line.strip()]
    if not containers:
        raise RuntimeError(f"{target.service} is not running; start it before running the backup")
    return containers[0]


def psql(container: str, user: str, database: str, sql: str) -> str:
    process = run(
        [
            "docker",
            "exec",
            container,
            "psql",
            "-X",
            "-U",
            user,
            "-d",
            database,
            "-v",
            "ON_ERROR_STOP=1",
            "-tA",
            "-F",
            "|",
            "-c",
            sql,
        ]
    )
    return process.stdout


def table_stats(container: str, user: str, database: str) -> list[dict[str, object]]:
    raw_tables = psql(
        container,
        user,
        database,
        """
        SELECT schemaname || '.' || tablename
        FROM pg_tables
        WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
        ORDER BY 1
        """,
    )
    tables = [line.strip() for line in raw_tables.splitlines() if line.strip()]
    if not tables:
        return []

    selects: list[str] = []
    for table in tables:
        schema, name = table.split(".", 1)
        label = table.replace("'", "''")
        relation = f"{quote_ident(schema)}.{quote_ident(name)}"
        checksum = "md5(coalesce(string_agg(md5(t::text), '' ORDER BY md5(t::text)), ''))"
        selects.append(f"SELECT '{label}', count(*), {checksum} FROM {relation} AS t")

    raw = psql(container, user, database, " UNION ALL ".join(selects) + " ORDER BY 1")
    stats: list[dict[str, object]] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        table, rows, checksum = line.split("|", 2)
        stats.append({"table": table, "rows": int(rows), "checksum": checksum.strip()})
    return stats


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_value(*args: str) -> str:
    process = run(["git", *args], check=False)
    return process.stdout.strip() if process.returncode == 0 else ""


def targets() -> list[DatabaseTarget]:
    core_user = os.getenv("POSTGRES_USER", "bmip")
    core_database = os.getenv("POSTGRES_DB", "bmip")
    lakekeeper_database = os.getenv("LAKEKEEPER_DB_NAME", "lakekeeper")
    prefect_user = os.getenv("PREFECT_DB_USER", "prefect")
    prefect_database = os.getenv("PREFECT_DB_NAME", "prefect")
    gov_user = os.getenv("POSTGRES_GOV_USER", "marquez")
    gov_database = os.getenv("POSTGRES_GOV_DB", "marquez")
    return [
        DatabaseTarget("postgres-core", core_user, core_database),
        DatabaseTarget("postgres-core", core_user, lakekeeper_database),
        DatabaseTarget("postgres-ml", prefect_user, prefect_database),
        DatabaseTarget("postgres-ml", prefect_user, "mlflow"),
        DatabaseTarget(
            "postgres-gov",
            gov_user,
            gov_database,
            profile="governance",
        ),
    ]


def backup_target(
    target: DatabaseTarget,
    *,
    stamp: str,
    backup_dir: Path,
) -> dict[str, object]:
    container = container_for(target)
    remote = f"/tmp/bmip_{stamp}_{target.database}.dump"
    local = backup_dir / f"{target.database}.dump"

    run(
        [
            "docker",
            "exec",
            container,
            "pg_dump",
            "-U",
            target.user,
            "-d",
            target.database,
            "-Fc",
            "-Z",
            "6",
            "-f",
            remote,
        ]
    )
    try:
        run(["docker", "cp", f"{container}:{remote}", str(local)])
    finally:
        run(["docker", "exec", container, "rm", "-f", remote], check=False)

    stats = table_stats(container, target.user, target.database)
    return {
        "service": target.service,
        "container": container,
        "database": target.database,
        "user": target.user,
        "dump_path": local.relative_to(ROOT).as_posix(),
        "bytes": local.stat().st_size,
        "sha256": sha256_file(local),
        "tables": stats,
        "row_total": sum(int(item["rows"]) for item in stats),
    }


def upload_file(local: Path, key: str) -> None:
    import boto3

    access_key = os.getenv("MINIO_SVC_BACKUP_ACCESS_KEY")
    secret_key = os.getenv("MINIO_SVC_BACKUP_SECRET_KEY")
    endpoint = os.getenv("MINIO_ENDPOINT", "http://localhost:9000")
    if not access_key or not secret_key:
        raise RuntimeError("missing MINIO_SVC_BACKUP_ACCESS_KEY or MINIO_SVC_BACKUP_SECRET_KEY")
    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=os.getenv("MINIO_S3_REGION", "local"),
    )
    client.upload_file(str(local), BACKUP_BUCKET, key)


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main(argv: list[str] | None = None) -> int:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stamp",
        default=datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"),
        help="backup stamp (default: current UTC time)",
    )
    parser.add_argument(
        "--backup-root",
        default="backups",
        help="local directory for dump files",
    )
    parser.add_argument(
        "--skip-upload",
        action="store_true",
        help="keep dumps local instead of uploading to MinIO",
    )
    args = parser.parse_args(argv)

    backup_dir = ROOT / args.backup_root / args.stamp
    backup_dir.mkdir(parents=True, exist_ok=True)

    databases: list[dict[str, object]] = []
    errors: list[dict[str, str]] = []
    for target in targets():
        try:
            item = backup_target(target, stamp=args.stamp, backup_dir=backup_dir)
        except Exception as exc:  # noqa: BLE001 - one database must not hide the rest
            errors.append(
                {
                    "service": target.service,
                    "database": target.database,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            print(
                f"backup failed for {target.service}/{target.database}: {exc}",
                file=sys.stderr,
            )
            continue
        databases.append(item)
        print(
            f"backed up {target.service}/{target.database} "
            f"({item['bytes']} bytes, {item['row_total']} rows)"
        )

    manifest: dict[str, object] = {
        "id": "W2D-CP1",
        "status": "PASS" if not errors else "FAILED",
        "stamp": args.stamp,
        "generated_at": datetime.now(UTC).isoformat(),
        "git_commit": git_value("rev-parse", "HEAD"),
        "git_branch": git_value("branch", "--show-current"),
        "backup_dir": backup_dir.relative_to(ROOT).as_posix(),
        "databases": databases,
        "errors": errors,
        "minio": {
            "bucket": BACKUP_BUCKET,
            "prefix": f"{BACKUP_PREFIX}/{args.stamp}",
            "uploaded": [],
        },
    }

    if not args.skip_upload:
        uploaded: list[str] = []
        for item in databases:
            key = f"{BACKUP_PREFIX}/{args.stamp}/{item['service']}/{item['database']}.dump"
            upload_file(ROOT / str(item["dump_path"]), key)
            uploaded.append(key)
        manifest["minio"] = {
            "bucket": BACKUP_BUCKET,
            "prefix": f"{BACKUP_PREFIX}/{args.stamp}",
            "uploaded": uploaded,
        }

    manifest_path = backup_dir / "manifest.json"
    write_json(manifest_path, manifest)
    evidence_path = ROOT / "evidence" / "recovery" / f"manifest_{args.stamp}.json"
    write_json(evidence_path, manifest)

    if not args.skip_upload:
        upload_file(manifest_path, f"{BACKUP_PREFIX}/{args.stamp}/manifest.json")

    print(f"manifest: {manifest_path.relative_to(ROOT)}")
    print(f"evidence: {evidence_path.relative_to(ROOT)}")
    if errors:
        print(f"{len(errors)} database(s) failed", file=sys.stderr)
        return 1
    print(f"{len(databases)} database(s) backed up")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 - surface a clean CLI error
        print(f"backup failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
