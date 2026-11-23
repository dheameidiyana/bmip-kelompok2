#!/usr/bin/env python3
"""Run the T-19 restore drill from a W2-D backup manifest."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv
from w2d_backup import (
    ROOT,
    DatabaseTarget,
    container_for,
    psql,
    quote_ident,
    run,
    sha256_file,
    table_stats,
)


def latest_manifest() -> Path:
    files = sorted((ROOT / "evidence" / "recovery").glob("manifest_*.json"))
    if not files:
        raise FileNotFoundError("no evidence/recovery/manifest_*.json found")
    return files[-1]


def compare_tables(
    expected: list[dict[str, object]],
    actual: list[dict[str, object]],
    *,
    prefix: str | None = None,
) -> dict[str, object]:
    expected_map = {str(item["table"]): item for item in expected}
    actual_map = {str(item["table"]): item for item in actual}
    selected = [name for name in expected_map if prefix is None or name.startswith(prefix)]
    missing = sorted(name for name in selected if name not in actual_map)
    extra = sorted(
        name
        for name in actual_map
        if (prefix is None or name.startswith(prefix)) and name not in expected_map
    )
    mismatches: list[dict[str, object]] = []
    for name in selected:
        if name not in actual_map:
            continue
        expected_row = expected_map[name]
        actual_row = actual_map[name]
        if (
            expected_row["rows"] != actual_row["rows"]
            or expected_row["checksum"] != actual_row["checksum"]
        ):
            mismatches.append(
                {
                    "table": name,
                    "expected_rows": expected_row["rows"],
                    "actual_rows": actual_row["rows"],
                    "expected_checksum": expected_row["checksum"],
                    "actual_checksum": actual_row["checksum"],
                }
            )
    return {
        "ok": not missing and not extra and not mismatches,
        "checked": len(selected),
        "missing": missing,
        "extra": extra,
        "mismatches": mismatches,
        "expected_rows": sum(int(expected_map[name]["rows"]) for name in selected),
        "actual_rows": sum(
            int(actual_map[name]["rows"]) for name in selected if name in actual_map
        ),
    }


def drop_create_database(container: str, user: str, scratch: str) -> None:
    psql(
        container,
        user,
        "postgres",
        f"DROP DATABASE IF EXISTS {quote_ident(scratch)} WITH (FORCE)",
    )
    psql(container, user, "postgres", f"CREATE DATABASE {quote_ident(scratch)}")


def restore_dump(
    container: str,
    user: str,
    scratch: str,
    dump: Path,
    *,
    stamp: str,
    database: str,
    schema: str | None = None,
) -> None:
    remote = f"/tmp/t19_{stamp}_{database}.dump"
    run(["docker", "cp", str(dump), f"{container}:{remote}"])
    try:
        command = [
            "docker",
            "exec",
            container,
            "pg_restore",
            "-U",
            user,
            "-d",
            scratch,
            "--no-owner",
            "--no-privileges",
            "--exit-on-error",
        ]
        if schema:
            command.extend(["--schema", schema])
        command.append(remote)
        run(command)
    finally:
        run(["docker", "exec", container, "rm", "-f", remote], check=False)


def cleanup_database(container: str, user: str, scratch: str) -> None:
    psql(
        container,
        user,
        "postgres",
        f"DROP DATABASE IF EXISTS {quote_ident(scratch)} WITH (FORCE)",
    )


def write_evidence(
    path: Path,
    *,
    manifest_path: Path,
    manifest: dict[str, object],
    results: list[dict[str, object]],
    passed: bool,
) -> None:
    lines = [
        "T-19 Backup and restore drill",
        f"generated_at={datetime.now(UTC).isoformat()}",
        f"manifest={manifest_path.relative_to(ROOT).as_posix()}",
        f"backup_stamp={manifest.get('stamp')}",
        f"git_commit={manifest.get('git_commit')}",
        f"git_branch={manifest.get('git_branch')}",
        "",
    ]
    for result in results:
        lines.append(
            f"database={result['database']} service={result['service']} scratch={result['scratch']}"
        )
        lines.append(f"  dump_sha256={result['dump_sha256']}")
        if "error" in result:
            lines.append(f"  error={result['error']}")
            lines.append("")
            continue
        comparison = result["comparison"]
        lines.append(
            f"  full_restore={'PASS' if comparison['ok'] else 'FAIL'} "
            f"checked={comparison['checked']} "
            f"expected_rows={comparison['expected_rows']} "
            f"actual_rows={comparison['actual_rows']}"
        )
        for item in comparison["mismatches"]:
            lines.append(
                f"  mismatch {item['table']} "
                f"expected={item['expected_rows']}/{item['expected_checksum']} "
                f"actual={item['actual_rows']}/{item['actual_checksum']}"
            )
        for name in comparison["missing"]:
            lines.append(f"  missing_table={name}")
        for name in comparison["extra"]:
            lines.append(f"  extra_table={name}")
        for table in result["restored_tables"]:
            lines.append(f"  {table['table']} rows={table['rows']} checksum={table['checksum']}")
        if "schema_drill" in result:
            schema = result["schema_drill"]
            lines.append(
                f"  schema_drill schema={schema['schema']} "
                f"{'PASS' if schema['comparison']['ok'] else 'FAIL'} "
                f"checked={schema['comparison']['checked']} "
                f"expected_rows={schema['comparison']['expected_rows']} "
                f"actual_rows={schema['comparison']['actual_rows']}"
            )
            for item in schema["comparison"]["mismatches"]:
                lines.append(
                    f"  schema_mismatch {item['table']} "
                    f"expected={item['expected_rows']}/{item['expected_checksum']} "
                    f"actual={item['actual_rows']}/{item['actual_checksum']}"
                )
        lines.append("")
    lines.append(f"RESULT: {'PASS' if passed else 'FAIL'}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", help="manifest path (default: latest evidence)")
    parser.add_argument("--keep", action="store_true", help="keep scratch databases")
    parser.add_argument(
        "--skip-schema-drill",
        action="store_true",
        help="skip the serving schema drop and restore step",
    )
    parser.add_argument(
        "--evidence",
        default="evidence/recovery/T19.txt",
        help="T-19 evidence path",
    )
    args = parser.parse_args(argv)

    manifest_path = Path(args.manifest) if args.manifest else latest_manifest()
    if not manifest_path.is_absolute():
        manifest_path = ROOT / manifest_path
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "PASS":
        raise RuntimeError(f"backup manifest is not PASS: {manifest_path}")

    stamp = str(manifest["stamp"])
    core_database = os.getenv("POSTGRES_DB", "bmip")
    results: list[dict[str, object]] = []

    for entry in manifest["databases"]:
        database = str(entry["database"])
        service = str(entry["service"])
        user = str(entry["user"])
        dump = ROOT / str(entry["dump_path"])
        scratch = "bmip_t19_" + re.sub(r"[^a-zA-Z0-9_]", "_", database)[:50]
        result: dict[str, object] = {
            "database": database,
            "service": service,
            "scratch": scratch,
            "dump_sha256": entry["sha256"],
        }
        results.append(result)

        if not dump.exists():
            result["error"] = f"dump not found: {dump}"
            continue
        if sha256_file(dump) != entry["sha256"]:
            result["error"] = f"dump checksum mismatch: {dump}"
            continue

        profile = "governance" if service == "postgres-gov" else None
        target = DatabaseTarget(service, user, database, profile=profile)
        container = container_for(target)
        try:
            drop_create_database(container, user, scratch)
            restore_dump(
                container,
                user,
                scratch,
                dump,
                stamp=stamp,
                database=database,
            )
            restored = table_stats(container, user, scratch)
            result["restored_tables"] = restored
            result["comparison"] = compare_tables(entry["tables"], restored)

            if database == core_database and not args.skip_schema_drill:
                psql(
                    container,
                    user,
                    scratch,
                    "DROP SCHEMA IF EXISTS serving CASCADE",
                )
                psql(
                    container,
                    user,
                    scratch,
                    "CREATE SCHEMA IF NOT EXISTS serving",
                )
                restore_dump(
                    container,
                    user,
                    scratch,
                    dump,
                    stamp=stamp,
                    database=database,
                    schema="serving",
                )
                restored_schema = table_stats(container, user, scratch)
                result["schema_drill"] = {
                    "schema": "serving",
                    "comparison": compare_tables(
                        entry["tables"],
                        restored_schema,
                        prefix="serving.",
                    ),
                }
        except Exception as exc:  # noqa: BLE001 - report the failing database
            result["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            if not args.keep:
                cleanup_database(container, user, scratch)

        comparison = result.get("comparison", {})
        schema_drill = result.get("schema_drill", {})
        print(
            f"restore {service}/{database}: "
            f"full={'PASS' if comparison.get('ok') else 'FAIL'} "
            f"schema={'PASS' if schema_drill.get('comparison', {}).get('ok', True) else 'FAIL'}"
        )

    passed = all(
        "error" not in result
        and bool(result.get("comparison", {}).get("ok"))
        and bool(result.get("schema_drill", {}).get("comparison", {}).get("ok", True))
        for result in results
    )
    evidence_path = ROOT / args.evidence
    write_evidence(
        evidence_path,
        manifest_path=manifest_path,
        manifest=manifest,
        results=results,
        passed=passed,
    )
    print(f"evidence: {evidence_path.relative_to(ROOT)}")
    print(f"RESULT: {'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 - surface a clean CLI error
        print(f"restore drill failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
