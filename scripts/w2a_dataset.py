"""Create the frozen W2-A dataset snapshot and feature-level T-09 evidence."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from bmip.common.config import get_settings
from bmip.common.symbols import MARKET_SYMBOLS
from bmip.ml.dataset import (
    MARKET_FEATURES,
    SYMBOL_FEATURES,
    load_mart_ml,
    save_snapshot,
    snapshot_metadata,
    write_metadata,
)

ROOT = Path(__file__).resolve().parents[1]


def t09_checks(snapshot) -> tuple[bool, list[str]]:
    frame = snapshot.frame
    lines = [
        f"dataset_id       : {snapshot.dataset_id}",
        f"snapshot_id      : {snapshot.snapshot_id}",
        f"sha256           : {snapshot.sha256}",
        f"rows             : {len(frame)}",
        f"counts           : {snapshot.counts}",
        f"start            : {snapshot.start.isoformat()}",
        f"end              : {snapshot.end.isoformat()}",
        "",
    ]
    checks = {
        "duplicate_symbol_window": int(
            frame.duplicated(["symbol", "window_start"]).sum()
        ),
        "null_market_features": int(frame[list(MARKET_FEATURES)].isna().sum().sum()),
        "label_before_feature": int(
            (frame["label_start"] < frame["window_start"]).sum()
        ),
        "label_end_not_after_start": int(
            (frame["label_end"] <= frame["label_start"]).sum()
        ),
        "one_hot_row_sum_bad": int(
            (frame[list(SYMBOL_FEATURES)].sum(axis=1) != 1).sum()
        ),
        "symbols": sorted(frame["symbol"].unique().tolist()),
        "splits": frame["split"].value_counts().sort_index().to_dict(),
    }
    passed = (
        checks["duplicate_symbol_window"] == 0
        and checks["null_market_features"] == 0
        and checks["label_before_feature"] == 0
        and checks["label_end_not_after_start"] == 0
        and checks["one_hot_row_sum_bad"] == 0
        and checks["symbols"] == sorted(MARKET_SYMBOLS)
    )
    lines.extend(f"{key:28}: {value}" for key, value in checks.items())
    lines.append("")
    lines.append(f"T-09 feature-level leakage check: {'PASS' if passed else 'FAIL'}")
    return passed, lines


def main() -> int:
    settings = get_settings()
    frame, snapshot_id = load_mart_ml(settings)
    snapshot = save_snapshot(settings, frame, snapshot_id)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    dataset_path = ROOT / "evidence" / "ml" / f"dataset_{stamp}.json"
    write_metadata(snapshot, dataset_path)
    passed, lines = t09_checks(snapshot)
    t09_path = ROOT / "evidence" / "tests" / "T09.txt"
    t09_path.parent.mkdir(parents=True, exist_ok=True)
    t09_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(snapshot_metadata(snapshot), indent=2, sort_keys=True))
    print(f"T09={'PASS' if passed else 'FAIL'} evidence={t09_path}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
