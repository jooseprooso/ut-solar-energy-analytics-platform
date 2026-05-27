#!/usr/bin/env bash
set -euo pipefail

AIRFLOW_UID="${AIRFLOW_UID:-50000}"
LOG_DIR="airflow/logs"
PROJECT_DIRS=(
  "airflow/dags"
  "airflow/plugins"
)
DBT_DIR="dbt"
TARGET_DIRS=(
  "airflow/logs"
  "airflow/dags"
  "airflow/plugins"
  "dbt"
)

PROJECT_OWNER_UID="$(id -u)"
PROJECT_OWNER_GID="$(id -g)"

run_privileged() {
  local command_str="$1"
  if [[ "${EUID}" -eq 0 ]]; then
    bash -lc "${command_str}"
    return
  fi

  # Use passwordless sudo when available in non-interactive deploy sessions.
  if command -v sudo >/dev/null 2>&1 && sudo -n true >/dev/null 2>&1; then
    sudo bash -lc "${command_str}"
    return
  fi

  # Fallback: use Docker (root in container) when sudo is unavailable.
  if command -v docker >/dev/null 2>&1; then
    docker run --rm -u 0:0 -v "${PWD}:/workspace" --workdir /workspace alpine:3.20 \
      sh -ceu "${command_str}"
    return
  fi

  echo "[prepare-airflow-dirs] Missing privileges to update mount permissions."
  echo "[prepare-airflow-dirs] Need one of: root, passwordless sudo, or docker access."
  exit 1
}

echo "[prepare-airflow-dirs] Ensuring required directories exist..."
mkdir -p "${TARGET_DIRS[@]}"

run_privileged "chown -R ${AIRFLOW_UID}:0 \"${LOG_DIR}\" && chmod -R u+rwX,g+rwX \"${LOG_DIR}\""

for dir in "${PROJECT_DIRS[@]}"; do
  run_privileged "chown -R ${PROJECT_OWNER_UID}:${PROJECT_OWNER_GID} \"${dir}\" && chmod -R u+rwX \"${dir}\""
done

# dbt needs to stay git-writable by deploy user and runtime-writable by Airflow (gid 0).
run_privileged "chown -R ${PROJECT_OWNER_UID}:0 \"${DBT_DIR}\" && chmod -R u+rwX,g+rwX \"${DBT_DIR}\""

echo "[prepare-airflow-dirs] Directory ownership and permissions are ready."
echo "[prepare-airflow-dirs] ${LOG_DIR} -> ${AIRFLOW_UID}:0 (Airflow runtime writes logs)."
echo "[prepare-airflow-dirs] airflow/dags, airflow/plugins -> ${PROJECT_OWNER_UID}:${PROJECT_OWNER_GID} (git-friendly)."
echo "[prepare-airflow-dirs] ${DBT_DIR} -> ${PROJECT_OWNER_UID}:0 with g+rwX (git + Airflow dbt runtime)."
