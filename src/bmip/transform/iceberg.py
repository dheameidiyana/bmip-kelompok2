"""Shared PyIceberg plumbing for the W1-C silver and gold writers.

Kept separate from ``transform.silver`` so the W1-B market writer stays untouched;
T05 and T24 depend on that module's exact behaviour.
"""

from __future__ import annotations

import time
from datetime import date

import requests
from pyiceberg.catalog import Catalog, load_catalog
from pyiceberg.exceptions import NamespaceAlreadyExistsError
from pyiceberg.expressions import EqualTo, Or
from pyiceberg.io.fsspec import FsspecFileIO

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


def _retry(call, attempts: int = 3):
    """Retry a catalog call when Docker's port proxy drops an idle socket."""
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            return call()
        except (requests.exceptions.ConnectionError, ConnectionResetError) as exc:
            last = exc
            time.sleep(0.5 * (attempt + 1))
    raise last if last else RuntimeError("catalog unavailable")


def load_rest_catalog(settings: Settings, service: str = "process") -> Catalog:
    # Docker Desktop's port proxy occasionally resets an idle keep-alive
    # connection, which surfaces as a ConnectionError on the very first
    # request. Retrying is enough; the catalog is stateless from here.
    return _retry(
        lambda: load_catalog(
            "lakekeeper",
            type="rest",
            uri=f"{settings.lakekeeper_url.rstrip('/')}/catalog",
            warehouse=settings.lakekeeper_warehouse,
            **s3_properties(settings, service),
        )
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
    table = _retry(lambda: catalog.load_table(identifier))
    # Build the file IO explicitly: Lakekeeper vends a REST signer and an
    # internal `minio:9000` endpoint, and ``load_file_io`` can return that
    # cached instance. On the host neither is reachable, so every read would
    # fail with a connection reset. A fresh FsspecFileIO with our own endpoint
    # and remote signing disabled is the only reliable path from outside the
    # compose network.
    table.io = FsspecFileIO(s3_properties(settings, service))
    return table


def date_filter(dates: list[date]):
    unique = sorted(set(dates))
    if not unique:
        raise ValueError("date_filter needs at least one date")
    if len(unique) == 1:
        return EqualTo("event_date", unique[0])
    return Or(*[EqualTo("event_date", value) for value in unique])
