"""Unit tests for C3-C ACL and governance helpers."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from bmip.catalog.governance import GovernanceError, _require_role, _validate_dataset

ROOT = Path(__file__).resolve().parents[2]


def _acl_module():
    path = ROOT / "scripts" / "c3c_acl.py"
    spec = importlib.util.spec_from_file_location("c3c_acl", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_acl_matrix_keeps_users_away_from_data_ports() -> None:
    module = _acl_module()
    payload = json.loads((ROOT / "deploy" / "tailscale" / "acl.json").read_text(encoding="utf-8"))
    matrix, problems = module.load_matrix(payload)
    assert not problems
    assert module._allowed(matrix, "tag:bmip-user", "tag:bmip-n1", 443)
    assert not module._allowed(matrix, "tag:bmip-user", "tag:bmip-n1", 5432)
    assert not module._allowed(matrix, "tag:bmip-user", "tag:bmip-n1", 8000)


def test_governance_requires_admin_and_complete_rows() -> None:
    with pytest.raises(GovernanceError):
        _require_role("viewer")
    _require_role("admin")
    payload = {
        "id": "serving.probe",
        "name": "probe",
        "layer": "serving",
        "domain": "ops",
        "kind": "postgres",
        "location": "serving.probe",
        "description": "probe",
        "owner": "vio",
        "classification": "internal",
        "retention_days": 1,
    }
    _validate_dataset(payload)
    payload["retention_days"] = 0
    with pytest.raises(GovernanceError):
        _validate_dataset(payload)
