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
    "VRM_SITE_ID",
]


def _check_runtime_config() -> None:
    validate_required_env(REQUIRED_ENV_KEYS, env=os.environ)


default_args = {
    "owner": "solar-platform",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}


with DAG(
    dag_id="solar_analytics_backtest_daily",
    description="Walk-forward backtest + mart_forecast_accuracy_daily for Grafana KPIs",
    start_date=datetime(2026, 1, 1),
    schedule="@daily",
    catchup=False,
    default_args=default_args,
    max_active_runs=1,
    tags=["solar", "production", "forecast", "backtest"],
) as dag:
    validate_runtime_config = PythonOperator(
        task_id="validate_runtime_config",
        python_callable=_check_runtime_config,
    )

    forecast = BashOperator(
        task_id="forecast",
        bash_command="cd /opt/airflow/project && python src/forecast/run_forecast.py --mode backtest",
    )

    dbt_run_forecast_marts = BashOperator(
        task_id="dbt_run_forecast_marts",
        bash_command=(
            "cd /opt/airflow/project && "
            "dbt run --project-dir dbt --profiles-dir dbt "
            "--select mart_forecast_accuracy_daily"
        ),
    )

    validate_runtime_config >> forecast >> dbt_run_forecast_marts
