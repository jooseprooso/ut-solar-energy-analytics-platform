from pathlib import Path


def test_dag_file_exists() -> None:
    assert Path("airflow/dags/dag_vrm_log_ingest.py").exists()


def test_dag_id() -> None:
    source = Path("airflow/dags/dag_vrm_log_ingest.py").read_text()
    assert 'dag_id="vrm_log_ingest"' in source


def test_schedule_is_hourly() -> None:
    source = Path("airflow/dags/dag_vrm_log_ingest.py").read_text()
    assert 'schedule="@hourly"' in source


def test_catchup_disabled() -> None:
    source = Path("airflow/dags/dag_vrm_log_ingest.py").read_text()
    assert "catchup=False" in source


def test_backfill_params_present() -> None:
    source = Path("airflow/dags/dag_vrm_log_ingest.py").read_text()
    assert '"start_time"' in source
    assert '"end_time"' in source
    # params must allow null so the UI field can be left blank
    assert '["null", "string"]' in source


def test_all_task_ids_present() -> None:
    source = Path("airflow/dags/dag_vrm_log_ingest.py").read_text()
    for task_id in ["validate_config", "ingest_vrm_log"]:
        assert f'task_id="{task_id}"' in source, f"Missing task: {task_id}"


def test_no_dbt_tasks_in_dag() -> None:
    source = Path("airflow/dags/dag_vrm_log_ingest.py").read_text()
    assert "dbt_transform" not in source
    assert "dbt_test" not in source


def test_task_dependency_order() -> None:
    source = Path("airflow/dags/dag_vrm_log_ingest.py").read_text()
    assert "validate_config >> ingest_vrm_log" in source


def test_required_env_vars_validated() -> None:
    source = Path("airflow/dags/dag_vrm_log_ingest.py").read_text()
    for var in ["VRM_API_TOKEN", "VRM_SITE_ID", "SUPABASE_DB_HOST"]:
        assert var in source, f"DAG must reference env var {var}"
