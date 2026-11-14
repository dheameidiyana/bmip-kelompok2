import pytest
import yaml

from bmip.serving.registry import (
    REQUIRED_FIELDS,
    RegistryError,
    load_registry,
    parse_registry,
)


def test_registry_file_has_the_eleven_datasets():
    datasets = load_registry()
    assert len(datasets) == 11
    ids = {dataset.id for dataset in datasets}
    assert "gold.mart_market" in ids
    assert "serving.predictions" in ids
    assert len(ids) == len(datasets)


def test_every_dataset_has_the_metadata_the_catalogue_promises():
    for dataset in load_registry():
        payload = dataset.as_dict()
        for field in REQUIRED_FIELDS:
            assert payload.get(field) not in (None, ""), (dataset.id, field)
        assert dataset.layer in {"bronze", "silver", "gold", "serving"}
        assert dataset.kind in {"iceberg", "postgres"}
        assert dataset.retention_days >= 0


def test_only_bronze_social_is_marked_as_pii():
    flagged = {dataset.id for dataset in load_registry() if dataset.contains_pii}
    assert flagged == {"bronze.social_post_raw"}


def test_parse_registry_rejects_duplicates():
    entry = {
        "id": "gold.duplicate",
        "name": "x",
        "layer": "gold",
        "domain": "market",
        "kind": "iceberg",
        "location": "gold.duplicate",
        "description": "x",
        "owner": "anin",
        "classification": "internal",
        "retention_days": 90,
    }
    with pytest.raises(RegistryError):
        parse_registry({"datasets": [entry, dict(entry)]})


def test_parse_registry_rejects_missing_fields():
    with pytest.raises(RegistryError):
        parse_registry({"datasets": [{"id": "broken"}]})


def test_parse_registry_rejects_unknown_kind():
    entry = {
        "id": "gold.bad",
        "name": "x",
        "layer": "gold",
        "domain": "market",
        "kind": "csv",
        "location": "gold.bad",
        "description": "x",
        "owner": "anin",
        "classification": "internal",
        "retention_days": 90,
    }
    with pytest.raises(RegistryError):
        parse_registry({"datasets": [entry]})


def test_registry_yaml_is_valid_yaml():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    payload = yaml.safe_load((root / "catalog" / "datasets.yml").read_text(encoding="utf-8"))
    assert len(payload["datasets"]) == 11
