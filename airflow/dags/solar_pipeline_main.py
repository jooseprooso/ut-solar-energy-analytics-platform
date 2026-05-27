from __future__ import annotations

import os
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator

from orchestration.config import validate_required_env


def _check_runtime_config() -> None:
    required_keys = [
        "SUPABASE_DB_HOST",
        "SUPABASE_DB_PORT",
        "SUPABASE_DB_NAME",
        "SUPABASE_DB_USER",
        "SUPABASE_DB_PASSWORD",
    ]
    validate_required_env(required_keys, env=os.environ)


default_args = {
    "owner": "solar-platform",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}


with DAG(
    dag_id="pipeline_smoke_test",
    description="Main Airflow orchestrator for ingestion, dbt, and forecasting",
    start_date=datetime(2026, 1, 1),
    schedule="@hourly",
    catchup=False,
    default_args=default_args,
    max_active_runs=1,
    tags=["solar", "production"],
) as dag:
    validate_runtime_config = PythonOperator(
        task_id="validate_runtime_config",
        python_callable=_check_runtime_config,
    )

    ingest_meteo = BashOperator(
        task_id="ingest_meteo",
        bash_command="cd /opt/airflow/project && python src/ingest/meteo_ingest.py",
    )

    dbt_deps = BashOperator(
        task_id="dbt_deps",
        bash_command=(
            "cd /opt/airflow/project && "
            "dbt deps --project-dir dbt --profiles-dir dbt"
        ),
    )

    dbt_run = BashOperator(
        task_id="dbt_run",
        bash_command=(
            "cd /opt/airflow/project && "
            "dbt run --project-dir dbt --profiles-dir dbt"
        ),
    )

    dbt_test = BashOperator(
        task_id="dbt_test",
        bash_command=(
            "cd /opt/airflow/project && "
            "dbt test --project-dir dbt --profiles-dir dbt"
        ),
    )

    forecast = BashOperator(
        task_id="forecast",
        bash_command="cd /opt/airflow/project && python src/forecast/run_forecast.py",
    )

    validate_runtime_config >> ingest_meteo >> dbt_deps >> dbt_run >> dbt_test >> forecast
