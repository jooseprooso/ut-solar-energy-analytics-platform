# Airflow Operations Runbook

## Standard operational commands

From repo root:

```bash
docker compose -f airflow/docker-compose.airflow.yml ps
docker compose -f airflow/docker-compose.airflow.yml logs airflow-scheduler --tail=200
docker compose -f airflow/docker-compose.airflow.yml logs airflow-apiserver --tail=200
```

## Restart workflow services

```bash
docker compose -f airflow/docker-compose.airflow.yml restart airflow-scheduler airflow-apiserver airflow-dag-processor
```

## Full stack restart

```bash
docker compose -f airflow/docker-compose.airflow.yml down
docker compose -f airflow/docker-compose.airflow.yml up -d
```

## Common failure scenarios

### `dbt debug` authentication failure

1. Validate Supabase credentials in `.env`.
2. Confirm pooler host and port are used.
3. Re-run task manually from Airflow UI.

### DAG not visible in Airflow UI

1. Check DAG file exists at `airflow/dags/solar_pipeline_main.py`.
2. Check scheduler logs for parse errors.
3. Restart scheduler and dag-processor.

### Task retries exhausted

1. Open task logs in Airflow UI.
2. Identify failing external dependency (API/database).
3. Fix underlying issue and clear task for rerun.

## Disaster recovery basics

- Keep repo as source of truth for DAG and orchestration code.
- Backup `.env` and Airflow metadata DB snapshots.
- Recreate stack on new VM with:
  - bootstrap script
  - repo clone
  - restored `.env`
  - `airflow-init` + stack startup
