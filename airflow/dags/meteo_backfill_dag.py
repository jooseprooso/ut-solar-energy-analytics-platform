from __future__ import annotations

import os
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator

from orchestration.config import validate_required_env

REQUIRED_ENV_KEYS = [
    "SUPABASE_DB_HOST",
    "SUPABASE_DB_PORT",
    "SUPABASE_DB_NAME",
    "SUPABASE_DB_USER",
    "SUPABASE_DB_PASSWORD",
    "METEO_LAT",
    "METEO_LON",
]


def _check_meteo_config() -> None:
    validate_required_env(REQUIRED_ENV_KEYS, env=os.environ)


default_args = {
    "owner": "solar-platform",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}


with DAG(
    dag_id="meteo_backfill",
    description="One-off backfill of 6 months of Open-Meteo archive data into bronze layer",
    start_date=datetime(2026, 1, 1),
    schedule=None,
    catchup=False,
    default_args=default_args,
    max_active_runs=1,
    tags=["solar", "ingestion", "meteo", "backfill"],
) as dag:
    validate_config = PythonOperator(
        task_id="validate_config",
        python_callable=_check_meteo_config,
    )

    run_backfill = BashOperator(
        task_id="run_backfill",
        bash_command="cd /opt/airflow/project && python src/ingest/meteo_backfill.py",
    )

    validate_config >> run_backfill
