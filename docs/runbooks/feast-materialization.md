# Feast materialization

1. Ensure `postgres-ml` is healthy and the `feast` database exists:
   `docker compose --env-file .env -f deploy/compose.base.yml -f deploy/compose.ml.yml up -d postgres-ml feast-db-init`
2. Build the offline sources:
   `python scripts/c3b_feast_build.py`
3. Apply and materialize:
   `python scripts/c3b_feast.py --start 2026-09-18T00:00:00Z --end 2026-11-17T00:00:00Z`
4. Verify parity:
   `python scripts/c3b_parity.py`
5. Verify the online read:
   `python scripts/c3b_feature_age.py --as-of 2026-11-17T00:00:00Z`

If `feast apply` stalls on `localhost`, use `127.0.0.1` for the host-side
online store. The API container uses `postgres-ml` instead.
