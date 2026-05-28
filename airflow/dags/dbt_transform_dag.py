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
]


def _check_dbt_config() -> None:
    validate_required_env(REQUIRED_ENV_KEYS, env=os.environ)


default_args = {
    "owner": "solar-platform",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}


with DAG(
    dag_id="dbt_transform",
    description="Hourly dbt run to transform bronze data into silver/gold star schema",
    start_date=datetime(2026, 1, 1),
    schedule="10 * * * *",
    catchup=False,
    default_args=default_args,
    max_active_runs=1,
    tags=["solar", "transformation", "dbt"],
) as dag:
    validate_config = PythonOperator(
        task_id="validate_config",
        python_callable=_check_dbt_config,
    )

    dbt_deps = BashOperator(
        task_id="dbt_deps",
        bash_command="cd /opt/airflow/project && dbt deps --project-dir dbt --profiles-dir dbt",
    )

    dbt_run = BashOperator(
        task_id="dbt_run",
        bash_command="cd /opt/airflow/project && dbt run --project-dir dbt --profiles-dir dbt",
    )

    dbt_test = BashOperator(
        task_id="dbt_test",
        bash_command="cd /opt/airflow/project && dbt test --project-dir dbt --profiles-dir dbt",
    )

    validate_config >> dbt_deps >> dbt_run >> dbt_test
