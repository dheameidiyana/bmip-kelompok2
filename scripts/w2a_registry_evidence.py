"""Backfill ARCHITECTURE run tags and attach the model card to the champion."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from mlflow.tracking import MlflowClient

ROOT = Path(__file__).resolve().parents[1]
MODEL_NAME = "volatility_model"
EXPERIMENT = "volatility"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def _commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def latest_dataset_metadata() -> dict:
    paths = sorted((ROOT / "evidence" / "ml").glob("dataset_*.json"))
    if not paths:
        raise FileNotFoundError("no dataset_*.json evidence")
    return json.loads(paths[-1].read_text(encoding="utf-8"))


def latest_feature_importance() -> Path:
    paths = sorted((ROOT / "evidence" / "ml").glob("feature_importance_*.json"))
    if not paths:
        raise FileNotFoundError("no feature_importance_*.json evidence")
    return paths[-1]


def main() -> int:
    mlflow_tracking = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000")
    os.environ["MLFLOW_TRACKING_URI"] = mlflow_tracking
    import mlflow

    mlflow.set_tracking_uri(mlflow_tracking)
    client = MlflowClient()
    experiment = client.get_experiment_by_name(EXPERIMENT)
    if experiment is None:
        raise RuntimeError(f"MLflow experiment {EXPERIMENT!r} does not exist")
    metadata = latest_dataset_metadata()
    tags = {
        "data_snapshot_id": str(metadata["snapshot_id"]),
        "feature_version": "features/v1",
        "trigger": "manual-w2a-closeout",
        "git_sha": _commit(),
    }
    runs = client.search_runs([experiment.experiment_id], max_results=100)
    tagged = []
    for run in runs:
        for key, value in tags.items():
            client.set_tag(run.info.run_id, key, value)
        tagged.append({"run_id": run.info.run_id, "run_name": run.info.run_name})

    champion = client.get_model_version_by_alias(MODEL_NAME, "champion")
    card = ROOT / "evidence" / "ml" / "model-card.md"
    if not card.exists():
        raise FileNotFoundError(card)
    client.log_artifact(
        champion.run_id,
        str(card),
        artifact_path="model_card",
    )
    importance = latest_feature_importance()
    client.log_artifact(
        champion.run_id,
        str(importance),
        artifact_path="feature_importance",
    )
    payload = {
        "id": "W2-A-registry-evidence",
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "tracking_uri": mlflow_tracking,
        "model_name": MODEL_NAME,
        "champion_version": champion.version,
        "champion_run_id": champion.run_id,
        "tags": tags,
        "tagged_run_count": len(tagged),
        "runs": tagged,
        "model_card_artifact": {
            "run_id": champion.run_id,
            "artifact_path": "model_card/model-card.md",
            "source": str(card.relative_to(ROOT)),
        },
        "feature_importance_artifact": {
            "run_id": champion.run_id,
            "artifact_path": f"feature_importance/{importance.name}",
            "source": str(importance.relative_to(ROOT)),
        },
    }
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output = ROOT / "evidence" / "ml" / f"registry-metadata_{stamp}.json"
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
