"""Run quality suites against silver and gold dataframes.

The runner is the gate described in ARCHITECTURE §13.4: a critical failure
blocks promotion, a warning is recorded and the pipeline continues. Every run
writes a machine-readable report so the evidence file is generated, not typed.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pandas as pd

from bmip.common.logging import get_logger
from bmip.quality.suites import Rule, Suite

log = get_logger(__name__)

DEFAULT_PII_COLUMNS = (
    "post_uri",
    "author_did",
    "author_handle",
    "display_name",
    "avatar",
    "did",
    "handle",
)


class QualityGateError(RuntimeError):
    """Raised when a critical expectation fails and the gate is enforced."""


@dataclass
class RuleResult:
    id: str
    kind: str
    severity: str
    status: str
    observed: Any = None
    expected: Any = None
    detail: str = ""

    @property
    def failed(self) -> bool:
        return self.status == "fail"

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "severity": self.severity,
            "status": self.status,
            "observed": self.observed,
            "expected": self.expected,
            "detail": self.detail,
        }


@dataclass
class SuiteResult:
    suite: str
    dataset: str
    rows: int
    rules: list[RuleResult] = field(default_factory=list)

    @property
    def critical_failures(self) -> list[RuleResult]:
        return [r for r in self.rules if r.failed and r.severity == "critical"]

    @property
    def warning_failures(self) -> list[RuleResult]:
        return [r for r in self.rules if r.failed and r.severity == "warning"]

    @property
    def status(self) -> str:
        return "fail" if self.critical_failures else "pass"

    def as_dict(self) -> dict[str, Any]:
        return {
            "suite": self.suite,
            "dataset": self.dataset,
            "rows": self.rows,
            "status": self.status,
            "critical_failures": len(self.critical_failures),
            "warning_failures": len(self.warning_failures),
            "rules": [rule.as_dict() for rule in self.rules],
        }


def _result(
    rule: Rule,
    ok: bool,
    *,
    observed: Any = None,
    expected: Any = None,
    detail: str = "",
) -> RuleResult:
    return RuleResult(
        id=rule.id,
        kind=rule.kind,
        severity=rule.severity,
        status="pass" if ok else "fail",
        observed=observed,
        expected=expected,
        detail=detail,
    )


def _gx_expectation(rule: Rule):
    import great_expectations as gx

    expectation_type = rule.kwargs.get("expectation")
    if not expectation_type:
        raise ValueError(f"{rule.id}: expectation rule needs an 'expectation' key")
    kwargs = {
        key: value for key, value in rule.kwargs.items() if key != "expectation"
    }
    try:
        expectation_class = getattr(gx.expectations, str(expectation_type))
    except AttributeError as exc:
        raise ValueError(f"{rule.id}: unknown expectation {expectation_type}") from exc
    return expectation_class(**kwargs)


def _run_expectation(rule: Rule, frame: pd.DataFrame, batch) -> RuleResult:
    expectation = _gx_expectation(rule)
    outcome = batch.validate(expectation)
    observed = outcome.result or {}
    return _result(
        rule,
        bool(outcome.success),
        observed=observed.get("observed_value", observed.get("unexpected_count")),
        expected=rule.kwargs.get("expectation"),
        detail="" if outcome.success else json.dumps(observed, default=str)[:600],
    )


def _run_expression(rule: Rule, frame: pd.DataFrame) -> RuleResult:
    expression = str(rule.kwargs.get("expression") or "")
    if not expression:
        raise ValueError(f"{rule.id}: expression rule needs 'expression'")
    mask = frame.eval(expression)
    failing = int((~mask.fillna(False)).sum())
    return _result(
        rule,
        failing == 0,
        observed={"failing_rows": failing, "rows": len(frame)},
        expected=expression,
    )


def _run_freshness(rule: Rule, frame: pd.DataFrame) -> RuleResult:
    column = str(rule.kwargs.get("column") or "window_start")
    threshold = float(rule.kwargs.get("threshold_minutes", 90))
    now = rule.kwargs.get("now")
    observed_at = (
        pd.Timestamp(now).to_pydatetime()
        if now is not None
        else datetime.now(UTC)
    )
    if column not in frame.columns or frame.empty:
        return _result(
            rule,
            False,
            observed=None,
            expected=f"max({column}) within {threshold} minutes",
            detail="no rows to check freshness",
        )
    series = pd.to_datetime(frame[column], utc=True).dropna()
    if series.empty:
        return _result(
            rule,
            False,
            observed=None,
            expected=f"max({column})",
            detail="all values null",
        )
    latest = series.max().to_pydatetime()
    age_minutes = (observed_at - latest).total_seconds() / 60.0
    return _result(
        rule,
        age_minutes <= threshold,
        observed={"latest": latest.isoformat(), "age_minutes": round(age_minutes, 3)},
        expected=f"<= {threshold} minutes",
    )


def _run_gap(rule: Rule, frame: pd.DataFrame) -> RuleResult:
    column = str(rule.kwargs.get("column") or "window_start")
    max_gap = float(rule.kwargs.get("max_gap_hours", 1))
    lookback = float(rule.kwargs.get("lookback_hours", 24))
    if column not in frame.columns or frame.empty:
        return _result(
            rule,
            False,
            observed=None,
            expected=f"no gap > {max_gap}h",
            detail="no rows",
        )
    series = (
        pd.to_datetime(frame[column], utc=True).dropna().drop_duplicates().sort_values()
    )
    if series.empty:
        return _result(
            rule,
            False,
            observed=None,
            expected=f"no gap > {max_gap}h",
            detail="all null",
        )
    latest = series.max()
    window = series[series >= latest - pd.Timedelta(hours=lookback)]
    if len(window) < 2:
        return _result(
            rule,
            False,
            observed=len(window),
            expected=f"no gap > {max_gap}h",
            detail="fewer than two hours",
        )
    gaps = window.diff().dropna()
    largest = gaps.max().total_seconds() / 3600.0
    return _result(
        rule,
        largest <= max_gap,
        observed={"largest_gap_hours": round(largest, 3), "hours_checked": len(window)},
        expected=f"<= {max_gap} hours",
    )


def _run_leakage(rule: Rule, frame: pd.DataFrame) -> RuleResult:
    required = ("window_start", "label_start", "label_end")
    missing = [name for name in required if name not in frame.columns]
    if missing:
        return _result(rule, False, detail=f"missing columns: {missing}")
    labelled = frame[frame["label_start"].notna()]
    if labelled.empty:
        return _result(rule, False, detail="no labelled rows to check")
    window = pd.to_datetime(labelled["window_start"], utc=True)
    start = pd.to_datetime(labelled["label_start"], utc=True)
    end = pd.to_datetime(labelled["label_end"], utc=True)
    bad_start = int((start != window).fillna(True).sum())
    bad_end = int((end != window + pd.Timedelta(hours=1)).fillna(True).sum())
    return _result(
        rule,
        bad_start == 0 and bad_end == 0,
        observed={
            "bad_label_start": bad_start,
            "bad_label_end": bad_end,
            "labelled_rows": len(labelled),
            "rows": len(frame),
        },
        expected="label_start == window_start and label_end == window_start + 1h",
    )


def _run_pii(rule: Rule, frame: pd.DataFrame) -> RuleResult:
    forbidden = tuple(rule.kwargs.get("forbidden") or DEFAULT_PII_COLUMNS)
    present = sorted(set(forbidden).intersection(frame.columns))
    return _result(
        rule,
        not present,
        observed={"present": present, "columns": list(frame.columns)},
        expected=f"none of {list(forbidden)}",
    )


def _run_lag(
    rule: Rule,
    frame: pd.DataFrame,
    datasets: dict[str, pd.DataFrame] | None,
) -> RuleResult:
    """Gold must not trail its silver source by more than the threshold."""
    column = str(rule.kwargs.get("column") or "window_start")
    reference_dataset = str(rule.kwargs.get("reference_dataset") or "")
    reference_column = str(rule.kwargs.get("reference_column") or column)
    threshold = float(rule.kwargs.get("threshold_minutes", 90))
    reference = (datasets or {}).get(reference_dataset)
    if reference is None:
        return _result(
            rule,
            False,
            expected=f"{reference_dataset} loaded",
            detail="reference dataset was not loaded",
        )
    if frame.empty or reference.empty:
        return _result(rule, False, detail="empty dataset or reference")
    gold_latest = pd.to_datetime(frame[column], utc=True).max()
    silver_latest = pd.to_datetime(reference[reference_column], utc=True).max()
    lag_minutes = (silver_latest - gold_latest).total_seconds() / 60.0
    return _result(
        rule,
        lag_minutes <= threshold,
        observed={
            "gold_latest": gold_latest.isoformat(),
            "silver_latest": silver_latest.isoformat(),
            "lag_minutes": round(lag_minutes, 3),
        },
        expected=f"<= {threshold} minutes behind {reference_dataset}",
    )


def _run_duplicate_rate(rule: Rule, frame: pd.DataFrame) -> RuleResult:
    columns = list(rule.kwargs.get("columns") or [])
    max_rate = float(rule.kwargs.get("max_rate", 0.02))
    if not columns or any(name not in frame.columns for name in columns):
        return _result(rule, False, detail=f"missing key columns: {columns}")
    if frame.empty:
        return _result(rule, False, detail="no rows")
    unique = len(frame.drop_duplicates(subset=columns))
    duplicates = len(frame) - unique
    rate = duplicates / len(frame)
    return _result(
        rule,
        rate <= max_rate,
        observed={
            "duplicate_rate": round(rate, 6),
            "duplicate_rows": duplicates,
            "rows": len(frame),
        },
        expected=f"<= {max_rate}",
    )


def run_rule(
    rule: Rule,
    frame: pd.DataFrame,
    batch=None,
    datasets: dict[str, pd.DataFrame] | None = None,
) -> RuleResult:
    if rule.kind == "expectation":
        if batch is None:
            batch = _gx_batch(frame, "adhoc")
        return _run_expectation(rule, frame, batch)
    if rule.kind == "expression":
        return _run_expression(rule, frame)
    if rule.kind == "freshness":
        return _run_freshness(rule, frame)
    if rule.kind == "gap":
        return _run_gap(rule, frame)
    if rule.kind == "leakage":
        return _run_leakage(rule, frame)
    if rule.kind == "no_pii_columns":
        return _run_pii(rule, frame)
    if rule.kind == "lag":
        return _run_lag(rule, frame, datasets)
    if rule.kind == "duplicate_rate":
        return _run_duplicate_rate(rule, frame)
    raise ValueError(f"{rule.id}: unsupported rule kind {rule.kind}")


def _gx_batch(frame: pd.DataFrame, dataset: str):
    os.environ.setdefault("TQDM_DISABLE", "1")
    import great_expectations as gx

    context = gx.get_context(mode="ephemeral")
    datasource = context.data_sources.add_pandas(f"bmip-{dataset}")
    asset = datasource.add_dataframe_asset(dataset)
    batch_definition = asset.add_batch_definition_whole_dataframe("batch")
    return batch_definition.get_batch(batch_parameters={"dataframe": frame})


def run_suite(
    suite: Suite,
    frame: pd.DataFrame,
    *,
    batch=None,
    datasets: dict[str, pd.DataFrame] | None = None,
) -> SuiteResult:
    if batch is None and any(rule.kind == "expectation" for rule in suite.rules):
        batch = _gx_batch(frame, suite.dataset)
    result = SuiteResult(suite=suite.name, dataset=suite.dataset, rows=len(frame))
    for rule in suite.rules:
        try:
            result.rules.append(run_rule(rule, frame, batch, datasets))
        except Exception as exc:  # a broken rule fails closed
            result.rules.append(
                _result(rule, False, detail=f"{type(exc).__name__}: {exc}")
            )
    return result


@dataclass
class CheckpointReport:
    generated_at: str
    commit: str
    owner: str
    warning_only: bool
    suites: list[SuiteResult]

    @property
    def critical_failures(self) -> list[tuple[str, RuleResult]]:
        failures: list[tuple[str, RuleResult]] = []
        for suite in self.suites:
            for rule in suite.critical_failures:
                failures.append((suite.suite, rule))
        return failures

    @property
    def status(self) -> str:
        return "fail" if self.critical_failures else "pass"

    def as_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "commit": self.commit,
            "owner": self.owner,
            "warning_only": self.warning_only,
            "status": self.status,
            "critical_failures": len(self.critical_failures),
            "warning_failures": sum(len(suite.warning_failures) for suite in self.suites),
            "suites": [suite.as_dict() for suite in self.suites],
        }

    def write(self, path) -> None:
        from pathlib import Path

        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(self.as_dict(), indent=2, default=str) + "\n",
            encoding="utf-8",
        )


def run_checkpoint(
    datasets: dict[str, pd.DataFrame],
    suites: list[Suite],
    *,
    commit: str = "nogit",
    owner: str = "vio",
    warning_only: bool = False,
    now: datetime | None = None,
) -> CheckpointReport:
    stamp = (now or datetime.now(UTC)).isoformat().replace("+00:00", "Z")
    results: list[SuiteResult] = []
    for suite in suites:
        frame = datasets.get(suite.dataset)
        if frame is None:
            if suite.required:
                missing = RuleResult(
                    id=f"{suite.name}-missing-dataset",
                    kind="presence",
                    severity="critical",
                    status="fail",
                    detail=f"dataset {suite.dataset} was not loaded",
                )
                results.append(
                    SuiteResult(
                        suite=suite.name,
                        dataset=suite.dataset,
                        rows=0,
                        rules=[missing],
                    )
                )
            continue
        results.append(run_suite(suite, frame, datasets=datasets))

    report = CheckpointReport(
        generated_at=stamp,
        commit=commit,
        owner=owner,
        warning_only=warning_only,
        suites=results,
    )
    for suite_name, rule in report.critical_failures:
        log.error(
            "critical data-quality failure",
            extra={"ctx_suite": suite_name, "ctx_rule": rule.id},
        )
    if report.critical_failures and not warning_only:
        names = ", ".join(f"{suite}:{rule.id}" for suite, rule in report.critical_failures)
        raise QualityGateError(f"critical data-quality failures: {names}")
    if report.critical_failures and warning_only:
        log.warning("critical failures tolerated because --warning-only is set")
    return report


def empty_frame(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame({column: pd.Series(dtype="object") for column in columns})


def to_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Build a dataframe and turn Iceberg decimals into floats for GX."""
    frame = pd.DataFrame(rows)
    for column in frame.columns:
        if frame[column].dtype != object:
            continue
        sample = frame[column].dropna()
        if not sample.empty and all(isinstance(value, Decimal) for value in sample):
            frame[column] = frame[column].astype(float)
    return frame
