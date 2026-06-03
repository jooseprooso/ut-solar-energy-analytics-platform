from __future__ import annotations

import os
from datetime import datetime, timedelta

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


def _check_config() -> None:
    validate_required_env(REQUIRED_ENV_KEYS, env=os.environ)


default_args = {
    "owner": "solar-platform",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    dag_id="vrm_log_ingest",
    description="Hourly VRM log export ingest → bronze.vrm_log_raw",
    start_date=datetime(2026, 1, 1),
    schedule="@hourly",
    catchup=False,
    default_args=default_args,
    max_active_runs=1,
    tags=["solar", "ingest", "vrm"],
    params={
        "start_time": Param(
            default=None,
            type=["null", "string"],
            description=(
                "Override start time (UTC, ISO 8601: YYYY-MM-DDTHH:MM:SS). "
                "Leave empty to use last completed hour."
            ),
        ),
        "end_time": Param(
            default=None,
            type=["null", "string"],
            description=(
                "Override end time (UTC, ISO 8601: YYYY-MM-DDTHH:MM:SS). "
                "Leave empty to use current hour boundary."
            ),
        ),
        "chunk_days": Param(
            default=1,
            type="integer",
            description=(
                "Days of data per API request. "
                "Max safe value is 7 — larger values trigger HTTP 202 async mode "
                "and will fail. Use 7 for long backfills, 1 for hourly runs."
            ),
        ),
    },
) as dag:
    validate_config = PythonOperator(
        task_id="validate_config",
        python_callable=_check_config,
    )

    ingest_vrm_log = BashOperator(
        task_id="ingest_vrm_log",
        bash_command="cd /opt/airflow/project && python src/ingest/vrm_log_ingest.py",
        env={
            "VRM_LOG_START":      "{{ params.start_time or '' }}",
            "VRM_LOG_END":        "{{ params.end_time or '' }}",
            "VRM_LOG_CHUNK_DAYS": "{{ params.chunk_days }}",
        },
        append_env=True,
    )

    validate_config >> ingest_vrm_log
