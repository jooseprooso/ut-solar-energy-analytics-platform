from __future__ import annotations

import os
from datetime import date, datetime, timedelta

from airflow import DAG
from airflow.models.param import Param
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator

from orchestration.config import validate_required_env

REQUIRED_ENV_KEYS = [
    "VRM_API_TOKEN",
    "VRM_SITE_ID",
    "SUPABASE_DB_HOST",
    "SUPABASE_DB_PORT",
    "SUPABASE_DB_NAME",
    "SUPABASE_DB_USER",
    "SUPABASE_DB_PASSWORD",
]

_DEFAULT_END   = (date.today() - timedelta(days=1)).isoformat()
_DEFAULT_START = (date.today() - timedelta(days=182)).isoformat()


def _check_vrm_config() -> None:
    validate_required_env(REQUIRED_ENV_KEYS, env=os.environ)


default_args = {
    "owner": "solar-platform",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    dag_id="vrm_backfill",
    description="One-off backfill of historical VRM stats into bronze.vrm_raw (endpoint='stats').",
    start_date=datetime(2026, 1, 1),
    schedule=None,
    catchup=False,
    default_args=default_args,
    max_active_runs=1,
    tags=["solar", "ingest", "vrm", "backfill"],
    params={
        "start_date": Param(
            default=_DEFAULT_START,
            type="string",
            format="date",
            description="Backfill start date (inclusive), YYYY-MM-DD. Defaults to 6 months ago.",
        ),
        "end_date": Param(
            default=_DEFAULT_END,
            type="string",
            format="date",
            description="Backfill end date (inclusive), YYYY-MM-DD. Defaults to yesterday.",
        ),
    },
) as dag:
    validate_config = PythonOperator(
        task_id="validate_config",
        python_callable=_check_vrm_config,
    )

    run_backfill = BashOperator(
        task_id="run_backfill",
        bash_command="cd /opt/airflow/project && python src/ingest/vrm_backfill.py",
        env={
            "VRM_BACKFILL_START": "{{ params.start_date }}",
            "VRM_BACKFILL_END":   "{{ params.end_date }}",
        },
        append_env=True,
    )

    validate_config >> run_backfill
