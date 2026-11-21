id        : T-38
timestamp : 2026-11-21T10:09:50.932732+00:00
commit    : e7823c5
command   : python scripts/w2c_scan.py --rbac
result    : PASS
owner     : anin

| Percobaan | Method | Path | Status |
| --- | --- | --- | --- |
| no key -> 401 | GET | `/v1/auth/whoami` | 401 |
| viewer read -> 200 | GET | `/v1/auth/whoami` | 200 |
| viewer backfill -> 403 | POST | `/v1/admin/backfill` | 403 |
| operator backfill -> 202 | POST | `/v1/admin/backfill` | 202 |
| admin reload -> 200 | POST | `/v1/admin/catalog/reload` | 200 |

Audit rows (last 10):
| id | ts | actor | role | action | status | request_id |
| --- | --- | --- | --- | --- | --- | --- |
| 56 | 2026-11-21 10:07:39.652950+00:00 | demo-admin | admin | catalog-reload | 200 | req-4aa8582e808f4cd2 |
| 55 | 2026-11-21 10:07:39.233636+00:00 | demo-operator | operator | backfill | 202 | req-c397e47b86e245c1 |
| 54 | 2026-11-21 10:07:38.969926+00:00 | demo-viewer | viewer | backfill | 403 | req-05ca895f31e74791 |
| 53 | 2026-11-21 10:07:38.686259+00:00 | demo-viewer | viewer | read | 200 | req-deba6d34b7184941 |
| 52 | 2026-11-21 10:07:38.274175+00:00 | anonymous | anonymous | read | 401 | req-3eafd4348fb84e8c |
| 51 | 2026-11-21 10:07:38.098812+00:00 | demo-viewer | viewer | read | 200 | req-1c8d54036ed0433f |
| 50 | 2026-11-21 10:01:16.387746+00:00 | legacy-key | viewer | read | 200 | req-9f6961fa37ec44fd |
| 49 | 2026-11-21 10:01:16.306556+00:00 | legacy-key | viewer | read | 200 | req-453e6ec8e57d480a |
| 48 | 2026-11-21 10:01:16.270158+00:00 | legacy-key | viewer | read | 200 | req-4088c99b1c5f4223 |
| 47 | 2026-11-21 10:01:16.218874+00:00 | legacy-key | viewer | read | 200 | req-cb5eb99c86674986 |
