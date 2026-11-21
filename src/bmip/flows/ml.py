"""Scheduled ML flows: hourly scoring and weekly retraining."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from prefect import flow, task

from bmip.common.config import get_settings
from bmip.common.logging import configure_logging
from bmip.lineage import dataset_ref, lineage_run
from bmip.ml.batch import run_batch

ROOT = Path(__file__).resolve().parents[3]


def _infer_once() -> dict[str, Any]:
    result = run_batch(get_settings())
    if result.get("failed"):
        stale = ", ".join(result.get("stale_symbols") or [])
        raise RuntimeError(f"batch inference failed; stale symbols: {stale or 'none'}")
    return result


@task(name="infer-volatility", retries=0)
def infer_volatility_task() -> dict[str, Any]:
    return _infer_once()


@task(name="train-volatility", retries=0)
def train_volatility_task() -> dict[str, Any]:
    load_dotenv(ROOT / ".env")
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "w2a_train.py")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(
            f"training failed with exit code {completed.returncode}: {detail[-4000:]}"
        )
    return {
        "returncode": completed.returncode,
        "stdout_tail": completed.stdout[-4000:],
    }


@flow(name="infer-volatility", log_prints=True)
def infer_volatility_flow() -> dict[str, Any]:
    configure_logging()
    with lineage_run(
        "infer-volatility",
        inputs=[
            dataset_ref("gold", "mart_ml"),
            dataset_ref("serving", "market_hourly"),
        ],
        outputs=[dataset_ref("serving", "predictions")],
        namespace="bmip_ml",
    ):
        return infer_volatility_task()


@flow(name="train-volatility", log_prints=True)
def train_volatility_flow() -> dict[str, Any]:
    configure_logging()
    with lineage_run(
        "train-volatility",
        inputs=[dataset_ref("gold", "mart_ml")],
        outputs=[dataset_ref("serving", "model_metrics")],
        namespace="bmip_ml",
    ):
        return train_volatility_task()
