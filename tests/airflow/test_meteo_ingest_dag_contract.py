from pathlib import Path


def test_meteo_ingest_dag_exists() -> None:
    dag_file = Path("airflow/dags/meteo_ingest_dag.py")
    assert dag_file.exists(), "Meteo ingest DAG file must exist"


def test_meteo_ingest_dag_contract() -> None:
    dag_file = Path("airflow/dags/meteo_ingest_dag.py")
    source = dag_file.read_text(encoding="utf-8")

    assert 'dag_id="meteo_ingest"' in source
    assert 'schedule="@hourly"' in source

    for task_id in ["validate_config", "ingest_meteo"]:
        assert f'task_id="{task_id}"' in source

    assert "validate_config >> ingest_meteo" in source


def test_meteo_ingest_dag_validates_all_required_env() -> None:
    dag_file = Path("airflow/dags/meteo_ingest_dag.py")
    source = dag_file.read_text(encoding="utf-8")

    required_vars = [
        "SUPABASE_DB_HOST",
        "SUPABASE_DB_PORT",
        "SUPABASE_DB_NAME",
        "SUPABASE_DB_USER",
        "SUPABASE_DB_PASSWORD",
        "METEO_LAT",
        "METEO_LON",
    ]
    for var in required_vars:
        assert var in source, f"DAG must validate {var}"


def test_meteo_ingest_dag_no_smoke_test_prefix() -> None:
    dag_file = Path("airflow/dags/meteo_ingest_dag.py")
    source = dag_file.read_text(encoding="utf-8")

    assert "BRONZE_TABLE_PREFIX" not in source, (
        "Production meteo DAG should not use smoke test table prefix"
    )
