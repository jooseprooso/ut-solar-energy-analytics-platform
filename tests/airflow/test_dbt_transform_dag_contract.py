from pathlib import Path


def test_dbt_transform_dag_exists() -> None:
    dag_file = Path("airflow/dags/dbt_transform_dag.py")
    assert dag_file.exists(), "dbt transform DAG file must exist"


def test_dbt_transform_dag_contract() -> None:
    dag_file = Path("airflow/dags/dbt_transform_dag.py")
    source = dag_file.read_text(encoding="utf-8")

    assert 'dag_id="dbt_transform"' in source
    assert 'schedule="10 * * * *"' in source

    for task_id in ["validate_config", "dbt_deps", "dbt_run", "dbt_test"]:
        assert f'task_id="{task_id}"' in source

    assert "validate_config >> dbt_deps >> dbt_run >> dbt_test" in source


def test_dbt_transform_dag_validates_db_env() -> None:
    dag_file = Path("airflow/dags/dbt_transform_dag.py")
    source = dag_file.read_text(encoding="utf-8")

    required_vars = [
        "SUPABASE_DB_HOST",
        "SUPABASE_DB_PORT",
        "SUPABASE_DB_NAME",
        "SUPABASE_DB_USER",
        "SUPABASE_DB_PASSWORD",
    ]
    for var in required_vars:
        assert var in source, f"DAG must validate {var}"


def test_dbt_transform_dag_runs_after_ingestion() -> None:
    dag_file = Path("airflow/dags/dbt_transform_dag.py")
    source = dag_file.read_text(encoding="utf-8")

    assert "10 * * * *" in source, (
        "dbt DAG should run at :10 past the hour, after ingestion at :00"
    )
