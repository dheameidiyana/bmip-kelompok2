"""Static and unit checks for the W2-C governance/security layer.

These run without Docker: they prove the keys round-trip, the classification
heuristics behave, the lineage mapper collapses a dbt manifest correctly, and
the committed Traefik/Tailscale configuration contains the required controls.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from bmip.api.keys import new_key, parse_key, verify_secret
from bmip.catalog.classify import suggest_classification
from bmip.lineage.dbt import mart_edges
from bmip.lineage.emitter import registry_id
from bmip.lineage.events import build_run_event, dataset_ref

ROOT = Path(__file__).resolve().parents[2]


def test_api_key_roundtrip() -> None:
    plaintext, identity, hashed = new_key("operator", "tester", salt="pepper")
    parsed = parse_key(plaintext)
    assert parsed is not None
    key_id, secret = parsed
    assert key_id == identity.key_id
    assert verify_secret(secret, hashed, "pepper")
    assert not verify_secret(secret, hashed, "wrong-pepper")
    assert not verify_secret("not-the-secret", hashed, "pepper")


def test_hash_is_not_plaintext() -> None:
    plaintext, _, hashed = new_key("viewer", "tester")
    assert plaintext not in hashed
    assert hashed.startswith("$argon2")


def test_classification_heuristics() -> None:
    assert suggest_classification([{"name": "author_did"}]) == "pii"
    assert suggest_classification([{"name": "raw_payload"}]) == "restricted"
    assert suggest_classification([{"name": "close"}]) == "internal"
    assert suggest_classification([]) == "internal"


def test_registry_id_mapping() -> None:
    assert (
        registry_id("s3://lakehouse/warehouse", "gold.db/mart_market")
        == "gold.mart_market"
    )
    assert registry_id("postgres://serving", "market_hourly") == "serving.market_hourly"


def test_run_event_shape() -> None:
    event = build_run_event(
        event_type="START",
        job_name="dbt_build",
        run_id="run-1",
        inputs=[dataset_ref("silver", "market_trades")],
        outputs=[dataset_ref("gold", "mart_market")],
    )
    assert event["eventType"] == "START"
    assert event["run"]["runId"] == "run-1"
    assert event["inputs"][0]["name"] == "silver.db/market_trades"
    assert event["outputs"][0]["name"] == "gold.db/mart_market"
    json.dumps(event)


def test_dbt_manifest_collapses_to_marts(tmp_path: Path) -> None:
    manifest = {
        "nodes": {
            "model.pkg.stg": {
                "unique_id": "model.pkg.stg",
                "resource_type": "model",
                "schema": "staging",
                "name": "stg",
                "depends_on": {"nodes": ["source.pkg.raw.market_trades"]},
            },
            "model.pkg.mart_market": {
                "unique_id": "model.pkg.mart_market",
                "resource_type": "model",
                "schema": "gold",
                "name": "mart_market",
                "depends_on": {"nodes": ["model.pkg.stg"]},
                "columns": {"close": {"description": "Last price"}},
            },
        },
        "sources": {
            "source.pkg.raw.market_trades": {
                "schema": "silver",
                "name": "market_trades",
            }
        },
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    edges = mart_edges(path)
    assert len(edges) == 1
    assert edges[0]["model"] == "mart_market"
    assert edges[0]["inputs"][0]["name"] == "silver.db/market_trades"
    assert edges[0]["outputs"][0]["name"] == "gold.db/mart_market"


def test_traefik_has_tls_and_api_middlewares() -> None:
    static = yaml.safe_load(
        (ROOT / "deploy" / "traefik" / "traefik.yml").read_text(encoding="utf-8")
    )
    assert static["entryPoints"]["websecure"]["address"] == ":443"
    dynamic = yaml.safe_load(
        (ROOT / "deploy" / "traefik" / "dynamic" / "api.yml").read_text(
            encoding="utf-8"
        )
    )
    assert dynamic["tls"]["certificates"]
    routers = dynamic["http"]["routers"]
    for name in ("api-read-host", "api-write-host", "app-host", "catalog-host"):
        assert name in routers
    assert "api-retry" in routers["api-read-host"]["middlewares"]
    assert "api-rate-limit" in routers["api-read-host"]["middlewares"]
    assert "api-headers" in routers["api-read-host"]["middlewares"]
    assert "api-circuit" in routers["api-read-host"]["middlewares"]
    assert "api-retry" not in routers["api-write-host"]["middlewares"]
    assert "admin-auth" in routers["prometheus-host"]["middlewares"]
    headers = dynamic["http"]["middlewares"]["api-headers"]["headers"]
    assert headers["stsSeconds"] == 31536000
    services = yaml.safe_load(
        (ROOT / "deploy" / "traefik" / "dynamic" / "services.yaml").read_text(
            encoding="utf-8"
        )
    )
    servers = services["http"]["services"]["api"]["loadBalancer"]["servers"]
    assert [item["url"] for item in servers] == [
        "http://api:8000",
        "http://api-2:8000",
    ]


def test_tailscale_acl_is_deny_by_default() -> None:
    acl = json.loads(
        (ROOT / "deploy" / "tailscale" / "acl.json").read_text(encoding="utf-8")
    )
    assert set(acl["tagOwners"]) == {
        "tag:bmip-core",
        "tag:bmip-ui",
        "tag:bmip-user",
    }
    for rule in acl["acls"]:
        assert rule["action"] == "accept"
        assert "*" not in rule["src"]
        assert all("*" not in destination for destination in rule["dst"])


def test_compose_has_governance_and_catalog() -> None:
    compose = yaml.safe_load(
        (ROOT / "deploy" / "compose.base.yml").read_text(encoding="utf-8")
    )
    services = compose["services"]
    assert services["marquez"]["profiles"] == ["governance"]
    assert services["postgres-gov"]["profiles"] == ["governance"]
    assert services["catalog"]["image"] == "bmip/dashboard:dev"
    assert "postgres-gov-data" in compose["volumes"]
