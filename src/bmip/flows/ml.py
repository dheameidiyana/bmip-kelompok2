"""Scheduled ML flows: hourly scoring and weekly retraining."""

from __future__ import annotations

import json
import os
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
TRAIN_DEPLOYMENT = "train-volatility/train-volatility"


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
    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    if completed.returncode != 0:
        detail = (stderr or stdout).strip()
        raise RuntimeError(
            f"training failed with exit code {completed.returncode}: {detail[-4000:]}"
        )
    return {
        "returncode": completed.returncode,
        "stdout_tail": stdout[-4000:],
    }


def _run_script(script: str, *args: str) -> dict[str, Any]:
    load_dotenv(ROOT / ".env")
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    if completed.returncode != 0:
        detail = (stderr or stdout).strip()
        raise RuntimeError(
            f"{script} failed with exit code {completed.returncode}: {detail[-4000:]}"
        )
    lines = [line for line in stdout.splitlines() if line.strip()]
    if not lines:
        return {"returncode": completed.returncode}
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return {"returncode": completed.returncode, "stdout_tail": "\n".join(lines[-20:])}


@task(name="refresh-feast", retries=0)
def refresh_feast_task() -> dict[str, Any]:
    return _run_script("c3b_feast.py")


@task(name="drift-report", retries=0)
def drift_report_task() -> dict[str, Any]:
    result = _run_script("c3b_drift.py")
    if result.get("trigger_required") and os.getenv(
        "C3B_TRIGGER_RETRAIN", "true"
    ).lower() in {"1", "true", "yes", "on"}:
        from prefect.deployments import run_deployment

        os.environ.setdefault("PREFECT_API_URL", "http://127.0.0.1:4200/api")
        deployment = os.getenv("C3B_TRAIN_DEPLOYMENT", TRAIN_DEPLOYMENT)
        flow_run = run_deployment(name=deployment, timeout=0)
        result["training_triggered"] = True
        result["training_deployment"] = deployment
        result["training_flow_run_id"] = str(flow_run.id)
    else:
        result["training_triggered"] = False
    return result


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


@flow(name="refresh-feast", log_prints=True)
def refresh_feast_flow() -> dict[str, Any]:
    configure_logging()
    with lineage_run(
        "refresh-feast",
        inputs=[dataset_ref("gold", "mart_ml")],
        outputs=[dataset_ref("feast", "online_store")],
        namespace="bmip_ml",
    ):
        return refresh_feast_task()


@flow(name="drift-report", log_prints=True)
def drift_report_flow() -> dict[str, Any]:
    configure_logging()
    with lineage_run(
        "drift-report",
        inputs=[dataset_ref("gold", "mart_ml")],
        outputs=[dataset_ref("serving", "drift_metrics")],
        namespace="bmip_ml",
    ):
        return drift_report_task()
