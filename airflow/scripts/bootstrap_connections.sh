#!/usr/bin/env bash
set -euo pipefail

required=(
  SUPABASE_DB_HOST
  SUPABASE_DB_PORT
  SUPABASE_DB_NAME
  SUPABASE_DB_USER
  SUPABASE_DB_PASSWORD
)

for key in "${required[@]}"; do
  if [[ -z "${!key:-}" ]]; then
    echo "Missing required env var: ${key}"
    exit 1
  fi
done

airflow connections delete supabase_postgres >/dev/null 2>&1 || true
airflow connections add supabase_postgres \
  --conn-type postgres \
  --conn-host "${SUPABASE_DB_HOST}" \
  --conn-port "${SUPABASE_DB_PORT}" \
  --conn-login "${SUPABASE_DB_USER}" \
  --conn-password "${SUPABASE_DB_PASSWORD}" \
  --conn-schema "${SUPABASE_DB_NAME}"

airflow variables set vrm_api_token "${VRM_API_TOKEN:-}"
airflow variables set vrm_site_id "${VRM_SITE_ID:-}"
airflow variables set meteo_lat "${METEO_LAT:-}"
airflow variables set meteo_lon "${METEO_LON:-}"
airflow variables set meteo_timezone "${METEO_TIMEZONE:-UTC}"

echo "Airflow connection/variables bootstrap complete."
