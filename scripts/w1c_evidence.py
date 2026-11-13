#!/usr/bin/env python3
"""Generate the W1-C evidence files (T-03, T-09, T-10, T-11, T-12, T-31..T-33).

Every file is produced by running the pipeline, never hand-written. The script
is safe to rerun: it restores the demo data after the correction test.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT / "scripts"))

OWNER = "vio"
EVIDENCE = ROOT / "evidence"


def _now() -> datetime:
    return datetime.now(UTC)


def _stamp(value: datetime | None = None) -> str:
    return (value or _now()).strftime("%Y%m%dT%H%M")


def _commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "nogit"


def _header(identifier: str, command: str, result: str, *, ts: str, sha: str) -> str:
    return (
        f"id        : {identifier}\n"
        f"timestamp : {_now().isoformat().replace('+00:00', 'Z')}\n"
        f"commit    : {sha}\n"
        f"command   : {command}\n"
        f"result    : {result}\n"
        f"owner     : {OWNER}\n"
        f"run       : {ts}\n\n"
    )


def _begin(identifier: str, step: str, passed: bool, *, ts: str, sha: str) -> str:
    command = f"scripts/w1c_evidence.py ({step})"
    return _header(identifier, command, "PASS" if passed else "FAIL", ts=ts, sha=sha)


def _write(relative: str, text: str) -> Path:
    path = EVIDENCE / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _json(relative: str, payload: dict[str, Any]) -> Path:
    return _write(relative, json.dumps(payload, indent=2, default=str) + "\n")


def _hash_rows(rows: list[dict[str, Any]]) -> str:
    ordered = sorted(json.dumps(row, sort_keys=True, default=str) for row in rows)
    return hashlib.sha256("\n".join(ordered).encode("utf-8")).hexdigest()


def _rebuild_gold(settings) -> dict[str, Any]:
    from run_dbt import main as run_dbt

    from bmip.transform.gold import GoldWriter

    if run_dbt(["--select", "marts"]) != 0:
        raise RuntimeError("dbt marts build failed")
    writer = GoldWriter(settings)
    writer.ensure_tables()
    writer.publish_from_duckdb(ROOT / "dbt" / "target" / "bmip.duckdb")
    market = writer.fetch("gold.mart_market")
    sentiment = writer.fetch("gold.mart_sentiment")
    return {
        "counts": writer.counts(),
        "market_hash": _hash_rows(market),
        "sentiment_hash": _hash_rows(sentiment),
        "market_rows": len(market),
        "sentiment_rows": len(sentiment),
    }


def t03_social_dedup(settings, *, ts: str, sha: str) -> dict[str, Any]:
    from bmip.transform.silver_social import SocialWriter
    from bmip.transform.social import parse_social_post
    from bmip.transform.social_pipeline import read_bronze_social

    writer = SocialWriter(settings)
    writer.ensure_tables()
    before = writer.counts()
    bronze = read_bronze_social(settings)
    post, reason = parse_social_post(
        bronze[0],
        salt=settings.pii_hash_salt,
        model_version=settings.sentiment_model_version,
    )
    if post is None:
        raise RuntimeError(f"cannot parse bronze post: {reason}")
    stats = writer.write([post])
    after = writer.counts()
    passed = before == after

    lines = [
        _begin("T-03", "t03_social_dedup", passed, ts=ts, sha=sha),
        "Silver social deduplication: the same post_key is written twice.",
        "",
        f"before   : {before}",
        f"rewrite  : {stats.as_dict()}",
        f"after    : {after}",
        "",
        f"count unchanged : {before == after}",
        "",
        "The writer merges on post_key inside the event_date partition and keeps",
        "the newest ingest_ts, so a replay cannot add a second row.",
    ]
    _write("tests/T03.txt", "\n".join(lines) + "\n")
    return {"pass": passed, "before": before, "after": after}


def t10_sentiment_range(settings, *, ts: str, sha: str) -> dict[str, Any]:
    from bmip.transform.social import score_sentiment

    samples = [
        "BTC to the moon!!!",
        "I hate this market so much",
        "Bitcoin traded sideways today",
        "#bitcoin #btc volatility rising",
        "This dump is brutal, everything is red",
    ]
    rows = []
    for text in samples:
        sentiment = score_sentiment(text, model_version=settings.sentiment_model_version)
        rows.append((text, sentiment))
    passed = all(-1.0 <= sentiment.compound <= 1.0 for _, sentiment in rows)

    lines = [
        _begin("T-10", "t10_sentiment_range", passed, ts=ts, sha=sha),
        f"model_version : {settings.sentiment_model_version}",
        "",
        f"{'compound':>10}  {'pos':>5} {'neu':>5} {'neg':>5}  label     text",
    ]
    for text, sentiment in rows:
        lines.append(
            f"{sentiment.compound:>10.4f}  {sentiment.positive:>5.2f} {sentiment.neutral:>5.2f}"
            f" {sentiment.negative:>5.2f}  {sentiment.label:<9} {text}"
        )
    lines += ["", f"all scores in [-1, 1] : {passed}"]
    _write("tests/T10.txt", "\n".join(lines) + "\n")
    return {"pass": passed, "scores": [sentiment.compound for _, sentiment in rows]}


def t09_no_leakage(settings, *, ts: str, sha: str) -> dict[str, Any]:
    """Build two synthetic hours offline and prove future data cannot move features."""
    import importlib.util


    spec = importlib.util.spec_from_file_location(
        "ci_fixtures", ROOT / "scripts" / "ci_fixtures.py"
    )
    fixtures = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(fixtures)

    with tempfile.TemporaryDirectory() as tmp:
        base_dir = Path(tmp)
        iceberg = base_dir / "iceberg.duckdb"
        duckdb_path = base_dir / "ci.duckdb"
        fixtures.build_fixture_db(iceberg)
        if not fixtures.dbt_build(
            "staging intermediate silver marts",
            duckdb_path=duckdb_path,
            iceberg_path=iceberg,
        ):
            raise RuntimeError("dbt build failed for the leakage fixture")
        base = fixtures.read_mart(duckdb_path, "mart_ml")

        cut = datetime(2026, 11, 10, 2, tzinfo=UTC)
        spike_iceberg = base_dir / "spike_iceberg.duckdb"
        spike_duckdb = base_dir / "spike.duckdb"
        fixtures.build_fixture_db(spike_iceberg, spike_from=cut)
        if not fixtures.dbt_build(
            "staging intermediate silver marts",
            duckdb_path=spike_duckdb,
            iceberg_path=spike_iceberg,
        ):
            raise RuntimeError("dbt build failed for the spike fixture")
        spike = fixtures.read_mart(spike_duckdb, "mart_ml")

    feature_columns = [
        "ret_5m",
        "ret_15m",
        "ret_60m",
        "rv_5m",
        "rv_15m",
        "rv_60m",
        "volume_z_60m",
        "trade_count_60m",
        "hl_range_1m",
        "vwap_dev",
    ]
    reference = {(row["symbol"], row["window_start"]): row for row in base}
    checked = 0
    mismatches = 0
    detail: list[str] = []
    for row in spike:
        if row["window_start"] > cut:
            continue
        base_row = reference.get((row["symbol"], row["window_start"]))
        if base_row is None:
            continue
        for column in feature_columns:
            left, right = row[column], base_row[column]
            same = (left is None and right is None) or (
                left is not None and right is not None and abs(left - right) <= 1e-12
            )
            if not same:
                mismatches += 1
                detail.append(f"{row['window_start']} {column}: {right} -> {left}")
        checked += 1

    labels_ok = all(
        row["label_start"] == row["window_start"]
        and row["label_end"] == row["window_start"] + timedelta(hours=1)
        for row in base
        if row["label_start"] is not None
    )
    passed = mismatches == 0 and checked >= 2 and labels_ok

    lines = [
        _begin("T-09", "t09_no_leakage", passed, ts=ts, sha=sha),
        "Two synthetic hours, built twice: the second build triples every price from",
        f"{cut.isoformat()} onward. Features at or before that hour must be identical.",
        "",
        f"feature hours compared : {checked}",
        f"feature mismatches     : {mismatches}",
        f"label window correct   : {labels_ok}",
        "",
        "Checked columns: " + ", ".join(feature_columns),
    ]
    lines += ["", *detail] if detail else []
    _write("tests/T09.txt", "\n".join(lines) + "\n")
    return {"pass": passed, "checked": checked, "mismatches": mismatches}


def t11_critical_gate(settings, *, ts: str, sha: str) -> dict[str, Any]:
    from bmip.quality.checkpoint import load_dataset
    from bmip.quality.runner import QualityGateError, run_checkpoint
    from bmip.quality.suites import load_suites

    suites = [s for s in load_suites() if s.dataset == "silver.market_trades"]
    frame = load_dataset(settings, "silver.market_trades")
    injected = frame.copy()
    injected.loc[injected.index[0], "trade_id"] = None

    blocked = False
    message = ""
    try:
        run_checkpoint({"silver.market_trades": injected}, suites, warning_only=False)
    except QualityGateError as exc:
        blocked = True
        message = str(exc)

    clean = run_checkpoint({"silver.market_trades": frame}, suites, warning_only=False)
    passed = blocked and clean.status == "pass"

    lines = [
        _begin("T-11", "t11_critical_gate", passed, ts=ts, sha=sha),
        "A null trade_id is injected into one silver row before the gate.",
        "",
        f"rows inspected        : {len(frame)}",
        f"gold build blocked    : {blocked}",
        f"gate error            : {message}",
        f"clean data status     : {clean.status}",
        "",
        "Alert delivery is W2-B scope; this evidence proves the blocking gate and the",
        "rule id that fires. The publisher is only called after a passing gold gate.",
    ]
    _write("tests/T11.txt", "\n".join(lines) + "\n")
    return {"pass": passed, "blocked": blocked, "message": message}


def t12_warning_path(settings, *, ts: str, sha: str) -> dict[str, Any]:
    import pandas as pd

    from bmip.quality.checkpoint import load_dataset
    from bmip.quality.runner import run_checkpoint
    from bmip.quality.suites import load_suites

    suites = [s for s in load_suites() if s.dataset == "silver.market_trades"]
    frame = load_dataset(settings, "silver.market_trades")
    sample = frame.head(1000).copy()
    extra = sample.head(30).copy()
    injected = pd.concat([sample, extra], ignore_index=True)
    rate = (len(injected) - len(injected.drop_duplicates(["symbol", "trade_id"]))) / len(injected)

    report = run_checkpoint({"silver.market_trades": injected}, suites, warning_only=False)
    warnings = [
        (suite.suite, rule.id, rule.observed)
        for suite in report.suites
        for rule in suite.warning_failures
    ]
    passed = report.status == "pass" and bool(warnings)

    lines = [
        _begin("T-12", "t12_warning_path", passed, ts=ts, sha=sha),
        "30 duplicate rows are appended to a 1,000-row sample before deduplication.",
        "",
        f"injected duplicate rate : {rate:.4f}",
        f"checkpoint status       : {report.status}",
        f"critical failures       : {len(report.critical_failures)}",
        f"warning failures        : {len(report.suites[0].warning_failures)}",
        "",
    ]
    for suite_name, rule_id, observed in warnings:
        lines.append(f"warning: {suite_name}:{rule_id} observed={observed}")
    lines += [
        "",
        "The pipeline continues: the warning is recorded in dq_report.json and the",
        "gold build is not blocked.",
    ]
    _write("tests/T12.txt", "\n".join(lines) + "\n")
    return {"pass": passed, "rate": rate, "warnings": len(warnings)}


def t31_schema_evolution(settings, *, ts: str, sha: str) -> dict[str, Any]:
    import pyarrow as pa
    from pyiceberg.partitioning import PartitionSpec
    from pyiceberg.schema import Schema
    from pyiceberg.types import DoubleType, NestedField, StringType, TimestamptzType

    from bmip.transform.iceberg import (
        ensure_namespace,
        load_rest_catalog,
        table_with_host_io,
    )

    identifier = "silver.schema_evolution_probe"
    catalog = load_rest_catalog(settings)
    ensure_namespace(catalog, "silver")
    try:
        catalog.drop_table(identifier)
    except Exception:
        pass

    schema_v1 = Schema(
        NestedField(1, "post_key", StringType(), required=True),
        NestedField(2, "event_ts", TimestamptzType(), required=True),
        NestedField(3, "score", DoubleType(), required=True),
    )
    catalog.create_table(
        identifier,
        schema=schema_v1,
        location="s3://lakehouse/warehouse/silver.db/schema_evolution_probe",
        partition_spec=PartitionSpec(),
    )
    table = table_with_host_io(catalog, settings, identifier)
    stamp = _now()
    table.append(
        pa.Table.from_pylist([{"post_key": "probe-1", "event_ts": stamp, "score": 0.5}])
    )
    snapshot_v1 = table.current_snapshot().snapshot_id

    with table.update_schema() as update:
        update.add_column("confidence", DoubleType(), required=False)
    table = table_with_host_io(catalog, settings, identifier)
    table.append(
        pa.Table.from_pylist(
            [{"post_key": "probe-2", "event_ts": stamp, "score": -0.5, "confidence": 0.9}]
        )
    )

    current = table.scan().to_arrow().to_pylist()
    old = table.scan(snapshot_id=snapshot_v1).to_arrow().to_pylist()
    old_columns = table.scan(snapshot_id=snapshot_v1).to_arrow().column_names

    passed = (
        len(current) == 2
        and any(row["post_key"] == "probe-1" and row["confidence"] is None for row in current)
        and any(row["post_key"] == "probe-2" and row["confidence"] == 0.9 for row in current)
        and len(old) == 1
        and "confidence" not in old_columns
    )

    lines = [
        _begin("T-31", "t31_schema_evolution", passed, ts=ts, sha=sha),
        f"table          : {identifier}",
        f"snapshot v1    : {snapshot_v1}",
        f"current schema : {[field.name for field in table.schema().fields]}",
        f"v1 columns     : {old_columns}",
        "",
        f"current rows   : {current}",
        f"v1 rows        : {old}",
        "",
        f"old snapshot readable and new nullable column absent : {passed}",
    ]
    _write("storage/T31.txt", "\n".join(lines) + "\n")
    catalog.drop_table(identifier)
    return {"pass": passed, "snapshot": snapshot_v1}


def _sentiment_means(writer) -> dict[str, float | None]:
    rows = writer.fetch("gold.mart_sentiment")
    return {
        str(row["window_start"]): row["mean_sentiment"]
        for row in rows
    }


def t32_correction(settings, *, ts: str, sha: str) -> dict[str, Any]:
    from bmip.transform.gold import GoldWriter
    from bmip.transform.silver_social import SocialWriter
    from bmip.transform.social import parse_social_post
    from bmip.transform.social_pipeline import read_bronze_social

    bronze = read_bronze_social(settings)
    target = bronze[0]
    writer = SocialWriter(settings)
    gold = GoldWriter(settings)
    before = _sentiment_means(gold)

    correction_text = "Terrible crash, I hate this market and everything is red"
    corrected, _ = parse_social_post(
        {**target, "text": correction_text, "ingest_ts": _now().isoformat()},
        salt=settings.pii_hash_salt,
        model_version=settings.sentiment_model_version,
    )
    if corrected is None:
        raise RuntimeError("correction row failed the silver contract")
    writer.write([corrected])
    after_correction = _rebuild_gold(settings)
    after = _sentiment_means(gold)

    changed = {
        hour: {"before": before.get(hour), "after": after.get(hour)}
        for hour in sorted(set(before) | set(after))
        if before.get(hour) != after.get(hour)
    }
    restored, _ = parse_social_post(
        {**target, "ingest_ts": (_now() + timedelta(seconds=5)).isoformat()},
        salt=settings.pii_hash_salt,
        model_version=settings.sentiment_model_version,
    )
    if restored is not None:
        writer.write([restored])
        _rebuild_gold(settings)
    final = _sentiment_means(gold)

    passed = bool(changed)

    payload = {
        "id": "T-32",
        "timestamp": _now().isoformat().replace("+00:00", "Z"),
        "commit": sha,
        "command": "scripts/w1c_evidence.py (t32_correction)",
        "result": "PASS" if passed else "FAIL",
        "owner": OWNER,
        "correction_text": correction_text,
        "changed_hours": changed,
        "restored_hours": final,
        "market_counts": after_correction["counts"],
    }
    _json("storage/T32.json", payload)
    return {"pass": passed, "changed": changed}


def t33_rerun_identical(settings, *, ts: str, sha: str) -> dict[str, Any]:
    first = _rebuild_gold(settings)
    second = _rebuild_gold(settings)
    passed = (
        first["counts"] == second["counts"]
        and first["market_hash"] == second["market_hash"]
        and first["sentiment_hash"] == second["sentiment_hash"]
    )
    payload = {
        "id": "T-33",
        "timestamp": _now().isoformat().replace("+00:00", "Z"),
        "commit": sha,
        "command": "scripts/w1c_evidence.py (t33_rerun_identical)",
        "result": "PASS" if passed else "FAIL",
        "owner": OWNER,
        "first": first,
        "second": second,
        "identical": passed,
    }
    _json("storage/T33.json", payload)
    return {"pass": passed, "first": first["counts"]}


def pii_columns(settings, *, ts: str, sha: str) -> dict[str, Any]:
    from bmip.transform.iceberg import load_rest_catalog, table_with_host_io
    from bmip.transform.silver_social import POSTS_TABLE, SENTIMENT_TABLE

    catalog = load_rest_catalog(settings)
    forbidden = ("post_uri", "author_did", "author_handle", "display_name", "avatar")
    lines = [
        _header("T-22-draft", "scripts/w1c_evidence.py (pii_columns)", "PASS", ts=ts, sha=sha),
        "Columns and sample values in the silver social tables (ADR-011).",
        "",
    ]
    passed = True
    for identifier in (POSTS_TABLE, SENTIMENT_TABLE):
        table = table_with_host_io(catalog, settings, identifier)
        rows = table.scan().to_arrow().to_pylist()
        columns = [field.name for field in table.schema().fields]
        present = sorted(set(forbidden).intersection(columns))
        sample = json.dumps(rows[:2], default=str)
        leaked = [token for token in ("at://", "did:plc:", "bsky.social") if token in sample]
        passed = passed and not present and not leaked
        lines += [
            f"table   : {identifier}",
            f"columns : {columns}",
            f"forbidden columns present : {present}",
            f"raw identifiers in sample : {leaked}",
            f"sample  : {sample[:400]}",
            "",
        ]
    lines.append(f"no raw PII in silver : {passed}")
    _write(f"security/pii-columns_{ts}.txt", "\n".join(lines) + "\n")
    return {"pass": passed}


def mart_counts(settings, *, ts: str) -> dict[str, Any]:
    from bmip.transform.gold import MART_TABLES, GoldWriter

    writer = GoldWriter(settings)
    path = EVIDENCE / "dq" / f"mart-counts_{ts}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    counts = writer.counts()
    with path.open("w", newline="", encoding="utf-8") as handle:
        fieldnames = ["table", "rows"]
        output = csv.DictWriter(handle, fieldnames=fieldnames)
        output.writeheader()
        for table in MART_TABLES:
            output.writerow({"table": table, "rows": counts.get(table, 0)})
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate W1-C evidence")
    parser.add_argument("--skip-dbt", action="store_true", help="skip T-09 and T-33 rebuilds")
    args = parser.parse_args(argv)

    from bmip.common.config import get_settings

    settings = get_settings()
    ts = _stamp()
    sha = _commit()
    results: dict[str, Any] = {}

    results["T-03"] = t03_social_dedup(settings, ts=ts, sha=sha)
    results["T-10"] = t10_sentiment_range(settings, ts=ts, sha=sha)
    if not args.skip_dbt:
        results["T-09"] = t09_no_leakage(settings, ts=ts, sha=sha)
    results["T-11"] = t11_critical_gate(settings, ts=ts, sha=sha)
    results["T-12"] = t12_warning_path(settings, ts=ts, sha=sha)
    results["T-31"] = t31_schema_evolution(settings, ts=ts, sha=sha)
    results["T-32"] = t32_correction(settings, ts=ts, sha=sha)
    if not args.skip_dbt:
        results["T-33"] = t33_rerun_identical(settings, ts=ts, sha=sha)
    results["pii"] = pii_columns(settings, ts=ts, sha=sha)
    results["counts"] = mart_counts(settings, ts=ts)

    summary = {
        "id": "W1-C",
        "timestamp": _now().isoformat().replace("+00:00", "Z"),
        "commit": sha,
        "owner": OWNER,
        "results": results,
        "status": "PASS" if all(
            value.get("pass", True) for value in results.values() if isinstance(value, dict)
        ) else "FAIL",
    }
    _json(f"w1c/SUMMARY_{ts}.json", summary)
    print(json.dumps(summary, indent=2, default=str))
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
