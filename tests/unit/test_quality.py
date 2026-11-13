"""Unit tests for the quality gate (W1-C)."""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest

from bmip.quality.runner import QualityGateError, RuleResult, run_checkpoint, run_rule
from bmip.quality.suites import Rule, Suite, load_suites


def _frame():
    return pd.DataFrame(
        {
            "post_key": ["a", "b", "c"],
            "text": ["hello", "world", "third"],
            "sentiment_score": [0.5, -0.2, 0.0],
            "window_start": pd.to_datetime(
                [
                    "2026-11-10T00:00:00Z",
                    "2026-11-10T01:00:00Z",
                    "2026-11-10T02:00:00Z",
                ]
            ),
        }
    )


def test_suites_load_from_disk():
    suites = load_suites()
    datasets = {suite.dataset for suite in suites}
    assert "silver.social_post" in datasets
    assert "gold.mart_ml" in datasets
    assert all(suite.rules for suite in suites)


def test_critical_failure_blocks_the_gate():
    suite = Suite(
        name="demo",
        dataset="silver.social_post",
        rules=(
            Rule(
                id="no-null-text",
                kind="expression",
                severity="critical",
                kwargs={"expression": "text != 'world'"},
            ),
        ),
    )
    with pytest.raises(QualityGateError):
        run_checkpoint({"silver.social_post": _frame()}, [suite], warning_only=False)


def test_warning_failure_continues():
    suite = Suite(
        name="demo",
        dataset="silver.social_post",
        rules=(
            Rule(
                id="warn-only",
                kind="expression",
                severity="warning",
                kwargs={"expression": "text != 'world'"},
            ),
        ),
    )
    report = run_checkpoint({"silver.social_post": _frame()}, [suite], warning_only=False)
    assert report.status == "pass"
    assert len(report.suites[0].warning_failures) == 1


def test_warning_only_records_critical_failure():
    suite = Suite(
        name="demo",
        dataset="silver.social_post",
        rules=(
            Rule(
                id="critical",
                kind="expression",
                severity="critical",
                kwargs={"expression": "text != 'world'"},
            ),
        ),
    )
    report = run_checkpoint(
        {"silver.social_post": _frame()}, [suite], warning_only=True
    )
    assert report.status == "fail"
    assert report.warning_only is True


def test_missing_dataset_fails_closed():
    suite = Suite(
        name="demo",
        dataset="gold.mart_ml",
        rules=(
            Rule(
                id="row-count",
                kind="expression",
                severity="critical",
                kwargs={"expression": "True"},
            ),
        ),
    )
    report = run_checkpoint({}, [suite], warning_only=True)
    assert report.status == "fail"
    assert report.suites[0].rows == 0


def test_pii_rule_detects_forbidden_columns():
    rule = Rule(id="pii", kind="no_pii_columns", severity="critical")
    clean = run_rule(rule, _frame())
    assert clean.status == "pass"

    dirty = _frame().assign(author_handle=["alice", "bob", "carol"])
    assert run_rule(rule, dirty).status == "fail"


def test_leakage_rule_checks_label_window():
    rule = Rule(id="leak", kind="leakage", severity="critical")
    frame = pd.DataFrame(
        {
            "window_start": pd.to_datetime(["2026-11-10T00:00:00Z", "2026-11-10T01:00:00Z"]),
            "label_start": pd.to_datetime(["2026-11-10T00:00:00Z", "2026-11-10T01:00:00Z"]),
            "label_end": pd.to_datetime(["2026-11-10T01:00:00Z", "2026-11-10T02:00:00Z"]),
        }
    )
    assert run_rule(rule, frame).status == "pass"

    shifted = frame.assign(
        label_start=pd.to_datetime(["2026-11-10T00:30:00Z", "2026-11-10T01:00:00Z"])
    )
    assert run_rule(rule, shifted).status == "fail"


def test_freshness_rule_uses_threshold():
    rule = Rule(
        id="fresh",
        kind="freshness",
        severity="critical",
        kwargs={"column": "window_start", "threshold_minutes": 90, "now": "2026-11-10T03:00:00Z"},
    )
    assert run_rule(rule, _frame()).status == "pass"
    stale = Rule(
        id="fresh",
        kind="freshness",
        severity="critical",
        kwargs={"column": "window_start", "threshold_minutes": 30, "now": "2026-11-10T03:00:00Z"},
    )
    assert run_rule(stale, _frame()).status == "fail"


def test_gap_rule_detects_missing_hour():
    rule = Rule(id="gap", kind="gap", severity="critical", kwargs={"column": "window_start"})
    assert run_rule(rule, _frame()).status == "pass"
    sparse = _frame().iloc[[0, 2]]
    assert run_rule(rule, sparse).status == "fail"


def test_lag_rule_compares_against_reference_dataset():
    rule = Rule(
        id="lag",
        kind="lag",
        severity="critical",
        kwargs={
            "column": "window_start",
            "reference_dataset": "silver.market_ohlcv_1m",
            "threshold_minutes": 90,
        },
    )
    reference = pd.DataFrame(
        {
            "window_start": pd.to_datetime(
                ["2026-11-10T00:00:00Z", "2026-11-10T03:00:00Z"]
            )
        }
    )
    datasets = {"silver.market_ohlcv_1m": reference}
    assert run_rule(rule, _frame(), datasets=datasets).status == "pass"
    assert run_rule(rule, _frame(), datasets={}).status == "fail"


def test_duplicate_rate_rule_is_a_warning():
    rule = Rule(
        id="dupes",
        kind="duplicate_rate",
        severity="warning",
        kwargs={"columns": ["post_key"], "max_rate": 0.3},
    )
    assert run_rule(rule, _frame()).status == "pass"
    duplicated = pd.concat([_frame(), _frame().iloc[[0]]], ignore_index=True)
    assert run_rule(rule, duplicated).status == "pass"
    heavy = pd.concat([_frame(), _frame()], ignore_index=True)
    assert run_rule(rule, heavy).status == "fail"


def test_expectation_rule_uses_gx():
    rule = Rule(
        id="unique",
        kind="expectation",
        severity="critical",
        kwargs={"expectation": "ExpectColumnValuesToBeUnique", "column": "post_key"},
    )
    result = run_rule(rule, _frame())
    assert isinstance(result, RuleResult)
    assert result.status == "pass"

    duplicated = pd.concat([_frame(), _frame().iloc[[0]]], ignore_index=True)
    assert run_rule(rule, duplicated).status == "fail"


def test_report_serialises_without_nan_failures():
    suite = Suite(
        name="demo",
        dataset="silver.social_post",
        rules=(
            Rule(
                id="range",
                kind="expectation",
                severity="critical",
                kwargs={
                    "expectation": "ExpectColumnValuesToBeBetween",
                    "column": "sentiment_score",
                    "min_value": -1,
                    "max_value": 1,
                },
            ),
        ),
    )
    report = run_checkpoint({"silver.social_post": _frame()}, [suite])
    payload = report.as_dict()
    assert payload["status"] == "pass"
    assert payload["generated_at"].endswith("Z")
    assert datetime.now(UTC).year >= 2026
