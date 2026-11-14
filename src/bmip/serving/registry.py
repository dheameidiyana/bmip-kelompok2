"""Dataset registry: business metadata for /v1/dataset (W1-D).

The registry is a committed YAML file so the catalogue answers questions the
lakehouse cannot: who owns a table, how long it is retained, whether it holds
personal data, and what its freshness promise is. W2-C replaces the loader's
source with ``ops.dataset_registry``; the API contract stays identical.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from bmip.common.config import Settings
from bmip.common.logging import get_logger

log = get_logger(__name__)

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PATH = ROOT / "catalog" / "datasets.yml"

REQUIRED_FIELDS = (
    "id",
    "name",
    "layer",
    "domain",
    "kind",
    "location",
    "description",
    "owner",
    "classification",
    "retention_days",
)

LAYERS = ("bronze", "silver", "gold", "serving")
KINDS = ("iceberg", "postgres")


class RegistryError(ValueError):
    """Raised when the registry file is incomplete or inconsistent."""


@dataclass(frozen=True)
class Dataset:
    id: str
    name: str
    layer: str
    domain: str
    kind: str
    location: str
    description: str
    owner: str
    classification: str
    retention_days: int
    refresh_schedule: str = ""
    sla: str = ""
    license: str = ""
    contains_pii: bool = False
    tags: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "layer": self.layer,
            "domain": self.domain,
            "kind": self.kind,
            "location": self.location,
            "description": self.description,
            "owner": self.owner,
            "classification": self.classification,
            "retention_days": int(self.retention_days),
            "refresh_schedule": self.refresh_schedule,
            "sla": self.sla,
            "license": self.license,
            "contains_pii": bool(self.contains_pii),
            "tags": list(self.tags),
        }

    def row(self) -> dict[str, Any]:
        payload = self.as_dict()
        payload["tags"] = list(self.tags)
        return payload


def _path(settings: Settings | None = None) -> Path:
    if settings is not None and settings.dataset_registry_path:
        candidate = Path(settings.dataset_registry_path)
        if not candidate.is_absolute():
            candidate = ROOT / candidate
        if candidate.exists():
            return candidate
    return DEFAULT_PATH


def parse_registry(payload: dict[str, Any]) -> list[Dataset]:
    entries = payload.get("datasets")
    if not isinstance(entries, list) or not entries:
        raise RegistryError("registry must contain a non-empty 'datasets' list")
    datasets: list[Dataset] = []
    seen: set[str] = set()
    for raw in entries:
        missing = [name for name in REQUIRED_FIELDS if name not in raw]
        if missing:
            raise RegistryError(
                f"dataset {raw.get('id', '<unknown>')} is missing {missing}"
            )
        if raw["kind"] not in KINDS:
            raise RegistryError(f"{raw['id']}: kind must be one of {KINDS}")
        if raw["layer"] not in LAYERS:
            raise RegistryError(f"{raw['id']}: layer must be one of {LAYERS}")
        if raw["id"] in seen:
            raise RegistryError(f"duplicate dataset id: {raw['id']}")
        seen.add(raw["id"])
        datasets.append(
            Dataset(
                id=str(raw["id"]),
                name=str(raw["name"]),
                layer=str(raw["layer"]),
                domain=str(raw["domain"]),
                kind=str(raw["kind"]),
                location=str(raw["location"]),
                description=str(raw["description"]),
                owner=str(raw["owner"]),
                classification=str(raw["classification"]),
                retention_days=int(raw["retention_days"]),
                refresh_schedule=str(raw.get("refresh_schedule") or ""),
                sla=str(raw.get("sla") or ""),
                license=str(raw.get("license") or ""),
                contains_pii=bool(raw.get("contains_pii", False)),
                tags=tuple(str(tag) for tag in raw.get("tags") or ()),
            )
        )
    return datasets


def load_registry(settings: Settings | None = None) -> list[Dataset]:
    path = _path(settings)
    if not path.exists():
        raise RegistryError(f"registry file not found: {path}")
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return parse_registry(payload)


def find_registry_entry(settings: Settings | None, dataset_id: str) -> Dataset | None:
    for dataset in load_registry(settings):
        if dataset.id == dataset_id:
            return dataset
    return None


def iceberg_columns(settings: Settings, identifier: str) -> list[dict[str, Any]] | None:
    """Read the live Iceberg schema; None when the table is not reachable."""
    try:
        from bmip.transform.iceberg import load_rest_catalog

        catalog = load_rest_catalog(settings, "api")
        table = catalog.load_table(identifier)
        return [
            {
                "name": field.name,
                "type": str(field.field_type),
                "required": bool(field.required),
                "doc": field.doc,
                "field_id": field.field_id,
            }
            for field in table.schema().fields
        ]
    except Exception as exc:
        log.warning(
            "iceberg schema lookup failed",
            extra={"ctx_dataset": identifier, "ctx_error": f"{type(exc).__name__}: {exc}"},
        )
        return None


def postgres_columns(connection, location: str) -> list[dict[str, Any]]:
    schema, table = location.split(".", 1)
    rows = connection.execute(
        """
        SELECT column_name, data_type, is_nullable, ordinal_position
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        ORDER BY ordinal_position
        """,
        (schema, table),
    ).fetchall()
    return [
        {
            "name": row["column_name"],
            "type": row["data_type"],
            "required": row["is_nullable"] == "NO",
            "doc": None,
            "field_id": row["ordinal_position"],
        }
        for row in rows
    ]
