"""Static checks on the W2-B observability configuration.

These run in CI without Docker: they prove the files that ship are the files
the workplan asked for (16 rules, three classes, runbooks that exist, five
scrape jobs, two provisioned dashboards).
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
OBS = ROOT / "deploy" / "observability"


def _rules() -> list[dict]:
    document = yaml.safe_load((OBS / "rules.yml").read_text(encoding="utf-8"))
    return [rule for group in document["groups"] for rule in group["rules"]]


def test_sixteen_rules_in_three_classes() -> None:
    rules = _rules()
    assert len(rules) == 16
    classes = {rule["labels"]["alert_class"] for rule in rules}
    assert classes == {"job-failure", "stream-lag", "service"}


def test_every_rule_carries_owner_channel_severity_and_runbook() -> None:
    for rule in _rules():
        labels = rule["labels"]
        assert labels["owner"] == "vio", rule["alert"]
        assert labels["channel"] == "telegram", rule["alert"]
        assert labels["severity"] in {"critical", "warning"}, rule["alert"]
        assert rule["for"], rule["alert"]
        assert rule["annotations"]["runbook_url"].startswith("https://"), rule["alert"]
        assert rule["annotations"]["runbook"].startswith("docs/runbooks/"), rule["alert"]


def test_every_referenced_runbook_exists() -> None:
    for rule in _rules():
        path = ROOT / rule["annotations"]["runbook"]
        assert path.is_file(), f"{rule['alert']} points at {path}"


def test_scrape_config_covers_the_five_required_targets() -> None:
    document = yaml.safe_load((OBS / "prometheus.yml").read_text(encoding="utf-8"))
    jobs = {scrape["job_name"] for scrape in document["scrape_configs"]}
    assert {"api", "stream", "pushgateway", "postgres", "cadvisor"} <= jobs
    assert document["rule_files"]


def test_alertmanager_routes_to_the_notifier() -> None:
    document = yaml.safe_load((OBS / "alertmanager.yml").read_text(encoding="utf-8"))
    assert document["route"]["receiver"] == "bmip-notify"
    webhook = document["receivers"][0]["webhook_configs"][0]
    assert webhook["url"].endswith("/alert")
    assert webhook["send_resolved"] is True


def test_two_dashboards_are_provisioned() -> None:
    pipeline = json.loads(
        (OBS / "grafana" / "dashboards" / "pipeline.json").read_text(encoding="utf-8")
    )
    business = json.loads(
        (OBS / "grafana" / "dashboards" / "business.json").read_text(encoding="utf-8")
    )

    assert pipeline["uid"] == "bmip-pipeline"
    assert business["uid"] == "bmip-business"
    assert len(pipeline["panels"]) >= 5
    titles = {panel.get("title") for panel in business["panels"]}
    assert {
        "Harga close (1 jam)",
        "Volatilitas terealisasi (1 jam)",
        "Sentimen per jam",
        "Prediksi terbaru",
    } <= titles


def test_batch_rules_carry_the_run_id_template() -> None:
    batch = [r for r in _rules() if r["labels"]["alert_class"] == "job-failure"]
    assert len(batch) == 4
    for rule in batch:
        assert rule["labels"]["run_id"] == "{{ $labels.run_id }}"
