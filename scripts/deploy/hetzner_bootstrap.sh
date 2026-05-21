#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Please run as root (sudo)."
  exit 1
fi

echo "[bootstrap] Updating apt packages..."
apt-get update -y
apt-get upgrade -y

echo "[bootstrap] Installing core packages..."
apt-get install -y ca-certificates curl gnupg lsb-release git ufw

if ! command -v docker >/dev/null 2>&1; then
  echo "[bootstrap] Installing Docker..."
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  chmod a+r /etc/apt/keyrings/docker.gpg
  echo \
    "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
    https://download.docker.com/linux/ubuntu \
    $(. /etc/os-release && echo "${VERSION_CODENAME}") stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -y
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi

DEPLOY_USER="${SUDO_USER:-$USER}"
usermod -aG docker "${DEPLOY_USER}" || true

echo "[bootstrap] Configuring firewall..."
ufw allow OpenSSH
ufw allow 8080/tcp
ufw --force enable

echo "[bootstrap] Bootstrap complete."
echo "Next steps:"
echo "  1) Re-login as ${DEPLOY_USER} to refresh docker group"
echo "  2) Clone repo and create .env from .env.example"
echo "  3) Run: docker compose -f airflow/docker-compose.airflow.yml up airflow-init"
echo "  4) Run: docker compose -f airflow/docker-compose.airflow.yml up -d"
