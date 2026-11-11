#!/bin/sh
set -eu

: "${MINIO_ROOT_USER:?MINIO_ROOT_USER is required}"
: "${MINIO_ROOT_PASSWORD:?MINIO_ROOT_PASSWORD is required}"

MC_CONFIG_DIR="${MC_CONFIG_DIR:-/tmp/mc}"
export MC_CONFIG_DIR
export MC_HOST_local="http://${MINIO_ROOT_USER}:${MINIO_ROOT_PASSWORD}@minio:9000"
MC="mc --quiet"

echo "waiting for MinIO..."
until $MC admin info local >/dev/null 2>&1; do
    sleep 1
done

for bucket in lakehouse artifacts backups docs quarantine; do
    $MC mb --ignore-existing "local/${bucket}" >/dev/null
done
$MC version enable local/lakehouse >/dev/null 2>&1 || true

create_user() {
    user_key="$1"
    user_secret="$2"
    policy_name="$3"
    policy_file="$4"

    $MC admin user add local "$user_key" "$user_secret" >/dev/null 2>&1 || true
    $MC admin user enable local "$user_key" >/dev/null 2>&1 || true

    $MC admin policy detach local "$policy_name" --user "$user_key" >/dev/null 2>&1 || true
    $MC admin policy remove local "$policy_name" >/dev/null 2>&1 || true
    $MC admin policy create local "$policy_name" "$policy_file" >/dev/null
    $MC admin policy attach local "$policy_name" --user "$user_key" >/dev/null
    echo "  user ${user_key} -> ${policy_name}"
}

create_user "$MINIO_SVC_INGEST_ACCESS_KEY" "$MINIO_SVC_INGEST_SECRET_KEY" "bmip-ingest" "/policies/ingest.json"
create_user "$MINIO_SVC_PROCESS_ACCESS_KEY" "$MINIO_SVC_PROCESS_SECRET_KEY" "bmip-process" "/policies/process.json"
create_user "$MINIO_SVC_DBT_ACCESS_KEY" "$MINIO_SVC_DBT_SECRET_KEY" "bmip-dbt" "/policies/dbt.json"
create_user "$MINIO_SVC_ML_ACCESS_KEY" "$MINIO_SVC_ML_SECRET_KEY" "bmip-ml" "/policies/ml.json"
create_user "$MINIO_SVC_API_ACCESS_KEY" "$MINIO_SVC_API_SECRET_KEY" "bmip-api" "/policies/api.json"
create_user "$MINIO_SVC_BACKUP_ACCESS_KEY" "$MINIO_SVC_BACKUP_SECRET_KEY" "bmip-backup" "/policies/backup.json"
create_user "$MINIO_SVC_DOCS_ACCESS_KEY" "$MINIO_SVC_DOCS_SECRET_KEY" "bmip-docs" "/policies/docs.json"

echo "minio bootstrap complete"
$MC ls local
