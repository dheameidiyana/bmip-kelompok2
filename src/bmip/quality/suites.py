"""Declarative data-quality suites.

Each suite targets one dataset. A rule is either a Great Expectations
expectation, a pandas predicate, or one of the small domain checks that GX
cannot express (freshness, hourly gaps, label leakage, PII columns).

Severity decides the gate: ``critical`` blocks promotion, ``warning`` is
recorded and the pipeline continues (ARCHITECTURE §13.4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

SEVERITIES = ("critical", "warning")
RULE_KINDS = (
    "expectation",
    "expression",
    "freshness",
    "gap",
    "leakage",
    "no_pii_columns",
    "lag",
    "duplicate_rate",
)

DEFAULT_SUITE_DIR = Path(__file__).resolve().parents[3] / "gx" / "suites"


@dataclass(frozen=True)
class Rule:
    id: str
    kind: str
    severity: str
    description: str = ""
    kwargs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Suite:
    name: str
    dataset: str
    rules: tuple[Rule, ...]
    required: bool = True

    @property
    def critical_rules(self) -> tuple[Rule, ...]:
        return tuple(rule for rule in self.rules if rule.severity == "critical")


def _rule(raw: dict[str, Any], suite: str, index: int) -> Rule:
    identifier = str(raw.get("id") or f"{suite}-{index}")
    kind = str(raw.get("kind") or "expectation")
    if kind not in RULE_KINDS:
        raise ValueError(f"{identifier}: unknown rule kind {kind!r}")
    severity = str(raw.get("severity") or "critical")
    if severity not in SEVERITIES:
        raise ValueError(f"{identifier}: unknown severity {severity!r}")
    kwargs = {
        key: value
        for key, value in raw.items()
        if key not in {"id", "kind", "severity", "description"}
    }
    return Rule(
        id=identifier,
        kind=kind,
        severity=severity,
        description=str(raw.get("description") or ""),
        kwargs=kwargs,
    )


def load_suite(path: Path) -> Suite:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    name = str(payload.get("suite") or path.stem)
    dataset = str(payload.get("dataset") or "")
    if not dataset:
        raise ValueError(f"{path.name}: missing dataset")
    rules = tuple(
        _rule(raw, name, index) for index, raw in enumerate(payload.get("rules") or [])
    )
    return Suite(
        name=name,
        dataset=dataset,
        rules=rules,
        required=bool(payload.get("required", True)),
    )


def load_suites(directory: Path | str | None = None) -> list[Suite]:
    root = Path(directory) if directory else DEFAULT_SUITE_DIR
    return [load_suite(path) for path in sorted(root.glob("*.yml"))]
