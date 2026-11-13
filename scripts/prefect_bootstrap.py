#!/usr/bin/env python3
"""Create the local work pool and deploy BMIP flows to Prefect."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


def _prefect(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    return subprocess.run(
        [sys.executable, "-m", "prefect", *args],
        cwd=ROOT,
        check=check,
        text=True,
        env=env,
    )


def main() -> int:
    load_dotenv(ROOT / ".env")
    pool = os.getenv("PREFECT_WORK_POOL", "local-process")
    os.environ.setdefault("PREFECT_API_URL", "http://localhost:4200/api")

    inspected = _prefect("work-pool", "inspect", pool, check=False)
    if inspected.returncode != 0:
        _prefect("work-pool", "create", pool, "--type", "process")
    _prefect("work-pool", "set-concurrency-limit", pool, "1")
    _prefect("deploy", "--all", "--no-prompt")
    print(f"deployed BMIP flows to work pool {pool}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
