#!/usr/bin/env python3
"""Render the Traefik API load-balancer file from services.yaml."""

from __future__ import annotations

import json
import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "deploy" / "traefik" / "services.yaml"
TARGET = ROOT / "deploy" / "traefik" / "dynamic" / "services.yaml"


def _replicas(source: dict) -> list[str]:
    raw = os.getenv("API_REPLICAS", "")
    if raw.strip():
        values = [part.strip() for part in raw.split(",") if part.strip()]
    else:
        values = [str(item).strip() for item in source["api"]["replicas"] if str(item).strip()]
    if not values:
        raise SystemExit("API_REPLICAS is empty")
    if len(values) != len(set(values)):
        raise SystemExit("API_REPLICAS contains duplicates")
    for name in values:
        if "/" in name or ":" in name or not name:
            raise SystemExit(f"invalid replica name: {name!r}")
    return values


def main() -> int:
    source = yaml.safe_load(SOURCE.read_text(encoding="utf-8")) or {}
    health = source["api"]["health_check"]
    replicas = _replicas(source)
    primary = str(source["primary"]["server"])
    chaos = source["chaos"]
    payload = {
        "http": {
            "services": {
                "api": {
                    "loadBalancer": {
                        "strategy": "wrr",
                        "healthCheck": {
                            "path": health["path"],
                            "interval": health["interval"],
                            "timeout": health["timeout"],
                        },
                        "servers": [{"url": f"http://{name}:8000"} for name in replicas],
                    }
                },
                "api-primary": {
                    "loadBalancer": {
                        "servers": [{"url": f"http://{primary}"}],
                    }
                },
                "api-chaos": {
                    "loadBalancer": {
                        "healthCheck": {
                            "path": chaos["health_check"]["path"],
                            "interval": chaos["health_check"]["interval"],
                            "timeout": chaos["health_check"]["timeout"],
                        },
                        "servers": [{"url": f"http://{chaos['server']}"}],
                    }
                },
            }
        }
    }
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(
        yaml.safe_dump(payload, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
    print(json.dumps({"target": str(TARGET.relative_to(ROOT)), "replicas": replicas}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
