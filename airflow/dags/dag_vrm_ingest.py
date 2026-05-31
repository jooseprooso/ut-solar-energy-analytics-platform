from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator
from src.ingest.vrm_ingest import main as vrm_main

default_args = {
    "owner": "solar-platform",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    dag_id="vrm_ingest",
    description="Hourly ingestion of Victron VRM diagnostics into bronze.vrm_raw",
    start_date=datetime(2026, 1, 1),
    schedule="@hourly",
    catchup=False,
    default_args=default_args,
    max_active_runs=1,
    tags=["solar", "ingest", "vrm"],
) as dag:
    ingest_vrm = PythonOperator(
        task_id="ingest_vrm",
        python_callable=vrm_main,
    )
