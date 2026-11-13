"""Shared PyIceberg plumbing for the W1-C silver and gold writers.

Kept separate from ``transform.silver`` so the W1-B market writer stays untouched;
T05 and T24 depend on that module's exact behaviour.
"""

from __future__ import annotations

from datetime import date

from pyiceberg.catalog import Catalog, load_catalog
from pyiceberg.exceptions import NamespaceAlreadyExistsError
from pyiceberg.expressions import EqualTo, Or
from pyiceberg.io import load_file_io

from bmip.common.config import Settings


def s3_properties(settings: Settings, service: str = "process") -> dict[str, str]:
    access_key, secret_key = settings.minio_credentials(service)
    return {
        "s3.endpoint": settings.minio_endpoint,
        "s3.access-key-id": access_key,
        "s3.secret-access-key": secret_key,
        "s3.region": settings.minio_region,
        "s3.path-style-access": "true",
        "s3.remote-signing-enabled": "false",
    }


def load_rest_catalog(settings: Settings, service: str = "process") -> Catalog:
    return load_catalog(
        "lakekeeper",
        type="rest",
        uri=f"{settings.lakekeeper_url.rstrip('/')}/catalog",
        warehouse=settings.lakekeeper_warehouse,
        **s3_properties(settings, service),
    )


def ensure_namespace(catalog: Catalog, namespace: str) -> None:
    try:
        catalog.create_namespace(namespace)
    except NamespaceAlreadyExistsError:
        return


def table_with_host_io(
    catalog: Catalog,
    settings: Settings,
    identifier: str,
    service: str = "process",
):
    table = catalog.load_table(identifier)
    table.io = load_file_io(s3_properties(settings, service), table.location())
    return table


def date_filter(dates: list[date]):
    unique = sorted(set(dates))
    if not unique:
        raise ValueError("date_filter needs at least one date")
    if len(unique) == 1:
        return EqualTo("event_date", unique[0])
    return Or(*[EqualTo("event_date", value) for value in unique])
