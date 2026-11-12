"""Bootstrap Lakekeeper: accept terms, create the warehouse, create namespaces."""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

LK = os.environ["LAKEKEEPER_URL_INTERNAL"].rstrip("/")
WAREHOUSE = os.environ["LAKEKEEPER_WAREHOUSE"]
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT_LAKEKEEPER", "http://host.docker.internal:9000")
REGION = os.getenv("MINIO_S3_REGION", "local")
ACCESS_KEY = os.environ["MINIO_ROOT_USER"]
SECRET_KEY = os.environ["MINIO_ROOT_PASSWORD"]


def request(method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{LK}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            body = response.read().decode("utf-8")
            return response.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(body) if body else {}
        except json.JSONDecodeError:
            parsed = {"raw": body}
        return exc.code, parsed


def wait_for_health(timeout: int = 120) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{LK}/health", timeout=3) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
        time.sleep(1)
    raise RuntimeError(f"Lakekeeper did not become healthy within {timeout}s")


def ensure_server_bootstrapped() -> None:
    code, info = request("GET", "/management/v1/info")
    if code != 200:
        raise RuntimeError(f"cannot read server info: HTTP {code} {info}")
    if info.get("bootstrapped"):
        print("server already bootstrapped")
        return

    code, body = request(
        "POST",
        "/management/v1/bootstrap",
        {"accept-terms-of-use": True, "is-operator": True},
    )
    if code not in (200, 201, 204, 409):
        raise RuntimeError(f"server bootstrap failed: HTTP {code} {body}")
    print(f"server bootstrapped (HTTP {code})")


def ensure_warehouse() -> str:
    code, listing = request("GET", "/management/v1/warehouse")
    if code == 200:
        for item in listing.get("warehouses", []):
            if item.get("name") == WAREHOUSE:
                print(f"warehouse {WAREHOUSE} already exists")
                return item["id"]

    payload = {
        "warehouse-name": WAREHOUSE,
        "project-id": "00000000-0000-0000-0000-000000000000",
        "storage-profile": {
            "type": "s3",
            "bucket": "lakehouse",
            "key-prefix": "warehouse",
            "assume-role-arn": None,
            "endpoint": MINIO_ENDPOINT,
            "sts-endpoint": MINIO_ENDPOINT,
            "region": REGION,
            "path-style-access": True,
            "flavor": "s3-compat",
            "sts-enabled": False,
        },
        "storage-credential": {
            "type": "s3",
            "credential-type": "access-key",
            "access-key-id": ACCESS_KEY,
            "secret-access-key": SECRET_KEY,
        },
    }
    code, body = request("POST", "/management/v1/warehouse", payload)
    overlap = body.get("error", {}).get("type") == "CreateWarehouseStorageProfileOverlap"
    if code not in (200, 201, 204, 409) and not (code == 400 and overlap):
        raise RuntimeError(f"warehouse create failed: HTTP {code} {body}")
    print(f"warehouse {WAREHOUSE} ready (HTTP {code})")

    code, listing = request("GET", "/management/v1/warehouse")
    if code != 200:
        raise RuntimeError(f"warehouse list failed: HTTP {code} {listing}")
    for item in listing.get("warehouses", []):
        if item.get("name") == WAREHOUSE:
            return item["id"]
    raise RuntimeError(f"warehouse {WAREHOUSE} missing from listing: {listing}")


def ensure_namespaces(warehouse_id: str) -> None:
    for namespace in ("bronze", "silver", "gold"):
        code, body = request(
            "POST",
            f"/catalog/v1/{warehouse_id}/namespaces",
            {"namespace": [namespace], "properties": {}},
        )
        if code not in (200, 201, 204, 409):
            raise RuntimeError(f"namespace {namespace} failed: HTTP {code} {body}")
        print(f"  namespace {namespace} ready (HTTP {code})")


def main() -> int:
    print(f"waiting for Lakekeeper at {LK}...")
    wait_for_health()
    ensure_server_bootstrapped()
    warehouse_id = ensure_warehouse()
    ensure_namespaces(warehouse_id)

    code, listing = request("GET", f"/catalog/v1/{warehouse_id}/namespaces")
    print(f"namespaces: {json.dumps(listing)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
