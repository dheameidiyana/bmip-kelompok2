"""Write W2-A persistence and EWMA baseline evidence from a frozen snapshot."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from bmip.ml.dataset import load_frozen_snapshot
from bmip.ml.metrics import baseline_metrics

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SNAPSHOT = (
    ROOT / "data" / "ml" / "snapshots" / "mart_ml_3627445140691597595.parquet"
)
BASELINES_START = "<!-- BASELINES:START -->"
BASELINES_END = "<!-- BASELINES:END -->"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def _now() -> datetime:
    return datetime.now(UTC)


def _commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def latest_metadata() -> Path:
    paths = sorted((ROOT / "evidence" / "ml").glob("dataset_*.json"))
    if not paths:
        raise FileNotFoundError("no dataset_*.json evidence")
    return paths[-1]


def baseline_markdown(metrics: dict, *, alpha: float) -> str:
    lines = [
        BASELINES_START,
        "## Baselines",
        "",
        f"EWMA uses `alpha={alpha}` (`lambda={1.0 - alpha:.2f}`) and is shifted "
        "one hour so the prediction never sees the label window.",
        "",
        "| Split | Baseline | Count | MAE | RMSE | R2 | Spearman |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for split in ("validation", "test"):
        for name in ("persistence", "ewma"):
            score = metrics[split][name]
            lines.append(
                f"| {split} | {name} | {score['count']} | "
                f"{score['mae']:.10f} | {score['rmse']:.10f} | "
                f"{score['r2']:.4f} | {score['spearman']:.4f} |"
            )
    lines.extend(["", BASELINES_END, ""])
    return "\n".join(lines)


def update_model_card(path: Path, block: str) -> None:
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    if BASELINES_START in text and BASELINES_END in text:
        before, rest = text.split(BASELINES_START, 1)
        _, after = rest.split(BASELINES_END, 1)
        text = before + block + after
    else:
        marker = "## Per-symbol test MAE"
        if marker not in text:
            text = text.rstrip() + "\n\n" + block
        else:
            text = text.replace(marker, block + "\n" + marker, 1)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--metadata", type=Path, default=None)
    parser.add_argument("--alpha", type=float, default=0.06)
    args = parser.parse_args()
    metadata_path = args.metadata or latest_metadata()
    snapshot = load_frozen_snapshot(args.snapshot, metadata_path)
    metrics = baseline_metrics(snapshot.frame, alpha=args.alpha)
    stamp = _now().strftime("%Y%m%dT%H%M%SZ")
    payload = {
        "id": "W2-A-baselines",
        "timestamp": _now().isoformat(timespec="seconds").replace("+00:00", "Z"),
        "commit": _commit(),
        "dataset_id": snapshot.dataset_id,
        "snapshot_id": snapshot.snapshot_id,
        "sha256": snapshot.sha256,
        "alpha": args.alpha,
        "lambda": 1.0 - args.alpha,
        "splits": metrics,
    }
    json_path = ROOT / "evidence" / "experiments" / f"baselines_{stamp}.json"
    md_path = ROOT / "evidence" / "experiments" / "baselines.md"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    block = baseline_markdown(metrics, alpha=args.alpha)
    md_path.write_text(
        "# W2-A Baselines\n\n" + block + "\n",
        encoding="utf-8",
    )
    update_model_card(
        ROOT / "evidence" / "ml" / "model-card.md",
        block,
    )
    print(
        json.dumps(
            {
                "evidence": str(json_path.relative_to(ROOT)),
                "markdown": str(md_path.relative_to(ROOT)),
                "validation": metrics["validation"],
                "test": metrics["test"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
