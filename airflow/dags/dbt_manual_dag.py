from __future__ import annotations

import os
from datetime import datetime, timedelta

from airflow import DAG
from airflow.models.param import Param
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
    "retries": 0,
    "retry_delay": timedelta(minutes=1),
}

with DAG(
    dag_id="dbt_manual",
    description="Manually trigger any dbt command (run, test, build, etc.)",
    start_date=datetime(2026, 1, 1),
    schedule=None,
    catchup=False,
    default_args=default_args,
    max_active_runs=1,
    tags=["solar", "transformation", "dbt", "manual"],
    params={
        "dbt_command": Param(
            default="run",
            type="string",
            description="dbt command to execute (e.g. 'run --full-refresh --select fct_meteo_hourly')",
        ),
    },
) as dag:
    validate_config = PythonOperator(
        task_id="validate_config",
        python_callable=_check_dbt_config,
    )

    dbt_deps = BashOperator(
        task_id="dbt_deps",
        bash_command="cd /opt/airflow/project && dbt deps --project-dir dbt --profiles-dir dbt",
    )

    dbt_command = BashOperator(
        task_id="dbt_command",
        bash_command="cd /opt/airflow/project && dbt {{ params.dbt_command }} --project-dir dbt --profiles-dir dbt",
    )

    validate_config >> dbt_deps >> dbt_command
