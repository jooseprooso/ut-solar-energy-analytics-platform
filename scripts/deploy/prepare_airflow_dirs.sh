#!/usr/bin/env bash
set -euo pipefail

AIRFLOW_UID="${AIRFLOW_UID:-50000}"
TARGET_DIRS=(
  "airflow/logs"
  "airflow/dags"
  "airflow/plugins"
  "dbt"
)

run_chown() {
  local target="$1"
  if [[ "${EUID}" -eq 0 ]]; then
    chown -R "${AIRFLOW_UID}:0" "${target}"
  elif command -v sudo >/dev/null 2>&1; then
    sudo chown -R "${AIRFLOW_UID}:0" "${target}"
  else
    echo "[prepare-airflow-dirs] Missing permissions for chown on ${target}."
    echo "[prepare-airflow-dirs] Re-run as root or with sudo available."
    exit 1
  fi
}

echo "[prepare-airflow-dirs] Ensuring required directories exist..."
mkdir -p "${TARGET_DIRS[@]}"

for dir in "${TARGET_DIRS[@]}"; do
  run_chown "${dir}"
  chmod -R u+rwX,g+rwX "${dir}"
done

echo "[prepare-airflow-dirs] Directory ownership and permissions are ready."
