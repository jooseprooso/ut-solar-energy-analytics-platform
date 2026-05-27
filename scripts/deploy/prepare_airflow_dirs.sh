#!/usr/bin/env bash
set -euo pipefail

AIRFLOW_UID="${AIRFLOW_UID:-50000}"
TARGET_DIRS=(
  "airflow/logs"
  "airflow/dags"
  "airflow/plugins"
  "dbt"
)

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

for dir in "${TARGET_DIRS[@]}"; do
  run_privileged "chown -R ${AIRFLOW_UID}:0 \"${dir}\" && chmod -R u+rwX,g+rwX \"${dir}\""
done

echo "[prepare-airflow-dirs] Directory ownership and permissions are ready."
