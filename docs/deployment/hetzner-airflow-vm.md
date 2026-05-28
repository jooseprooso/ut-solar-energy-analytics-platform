# Hetzner VM Deployment for Airflow 3

This guide provisions a central VM for Airflow 3 and dbt orchestration.

## Recommended VM

- Provider: Hetzner Cloud (Cost-Optimized or shared cloud)
- Recommended size: 4 vCPU, 8 GB RAM, 80 GB SSD
- Minimum size: 2 vCPU, 4 GB RAM, 40 GB SSD
- OS: Ubuntu 24.04 LTS

## 1) Initial VM setup

On your local machine:

```bash
ssh root@<VM_IP>
```

On VM:

```bash
apt-get update -y
apt-get install -y git
git clone https://github.com/jooseprooso/ut-solar-energy-analytics-platform.git
cd ut-solar-energy-analytics-platform
bash scripts/deploy/hetzner_bootstrap.sh
```

Re-login after bootstrap to refresh Docker group membership.

## 2) Environment configuration

```bash
cd ut-solar-energy-analytics-platform
cp .env.example .env
```

Fill required secrets:
- Supabase connection settings
- VRM and Open-Meteo credentials/config
- Airflow admin values:
  - `AIRFLOW_ADMIN_USER`
  - `AIRFLOW_ADMIN_PASSWORD`
  - `AIRFLOW_ADMIN_EMAIL`
  - `AIRFLOW_BASE_URL` (nt `https://<tailscale-host>/airflow`)

## 3) Start Airflow stack

Run as the regular deploy user (not root):

```bash
bash scripts/deploy/prepare_airflow_dirs.sh
docker compose -f airflow/docker-compose.airflow.yml up airflow-init
docker compose -f airflow/docker-compose.airflow.yml up -d
```

## 4) Start reverse proxy stack

```bash
docker compose --env-file .env -f proxy/docker-compose.proxy.yml up -d
```

## 5) Configure Tailscale entrypoint

Suuna Tailscale HTTPS liiklus ainult reverse proxyle:

```bash
tailscale serve --bg http://127.0.0.1:8088
tailscale serve status
```

Airflow UI:

- `https://<tailscale-host>/airflow`

## 6) Verify scheduler health

```bash
docker compose -f airflow/docker-compose.airflow.yml ps
docker compose -f airflow/docker-compose.airflow.yml logs airflow-scheduler --tail=100
```

## 7) Load and run the main DAG

- Open Airflow UI
- Confirm DAG `pipeline_smoke_test` is present
- Trigger manual run once
- Verify task logs and Supabase outputs

## 8) Security hardening

- Restrict port `8080` to local binding (`127.0.0.1`) and keep external access through Tailscale only.
- Use strong admin password.
- Keep `.env` only on server and local machines (never commit).
- Keep Tailscale as the only public entrypoint.
