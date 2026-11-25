from __future__ import annotations

from bmip.api.keys import new_key, resolve_key


class _Cursor:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _ReadOnlyConnection:
    def __init__(self, row):
        self._row = row
        self.executed: list[str] = []

    def execute(self, statement, params=None):
        self.executed.append(statement)
        if statement.strip().lower().startswith("update"):
            raise RuntimeError("read-only role")
        return _Cursor(self._row)

    def commit(self):
        raise AssertionError("commit must not be reached after a failed update")

    def rollback(self):
        pass


def test_resolve_key_survives_read_only_telemetry_write():
    plaintext, identity, key_hash = new_key("viewer", "demo", key_id="abc12345")
    row = {
        "key_id": identity.key_id,
        "key_hash": key_hash,
        "role": identity.role,
        "owner": identity.owner,
    }
    connection = _ReadOnlyConnection(row)
    resolved = resolve_key(connection, plaintext)
    assert resolved == identity
    assert any(statement.strip().lower().startswith("update") for statement in connection.executed)
