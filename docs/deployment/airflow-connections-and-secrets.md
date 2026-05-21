# Airflow Connections and Secrets

This project uses Airflow as the primary orchestrator. Secrets must be provided via environment variables and then registered as Airflow Connections/Variables.

## Required environment variables

### Supabase/Postgres
- `SUPABASE_DB_HOST`
- `SUPABASE_DB_PORT`
- `SUPABASE_DB_NAME`
- `SUPABASE_DB_USER`
- `SUPABASE_DB_PASSWORD`

### Victron VRM
- `VRM_API_TOKEN`
- `VRM_SITE_ID`

### Open-Meteo
- `METEO_LAT`
- `METEO_LON`
- `METEO_TIMEZONE`

### Airflow admin
- `AIRFLOW_ADMIN_USER`
- `AIRFLOW_ADMIN_PASSWORD`
- `AIRFLOW_ADMIN_EMAIL`

## Bootstrap command

After Airflow services are up:

```bash
docker compose -f airflow/docker-compose.airflow.yml run --rm airflow-apiserver \
  bash /opt/airflow/project/airflow/scripts/bootstrap_connections.sh
```

## Created Airflow resources

### Connection
- `supabase_postgres` (Postgres connection for warehouse access)

### Variables
- `vrm_api_token`
- `vrm_site_id`
- `meteo_lat`
- `meteo_lon`
- `meteo_timezone`

## Security rules

- Never commit `.env`.
- Never hardcode secrets in DAG files.
- Rotate DB/API secrets when team membership changes.
