#!/usr/bin/env python3
"""Run dbt with the repository .env loaded and emit OpenLineage events."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    load_dotenv(ROOT / ".env")
    target = ROOT / "dbt" / "target"
    target.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("DBT_DUCKDB_PATH", str(target / "bmip.duckdb"))
    from dbt.cli.main import dbtRunner

    from bmip.lineage.dbt import dbt_lineage

    args = list(argv if argv is not None else sys.argv[1:])
    command = [
        "build",
        "--project-dir",
        str(ROOT / "dbt"),
        "--profiles-dir",
        str(ROOT / "dbt"),
        *args,
    ]
    with_error: str | None = None
    try:
        with dbt_lineage(select=" ".join(args) or None):
            result = dbtRunner().invoke(command)
            if not result.success:
                with_error = (
                    str(result.exception)
                    if result.exception is not None
                    else "dbt build failed"
                )
                raise RuntimeError(with_error)
    except Exception as exc:  # noqa: BLE001 - dbt failures return 1 to the caller
        if with_error is None:
            print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
